"""Exact latest PORT-001 schema validation."""

from __future__ import annotations

from sqlalchemy import inspect

from app.platform.migration_errors import MigrationSchemaError


def validate_portfolio_schema(connection) -> None:
    inspector = inspect(connection)
    expected_columns = {
        "parties": (
            {"id", "party_kind", "display_name", "email", "phone", "created_at", "updated_at", "archived_at"},
            {"email", "phone", "archived_at"},
        ),
        "properties": (
            {"id", "display_name", "address_line_1", "address_line_2", "city", "region", "postal_code", "country_code", "notes", "status", "created_at", "updated_at", "archived_at"},
            {"address_line_2", "region", "postal_code", "notes", "archived_at"},
        ),
        "property_ownerships": (
            {"id", "property_id", "owner_kind", "party_id", "starts_on", "ends_on", "created_at", "ended_at"},
            {"party_id", "ends_on", "ended_at"},
        ),
    }
    _validate_columns(inspector, expected_columns)
    _validate_indexes(connection, inspector, expected_columns)
    _validate_foreign_keys(inspector)
    _validate_checks(inspector, expected_columns)


def _validate_columns(inspector, expected_columns) -> None:
    for table, (names, nullable) in expected_columns.items():
        if not inspector.has_table(table):
            raise MigrationSchemaError(f"{table} schema is missing or incompatible with PORT-001.")
        columns = inspector.get_columns(table)
        if {column["name"] for column in columns} != names:
            raise MigrationSchemaError(f"{table} columns are incompatible with PORT-001.")
        if {column["name"] for column in columns if column["primary_key"]} != {"id"}:
            raise MigrationSchemaError(f"{table} primary key is incompatible with PORT-001.")
        for column in columns:
            if not column["primary_key"] and bool(column["nullable"]) != (column["name"] in nullable):
                raise MigrationSchemaError(f"{table} nullability is incompatible with PORT-001.")
            if "TEXT" not in str(column["type"]).upper() and "CHAR" not in str(column["type"]).upper():
                raise MigrationSchemaError(f"{table} column types are incompatible with PORT-001.")


def _validate_indexes(connection, inspector, expected_columns) -> None:
    indexes = {
        table: {
            item["name"]: (tuple(item["column_names"]), bool(item.get("unique")))
            for item in inspector.get_indexes(table)
        }
        for table in expected_columns
    }
    required = {
        "parties": {
            "parties_active_name": (("archived_at", "display_name"), False),
        },
        "properties": {
            "properties_status_name": (("status", "display_name"), False),
        },
        "property_ownerships": {
            "property_ownerships_property_active": (("property_id", "ends_on"), False),
            "property_ownerships_party_active": (("party_id", "ends_on"), False),
            "property_ownerships_one_active_operator": (("property_id",), True),
            "property_ownerships_one_active_client": (("property_id", "party_id"), True),
        },
    }
    if indexes != required:
        raise MigrationSchemaError("PORT-001 indexes are incompatible.")

    rows = connection.exec_driver_sql(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type = 'index' AND name IN "
        "('property_ownerships_one_active_operator', "
        "'property_ownerships_one_active_client')"
    ).all()
    predicates = {
        name: _normalise_sql(sql.partition("WHERE")[2])
        for name, sql in rows
        if sql is not None and "WHERE" in sql.upper()
    }
    expected_predicates = {
        "property_ownerships_one_active_operator": "owner_kind='local_operator'andends_onisnull",
        "property_ownerships_one_active_client": "owner_kind='client_owner'andends_onisnull",
    }
    if predicates != expected_predicates:
        raise MigrationSchemaError("PORT-001 partial-index predicates are incompatible.")


def _validate_foreign_keys(inspector) -> None:
    expected = {
        (("property_id",), "properties", ("id",)),
        (("party_id",), "parties", ("id",)),
    }
    found = {
        (tuple(key["constrained_columns"]), key["referred_table"], tuple(key["referred_columns"]))
        for key in inspector.get_foreign_keys("property_ownerships")
    }
    if found != expected:
        raise MigrationSchemaError("PORT-001 foreign keys are incompatible.")


def _validate_checks(inspector, expected_columns) -> None:
    expected = {
        "parties": {
            "party_kindin('individual','organization')",
            "length(trim(display_name))>0",
        },
        "properties": {
            "statusin('active','archived')",
            "length(trim(display_name))>0",
            "length(trim(address_line_1))>0",
            "length(trim(city))>0",
            "length(trim(country_code))=2",
        },
        "property_ownerships": {
            "owner_kindin('local_operator','client_owner')",
            "(owner_kind='local_operator'andparty_idisnull)or(owner_kind='client_owner'andparty_idisnotnull)",
            "ends_onisnullorends_on>=starts_on",
        },
    }
    found = {
        table: {
            _normalise_sql(item.get("sqltext") or "")
            for item in inspector.get_check_constraints(table)
        }
        for table in expected_columns
    }
    if found != expected:
        raise MigrationSchemaError("PORT-001 checks are incompatible.")


def _normalise_sql(value: str) -> str:
    return "".join(value.lower().split())

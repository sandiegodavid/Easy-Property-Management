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
            {"id", "display_name", "address_line_1", "address_line_2", "city", "region", "postal_code", "country_code", "notes", "status", "created_at", "updated_at", "archived_at", "property_type", "inventory_layout"},
            {"address_line_2", "region", "postal_code", "notes", "archived_at"},
        ),
        "property_ownerships": (
            {"id", "property_id", "owner_kind", "party_id", "starts_on", "ends_on", "created_at", "ended_at"},
            {"party_id", "ends_on", "ended_at"},
        ),
        "spaces": (
            {"id", "property_id", "space_kind", "display_name", "normalized_name", "suite_or_floor", "notes", "status", "created_at", "updated_at", "archived_at", "archived_by_property_operation_id"},
            {"suite_or_floor", "notes", "archived_at", "archived_by_property_operation_id"},
        ),
        "space_occupancy_periods": (
            {"id", "space_id", "occupancy_status", "starts_on", "ends_on", "record_state", "superseded_by_id", "source_kind", "source_id", "note", "created_at", "ended_at", "cancelled_at"},
            {"ends_on", "superseded_by_id", "source_id", "note", "ended_at", "cancelled_at"},
        ),
        "space_availability": (
            {"space_id", "availability_status", "available_on", "source_kind", "source_id", "note", "updated_at"},
            {"available_on", "source_id", "note"},
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
        expected_primary_key = {"space_id"} if table == "space_availability" else {"id"}
        if {column["name"] for column in columns if column["primary_key"]} != expected_primary_key:
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
        "spaces": {
            "spaces_property_status_name": (("property_id", "status", "display_name"), False),
            "spaces_one_active_name": (("property_id", "normalized_name"), True),
        },
        "space_occupancy_periods": {
            "space_occupancy_periods_space_dates": (("space_id", "starts_on", "ends_on"), False),
            "space_occupancy_periods_one_open": (("space_id",), True),
        },
        "space_availability": {
            "space_availability_status_date": (("availability_status", "available_on"), False),
        },
    }
    if indexes != required:
        raise MigrationSchemaError("PORT-001 indexes are incompatible.")

    rows = connection.exec_driver_sql(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type = 'index' AND name IN "
        "('property_ownerships_one_active_operator', "
        "'property_ownerships_one_active_client', 'spaces_one_active_name', 'space_occupancy_periods_one_open')"
    ).all()
    predicates = {
        name: _normalise_sql(sql.partition("WHERE")[2])
        for name, sql in rows
        if sql is not None and "WHERE" in sql.upper()
    }
    expected_predicates = {
        "property_ownerships_one_active_operator": "owner_kind='local_operator'andends_onisnull",
        "property_ownerships_one_active_client": "owner_kind='client_owner'andends_onisnull",
        "spaces_one_active_name": "status='active'",
        "space_occupancy_periods_one_open": "record_state='valid'andends_onisnull",
    }
    if predicates != expected_predicates:
        raise MigrationSchemaError("PORT-001 partial-index predicates are incompatible.")


def _validate_foreign_keys(inspector) -> None:
    expected = {
        "property_ownerships": {
            (("property_id",), "properties", ("id",)),
            (("party_id",), "parties", ("id",)),
        },
        "spaces": {
            (("property_id",), "properties", ("id",)),
        },
        "space_occupancy_periods": {
            (("space_id",), "spaces", ("id",)),
            (("superseded_by_id",), "space_occupancy_periods", ("id",)),
        },
        "space_availability": {
            (("space_id",), "spaces", ("id",)),
        },
    }
    found = {
        table: {
            (tuple(key["constrained_columns"]), key["referred_table"], tuple(key["referred_columns"]))
            for key in inspector.get_foreign_keys(table)
        }
        for table in expected
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
            "property_typein('single_family_home','condo','townhome','office')",
            "inventory_layoutin('single_space','whole_office','office_suites')",
        },
        "property_ownerships": {
            "owner_kindin('local_operator','client_owner')",
            "(owner_kind='local_operator'andparty_idisnull)or(owner_kind='client_owner'andparty_idisnotnull)",
            "ends_onisnullorends_on>=starts_on",
        },
        "spaces": {
            "space_kindin('whole_home','whole_office','office_suite')",
            "statusin('active','archived')",
            "length(trim(display_name))>0",
        },
        "space_occupancy_periods": {
            "occupancy_statusin('occupied','vacant','unknown')",
            "record_statein('valid','cancelled','superseded')",
            "ends_onisnullorends_on>starts_on",
            "(source_kind='manual'andsource_idisnull)or(source_kind='lease'andsource_idisnotnull)",
        },
        "space_availability": {
            "availability_statusin('available_now','available_on','not_available','unknown')",
            "(availability_status='available_on'andavailable_onisnotnull)or(availability_status!='available_on'andavailable_onisnull)",
            "(source_kind='manual'andsource_idisnull)or(source_kindin('listing','lease')andsource_idisnotnull)",
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

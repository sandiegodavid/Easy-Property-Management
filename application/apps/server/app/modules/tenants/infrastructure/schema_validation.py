"""Exact TEN-001 schema validation."""

import warnings

from sqlalchemy import inspect
from sqlalchemy.exc import SAWarning

from app.platform.migration_errors import MigrationSchemaError


def validate_tenant_schema(connection) -> None:
    inspector = inspect(connection)
    expected = {"tenant_profiles": {"party_id", "preferred_contact_method_id", "do_not_contact", "notes", "created_at", "updated_at", "archived_at"}, "party_contact_methods": {"id", "party_id", "method_kind", "display_value", "normalized_value", "extension", "label", "status", "created_at", "updated_at", "archived_at"}}
    nullable = {
        "tenant_profiles": {"preferred_contact_method_id", "notes", "archived_at"},
        "party_contact_methods": {"extension", "label", "archived_at"},
    }
    for table, columns in expected.items():
        if not inspector.has_table(table):
            raise MigrationSchemaError("TEN-001 schema is incompatible.")
        reflected = inspector.get_columns(table)
        if {item["name"] for item in reflected} != columns:
            raise MigrationSchemaError("TEN-001 schema is incompatible.")
        primary = {"party_id"} if table == "tenant_profiles" else {"id"}
        if {item["name"] for item in reflected if item["primary_key"]} != primary:
            raise MigrationSchemaError("TEN-001 schema is incompatible.")
        for item in reflected:
            if not item["primary_key"] and bool(item["nullable"]) != (item["name"] in nullable[table]):
                raise MigrationSchemaError("TEN-001 schema is incompatible.")
            if item["name"] == "do_not_contact":
                if "INT" not in str(item["type"]).upper():
                    raise MigrationSchemaError("TEN-001 schema is incompatible.")
            elif "TEXT" not in str(item["type"]).upper() and "CHAR" not in str(item["type"]).upper():
                raise MigrationSchemaError("TEN-001 schema is incompatible.")
    expected_indexes = {
        "tenant_profiles": {"tenant_profiles_active_name": (("archived_at",), False)},
        "party_contact_methods": {
            "party_contact_methods_party_status": (("party_id", "status"), False),
        },
    }
    for table, required in expected_indexes.items():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SAWarning)
            indexes = inspector.get_indexes(table)
        found = {item["name"]: (tuple(item["column_names"]), bool(item.get("unique"))) for item in indexes}
        if found != required:
            raise MigrationSchemaError("TEN-001 indexes are incompatible.")
    foreign_keys = {
        table: {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"])) for item in inspector.get_foreign_keys(table)}
        for table in expected
    }
    if foreign_keys != {
        "tenant_profiles": {
            (('party_id',), 'parties', ('id',)),
            (('preferred_contact_method_id',), 'party_contact_methods', ('id',)),
        },
        "party_contact_methods": {(('party_id',), 'parties', ('id',))},
    }:
        raise MigrationSchemaError("TEN-001 foreign keys are incompatible.")
    checks = {
        table: {_normalise_sql(item["sqltext"]) for item in inspector.get_check_constraints(table)}
        for table in expected
    }
    if checks != {
        "tenant_profiles": {"do_not_contactin(0,1)"},
        "party_contact_methods": {
            "method_kindin('email','phone')",
            "statusin('active','archived')",
            "length(trim(display_value))>0",
            "(status='active'andarchived_atisnull)or(status='archived'andarchived_atisnotnull)",
            "method_kind='phone'orextensionisnull",
        },
    }:
        raise MigrationSchemaError("TEN-001 check constraints are incompatible.")
    row = connection.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'party_contact_methods_one_active_value'"
    ).scalar_one_or_none()
    normalized_index = _normalise_sql(row or "")
    if (
        "onparty_contact_methods(party_id,method_kind,normalized_value,coalesce(extension,''))" not in normalized_index
        or normalized_index.partition("where")[2] != "status='active'"
    ):
        raise MigrationSchemaError("TEN-001 partial-index predicate is incompatible.")


def _normalise_sql(value: str) -> str:
    return "".join(value.lower().split()).replace('"', "").replace("`", "")

"""Current-format validation owned by the audit module."""
from sqlalchemy import inspect
APPEND_ONLY_TRIGGERS = {"audit_events_no_update", "audit_events_no_delete"}
from app.platform.migration_errors import MigrationSchemaError


def validate_audit_schema(connection) -> None:
    inspector = inspect(connection)
    if "audit_events" not in inspector.get_table_names():
        raise MigrationSchemaError("audit_events is missing.")
    required = {"id", "occurred_at", "entity_type", "entity_id", "action", "before_snapshot", "after_snapshot", "changed_fields", "reason", "actor_kind", "actor_reference", "correlation_id", "schema_version"}
    columns = inspector.get_columns("audit_events")
    if {column["name"] for column in columns} != required:
        raise MigrationSchemaError("audit_events has an incompatible shape.")
    nullable = {"before_snapshot", "after_snapshot", "reason", "actor_reference"}
    for column in columns:
        if column["name"] == "schema_version":
            if "INT" not in str(column["type"]).upper():
                raise MigrationSchemaError("audit_events has incompatible column types.")
        elif not ("TEXT" in str(column["type"]).upper() or "CHAR" in str(column["type"]).upper()):
            raise MigrationSchemaError("audit_events has incompatible column types.")
        if not column["primary_key"] and bool(column["nullable"]) != (column["name"] in nullable):
            raise MigrationSchemaError("audit_events has incompatible nullability.")
    if {column["name"] for column in columns if column["primary_key"]} != {"id"}:
        raise MigrationSchemaError("audit_events has an incompatible primary key.")
    indexes = {item["name"]: (tuple(item["column_names"]), item.get("unique")) for item in inspector.get_indexes("audit_events")}
    expected_indexes = {
        "audit_events_entity_time": (("entity_type", "entity_id", "occurred_at", "id"), 0),
        "audit_events_correlation": (("correlation_id", "occurred_at", "id"), 0),
        "audit_events_activity": (("occurred_at", "action", "actor_kind"), 0),
    }
    if indexes != expected_indexes or inspector.get_unique_constraints("audit_events"):
        raise MigrationSchemaError("audit_events has incompatible indexes or uniqueness.")
    checks = {_normalize(item.get("sqltext") or "") for item in inspector.get_check_constraints("audit_events")}
    expected_checks = {
        "lengthtrimentity_type>0", "lengthtrimentity_id>0", "lengthtrimaction>0",
        "actor_kindin'local_operator','system','connector','ai_assistant'",
    }
    if checks != expected_checks:
        raise MigrationSchemaError("audit_events has incompatible constraints.")
    triggers = {name: _normalize(sql) for name, sql in connection.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'audit_events'")}
    if set(triggers) != APPEND_ONLY_TRIGGERS or triggers != {
        "audit_events_no_update": "createtriggeraudit_events_no_updatebeforeupdateonaudit_eventsbeginselectraiseabort,'auditeventsareappend-only';end",
        "audit_events_no_delete": "createtriggeraudit_events_no_deletebeforedeleteonaudit_eventsbeginselectraiseabort,'auditeventsareappend-only';end",
    }:
        raise MigrationSchemaError("audit_events append-only triggers are missing.")


def _normalize(value: str) -> str:
    return "".join(value.lower().replace("(", "").replace(")", "").split())

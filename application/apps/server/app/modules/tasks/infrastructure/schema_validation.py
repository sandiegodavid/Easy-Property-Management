"""TASK-001 schema validation owned by the task module."""
from sqlalchemy import inspect
from app.platform.migration_errors import MigrationSchemaError


def validate_task_schema(connection) -> None:
    inspector = inspect(connection)
    expected = {
        "tasks": {"id", "title", "notes", "status", "priority", "due_at_utc", "due_timezone", "is_all_day", "completed_at_utc", "cancelled_at_utc", "outcome_note", "related_entity_type", "related_entity_id", "related_label", "created_at_utc", "updated_at_utc"},
        "task_reminders": {"id", "task_id", "remind_at_utc", "status", "acknowledged_at_utc", "dismissed_at_utc", "created_at_utc"},
    }
    for table, names in expected.items():
        if not inspector.has_table(table): raise MigrationSchemaError(f"{table} schema is missing or incompatible with TASK-001.")
        columns = inspector.get_columns(table)
        nullable = {"notes", "due_at_utc", "due_timezone", "completed_at_utc", "cancelled_at_utc", "outcome_note", "related_entity_type", "related_entity_id", "related_label"} if table == "tasks" else {"acknowledged_at_utc", "dismissed_at_utc"}
        if {c["name"] for c in columns} != names or any(bool(c["nullable"]) != (c["name"] in nullable) and not c["primary_key"] for c in columns): raise MigrationSchemaError(f"{table} schema is incompatible with TASK-001.")
        if {c["name"] for c in columns if c["primary_key"]} != {"id"}: raise MigrationSchemaError(f"{table} primary key is incompatible with TASK-001.")
        for c in columns:
            integer = table == "tasks" and c["name"] == "is_all_day"; actual = str(c["type"]).upper()
            if integer and "INT" not in actual: raise MigrationSchemaError(f"{table} has incompatible column types.")
            if not integer and not ("TEXT" in actual or "CHAR" in actual): raise MigrationSchemaError(f"{table} has incompatible column types.")
    indexes = {i["name"]: (tuple(i["column_names"]), i.get("unique")) for i in [*inspector.get_indexes("tasks"), *inspector.get_indexes("task_reminders")]}
    if indexes.get("tasks_status_due") != (("status", "due_at_utc"), 0) or indexes.get("tasks_related_record") != (("related_entity_type", "related_entity_id"), 0) or indexes.get("task_reminders_status_time") != (("status", "remind_at_utc"), 0): raise MigrationSchemaError("TASK-001 indexes are incompatible.")
    if any(unique for _, unique in indexes.values()) or inspector.get_unique_constraints("tasks") or inspector.get_unique_constraints("task_reminders"): raise MigrationSchemaError("TASK-001 uniqueness is incompatible.")
    foreign_keys = inspector.get_foreign_keys("task_reminders")
    if len(foreign_keys) != 1 or foreign_keys[0].get("referred_table") != "tasks" or foreign_keys[0].get("constrained_columns") != ["task_id"] or foreign_keys[0].get("referred_columns") != ["id"]: raise MigrationSchemaError("TASK-001 reminder foreign key is incompatible.")
    checks = {"".join((c.get("sqltext") or "").lower().replace("(", "").replace(")", "").split()) for c in inspector.get_check_constraints("tasks")}
    if checks != {"statusin'open','in_progress','completed','cancelled'", "priorityin'low','normal','high','urgent'", "is_all_dayin0,1"}: raise MigrationSchemaError("TASK-001 task checks are incompatible.")
    reminder_checks = {"".join((c.get("sqltext") or "").lower().replace("(", "").replace(")", "").split()) for c in inspector.get_check_constraints("task_reminders")}
    if reminder_checks != {"statusin'pending','acknowledged','dismissed'"}: raise MigrationSchemaError("TASK-001 reminder checks are incompatible.")

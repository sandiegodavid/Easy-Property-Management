"""Current-baseline append-only Files command receipts."""

FILE_COMMAND_TRIGGERS = {
    f"file_command_operations_no_{action}": f"CREATE TRIGGER file_command_operations_no_{action} BEFORE {action.upper()} "
    "ON file_command_operations BEGIN SELECT RAISE(ABORT, 'file commands are immutable'); END"
    for action in ("update", "delete")
}
FILE_COMMAND_TRIGGERS["file_command_operations_no_replace"] = (
    "CREATE TRIGGER file_command_operations_no_replace BEFORE INSERT ON file_command_operations "
    "WHEN EXISTS (SELECT 1 FROM file_command_operations WHERE id=NEW.id OR idempotency_key=NEW.idempotency_key) "
    "BEGIN SELECT RAISE(ABORT, 'file commands are immutable'); END"
)

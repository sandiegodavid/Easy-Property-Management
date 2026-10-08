"""Immutable current-format Lease command receipts."""

LEASE_COMMAND_TRIGGERS = {
    f"lease_command_operations_no_{action}": (
        f"CREATE TRIGGER lease_command_operations_no_{action} BEFORE {action.upper()} "
        "ON lease_command_operations BEGIN SELECT RAISE(ABORT, 'lease command receipts are append-only'); END"
    )
    for action in ("update", "delete")
}
LEASE_COMMAND_TRIGGERS["lease_command_operations_no_replace"] = """
CREATE TRIGGER lease_command_operations_no_replace BEFORE INSERT ON lease_command_operations
WHEN EXISTS (
    SELECT 1 FROM lease_command_operations
    WHERE id = NEW.id OR idempotency_key = NEW.idempotency_key
       OR (effective = 1 AND NEW.effective = 1
           AND lease_id = NEW.lease_id AND result_revision = NEW.result_revision)
)
BEGIN SELECT RAISE(ABORT, 'lease command receipts are append-only'); END
"""

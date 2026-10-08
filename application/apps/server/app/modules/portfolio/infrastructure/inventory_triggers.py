"""Current-format, append-only Portfolio inventory receipts."""

INVENTORY_TRIGGERS = {
    f"portfolio_inventory_operations_no_{action}": (
        f"CREATE TRIGGER portfolio_inventory_operations_no_{action} BEFORE {action.upper()} "
        "ON portfolio_inventory_operations BEGIN SELECT RAISE(ABORT, 'inventory receipts are append-only'); END"
    )
    for action in ("update", "delete")
}
INVENTORY_TRIGGERS["portfolio_inventory_operations_no_replace"] = """
CREATE TRIGGER portfolio_inventory_operations_no_replace BEFORE INSERT ON portfolio_inventory_operations
WHEN EXISTS (
    SELECT 1 FROM portfolio_inventory_operations
    WHERE id = NEW.id OR idempotency_key = NEW.idempotency_key
       OR (effective = 1 AND NEW.effective = 1
           AND property_id = NEW.property_id AND result_revision = NEW.result_revision)
)
BEGIN SELECT RAISE(ABORT, 'inventory receipts are append-only'); END
"""

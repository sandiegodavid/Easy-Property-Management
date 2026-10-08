"""Baseline DDL for retained status receipts, including lease result attachment."""

STATUS_OPERATION_TRIGGERS = {
    "space_status_operations_no_replace": """
CREATE TRIGGER space_status_operations_no_replace
BEFORE INSERT ON space_status_operations
WHEN EXISTS (
    SELECT 1 FROM space_status_operations
    WHERE id = NEW.id OR idempotency_key = NEW.idempotency_key
       OR (space_id = NEW.space_id AND result_revision = NEW.result_revision)
)
BEGIN SELECT RAISE(ABORT, 'status operation receipts are immutable'); END
""",
    "space_status_operations_no_delete": """
CREATE TRIGGER space_status_operations_no_delete
BEFORE DELETE ON space_status_operations
BEGIN SELECT RAISE(ABORT, 'status operation receipts are immutable'); END
""",
    "space_status_operations_conditional_update": """
CREATE TRIGGER space_status_operations_conditional_update
BEFORE UPDATE ON space_status_operations
WHEN NOT (
    NEW.id IS OLD.id AND NEW.space_id IS OLD.space_id
    AND NEW.idempotency_key IS OLD.idempotency_key
    AND NEW.request_fingerprint IS OLD.request_fingerprint
    AND NEW.result_revision IS OLD.result_revision
    AND NEW.created_at IS OLD.created_at
    AND CASE WHEN json_valid(OLD.result_snapshot) AND json_valid(NEW.result_snapshot)
    THEN COALESCE(
        json_type(OLD.result_snapshot) = 'object'
        AND json_type(NEW.result_snapshot) = 'object'
        AND json_extract(OLD.result_snapshot, '$.sourceKind') = 'lease'
        AND json_type(OLD.result_snapshot, '$.sourceId') = 'text'
        AND length(trim(json_extract(OLD.result_snapshot, '$.sourceId'))) > 0
        AND json_type(OLD.result_snapshot, '$.currentOccupancy') IS NULL
        AND json_type(OLD.result_snapshot, '$.consumerResult') IS NULL
        AND json_type(NEW.result_snapshot, '$.consumerResult') = 'object'
        AND (SELECT count(*) FROM json_each(NEW.result_snapshot)
             WHERE key = 'consumerResult') = 1
        AND NOT EXISTS (
            SELECT fullkey, type, atom FROM json_tree(OLD.result_snapshot)
            EXCEPT
            SELECT fullkey, type, atom
            FROM json_tree(json_remove(NEW.result_snapshot, '$.consumerResult'))
        )
        AND NOT EXISTS (
            SELECT fullkey, type, atom
            FROM json_tree(json_remove(NEW.result_snapshot, '$.consumerResult'))
            EXCEPT
            SELECT fullkey, type, atom FROM json_tree(OLD.result_snapshot)
        ), 0)
    ELSE 0 END
)
BEGIN SELECT RAISE(ABORT, 'status operation receipts are immutable'); END
""",
}

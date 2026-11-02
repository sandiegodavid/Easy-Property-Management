"""Pending effects remain exclusive until receipted or explicitly reconciled."""

PENDING_STORAGE = """
SELECT a.operation_id,d.instance FROM storage_attempt a
JOIN storage_allocation d ON d.operation_id=a.operation_id
LEFT JOIN storage_command c ON c.id=a.id
WHERE c.id IS NULL AND NOT EXISTS (
 SELECT 1 FROM storage_command r JOIN storage_attempt ra ON ra.id=r.id
 WHERE r.operation_id=a.operation_id AND json_extract(r.request,'$.action') IN ('reconcile','finish_retirement')
 AND ra.rowid>a.rowid
)
"""

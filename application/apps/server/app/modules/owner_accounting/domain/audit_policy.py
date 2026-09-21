"""Safe activity projection for OWNER-003's detailed audit snapshots."""
from dataclasses import dataclass
from typing import Any, Mapping

from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy

_SENSITIVE = frozenset({
    "amountMinor", "ownerPartyId", "ownerDisplayNameSnapshot", "leaseId", "verifiedReceiptId",
    "paymentMethodKind", "paymentMethodLabel", "maskedReference", "otherPaymentMethodNote",
    "sourceNote", "reviewNote", "replacesReportId", "receiptId", "allocations", "expectationId",
    "fileId", "linkId", "idempotency_key", "request_fingerprint", "report_id", "result_receipt_id",
    "correlation_id", "idempotencyKey", "requestFingerprint", "reportId", "resultReceiptId",
    "correlationId",
})

@dataclass(frozen=True)
class OwnerReportActivityPolicy:
    """Accept full contextual history while only rendering activity-safe fields."""
    schema_version: int = 1
    _base: DefaultAuditSnapshotPolicy = DefaultAuditSnapshotPolicy()
    def validate(self, snapshot: Mapping[str, Any] | None) -> None:
        self._base.validate(snapshot)
    def redact(self, snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if snapshot is None: return None
        return _redact(snapshot)

def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: "[redacted]" if key in _SENSITIVE else _redact(item) for key, item in value.items()}
    if isinstance(value, list): return [_redact(item) for item in value]
    if isinstance(value, tuple): return tuple(_redact(item) for item in value)
    return value

OWNER_REPORT_ACTIVITY_POLICY = OwnerReportActivityPolicy()

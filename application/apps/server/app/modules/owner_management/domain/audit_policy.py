from dataclasses import dataclass
from typing import Any, Mapping
from app.modules.audit.domain.models import DefaultAuditSnapshotPolicy

_SENSITIVE = frozenset({"description", "ownerPartyId", "ownerDisplayNameSnapshot", "tenantPartyId", "tenantDisplayNameSnapshot", "leaseId", "leaseDisplaySnapshot", "originatingCommunicationId", "resolutionSummary", "dismissalReason", "reopenReason", "historicalSelectionReason", "duplicateReason", "idempotencyKey", "requestFingerprint", "taskId", "notes"})

@dataclass(frozen=True)
class OwnerConcernActivityPolicy:
    schema_version: int = 1
    _base: DefaultAuditSnapshotPolicy = DefaultAuditSnapshotPolicy()
    def validate(self, snapshot: Mapping[str, Any] | None) -> None: self._base.validate(snapshot)
    def redact(self, snapshot: Mapping[str, Any] | None):
        if snapshot is None: return None
        return _redact(snapshot)

def _redact(value):
    if isinstance(value, Mapping): return {key: "[redacted]" if key in _SENSITIVE else _redact(item) for key,item in value.items()}
    if isinstance(value, list): return [_redact(item) for item in value]
    return value

OWNER_CONCERN_ACTIVITY_POLICY = OwnerConcernActivityPolicy()

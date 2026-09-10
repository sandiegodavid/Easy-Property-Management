"""Finance activity presentation keeps monetary and correction detail contextual."""
from typing import Any, Mapping
from app.modules.audit.domain.models import DEFAULT_SNAPSHOT_POLICY

class FinanceActivityPolicy:
    schema_version = 1
    def __init__(self, fields: set[str]): self.fields = fields
    def validate(self, snapshot: Mapping[str, Any] | None) -> None: DEFAULT_SNAPSHOT_POLICY.validate(snapshot)
    def redact(self, snapshot: Mapping[str, Any] | None):
        if snapshot is None: return None
        return {key: value for key, value in snapshot.items() if key in self.fields}

EXPECTATION_ACTIVITY_POLICY = FinanceActivityPolicy({"id", "leaseId", "dueOn", "periodStartsOn", "periodEndsOn", "lifecycleStatus"})
REVIEW_ACTIVITY_POLICY = FinanceActivityPolicy({"id", "expectationId", "decision", "createdAt"})
RECEIPT_ACTIVITY_POLICY = FinanceActivityPolicy({"id", "leaseId", "receivedOn", "voidedAt"})
class AllocationActivityPolicy(FinanceActivityPolicy):
    def redact(self, snapshot):
        return None if snapshot is None else {"redacted": True}

ALLOCATION_ACTIVITY_POLICY = AllocationActivityPolicy(set())

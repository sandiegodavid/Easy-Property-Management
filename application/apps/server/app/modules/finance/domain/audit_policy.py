"""Finance activity presentation keeps monetary and correction detail contextual."""
from typing import Any, Mapping
from app.modules.audit.domain.models import DEFAULT_SNAPSHOT_POLICY
from app.modules.audit.domain.models import AuditSnapshotPolicy


class DepositActivitySnapshotPolicy(AuditSnapshotPolicy):
    """Global activity identifies the deposit action without financial detail."""
    schema_version = 1
    _sensitive = {
        "amount", "agreedAmount", "activeReceivedAmount", "activeRefundedAmount",
        "varianceAmount", "receiptTotal", "creditTotal", "deductionTotal", "refundDue",
        "agreedAmountMinor", "amountMinor", "receiptTotalMinor", "creditTotalMinor",
        "deductionTotalMinor", "refundDueMinor", "outstandingAmountMinor", "outstandingAmount",
        "calculatorPrincipal", "calculatedAmount", "calculatorPrincipalMinor", "calculatedAmountMinor",
        "receivedFromName", "receivedByName", "recipientName", "description", "rationale",
        "reference", "notes", "reviewNotes", "legalRuleReference", "voidReason",
        "eligibilityOverrideReason", "deadlineOverrideReason", "recipientOverrideReason",
        "historicalEntryReason", "historicalPartyReason", "historicalReason", "overageReason",
        "sourceSummary",
    }
    def validate(self, snapshot):
        DEFAULT_SNAPSHOT_POLICY.validate(snapshot)
    def redact(self, snapshot):
        if snapshot is None: return None
        return {key: ("[redacted]" if key in self._sensitive else value) for key, value in snapshot.items()}


DEPOSIT_ACTIVITY_POLICY = DepositActivitySnapshotPolicy()

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

EXPENSE_CATEGORY_ACTIVITY_POLICY = FinanceActivityPolicy({"id", "displayName", "displayOrder", "archivedAt"})
EXPENSE_ACTIVITY_POLICY = FinanceActivityPolicy({"id", "propertyId", "paidOn", "voidedAt"})
EXPENSE_REFUND_ACTIVITY_POLICY = FinanceActivityPolicy({"id", "receivedOn", "voidedAt"})

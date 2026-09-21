"""MAINT-003 immutable work-journal commands."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from .models import MaintenanceError, instant, text, uuid

SUBSTANTIVE_KINDS = frozenset({"work_started", "progress_update", "work_blocked", "work_completed", "general_note"})
ENTRY_KINDS = SUBSTANTIVE_KINDS | {"correction"}
SOURCE_KINDS = frozenset({"operator_observation", "provider_report", "other_report"})
OUTCOME_STATUSES = frozenset({"completed", "partially_completed", "unsuccessful"})


@dataclass(frozen=True)
class WorkJournalCreate:
    assignment_id: str | None
    entry_kind: str
    source_kind: str
    occurred_at_utc: str
    summary: str
    detail: str | None = None
    outcome_status: str | None = None
    outcome_summary: str | None = None
    follow_up_required: bool | None = None
    operator_verified: bool | None = None
    corrects_entry_id: str | None = None
    corrected_entry_kind: str | None = None
    correction_reason: str | None = None
    historical_entry_confirmed: bool | None = None

    def __post_init__(self) -> None:
        if self.entry_kind not in ENTRY_KINDS:
            raise MaintenanceError("entryKind is invalid.")
        if self.source_kind not in SOURCE_KINDS:
            raise MaintenanceError("sourceKind is invalid.")
        if self.assignment_id is not None:
            object.__setattr__(self, "assignment_id", uuid(self.assignment_id, "assignmentId"))
        object.__setattr__(self, "occurred_at_utc", instant(self.occurred_at_utc, "occurredAtUtc"))
        object.__setattr__(self, "summary", text(self.summary, "summary", 240, required=True))
        object.__setattr__(self, "detail", text(self.detail, "detail", 4000) if self.detail is not None else None)
        correction = self.entry_kind == "correction"
        if correction:
            object.__setattr__(self, "corrects_entry_id", uuid(self.corrects_entry_id, "correctsEntryId"))
            if self.corrected_entry_kind not in SUBSTANTIVE_KINDS:
                raise MaintenanceError("correctedEntryKind is required for a correction.")
            object.__setattr__(self, "correction_reason", text(self.correction_reason, "correctionReason", 1000, required=True))
        elif any(value is not None for value in (self.corrects_entry_id, self.corrected_entry_kind, self.correction_reason)):
            raise MaintenanceError("Correction fields apply only to correction entries.")
        effective_kind = self.corrected_entry_kind if correction else self.entry_kind
        if effective_kind == "work_completed":
            if self.outcome_status not in OUTCOME_STATUSES:
                raise MaintenanceError("outcomeStatus is required for completed work.")
            object.__setattr__(self, "outcome_summary", text(self.outcome_summary, "outcomeSummary", 4000, required=True))
            if type(self.follow_up_required) is not bool or type(self.operator_verified) is not bool:
                raise MaintenanceError("followUpRequired and operatorVerified are required booleans for completed work.")
        elif any(value is not None for value in (self.outcome_status, self.outcome_summary, self.follow_up_required, self.operator_verified)):
            raise MaintenanceError("Outcome fields apply only to completed work.")
        if self.source_kind == "provider_report" and self.assignment_id is None:
            raise MaintenanceError("providerReport entries require an assignment.")
        if self.historical_entry_confirmed is not None and type(self.historical_entry_confirmed) is not bool:
            raise MaintenanceError("historicalEntryConfirmed must be a boolean.")

    @property
    def effective_kind(self) -> str:
        return self.corrected_entry_kind or self.entry_kind

    def fingerprint_payload(self) -> dict[str, object]:
        return asdict(self)


def utc_now() -> datetime:
    return datetime.now(UTC)

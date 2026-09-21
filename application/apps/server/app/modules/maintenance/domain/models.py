"""MAINT-001 values and command validation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID
from zoneinfo import ZoneInfo

CATEGORIES = frozenset({"plumbing", "electrical", "heating_cooling", "appliance", "structural", "safety_security", "pest", "exterior_grounds", "cleaning", "other"})
PRIORITIES = frozenset({"low", "normal", "high", "urgent"})
REPORTER_ROLES = frozenset({"owner", "tenant", "manager", "staff"})
REPORTER_SUBJECT_KINDS = frozenset({"party", "local_operator"})

class MaintenanceError(ValueError): code = "maintenance_validation"
class MaintenanceNotFoundError(MaintenanceError): code = "maintenance_not_found"
class MaintenanceConflictError(MaintenanceError):
    def __init__(self, message: str, code: str = "maintenance_conflict") -> None: super().__init__(message); self.code = code

def uuid(value: str, name: str) -> str:
    try: return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as error: raise MaintenanceError(f"{name} must be a UUID.") from error

def text(value: str | None, name: str, maximum: int, *, required: bool = False) -> str | None:
    if value is None:
        if required: raise MaintenanceError(f"{name} is required.")
        return None
    if not isinstance(value, str) or not (clean := value.strip()) or len(clean) > maximum: raise MaintenanceError(f"{name} must contain 1 to {maximum} characters.")
    return clean

def instant(value: str, name: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None: raise ValueError
        return parsed.astimezone(UTC).isoformat()
    except (TypeError, ValueError) as error: raise MaintenanceError(f"{name} must be an aware timestamp.") from error

def zone(value: str) -> str:
    try: ZoneInfo(value); return value
    except Exception as error: raise MaintenanceError("Timezone is invalid.") from error

def money(value: str) -> int:
    if not isinstance(value, str): raise MaintenanceError("amount must be an exact decimal string.")
    try: amount = Decimal(value)
    except InvalidOperation as error: raise MaintenanceError("amount is invalid.") from error
    if amount.as_tuple().exponent != -2 or amount <= 0 or amount > Decimal("99999999.99"): raise MaintenanceError("amount must be between 0.01 and 99,999,999.99 with two decimals.")
    return int(amount * 100)

def fingerprint(action: str, payload: object) -> str:
    return hashlib.sha256(json.dumps({"action": action, "payload": asdict(payload) if hasattr(payload, "__dataclass_fields__") else payload}, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

@dataclass(frozen=True)
class ReporterAttribution:
    role: str; subject_kind: str; party_id: str | None = None; historical_selection_confirmed: bool | None = None; historical_selection_reason: str | None = None
    def __post_init__(self):
        if self.role not in REPORTER_ROLES or self.subject_kind not in REPORTER_SUBJECT_KINDS:
            raise MaintenanceError("Reporter role or subject kind is invalid.")
        if self.subject_kind == "party":
            object.__setattr__(self, "party_id", uuid(self.party_id, "reporter.partyId"))
        elif self.party_id is not None:
            raise MaintenanceError("A local operator reporter cannot have a partyId.")
        if self.role in {"manager", "staff"} and self.subject_kind != "local_operator":
            raise MaintenanceError("Manager and staff reporters must be the local operator.")
        if self.role == "tenant" and self.subject_kind != "party":
            raise MaintenanceError("Tenant reporters must be parties.")
        confirmed, reason = self.historical_selection_confirmed, self.historical_selection_reason
        if self.subject_kind != "party" and (confirmed is not None or reason is not None):
            raise MaintenanceError("Historical reporter selection applies only to party reporters.")
        if confirmed is not None and type(confirmed) is not bool:
            raise MaintenanceError("historicalSelectionConfirmed must be a boolean.")
        if (confirmed is None) != (reason is None):
            raise MaintenanceError("Historical reporter selection confirmation and reason must be supplied together.")
        if confirmed is False:
            raise MaintenanceError("Historical reporter selection requires confirmation.")
        if reason is not None:
            object.__setattr__(self, "historical_selection_reason", text(reason, "historicalSelectionReason", 1000, required=True))

@dataclass(frozen=True)
class IssueCreate:
    property_id: str; space_id: str | None; summary: str; description: str; category: str; category_detail: str | None; priority: str; reported_at_utc: str; reporter: ReporterAttribution
    def __post_init__(self):
        object.__setattr__(self, "property_id", uuid(self.property_id, "propertyId"));
        if self.space_id is not None: object.__setattr__(self, "space_id", uuid(self.space_id, "spaceId"))
        object.__setattr__(self, "summary", text(self.summary, "summary", 240, required=True)); object.__setattr__(self, "description", text(self.description, "description", 10_000, required=True)); object.__setattr__(self, "reported_at_utc", instant(self.reported_at_utc, "reportedAtUtc"))
        if self.category not in CATEGORIES or self.priority not in PRIORITIES: raise MaintenanceError("Category or priority is invalid.")
        detail = text(self.category_detail, "categoryDetail", 200) if self.category_detail is not None else None
        if (self.category == "other") != (detail is not None): raise MaintenanceError("categoryDetail is required only for other.")
        object.__setattr__(self, "category_detail", detail)

@dataclass(frozen=True)
class ReporterCorrection:
    reporter: ReporterAttribution; confirmed: bool; reason: str
    def __post_init__(self):
        if type(self.confirmed) is not bool or not self.confirmed:
            raise MaintenanceError("Explicit confirmation is required.")
        object.__setattr__(self, "reason", text(self.reason, "reason", 1000, required=True))

@dataclass(frozen=True)
class AppointmentCreate:
    starts_at_utc: str; ends_at_utc: str; purpose: str; instructions: str | None = None
    def __post_init__(self):
        start, end = instant(self.starts_at_utc, "startsAtUtc"), instant(self.ends_at_utc, "endsAtUtc")
        if end <= start: raise MaintenanceError("Appointment end must be after start.")
        object.__setattr__(self, "starts_at_utc", start); object.__setattr__(self, "ends_at_utc", end); object.__setattr__(self, "purpose", text(self.purpose, "purpose", 500, required=True)); object.__setattr__(self, "instructions", text(self.instructions, "instructions", 4000) if self.instructions is not None else None)

@dataclass(frozen=True)
class CostCreate:
    context_kind: str; label: str; amount: str; observed_on: str; source_note: str | None = None; replaces_cost_context_id: str | None = None
    def __post_init__(self):
        if self.context_kind not in {"operator_estimate", "work_reported"}: raise MaintenanceError("Cost context kind is invalid.")
        object.__setattr__(self, "label", text(self.label, "label", 200, required=True)); object.__setattr__(self, "amount", money(self.amount));
        # A cost observation is a property-local calendar date.  Datetime
        # strings are deliberately not accepted: accepting them would make
        # the persisted meaning depend on a later timezone conversion.
        try: date.fromisoformat(self.observed_on)
        except ValueError as error: raise MaintenanceError("observedOn must be an ISO date.") from error
        object.__setattr__(self, "source_note", text(self.source_note, "sourceNote", 4000) if self.source_note is not None else None)
        if self.replaces_cost_context_id is not None: object.__setattr__(self, "replaces_cost_context_id", uuid(self.replaces_cost_context_id, "replacesCostContextId"))

def local_date(value: str, name: str) -> str:
    if not isinstance(value, str): raise MaintenanceError(f"{name} must be an ISO date.")
    try: return date.fromisoformat(value).isoformat()
    except ValueError as error: raise MaintenanceError(f"{name} must be an ISO date.") from error

@dataclass(frozen=True)
class QuoteCreate:
    provider_party_id: str; label: str; scope_summary: str; amount: str; received_on: str
    valid_through: str | None = None; earliest_work_start_on: str | None = None; estimated_work_finish_on: str | None = None; terms_notes: str | None = None; replaces_quote_id: str | None = None
    def __post_init__(self):
        object.__setattr__(self, "provider_party_id", uuid(self.provider_party_id, "providerPartyId"))
        object.__setattr__(self, "label", text(self.label, "label", 200, required=True))
        object.__setattr__(self, "scope_summary", text(self.scope_summary, "scopeSummary", 4000, required=True))
        object.__setattr__(self, "amount", money(self.amount))
        received = local_date(self.received_on, "receivedOn"); object.__setattr__(self, "received_on", received)
        if self.valid_through is not None:
            valid = local_date(self.valid_through, "validThrough")
            if valid < received: raise MaintenanceError("validThrough cannot precede receivedOn.")
            object.__setattr__(self, "valid_through", valid)
        if (self.earliest_work_start_on is None) != (self.estimated_work_finish_on is None):
            raise MaintenanceError("Quoted work start and finish dates must be supplied together.")
        if self.earliest_work_start_on is not None:
            start = local_date(self.earliest_work_start_on, "earliestWorkStartOn")
            finish = local_date(self.estimated_work_finish_on, "estimatedWorkFinishOn")
            if finish < start:
                raise MaintenanceError("estimatedWorkFinishOn cannot precede earliestWorkStartOn.")
            object.__setattr__(self, "earliest_work_start_on", start)
            object.__setattr__(self, "estimated_work_finish_on", finish)
        object.__setattr__(self, "terms_notes", text(self.terms_notes, "termsNotes", 4000) if self.terms_notes is not None else None)
        if self.replaces_quote_id is not None: object.__setattr__(self, "replaces_quote_id", uuid(self.replaces_quote_id, "replacesQuoteId"))

@dataclass(frozen=True)
class AssignmentCreate:
    provider_party_id: str; quote_id: str | None = None; selection_reason: str | None = None
    instructions: str | None = None; direct_assignment_confirmed: bool | None = None
    avoid_override_confirmed: bool | None = None; avoid_override_reason: str | None = None
    replaces_assignment_id: str | None = None; replacement_confirmed: bool | None = None; end_reason: str | None = None
    def __post_init__(self):
        object.__setattr__(self, "provider_party_id", uuid(self.provider_party_id, "providerPartyId"))
        if self.quote_id is not None: object.__setattr__(self, "quote_id", uuid(self.quote_id, "quoteId"))
        object.__setattr__(self, "selection_reason", text(self.selection_reason, "selectionReason", 1000) if self.selection_reason is not None else None)
        object.__setattr__(self, "instructions", text(self.instructions, "instructions", 4000) if self.instructions is not None else None)
        if self.quote_id is None:
            if self.direct_assignment_confirmed is not True or self.selection_reason is None: raise MaintenanceError("Direct assignment requires confirmation and a selection reason.")
        elif self.direct_assignment_confirmed is not None: raise MaintenanceError("directAssignmentConfirmed applies only without a quote.")
        if self.avoid_override_confirmed is not None and type(self.avoid_override_confirmed) is not bool: raise MaintenanceError("avoidOverrideConfirmed must be a boolean.")
        object.__setattr__(self, "avoid_override_reason", text(self.avoid_override_reason, "avoidOverrideReason", 1000) if self.avoid_override_reason is not None else None)
        if self.replaces_assignment_id is not None:
            object.__setattr__(self, "replaces_assignment_id", uuid(self.replaces_assignment_id, "replacesAssignmentId"))
            if self.replacement_confirmed is not True: raise MaintenanceError("Reassignment requires explicit confirmation.")
            object.__setattr__(self, "end_reason", text(self.end_reason, "endReason", 1000, required=True))
        elif self.replacement_confirmed is not None or self.end_reason is not None: raise MaintenanceError("Replacement confirmation and end reason require replacesAssignmentId.")

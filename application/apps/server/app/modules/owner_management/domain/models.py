"""OWNER-004 values and command validation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from uuid import UUID


CONCERN_TYPES = frozenset({"general_rental", "lease", "tenant", "vacancy"})
PRIORITIES = frozenset({"low", "normal", "high", "urgent"})
ACTIVE_STATUSES = frozenset({"open", "in_progress"})
TERMINAL_STATUSES = frozenset({"resolved", "dismissed"})


class OwnerConcernError(RuntimeError):
    code = "owner_concern_validation"


class OwnerConcernNotFoundError(OwnerConcernError):
    code = "owner_concern_not_found"


class OwnerConcernConflictError(OwnerConcernError):
    code = "owner_concern_conflict"

    def __init__(self, message: str, code: str = "owner_concern_conflict", details: dict[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def uuid(value: str, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise OwnerConcernError(f"{label} must be a UUID.") from error


def text(value: str | None, label: str, maximum: int, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise OwnerConcernError(f"{label} is required.")
        return None
    if not isinstance(value, str):
        raise OwnerConcernError(f"{label} must be text.")
    cleaned = value.strip()
    if not cleaned and required:
        raise OwnerConcernError(f"{label} is required.")
    if not cleaned:
        return None
    if len(cleaned) > maximum:
        raise OwnerConcernError(f"{label} is too long.")
    return cleaned


def timestamp(value: str, label: str) -> str:
    try:
        item = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if item.tzinfo is None:
            raise ValueError
        return item.astimezone(UTC).isoformat()
    except (AttributeError, TypeError, ValueError) as error:
        raise OwnerConcernError(f"{label} must be an aware timestamp.") from error


@dataclass(frozen=True)
class FollowUpInput:
    title: str
    notes: str | None = None
    priority: str = "normal"
    due_at_utc: str | None = None
    due_timezone: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "title", text(self.title, "Follow-up title", 255, required=True))
        object.__setattr__(self, "notes", text(self.notes, "Follow-up notes", 10_000))
        if self.priority not in PRIORITIES:
            raise OwnerConcernError("Follow-up priority is invalid.")
        if (self.due_at_utc is None) != (self.due_timezone is None):
            raise OwnerConcernError("Follow-up due time and timezone must be supplied together.")
        if self.due_at_utc:
            object.__setattr__(self, "due_at_utc", timestamp(self.due_at_utc, "Follow-up due time"))
            object.__setattr__(self, "due_timezone", text(self.due_timezone, "Follow-up timezone", 128, required=True))


@dataclass(frozen=True)
class ConcernCreateCommand:
    owner_party_id: str
    property_id: str
    concern_type: str
    summary: str
    description: str
    raised_at_utc: str
    idempotency_key: str
    space_id: str | None = None
    lease_id: str | None = None
    tenant_party_id: str | None = None
    originating_communication_id: str | None = None
    priority: str = "normal"
    historical_selection_confirmed: bool = False
    historical_selection_reason: str | None = None
    duplicate_confirmed: bool = False
    duplicate_reason: str | None = None
    replaces_concern_id: str | None = None
    follow_up: FollowUpInput | None = None

    def __post_init__(self):
        for field, label in (("owner_party_id", "Owner party ID"), ("property_id", "Property ID"), ("idempotency_key", "Idempotency key")):
            object.__setattr__(self, field, uuid(getattr(self, field), label))
        for field, label in (("space_id", "Space ID"), ("lease_id", "Lease ID"), ("tenant_party_id", "Tenant party ID"), ("originating_communication_id", "Originating communication ID"), ("replaces_concern_id", "Replaced concern ID")):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, uuid(value, label))
        if self.concern_type not in CONCERN_TYPES:
            raise OwnerConcernError("Concern type is invalid.")
        if self.priority not in PRIORITIES:
            raise OwnerConcernError("Concern priority is invalid.")
        object.__setattr__(self, "summary", text(self.summary, "Summary", 240, required=True))
        object.__setattr__(self, "description", text(self.description, "Description", 10_000, required=True))
        object.__setattr__(self, "raised_at_utc", timestamp(self.raised_at_utc, "Raised time"))
        for flag in ("historical_selection_confirmed", "duplicate_confirmed"):
            if type(getattr(self, flag)) is not bool:
                raise OwnerConcernError(f"{flag} must be a boolean.")
        object.__setattr__(self, "historical_selection_reason", text(self.historical_selection_reason, "Historical selection reason", 1000, required=self.historical_selection_confirmed))
        object.__setattr__(self, "duplicate_reason", text(self.duplicate_reason, "Independent concern reason", 1000, required=self.duplicate_confirmed))
        if self.concern_type in {"lease", "tenant", "vacancy"} and self.space_id is None:
            raise OwnerConcernError("This concern type requires a space.")
        if self.concern_type in {"lease", "tenant"} and self.lease_id is None:
            raise OwnerConcernError("This concern type requires a lease.")
        if self.concern_type == "tenant" and self.tenant_party_id is None:
            raise OwnerConcernError("Tenant concerns require a tenant party.")
        if self.follow_up is not None and not isinstance(self.follow_up, FollowUpInput):
            raise OwnerConcernError("Follow-up input is invalid.")


@dataclass(frozen=True)
class Concern:
    id: str; owner_party_id: str; owner_display_name_snapshot: str
    property_id: str; property_display_name_snapshot: str
    space_id: str | None; space_display_name_snapshot: str | None
    lease_id: str | None; lease_display_snapshot: str | None
    tenant_party_id: str | None; tenant_display_name_snapshot: str | None
    originating_communication_id: str | None; concern_type: str; summary: str; description: str
    priority: str; status: str; raised_at_utc: str; property_timezone_snapshot: str
    recorded_at_utc: str; updated_at_utc: str; resolved_at_utc: str | None
    resolution_summary: str | None; dismissed_at_utc: str | None; dismissal_reason: str | None
    replaces_concern_id: str | None; observed_occupancy_status: str | None
    observed_availability_status: str | None; observed_available_on: str | None
    idempotency_key: str; request_fingerprint: str

    def to_dict(self) -> dict[str, object]:
        values = asdict(self)
        values.pop("idempotency_key"); values.pop("request_fingerprint")
        return _camel(values)


def _camel(values: dict[str, object]) -> dict[str, object]:
    return {key.split("_")[0] + "".join(part.title() for part in key.split("_")[1:]): value for key, value in values.items()}

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
class IssueCreate:
    property_id: str; space_id: str | None; summary: str; description: str; category: str; category_detail: str | None; priority: str; reported_at_utc: str
    def __post_init__(self):
        object.__setattr__(self, "property_id", uuid(self.property_id, "propertyId"));
        if self.space_id is not None: object.__setattr__(self, "space_id", uuid(self.space_id, "spaceId"))
        object.__setattr__(self, "summary", text(self.summary, "summary", 240, required=True)); object.__setattr__(self, "description", text(self.description, "description", 10_000, required=True)); object.__setattr__(self, "reported_at_utc", instant(self.reported_at_utc, "reportedAtUtc"))
        if self.category not in CATEGORIES or self.priority not in PRIORITIES: raise MaintenanceError("Category or priority is invalid.")
        detail = text(self.category_detail, "categoryDetail", 200) if self.category_detail is not None else None
        if (self.category == "other") != (detail is not None): raise MaintenanceError("categoryDetail is required only for other.")
        object.__setattr__(self, "category_detail", detail)

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

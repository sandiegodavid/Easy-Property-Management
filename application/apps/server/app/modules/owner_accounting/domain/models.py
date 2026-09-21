"""OWNER-003 report values and command validation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from app.modules.finance.domain.models import PAYMENT_METHOD_KINDS, _masked_reference, _text


class OwnerReportError(RuntimeError):
    code = "owner_rent_report_validation"


class OwnerReportNotFoundError(OwnerReportError):
    code = "owner_rent_report_not_found"


class OwnerReportConflictError(OwnerReportError):
    code = "owner_rent_report_conflict"
    def __init__(self, message: str, *, details: dict[str, object] | None = None):
        super().__init__(message); self.details = details or {}


def _uuid(value: str, label: str) -> str:
    try: return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as error: raise OwnerReportError(f"{label} must be a UUID.") from error

def _date(value: str, label: str) -> str:
    try: return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as error: raise OwnerReportError(f"{label} must be an ISO date.") from error

def _stamp(value: str, label: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None: raise ValueError
        return parsed.astimezone(UTC).isoformat()
    except (TypeError, ValueError) as error: raise OwnerReportError(f"{label} must be an aware timestamp.") from error

def _method(kind: str, label: str | None, reference: str | None, other: str | None):
    if kind not in PAYMENT_METHOD_KINDS: raise OwnerReportError("Payment method kind is invalid.")
    try:
        label = _text(label, "Payment method label", 100)
        reference = _masked_reference(reference)
        other = _text(other, "Other payment method note", 200, required=kind == "other") if kind == "other" else other
    except Exception as error: raise OwnerReportError(str(error)) from error
    if kind != "other" and other is not None: raise OwnerReportError("Other payment method note is allowed only for other payment methods.")
    return label, reference, other

@dataclass(frozen=True)
class OwnerRentReportCommand:
    lease_id: str; owner_party_id: str; received_on: str; amount_minor: int
    payment_method_kind: str; idempotency_key: str; reported_at_utc: str
    payment_method_label: str | None = None; masked_reference: str | None = None
    other_payment_method_note: str | None = None; source_note: str | None = None
    replaces_report_id: str | None = None
    def __post_init__(self):
        for name, label in (("lease_id", "Lease ID"), ("owner_party_id", "Owner party ID"), ("idempotency_key", "Idempotency key")):
            object.__setattr__(self, name, _uuid(getattr(self, name), label))
        object.__setattr__(self, "received_on", _date(self.received_on, "Received date"))
        object.__setattr__(self, "reported_at_utc", _stamp(self.reported_at_utc, "Reported time"))
        if type(self.amount_minor) is not int or not 1 <= self.amount_minor <= 9_999_999_999: raise OwnerReportError("Amount must be an integer between 1 and 9,999,999,999.")
        label, reference, other = _method(self.payment_method_kind, self.payment_method_label, self.masked_reference, self.other_payment_method_note)
        object.__setattr__(self, "payment_method_label", label); object.__setattr__(self, "masked_reference", reference); object.__setattr__(self, "other_payment_method_note", other)
        try: object.__setattr__(self, "source_note", _text(self.source_note, "Source note", 4000))
        except Exception as error: raise OwnerReportError(str(error)) from error
        if self.replaces_report_id is not None: object.__setattr__(self, "replaces_report_id", _uuid(self.replaces_report_id, "Replaced report ID"))

@dataclass(frozen=True)
class VerifyOwnerRentReportCommand:
    confirmed: bool; review_note: str; existing_receipt_id: str | None = None
    receipt_idempotency_key: str | None = None; allocations: tuple[object, ...] = ()
    replaces_receipt_id: str | None = None
    def __post_init__(self):
        if type(self.confirmed) is not bool or not self.confirmed: raise OwnerReportError("Explicit verification confirmation is required.")
        try: object.__setattr__(self, "review_note", _text(self.review_note, "Verification note", 1000, required=True))
        except Exception as error: raise OwnerReportError(str(error)) from error
        if (self.existing_receipt_id is None) == (self.receipt_idempotency_key is None): raise OwnerReportError("Choose exactly one existing receipt or receipt creation.")
        if self.existing_receipt_id is not None:
            object.__setattr__(self, "existing_receipt_id", _uuid(self.existing_receipt_id, "Receipt ID"))
            if self.allocations or self.replaces_receipt_id is not None: raise OwnerReportError("Existing receipt verification cannot include allocations or replacement.")
        else:
            object.__setattr__(self, "receipt_idempotency_key", _uuid(self.receipt_idempotency_key, "Receipt idempotency key"))
            if self.replaces_receipt_id is not None: object.__setattr__(self, "replaces_receipt_id", _uuid(self.replaces_receipt_id, "Replaced receipt ID"))

@dataclass(frozen=True)
class RejectOwnerRentReportCommand:
    confirmed: bool; reason: str
    def __post_init__(self):
        if type(self.confirmed) is not bool or not self.confirmed: raise OwnerReportError("Explicit rejection confirmation is required.")
        try: object.__setattr__(self, "reason", _text(self.reason, "Rejection reason", 1000, required=True))
        except Exception as error: raise OwnerReportError(str(error)) from error

@dataclass(frozen=True)
class OwnerRentReport:
    id: str; lease_id: str; property_id: str; space_id: str; property_timezone_snapshot: str
    owner_party_id: str; owner_display_name_snapshot: str; received_on: str; amount_minor: int
    currency_code: str; payment_method_kind: str; payment_method_label: str | None
    masked_reference: str | None; other_payment_method_note: str | None; reported_at_utc: str
    source_note: str | None; status: str; verified_receipt_id: str | None
    reviewed_at: str | None; review_note: str | None; replaces_report_id: str | None
    created_at: str; updated_at: str
    def to_dict(self): return _camel(asdict(self))

def _camel(value: dict[str, object]) -> dict[str, object]:
    parts = lambda key: key.split("_")
    return {parts(key)[0] + "".join(item.title() for item in parts(key)[1:]): item for key, item in value.items()}

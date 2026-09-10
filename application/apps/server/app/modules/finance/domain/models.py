"""Immutable FIN-001 records and command validation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from uuid import UUID


class FinanceError(RuntimeError): pass
class FinanceNotFoundError(FinanceError): pass
class FinanceConflictError(FinanceError): pass


def _date(value: str, label: str) -> str:
    if not isinstance(value, str): raise FinanceError(f"{label} must be an ISO date.")
    try: return date.fromisoformat(value).isoformat()
    except ValueError as error: raise FinanceError(f"{label} must be an ISO date.") from error

def _uuid(value: str, label: str) -> str:
    try: return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as error: raise FinanceError(f"{label} must be a UUID.") from error

def _text(value: str | None, label: str, limit: int, *, required: bool = False) -> str | None:
    if value is None:
        if required: raise FinanceError(f"{label} is required.")
        return None
    if not isinstance(value, str) or not (result := value.strip()) or len(result) > limit:
        raise FinanceError(f"{label} must be between 1 and {limit} characters.")
    return result

@dataclass(frozen=True)
class SynchronizeExpectationsCommand:
    lease_term_id: str; through_on: str; schedule_anchor_on: str | None = None; responsibility_ends_on_override: str | None = None; override_reason: str | None = None; override_confirmed: bool = False
    def __post_init__(self):
        object.__setattr__(self, "lease_term_id", _uuid(self.lease_term_id, "Lease term ID")); object.__setattr__(self, "through_on", _date(self.through_on, "Through date"))
        if self.schedule_anchor_on is not None: object.__setattr__(self, "schedule_anchor_on", _date(self.schedule_anchor_on, "Schedule anchor"))
        if type(self.override_confirmed) is not bool: raise FinanceError("Override confirmation must be boolean.")
        if self.responsibility_ends_on_override is None:
            if self.override_reason is not None: raise FinanceError("An override reason requires a responsibility boundary.")
        else:
            if not self.override_confirmed: raise FinanceError("Explicit override confirmation is required.")
            object.__setattr__(self, "responsibility_ends_on_override", _date(self.responsibility_ends_on_override, "Responsibility boundary")); object.__setattr__(self, "override_reason", _text(self.override_reason, "Override reason", 1000, required=True))

@dataclass(frozen=True)
class ReceiptAllocationCommand:
    expectation_id: str; amount_minor: int
    def __post_init__(self):
        object.__setattr__(self, "expectation_id", _uuid(self.expectation_id, "Expectation ID"))
        if type(self.amount_minor) is not int or self.amount_minor <= 0: raise FinanceError("Allocation amount must be a positive integer.")

@dataclass(frozen=True)
class RecordReceiptCommand:
    lease_id: str; idempotency_key: str; received_on: str; amount_minor: int; currency_code: str; allocations: tuple[ReceiptAllocationCommand, ...]; received_by_party_id: str | None = None; replaces_receipt_id: str | None = None; notes: str | None = None
    def __post_init__(self):
        object.__setattr__(self, "lease_id", _uuid(self.lease_id, "Lease ID")); object.__setattr__(self, "idempotency_key", _uuid(self.idempotency_key, "Idempotency key")); object.__setattr__(self, "received_on", _date(self.received_on, "Received date"))
        if self.currency_code != "USD": raise FinanceError("FIN-001 supports USD receipts only.")
        if type(self.amount_minor) is not int or self.amount_minor <= 0: raise FinanceError("Receipt amount must be a positive integer.")
        if not isinstance(self.allocations, tuple) or not self.allocations or len(self.allocations) > 100 or any(not isinstance(item, ReceiptAllocationCommand) for item in self.allocations): raise FinanceError("A receipt requires one to 100 valid allocations.")
        if len({item.expectation_id for item in self.allocations}) != len(self.allocations): raise FinanceError("A receipt cannot allocate an expectation twice.")
        if sum(item.amount_minor for item in self.allocations) != self.amount_minor: raise FinanceError("Allocations must equal the receipt amount.")
        if self.received_by_party_id is not None: object.__setattr__(self, "received_by_party_id", _uuid(self.received_by_party_id, "Recipient party ID"))
        if self.replaces_receipt_id is not None: object.__setattr__(self, "replaces_receipt_id", _uuid(self.replaces_receipt_id, "Replacement receipt ID"))
        object.__setattr__(self, "notes", _text(self.notes, "Receipt notes", 4000))

@dataclass(frozen=True)
class VoidCommand:
    confirmed: bool; reason: str
    def __post_init__(self):
        if type(self.confirmed) is not bool or not self.confirmed: raise FinanceError("Explicit confirmation is required.")
        object.__setattr__(self, "reason", _text(self.reason, "Reason", 1000, required=True))

@dataclass(frozen=True)
class TimelinessReviewCommand:
    decision: str; reason: str; confirmed: bool
    def __post_init__(self):
        if self.decision not in {"mark_missed", "clear_missed"}: raise FinanceError("Timeliness decision is invalid.")
        if type(self.confirmed) is not bool or not self.confirmed: raise FinanceError("Explicit confirmation is required.")
        object.__setattr__(self, "reason", _text(self.reason, "Reason", 1000, required=True))

@dataclass(frozen=True)
class RentExpectation:
    id: str; lease_id: str; lease_term_id: str; period_starts_on: str; period_ends_on: str; due_on: str; expected_amount_minor: int; currency_code: str; payment_frequency: str; schedule_anchor_on: str; is_prorated: bool; proration_numerator_days: int | None; proration_denominator_days: int | None; responsibility_boundary_on: str | None; responsibility_override_reason: str | None; voided_at: str | None; void_reason: str | None; created_at: str
    def to_dict(self): return _camel(asdict(self))

@dataclass(frozen=True)
class RentReceipt:
    id: str; lease_id: str; idempotency_key: str; received_on: str; amount_minor: int; currency_code: str; received_by_party_id: str | None; replaces_receipt_id: str | None; notes: str | None; voided_at: str | None; void_reason: str | None; created_at: str
    def to_dict(self): return _camel(asdict(self))

def _camel(values): return {key.split("_")[0] + "".join(word.title() for word in key.split("_")[1:]): value for key, value in values.items()}

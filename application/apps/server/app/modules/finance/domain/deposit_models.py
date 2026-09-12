"""FIN-008 command validation and neutral deposit records."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
from typing import Literal

from app.modules.finance.domain.expense_models import amount_minor, amount_text, identifier, local_date, text
from app.modules.finance.domain.models import FinanceError


def _bool(value: bool, label: str) -> bool:
    if type(value) is not bool:
        raise FinanceError(f"{label} must be boolean.")
    return value


def _fingerprint(values: dict[str, object]) -> str:
    return sha256(json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class DepositAccountCreateCommand:
    lease_term_id: str
    def __post_init__(self): object.__setattr__(self, "lease_term_id", identifier(self.lease_term_id, "Lease term ID"))


@dataclass(frozen=True)
class DepositReceiptCommand:
    idempotency_key: str; received_on: str; amount: str; currency_code: str
    received_by_kind: Literal["local_operator", "party"]
    received_from_party_id: str | None = None; received_by_party_id: str | None = None
    reference: str | None = None; notes: str | None = None; replaces_receipt_id: str | None = None
    duplicate_confirmed: bool = False; historical_entry_confirmed: bool = False; historical_entry_reason: str | None = None
    overage_confirmed: bool = False; overage_reason: str | None = None
    historical_party_confirmed: bool = False; historical_party_reason: str | None = None
    def __post_init__(self):
        object.__setattr__(self, "idempotency_key", identifier(self.idempotency_key, "Idempotency key")); object.__setattr__(self, "received_on", local_date(self.received_on, "Received date"))
        if self.currency_code != "USD": raise FinanceError("FIN-008 supports USD only.")
        amount_minor(self.amount)
        if self.received_by_kind not in {"local_operator", "party"}: raise FinanceError("Received-by kind is invalid.")
        for field, label in (("received_from_party_id", "Payer party ID"), ("received_by_party_id", "Recipient party ID"), ("replaces_receipt_id", "Replacement receipt ID")):
            if getattr(self, field) is not None: object.__setattr__(self, field, identifier(getattr(self, field), label))
        if (self.received_by_kind == "party") != (self.received_by_party_id is not None): raise FinanceError("Received-by party must be set exactly for party receipt handling.")
        for name, label in (("duplicate_confirmed", "Duplicate confirmation"), ("historical_entry_confirmed", "Historical confirmation"), ("overage_confirmed", "Overage confirmation"), ("historical_party_confirmed", "Historical party confirmation")):
            object.__setattr__(self, name, _bool(getattr(self, name), label))
        if (self.historical_entry_reason is not None) != self.historical_entry_confirmed: raise FinanceError("Historical confirmation and reason must be supplied together.")
        if (self.overage_reason is not None) != self.overage_confirmed: raise FinanceError("Overage confirmation and reason must be supplied together.")
        if (self.historical_party_reason is not None) != self.historical_party_confirmed: raise FinanceError("Historical party confirmation and reason must be supplied together.")
        object.__setattr__(self, "reference", text(self.reference, "Reference", 200)); object.__setattr__(self, "notes", text(self.notes, "Notes", 4000)); object.__setattr__(self, "historical_entry_reason", text(self.historical_entry_reason, "Historical reason", 1000, required=self.historical_entry_confirmed)); object.__setattr__(self, "overage_reason", text(self.overage_reason, "Overage reason", 1000, required=self.overage_confirmed)); object.__setattr__(self, "historical_party_reason", text(self.historical_party_reason, "Historical party reason", 1000, required=self.historical_party_confirmed))
    @property
    def amount_minor(self): return amount_minor(self.amount)
    def fingerprint(self): return _fingerprint(asdict(self))


@dataclass(frozen=True)
class SettlementCreateCommand:
    settlement_due_on: str; legal_rule_reference: str | None = None; review_notes: str | None = None
    eligibility_override_confirmed: bool = False; eligibility_override_reason: str | None = None
    deadline_override_confirmed: bool = False; deadline_override_reason: str | None = None
    replaces_settlement_id: str | None = None
    def __post_init__(self):
        object.__setattr__(self, "settlement_due_on", local_date(self.settlement_due_on, "Settlement due date"))
        for field, label in (("eligibility_override_confirmed", "Eligibility override confirmation"), ("deadline_override_confirmed", "Deadline override confirmation")): object.__setattr__(self, field, _bool(getattr(self, field), label))
        if (self.eligibility_override_reason is not None) != self.eligibility_override_confirmed or (self.deadline_override_reason is not None) != self.deadline_override_confirmed: raise FinanceError("Each override reason requires its confirmation.")
        object.__setattr__(self, "eligibility_override_reason", text(self.eligibility_override_reason, "Eligibility override reason", 1000, required=self.eligibility_override_confirmed)); object.__setattr__(self, "deadline_override_reason", text(self.deadline_override_reason, "Deadline override reason", 1000, required=self.deadline_override_confirmed)); object.__setattr__(self, "legal_rule_reference", text(self.legal_rule_reference, "Legal or rule reference", 500)); object.__setattr__(self, "review_notes", text(self.review_notes, "Review notes", 4000))
        if self.replaces_settlement_id is not None: object.__setattr__(self, "replaces_settlement_id", identifier(self.replaces_settlement_id, "Replacement settlement ID"))


@dataclass(frozen=True)
class DeductionCommand:
    category: str; amount: str; description: str; rationale: str
    def __post_init__(self):
        if self.category not in {"unpaid_rent", "damage", "cleaning", "missing_property", "contractual_fee", "other"}: raise FinanceError("Deduction category is invalid.")
        amount_minor(self.amount); object.__setattr__(self, "description", text(self.description, "Deduction description", 500, required=True)); object.__setattr__(self, "rationale", text(self.rationale, "Deduction rationale", 2000, required=True))
    @property
    def amount_minor(self): return amount_minor(self.amount)


@dataclass(frozen=True)
class CreditCommand:
    kind: str; amount: str; description: str
    calculator_principal: str | None = None; annual_rate_basis_points: int | None = None; starts_on: str | None = None; ends_on: str | None = None; override_reason: str | None = None
    def __post_init__(self):
        if self.kind not in {"interest", "other"}: raise FinanceError("Credit kind is invalid.")
        amount_minor(self.amount); object.__setattr__(self, "description", text(self.description, "Credit description", 500, required=True))
        values = (self.calculator_principal, self.annual_rate_basis_points, self.starts_on, self.ends_on)
        if any(value is not None for value in values):
            if self.kind != "interest" or any(value is None for value in values): raise FinanceError("Interest calculator inputs must be complete and apply only to interest credits.")
            principal = amount_minor(self.calculator_principal); starts = local_date(self.starts_on, "Interest starts-on"); ends = local_date(self.ends_on, "Interest ends-on")
            days = (date.fromisoformat(ends) - date.fromisoformat(starts)).days
            if type(self.annual_rate_basis_points) is not int or not 1 <= self.annual_rate_basis_points <= 100_000 or not 1 <= days <= 36_600: raise FinanceError("Interest calculator inputs are invalid.")
            calculated = int((Decimal(principal) * Decimal(self.annual_rate_basis_points) * Decimal(days) / Decimal(10_000) / Decimal(365)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            object.__setattr__(self, "calculator_principal", self.calculator_principal); object.__setattr__(self, "starts_on", starts); object.__setattr__(self, "ends_on", ends)
            if self.amount_minor != calculated: object.__setattr__(self, "override_reason", text(self.override_reason, "Interest override reason", 1000, required=True))
            elif self.override_reason is not None: raise FinanceError("An interest override reason is allowed only when applied amount differs from the calculation.")
        elif self.override_reason is not None: raise FinanceError("An override reason requires interest calculator inputs.")
    @property
    def amount_minor(self): return amount_minor(self.amount)
    @property
    def calculated_amount_minor(self):
        if self.calculator_principal is None: return None
        days = (date.fromisoformat(self.ends_on) - date.fromisoformat(self.starts_on)).days
        return int((Decimal(amount_minor(self.calculator_principal)) * Decimal(self.annual_rate_basis_points) * Decimal(days) / Decimal(10_000) / Decimal(365)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class DepositRefundCommand:
    idempotency_key: str; recipient_party_id: str; paid_on: str; amount: str; currency_code: str
    reference: str | None = None; notes: str | None = None; recipient_override_confirmed: bool = False; recipient_override_reason: str | None = None; replaces_refund_id: str | None = None; duplicate_confirmed: bool = False; historical_party_confirmed: bool = False; historical_party_reason: str | None = None
    def __post_init__(self):
        object.__setattr__(self, "idempotency_key", identifier(self.idempotency_key, "Idempotency key")); object.__setattr__(self, "recipient_party_id", identifier(self.recipient_party_id, "Recipient party ID")); object.__setattr__(self, "paid_on", local_date(self.paid_on, "Paid date")); amount_minor(self.amount)
        if self.currency_code != "USD": raise FinanceError("FIN-008 supports USD only.")
        object.__setattr__(self, "recipient_override_confirmed", _bool(self.recipient_override_confirmed, "Recipient override confirmation")); object.__setattr__(self, "duplicate_confirmed", _bool(self.duplicate_confirmed, "Duplicate confirmation")); object.__setattr__(self, "historical_party_confirmed", _bool(self.historical_party_confirmed, "Historical party confirmation"))
        if (self.recipient_override_reason is not None) != self.recipient_override_confirmed: raise FinanceError("Recipient override confirmation and reason must be supplied together.")
        if (self.historical_party_reason is not None) != self.historical_party_confirmed: raise FinanceError("Historical party confirmation and reason must be supplied together.")
        object.__setattr__(self, "reference", text(self.reference, "Reference", 200)); object.__setattr__(self, "notes", text(self.notes, "Notes", 4000)); object.__setattr__(self, "recipient_override_reason", text(self.recipient_override_reason, "Recipient override reason", 1000, required=self.recipient_override_confirmed)); object.__setattr__(self, "historical_party_reason", text(self.historical_party_reason, "Historical party reason", 1000, required=self.historical_party_confirmed))
        if self.replaces_refund_id is not None: object.__setattr__(self, "replaces_refund_id", identifier(self.replaces_refund_id, "Replacement refund ID"))
    @property
    def amount_minor(self): return amount_minor(self.amount)
    def fingerprint(self): return _fingerprint(asdict(self))


def money(value: int | None) -> str | None: return None if value is None else amount_text(value)


def signed_money(value: int) -> str:
    """Render a signed balance without floor-division distortion for negatives."""
    sign = "-" if value < 0 else ""
    amount = abs(value)
    return f"{sign}{amount // 100}.{amount % 100:02d}"

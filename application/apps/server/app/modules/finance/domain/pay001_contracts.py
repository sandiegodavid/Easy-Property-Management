"""Finance-owned PAY-001 late-fee integration contracts (FIN-009 Slice 5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.modules.finance.application.commands import canonical_uuid
from app.modules.finance.domain.late_fee_models import (
    MAX_MINOR_AMOUNT,
    _iso_date,
    _strict_int,
    _text,
    _validate_payment_method,
)
from app.modules.finance.domain.models import FinanceValidationError

ChargeKind = Literal["rent_expectation", "late_fee_assessment"]
AutopayMandateScope = Literal["rent_only", "rent_and_assessed_late_fees"]

VALID_CHARGE_KINDS = frozenset({"rent_expectation", "late_fee_assessment"})
VALID_AUTOPAY_MANDATE_SCOPES = frozenset({"rent_only", "rent_and_assessed_late_fees"})

ALLOCATION_ORDER_EXPLANATION = (
    "Oldest eligible unpaid rent periods first (by due date), "
    "then oldest eligible unpaid assessed late fees (by assessment date)."
)


@dataclass(frozen=True)
class ChargeAllocationTarget:
    charge_kind: ChargeKind
    target_id: str
    amount_minor: int

    def __post_init__(self) -> None:
        if self.charge_kind not in VALID_CHARGE_KINDS:
            raise FinanceValidationError(
                "chargeKind must be rent_expectation or late_fee_assessment."
            )
        object.__setattr__(self, "target_id", canonical_uuid(self.target_id))
        _strict_int(self.amount_minor, "Allocation amount", 1, MAX_MINOR_AMOUNT)

    def to_dict(self) -> dict[str, object]:
        return {
            "chargeKind": self.charge_kind,
            "targetId": self.target_id,
            "amountMinor": self.amount_minor,
        }


@dataclass(frozen=True)
class ChargeAllocationPreview:
    lease_id: str
    rent_total_minor: int
    late_fee_total_minor: int
    gross_total_minor: int
    allocations: tuple[ChargeAllocationTarget, ...]
    allocation_order_explanation: str
    rent_ledger_revision: int

    def to_dict(self) -> dict[str, object]:
        return {
            "leaseId": self.lease_id,
            "rentTotalMinor": self.rent_total_minor,
            "lateFeeTotalMinor": self.late_fee_total_minor,
            "grossTotalMinor": self.gross_total_minor,
            "allocations": [item.to_dict() for item in self.allocations],
            "allocationOrderExplanation": self.allocation_order_explanation,
            "rentLedgerRevision": self.rent_ledger_revision,
        }


@dataclass(frozen=True)
class AutopayOccurrencePlan:
    lease_id: str
    mandate_scope: AutopayMandateScope
    max_amount_minor: int
    rent_total_minor: int
    late_fee_total_minor: int
    gross_total_minor: int
    allocations: tuple[ChargeAllocationTarget, ...]
    allocation_order_explanation: str
    rent_ledger_revision: int

    def to_dict(self) -> dict[str, object]:
        return {
            "leaseId": self.lease_id,
            "mandateScope": self.mandate_scope,
            "maxAmountMinor": self.max_amount_minor,
            "rentTotalMinor": self.rent_total_minor,
            "lateFeeTotalMinor": self.late_fee_total_minor,
            "grossTotalMinor": self.gross_total_minor,
            "allocations": [item.to_dict() for item in self.allocations],
            "allocationOrderExplanation": self.allocation_order_explanation,
            "rentLedgerRevision": self.rent_ledger_revision,
        }


@dataclass(frozen=True)
class UnappliedProcessorFundsException:
    charge_kind: ChargeKind
    target_id: str
    excess_amount_minor: int
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "chargeKind": self.charge_kind,
            "targetId": self.target_id,
            "excessAmountMinor": self.excess_amount_minor,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ProviderPaymentOutcomeCommand:
    lease_id: str
    payment_attempt_id: str
    received_on: str
    allocations: tuple[ChargeAllocationTarget, ...]
    payment_method_kind: str = "online_payment"
    payment_method_label: str | None = None
    masked_reference: str | None = None
    other_payment_method_note: str | None = None
    received_by_party_id: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "lease_id", canonical_uuid(self.lease_id))
        object.__setattr__(self, "payment_attempt_id", canonical_uuid(self.payment_attempt_id))
        object.__setattr__(self, "received_on", _iso_date(self.received_on, "Received date"))
        if (
            not isinstance(self.allocations, tuple)
            or not self.allocations
            or len(self.allocations) > 200
            or any(not isinstance(item, ChargeAllocationTarget) for item in self.allocations)
        ):
            raise FinanceValidationError(
                "Provider payment outcome requires 1 to 200 typed charge allocations."
            )
        seen = {(item.charge_kind, item.target_id) for item in self.allocations}
        if len(seen) != len(self.allocations):
            raise FinanceValidationError(
                "Provider payment outcome cannot allocate the same charge target twice."
            )
        label, ref, other_note = _validate_payment_method(
            payment_method_kind=self.payment_method_kind,
            payment_method_label=self.payment_method_label,
            masked_reference=self.masked_reference,
            other_payment_method_note=self.other_payment_method_note,
        )
        object.__setattr__(self, "payment_method_label", label)
        object.__setattr__(self, "masked_reference", ref)
        object.__setattr__(self, "other_payment_method_note", other_note)
        if self.received_by_party_id is not None:
            object.__setattr__(
                self, "received_by_party_id", canonical_uuid(self.received_by_party_id)
            )
        object.__setattr__(self, "notes", _text(self.notes, "Notes", 4000))


@dataclass(frozen=True)
class PartialRefundAttribution:
    rent_refund_minor: int
    late_fee_refund_minor: int
    total_refund_minor: int
    waives_assessed_late_fees: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "rentRefundMinor": self.rent_refund_minor,
            "lateFeeRefundMinor": self.late_fee_refund_minor,
            "totalRefundMinor": self.total_refund_minor,
            "waivesAssessedLateFees": self.waives_assessed_late_fees,
        }


def validate_partial_refund_attribution(
    *,
    rent_refund_minor: int,
    late_fee_refund_minor: int,
    settled_rent_minor: int,
    settled_late_fee_minor: int,
) -> PartialRefundAttribution:
    """Validate explicit partial-refund split; refunding money never auto-waives late fees."""
    _strict_int(rent_refund_minor, "Rent refund amount", 0, MAX_MINOR_AMOUNT)
    _strict_int(late_fee_refund_minor, "Late-fee refund amount", 0, MAX_MINOR_AMOUNT)
    total = rent_refund_minor + late_fee_refund_minor
    if total <= 0:
        raise FinanceValidationError("Partial refund must attribute at least 1 cent.")
    if rent_refund_minor > settled_rent_minor:
        raise FinanceValidationError("Rent refund exceeds settled rent payment amount.")
    if late_fee_refund_minor > settled_late_fee_minor:
        raise FinanceValidationError("Late-fee refund exceeds settled late-fee payment amount.")
    return PartialRefundAttribution(
        rent_refund_minor=rent_refund_minor,
        late_fee_refund_minor=late_fee_refund_minor,
        total_refund_minor=total,
        waives_assessed_late_fees=False,
    )

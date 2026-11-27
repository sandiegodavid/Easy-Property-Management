"""FIN-009 late-fee policy domain models and strict validators."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from uuid import UUID

from app.modules.finance.domain.models import (
    PAYMENT_METHOD_KINDS,
    FinanceValidationError,
    ReceiptAllocationCommand,
    validate_masked_reference,
)

LATE_FEE_CALCULATION_BASES = frozenset(
    {"unpaid_rent_at_grace_end", "current_unpaid_rent", "scheduled_rent"}
)
LATE_FEE_FORMULA_KINDS = frozenset(
    {"fixed_flat", "percentage_once", "daily_flat", "fixed_plus_daily_flat"}
)
LATE_FEE_ROUNDING_MODES = frozenset({"half_up", "floor"})
LATE_FEE_POLICY_STATUSES = frozenset({"active", "superseded", "voided"})

MAX_MINOR_AMOUNT = 9_999_999_999


def _uuid(value: str, label: str) -> str:
    try:
        parsed = str(UUID(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise FinanceValidationError(f"{label} must be a UUID.") from error
    if not isinstance(value, str) or parsed != value:
        raise FinanceValidationError(f"{label} must be a canonical UUID.")
    return parsed


def _iso_date(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise FinanceValidationError(f"{label} must be an ISO date.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise FinanceValidationError(f"{label} must be an ISO date.") from error
    if parsed < date(1900, 1, 1):
        raise FinanceValidationError(f"{label} must be on or after 1900-01-01.")
    return parsed.isoformat()


def _text(value: str | None, label: str, limit: int, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise FinanceValidationError(f"{label} is required.")
        return None
    if not isinstance(value, str) or not (result := value.strip()) or len(result) > limit:
        raise FinanceValidationError(f"{label} must be between 1 and {limit} characters.")
    return result


def _strict_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise FinanceValidationError(f"{label} must be an integer between {minimum} and {maximum}.")
    return value


def _camel(data: dict[str, object]) -> dict[str, object]:
    return {
        "".join(word if i == 0 else word.capitalize() for i, word in enumerate(key.split("_"))): val
        for key, val in data.items()
    }


def windows_overlap(start_a: str, end_a: str | None, start_b: str, end_b: str | None) -> bool:
    """Return True iff half-open ISO date windows [start_a, end_a) and [start_b, end_b) overlap."""
    return (end_a is None or start_b < end_a) and (end_b is None or start_a < end_b)


@dataclass(frozen=True)
class CreateLateFeePolicyCommand:
    effective_on: str
    rule_basis: str
    grace_period_days: int
    calculation_basis: str
    formula_kind: str
    rounding_mode: str
    applies_to_prorated_periods: bool
    operator_confirmed: bool
    ends_on: str | None = None
    lease_term_id: str | None = None
    flat_amount_minor: int | None = None
    percentage_bps: int | None = None
    daily_amount_minor: int | None = None
    max_accrual_days: int | None = None
    per_period_cap_minor: int | None = None
    per_period_min_minor: int | None = None
    minimum_unpaid_threshold_minor: int = 0
    supersedes_policy_version_id: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if type(self.operator_confirmed) is not bool or not self.operator_confirmed:
            raise FinanceValidationError("Explicit operator confirmation is required.")
        effective_on = _iso_date(self.effective_on, "Effective date")
        object.__setattr__(self, "effective_on", effective_on)
        if self.ends_on is not None:
            ends_on = _iso_date(self.ends_on, "End date")
            if ends_on <= effective_on:
                raise FinanceValidationError("Policy end date must be after its effective date.")
            object.__setattr__(self, "ends_on", ends_on)
        if self.lease_term_id is not None:
            object.__setattr__(self, "lease_term_id", _uuid(self.lease_term_id, "Lease term ID"))
        if self.supersedes_policy_version_id is not None:
            object.__setattr__(
                self,
                "supersedes_policy_version_id",
                _uuid(self.supersedes_policy_version_id, "Superseded policy version ID"),
            )
        object.__setattr__(
            self, "rule_basis", _text(self.rule_basis, "Contractual rule basis", 500, required=True)
        )
        object.__setattr__(self, "notes", _text(self.notes, "Policy notes", 1000))
        _strict_int(self.grace_period_days, "Grace period days", 0, 60)
        if self.calculation_basis not in LATE_FEE_CALCULATION_BASES:
            raise FinanceValidationError("Calculation basis is invalid.")
        if self.formula_kind not in LATE_FEE_FORMULA_KINDS:
            raise FinanceValidationError("Formula kind is invalid.")
        if self.rounding_mode not in LATE_FEE_ROUNDING_MODES:
            raise FinanceValidationError("Rounding mode is invalid.")
        if type(self.applies_to_prorated_periods) is not bool:
            raise FinanceValidationError("Applies to prorated periods must be boolean.")
        _strict_int(
            self.minimum_unpaid_threshold_minor,
            "Minimum unpaid threshold",
            0,
            MAX_MINOR_AMOUNT,
        )
        if self.flat_amount_minor is not None:
            _strict_int(self.flat_amount_minor, "Flat amount", 1, MAX_MINOR_AMOUNT)
        if self.percentage_bps is not None:
            _strict_int(self.percentage_bps, "Percentage basis points", 1, 10_000)
        if self.daily_amount_minor is not None:
            _strict_int(self.daily_amount_minor, "Daily amount", 1, MAX_MINOR_AMOUNT)
        if self.max_accrual_days is not None:
            _strict_int(self.max_accrual_days, "Max accrual days", 1, 365)
        if self.per_period_cap_minor is not None:
            _strict_int(self.per_period_cap_minor, "Per-period cap", 1, MAX_MINOR_AMOUNT)
        if self.per_period_min_minor is not None:
            _strict_int(self.per_period_min_minor, "Per-period minimum", 1, MAX_MINOR_AMOUNT)
        if (
            self.per_period_min_minor is not None
            and self.per_period_cap_minor is not None
            and self.per_period_min_minor > self.per_period_cap_minor
        ):
            raise FinanceValidationError("Per-period minimum cannot exceed per-period cap.")
        self._validate_formula_pairing()

    def _validate_formula_pairing(self) -> None:
        kind = self.formula_kind
        if kind == "fixed_flat":
            if self.flat_amount_minor is None:
                raise FinanceValidationError("fixed_flat requires flatAmountMinor.")
            if (
                self.percentage_bps is not None
                or self.daily_amount_minor is not None
                or self.max_accrual_days is not None
            ):
                raise FinanceValidationError(
                    "fixed_flat does not accept percentageBps, dailyAmountMinor, or maxAccrualDays."
                )
        elif kind == "percentage_once":
            if self.percentage_bps is None:
                raise FinanceValidationError("percentage_once requires percentageBps.")
            if (
                self.flat_amount_minor is not None
                or self.daily_amount_minor is not None
                or self.max_accrual_days is not None
            ):
                raise FinanceValidationError(
                    "percentage_once does not accept flatAmountMinor, dailyAmountMinor, or maxAccrualDays."
                )
        elif kind == "daily_flat":
            if self.daily_amount_minor is None:
                raise FinanceValidationError("daily_flat requires dailyAmountMinor.")
            if self.flat_amount_minor is not None or self.percentage_bps is not None:
                raise FinanceValidationError(
                    "daily_flat does not accept flatAmountMinor or percentageBps."
                )
            if self.per_period_cap_minor is None and self.max_accrual_days is None:
                raise FinanceValidationError(
                    "daily_flat requires at least one of perPeriodCapMinor or maxAccrualDays."
                )
        elif kind == "fixed_plus_daily_flat":
            if self.flat_amount_minor is None or self.daily_amount_minor is None:
                raise FinanceValidationError(
                    "fixed_plus_daily_flat requires both flatAmountMinor and dailyAmountMinor."
                )
            if self.percentage_bps is not None:
                raise FinanceValidationError("fixed_plus_daily_flat does not accept percentageBps.")
            if self.per_period_cap_minor is None and self.max_accrual_days is None:
                raise FinanceValidationError(
                    "fixed_plus_daily_flat requires at least one of perPeriodCapMinor or maxAccrualDays."
                )

    def command_payload(self) -> dict[str, object]:
        return _camel(asdict(self))


@dataclass(frozen=True)
class CreateLeaseLateFeeWaiverCommand:
    reason: str
    confirmed: bool
    waive_open_assessments: bool = False
    internal_notes: str | None = None

    def __post_init__(self) -> None:
        if type(self.confirmed) is not bool or not self.confirmed:
            raise FinanceValidationError("Explicit confirmation is required.")
        if type(self.waive_open_assessments) is not bool:
            raise FinanceValidationError("waiveOpenAssessments must be boolean.")
        object.__setattr__(self, "reason", _text(self.reason, "Waiver reason", 1000, required=True))
        object.__setattr__(
            self, "internal_notes", _text(self.internal_notes, "Internal notes", 1000)
        )

    def command_payload(self) -> dict[str, object]:
        return _camel(asdict(self))


@dataclass(frozen=True)
class RevokeLeaseLateFeeWaiverCommand:
    reason: str
    confirmed: bool

    def __post_init__(self) -> None:
        if type(self.confirmed) is not bool or not self.confirmed:
            raise FinanceValidationError("Explicit confirmation is required.")
        object.__setattr__(self, "reason", _text(self.reason, "Revoke reason", 1000, required=True))

    def command_payload(self) -> dict[str, object]:
        return _camel(asdict(self))


@dataclass(frozen=True)
class LateFeeLeaseWaiver:
    id: str
    lease_id: str
    status: str
    reason: str
    internal_notes: str | None
    waived_at: str
    waived_by_actor: str
    waived_open_assessments_count: int
    revoked_at: str | None = None
    revoked_by_actor: str | None = None
    revoke_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "leaseId": self.lease_id,
            "status": self.status,
            "reason": self.reason,
            "internalNotes": self.internal_notes,
            "waivedAt": self.waived_at,
            "waivedByActor": self.waived_by_actor,
            "waivedOpenAssessmentsCount": self.waived_open_assessments_count,
            "revokedAt": self.revoked_at,
            "revokedByActor": self.revoked_by_actor,
            "revokeReason": self.revoke_reason,
        }


@dataclass(frozen=True)
class VoidLateFeePolicyCommand:
    confirmed: bool
    reason: str

    def __post_init__(self) -> None:
        if type(self.confirmed) is not bool or not self.confirmed:
            raise FinanceValidationError("Explicit confirmation is required.")
        object.__setattr__(self, "reason", _text(self.reason, "Void reason", 1000, required=True))


@dataclass(frozen=True)
class LateFeePolicyVersion:
    id: str
    lease_id: str
    lease_term_id: str | None
    version_number: int
    effective_on: str
    ends_on: str | None
    rule_basis: str
    grace_period_days: int
    calculation_basis: str
    formula_kind: str
    flat_amount_minor: int | None
    percentage_bps: int | None
    daily_amount_minor: int | None
    max_accrual_days: int | None
    per_period_cap_minor: int | None
    per_period_min_minor: int | None
    minimum_unpaid_threshold_minor: int
    rounding_mode: str
    applies_to_prorated_periods: bool
    status: str
    supersedes_policy_version_id: str | None
    notes: str | None
    operator_confirmed_at: str
    operator_confirmed_by_actor: str
    voided_at: str | None
    void_reason: str | None
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "applies_to_prorated_periods", bool(self.applies_to_prorated_periods)
        )

    def to_dict(self) -> dict[str, object]:
        return _camel(asdict(self))


def _sha256_hex(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise FinanceValidationError(
            f"{label} must be a 64-character lowercase SHA-256 hex digest."
        )
    return value


@dataclass(frozen=True)
class AssessLateFeeCommand:
    rent_expectation_id: str
    as_of_date: str
    preview_fingerprint: str
    operator_confirmed: bool
    acknowledge_processing_payments: bool = False
    processing_acknowledgment_reason: str | None = None
    internal_notes: str | None = None
    replaces_assessment_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.operator_confirmed) is not bool or not self.operator_confirmed:
            raise FinanceValidationError("Explicit operator confirmation is required.")
        object.__setattr__(
            self, "rent_expectation_id", _uuid(self.rent_expectation_id, "Rent expectation ID")
        )
        object.__setattr__(self, "as_of_date", _iso_date(self.as_of_date, "As-of date"))
        object.__setattr__(
            self,
            "preview_fingerprint",
            _sha256_hex(self.preview_fingerprint, "Preview fingerprint"),
        )
        if type(self.acknowledge_processing_payments) is not bool:
            raise FinanceValidationError("Processing payment acknowledgment must be boolean.")
        if self.acknowledge_processing_payments:
            object.__setattr__(
                self,
                "processing_acknowledgment_reason",
                _text(
                    self.processing_acknowledgment_reason,
                    "Processing acknowledgment reason",
                    1000,
                    required=True,
                ),
            )
        elif self.processing_acknowledgment_reason is not None:
            raise FinanceValidationError(
                "Processing acknowledgment reason requires acknowledgeProcessingPayments=true."
            )
        object.__setattr__(
            self, "internal_notes", _text(self.internal_notes, "Internal notes", 1000)
        )
        if self.replaces_assessment_id is not None:
            object.__setattr__(
                self,
                "replaces_assessment_id",
                _uuid(self.replaces_assessment_id, "Replaced assessment ID"),
            )

    def command_payload(self) -> dict[str, object]:
        return _camel(asdict(self))


@dataclass(frozen=True)
class WaiveLateFeeCommand:
    waived_amount_minor: int
    waived_on: str
    reason: str
    confirmed: bool
    internal_notes: str | None = None

    def __post_init__(self) -> None:
        if type(self.confirmed) is not bool or not self.confirmed:
            raise FinanceValidationError("Explicit confirmation is required.")
        _strict_int(self.waived_amount_minor, "Waived amount", 1, MAX_MINOR_AMOUNT)
        object.__setattr__(self, "waived_on", _iso_date(self.waived_on, "Waived date"))
        object.__setattr__(self, "reason", _text(self.reason, "Waiver reason", 1000, required=True))
        object.__setattr__(
            self, "internal_notes", _text(self.internal_notes, "Internal notes", 1000)
        )

    def command_payload(self) -> dict[str, object]:
        return _camel(asdict(self))


@dataclass(frozen=True)
class VoidLateFeeAssessmentCommand:
    confirmed: bool
    reason: str

    def __post_init__(self) -> None:
        if type(self.confirmed) is not bool or not self.confirmed:
            raise FinanceValidationError("Explicit confirmation is required.")
        object.__setattr__(self, "reason", _text(self.reason, "Void reason", 1000, required=True))


@dataclass(frozen=True)
class LateFeeAssessment:
    id: str
    lease_id: str
    rent_expectation_id: str
    policy_version_id: str
    occurrence_number: int
    as_of_date: str
    accrual_starts_on: str
    accrual_ends_on: str
    accrual_days: int
    assessed_amount_minor: int
    currency_code: str
    time_zone: str
    rule_basis_snapshot: str
    calculation_snapshot_json: str
    calculation_snapshot_hash: str
    processing_acknowledged: bool
    processing_acknowledgment_reason: str | None
    internal_notes: str | None
    replaces_assessment_id: str | None
    voided_at: str | None
    void_reason: str | None
    assessed_at: str
    assessed_by_actor: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "processing_acknowledged", bool(self.processing_acknowledged))

    def to_dict(self) -> dict[str, object]:
        return _camel(asdict(self))


@dataclass(frozen=True)
class LateFeeWaiver:
    id: str
    assessment_id: str
    lease_id: str
    waived_amount_minor: int
    currency_code: str
    reason: str
    internal_notes: str | None
    waived_on: str
    waived_at: str
    waived_by_actor: str

    def to_dict(self) -> dict[str, object]:
        return _camel(asdict(self))


def derive_assessment_settlement_status(
    *,
    assessed_amount_minor: int,
    waived_amount_minor: int,
    paid_amount_minor: int,
    voided_at: str | None,
) -> tuple[str, int]:
    """Return (settlementStatus, remainingBalanceMinor) with exact integer conservation."""
    if voided_at is not None:
        return ("voided", 0)
    remaining = max(0, assessed_amount_minor - waived_amount_minor - paid_amount_minor)
    if remaining == 0:
        if paid_amount_minor == 0 and waived_amount_minor >= assessed_amount_minor:
            return ("waived", 0)
        return ("paid", 0)
    if paid_amount_minor > 0 or waived_amount_minor > 0:
        return ("partially_paid", remaining)
    return ("unpaid", remaining)


def _validate_payment_method(
    *,
    payment_method_kind: str,
    payment_method_label: str | None,
    masked_reference: str | None,
    other_payment_method_note: str | None,
) -> tuple[str | None, str | None, str | None]:
    if not isinstance(payment_method_kind, str) or payment_method_kind not in PAYMENT_METHOD_KINDS:
        raise FinanceValidationError("Payment method kind is invalid.")
    label = _text(payment_method_label, "Payment method label", 100)
    ref = validate_masked_reference(masked_reference)
    if payment_method_kind == "other":
        other_note = _text(
            other_payment_method_note, "Other payment method note", 200, required=True
        )
    elif other_payment_method_note is not None:
        raise FinanceValidationError(
            "Other payment method note is allowed only for other payment methods."
        )
    else:
        other_note = None
    return label, ref, other_note


@dataclass(frozen=True)
class LateFeeReceiptAllocationCommand:
    assessment_id: str
    amount_minor: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "assessment_id", _uuid(self.assessment_id, "Assessment ID"))
        _strict_int(self.amount_minor, "Late-fee allocation amount", 1, MAX_MINOR_AMOUNT)


@dataclass(frozen=True)
class RecordLateFeeReceiptCommand:
    received_on: str
    amount_minor: int
    currency_code: str
    allocations: tuple[LateFeeReceiptAllocationCommand, ...]
    payment_method_kind: str
    payment_method_label: str | None = None
    masked_reference: str | None = None
    other_payment_method_note: str | None = None
    received_by_party_id: str | None = None
    replaces_receipt_id: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "received_on", _iso_date(self.received_on, "Received date"))
        if self.currency_code != "USD":
            raise FinanceValidationError("FIN-009 supports USD late-fee receipts only.")
        _strict_int(self.amount_minor, "Receipt amount", 1, MAX_MINOR_AMOUNT)
        if (
            not isinstance(self.allocations, tuple)
            or not self.allocations
            or len(self.allocations) > 100
            or any(
                not isinstance(item, LateFeeReceiptAllocationCommand) for item in self.allocations
            )
        ):
            raise FinanceValidationError("A late-fee receipt requires 1 to 100 valid allocations.")
        if len({item.assessment_id for item in self.allocations}) != len(self.allocations):
            raise FinanceValidationError("A late-fee receipt cannot allocate an assessment twice.")
        if sum(item.amount_minor for item in self.allocations) != self.amount_minor:
            raise FinanceValidationError(
                "Late-fee allocations must equal the late-fee receipt amount."
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
                self, "received_by_party_id", _uuid(self.received_by_party_id, "Recipient party ID")
            )
        if self.replaces_receipt_id is not None:
            object.__setattr__(
                self,
                "replaces_receipt_id",
                _uuid(self.replaces_receipt_id, "Replaced receipt ID"),
            )
        object.__setattr__(self, "notes", _text(self.notes, "Receipt notes", 4000))

    def command_payload(self) -> dict[str, object]:
        data = _camel(asdict(self))
        data["allocations"] = [
            {"assessmentId": item.assessment_id, "amountMinor": item.amount_minor}
            for item in self.allocations
        ]
        return data


@dataclass(frozen=True)
class RecordCombinedReceiptCommand:
    received_on: str
    currency_code: str
    rent_allocations: tuple[ReceiptAllocationCommand, ...]
    late_fee_allocations: tuple[LateFeeReceiptAllocationCommand, ...]
    payment_method_kind: str
    payment_method_label: str | None = None
    masked_reference: str | None = None
    other_payment_method_note: str | None = None
    received_by_party_id: str | None = None
    notes: str | None = None
    duplicate_confirmed: bool = False
    duplicate_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "received_on", _iso_date(self.received_on, "Received date"))
        if self.currency_code != "USD":
            raise FinanceValidationError("Combined receipts support USD only.")
        if (
            not isinstance(self.rent_allocations, tuple)
            or not self.rent_allocations
            or len(self.rent_allocations) > 100
            or any(not isinstance(item, ReceiptAllocationCommand) for item in self.rent_allocations)
        ):
            raise FinanceValidationError("Combined receipt requires 1 to 100 rent allocations.")
        if len({item.expectation_id for item in self.rent_allocations}) != len(
            self.rent_allocations
        ):
            raise FinanceValidationError("A combined receipt cannot allocate an expectation twice.")
        if (
            not isinstance(self.late_fee_allocations, tuple)
            or not self.late_fee_allocations
            or len(self.late_fee_allocations) > 100
            or any(
                not isinstance(item, LateFeeReceiptAllocationCommand)
                for item in self.late_fee_allocations
            )
        ):
            raise FinanceValidationError("Combined receipt requires 1 to 100 late-fee allocations.")
        if len({item.assessment_id for item in self.late_fee_allocations}) != len(
            self.late_fee_allocations
        ):
            raise FinanceValidationError("A combined receipt cannot allocate an assessment twice.")
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
                self, "received_by_party_id", _uuid(self.received_by_party_id, "Recipient party ID")
            )
        object.__setattr__(self, "notes", _text(self.notes, "Receipt notes", 4000))
        if type(self.duplicate_confirmed) is not bool:
            raise FinanceValidationError("Duplicate confirmation must be boolean.")
        if self.duplicate_confirmed:
            object.__setattr__(
                self,
                "duplicate_reason",
                _text(self.duplicate_reason, "Duplicate confirmation reason", 1000, required=True),
            )
        elif self.duplicate_reason is not None:
            raise FinanceValidationError("Duplicate confirmation reason requires confirmation.")

    @property
    def rent_amount_minor(self) -> int:
        return sum(item.amount_minor for item in self.rent_allocations)

    @property
    def late_fee_amount_minor(self) -> int:
        return sum(item.amount_minor for item in self.late_fee_allocations)

    @property
    def total_amount_minor(self) -> int:
        return self.rent_amount_minor + self.late_fee_amount_minor

    def command_payload(self) -> dict[str, object]:
        data = _camel(asdict(self))
        data["rentAllocations"] = [
            {"expectationId": item.expectation_id, "amountMinor": item.amount_minor}
            for item in self.rent_allocations
        ]
        data["lateFeeAllocations"] = [
            {"assessmentId": item.assessment_id, "amountMinor": item.amount_minor}
            for item in self.late_fee_allocations
        ]
        return data


@dataclass(frozen=True)
class VoidLateFeeReceiptCommand:
    confirmed: bool
    reason: str

    def __post_init__(self) -> None:
        if type(self.confirmed) is not bool or not self.confirmed:
            raise FinanceValidationError("Explicit confirmation is required.")
        object.__setattr__(self, "reason", _text(self.reason, "Void reason", 1000, required=True))


@dataclass(frozen=True)
class LateFeeReceipt:
    id: str
    lease_id: str
    idempotency_key: str
    payment_batch_id: str | None
    received_on: str
    amount_minor: int
    currency_code: str
    payment_method_kind: str
    payment_method_label: str | None
    masked_reference: str | None
    other_payment_method_note: str | None
    received_by_party_id: str | None
    replaces_receipt_id: str | None
    notes: str | None
    voided_at: str | None
    void_reason: str | None
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return _camel(asdict(self))

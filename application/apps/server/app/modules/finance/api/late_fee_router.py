"""Typed FIN-009 late-fee policy HTTP API (Slice 1)."""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
)

from app.modules.finance.api.conflicts import FinanceConflictResponse
from app.modules.finance.application.late_fee_service import LateFeeService
from app.modules.finance.domain.late_fee_models import (
    AssessLateFeeCommand,
    CreateLateFeePolicyCommand,
    LateFeeReceiptAllocationCommand,
    RecordCombinedReceiptCommand,
    RecordLateFeeReceiptCommand,
    VoidLateFeeAssessmentCommand,
    VoidLateFeePolicyCommand,
    VoidLateFeeReceiptCommand,
    WaiveLateFeeCommand,
)
from app.modules.finance.domain.models import (
    SAFE_MASKED_REFERENCE_PATTERN,
    FinanceConflictError,
    FinanceError,
    FinanceNotFoundError,
    FinanceValidationError,
    ReceiptAllocationCommand,
)
from app.modules.workspace.application.runtime import WorkspaceRuntime
from app.platform.api_errors import domain_problem, workspace_unavailable


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CommandInput(Contract):
    expectedRevision: StrictInt = Field(ge=0)
    idempotencyKey: UUID


class CreateLateFeePolicyInput(CommandInput):
    effectiveOn: date
    endsOn: date | None = None
    leaseTermId: UUID | None = None
    ruleBasis: str = Field(min_length=1, max_length=500)
    gracePeriodDays: StrictInt = Field(ge=0, le=60)
    calculationBasis: Literal["unpaid_rent_at_grace_end", "current_unpaid_rent", "scheduled_rent"]
    formulaKind: Literal["fixed_flat", "percentage_once", "daily_flat", "fixed_plus_daily_flat"]
    flatAmountMinor: StrictInt | None = Field(default=None, ge=1, le=9_999_999_999)
    percentageBps: StrictInt | None = Field(default=None, ge=1, le=10_000)
    dailyAmountMinor: StrictInt | None = Field(default=None, ge=1, le=9_999_999_999)
    maxAccrualDays: StrictInt | None = Field(default=None, ge=1, le=365)
    perPeriodCapMinor: StrictInt | None = Field(default=None, ge=1, le=9_999_999_999)
    perPeriodMinMinor: StrictInt | None = Field(default=None, ge=1, le=9_999_999_999)
    minimumUnpaidThresholdMinor: StrictInt = Field(default=0, ge=0, le=9_999_999_999)
    roundingMode: Literal["half_up", "floor"]
    appliesToProratedPeriods: StrictBool
    supersedesPolicyVersionId: UUID | None = None
    notes: str | None = Field(default=None, max_length=1000)
    operatorConfirmed: StrictBool


class VoidLateFeePolicyInput(CommandInput):
    confirmed: StrictBool
    reason: str = Field(min_length=1, max_length=1000)


class LateFeePolicyResponse(Contract):
    id: UUID
    leaseId: UUID
    leaseTermId: UUID | None
    versionNumber: StrictInt = Field(ge=1)
    effectiveOn: date
    endsOn: date | None
    ruleBasis: str
    gracePeriodDays: StrictInt
    calculationBasis: Literal["unpaid_rent_at_grace_end", "current_unpaid_rent", "scheduled_rent"]
    formulaKind: Literal["fixed_flat", "percentage_once", "daily_flat", "fixed_plus_daily_flat"]
    flatAmountMinor: StrictInt | None
    percentageBps: StrictInt | None
    dailyAmountMinor: StrictInt | None
    maxAccrualDays: StrictInt | None
    perPeriodCapMinor: StrictInt | None
    perPeriodMinMinor: StrictInt | None
    minimumUnpaidThresholdMinor: StrictInt
    roundingMode: Literal["half_up", "floor"]
    appliesToProratedPeriods: StrictBool
    status: Literal["active", "superseded", "voided"]
    supersedesPolicyVersionId: UUID | None
    notes: str | None
    operatorConfirmedAt: AwareDatetime
    operatorConfirmedByActor: str
    voidedAt: AwareDatetime | None
    voidReason: str | None
    createdAt: AwareDatetime


class LateFeePolicyListResponse(Contract):
    leaseId: UUID
    rentLedgerRevision: StrictInt = Field(ge=0)
    items: list[LateFeePolicyResponse]


class LateFeePolicyMutationResponse(LateFeePolicyResponse):
    rentLedgerRevision: StrictInt = Field(ge=0)
    operationId: UUID


class LateFeePreviewInput(Contract):
    asOfDate: date | None = None
    rentExpectationId: UUID | None = None
    cursor: str | None = None


class CalculationStepResponse(Contract):
    stepCode: str
    label: str
    inputs: dict[str, object]
    resultMinor: StrictInt | None
    expression: str


class ScheduledPrepaidChecksWarningResponse(Contract):
    count: StrictInt = Field(ge=0)
    totalMinor: StrictInt = Field(ge=0)
    checkDates: list[date]


class ProcessingPaymentsWarningResponse(Contract):
    count: StrictInt = Field(ge=0)
    totalMinor: StrictInt = Field(ge=0)
    earliestSubmittedOn: date | None


class LateFeePreviewItemResponse(Contract):
    rentExpectationId: UUID
    periodStartsOn: date
    periodEndsOn: date
    dueOn: date
    isProrated: StrictBool
    expectedAmountMinor: StrictInt = Field(gt=0)
    policyVersionId: UUID | None
    policyVersionNumber: StrictInt | None
    ruleBasis: str | None
    formulaKind: (
        Literal["fixed_flat", "percentage_once", "daily_flat", "fixed_plus_daily_flat"] | None
    )
    calculationBasis: (
        Literal["unpaid_rent_at_grace_end", "current_unpaid_rent", "scheduled_rent"] | None
    )
    roundingMode: Literal["half_up", "floor"] | None
    eligibilityStatus: Literal[
        "eligible",
        "no_applicable_policy",
        "excluded_prorated_period",
        "within_grace_period",
        "paid_in_full",
        "below_minimum_threshold",
        "already_assessed",
        "already_assessed_through_date",
        "max_accrual_days_reached",
        "period_cap_reached",
        "calculated_zero",
    ]
    graceEndsOn: date | None
    firstEligibleOn: date | None
    paidThroughGraceMinor: StrictInt = Field(ge=0)
    paidAfterGraceThroughAsOfMinor: StrictInt = Field(ge=0)
    unpaidAtGraceEndMinor: StrictInt | None = Field(default=None, ge=0)
    unpaidAsOfDateMinor: StrictInt | None = Field(default=None, ge=0)
    basisAmountMinor: StrictInt | None = Field(default=None, ge=0)
    previouslyAssessedMinor: StrictInt = Field(ge=0)
    occurrenceNumber: StrictInt | None = Field(default=None, ge=1)
    accrualStartsOn: date | None
    accrualEndsOn: date | None
    accrualDays: StrictInt | None = Field(default=None, ge=1)
    calculatedAmountMinor: StrictInt = Field(ge=0)
    currencyCode: Literal["USD"]
    scheduledPrepaidChecks: ScheduledPrepaidChecksWarningResponse
    processingPayments: ProcessingPaymentsWarningResponse
    requiresProcessingAcknowledgment: StrictBool
    calculationSteps: list[CalculationStepResponse]
    calculationSnapshot: dict[str, object]
    previewFingerprint: str | None


class LateFeePreviewResponse(Contract):
    previewOnly: Literal[True]
    leaseId: UUID
    timeZone: str
    asOf: AwareDatetime
    asOfDate: date
    currentPropertyLocalDate: date
    futureProjection: StrictBool
    rentLedgerRevision: StrictInt = Field(ge=0)
    items: list[LateFeePreviewItemResponse]
    nextCursor: str | None = None


class AssessLateFeeInput(CommandInput):
    rentExpectationId: UUID
    asOfDate: date
    previewFingerprint: str = Field(min_length=64, max_length=64)
    operatorConfirmed: StrictBool
    acknowledgeProcessingPayments: StrictBool = False
    processingAcknowledgmentReason: str | None = Field(default=None, max_length=1000)
    internalNotes: str | None = Field(default=None, max_length=1000)
    replacesAssessmentId: UUID | None = None


class WaiveLateFeeInput(CommandInput):
    waivedAmountMinor: StrictInt = Field(ge=1, le=9_999_999_999)
    waivedOn: date
    reason: str = Field(min_length=1, max_length=1000)
    confirmed: StrictBool
    internalNotes: str | None = Field(default=None, max_length=1000)


class VoidLateFeeAssessmentInput(CommandInput):
    confirmed: StrictBool
    reason: str = Field(min_length=1, max_length=1000)


class LateFeeWaiverResponse(Contract):
    id: UUID
    assessmentId: UUID
    leaseId: UUID
    waivedAmountMinor: StrictInt = Field(ge=1)
    currencyCode: Literal["USD"]
    reason: str
    internalNotes: str | None
    waivedOn: date
    waivedAt: AwareDatetime
    waivedByActor: str


class LateFeeAllocationSummaryResponse(Contract):
    allocationId: UUID
    receiptId: UUID
    receivedOn: date
    amountMinor: StrictInt = Field(ge=1)
    receiptLifecycleStatus: Literal["active", "voided"]


class LateFeeAssessmentSummaryResponse(Contract):
    id: UUID
    leaseId: UUID
    rentExpectationId: UUID
    policyVersionId: UUID
    occurrenceNumber: StrictInt = Field(ge=1)
    asOfDate: date
    accrualStartsOn: date
    accrualEndsOn: date
    accrualDays: StrictInt = Field(ge=1)
    assessedAmountMinor: StrictInt = Field(ge=1)
    waivedAmountMinor: StrictInt = Field(ge=0)
    paidAmountMinor: StrictInt = Field(ge=0)
    remainingBalanceMinor: StrictInt = Field(ge=0)
    settlementStatus: Literal["unpaid", "partially_paid", "paid", "waived", "voided"]
    currencyCode: Literal["USD"]
    timeZone: str
    ruleBasisSnapshot: str
    processingAcknowledged: StrictBool
    processingAcknowledgmentReason: str | None
    internalNotes: str | None
    replacesAssessmentId: UUID | None
    replacedByAssessmentId: UUID | None
    voidedAt: AwareDatetime | None
    voidReason: str | None
    assessedAt: AwareDatetime
    assessedByActor: str
    sourceDriftWarning: StrictBool


class LateFeeAssessmentDetailResponse(LateFeeAssessmentSummaryResponse):
    calculationSnapshotHash: str
    calculationSnapshot: dict[str, object]
    calculationSteps: list[CalculationStepResponse]
    waivers: list[LateFeeWaiverResponse]
    allocations: list[LateFeeAllocationSummaryResponse]
    rentLedgerRevision: StrictInt = Field(ge=0)


class LateFeeAssessmentMutationResponse(LateFeeAssessmentDetailResponse):
    operationId: UUID


class LateFeeAssessmentPageResponse(Contract):
    items: list[LateFeeAssessmentSummaryResponse]
    nextCursor: str | None


class LateFeeReceiptAllocationInput(Contract):
    assessmentId: UUID
    amountMinor: StrictInt = Field(ge=1, le=9_999_999_999)


class RentAllocationInput(Contract):
    expectationId: UUID
    amountMinor: StrictInt = Field(ge=1, le=9_999_999_999)


class RecordLateFeeReceiptInput(CommandInput):
    receivedOn: date
    amountMinor: StrictInt = Field(ge=1, le=9_999_999_999)
    currencyCode: Literal["USD"]
    allocations: list[LateFeeReceiptAllocationInput] = Field(min_length=1, max_length=100)
    paymentMethodKind: Literal[
        "automatic_bank_payment", "bank_transfer", "check", "cash", "online_payment", "other"
    ]
    paymentMethodLabel: str | None = Field(default=None, max_length=100)
    maskedReference: str | None = Field(
        default=None, max_length=80, pattern=SAFE_MASKED_REFERENCE_PATTERN
    )
    otherPaymentMethodNote: str | None = Field(default=None, max_length=200)
    receivedByPartyId: UUID | None = None
    replacesReceiptId: UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("maskedReference", mode="before")
    @classmethod
    def trim_masked_reference(cls, value):
        return value.strip() if isinstance(value, str) else value


class RecordCombinedReceiptInput(CommandInput):
    receivedOn: date
    currencyCode: Literal["USD"]
    rentAllocations: list[RentAllocationInput] = Field(min_length=1, max_length=100)
    lateFeeAllocations: list[LateFeeReceiptAllocationInput] = Field(min_length=1, max_length=100)
    paymentMethodKind: Literal[
        "automatic_bank_payment", "bank_transfer", "check", "cash", "online_payment", "other"
    ]
    paymentMethodLabel: str | None = Field(default=None, max_length=100)
    maskedReference: str | None = Field(
        default=None, max_length=80, pattern=SAFE_MASKED_REFERENCE_PATTERN
    )
    otherPaymentMethodNote: str | None = Field(default=None, max_length=200)
    receivedByPartyId: UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)
    duplicateConfirmed: StrictBool = False
    duplicateReason: str | None = Field(default=None, max_length=1000)

    @field_validator("maskedReference", mode="before")
    @classmethod
    def trim_masked_reference(cls, value):
        return value.strip() if isinstance(value, str) else value


class VoidLateFeeReceiptInput(CommandInput):
    confirmed: StrictBool
    reason: str = Field(min_length=1, max_length=1000)


class LateFeeReceiptAllocationResponse(Contract):
    id: UUID
    receiptId: UUID
    assessmentId: UUID
    amountMinor: StrictInt = Field(ge=1)
    createdAt: AwareDatetime


class LateFeeReceiptResponse(Contract):
    id: UUID
    leaseId: UUID
    idempotencyKey: UUID
    paymentBatchId: UUID | None
    receivedOn: date
    amountMinor: StrictInt = Field(ge=1)
    currencyCode: Literal["USD"]
    paymentMethodKind: Literal[
        "automatic_bank_payment", "bank_transfer", "check", "cash", "online_payment", "other"
    ]
    paymentMethodLabel: str | None
    maskedReference: str | None
    otherPaymentMethodNote: str | None
    receivedByPartyId: UUID | None
    replacesReceiptId: UUID | None
    replacedByReceiptId: UUID | None = None
    rentLedgerRevision: StrictInt | None = None
    notes: str | None
    voidedAt: AwareDatetime | None
    voidReason: str | None
    createdAt: AwareDatetime
    allocations: list[LateFeeReceiptAllocationResponse]


class LateFeeReceiptMutationResponse(LateFeeReceiptResponse):
    rentLedgerRevision: StrictInt = Field(ge=0)
    operationId: UUID


class CombinedRentAllocationResponse(Contract):
    id: UUID
    receiptId: UUID
    expectationId: UUID
    amountMinor: StrictInt = Field(ge=1)
    createdAt: AwareDatetime


class CombinedRentReceiptResponse(Contract):
    id: UUID
    leaseId: UUID
    idempotencyKey: UUID
    paymentBatchId: UUID
    receivedOn: date
    amountMinor: StrictInt = Field(ge=1)
    currencyCode: Literal["USD"]
    paymentMethodKind: Literal[
        "automatic_bank_payment", "bank_transfer", "check", "cash", "online_payment", "other"
    ]
    paymentMethodLabel: str | None
    maskedReference: str | None
    otherPaymentMethodNote: str | None
    receivedByPartyId: UUID | None
    replacesReceiptId: UUID | None
    replacedByReceiptId: UUID | None = None
    rentLedgerRevision: StrictInt | None = None
    notes: str | None
    voidedAt: AwareDatetime | None
    voidReason: str | None
    createdAt: AwareDatetime
    allocations: list[CombinedRentAllocationResponse]


class CombinedReceiptMutationResponse(Contract):
    paymentBatchId: UUID
    leaseId: UUID
    receivedOn: date
    rentAmountMinor: StrictInt = Field(ge=1)
    lateFeeAmountMinor: StrictInt = Field(ge=1)
    totalAmountMinor: StrictInt = Field(ge=2)
    currencyCode: Literal["USD"]
    rentReceipt: CombinedRentReceiptResponse
    lateFeeReceipt: LateFeeReceiptResponse
    rentLedgerRevision: StrictInt = Field(ge=0)
    operationId: UUID


def build_router(service: LateFeeService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(tags=["finance"], responses={409: {"model": FinanceConflictResponse}})

    def ready(write: bool = False) -> None:
        if not runtime.ready or runtime.error:
            raise workspace_unavailable(str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:
            raise workspace_unavailable("Workspace writer lock is unavailable.")

    def invoke(fn):
        try:
            return fn()
        except FinanceNotFoundError as error:
            raise domain_problem(error, status_code=404, code="late_fee_not_found") from error
        except FinanceConflictError as error:
            raise domain_problem(error, status_code=409, **error.details) from error
        except FinanceValidationError as error:
            raise domain_problem(
                error, status_code=422, code="late_fee_validation_error"
            ) from error
        except FinanceError as error:
            raise domain_problem(
                error, status_code=422, code="late_fee_validation_error"
            ) from error

    @router.get(
        "/api/leases/{lease_id}/late-fee-policies",
        response_model=LateFeePolicyListResponse,
        operation_id="listLateFeePolicies",
    )
    def list_policies(lease_id: UUID):
        ready()
        return invoke(lambda: service.list_policies(str(lease_id)))

    @router.post(
        "/api/leases/{lease_id}/late-fee-policies",
        response_model=LateFeePolicyMutationResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createLateFeePolicy",
    )
    def create_policy(lease_id: UUID, data: CreateLateFeePolicyInput):
        ready(True)
        return invoke(
            lambda: service.create_policy(
                str(lease_id),
                CreateLateFeePolicyCommand(
                    effective_on=data.effectiveOn.isoformat(),
                    ends_on=data.endsOn.isoformat() if data.endsOn else None,
                    lease_term_id=str(data.leaseTermId) if data.leaseTermId else None,
                    rule_basis=data.ruleBasis,
                    grace_period_days=data.gracePeriodDays,
                    calculation_basis=data.calculationBasis,
                    formula_kind=data.formulaKind,
                    flat_amount_minor=data.flatAmountMinor,
                    percentage_bps=data.percentageBps,
                    daily_amount_minor=data.dailyAmountMinor,
                    max_accrual_days=data.maxAccrualDays,
                    per_period_cap_minor=data.perPeriodCapMinor,
                    per_period_min_minor=data.perPeriodMinMinor,
                    minimum_unpaid_threshold_minor=data.minimumUnpaidThresholdMinor,
                    rounding_mode=data.roundingMode,
                    applies_to_prorated_periods=data.appliesToProratedPeriods,
                    supersedes_policy_version_id=(
                        str(data.supersedesPolicyVersionId)
                        if data.supersedesPolicyVersionId
                        else None
                    ),
                    notes=data.notes,
                    operator_confirmed=data.operatorConfirmed,
                ),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/leases/{lease_id}/late-fee-policies/{policy_version_id}/void",
        response_model=LateFeePolicyMutationResponse,
        operation_id="voidLateFeePolicy",
    )
    def void_policy(lease_id: UUID, policy_version_id: UUID, data: VoidLateFeePolicyInput):
        ready(True)
        return invoke(
            lambda: service.void_policy(
                str(lease_id),
                str(policy_version_id),
                VoidLateFeePolicyCommand(confirmed=data.confirmed, reason=data.reason),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/leases/{lease_id}/late-fees/preview",
        response_model=LateFeePreviewResponse,
        operation_id="previewLateFees",
    )
    def preview_late_fees(lease_id: UUID, data: LateFeePreviewInput):
        ready()
        return invoke(
            lambda: service.preview_late_fees(
                str(lease_id),
                as_of_date=data.asOfDate.isoformat() if data.asOfDate else None,
                rent_expectation_id=(
                    str(data.rentExpectationId) if data.rentExpectationId else None
                ),
                cursor=data.cursor,
            )
        )

    @router.post(
        "/api/leases/{lease_id}/late-fee-assessments",
        response_model=LateFeeAssessmentMutationResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="assessLateFee",
    )
    def assess_late_fee(lease_id: UUID, data: AssessLateFeeInput):
        ready(True)
        return invoke(
            lambda: service.assess_late_fee(
                str(lease_id),
                AssessLateFeeCommand(
                    rent_expectation_id=str(data.rentExpectationId),
                    as_of_date=data.asOfDate.isoformat(),
                    preview_fingerprint=data.previewFingerprint,
                    operator_confirmed=data.operatorConfirmed,
                    acknowledge_processing_payments=data.acknowledgeProcessingPayments,
                    processing_acknowledgment_reason=data.processingAcknowledgmentReason,
                    internal_notes=data.internalNotes,
                    replaces_assessment_id=(
                        str(data.replacesAssessmentId) if data.replacesAssessmentId else None
                    ),
                ),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.get(
        "/api/leases/{lease_id}/late-fee-assessments",
        response_model=LateFeeAssessmentPageResponse,
        operation_id="listLeaseLateFeeAssessments",
    )
    def list_lease_assessments(
        lease_id: UUID,
        settlementStatus: Literal["unpaid", "partially_paid", "paid", "waived", "voided"]
        | None = None,
        includeVoided: bool = False,
        cursor: str | None = None,
        pageSize: int = Query(50, ge=1, le=100),
    ):
        ready()
        return invoke(
            lambda: service.list_assessments(
                lease_id=str(lease_id),
                settlement_status=settlementStatus,
                include_voided=includeVoided,
                cursor=cursor,
                page_size=pageSize,
            )
        )

    @router.get(
        "/api/late-fee-assessments",
        response_model=LateFeeAssessmentPageResponse,
        operation_id="listLateFeeAssessments",
    )
    def list_portfolio_assessments(
        propertyId: UUID | None = None,
        leaseId: UUID | None = None,
        settlementStatus: Literal["unpaid", "partially_paid", "paid", "waived", "voided"]
        | None = None,
        includeVoided: bool = False,
        cursor: str | None = None,
        pageSize: int = Query(50, ge=1, le=100),
    ):
        ready()
        return invoke(
            lambda: service.list_assessments(
                lease_id=str(leaseId) if leaseId else None,
                property_id=str(propertyId) if propertyId else None,
                settlement_status=settlementStatus,
                include_voided=includeVoided,
                cursor=cursor,
                page_size=pageSize,
            )
        )

    @router.get(
        "/api/late-fee-assessments/{assessment_id}",
        response_model=LateFeeAssessmentDetailResponse,
        operation_id="getLateFeeAssessment",
    )
    def get_assessment(assessment_id: UUID):
        ready()
        return invoke(lambda: service.get_assessment(str(assessment_id)))

    @router.post(
        "/api/late-fee-assessments/{assessment_id}/waive",
        response_model=LateFeeAssessmentMutationResponse,
        operation_id="waiveLateFee",
    )
    def waive_assessment(assessment_id: UUID, data: WaiveLateFeeInput):
        ready(True)
        return invoke(
            lambda: service.waive_late_fee(
                str(assessment_id),
                WaiveLateFeeCommand(
                    waived_amount_minor=data.waivedAmountMinor,
                    waived_on=data.waivedOn.isoformat(),
                    reason=data.reason,
                    confirmed=data.confirmed,
                    internal_notes=data.internalNotes,
                ),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/late-fee-assessments/{assessment_id}/void",
        response_model=LateFeeAssessmentMutationResponse,
        operation_id="voidLateFeeAssessment",
    )
    def void_assessment(assessment_id: UUID, data: VoidLateFeeAssessmentInput):
        ready(True)
        return invoke(
            lambda: service.void_assessment(
                str(assessment_id),
                VoidLateFeeAssessmentCommand(confirmed=data.confirmed, reason=data.reason),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/leases/{lease_id}/late-fee-receipts",
        response_model=LateFeeReceiptMutationResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="recordLateFeeReceipt",
    )
    def record_late_fee_receipt(lease_id: UUID, data: RecordLateFeeReceiptInput):
        ready(True)
        return invoke(
            lambda: service.record_late_fee_receipt(
                str(lease_id),
                RecordLateFeeReceiptCommand(
                    received_on=data.receivedOn.isoformat(),
                    amount_minor=data.amountMinor,
                    currency_code=data.currencyCode,
                    allocations=tuple(
                        LateFeeReceiptAllocationCommand(str(item.assessmentId), item.amountMinor)
                        for item in data.allocations
                    ),
                    payment_method_kind=data.paymentMethodKind,
                    payment_method_label=data.paymentMethodLabel,
                    masked_reference=data.maskedReference,
                    other_payment_method_note=data.otherPaymentMethodNote,
                    received_by_party_id=(
                        str(data.receivedByPartyId) if data.receivedByPartyId else None
                    ),
                    replaces_receipt_id=(
                        str(data.replacesReceiptId) if data.replacesReceiptId else None
                    ),
                    notes=data.notes,
                ),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/leases/{lease_id}/combined-receipts",
        response_model=CombinedReceiptMutationResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="recordCombinedReceipt",
    )
    def record_combined_receipt(lease_id: UUID, data: RecordCombinedReceiptInput):
        ready(True)
        return invoke(
            lambda: service.record_combined_receipt(
                str(lease_id),
                RecordCombinedReceiptCommand(
                    received_on=data.receivedOn.isoformat(),
                    currency_code=data.currencyCode,
                    rent_allocations=tuple(
                        ReceiptAllocationCommand(str(item.expectationId), item.amountMinor)
                        for item in data.rentAllocations
                    ),
                    late_fee_allocations=tuple(
                        LateFeeReceiptAllocationCommand(str(item.assessmentId), item.amountMinor)
                        for item in data.lateFeeAllocations
                    ),
                    payment_method_kind=data.paymentMethodKind,
                    payment_method_label=data.paymentMethodLabel,
                    masked_reference=data.maskedReference,
                    other_payment_method_note=data.otherPaymentMethodNote,
                    received_by_party_id=(
                        str(data.receivedByPartyId) if data.receivedByPartyId else None
                    ),
                    notes=data.notes,
                    duplicate_confirmed=data.duplicateConfirmed,
                    duplicate_reason=data.duplicateReason,
                ),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.get(
        "/api/late-fee-receipts/{receipt_id}",
        response_model=LateFeeReceiptResponse,
        operation_id="getLateFeeReceipt",
    )
    def get_late_fee_receipt(receipt_id: UUID):
        ready()
        return invoke(lambda: service.get_late_fee_receipt(str(receipt_id)))

    @router.post(
        "/api/late-fee-receipts/{receipt_id}/void",
        response_model=LateFeeReceiptMutationResponse,
        operation_id="voidLateFeeReceipt",
    )
    def void_late_fee_receipt(receipt_id: UUID, data: VoidLateFeeReceiptInput):
        ready(True)
        return invoke(
            lambda: service.void_late_fee_receipt(
                str(receipt_id),
                VoidLateFeeReceiptCommand(confirmed=data.confirmed, reason=data.reason),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    return router

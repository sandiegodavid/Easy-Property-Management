"""Typed FIN-001 HTTP contract."""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt

from app.modules.finance.api.conflicts import FinanceConflictResponse

from app.platform.api_errors import domain_problem, workspace_unavailable

from app.modules.finance.application.service import FinanceService
from app.modules.finance.api.expense_router import ExpenseMutationResponse, RefundMutationResponse
from app.modules.finance.api.prepaid_check_router import PrepaidCheckMutationResponse
from app.modules.finance.api.deposit_router import (
    DepositMutationResponse,
    ReceiptMutationResponse as DepositReceiptMutationResponse,
    SettlementMutationResponse,
    DeductionLineMutationResponse,
    CreditMutationResponse,
    DeductionSourceMutationResponse,
    RefundMutationResponse as DepositRefundMutationResponse,
    DeletedMutationResponse,
)
from app.modules.finance.domain.models import (
    FinanceConflictError,
    FinanceError,
    FinanceNotFoundError,
    FinanceValidationError,
    ReceiptAllocationCommand,
    RecordReceiptCommand,
    SynchronizeExpectationsCommand,
    TimelinessReviewCommand,
    VoidCommand,
)
from app.modules.workspace.application.runtime import WorkspaceRuntime


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CommandInput(Contract):
    expectedRevision: StrictInt = Field(ge=0)
    idempotencyKey: UUID


class SynchronizeInput(CommandInput):
    leaseTermId: UUID
    throughOn: date
    scheduleAnchorOn: date | None = None
    responsibilityEndsOnOverride: date | None = None
    overrideReason: str | None = Field(None, max_length=1000)
    overrideConfirmed: StrictBool = False


class AllocationInput(Contract):
    expectationId: UUID
    amountMinor: StrictInt = Field(gt=0)


class ReceiptInput(Contract):
    leaseId: UUID
    idempotencyKey: UUID
    expectedRevision: StrictInt = Field(ge=0)
    receivedOn: date
    amountMinor: StrictInt = Field(gt=0)
    currencyCode: Literal["USD"]
    allocations: list[AllocationInput] = Field(min_length=1, max_length=100)
    paymentMethodKind: Literal[
        "automatic_bank_payment", "bank_transfer", "check", "cash", "online_payment", "other"
    ]
    paymentMethodLabel: str | None = Field(None, max_length=100)
    maskedReference: str | None = Field(None, max_length=80)
    otherPaymentMethodNote: str | None = Field(None, max_length=200)
    receivedByPartyId: UUID | None = None
    replacesReceiptId: UUID | None = None
    notes: str | None = Field(None, max_length=4000)
    duplicateConfirmed: StrictBool = False
    duplicateReason: str | None = Field(None, max_length=1000)


class VoidInput(CommandInput):
    confirmed: StrictBool
    voidReason: str = Field(min_length=1, max_length=1000)


class ReviewInput(CommandInput):
    decision: Literal["mark_missed", "clear_missed"]
    reason: str = Field(min_length=1, max_length=1000)
    confirmed: StrictBool


class AllocationResponse(Contract):
    id: UUID
    receiptId: UUID
    expectationId: UUID
    amountMinor: int
    createdAt: AwareDatetime
    expectationDueOn: date
    expectationPeriodStartsOn: date
    expectationPeriodEndsOn: date


class ExpectationAllocationSummaryResponse(Contract):
    allocationId: str
    receiptId: UUID
    receivedOn: date
    amountMinor: int
    receiptLifecycleStatus: Literal["active", "voided"]


class ExpectationResponse(Contract):
    id: UUID
    leaseId: UUID
    leaseTermId: str
    propertyId: UUID
    spaceId: UUID
    periodStartsOn: date
    periodEndsOn: date
    dueOn: date
    expectedAmountMinor: int
    currencyCode: Literal["USD"]
    paymentFrequency: Literal["monthly", "weekly"]
    scheduleAnchorOn: date
    isProrated: bool
    prorationNumeratorDays: int | None
    prorationDenominatorDays: int | None
    responsibilityBoundaryOn: date | None
    responsibilityOverrideReason: str | None
    voidedAt: AwareDatetime | None
    voidReason: str | None
    createdAt: AwareDatetime
    lifecycleStatus: Literal["active", "voided"]
    settlementStatus: Literal["unpaid", "partial", "paid"] | None
    timelinessStatus: (
        Literal["upcoming", "due", "late", "missed", "paid_on_time", "paid_late"] | None
    )
    effectiveMissedReview: bool
    allocationCount: int
    allocationSummaries: list[ExpectationAllocationSummaryResponse]
    receivedAmountMinor: int
    outstandingAmountMinor: int


class PaymentMethodSuggestionResponse(Contract):
    paymentMethodKind: Literal[
        "automatic_bank_payment", "bank_transfer", "check", "cash", "online_payment", "other"
    ]
    paymentMethodLabel: str | None
    maskedReference: str | None
    otherPaymentMethodNote: str | None


class ReceiptResponse(Contract):
    id: UUID
    leaseId: UUID
    idempotencyKey: str
    receivedOn: date
    amountMinor: int
    currencyCode: Literal["USD"]
    paymentMethodKind: Literal[
        "automatic_bank_payment", "bank_transfer", "check", "cash", "online_payment", "other"
    ]
    paymentMethodLabel: str | None
    maskedReference: str | None
    otherPaymentMethodNote: str | None
    receivedByPartyId: str | None
    replacesReceiptId: str | None
    notes: str | None
    voidedAt: AwareDatetime | None
    voidReason: str | None
    createdAt: AwareDatetime
    allocations: list[AllocationResponse]


class ExpectationPageResponse(Contract):
    items: list[ExpectationResponse]
    nextCursor: str | None


class ReceiptPageResponse(Contract):
    items: list[ReceiptResponse]
    nextCursor: str | None


class ExpectationMutationResponse(ExpectationResponse):
    rentLedgerRevision: StrictInt = Field(ge=0)
    operationId: UUID


class ReceiptMutationResponse(ReceiptResponse):
    rentLedgerRevision: StrictInt = Field(ge=0)
    operationId: UUID


class SynchronizeResponse(Contract):
    items: list[ExpectationResponse]
    rentLedgerRevision: StrictInt = Field(ge=0)
    operationId: UUID


class LedgerRevisionResponse(Contract):
    leaseId: UUID
    rentLedgerRevision: StrictInt = Field(ge=0)


class CommandRecoveryResponse(Contract):
    operationId: UUID
    scopeKind: Literal["rent_ledger", "expense", "deposit_account"]
    scopeId: UUID
    action: Literal[
        "synchronize_expectations",
        "record_receipt",
        "void_receipt",
        "void_expectation",
        "review_timeliness",
        "create_prepaid_check",
        "deposit_prepaid_check",
        "return_prepaid_check",
        "void_prepaid_check",
        "replace_prepaid_check",
        "record_expense",
        "patch_expense",
        "void_expense",
        "record_refund",
        "void_refund",
        "create_account",
        "create_settlement",
        "patch_settlement",
        "add_deduction",
        "update_deduction",
        "delete_deduction",
        "add_credit",
        "update_credit",
        "delete_credit",
        "add_deduction_source",
        "delete_deduction_source",
        "approve_settlement",
        "complete_settlement",
        "void_settlement",
    ]
    expectedRevision: StrictInt = Field(ge=0)
    resultRevision: StrictInt = Field(ge=0)
    result: (
        SynchronizeResponse
        | ReceiptMutationResponse
        | ExpectationMutationResponse
        | ExpenseMutationResponse
        | RefundMutationResponse
        | PrepaidCheckMutationResponse
        | DepositMutationResponse
        | DepositReceiptMutationResponse
        | SettlementMutationResponse
        | DeductionLineMutationResponse
        | CreditMutationResponse
        | DeductionSourceMutationResponse
        | DepositRefundMutationResponse
        | DeletedMutationResponse
    )


def build_router(service: FinanceService, runtime: WorkspaceRuntime):
    router = APIRouter(tags=["finance"], responses={409: {"model": FinanceConflictResponse}})

    def ready(write=False):
        if not runtime.ready or runtime.error:
            raise workspace_unavailable(str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:
            raise workspace_unavailable("Workspace writer lock is unavailable.")

    def invoke(fn):
        try:
            return fn()
        except FinanceNotFoundError as e:
            raise domain_problem(e, status_code=404, code="finance_not_found") from e
        except FinanceConflictError as e:
            raise domain_problem(e, status_code=409, **e.details) from e
        except FinanceValidationError as e:
            raise domain_problem(e, status_code=422, code="finance_validation") from e
        except FinanceError as e:
            raise domain_problem(e, status_code=400, code="finance_validation") from e

    @router.post(
        "/api/leases/{lease_id}/rent-expectations/synchronize",
        response_model=SynchronizeResponse,
        status_code=201,
        operation_id="synchronizeRentExpectations",
    )
    def synchronize(lease_id: UUID, data: SynchronizeInput):
        ready(True)
        return invoke(
            lambda: service.synchronize(
                str(lease_id),
                SynchronizeExpectationsCommand(
                    str(data.leaseTermId),
                    data.throughOn.isoformat(),
                    data.scheduleAnchorOn.isoformat() if data.scheduleAnchorOn else None,
                    data.responsibilityEndsOnOverride.isoformat()
                    if data.responsibilityEndsOnOverride
                    else None,
                    data.overrideReason,
                    data.overrideConfirmed,
                ),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.get(
        "/api/rent-expectations",
        response_model=ExpectationPageResponse,
        operation_id="listRentExpectations",
    )
    def expectations(
        leaseId: str | None = None,
        propertyId: str | None = None,
        status: Literal["unpaid", "partial", "paid"] | None = None,
        dueFrom: date | None = None,
        dueTo: date | None = None,
        timelinessStatus: Literal["upcoming", "due", "late", "missed", "paid_on_time", "paid_late"]
        | None = None,
        includeVoided: bool = False,
        cursor: str | None = None,
        pageSize: int = Query(100, ge=1, le=500),
    ):
        ready()
        return invoke(
            lambda: service.list_expectations(
                lease_id=leaseId,
                property_id=propertyId,
                status=status,
                due_from=dueFrom.isoformat() if dueFrom else None,
                due_to=dueTo.isoformat() if dueTo else None,
                timeliness=timelinessStatus,
                include_voided=includeVoided,
                cursor=cursor,
                page_size=pageSize,
            )
        )

    @router.get(
        "/api/rent-expectations/{expectation_id}",
        response_model=ExpectationResponse,
        operation_id="getRentExpectation",
    )
    def expectation(expectation_id: UUID):
        ready()
        return invoke(lambda: service.expectation(str(expectation_id)))

    @router.post(
        "/api/rent-expectations/{expectation_id}/void",
        response_model=ExpectationMutationResponse,
        operation_id="voidRentExpectation",
    )
    def void_expectation(expectation_id: UUID, data: VoidInput):
        ready(True)
        return invoke(
            lambda: service.void_expectation(
                str(expectation_id),
                VoidCommand(data.confirmed, data.voidReason),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/rent-expectations/{expectation_id}/timeliness-reviews",
        response_model=ExpectationMutationResponse,
        operation_id="reviewRentExpectationTimeliness",
    )
    def review(expectation_id: UUID, data: ReviewInput):
        ready(True)
        return invoke(
            lambda: service.review_timeliness(
                str(expectation_id),
                TimelinessReviewCommand(data.decision, data.reason, data.confirmed),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/rent-receipts",
        response_model=ReceiptMutationResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="recordRentReceipt",
    )
    def receipt(data: ReceiptInput):
        ready(True)
        return invoke(
            lambda: service.record_receipt(
                RecordReceiptCommand(
                    lease_id=str(data.leaseId),
                    idempotency_key=str(data.idempotencyKey),
                    received_on=data.receivedOn.isoformat(),
                    amount_minor=data.amountMinor,
                    currency_code=data.currencyCode,
                    allocations=tuple(
                        ReceiptAllocationCommand(str(x.expectationId), x.amountMinor)
                        for x in data.allocations
                    ),
                    payment_method_kind=data.paymentMethodKind,
                    payment_method_label=data.paymentMethodLabel,
                    masked_reference=data.maskedReference,
                    other_payment_method_note=data.otherPaymentMethodNote,
                    received_by_party_id=str(data.receivedByPartyId)
                    if data.receivedByPartyId
                    else None,
                    replaces_receipt_id=str(data.replacesReceiptId)
                    if data.replacesReceiptId
                    else None,
                    notes=data.notes,
                    duplicate_confirmed=data.duplicateConfirmed,
                    duplicate_reason=data.duplicateReason,
                ),
                expected_revision=data.expectedRevision,
            )
        )

    @router.get(
        "/api/leases/{lease_id}/rent-receipts/payment-method-suggestion",
        response_model=PaymentMethodSuggestionResponse,
        operation_id="getRentReceiptPaymentMethodSuggestion",
    )
    def payment_method_suggestion(lease_id: UUID):
        ready()
        value = invoke(lambda: service.payment_method_suggestion(str(lease_id)))
        return Response(status_code=status.HTTP_204_NO_CONTENT) if value is None else value

    @router.get(
        "/api/rent-receipts", response_model=ReceiptPageResponse, operation_id="listRentReceipts"
    )
    def receipts(
        leaseId: str | None = None,
        receivedFrom: date | None = None,
        receivedTo: date | None = None,
        receivedByPartyId: str | None = None,
        replacesReceiptId: str | None = None,
        includeVoided: bool = False,
        cursor: str | None = None,
        pageSize: int = Query(100, ge=1, le=500),
    ):
        ready()
        return invoke(
            lambda: service.list_receipts(
                lease_id=leaseId,
                received_from=receivedFrom.isoformat() if receivedFrom else None,
                received_to=receivedTo.isoformat() if receivedTo else None,
                received_by_party_id=receivedByPartyId,
                replaces_receipt_id=replacesReceiptId,
                include_voided=includeVoided,
                cursor=cursor,
                page_size=pageSize,
            )
        )

    @router.get(
        "/api/rent-receipts/{receipt_id}",
        response_model=ReceiptResponse,
        operation_id="getRentReceipt",
    )
    def receipt_detail(receipt_id: UUID):
        ready()
        return invoke(lambda: service.receipt(str(receipt_id)))

    @router.post(
        "/api/rent-receipts/{receipt_id}/void",
        response_model=ReceiptMutationResponse,
        operation_id="voidRentReceipt",
    )
    def void_receipt(receipt_id: UUID, data: VoidInput):
        ready(True)
        return invoke(
            lambda: service.void_receipt(
                str(receipt_id),
                VoidCommand(data.confirmed, data.voidReason),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.get(
        "/api/leases/{lease_id}/rent-ledger",
        response_model=LedgerRevisionResponse,
        operation_id="getRentLedgerRevision",
    )
    def ledger_revision(lease_id: UUID):
        ready()
        return invoke(lambda: service.rent_ledger_revision(str(lease_id)))

    @router.get(
        "/api/finance/command-operations/{idempotency_key}",
        response_model=CommandRecoveryResponse,
        operation_id="getFinanceCommandOperation",
    )
    def command_recovery(idempotency_key: UUID):
        ready()
        return invoke(lambda: service.command_operation(str(idempotency_key)))

    return router

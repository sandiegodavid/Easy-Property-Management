"""Typed FIN-008 HTTP contract."""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt

from app.modules.finance.api.conflicts import FinanceConflictDetail

from app.platform.api_errors import domain_problem, workspace_unavailable

from app.modules.finance.application.deposit_service import (
    DepositService,
    PossibleDuplicateDepositReceiptError,
    PossibleDuplicateDepositRefundError,
)
from app.modules.finance.domain.deposit_models import (
    CreditCommand,
    DeductionCommand,
    DepositAccountCreateCommand,
    DepositReceiptCommand,
    DepositRefundCommand,
    SettlementCreateCommand,
)
from app.modules.finance.domain.models import (
    FinanceConflictError,
    FinanceError,
    FinanceNotFoundError,
    VoidCommand,
)
from app.modules.workspace.application.runtime import WorkspaceRuntime


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CommandInput(Contract):
    expectedRevision: StrictInt = Field(ge=0)
    idempotencyKey: UUID


class AccountInput(CommandInput):
    leaseTermId: UUID


class ReceiptInput(CommandInput):
    idempotencyKey: UUID
    receivedOn: date
    amount: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$")
    currencyCode: Literal["USD"]
    receivedByKind: Literal["local_operator", "party"]
    receivedFromPartyId: UUID | None = None
    receivedByPartyId: UUID | None = None
    reference: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=4000)
    replacesReceiptId: UUID | None = None
    duplicateConfirmed: StrictBool = False
    historicalEntryConfirmed: StrictBool = False
    historicalEntryReason: str | None = Field(None, max_length=1000)
    overageConfirmed: StrictBool = False
    overageReason: str | None = Field(None, max_length=1000)
    historicalPartyConfirmed: StrictBool = False
    historicalPartyReason: str | None = Field(None, max_length=1000)


class SettlementInput(CommandInput):
    settlementDueOn: date
    legalRuleReference: str | None = Field(None, max_length=500)
    reviewNotes: str | None = Field(None, max_length=4000)
    eligibilityOverrideConfirmed: StrictBool = False
    eligibilityOverrideReason: str | None = Field(None, max_length=1000)
    deadlineOverrideConfirmed: StrictBool = False
    deadlineOverrideReason: str | None = Field(None, max_length=1000)
    replacesSettlementId: UUID | None = None


class SettlementPatchInput(CommandInput):
    settlementDueOn: date | None = None
    legalRuleReference: str | None = Field(None, max_length=500)
    reviewNotes: str | None = Field(None, max_length=4000)
    deadlineOverrideConfirmed: StrictBool | None = None
    deadlineOverrideReason: str | None = Field(None, max_length=1000)


class DeductionInput(CommandInput):
    category: Literal[
        "unpaid_rent", "damage", "cleaning", "missing_property", "contractual_fee", "other"
    ]
    amount: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$")
    description: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=2000)


class CreditInput(CommandInput):
    kind: Literal["interest", "other"]
    amount: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$")
    description: str = Field(min_length=1, max_length=500)
    calculatorPrincipal: str | None = Field(None, pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$")
    annualRateBasisPoints: StrictInt | None = Field(None, ge=1, le=100000)
    startsOn: date | None = None
    endsOn: date | None = None
    overrideReason: str | None = Field(None, max_length=1000)


class DeductionSourceInput(CommandInput):
    sourceKind: Literal[
        "inspection_comparison", "inspection_observation", "rent_expectation", "expense"
    ]
    sourceId: UUID
    historicalConfirmed: StrictBool = False
    historicalReason: str | None = Field(None, max_length=1000)
    duplicateUseConfirmed: StrictBool = False


class RefundInput(CommandInput):
    idempotencyKey: UUID
    recipientPartyId: UUID
    paidOn: date
    amount: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$")
    currencyCode: Literal["USD"]
    reference: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=4000)
    recipientOverrideConfirmed: StrictBool = False
    recipientOverrideReason: str | None = Field(None, max_length=1000)
    replacesRefundId: UUID | None = None
    duplicateConfirmed: StrictBool = False
    historicalPartyConfirmed: StrictBool = False
    historicalPartyReason: str | None = Field(None, max_length=1000)


class ConfirmInput(CommandInput):
    confirmed: StrictBool
    zeroDollarClosureConfirmed: StrictBool = False


class VoidInput(CommandInput):
    confirmed: StrictBool
    reason: str = Field(min_length=1, max_length=1000)


class DepositResponse(Contract):
    depositAccountRevision: StrictInt
    id: UUID
    leaseId: UUID
    leaseTermId: UUID
    propertyId: UUID
    spaceId: UUID
    agreedAmount: str
    currencyCode: Literal["USD"]
    activeReceivedAmount: str
    activeRefundedAmount: str
    varianceAmount: str
    settlementId: UUID | None = None
    settlementStatus: Literal["draft", "approved", "completed"] | None = None
    deadlineState: Literal["due", "due_today", "overdue", "complete"] | None = None
    unresolvedBalance: bool
    createdAt: AwareDatetime
    updatedAt: AwareDatetime


class DepositPageResponse(Contract):
    items: list[DepositResponse]
    nextCursor: str | None


class ReceiptResponse(Contract):
    id: UUID
    accountId: UUID
    idempotencyKey: UUID
    receivedOn: date
    amount: str
    currencyCode: Literal["USD"]
    receivedFromPartyId: UUID | None
    receivedFromName: str | None
    receivedByKind: Literal["local_operator", "party"]
    receivedByPartyId: UUID | None
    receivedByName: str | None
    reference: str | None
    notes: str | None
    replacesReceiptId: UUID | None
    replacedByReceiptId: UUID | None = None
    voidedAt: AwareDatetime | None
    voidReason: str | None
    createdAt: AwareDatetime
    lifecycleStatus: Literal["active", "voided"]


class EvidenceResponse(Contract):
    fileId: UUID
    purpose: str
    createdAt: AwareDatetime
    archivedAt: AwareDatetime | None


class DeductionSourceResponse(Contract):
    id: UUID
    deductionId: UUID
    sourceKind: Literal[
        "inspection_comparison", "inspection_observation", "rent_expectation", "expense"
    ]
    sourceId: UUID
    sourceSummary: str
    outstandingAmount: str | None
    historicalConfirmed: bool
    historicalReason: str | None
    duplicateUseConfirmed: bool
    createdAt: AwareDatetime


class DeductionLineResponse(Contract):
    id: UUID
    settlementId: UUID
    category: Literal[
        "unpaid_rent", "damage", "cleaning", "missing_property", "contractual_fee", "other"
    ]
    amount: str
    description: str
    rationale: str
    createdAt: AwareDatetime
    updatedAt: AwareDatetime


class DeductionResponse(DeductionLineResponse):
    sources: list[DeductionSourceResponse]
    evidence: list[EvidenceResponse]


class CreditResponse(Contract):
    id: UUID
    settlementId: UUID
    kind: Literal["interest", "other"]
    amount: str
    description: str
    calculatorPrincipal: str | None
    annualRateBasisPoints: StrictInt | None
    startsOn: date | None
    endsOn: date | None
    dayCount: StrictInt | None
    calculatedAmount: str | None
    overrideReason: str | None
    createdAt: AwareDatetime
    updatedAt: AwareDatetime


class RefundResponse(Contract):
    id: UUID
    accountId: UUID
    authorizedBySettlementId: UUID
    idempotencyKey: UUID
    recipientPartyId: UUID
    recipientName: str
    paidOn: date
    amount: str
    currencyCode: Literal["USD"]
    reference: str | None
    notes: str | None
    recipientOverrideReason: str | None
    replacesRefundId: UUID | None
    replacedByRefundId: UUID | None = None
    voidedAt: AwareDatetime | None
    voidReason: str | None
    createdAt: AwareDatetime
    lifecycleStatus: Literal["active", "voided"]


class SettlementResponse(Contract):
    id: UUID
    accountId: UUID
    status: Literal["draft", "approved", "completed", "voided"]
    settlementDueOn: date
    legalRuleReference: str | None
    reviewNotes: str | None
    eligibilityOverrideReason: str | None
    deadlineOverrideReason: str | None
    receiptTotal: str | None
    creditTotal: str | None
    deductionTotal: str | None
    refundDue: str | None
    replacesSettlementId: UUID | None
    replacedBySettlementId: UUID | None
    approvedAt: AwareDatetime | None
    completedAt: AwareDatetime | None
    voidedAt: AwareDatetime | None
    voidReason: str | None
    deductions: list[DeductionResponse]
    credits: list[CreditResponse]
    refunds: list[RefundResponse]
    evidence: list[EvidenceResponse]
    sourceWarnings: list[str]
    inspectionWarnings: list[str]
    unsettledReceiptAmount: str
    createdAt: AwareDatetime
    updatedAt: AwareDatetime


class DeletedMutationResponse(Contract):
    deleted: Literal[True]
    id: UUID
    depositAccountRevision: StrictInt
    operationId: UUID


class DepositMutationResponse(DepositResponse):
    depositAccountRevision: StrictInt
    operationId: UUID


class ReceiptMutationResponse(ReceiptResponse):
    depositAccountRevision: StrictInt
    operationId: UUID


class SettlementMutationResponse(SettlementResponse):
    depositAccountRevision: StrictInt
    operationId: UUID


class DeductionLineMutationResponse(DeductionLineResponse):
    depositAccountRevision: StrictInt
    operationId: UUID


class CreditMutationResponse(CreditResponse):
    depositAccountRevision: StrictInt
    operationId: UUID


class DeductionSourceMutationResponse(DeductionSourceResponse):
    depositAccountRevision: StrictInt
    operationId: UUID


class RefundMutationResponse(RefundResponse):
    depositAccountRevision: StrictInt
    operationId: UUID


class DepositConflictDetail(FinanceConflictDetail):
    candidates: list[ReceiptResponse | RefundResponse] | None = None


class DepositConflictResponse(Contract):
    detail: DepositConflictDetail


def build_router(service: DepositService, runtime: WorkspaceRuntime):
    router = APIRouter(
        tags=["security deposits"], responses={409: {"model": DepositConflictResponse}}
    )

    def ready(write=False):
        if not runtime.ready or runtime.error:
            raise workspace_unavailable(str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:
            raise workspace_unavailable("Workspace writer lock is unavailable.")

    def invoke(fn):
        try:
            return fn()
        except PossibleDuplicateDepositReceiptError as error:
            raise domain_problem(
                error,
                status_code=409,
                code="possible_duplicate_deposit_receipt",
                candidates=error.candidates,
            ) from error
        except PossibleDuplicateDepositRefundError as error:
            raise domain_problem(
                error,
                status_code=409,
                code="possible_duplicate_deposit_refund",
                candidates=error.candidates,
            ) from error
        except FinanceNotFoundError as error:
            raise domain_problem(error, status_code=404, code="finance_not_found") from error
        except FinanceConflictError as error:
            raise domain_problem(
                error, status_code=409, code=error.code, **error.details
            ) from error
        except FinanceError as error:
            raise domain_problem(error, status_code=422, code="finance_validation") from error

    @router.post(
        "/api/leases/{lease_id}/security-deposit",
        response_model=DepositMutationResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createSecurityDepositAccount",
    )
    def create(lease_id: UUID, data: AccountInput):
        ready(True)
        return invoke(
            lambda: service.create_account(
                str(lease_id),
                DepositAccountCreateCommand(str(data.leaseTermId)),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.get(
        "/api/leases/{lease_id}/security-deposit",
        response_model=DepositResponse,
        operation_id="getLeaseSecurityDeposit",
    )
    def lease_account(lease_id: UUID):
        ready()
        return invoke(lambda: service.account_for_lease(str(lease_id)))

    @router.get(
        "/api/security-deposits/{account_id}/receipts",
        response_model=list[ReceiptResponse],
        operation_id="listSecurityDepositReceipts",
    )
    def receipt_history(account_id: UUID):
        ready()
        return invoke(lambda: service.receipt_history(str(account_id)))

    @router.get(
        "/api/security-deposits/{account_id}/refunds",
        response_model=list[RefundResponse],
        operation_id="listSecurityDepositRefunds",
    )
    def refund_history(account_id: UUID):
        ready()
        return invoke(lambda: service.refund_history(str(account_id)))

    @router.get(
        "/api/security-deposits",
        response_model=DepositPageResponse,
        operation_id="listSecurityDeposits",
    )
    def accounts(
        leaseId: UUID | None = None,
        propertyId: UUID | None = None,
        spaceId: UUID | None = None,
        settlementStatus: Literal["draft", "approved", "completed"] | None = None,
        deadlineState: Literal["due", "due_today", "overdue", "complete"] | None = None,
        unresolvedBalance: bool | None = None,
        cursor: str | None = None,
        pageSize: int = Query(100, ge=1, le=500),
    ):
        ready()
        return invoke(
            lambda: service.list_accounts(
                lease_id=str(leaseId) if leaseId else None,
                property_id=str(propertyId) if propertyId else None,
                space_id=str(spaceId) if spaceId else None,
                settlement_state=settlementStatus,
                deadline_state=deadlineState,
                unresolved_balance=unresolvedBalance,
                cursor=cursor,
                page_size=pageSize,
            )
        )

    @router.post(
        "/api/security-deposits/{account_id}/receipts",
        response_model=ReceiptMutationResponse,
        status_code=201,
        operation_id="recordSecurityDepositReceipt",
    )
    def receipt(account_id: UUID, data: ReceiptInput):
        ready(True)
        return invoke(
            lambda: service.record_receipt(
                str(account_id),
                DepositReceiptCommand(
                    str(data.idempotencyKey),
                    data.receivedOn.isoformat(),
                    data.amount,
                    data.currencyCode,
                    data.receivedByKind,
                    str(data.receivedFromPartyId) if data.receivedFromPartyId else None,
                    str(data.receivedByPartyId) if data.receivedByPartyId else None,
                    data.reference,
                    data.notes,
                    str(data.replacesReceiptId) if data.replacesReceiptId else None,
                    data.duplicateConfirmed,
                    data.historicalEntryConfirmed,
                    data.historicalEntryReason,
                    data.overageConfirmed,
                    data.overageReason,
                    data.historicalPartyConfirmed,
                    data.historicalPartyReason,
                ),
                expected_revision=data.expectedRevision,
            )
        )

    @router.post(
        "/api/security-deposit-receipts/{receipt_id}/void",
        response_model=ReceiptMutationResponse,
        operation_id="voidSecurityDepositReceipt",
    )
    def void_receipt(receipt_id: UUID, data: VoidInput):
        ready(True)
        return invoke(
            lambda: service.void_receipt(
                str(receipt_id),
                VoidCommand(data.confirmed, data.reason),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/security-deposits/{account_id}/settlements",
        response_model=SettlementMutationResponse,
        status_code=201,
        operation_id="createSecurityDepositSettlement",
    )
    def settlement(account_id: UUID, data: SettlementInput):
        ready(True)
        return invoke(
            lambda: service.create_settlement(
                str(account_id),
                SettlementCreateCommand(
                    data.settlementDueOn.isoformat(),
                    data.legalRuleReference,
                    data.reviewNotes,
                    data.eligibilityOverrideConfirmed,
                    data.eligibilityOverrideReason,
                    data.deadlineOverrideConfirmed,
                    data.deadlineOverrideReason,
                    str(data.replacesSettlementId) if data.replacesSettlementId else None,
                ),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.patch(
        "/api/security-deposit-settlements/{settlement_id}",
        response_model=SettlementMutationResponse,
        operation_id="patchSecurityDepositSettlement",
    )
    def patch_settlement(settlement_id: UUID, data: SettlementPatchInput):
        ready(True)
        fields = frozenset(
            {
                "settlementDueOn": "settlement_due_on",
                "legalRuleReference": "legal_rule_reference",
                "reviewNotes": "review_notes",
                "deadlineOverrideConfirmed": "deadline_override_confirmed",
                "deadlineOverrideReason": "deadline_override_reason",
            }[name]
            for name in data.model_fields_set
            if name not in {"expectedRevision", "idempotencyKey"}
        )
        return invoke(
            lambda: service.patch_settlement(
                str(settlement_id),
                fields=fields,
                settlement_due_on=data.settlementDueOn.isoformat()
                if data.settlementDueOn
                else None,
                legal_rule_reference=data.legalRuleReference,
                review_notes=data.reviewNotes,
                deadline_override_confirmed=data.deadlineOverrideConfirmed,
                deadline_override_reason=data.deadlineOverrideReason,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/security-deposit-settlements/{settlement_id}/deductions",
        response_model=DeductionLineMutationResponse,
        status_code=201,
        operation_id="addSecurityDepositDeduction",
    )
    def deduction(settlement_id: UUID, data: DeductionInput):
        ready(True)
        return invoke(
            lambda: service.add_deduction(
                str(settlement_id),
                DeductionCommand(data.category, data.amount, data.description, data.rationale),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/security-deposit-deductions/{deduction_id}/sources",
        response_model=DeductionSourceMutationResponse,
        status_code=201,
        operation_id="addSecurityDepositDeductionSource",
    )
    def deduction_source(deduction_id: UUID, data: DeductionSourceInput):
        ready(True)
        return invoke(
            lambda: service.add_deduction_source(
                str(deduction_id),
                data.sourceKind,
                str(data.sourceId),
                historical_confirmed=data.historicalConfirmed,
                historical_reason=data.historicalReason,
                duplicate_use_confirmed=data.duplicateUseConfirmed,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.delete(
        "/api/security-deposit-deduction-sources/{source_id}",
        response_model=DeletedMutationResponse,
        operation_id="deleteSecurityDepositDeductionSource",
    )
    def delete_deduction_source(source_id: UUID, data: CommandInput):
        ready(True)
        return invoke(
            lambda: service.delete_deduction_source(
                str(source_id),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.patch(
        "/api/security-deposit-deductions/{deduction_id}",
        response_model=DeductionLineMutationResponse,
        operation_id="patchSecurityDepositDeduction",
    )
    def patch_deduction(deduction_id: UUID, data: DeductionInput):
        ready(True)
        return invoke(
            lambda: service.update_deduction(
                str(deduction_id),
                DeductionCommand(data.category, data.amount, data.description, data.rationale),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.delete(
        "/api/security-deposit-deductions/{deduction_id}",
        response_model=DeletedMutationResponse,
        operation_id="deleteSecurityDepositDeduction",
    )
    def delete_deduction(deduction_id: UUID, data: CommandInput):
        ready(True)
        return invoke(
            lambda: service.delete_deduction(
                str(deduction_id),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/security-deposit-settlements/{settlement_id}/credits",
        response_model=CreditMutationResponse,
        status_code=201,
        operation_id="addSecurityDepositCredit",
    )
    def credit(settlement_id: UUID, data: CreditInput):
        ready(True)
        return invoke(
            lambda: service.add_credit(
                str(settlement_id),
                CreditCommand(
                    data.kind,
                    data.amount,
                    data.description,
                    data.calculatorPrincipal,
                    data.annualRateBasisPoints,
                    data.startsOn.isoformat() if data.startsOn else None,
                    data.endsOn.isoformat() if data.endsOn else None,
                    data.overrideReason,
                ),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.patch(
        "/api/security-deposit-credits/{credit_id}",
        response_model=CreditMutationResponse,
        operation_id="patchSecurityDepositCredit",
    )
    def patch_credit(credit_id: UUID, data: CreditInput):
        ready(True)
        return invoke(
            lambda: service.update_credit(
                str(credit_id),
                CreditCommand(
                    data.kind,
                    data.amount,
                    data.description,
                    data.calculatorPrincipal,
                    data.annualRateBasisPoints,
                    data.startsOn.isoformat() if data.startsOn else None,
                    data.endsOn.isoformat() if data.endsOn else None,
                    data.overrideReason,
                ),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.delete(
        "/api/security-deposit-credits/{credit_id}",
        response_model=DeletedMutationResponse,
        operation_id="deleteSecurityDepositCredit",
    )
    def delete_credit(credit_id: UUID, data: CommandInput):
        ready(True)
        return invoke(
            lambda: service.delete_credit(
                str(credit_id),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/security-deposit-settlements/{settlement_id}/approve",
        response_model=SettlementMutationResponse,
        operation_id="approveSecurityDepositSettlement",
    )
    def approve(settlement_id: UUID, data: ConfirmInput):
        ready(True)
        return invoke(
            lambda: service.approve_settlement(
                str(settlement_id),
                data.confirmed,
                zero_dollar_closure_confirmed=data.zeroDollarClosureConfirmed,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/security-deposit-settlements/{settlement_id}/complete",
        response_model=SettlementMutationResponse,
        operation_id="completeSecurityDepositSettlement",
    )
    def complete(settlement_id: UUID, data: ConfirmInput):
        ready(True)
        return invoke(
            lambda: service.complete_settlement(
                str(settlement_id),
                data.confirmed,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/security-deposit-settlements/{settlement_id}/void",
        response_model=SettlementMutationResponse,
        operation_id="voidSecurityDepositSettlement",
    )
    def void(settlement_id: UUID, data: VoidInput):
        ready(True)
        return invoke(
            lambda: service.void_settlement(
                str(settlement_id),
                VoidCommand(data.confirmed, data.reason),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/security-deposit-settlements/{settlement_id}/refunds",
        response_model=RefundMutationResponse,
        status_code=201,
        operation_id="recordSecurityDepositRefund",
    )
    def refund(settlement_id: UUID, data: RefundInput):
        ready(True)
        return invoke(
            lambda: service.record_refund(
                str(settlement_id),
                DepositRefundCommand(
                    str(data.idempotencyKey),
                    str(data.recipientPartyId),
                    data.paidOn.isoformat(),
                    data.amount,
                    data.currencyCode,
                    data.reference,
                    data.notes,
                    data.recipientOverrideConfirmed,
                    data.recipientOverrideReason,
                    str(data.replacesRefundId) if data.replacesRefundId else None,
                    data.duplicateConfirmed,
                    data.historicalPartyConfirmed,
                    data.historicalPartyReason,
                ),
                expected_revision=data.expectedRevision,
            )
        )

    @router.post(
        "/api/security-deposit-refunds/{refund_id}/void",
        response_model=RefundMutationResponse,
        operation_id="voidSecurityDepositRefund",
    )
    def void_refund(refund_id: UUID, data: VoidInput):
        ready(True)
        return invoke(
            lambda: service.void_refund(
                str(refund_id),
                VoidCommand(data.confirmed, data.reason),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.get(
        "/api/security-deposit-settlements/{settlement_id}",
        response_model=SettlementResponse,
        operation_id="getSecurityDepositSettlement",
    )
    def detail(settlement_id: UUID):
        ready()
        return invoke(lambda: service.settlement(str(settlement_id)))

    return router

"""Typed FIN-008 HTTP contract."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from app.modules.finance.application.deposit_service import DepositService, PossibleDuplicateDepositReceiptError, PossibleDuplicateDepositRefundError
from app.modules.finance.domain.deposit_models import CreditCommand, DeductionCommand, DepositAccountCreateCommand, DepositReceiptCommand, DepositRefundCommand, SettlementCreateCommand
from app.modules.finance.domain.models import FinanceConflictError, FinanceError, FinanceNotFoundError, VoidCommand
from app.modules.workspace.application.runtime import WorkspaceRuntime

class Contract(BaseModel): model_config = ConfigDict(extra="forbid")
class AccountInput(Contract): leaseTermId: UUID
class ReceiptInput(Contract):
    idempotencyKey: UUID; receivedOn: date; amount: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$"); currencyCode: Literal["USD"]
    receivedByKind: Literal["local_operator", "party"]; receivedFromPartyId: UUID|None=None; receivedByPartyId: UUID|None=None; reference: str|None=Field(None,max_length=200); notes: str|None=Field(None,max_length=4000); replacesReceiptId: UUID|None=None; duplicateConfirmed: StrictBool=False; historicalEntryConfirmed: StrictBool=False; historicalEntryReason: str|None=Field(None,max_length=1000); overageConfirmed: StrictBool=False; overageReason: str|None=Field(None,max_length=1000); historicalPartyConfirmed: StrictBool=False; historicalPartyReason: str|None=Field(None,max_length=1000)
class SettlementInput(Contract): settlementDueOn: date; legalRuleReference: str|None=Field(None,max_length=500); reviewNotes: str|None=Field(None,max_length=4000); eligibilityOverrideConfirmed: StrictBool=False; eligibilityOverrideReason: str|None=Field(None,max_length=1000); deadlineOverrideConfirmed: StrictBool=False; deadlineOverrideReason: str|None=Field(None,max_length=1000); replacesSettlementId: UUID|None=None
class SettlementPatchInput(Contract): settlementDueOn: date|None=None; legalRuleReference: str|None=Field(None,max_length=500); reviewNotes: str|None=Field(None,max_length=4000); deadlineOverrideConfirmed: StrictBool|None=None; deadlineOverrideReason: str|None=Field(None,max_length=1000)
class DeductionInput(Contract): category: Literal["unpaid_rent","damage","cleaning","missing_property","contractual_fee","other"]; amount: str=Field(pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$"); description: str=Field(min_length=1,max_length=500); rationale: str=Field(min_length=1,max_length=2000)
class CreditInput(Contract): kind: Literal["interest","other"]; amount: str=Field(pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$"); description: str=Field(min_length=1,max_length=500); calculatorPrincipal: str|None=Field(None,pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$"); annualRateBasisPoints: StrictInt|None=Field(None,ge=1,le=100000); startsOn: date|None=None; endsOn: date|None=None; overrideReason: str|None=Field(None,max_length=1000)
class DeductionSourceInput(Contract): sourceKind: Literal["inspection_comparison","inspection_observation","rent_expectation","expense"]; sourceId: UUID; historicalConfirmed: StrictBool=False; historicalReason: str|None=Field(None,max_length=1000); duplicateUseConfirmed: StrictBool=False
class RefundInput(Contract): idempotencyKey: UUID; recipientPartyId: UUID; paidOn: date; amount: str=Field(pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$"); currencyCode: Literal["USD"]; reference: str|None=Field(None,max_length=200); notes: str|None=Field(None,max_length=4000); recipientOverrideConfirmed: StrictBool=False; recipientOverrideReason: str|None=Field(None,max_length=1000); replacesRefundId: UUID|None=None; duplicateConfirmed: StrictBool=False; historicalPartyConfirmed: StrictBool=False; historicalPartyReason: str|None=Field(None,max_length=1000)
class ConfirmInput(Contract): confirmed: StrictBool; zeroDollarClosureConfirmed: StrictBool=False
class VoidInput(Contract): confirmed: StrictBool; reason: str=Field(min_length=1,max_length=1000)
class DepositResponse(Contract): id: UUID; leaseId: UUID; leaseTermId: UUID; propertyId: UUID; spaceId: UUID; agreedAmount: str; currencyCode: Literal["USD"]; activeReceivedAmount: str; activeRefundedAmount: str; varianceAmount: str; settlementId: UUID|None=None; settlementStatus: Literal["draft","approved","completed"]|None=None; deadlineState: Literal["due","due_today","overdue","complete"]|None=None; unresolvedBalance: bool; createdAt: datetime; updatedAt: datetime
class DepositPageResponse(Contract): items: list[DepositResponse]; nextCursor: str|None
class ReceiptResponse(Contract): id: UUID; accountId: UUID; idempotencyKey: UUID; receivedOn: date; amount: str; currencyCode: Literal["USD"]; receivedFromPartyId: UUID|None; receivedFromName: str|None; receivedByKind: Literal["local_operator","party"]; receivedByPartyId: UUID|None; receivedByName: str|None; reference: str|None; notes: str|None; replacesReceiptId: UUID|None; replacedByReceiptId: UUID|None=None; voidedAt: datetime|None; voidReason: str|None; createdAt: datetime; lifecycleStatus: Literal["active","voided"]
class EvidenceResponse(Contract): fileId: UUID; purpose: str; createdAt: datetime; archivedAt: datetime|None
class DeductionSourceResponse(Contract): id: UUID; deductionId: UUID; sourceKind: Literal["inspection_comparison","inspection_observation","rent_expectation","expense"]; sourceId: UUID; sourceSummary: str; outstandingAmount: str|None; historicalConfirmed: bool; historicalReason: str|None; duplicateUseConfirmed: bool; createdAt: datetime
class DeductionLineResponse(Contract): id: UUID; settlementId: UUID; category: Literal["unpaid_rent","damage","cleaning","missing_property","contractual_fee","other"]; amount: str; description: str; rationale: str; createdAt: datetime; updatedAt: datetime
class DeductionResponse(DeductionLineResponse): sources: list[DeductionSourceResponse]; evidence: list[EvidenceResponse]
class CreditResponse(Contract): id: UUID; settlementId: UUID; kind: Literal["interest","other"]; amount: str; description: str; calculatorPrincipal: str|None; annualRateBasisPoints: StrictInt|None; startsOn: date|None; endsOn: date|None; dayCount: StrictInt|None; calculatedAmount: str|None; overrideReason: str|None; createdAt: datetime; updatedAt: datetime
class RefundResponse(Contract): id: UUID; accountId: UUID; authorizedBySettlementId: UUID; idempotencyKey: UUID; recipientPartyId: UUID; recipientName: str; paidOn: date; amount: str; currencyCode: Literal["USD"]; reference: str|None; notes: str|None; recipientOverrideReason: str|None; replacesRefundId: UUID|None; replacedByRefundId: UUID|None=None; voidedAt: datetime|None; voidReason: str|None; createdAt: datetime; lifecycleStatus: Literal["active","voided"]
class SettlementResponse(Contract):
    id: UUID; accountId: UUID; status: Literal["draft","approved","completed","voided"]; settlementDueOn: date
    legalRuleReference: str|None; reviewNotes: str|None; eligibilityOverrideReason: str|None; deadlineOverrideReason: str|None
    receiptTotal: str|None; creditTotal: str|None; deductionTotal: str|None; refundDue: str|None; replacesSettlementId: UUID|None; replacedBySettlementId: UUID|None
    approvedAt: datetime|None; completedAt: datetime|None; voidedAt: datetime|None; voidReason: str|None
    deductions:list[DeductionResponse]; credits:list[CreditResponse]; refunds:list[RefundResponse]; evidence:list[EvidenceResponse]; sourceWarnings:list[str]; inspectionWarnings:list[str]; unsettledReceiptAmount: str; createdAt: datetime; updatedAt: datetime

def build_router(service: DepositService, runtime: WorkspaceRuntime):
    router=APIRouter(tags=["security deposits"])
    def ready(write=False):
        if not runtime.ready or runtime.error: raise HTTPException(503,str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write: raise HTTPException(503,"Workspace writer lock is unavailable.")
    def invoke(fn):
        try:return fn()
        except PossibleDuplicateDepositReceiptError as error: raise HTTPException(409,{"code":"possible_duplicate_deposit_receipt","candidates":error.candidates}) from error
        except PossibleDuplicateDepositRefundError as error: raise HTTPException(409,{"code":"possible_duplicate_deposit_refund","candidates":error.candidates}) from error
        except FinanceNotFoundError as error: raise HTTPException(404,str(error)) from error
        except FinanceConflictError as error: raise HTTPException(409,{"code":"finance_conflict","message":str(error)}) from error
        except FinanceError as error: raise HTTPException(422,str(error)) from error
    @router.post("/api/leases/{lease_id}/security-deposit",response_model=DepositResponse,status_code=status.HTTP_201_CREATED)
    def create(lease_id:UUID,data:AccountInput): ready(True);return invoke(lambda:service.create_account(str(lease_id),DepositAccountCreateCommand(str(data.leaseTermId))))
    @router.get("/api/leases/{lease_id}/security-deposit",response_model=DepositResponse)
    def lease_account(lease_id:UUID):ready();return invoke(lambda:service.account_for_lease(str(lease_id)))
    @router.get("/api/security-deposits/{account_id}/receipts", response_model=list[ReceiptResponse])
    def receipt_history(account_id: UUID): ready(); return invoke(lambda: service.receipt_history(str(account_id)))
    @router.get("/api/security-deposits/{account_id}/refunds", response_model=list[RefundResponse])
    def refund_history(account_id: UUID): ready(); return invoke(lambda: service.refund_history(str(account_id)))
    @router.get("/api/security-deposits",response_model=DepositPageResponse)
    def accounts(leaseId:UUID|None=None,propertyId:UUID|None=None,spaceId:UUID|None=None,settlementStatus:Literal["draft","approved","completed"]|None=None,deadlineState:Literal["due","due_today","overdue","complete"]|None=None,unresolvedBalance:bool|None=None,cursor:str|None=None,pageSize:int=Query(100,ge=1,le=500)):ready();return invoke(lambda:service.list_accounts(lease_id=str(leaseId) if leaseId else None,property_id=str(propertyId) if propertyId else None,space_id=str(spaceId) if spaceId else None,settlement_state=settlementStatus,deadline_state=deadlineState,unresolved_balance=unresolvedBalance,cursor=cursor,page_size=pageSize))
    @router.post("/api/security-deposits/{account_id}/receipts",response_model=ReceiptResponse,status_code=201)
    def receipt(account_id:UUID,data:ReceiptInput):
        ready(True);return invoke(lambda:service.record_receipt(str(account_id),DepositReceiptCommand(str(data.idempotencyKey),data.receivedOn.isoformat(),data.amount,data.currencyCode,data.receivedByKind,str(data.receivedFromPartyId) if data.receivedFromPartyId else None,str(data.receivedByPartyId) if data.receivedByPartyId else None,data.reference,data.notes,str(data.replacesReceiptId) if data.replacesReceiptId else None,data.duplicateConfirmed,data.historicalEntryConfirmed,data.historicalEntryReason,data.overageConfirmed,data.overageReason,data.historicalPartyConfirmed,data.historicalPartyReason)))
    @router.post("/api/security-deposit-receipts/{receipt_id}/void",response_model=ReceiptResponse)
    def void_receipt(receipt_id:UUID,data:VoidInput):ready(True);return invoke(lambda:service.void_receipt(str(receipt_id),VoidCommand(data.confirmed,data.reason)))
    @router.post("/api/security-deposits/{account_id}/settlements",response_model=SettlementResponse,status_code=201)
    def settlement(account_id:UUID,data:SettlementInput):ready(True);return invoke(lambda:service.create_settlement(str(account_id),SettlementCreateCommand(data.settlementDueOn.isoformat(),data.legalRuleReference,data.reviewNotes,data.eligibilityOverrideConfirmed,data.eligibilityOverrideReason,data.deadlineOverrideConfirmed,data.deadlineOverrideReason,str(data.replacesSettlementId) if data.replacesSettlementId else None)))
    @router.patch("/api/security-deposit-settlements/{settlement_id}",response_model=SettlementResponse)
    def patch_settlement(settlement_id:UUID,data:SettlementPatchInput):
        ready(True)
        fields = frozenset({
            "settlementDueOn": "settlement_due_on",
            "legalRuleReference": "legal_rule_reference",
            "reviewNotes": "review_notes",
            "deadlineOverrideConfirmed": "deadline_override_confirmed",
            "deadlineOverrideReason": "deadline_override_reason",
        }[name] for name in data.model_fields_set)
        return invoke(lambda: service.patch_settlement(
            str(settlement_id), fields=fields,
            settlement_due_on=data.settlementDueOn.isoformat() if data.settlementDueOn else None,
            legal_rule_reference=data.legalRuleReference,
            review_notes=data.reviewNotes,
            deadline_override_confirmed=data.deadlineOverrideConfirmed,
            deadline_override_reason=data.deadlineOverrideReason,
        ))
    @router.post("/api/security-deposit-settlements/{settlement_id}/deductions",response_model=DeductionLineResponse,status_code=201)
    def deduction(settlement_id:UUID,data:DeductionInput):ready(True);return invoke(lambda:service.add_deduction(str(settlement_id),DeductionCommand(data.category,data.amount,data.description,data.rationale)))
    @router.post("/api/security-deposit-deductions/{deduction_id}/sources",response_model=DeductionSourceResponse,status_code=201)
    def deduction_source(deduction_id:UUID,data:DeductionSourceInput):ready(True);return invoke(lambda:service.add_deduction_source(str(deduction_id),data.sourceKind,str(data.sourceId),historical_confirmed=data.historicalConfirmed,historical_reason=data.historicalReason,duplicate_use_confirmed=data.duplicateUseConfirmed))
    @router.delete("/api/security-deposit-deduction-sources/{source_id}",response_model=dict)
    def delete_deduction_source(source_id:UUID):ready(True);return invoke(lambda:service.delete_deduction_source(str(source_id)))
    @router.patch("/api/security-deposit-deductions/{deduction_id}",response_model=DeductionLineResponse)
    def patch_deduction(deduction_id:UUID,data:DeductionInput):ready(True);return invoke(lambda:service.update_deduction(str(deduction_id),DeductionCommand(data.category,data.amount,data.description,data.rationale)))
    @router.delete("/api/security-deposit-deductions/{deduction_id}",response_model=dict)
    def delete_deduction(deduction_id:UUID):ready(True);return invoke(lambda:service.delete_deduction(str(deduction_id)))
    @router.post("/api/security-deposit-settlements/{settlement_id}/credits",response_model=CreditResponse,status_code=201)
    def credit(settlement_id:UUID,data:CreditInput):ready(True);return invoke(lambda:service.add_credit(str(settlement_id),CreditCommand(data.kind,data.amount,data.description,data.calculatorPrincipal,data.annualRateBasisPoints,data.startsOn.isoformat() if data.startsOn else None,data.endsOn.isoformat() if data.endsOn else None,data.overrideReason)))
    @router.patch("/api/security-deposit-credits/{credit_id}",response_model=CreditResponse)
    def patch_credit(credit_id:UUID,data:CreditInput):ready(True);return invoke(lambda:service.update_credit(str(credit_id),CreditCommand(data.kind,data.amount,data.description,data.calculatorPrincipal,data.annualRateBasisPoints,data.startsOn.isoformat() if data.startsOn else None,data.endsOn.isoformat() if data.endsOn else None,data.overrideReason)))
    @router.delete("/api/security-deposit-credits/{credit_id}",response_model=dict)
    def delete_credit(credit_id:UUID):ready(True);return invoke(lambda:service.delete_credit(str(credit_id)))
    @router.post("/api/security-deposit-settlements/{settlement_id}/approve",response_model=SettlementResponse)
    def approve(settlement_id:UUID,data:ConfirmInput):ready(True);return invoke(lambda:service.approve_settlement(str(settlement_id),data.confirmed,zero_dollar_closure_confirmed=data.zeroDollarClosureConfirmed))
    @router.post("/api/security-deposit-settlements/{settlement_id}/complete",response_model=SettlementResponse)
    def complete(settlement_id:UUID,data:ConfirmInput):ready(True);return invoke(lambda:service.complete_settlement(str(settlement_id),data.confirmed))
    @router.post("/api/security-deposit-settlements/{settlement_id}/void",response_model=SettlementResponse)
    def void(settlement_id:UUID,data:VoidInput):ready(True);return invoke(lambda:service.void_settlement(str(settlement_id),VoidCommand(data.confirmed,data.reason)))
    @router.post("/api/security-deposit-settlements/{settlement_id}/refunds",response_model=RefundResponse,status_code=201)
    def refund(settlement_id:UUID,data:RefundInput):ready(True);return invoke(lambda:service.record_refund(str(settlement_id),DepositRefundCommand(str(data.idempotencyKey),str(data.recipientPartyId),data.paidOn.isoformat(),data.amount,data.currencyCode,data.reference,data.notes,data.recipientOverrideConfirmed,data.recipientOverrideReason,str(data.replacesRefundId) if data.replacesRefundId else None,data.duplicateConfirmed,data.historicalPartyConfirmed,data.historicalPartyReason)))
    @router.post("/api/security-deposit-refunds/{refund_id}/void",response_model=RefundResponse)
    def void_refund(refund_id:UUID,data:VoidInput):ready(True);return invoke(lambda:service.void_refund(str(refund_id),VoidCommand(data.confirmed,data.reason)))
    @router.get("/api/security-deposit-settlements/{settlement_id}",response_model=SettlementResponse)
    def detail(settlement_id:UUID):ready();return invoke(lambda:service.settlement(str(settlement_id)))
    return router

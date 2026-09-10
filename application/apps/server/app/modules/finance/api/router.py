"""Typed FIN-001 HTTP contract."""
from datetime import date
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from app.modules.finance.application.service import FinanceService
from app.modules.finance.domain.models import FinanceConflictError, FinanceError, FinanceNotFoundError, ReceiptAllocationCommand, RecordReceiptCommand, SynchronizeExpectationsCommand, TimelinessReviewCommand, VoidCommand
from app.modules.workspace.application.runtime import WorkspaceRuntime
class Contract(BaseModel): model_config=ConfigDict(extra="forbid")
class SynchronizeInput(Contract): leaseTermId:str; throughOn:date; scheduleAnchorOn:date|None=None; responsibilityEndsOnOverride:date|None=None; overrideReason:str|None=Field(None,max_length=1000); overrideConfirmed:StrictBool=False
class AllocationInput(Contract): expectationId:str; amountMinor:StrictInt=Field(gt=0)
class ReceiptInput(Contract): leaseId:str; idempotencyKey:str; receivedOn:date; amountMinor:StrictInt=Field(gt=0); currencyCode:Literal["USD"]; allocations:list[AllocationInput]=Field(min_length=1,max_length=100); receivedByPartyId:str|None=None; replacesReceiptId:str|None=None; notes:str|None=Field(None,max_length=4000)
class VoidInput(Contract): confirmed:StrictBool; voidReason:str=Field(min_length=1,max_length=1000)
class ReviewInput(Contract): decision:Literal["mark_missed","clear_missed"]; reason:str=Field(min_length=1,max_length=1000); confirmed:StrictBool
class AllocationResponse(Contract): id:str; receiptId:str; expectationId:str; amountMinor:int; createdAt:str; expectationDueOn:date; expectationPeriodStartsOn:date; expectationPeriodEndsOn:date
class ExpectationAllocationSummaryResponse(Contract): allocationId:str; receiptId:str; receivedOn:date; amountMinor:int; receiptLifecycleStatus:Literal["active","voided"]
class ExpectationResponse(Contract): id:str; leaseId:str; leaseTermId:str; propertyId:str; spaceId:str; periodStartsOn:date; periodEndsOn:date; dueOn:date; expectedAmountMinor:int; currencyCode:Literal["USD"]; paymentFrequency:Literal["monthly","weekly"]; scheduleAnchorOn:date; isProrated:bool; prorationNumeratorDays:int|None; prorationDenominatorDays:int|None; responsibilityBoundaryOn:date|None; responsibilityOverrideReason:str|None; voidedAt:str|None; voidReason:str|None; createdAt:str; lifecycleStatus:Literal["active","voided"]; settlementStatus:Literal["unpaid","partial","paid"]|None; timelinessStatus:Literal["upcoming","due","late","missed","paid_on_time","paid_late"]|None; effectiveMissedReview:bool; allocationCount:int; allocationSummaries:list[ExpectationAllocationSummaryResponse]; receivedAmountMinor:int; outstandingAmountMinor:int
class ReceiptResponse(Contract): id:str; leaseId:str; idempotencyKey:str; receivedOn:date; amountMinor:int; currencyCode:Literal["USD"]; receivedByPartyId:str|None; replacesReceiptId:str|None; notes:str|None; voidedAt:str|None; voidReason:str|None; createdAt:str; allocations:list[AllocationResponse]
class ExpectationPageResponse(Contract): items:list[ExpectationResponse]; nextCursor:str|None
class ReceiptPageResponse(Contract): items:list[ReceiptResponse]; nextCursor:str|None
def build_router(service:FinanceService,runtime:WorkspaceRuntime):
    router=APIRouter(tags=["finance"])
    def ready(write=False):
        if not runtime.ready or runtime.error: raise HTTPException(503,str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write: raise HTTPException(503,"Workspace writer lock is unavailable.")
    def invoke(fn):
        try:return fn()
        except FinanceNotFoundError as e: raise HTTPException(404,str(e)) from e
        except FinanceConflictError as e: raise HTTPException(409,str(e)) from e
        except FinanceError as e: raise HTTPException(400,str(e)) from e
    @router.post("/api/leases/{lease_id}/rent-expectations/synchronize",response_model=list[ExpectationResponse],status_code=201)
    def synchronize(lease_id:str,data:SynchronizeInput):
        ready(True); return invoke(lambda:service.synchronize(lease_id,SynchronizeExpectationsCommand(data.leaseTermId,data.throughOn.isoformat(),data.scheduleAnchorOn.isoformat() if data.scheduleAnchorOn else None,data.responsibilityEndsOnOverride.isoformat() if data.responsibilityEndsOnOverride else None,data.overrideReason,data.overrideConfirmed)))
    @router.get("/api/rent-expectations",response_model=ExpectationPageResponse)
    def expectations(leaseId:str|None=None,propertyId:str|None=None,status:Literal["unpaid","partial","paid"]|None=None,dueFrom:date|None=None,dueTo:date|None=None,timelinessStatus:Literal["upcoming","due","late","missed","paid_on_time","paid_late"]|None=None,includeVoided:bool=False,cursor:str|None=None,pageSize:int=Query(100,ge=1,le=500)): ready();return invoke(lambda:service.list_expectations(lease_id=leaseId,property_id=propertyId,status=status,due_from=dueFrom.isoformat() if dueFrom else None,due_to=dueTo.isoformat() if dueTo else None,timeliness=timelinessStatus,include_voided=includeVoided,cursor=cursor,page_size=pageSize))
    @router.get("/api/rent-expectations/{expectation_id}",response_model=ExpectationResponse)
    def expectation(expectation_id:str):ready();return invoke(lambda:service.expectation(expectation_id))
    @router.post("/api/rent-expectations/{expectation_id}/void",response_model=ExpectationResponse)
    def void_expectation(expectation_id:str,data:VoidInput):ready(True);return invoke(lambda:service.void_expectation(expectation_id,VoidCommand(data.confirmed,data.voidReason)))
    @router.post("/api/rent-expectations/{expectation_id}/timeliness-reviews",response_model=ExpectationResponse)
    def review(expectation_id:str,data:ReviewInput):ready(True);return invoke(lambda:service.review_timeliness(expectation_id,TimelinessReviewCommand(data.decision,data.reason,data.confirmed)))
    @router.post("/api/rent-receipts",response_model=ReceiptResponse,status_code=status.HTTP_201_CREATED)
    def receipt(data:ReceiptInput):
        ready(True); return invoke(lambda:service.record_receipt(RecordReceiptCommand(data.leaseId,data.idempotencyKey,data.receivedOn.isoformat(),data.amountMinor,data.currencyCode,tuple(ReceiptAllocationCommand(x.expectationId,x.amountMinor) for x in data.allocations),data.receivedByPartyId,data.replacesReceiptId,data.notes)))
    @router.get("/api/rent-receipts", response_model=ReceiptPageResponse)
    def receipts(leaseId: str | None = None, receivedFrom: date | None = None, receivedTo: date | None = None, receivedByPartyId: str | None = None, replacesReceiptId: str | None = None, includeVoided: bool = False, cursor: str | None = None, pageSize: int = Query(100, ge=1, le=500)): ready(); return invoke(lambda: service.list_receipts(lease_id=leaseId, received_from=receivedFrom.isoformat() if receivedFrom else None, received_to=receivedTo.isoformat() if receivedTo else None, received_by_party_id=receivedByPartyId, replaces_receipt_id=replacesReceiptId, include_voided=includeVoided, cursor=cursor, page_size=pageSize))
    @router.get("/api/rent-receipts/{receipt_id}",response_model=ReceiptResponse)
    def receipt_detail(receipt_id:str): ready();return invoke(lambda:service.receipt(receipt_id))
    @router.post("/api/rent-receipts/{receipt_id}/void",response_model=ReceiptResponse)
    def void_receipt(receipt_id:str,data:VoidInput):ready(True);return invoke(lambda:service.void_receipt(receipt_id,VoidCommand(data.confirmed,data.voidReason)))
    return router

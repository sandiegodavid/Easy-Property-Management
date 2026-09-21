from datetime import date, datetime
from enum import Enum
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator
from app.modules.finance.api.router import Contract
from app.modules.finance.domain.models import FinanceConflictError, FinanceError, FinanceNotFoundError, PAYMENT_METHOD_KINDS, ReceiptAllocationCommand
from app.modules.owner_accounting.application.service import OwnerRentReportService
from app.modules.owner_accounting.domain.models import OwnerRentReportCommand, OwnerReportConflictError, OwnerReportError, OwnerReportNotFoundError, RejectOwnerRentReportCommand, VerifyOwnerRentReportCommand

class PaymentMethodKind(str, Enum):
    automatic_bank_payment="automatic_bank_payment"; bank_transfer="bank_transfer"; check="check"; cash="cash"; online_payment="online_payment"; other="other"
class ReportStatus(str, Enum): pending="pending"; verified="verified"; rejected="rejected"
class ReceiptLifecycle(str, Enum): active="active"; voided="voided"
class AllocationInput(Contract): expectationId:UUID; amountMinor:StrictInt=Field(gt=0)
class ReportInput(Contract):
    leaseId:UUID; ownerPartyId:UUID; receivedOn:date; amountMinor:StrictInt=Field(gt=0,le=9_999_999_999); paymentMethodKind:PaymentMethodKind; reportedAtUtc:AwareDatetime; idempotencyKey:UUID
    paymentMethodLabel:str|None=Field(None,max_length=100); maskedReference:str|None=Field(None,max_length=100); otherPaymentMethodNote:str|None=Field(None,max_length=200); sourceNote:str|None=Field(None,max_length=4000); replacesReportId:UUID|None=None
class PatchInput(Contract):
    ownerPartyId:UUID|None=None; receivedOn:date|None=None; amountMinor:StrictInt|None=Field(None,gt=0,le=9_999_999_999); paymentMethodKind:PaymentMethodKind|None=None; paymentMethodLabel:str|None=Field(None,max_length=100); maskedReference:str|None=Field(None,max_length=100); otherPaymentMethodNote:str|None=Field(None,max_length=200); reportedAtUtc:AwareDatetime|None=None; sourceNote:str|None=Field(None,max_length=4000); idempotencyKey:UUID
class VerifyInput(Contract):
    confirmed:StrictBool; reviewNote:str=Field(min_length=1,max_length=1000); idempotencyKey:UUID; existingReceiptId:UUID|None=None; receiptIdempotencyKey:UUID|None=None; allocations:list[AllocationInput]=Field(default_factory=list); replacesReceiptId:UUID|None=None
    @model_validator(mode="after")
    def verify_mode(self):
        if (self.existingReceiptId is None) == (self.receiptIdempotencyKey is None):
            raise ValueError("Choose exactly one existing receipt or receipt creation.")
        if self.existingReceiptId is not None:
            if self.allocations or self.replacesReceiptId is not None:
                raise ValueError("Existing receipt verification cannot include allocations or replacement.")
        elif not 1 <= len(self.allocations) <= 100:
            raise ValueError("Receipt creation requires between 1 and 100 allocations.")
        return self
class RejectInput(Contract): confirmed:StrictBool; reason:str=Field(min_length=1,max_length=1000); idempotencyKey:UUID
class OwnerRentReportResponse(Contract):
    id:str; leaseId:str; propertyId:str; spaceId:str; propertyTimezoneSnapshot:str
    ownerPartyId:str; ownerDisplayNameSnapshot:str; receivedOn:str; amountMinor:int; currencyCode:str
    paymentMethodKind:PaymentMethodKind; paymentMethodLabel:str|None; maskedReference:str|None
    otherPaymentMethodNote:str|None; reportedAtUtc:str; sourceNote:str|None; status:ReportStatus
    verifiedReceiptId:str|None; reviewedAt:str|None; reviewNote:str|None; replacesReportId:str|None
    createdAt:str; updatedAt:str; receiptLifecycleStatus:ReceiptLifecycle|None; financiallyEffective:bool; evidenceCount:int
    files:list[dict[str,object]]|None=None; receiptAllocations:list[dict[str,object]]|None=None
    currentOwnerState:str|None=None; priorReportId:str|None=None; replacementReportId:str|None=None; replacementReceiptId:str|None=None
class OwnerRentReportPageResponse(Contract): items:list[OwnerRentReportResponse]; nextCursor:str|None
def build_router(service:OwnerRentReportService,runtime):
    router=APIRouter(prefix="/api",tags=["owner-accounting"])
    def ready(write=False):
        if not runtime.ready or runtime.error:raise HTTPException(503,str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:raise HTTPException(503,"Workspace writer lock is unavailable.")
    def invoke(call):
        try:return call()
        except OwnerReportNotFoundError as error:raise HTTPException(404,{"code":error.code,"message":str(error)}) from error
        except OwnerReportConflictError as error:raise HTTPException(409,{"code":error.code,"message":str(error),"details":error.details}) from error
        except OwnerReportError as error:raise HTTPException(400,{"code":error.code,"message":str(error)}) from error
        except FinanceNotFoundError as error:raise HTTPException(404,{"code":"owner_rent_report_not_found","message":str(error)}) from error
        except FinanceConflictError as error:raise HTTPException(409,{"code":"owner_rent_report_conflict","message":str(error)}) from error
        except FinanceError as error:raise HTTPException(400,{"code":"owner_rent_report_validation","message":str(error)}) from error
    @router.post("/owner-rent-reports",status_code=status.HTTP_201_CREATED,response_model=OwnerRentReportResponse)
    def create(data:ReportInput):
        ready(True);return invoke(lambda:service.create(OwnerRentReportCommand(str(data.leaseId),str(data.ownerPartyId),data.receivedOn.isoformat(),data.amountMinor,data.paymentMethodKind.value,str(data.idempotencyKey),data.reportedAtUtc.isoformat(),data.paymentMethodLabel,data.maskedReference,data.otherPaymentMethodNote,data.sourceNote,str(data.replacesReportId) if data.replacesReportId else None)))
    @router.get("/owner-rent-reports",response_model=OwnerRentReportPageResponse)
    def reports(ownerPartyId:UUID|None=None,propertyId:UUID|None=None,spaceId:UUID|None=None,leaseId:UUID|None=None,receivedFrom:date|None=None,receivedTo:date|None=None,status:ReportStatus|None=None,hasEvidence:StrictBool|None=None,receiptLifecycle:ReceiptLifecycle|None=None,cursor:str|None=None,pageSize:int=Query(100,ge=1,le=500)):
        ready()
        parsed=None
        if cursor is not None:
            parts=cursor.split("|",1)
            if len(parts)!=2: raise HTTPException(422,"Cursor must contain a received date and report ID.")
            try: parsed=(date.fromisoformat(parts[0]).isoformat(),str(UUID(parts[1])))
            except ValueError as error: raise HTTPException(422,"Cursor is invalid.") from error
        return invoke(lambda:service.list(owner_party_id=str(ownerPartyId) if ownerPartyId else None,property_id=str(propertyId) if propertyId else None,space_id=str(spaceId) if spaceId else None,lease_id=str(leaseId) if leaseId else None,received_from=None if receivedFrom is None else receivedFrom.isoformat(),received_to=None if receivedTo is None else receivedTo.isoformat(),status=None if status is None else status.value,has_evidence=hasEvidence,receipt_lifecycle=None if receiptLifecycle is None else receiptLifecycle.value,cursor=parsed,page_size=pageSize))
    @router.get("/owner-rent-reports/{report_id}",response_model=OwnerRentReportResponse)
    def detail(report_id:UUID):ready();return invoke(lambda:service.detail(str(report_id)))
    @router.patch("/owner-rent-reports/{report_id}",response_model=OwnerRentReportResponse)
    def patch(report_id:UUID,data:PatchInput):
        ready(True)
        raw=data.model_dump(exclude={"idempotencyKey"},exclude_unset=True)
        names={"ownerPartyId":"owner_party_id","receivedOn":"received_on","amountMinor":"amount_minor","paymentMethodKind":"payment_method_kind","paymentMethodLabel":"payment_method_label","maskedReference":"masked_reference","otherPaymentMethodNote":"other_payment_method_note","reportedAtUtc":"reported_at_utc","sourceNote":"source_note"}
        values={names[key]:(value.isoformat() if isinstance(value,(date,datetime)) else str(value) if isinstance(value,UUID) else value) for key,value in raw.items()}
        return invoke(lambda:service.patch(str(report_id),values,str(data.idempotencyKey)))
    @router.post("/owner-rent-reports/{report_id}/verify",response_model=OwnerRentReportResponse)
    def verify(report_id:UUID,data:VerifyInput):
        ready(True); return invoke(lambda:service.verify(str(report_id),VerifyOwnerRentReportCommand(data.confirmed,data.reviewNote,str(data.existingReceiptId) if data.existingReceiptId else None,str(data.receiptIdempotencyKey) if data.receiptIdempotencyKey else None,tuple(ReceiptAllocationCommand(str(item.expectationId),item.amountMinor) for item in data.allocations),str(data.replacesReceiptId) if data.replacesReceiptId else None),str(data.idempotencyKey)))
    @router.post("/owner-rent-reports/{report_id}/reject",response_model=OwnerRentReportResponse)
    def reject(report_id:UUID,data:RejectInput):ready(True);return invoke(lambda:service.reject(str(report_id),RejectOwnerRentReportCommand(data.confirmed,data.reason),str(data.idempotencyKey)))
    return router

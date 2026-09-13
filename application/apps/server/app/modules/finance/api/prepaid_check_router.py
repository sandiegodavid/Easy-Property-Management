"""Typed FIN-007 prepaid-check API."""
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.modules.finance.application.prepaid_check_service import PrepaidCheckService
from app.modules.finance.domain.models import FinanceConflictError, FinanceError, FinanceNotFoundError, PrepaidCheckCommand, PrepaidCheckTransitionCommand
from app.modules.workspace.application.runtime import WorkspaceRuntime


class Contract(BaseModel): model_config = ConfigDict(extra="forbid")
class CreateInput(Contract):
    expectationId: UUID
    payerPartyId: UUID
    receivedOn: date
    checkDatedOn: date
    maskedReference: str | None = Field(None, max_length=80)
    idempotencyKey: UUID
class DepositInput(Contract):
    idempotencyKey: UUID
    confirmed: StrictBool
    occurredOn: date | None = None
    existingReceiptId: UUID | None = None
class ReturnInput(Contract):
    idempotencyKey: UUID
    confirmed: StrictBool
    reason: str = Field(min_length=1, max_length=1000)
    returnedOn: date
class VoidInput(Contract):
    idempotencyKey: UUID
    confirmed: StrictBool
    reason: str = Field(min_length=1, max_length=1000)
class ReplaceInput(CreateInput):
    confirmed: StrictBool
    reason: str = Field(min_length=1, max_length=1000)
class ExpectationSummary(Contract): id:str; periodStartsOn:date; periodEndsOn:date; dueOn:date; amountMinor:int
class ReceiptSummary(Contract): id:str; receivedOn:date; voidedAt:str|None
class PrepaidCheckResponse(Contract):
    id:str; expectationId:str; leaseId:str; propertyId:str; spaceId:str; payerPartyId:str; receivedOn:date; checkDatedOn:date
    amountMinor:int; currencyCode:Literal["USD"]; maskedReference:str|None
    status:Literal["scheduled","deposited","returned","voided","replaced"]
    receiptId:str|None; depositedOn:date|None; returnedOn:date|None; returnedReason:str|None
    voidedAt:str|None; voidReason:str|None; replacesPrepaidCheckId:str|None; replacedByPrepaidCheckId:str|None; replacementReason:str|None
    reminderTaskId:str|None; reminderStatus:Literal["pending", "acknowledged", "dismissed"]|None; createdAt:str; updatedAt:str
    depositEligibility:Literal["not_yet_eligible","eligible","not_applicable"]
    expectation:ExpectationSummary; receipt:ReceiptSummary|None
class PrepaidCheckPageResponse(Contract): items:list[PrepaidCheckResponse]; nextCursor:str|None


def build_router(service: PrepaidCheckService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(prefix="/api/prepaid-checks", tags=["finance"])
    def ready(write: bool = False):
        if not runtime.ready or runtime.error: raise HTTPException(503, str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write: raise HTTPException(503, "Workspace writer lock is unavailable.")
    def invoke(fn):
        try: return fn()
        except FinanceNotFoundError as error:
            raise HTTPException(404, {"code": "prepaid_check_not_found", "message": str(error)}) from error
        except FinanceConflictError as error:
            raise HTTPException(409, {"code": error.code, "message": str(error), **error.details}) from error
        except FinanceError as error:
            raise HTTPException(422, {"code": "prepaid_check_validation_error", "message": str(error)}) from error
    def create_command(data: CreateInput) -> PrepaidCheckCommand:
        return PrepaidCheckCommand(str(data.expectationId), str(data.payerPartyId), data.receivedOn.isoformat(), data.checkDatedOn.isoformat(), data.maskedReference, str(data.idempotencyKey))
    def deposit_command(data: DepositInput) -> PrepaidCheckTransitionCommand:
        return PrepaidCheckTransitionCommand(str(data.idempotencyKey), data.confirmed, occurred_on=data.occurredOn.isoformat() if data.occurredOn else None, existing_receipt_id=str(data.existingReceiptId) if data.existingReceiptId else None)
    def return_command(data: ReturnInput) -> PrepaidCheckTransitionCommand:
        return PrepaidCheckTransitionCommand(str(data.idempotencyKey), data.confirmed, data.reason, data.returnedOn.isoformat())
    def void_command(data: VoidInput) -> PrepaidCheckTransitionCommand:
        return PrepaidCheckTransitionCommand(str(data.idempotencyKey), data.confirmed, data.reason)
    @router.post("", response_model=PrepaidCheckResponse, status_code=status.HTTP_201_CREATED)
    def create(data: CreateInput): ready(True); return invoke(lambda: service.create(create_command(data)))
    @router.get("", response_model=PrepaidCheckPageResponse)
    def list_checks(leaseId: UUID | None = None, propertyId: UUID | None = None, spaceId: UUID | None = None, payerPartyId: UUID | None = None, expectationId: UUID | None = None, status: Literal["scheduled","deposited","returned","voided","replaced"] | None = None, eligibility: Literal["not_yet_eligible","eligible","not_applicable"] | None = None, cursor: str | None = None, pageSize: int = 100): ready(); return invoke(lambda: service.list(lease_id=str(leaseId) if leaseId else None, property_id=str(propertyId) if propertyId else None, space_id=str(spaceId) if spaceId else None, payer_party_id=str(payerPartyId) if payerPartyId else None, expectation_id=str(expectationId) if expectationId else None, status=status, eligibility=eligibility, cursor=cursor, page_size=pageSize))
    @router.get("/{check_id}", response_model=PrepaidCheckResponse)
    def get(check_id: UUID): ready(); return invoke(lambda: service.get(str(check_id)))
    @router.post("/{check_id}/deposit", response_model=PrepaidCheckResponse)
    def deposit(check_id: UUID, data: DepositInput): ready(True); return invoke(lambda: service.deposit(str(check_id), deposit_command(data)))
    @router.post("/{check_id}/return", response_model=PrepaidCheckResponse)
    def return_check(check_id: UUID, data: ReturnInput): ready(True); return invoke(lambda: service.return_check(str(check_id), return_command(data)))
    @router.post("/{check_id}/void", response_model=PrepaidCheckResponse)
    def void(check_id: UUID, data: VoidInput): ready(True); return invoke(lambda: service.void(str(check_id), void_command(data)))
    @router.post("/{check_id}/replace", response_model=PrepaidCheckResponse, status_code=status.HTTP_201_CREATED)
    def replace(check_id: UUID, data: ReplaceInput):
        ready(True)
        return invoke(lambda: service.replace(str(check_id), create_command(data), confirmed=data.confirmed, reason=data.reason))
    return router

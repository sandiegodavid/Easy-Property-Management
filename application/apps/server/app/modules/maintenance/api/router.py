from datetime import date, datetime
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from app.modules.maintenance.application.service import MaintenanceService
from app.modules.maintenance.domain.models import AppointmentCreate, CostCreate, IssueCreate, ReporterAttribution, ReporterCorrection, MaintenanceConflictError, MaintenanceError, MaintenanceNotFoundError
from app.modules.workspace.application.runtime import WorkspaceRuntime
class Contract(BaseModel): model_config=ConfigDict(extra="forbid")
class ReporterInput(Contract): role:Literal["owner","tenant","manager","staff"]; subjectKind:Literal["party","local_operator"]; partyId:UUID|None=None; historicalSelectionConfirmed:StrictBool|None=None; historicalSelectionReason:str|None=Field(None,min_length=1,max_length=1000)
class IssueInput(Contract): propertyId: UUID; spaceId: UUID|None=None; summary:str=Field(min_length=1,max_length=240); description:str=Field(min_length=1,max_length=10000); category:Literal["plumbing","electrical","heating_cooling","appliance","structural","safety_security","pest","exterior_grounds","cleaning","other"]; categoryDetail:str|None=Field(None,max_length=200); priority:Literal["low","normal","high","urgent"]="normal"; reportedAtUtc:datetime; reporter:ReporterInput; idempotencyKey:UUID
class IssuePatch(Contract): summary:str|None=Field(None,min_length=1,max_length=240); description:str|None=Field(None,min_length=1,max_length=10000); category:Literal["plumbing","electrical","heating_cooling","appliance","structural","safety_security","pest","exterior_grounds","cleaning","other"]|None=None; categoryDetail:str|None=Field(None,max_length=200); priority:Literal["low","normal","high","urgent"]|None=None
class Reason(Contract): confirmed:StrictBool; reason:str=Field(min_length=1,max_length=1000)
class ReporterCorrectionInput(Contract): reporter:ReporterInput; confirmed:StrictBool; reason:str=Field(min_length=1,max_length=1000)
class AppointmentInput(Contract): startsAtUtc:datetime; endsAtUtc:datetime; purpose:str=Field(min_length=1,max_length=500); instructions:str|None=Field(None,max_length=4000); idempotencyKey:UUID
class CostInput(Contract): contextKind:Literal["operator_estimate","work_reported"]; label:str=Field(min_length=1,max_length=200); amount:str; observedOn:date; sourceNote:str|None=Field(None,max_length=4000); replacesCostContextId:UUID|None=None; idempotencyKey:UUID
class ExpenseLinkInput(Contract): expenseId:UUID; idempotencyKey:UUID
class AppointmentPatch(Contract): startsAtUtc:datetime; endsAtUtc:datetime; purpose:str=Field(min_length=1,max_length=500); instructions:str|None=Field(None,max_length=4000); rescheduleReason:str|None=Field(None,max_length=1000)
class AppointmentFinish(Contract): confirmed:StrictBool; outcomeNote:str|None=Field(None,max_length=4000)
class FollowUpInput(Contract): title:str=Field(min_length=1,max_length=240); notes:str|None=Field(None,max_length=10000); priority:Literal["low","normal","high","urgent"]="normal"; dueAtUtc:datetime|None=None; dueTimezone:str|None=None; idempotencyKey:UUID
class AppointmentResponse(Contract): id:UUID; issueId:UUID; startsAtUtc:datetime; endsAtUtc:datetime; scheduledTimezone:str; purpose:str; instructions:str|None; status:Literal["scheduled","completed","cancelled"]; completedAt:datetime|None; outcomeNote:str|None; cancelledAt:datetime|None; cancellationReason:str|None; createdAt:datetime; updatedAt:datetime
class CostResponse(Contract): id:UUID; issueId:UUID; contextKind:Literal["operator_estimate","work_reported"]; label:str; amountMinor:int; currencyCode:Literal["USD"]; observedOn:str; sourceNote:str|None; replacesCostContextId:UUID|None; voidedAt:datetime|None; voidReason:str|None; createdAt:datetime
class ExpenseLinkResponse(Contract): id:UUID; issueId:UUID; expenseId:UUID; createdAt:datetime; archivedAt:datetime|None; archiveReason:str|None
class FileSummaryResponse(Contract): id:UUID; entityType:str; entityId:UUID; purpose:str; fileId:UUID; createdAt:datetime; archivedAt:datetime|None; archiveReason:str|None; originalName:str; mediaType:str; sizeBytes:int; contentSha256:str
class TaskSummaryResponse(Contract): id:UUID; title:str; status:Literal["open","in_progress","completed","cancelled"]; priority:Literal["low","normal","high","urgent"]; dueAtUtc:datetime|None; dueTimezone:str|None; isAllDay:bool; relatedEntityType:str; relatedEntityId:UUID
class PropertySummaryResponse(Contract): id:UUID; displayName:str|None; status:str|None=None; timeZone:str|None=None
class SpaceSummaryResponse(Contract): id:UUID; displayName:str|None; status:str|None=None
class ExpenseSummaryResponse(Contract): id:UUID; propertyId:UUID; spaceId:UUID|None; lifecycleStatus:Literal["active","voided"]; netAmountMinor:int; currencyCode:Literal["USD"]; occurredOn:str; payeeSnapshot:str
class AppointmentSummaryResponse(Contract): id:UUID; startsAtUtc:datetime; endsAtUtc:datetime; status:Literal["scheduled","completed","cancelled"]
class ReporterResponse(Contract): role:Literal["owner","tenant","manager","staff"]; subjectKind:Literal["party","local_operator"]; partyId:UUID|None; displayName:str; currentPartyState:Literal["active","archived"]|None=None
class CommunicationSummaryResponse(Contract): id:UUID; subject:str; channel:str; direction:str; status:str; occurredAtUtc:datetime; occurredTimezone:str
class DetailedAppointmentResponse(AppointmentResponse): files:list[FileSummaryResponse]=[]
class DetailedCostResponse(CostResponse): files:list[FileSummaryResponse]=[]
class DetailedExpenseLinkResponse(ExpenseLinkResponse): expense:ExpenseSummaryResponse|None
class IssueSummaryResponse(Contract): id:UUID; propertyId:UUID; spaceId:UUID|None; summary:str; category:str; priority:str; status:str; reportedAtUtc:datetime; reportedTimezone:str; reporter:ReporterResponse; property:PropertySummaryResponse; space:SpaceSummaryResponse|None; currentAppointment:AppointmentSummaryResponse|None; activeFollowUpCount:int; evidenceCount:int; linkedExpenseCount:int
class IssueResponse(Contract): id:UUID; propertyId:UUID; spaceId:UUID|None; summary:str; description:str; category:str; categoryDetail:str|None; priority:str; status:str; reportedAtUtc:datetime; reportedTimezone:str; reporter:ReporterResponse; resolutionSummary:str|None; resolvedAt:datetime|None; cancellationReason:str|None; cancelledAt:datetime|None; createdAt:datetime; updatedAt:datetime; property:PropertySummaryResponse; space:SpaceSummaryResponse|None; files:list[FileSummaryResponse]; appointments:list[DetailedAppointmentResponse]; costContexts:list[DetailedCostResponse]; expenseLinks:list[DetailedExpenseLinkResponse]; tasks:list[TaskSummaryResponse]; communications:list[CommunicationSummaryResponse]
class IssuePageResponse(Contract): items:list[IssueSummaryResponse]; nextCursor:str|None
def build_router(service:MaintenanceService,runtime:WorkspaceRuntime):
 router=APIRouter(prefix="/api",tags=["maintenance"])
 def ready(write=False):
  if not runtime.ready or runtime.error:raise HTTPException(503,str(runtime.error or "Workspace is not ready."))
  if write and not runtime.can_write:raise HTTPException(503,"Workspace writer lock is unavailable.")
 def invoke(fn):
  try:return fn()
  except MaintenanceNotFoundError as e:raise HTTPException(404,{"code":e.code,"message":str(e)}) from e
  except MaintenanceConflictError as e:raise HTTPException(409,{"code":e.code,"message":str(e)}) from e
  except MaintenanceError as e:raise HTTPException(400,{"code":e.code,"message":str(e)}) from e
 @router.post("/maintenance-issues",response_model=IssueResponse,status_code=status.HTTP_201_CREATED)
 def create(data:IssueInput):
  ready(True); reporter=data.reporter
  return invoke(lambda:service.create_issue(IssueCreate(str(data.propertyId),str(data.spaceId) if data.spaceId else None,data.summary,data.description,data.category,data.categoryDetail,data.priority,data.reportedAtUtc.isoformat(),ReporterAttribution(reporter.role,reporter.subjectKind,str(reporter.partyId) if reporter.partyId else None,reporter.historicalSelectionConfirmed,reporter.historicalSelectionReason)),str(data.idempotencyKey)))
 @router.get("/maintenance-issues",response_model=IssuePageResponse)
 def list_issues(propertyId:UUID|None=None,spaceId:UUID|None=None,category:Literal["plumbing","electrical","heating_cooling","appliance","structural","safety_security","pest","exterior_grounds","cleaning","other"]|None=None,priority:Literal["low","normal","high","urgent"]|None=None,status:Literal["open","in_progress","resolved","cancelled"]|None=None,reporterRole:Literal["owner","tenant","manager","staff"]|None=None,reporterPartyId:UUID|None=None,reporterSubjectKind:Literal["party","local_operator"]|None=None,reportedFrom:datetime|None=None,reportedTo:datetime|None=None,appointmentFrom:datetime|None=None,appointmentTo:datetime|None=None,hasEvidence:bool|None=None,hasLinkedExpense:bool|None=None,hasActiveTask:bool|None=None,cursor:str|None=None,pageSize:int=Query(100,ge=1,le=500)):
  ready()
  parsed=None
  if cursor:
   try:
    priority_value,reported,item_id=cursor.split("|",2)
    if priority_value not in {"urgent","high","normal","low"}: raise ValueError
    if datetime.fromisoformat(reported).tzinfo is None: raise ValueError
    parsed=(priority_value,reported,str(UUID(item_id)))
   except (ValueError,AttributeError) as error:raise HTTPException(422,{"code":"maintenance_validation","message":"cursor is invalid."}) from error
  return invoke(lambda:service.list_issues(property_id=str(propertyId) if propertyId else None,space_id=str(spaceId) if spaceId else None,category=category,priority=priority,status=status,reporter_role=reporterRole,reporter_party_id=str(reporterPartyId) if reporterPartyId else None,reporter_subject_kind=reporterSubjectKind,reported_from=reportedFrom.isoformat() if reportedFrom else None,reported_to=reportedTo.isoformat() if reportedTo else None,appointment_from=appointmentFrom.isoformat() if appointmentFrom else None,appointment_to=appointmentTo.isoformat() if appointmentTo else None,has_evidence=hasEvidence,has_linked_expense=hasLinkedExpense,has_active_task=hasActiveTask,cursor=parsed,page_size=pageSize))
 @router.get("/maintenance-issues/{issue_id}",response_model=IssueResponse)
 def detail(issue_id:UUID):ready();return invoke(lambda:service.detail(str(issue_id)))
 @router.patch("/maintenance-issues/{issue_id}",response_model=IssueResponse)
 def patch(issue_id:UUID,data:IssuePatch):
  ready(True)
  names={"categoryDetail":"category_detail"}
  return invoke(lambda:service.patch_issue(str(issue_id),{names.get(k,k):v for k,v in data.model_dump(exclude_unset=True).items()}))
 @router.post("/maintenance-issues/{issue_id}/reporter/correct",response_model=IssueResponse)
 def correct_reporter(issue_id:UUID,data:ReporterCorrectionInput):
  ready(True); reporter=data.reporter
  return invoke(lambda:service.correct_reporter(str(issue_id),ReporterCorrection(ReporterAttribution(reporter.role,reporter.subjectKind,str(reporter.partyId) if reporter.partyId else None,reporter.historicalSelectionConfirmed,reporter.historicalSelectionReason),data.confirmed,data.reason)))
 @router.post("/maintenance-issues/{issue_id}/start",response_model=IssueResponse)
 def start(issue_id:UUID):ready(True);return invoke(lambda:service.transition(str(issue_id),"start"))
 @router.post("/maintenance-issues/{issue_id}/return-to-open",response_model=IssueResponse)
 def return_to_open(issue_id:UUID):ready(True);return invoke(lambda:service.transition(str(issue_id),"return_to_open"))
 for path,action in (("resolve","resolve"),("cancel","cancel"),("reopen","reopen")):
  def endpoint(issue_id:UUID,data:Reason,_action=action):ready(True);return invoke(lambda:service.transition(str(issue_id),_action,data.reason,data.confirmed))
  router.add_api_route("/maintenance-issues/{issue_id}/"+path,endpoint,methods=["POST"],response_model=IssueResponse)
 @router.post("/maintenance-issues/{issue_id}/appointments",response_model=AppointmentResponse,status_code=201)
 def appointment(issue_id:UUID,data:AppointmentInput):ready(True);return invoke(lambda:service.create_appointment(str(issue_id),AppointmentCreate(data.startsAtUtc.isoformat(),data.endsAtUtc.isoformat(),data.purpose,data.instructions),str(data.idempotencyKey)))
 @router.post("/maintenance-issues/{issue_id}/cost-contexts",response_model=CostResponse,status_code=201)
 def cost(issue_id:UUID,data:CostInput):ready(True);return invoke(lambda:service.create_cost(str(issue_id),CostCreate(data.contextKind,data.label,data.amount,data.observedOn.isoformat(),data.sourceNote,str(data.replacesCostContextId) if data.replacesCostContextId else None),str(data.idempotencyKey)))
 @router.post("/maintenance-issues/{issue_id}/expense-links",response_model=ExpenseLinkResponse,status_code=201)
 def expense_link(issue_id:UUID,data:ExpenseLinkInput):ready(True);return invoke(lambda:service.link_expense(str(issue_id),str(data.expenseId),str(data.idempotencyKey)))
 @router.patch("/maintenance-appointments/{appointment_id}",response_model=AppointmentResponse)
 def patch_appointment(appointment_id:UUID,data:AppointmentPatch):ready(True);return invoke(lambda:service.update_appointment(str(appointment_id),AppointmentCreate(data.startsAtUtc.isoformat(),data.endsAtUtc.isoformat(),data.purpose,data.instructions),data.rescheduleReason))
 @router.post("/maintenance-appointments/{appointment_id}/complete",response_model=AppointmentResponse)
 def complete_appointment(appointment_id:UUID,data:AppointmentFinish):ready(True);return invoke(lambda:service.finish_appointment(str(appointment_id),cancelled=False,reason=data.outcomeNote,confirmed=data.confirmed))
 @router.post("/maintenance-appointments/{appointment_id}/cancel",response_model=AppointmentResponse)
 def cancel_appointment(appointment_id:UUID,data:Reason):ready(True);return invoke(lambda:service.finish_appointment(str(appointment_id),cancelled=True,reason=data.reason,confirmed=data.confirmed))
 @router.post("/maintenance-cost-contexts/{context_id}/void",response_model=CostResponse)
 def void_cost(context_id:UUID,data:Reason):ready(True);return invoke(lambda:service.void_cost(str(context_id),data.reason,data.confirmed))
 @router.post("/maintenance-expense-links/{link_id}/archive",response_model=ExpenseLinkResponse)
 def archive_link(link_id:UUID,data:Reason):ready(True);return invoke(lambda:service.archive_expense_link(str(link_id),data.reason,data.confirmed))
 @router.post("/maintenance-issues/{issue_id}/follow-ups",response_model=TaskSummaryResponse,status_code=201)
 def follow_up(issue_id:UUID,data:FollowUpInput):ready(True);return invoke(lambda:service.create_follow_up(str(issue_id),data.title,data.notes,data.priority,data.dueAtUtc.isoformat() if data.dueAtUtc else None,data.dueTimezone,str(data.idempotencyKey)))
 return router

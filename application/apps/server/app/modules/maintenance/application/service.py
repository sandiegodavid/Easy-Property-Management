"""Maintenance aggregate workflows."""
from __future__ import annotations
from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo
from app.modules.maintenance.domain.models import *
from app.modules.maintenance.domain.models import text as maintenance_text
from app.modules.maintenance.application.ports import MaintenanceUnitOfWork

def _stamp(): return datetime.now(UTC).isoformat()
def _dict(row):
    hidden={"idempotency_key","request_fingerprint"}
    return {"id":row["id"], **{_camel(k):v for k,v in row.items() if k!="id" and k not in hidden}}
def _camel(value):
    parts=value.split("_");return parts[0]+"".join(x.title() for x in parts[1:])
def _camel_mapping(value):
    return None if value is None else {_camel(key): item for key,item in value.items()}
def _task_summary(value):
    mapped = _camel_mapping(value)
    return {key: mapped[key] for key in {"id","title","status","priority","dueAtUtc","dueTimezone","isAllDay","relatedEntityType","relatedEntityId"}}

class MaintenanceService:
    def __init__(self, unit_of_work: MaintenanceUnitOfWork): self.unit_of_work=unit_of_work
    def create_issue(self, command:IssueCreate, idempotency_key:str):
        uuid(idempotency_key,"idempotencyKey"); fp=fingerprint("issue",command)
        def op(tx):
            existing=tx.issue_by_key(idempotency_key)
            if existing:
                if existing["request_fingerprint"]!=fp:raise MaintenanceConflictError("Idempotency key payload changed.","idempotency_conflict")
                return self._detail(tx,existing["id"])
            context=tx.issue_context(command.property_id,command.space_id)
            if not context:raise MaintenanceNotFoundError("Property or space was not found.")
            if context["property"]["status"]!="active" or (context["space"] and context["space"]["status"]!="active"):raise MaintenanceConflictError("Issue requires active property and space.","archived_context")
            reporter=self._validated_reporter(tx,command.reporter,command.property_id,command.space_id,command.reported_at_utc,context["property"]["time_zone"])
            now=_stamp(); item={"id":str(uuid4()),"property_id":command.property_id,"space_id":command.space_id,"summary":command.summary,"description":command.description,"category":command.category,"category_detail":command.category_detail,"priority":command.priority,"status":"open","reported_at_utc":command.reported_at_utc,"reported_timezone":context["property"]["time_zone"],**reporter,"resolution_summary":None,"resolved_at":None,"cancellation_reason":None,"cancelled_at":None,"idempotency_key":idempotency_key,"request_fingerprint":fp,"created_at":now,"updated_at":now}
            tx.insert_issue(item)
            audit_after=_dict(item)
            if command.reporter.historical_selection_reason:
                audit_after["historicalSelectionReason"]=command.reporter.historical_selection_reason
            self._audit(tx,"maintenance_issue",item["id"],"created",None,audit_after,"issue_created")
            return self._detail(tx,item["id"])
        return self.unit_of_work.write(op)
    def patch_issue(self, issue_id, values):
        def op(tx):
            old=self._require(tx.issue,issue_id,"Issue")
            if old["status"] not in {"open","in_progress"}:raise MaintenanceConflictError("Only active issues can be edited.","issue_closed")
            allowed={k:v for k,v in values.items() if k in {"summary","description","category","category_detail","priority"}}
            updated={**old,**allowed,"updated_at":_stamp()}
            IssueCreate(old["property_id"],old["space_id"],updated["summary"],updated["description"],updated["category"],updated["category_detail"],updated["priority"],old["reported_at_utc"],ReporterAttribution(old["reporter_role"],old["reporter_subject_kind"],old["reporter_party_id"]))
            if all(old[k]==updated[k] for k in allowed):return self._detail(tx,issue_id)
            tx.replace_issue(issue_id,updated);self._audit(tx,"maintenance_issue",issue_id,"updated",_dict(old),_dict(updated),"issue_updated");return self._detail(tx,issue_id)
        return self.unit_of_work.write(op)
    def correct_reporter(self, issue_id, command: ReporterCorrection):
        def op(tx):
            old=self._require(tx.issue,issue_id,"Issue")
            replacement=self._validated_reporter(tx,command.reporter,old["property_id"],old["space_id"],old["reported_at_utc"],old["reported_timezone"])
            if all(old[key] == value for key,value in replacement.items()):
                raise MaintenanceConflictError("Reporter correction makes no change.","reporter_unchanged")
            updated={**old,**replacement,"updated_at":_stamp()}
            tx.replace_issue(issue_id,updated)
            audit_after=_dict(updated)
            if command.reporter.historical_selection_reason:
                audit_after["historicalSelectionReason"]=command.reporter.historical_selection_reason
            self._audit(tx,"maintenance_issue",issue_id,"reporter_corrected",_dict(old),audit_after,"reporter_corrected",narrative=command.reason)
            return self._detail(tx,issue_id)
        return self.unit_of_work.write(op)
    def transition(self,issue_id,action,reason=None,confirmed=None):
        if action in {"resolve", "cancel", "reopen"}:
            if type(confirmed) is not bool or not confirmed:raise MaintenanceError("Explicit confirmation is required.")
            reason=maintenance_text(reason,"reason",1000,required=True)
        elif action not in {"start", "return_to_open"}:
            raise MaintenanceError("Transition is invalid.")
        def op(tx):
            old=self._require(tx.issue,issue_id,"Issue")
            if action=="start" and old["status"]!="open":raise MaintenanceConflictError("Issue cannot be started.")
            if action=="return_to_open" and old["status"]!="in_progress":raise MaintenanceConflictError("Issue cannot return to open.")
            if action in {"resolve","cancel"} and old["status"] not in {"open","in_progress"}:raise MaintenanceConflictError("Issue cannot transition.")
            if action=="reopen" and old["status"] not in {"resolved","cancelled"}:raise MaintenanceConflictError("Issue cannot be reopened.")
            if action=="resolve" and any(x["status"]=="scheduled" and x["starts_at_utc"]>_stamp() for x in tx.appointments_for_issue(issue_id)):raise MaintenanceConflictError("Scheduled appointments must be completed or cancelled.","scheduled_appointment")
            new={**old,"status":{"start":"in_progress","return_to_open":"open","resolve":"resolved","cancel":"cancelled","reopen":"open"}[action],"updated_at":_stamp(),"resolution_summary":reason if action=="resolve" else None,"resolved_at":_stamp() if action=="resolve" else None,"cancellation_reason":reason if action=="cancel" else None,"cancelled_at":_stamp() if action=="cancel" else None}
            # Reopen keeps the former terminal narrative in historical audit
            # snapshots, but clears terminal fields on the current record.
            if action == "reopen":
                new.update(resolution_summary=None,resolved_at=None,cancellation_reason=None,cancelled_at=None)
            action_name={"start":"started","return_to_open":"returned_to_open","resolve":"resolved","cancel":"cancelled","reopen":"reopened"}[action]
            tx.replace_issue(issue_id,new)
            self._audit(tx,"maintenance_issue",issue_id,action_name,_dict(old),_dict(new),"issue_"+action, narrative=reason)
            return self._detail(tx,issue_id)
        return self.unit_of_work.write(op)
    def create_appointment(self,issue_id,command:AppointmentCreate,idempotency_key):
        uuid(idempotency_key,"idempotencyKey");fp=fingerprint("appointment",{"issueId":issue_id,"command":command.__dict__})
        def op(tx):
            prior=tx.appointment_by_key(idempotency_key)
            if prior:
                if prior["request_fingerprint"]!=fp:raise MaintenanceConflictError("Idempotency key payload changed.","idempotency_conflict")
                return _dict(dict(prior))
            issue=self._require(tx.issue,issue_id,"Issue")
            context=tx.issue_context(issue["property_id"],issue["space_id"])
            if issue["status"] not in {"open","in_progress"} or not context or context["property"]["status"]!="active" or (context["space"] and context["space"]["status"]!="active"):raise MaintenanceConflictError("Appointment requires an active issue context.","archived_context")
            now=_stamp();item={"id":str(uuid4()),"issue_id":issue_id,"starts_at_utc":command.starts_at_utc,"ends_at_utc":command.ends_at_utc,"scheduled_timezone":context["property"]["time_zone"],"purpose":command.purpose,"instructions":command.instructions,"status":"scheduled","completed_at":None,"outcome_note":None,"cancelled_at":None,"cancellation_reason":None,"idempotency_key":idempotency_key,"request_fingerprint":fp,"created_at":now,"updated_at":now};tx.insert_appointment(item);self._audit(tx,"maintenance_appointment",item["id"],"created",None,_dict(item),"appointment_created");return _dict(item)
        return self.unit_of_work.write(op)
    def create_cost(self,issue_id,command:CostCreate,idempotency_key):
        uuid(idempotency_key,"idempotencyKey");fp=fingerprint("cost",{"issueId":issue_id,"command":command.__dict__})
        def op(tx):
            prior=tx.cost_context_by_key(idempotency_key)
            if prior:
                if prior["request_fingerprint"]!=fp:raise MaintenanceConflictError("Idempotency key payload changed.","idempotency_conflict")
                return _dict(dict(prior))
            self._require(tx.issue,issue_id,"Issue")
            if command.replaces_cost_context_id:
                replaced=self._require(tx.cost_context,command.replaces_cost_context_id,"Cost context")
                if replaced["issue_id"]!=issue_id or replaced["context_kind"]!=command.context_kind or not replaced["voided_at"]:raise MaintenanceConflictError("Replacement must target a voided same-kind context.")
            now=_stamp(); item={"id":str(uuid4()),"issue_id":issue_id,"context_kind":command.context_kind,"label":command.label,"amount_minor":command.amount,"currency_code":"USD","observed_on":command.observed_on,"source_note":command.source_note,"replaces_cost_context_id":command.replaces_cost_context_id,"voided_at":None,"void_reason":None,"idempotency_key":idempotency_key,"request_fingerprint":fp,"created_at":now};tx.insert_cost_context(item);self._audit(tx,"maintenance_cost_context",item["id"],"created",None,_dict(item),"cost_context_created");return _dict(item)
        return self.unit_of_work.write(op)
    def link_expense(self,issue_id,expense_id,idempotency_key):
        uuid(expense_id,"expenseId");uuid(idempotency_key,"idempotencyKey");fp=fingerprint("expense_link",{"issue":issue_id,"expense":expense_id})
        def op(tx):
            prior=tx.expense_link_by_key(idempotency_key)
            if prior:
                if prior["request_fingerprint"]!=fp:raise MaintenanceConflictError("Idempotency key payload changed.","idempotency_conflict")
                return _dict(dict(prior))
            issue=self._require(tx.issue,issue_id,"Issue");expense=tx.expense(expense_id)
            if not expense:raise MaintenanceNotFoundError("Expense was not found.")
            if expense["voided_at"] or expense["property_id"]!=issue["property_id"] or (issue["space_id"] and expense["space_id"] not in {None,issue["space_id"]}):raise MaintenanceConflictError("Expense is not compatible with this issue.")
            if tx.active_expense_link(expense_id):raise MaintenanceConflictError("Expense already has an active maintenance link.","duplicate_expense_link")
            item={"id":str(uuid4()),"issue_id":issue_id,"expense_id":expense_id,"idempotency_key":idempotency_key,"request_fingerprint":fp,"created_at":_stamp(),"archived_at":None,"archive_reason":None};tx.insert_expense_link(item);self._audit(tx,"maintenance_expense_link",item["id"],"created",None,_dict(item),"expense_linked");return _dict(item)
        return self.unit_of_work.write(op)
    def update_appointment(self, appointment_id, command: AppointmentCreate, reschedule_reason: str | None = None):
        def op(tx):
            old=self._require(tx.appointment,appointment_id,"Appointment")
            if old["status"]!="scheduled": raise MaintenanceConflictError("Only scheduled appointments can be changed.","appointment_closed")
            changed_times=(old["starts_at_utc"],old["ends_at_utc"]) != (command.starts_at_utc,command.ends_at_utc)
            if changed_times and maintenance_text(reschedule_reason,"rescheduleReason",1000) is None: raise MaintenanceError("Rescheduling requires a reason.")
            updated={**old,"starts_at_utc":command.starts_at_utc,"ends_at_utc":command.ends_at_utc,"purpose":command.purpose,"instructions":command.instructions,"updated_at":_stamp()}
            if all(updated[k]==old[k] for k in ("starts_at_utc","ends_at_utc","purpose","instructions")):return _dict(old)
            tx.replace_appointment(appointment_id,updated)
            self._audit(tx,"maintenance_appointment",appointment_id,"updated",_dict(old),_dict(updated),"appointment_rescheduled" if changed_times else "appointment_updated", narrative=reschedule_reason)
            return _dict(updated)
        return self.unit_of_work.write(op)
    def finish_appointment(self, appointment_id, *, cancelled: bool, reason: str | None, confirmed: bool):
        if type(confirmed) is not bool or not confirmed:raise MaintenanceError("Explicit confirmation is required.")
        if cancelled: reason=maintenance_text(reason,"cancellationReason",1000,required=True)
        def op(tx):
            old=self._require(tx.appointment,appointment_id,"Appointment")
            if old["status"]!="scheduled":raise MaintenanceConflictError("Appointment is no longer scheduled.","appointment_closed")
            updated={**old,"status":"cancelled" if cancelled else "completed","cancelled_at":_stamp() if cancelled else None,"cancellation_reason":reason if cancelled else None,"completed_at":None if cancelled else _stamp(),"outcome_note":None if cancelled else maintenance_text(reason,"outcomeNote",4000),"updated_at":_stamp()}
            tx.replace_appointment(appointment_id,updated)
            self._audit(tx,"maintenance_appointment",appointment_id,"cancelled" if cancelled else "completed",_dict(old),_dict(updated),"appointment_cancelled" if cancelled else "appointment_completed", narrative=reason)
            return _dict(updated)
        return self.unit_of_work.write(op)
    def void_cost(self, context_id, reason, confirmed):
        if type(confirmed) is not bool or not confirmed:raise MaintenanceError("Explicit confirmation is required.")
        reason=maintenance_text(reason,"voidReason",1000,required=True)
        def op(tx):
            old=self._require(tx.cost_context,context_id,"Cost context")
            if old["voided_at"]:raise MaintenanceConflictError("Cost context is already voided.","cost_context_voided")
            updated={**old,"voided_at":_stamp(),"void_reason":reason};tx.replace_cost_context(context_id,updated);self._audit(tx,"maintenance_cost_context",context_id,"voided",_dict(old),_dict(updated),"cost_context_voided", narrative=reason);return _dict(updated)
        return self.unit_of_work.write(op)
    def archive_expense_link(self, link_id, reason, confirmed):
        if type(confirmed) is not bool or not confirmed:raise MaintenanceError("Explicit confirmation is required.")
        reason=maintenance_text(reason,"archiveReason",1000,required=True)
        def op(tx):
            old=self._require(tx.expense_link,link_id,"Expense link")
            if old["archived_at"]:raise MaintenanceConflictError("Expense link is already archived.","expense_link_archived")
            updated={**old,"archived_at":_stamp(),"archive_reason":reason};tx.replace_expense_link(link_id,updated);self._audit(tx,"maintenance_expense_link",link_id,"archived",_dict(old),_dict(updated),"expense_link_archived", narrative=reason);return _dict(updated)
        return self.unit_of_work.write(op)
    def create_follow_up(self, issue_id, title, notes, priority, due_at_utc, due_timezone, idempotency_key):
        uuid(idempotency_key,"idempotencyKey")
        payload={"issueId":issue_id,"title":title,"notes":notes,"priority":priority,"dueAtUtc":due_at_utc,"dueTimezone":due_timezone};fp=fingerprint("follow_up",payload)
        def op(tx):
            previous=tx.follow_up_by_key(idempotency_key)
            if previous:
                if previous["request_fingerprint"]!=fp:raise MaintenanceConflictError("Idempotency key payload changed.","idempotency_conflict")
                return _task_summary(tx.task(previous["task_id"]))
            issue=self._require(tx.issue,issue_id,"Issue")
            if issue["status"] not in {"open","in_progress"}:raise MaintenanceConflictError("Follow-ups require an active issue.","issue_closed")
            now=_stamp(); correlation=str(uuid4())
            try:
                from app.modules.tasks.application.service import TaskCreateCommand, TaskError
                command=TaskCreateCommand(title,notes,"open",priority,due_at_utc,due_timezone,False,"maintenance_issue",issue_id,issue["summary"])
                task=tx.create_task(command,correlation_id=correlation)
            except TaskError as error:
                raise MaintenanceError(str(error)) from error
            tx.insert_follow_up_operation({"idempotency_key":idempotency_key,"request_fingerprint":fp,"issue_id":issue_id,"task_id":task.id,"correlation_id":correlation,"created_at":now})
            tx.record_change(entity_type="maintenance_issue",entity_id=issue_id,action="follow_up_created",before=None,after={"taskId":task.id},reason="maintenance_follow_up",correlation_id=correlation)
            return _task_summary({
                "id":task.id,"title":task.title,"status":task.status,"priority":task.priority,
                "due_at_utc":task.due_at_utc,"due_timezone":task.due_timezone,"is_all_day":task.is_all_day,
                "related_entity_type":task.related_entity_type,"related_entity_id":task.related_entity_id,
            })
        return self.unit_of_work.write(op)
    def list_issues(self, *, property_id=None, space_id=None, category=None, priority=None, status=None, reporter_role=None, reporter_party_id=None, reporter_subject_kind=None, reported_from=None, reported_to=None, appointment_from=None, appointment_to=None, has_evidence=None, has_linked_expense=None, has_active_task=None, cursor=None, page_size=100):
        if not isinstance(page_size,int) or not 1<=page_size<=500:raise MaintenanceError("pageSize must be between 1 and 500.")
        for item,name in ((property_id,"propertyId"),(space_id,"spaceId")):
            if item is not None:uuid(item,name)
        if category is not None and category not in CATEGORIES:raise MaintenanceError("Category is invalid.")
        if priority is not None and priority not in PRIORITIES:raise MaintenanceError("Priority is invalid.")
        if status is not None and status not in {"open","in_progress","resolved","cancelled"}:raise MaintenanceError("Status is invalid.")
        if reporter_role is not None and reporter_role not in REPORTER_ROLES:raise MaintenanceError("Reporter role is invalid.")
        if reporter_subject_kind is not None and reporter_subject_kind not in REPORTER_SUBJECT_KINDS:raise MaintenanceError("Reporter subject kind is invalid.")
        if reporter_party_id is not None:uuid(reporter_party_id,"reporterPartyId")
        def op(tx):
            for value,name in ((has_evidence,"hasEvidence"),(has_linked_expense,"hasLinkedExpense"),(has_active_task,"hasActiveTask")):
                if value is not None and type(value) is not bool:raise MaintenanceError(f"{name} must be a boolean.")
            records, resume_cursor = tx.issues_page(property_id=property_id,space_id=space_id,category=category,priority=priority,status=status,reporter_role=reporter_role,reporter_party_id=reporter_party_id,reporter_subject_kind=reporter_subject_kind,reported_from=reported_from,reported_to=reported_to,appointment_from=appointment_from,appointment_to=appointment_to,has_evidence=has_evidence,has_linked_expense=has_linked_expense,has_active_task=has_active_task,cursor=cursor,limit=page_size+1)
            page=records[:page_size]; next_cursor=None
            if len(records)>page_size:
                tail=page[-1]; next_cursor=f"{tail['priority']}|{tail['reported_at_utc']}|{tail['id']}"
            elif resume_cursor is not None:
                next_cursor="|".join(resume_cursor)
            projection=tx.projection([row["id"] for row in page], include_detail=False)
            return {"items":[self._summary(projection[row["id"]]) for row in page],"nextCursor":next_cursor}
        return self.unit_of_work.read(op)
    def detail(self,issue_id):return self.unit_of_work.read(lambda tx:self._detail(tx,issue_id))
    def _require(self,getter,item_id,name):
        row=getter(item_id)
        if row is None:raise MaintenanceNotFoundError(f"{name} was not found.")
        return row
    def _validated_reporter(self, tx, reporter, property_id, space_id, reported_at_utc, time_zone):
        reported_on=datetime.fromisoformat(reported_at_utc).astimezone(ZoneInfo(time_zone)).date().isoformat()
        if reporter.subject_kind == "local_operator":
            if reporter.role == "owner" and not tx.reporter_is_owner(property_id,None,reported_on):
                raise MaintenanceConflictError("The local operator does not own this property on the reported date.","reporter_relationship")
            return {"reporter_role":reporter.role,"reporter_subject_kind":"local_operator","reporter_party_id":None,"reporter_display_name_snapshot":"Local operator"}
        party=tx.reporter_party(reporter.party_id)
        if party is None: raise MaintenanceNotFoundError("Reporter party was not found.")
        if party.archived_at is not None:
            if not reporter.historical_selection_confirmed or not reporter.historical_selection_reason:
                raise MaintenanceConflictError("Archived reporter selection requires historical confirmation.","archived_reporter")
            if reported_on >= datetime.now(ZoneInfo(time_zone)).date().isoformat():
                raise MaintenanceConflictError("Archived reporter selection is only available for a backdated issue.","archived_reporter")
        elif reporter.historical_selection_confirmed is not None:
            raise MaintenanceConflictError("Historical reporter selection applies only to archived parties.","historical_reporter")
        if reporter.role == "owner" and not tx.reporter_is_owner(property_id,reporter.party_id,reported_on):
            raise MaintenanceConflictError("Reporter was not an owner on the reported date.","reporter_relationship")
        if reporter.role == "tenant" and not tx.reporter_is_tenant(property_id,space_id,reporter.party_id,reported_on):
            raise MaintenanceConflictError("Reporter was not a tenant for this issue context on the reported date.","reporter_relationship")
        return {"reporter_role":reporter.role,"reporter_subject_kind":"party","reporter_party_id":reporter.party_id,"reporter_display_name_snapshot":party.display_name}
    def _detail(self,tx,issue_id):
        projection=tx.projection([issue_id])
        if issue_id not in projection:raise MaintenanceNotFoundError("Issue was not found.")
        return self._detail_projection(projection[issue_id])
    def _file(self,item):
        return {"id":item.id,"entityType":item.entity_type,"entityId":item.entity_id,"purpose":item.purpose,"fileId":item.file_id,"createdAt":item.created_at,"archivedAt":item.archived_at,"archiveReason":item.archive_reason,"originalName":item.original_name,"mediaType":item.media_type,"sizeBytes":item.size_bytes,"contentSha256":item.content_sha256}
    def _detail_projection(self,projection):
        issue=projection["issue"]; result=_dict(issue)
        for key in ("reporterRole","reporterSubjectKind","reporterPartyId","reporterDisplayNameSnapshot"):
            result.pop(key,None)
        context=projection["context"] or {}
        result["property"]={"id":issue["property_id"],"displayName":context.get("property_display_name"),"status":context.get("property_status"),"timeZone":context.get("time_zone")}
        result["space"]=None if issue["space_id"] is None else {"id":issue["space_id"],"displayName":context.get("space_display_name"),"status":context.get("space_status")}
        result["files"]=[self._file(item) for item in projection["files"]]
        result["appointments"]=[{**_dict(item),"files":[self._file(link) for link in projection["appointment_files"].get(item["id"],[])]} for item in projection["appointments"]]
        result["costContexts"]=[{**_dict(item),"files":[self._file(link) for link in projection["cost_files"].get(item["id"],[])]} for item in projection["costs"]]
        result["expenseLinks"]= [{**_dict(item),"expense":_camel_mapping(projection["expenses"].get(item["expense_id"]))} for item in projection["links"]]
        result["tasks"]=[_camel_mapping(item) for item in projection["tasks"]]
        result["reporter"]=self._reporter_view(issue,projection["party_states"])
        result["communications"]= [self._communication_view(item) for item in projection["communications"]]
        return result
    def _summary(self,projection):
        issue=projection["issue"]; context=projection["context"] or {}
        scheduled=next((item for item in reversed(projection["appointments"]) if item["status"]=="scheduled"),None)
        evidence_count=len(projection["files"])+sum(len(projection["appointment_files"].get(item["id"],[])) for item in projection["appointments"])+sum(len(projection["cost_files"].get(item["id"],[])) for item in projection["costs"])
        return {"id":issue["id"],"propertyId":issue["property_id"],"spaceId":issue["space_id"],"summary":issue["summary"],"category":issue["category"],"priority":issue["priority"],"status":issue["status"],"reportedAtUtc":issue["reported_at_utc"],"reportedTimezone":issue["reported_timezone"],"reporter":self._reporter_view(issue),"property":{"id":issue["property_id"],"displayName":context.get("property_display_name")},"space":None if issue["space_id"] is None else {"id":issue["space_id"],"displayName":context.get("space_display_name")},"currentAppointment":None if scheduled is None else {"id":scheduled["id"],"startsAtUtc":scheduled["starts_at_utc"],"endsAtUtc":scheduled["ends_at_utc"],"status":scheduled["status"]},"activeFollowUpCount":sum(1 for task in projection["tasks"] if task["status"] in {"open","in_progress"}),"evidenceCount":evidence_count,"linkedExpenseCount":sum(1 for link in projection["links"] if link["archived_at"] is None)}
    def _reporter_view(self,issue,party_states=None):
        result={"role":issue["reporter_role"],"subjectKind":issue["reporter_subject_kind"],"partyId":issue["reporter_party_id"],"displayName":issue["reporter_display_name_snapshot"]}
        if issue["reporter_party_id"] is not None and party_states is not None:result["currentPartyState"]=party_states.get(issue["reporter_party_id"])
        return result
    def _communication_view(self,item):
        return {"id":item["id"],"subject":item["subject"],"channel":item["channel"],"direction":item["direction"],"status":item["status"],"occurredAtUtc":item["occurred_at_utc"],"occurredTimezone":item["occurred_timezone"]}
    def _audit(self,tx,entity_type,entity_id,action,before,after,reason,*,narrative=None):
        # General activity exposes only stable action labels.  Free-form
        # operator narratives remain in a snapshot field redacted by the
        # maintenance activity policy, while contextual history retains them.
        if narrative:
            after={**after,"operatorNarrative":narrative}
        tx.record_change(entity_type=entity_type,entity_id=entity_id,action=action,before=before,after=after,reason=reason,correlation_id=str(uuid4()))

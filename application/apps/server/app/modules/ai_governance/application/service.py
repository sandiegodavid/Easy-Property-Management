"""Synchronous coordinator for bounded, reviewable AI generations."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from typing import Any, Callable, Mapping
from uuid import uuid4
from app.modules.ai_governance.application.ports import AiApprovalContext, AiApprovalHandler, AiGovernanceUnitOfWork, AiProviderError, AiProviderPort, AiTransportCredentialStore
from app.modules.ai_governance.domain.models import AiActionDefinition, AiActionRegistry, AiConflictError, AiNotFoundError, AiValidationError, RedactionProfileRegistry, canonical_json, fingerprint, validate_uuid

_UNSET = object()


@dataclass(frozen=True)
class AiAdapterDefinition:
    adapter_id: str; adapter_version: str; execution_location: str; models: frozenset[str]
    requires_credential: bool = True; timeout_seconds: int = 30


class AiAdapterRegistry:
    def __init__(self, definitions: tuple[AiAdapterDefinition,...]=()) -> None:
        self._items={(item.adapter_id,item.adapter_version):item for item in definitions}
        if len(self._items)!=len(definitions): raise ValueError("Duplicate AI adapter definition.")
    def require(self, adapter_id:str, adapter_version:str) -> AiAdapterDefinition:
        try:return self._items[(adapter_id,adapter_version)]
        except KeyError as error: raise AiValidationError("AI model adapter is not registered.") from error
    def all(self)->tuple[AiAdapterDefinition,...]:return tuple(self._items[key] for key in sorted(self._items))


class _AiGovernanceRuntime:
    def __init__(self, unit_of_work: AiGovernanceUnitOfWork, *, workspace_id: str,
                 actions: AiActionRegistry, profiles: RedactionProfileRegistry,
                 adapters: AiAdapterRegistry, providers: Mapping[str,AiProviderPort] | None=None,
                 credentials: AiTransportCredentialStore | None=None,
                 approval_handlers: Mapping[str,AiApprovalHandler] | None=None,
                 source_projections: Mapping[str,Any] | None=None,
                 now: Callable[[],datetime] | None=None) -> None:
        self.unit_of_work=unit_of_work; self.workspace_id=workspace_id; self.actions=actions; self.profiles=profiles; self.adapters=adapters
        self.providers=dict(providers or {}); self.credentials=credentials; self.approval_handlers=dict(approval_handlers or {}); self.source_projections=dict(source_projections or {}); self._clock=now or (lambda:datetime.now(UTC))

    def settings(self)->dict[str,Any]:
        value=self._settings_row(self.unit_of_work.settings_row())
        return {**value,"registeredAdapters":[{"adapterId":item.adapter_id,"adapterVersion":item.adapter_version,"executionLocation":item.execution_location,"models":sorted(item.models),"credentialRequired":item.requires_credential} for item in self.adapters.all()],"actions":[{"actionType":item.action_type,"owningModule":item.owning_module,"maxRunsPerUtcDay":item.max_runs_per_utc_day,"maxPromptTokens":item.max_prompt_tokens,"maxCompletionTokens":item.max_completion_tokens} for item in self.actions.all()]}
    def update_settings(self, *, kill_switch:bool|None=None,built_in_enabled:bool|None=None,default_connection_id:object=_UNSET,idempotency_key:str|None=None)->dict[str,Any]:
        if kill_switch is not None and type(kill_switch) is not bool: raise AiValidationError("killSwitch must be a boolean.")
        if built_in_enabled is not None and type(built_in_enabled) is not bool: raise AiValidationError("builtInEnabled must be a boolean.")
        stamp=self._now(); correlation=str(uuid4())
        requested={"kill_switch":kill_switch,"built_in_enabled":built_in_enabled,
                   "default_connection_provided":default_connection_id is not _UNSET,
                   "default_connection_id":None if default_connection_id is _UNSET else default_connection_id}
        request_fingerprint=_settings_fingerprint(requested)
        if idempotency_key is not None: validate_uuid(idempotency_key,"idempotencyKey")
        def operation(tx):
            before=tx.settings(); values={"updated_at":stamp}
            prior=None if idempotency_key is None else tx.settings_operation(idempotency_key)
            if prior is not None:
                if prior["request_fingerprint"] != request_fingerprint:
                    raise AiConflictError("ai_idempotency_conflict")
                return json.loads(prior["result_json"])
            if kill_switch is not None:values["kill_switch"]=kill_switch
            if built_in_enabled is not None:values["built_in_enabled"]=built_in_enabled
            if default_connection_id is not _UNSET:
                if default_connection_id is not None and not isinstance(default_connection_id, str): raise AiValidationError("defaultConnectionId must be a UUID.")
                if default_connection_id is not None and tx.model_connection(default_connection_id) is None:raise AiNotFoundError("AI model connection was not found.")
                values["default_connection_id"]=default_connection_id
            after={**before,**values}; result=self._settings_row(after)
            if idempotency_key is not None:
                tx.insert_settings_operation({"idempotency_key":idempotency_key,"request_fingerprint":request_fingerprint,"result_json":_settings_json(result),"created_at":stamp})
            tx.update_settings(values);self._audit(tx,"ai_settings","1","updated",before,after,correlation);return result
        return self.unit_of_work.write(operation)

    def connections(self)->list[dict[str,Any]]:
        rows=self.unit_of_work.connection_rows()
        return [self._connection_view(row) for row in rows]
    def create_connection(self, data:Mapping[str,Any])->dict[str,Any]:
        stamp=self._now(); connection_id=str(uuid4()); adapter=self.adapters.require(str(data.get("adapter_id")),str(data.get("adapter_version")))
        model=str(data.get("model_identifier","")); location=str(data.get("execution_location",""))
        if model not in adapter.models or location!=adapter.execution_location: raise AiValidationError("AI model connection is not an approved adapter configuration.")
        label=_text(data.get("label"),"Connection label",120); self._local_fields(data,location)
        row={"id":connection_id,"label":label,"revision":1,"adapter_id":adapter.adapter_id,"adapter_version":adapter.adapter_version,"model_identifier":model,"execution_location":location,"model_artifact_digest":data.get("model_artifact_digest"),"quantization":data.get("quantization"),"runtime_id":data.get("runtime_id"),"runtime_version":data.get("runtime_version"),"enabled":bool(data.get("enabled",True)),"cloud_data_classes":"[]","disclosure_version":None,"disclosure_accepted_at":None,"created_at":stamp,"updated_at":stamp}
        def operation(tx):tx.insert_connection(row);self._audit(tx,"ai_model_connection",connection_id,"created",None,row,str(uuid4()));return row
        return self._connection_view(self.unit_of_work.write(operation))
    def update_connection(self, connection_id:str, *, expected_revision:int, data:Mapping[str,Any])->dict[str,Any]:
        if type(expected_revision) is not int or expected_revision<1:raise AiValidationError("expectedRevision must be a positive integer.")
        def operation(tx):
            before=tx.model_connection(connection_id)
            if not before:raise AiNotFoundError("AI model connection was not found.")
            if before["revision"]!=expected_revision: raise AiConflictError("ai_connection_revision_conflict")
            allowed={"label","enabled","model_artifact_digest","quantization","runtime_id","runtime_version"}
            if set(data)-allowed:raise AiValidationError("Unsupported AI connection field.")
            values=dict(data);
            if "label" in values:values["label"]=_text(values["label"],"Connection label",120)
            if "enabled" in values and type(values["enabled"]) is not bool:raise AiValidationError("enabled must be a boolean.")
            if any(key in values for key in {"model_artifact_digest","quantization","runtime_id","runtime_version"}):self._local_fields({**before,**values},before["execution_location"])
            values.update(revision=before["revision"]+1,updated_at=self._now(),cloud_data_classes="[]",disclosure_version=None,disclosure_accepted_at=None)
            tx.replace_connection(connection_id,values);after={**before,**values};self._audit(tx,"ai_model_connection",connection_id,"updated",before,after,str(uuid4()));return after
        return self._connection_view(self.unit_of_work.write(operation))
    def set_disclosure(self,connection_id:str,*,expected_revision:int,disclosure_version:str,data_classes:list[str])->dict[str,Any]:
        if not disclosure_version.strip() or len(disclosure_version)>80 or not all(isinstance(value,str) and value for value in data_classes):raise AiValidationError("Invalid AI disclosure.")
        def operation(tx):
            before=tx.model_connection(connection_id)
            if not before:raise AiNotFoundError("AI model connection was not found.")
            if before["revision"]!=expected_revision:raise AiConflictError("ai_connection_revision_conflict")
            if before["execution_location"]!="cloud":raise AiValidationError("Only cloud connections require disclosure.")
            values={"cloud_data_classes":canonical_json(sorted(set(data_classes))),"disclosure_version":disclosure_version,"disclosure_accepted_at":self._now(),"revision":before["revision"]+1,"updated_at":self._now()};tx.replace_connection(connection_id,values);after={**before,**values};self._audit(tx,"ai_model_connection",connection_id,"disclosure_recorded",before,after,str(uuid4()));return after
        return self._connection_view(self.unit_of_work.write(operation))
    def set_credential(self,connection_id:str,credential:str)->None:
        if self.credentials is None:raise AiValidationError("AI credential storage is unavailable.")
        if self.unit_of_work.connection_row(connection_id) is None:raise AiNotFoundError("AI model connection was not found.")
        self.credentials.set_credential(self.workspace_id,connection_id,credential)
    def delete_credential(self,connection_id:str)->None:
        if self.credentials is None:raise AiValidationError("AI credential storage is unavailable.")
        self.credentials.delete_credential(self.workspace_id,connection_id)
    def test_connection(self, connection_id: str) -> dict[str, Any]:
        row=self.unit_of_work.connection_row(connection_id)
        if row is None: raise AiNotFoundError("AI model connection was not found.")
        try: adapter=self.adapters.require(row["adapter_id"],row["adapter_version"])
        except AiValidationError:return {"ready":False,"reason":"adapter_unregistered"}
        if not row["enabled"]: return {"ready":False,"reason":"connection_disabled"}
        try: credential_present=self.credentials is not None and self.credentials.get_credential(self.workspace_id,connection_id) is not None
        except Exception: credential_present=False
        if adapter.requires_credential and not credential_present: return {"ready":False,"reason":"credential_unavailable"}
        return {"ready":True,"reason":None}
    def limits(self)->list[dict[str,Any]]:
        overrides={row["action_type"]:row for row in self.unit_of_work.action_limit_rows()}
        return [self._limit_view(definition,overrides.get(definition.action_type)) for definition in self.actions.all()]
    def put_limit(self,action_type:str,data:Mapping[str,Any])->dict[str,Any]:
        definition=self.actions.require(action_type); allowed={"enabled","connection_id","max_runs_per_utc_day","max_prompt_tokens","max_completion_tokens","allowed_models"}
        if set(data)-allowed:raise AiValidationError("Unsupported AI action limit field.")
        def operation(tx):
            old=tx.action_limit(action_type);base=self._limit_values(definition,old);base.update(data)
            for name,ceiling in (("max_runs_per_utc_day",definition.max_runs_per_utc_day),("max_prompt_tokens",definition.max_prompt_tokens),("max_completion_tokens",definition.max_completion_tokens)):
                if type(base[name]) is not int or not 1<=base[name]<=ceiling:raise AiValidationError("AI action limit exceeds its registered ceiling.")
            if type(base["enabled"]) is not bool:raise AiValidationError("enabled must be a boolean.")
            models=base["allowed_models"];models=json.loads(models) if isinstance(models,str) else models
            if not isinstance(models,list) or not models or not set(models)<=definition.allowed_models:raise AiValidationError("AI allowed models must narrow the registered set.")
            if base.get("connection_id") and tx.model_connection(base["connection_id"]) is None:raise AiNotFoundError("AI model connection was not found.")
            row={**base,"action_type":action_type,"allowed_models":canonical_json(sorted(models)),"updated_at":self._now()};tx.put_action_limit(row);self._audit(tx,"ai_action_limit",action_type,"updated",old,row,str(uuid4()));return self._limit_view(definition,row)
        return self.unit_of_work.write(operation)

    def run(self, *, action_type:str, source_entity_type:str, source_entity_id:str, source_revision:str, source_fingerprint:str, candidate:Mapping[str,Any], idempotency_key:str, supersedes_draft_id: str | None = None)->dict[str,Any]:
        definition=self.actions.require(action_type);validate_uuid(idempotency_key,"idempotencyKey");definition.validate_candidate(candidate)
        if source_entity_type not in definition.source_entity_types:raise AiValidationError("Source entity type is not allowed for this AI action.")
        self._require_current_source(source_entity_type,source_entity_id,source_revision,source_fingerprint)
        profile=self.profiles.require(*definition.redaction_profile); governed=profile.redact(candidate)
        if definition.validate_provider_request is not None:
            try: definition.validate_provider_request(governed)
            except Exception as error: raise AiValidationError("AI provider request does not match its registered schema.") from error
        governed_json=canonical_json(governed,maximum_bytes=definition.max_provider_request_bytes)
        request_fingerprint=_operation_fingerprint({"action":action_type,"source":source_entity_type,"sourceId":source_entity_id,"sourceRevision":source_revision,"sourceFingerprint":source_fingerprint,"governedInput":governed,"profile":definition.redaction_profile,"supersedesDraftId":supersedes_draft_id})
        stamp=self._now();run_id=str(uuid4());correlation=str(uuid4())
        # Keyring and adapter work happen before *every* short write phase.
        # Reservation itself only rechecks SQLite-owned mutable policy.
        preflight=self._preflight(definition, governed)
        reservation=self.unit_of_work.write(lambda tx:self._reserve(tx,definition,governed_json,source_entity_type,source_entity_id,source_revision,source_fingerprint,idempotency_key,request_fingerprint,run_id,correlation,stamp,preflight,supersedes_draft_id))
        if reservation.get("replay"):return reservation["result"]
        if reservation["status"]=="blocked":return self._run_view(reservation)
        provider=self.providers.get(reservation["transport_provider"])
        if provider is None:return self._fail(run_id,"ai_provider_unavailable","Configured AI provider is unavailable.")
        dispatch_preflight=self._preflight(definition, governed)
        started=self.unit_of_work.write(lambda tx:self._start(tx,run_id,dispatch_preflight))
        if not started:
            row=self.unit_of_work.run_row(run_id)
            if row is None: raise AiNotFoundError("AI run was not found.")
            return self._run_view(row)
        try: result=provider.generate(governed,reservation["model_identifier"],reservation["max_completion_tokens"],reservation["timeout_seconds"])
        except AiProviderError as error:return self._fail(run_id,getattr(error,"code","ai_provider_failure"),str(error))
        except Exception:return self._fail(run_id,"ai_provider_failure","The AI provider did not complete the request.")
        admission_preflight=self._preflight(definition, governed)
        return self.unit_of_work.write(lambda tx:self._succeed(tx,run_id,definition,result.payload,result.prompt_tokens,result.completion_tokens,result.provider_request_id,admission_preflight,supersedes_draft_id))

    def list_drafts(self,**filters:Any)->dict[str,Any]:
        limit=filters.pop("page_size",100);cursor=filters.pop("cursor",None)
        rows=self.unit_of_work.page_draft_rows(
            status=filters.get("status"), owning_module=filters.get("owning_module"),
            entity_kind=filters.get("entity_kind"), action_type=filters.get("action_type"),
            source_type=filters.get("source_entity_type"), source_id=filters.get("source_entity_id"),
            limit=limit + 1, cursor=cursor,
        )
        items=[self._draft_view(row) for row in rows[:limit]]
        next_cursor=None if len(rows)<=limit else (rows[limit-1]["updated_at"],rows[limit-1]["id"])
        return {"items":items,"nextCursor":None if next_cursor is None else "|".join(next_cursor)}
    def draft_detail(self,draft_id:str)->dict[str,Any]:
        row=self.unit_of_work.draft_detail_row(draft_id)
        if not row:raise AiNotFoundError("AI draft was not found.")
        value=self._draft_view(row,detail=True)
        value["currentSource"]=self._source_state(row["source_entity_type"],row["source_entity_id"])
        value["reviewHistory"]=[self._decision_view(item) for item in self.unit_of_work.draft_decision_rows(draft_id)]
        return value
    def edit_draft(self,draft_id:str,*,version:int,payload:Mapping[str,Any],operator_note:str|None=None)->dict[str,Any]:return self._decide(draft_id,version,"edited",payload,operator_note)
    def dismiss_draft(self,draft_id:str,*,version:int,operator_note:str|None=None)->dict[str,Any]:return self._decide(draft_id,version,"dismissed",None,operator_note)
    def approve_draft(self,draft_id:str,*,version:int,operator_note:str|None=None)->dict[str,Any]:
        if type(version) is not int or version<1: raise AiValidationError("Draft version must be a positive integer.")
        # Non-advisory approval belongs to the owning domain.  It receives
        # immutable source facts and uses its injected AiReviewOperations in
        # the same transaction as the official domain consequence.
        context=self._approval_context(draft_id,version,operator_note)
        definition=self.actions.require(context.action_type); handler=self.approval_handlers.get(context.action_type)
        if handler is None: raise AiConflictError("ai_approval_unavailable")
        # Even advisory decisions are completed by the source owner so it can
        # reload freshness inside its transaction before terminalizing review.
        return dict(handler.approve(context))

    def _approval_context(self, draft_id: str, version: int, operator_note: str | None) -> AiApprovalContext:
        row=self.unit_of_work.approval_context_row(draft_id)
        if row is None: raise AiNotFoundError("AI draft was not found.")
        if row["status"] not in {"proposed","edited"}: raise AiConflictError("ai_draft_terminal")
        if row["version"] != version: raise AiConflictError("ai_draft_version_conflict")
        return AiApprovalContext(draft_id=row["id"],draft_version=row["version"],action_type=row["action_type"],draft_payload=json.loads(row["draft_payload"]),source_entity_type=row["source_entity_type"],source_entity_id=row["source_entity_id"],source_revision=row["source_revision"],source_fingerprint=row["source_fingerprint"],correlation_id=row["correlation_id"],operator_note=operator_note)

    def _source_state(self, source_type, source_id):
        projection=self.source_projections.get(source_type)
        return None if projection is None else projection.source_state(source_entity_type=source_type,source_entity_id=source_id)
    def _require_current_source(self, source_type, source_id, revision, source_fingerprint):
        state=self._source_state(source_type,source_id)
        if state is None or state.get("tombstoned") or (state.get("revision"),state.get("fingerprint")) != (revision,source_fingerprint):
            raise AiConflictError("ai_source_stale")

    def recover_interrupted(self)->int:
        def operation(tx):
            rows=tx.interrupted_runs();stamp=self._now()
            for row in rows:
                # Both stranded states are failures.  A null started_at
                # records that this failure never reached provider transport.
                status="failed"
                after={**row,"status":status,"error_code":"ai_run_interrupted","error_detail":"The application stopped before the AI run completed.","finished_at":stamp}
                tx.update_run(row["id"],{"status":status,"error_code":"ai_run_interrupted","error_detail":"The application stopped before the AI run completed.","finished_at":stamp})
                self._audit(tx,"ai_run",row["id"],"interrupted",row,after,row["correlation_id"],actor="system")
            return len(rows)
        return self.unit_of_work.write(operation)

    def _reserve(self,tx,definition,governed_json,source_type,source_id,source_revision,source_fingerprint,key,request_fingerprint,run_id,correlation,stamp,preflight,supersedes_draft_id=None):
        prior=tx.run_by_key(key)
        if prior:
            if prior["request_fingerprint"]!=request_fingerprint:raise AiConflictError("ai_idempotency_conflict")
            draft=tx.draft_for_run(prior["id"])
            if draft is not None:
                draft={**draft,"action_type":prior["action_type"],"owning_module":prior["owning_module"],"source_entity_type":prior["source_entity_type"],"source_entity_id":prior["source_entity_id"]}
            return {"replay":True,"result":self._run_view(prior,draft)}
        settings=tx.settings(); override=tx.action_limit(definition.action_type);limits=self._limit_values(definition,override)
        effective_connection=limits.get("connection_id") or settings["default_connection_id"]
        connection=None if effective_connection is None else tx.model_connection(effective_connection)
        error=self._policy_error(definition,settings,limits,connection)
        if error is None:
            try:self._require_current_source(source_type,source_id,source_revision,source_fingerprint)
            except AiConflictError:error=("ai_source_stale","The source changed before AI reservation.")
        # The preflight proves non-database readiness.  A changed connection
        # revision/model must not inherit a prior credential/disclosure check.
        if error is None and not self._same_configuration(connection,preflight.get("connection")):
            error=("ai_configuration_changed","AI connection changed before reservation.")
        if error is None and preflight.get("error") is not None:error=preflight["error"]
        if error is None:
            error=self._supersession_error(tx,definition.action_type,source_type,source_id,supersedes_draft_id)
        if error is None and tx.active_run_count(definition.action_type,_day(stamp),_day(datetime.fromisoformat(stamp)+timedelta(days=1)))>=limits["max_runs_per_utc_day"]:
            error=("ai_daily_limit_reached","AI daily run limit has been reached.")
        row={"id":run_id,"execution_kind":"provider_generation","action_type":definition.action_type,"owning_module":definition.owning_module,"source_entity_type":source_type,"source_entity_id":source_id,"source_revision":source_revision,"source_fingerprint":source_fingerprint,"requested_supersedes_draft_id":supersedes_draft_id,"connection_id":None if connection is None else connection["id"],"configuration_revision":None if connection is None else connection["revision"],"transport_provider":None if connection is None else connection["adapter_id"],"adapter_version":None if connection is None else connection["adapter_version"],"model_identifier":None if connection is None else connection["model_identifier"],"execution_location":None if connection is None else connection["execution_location"],"model_artifact_digest":None if connection is None else connection["model_artifact_digest"],"quantization":None if connection is None else connection["quantization"],"runtime_id":None if connection is None else connection["runtime_id"],"runtime_version":None if connection is None else connection["runtime_version"],"assistant_name":None,"assistant_connection_id":None,"delegation_id":None,"reported_model_identifier":None,"prompt_template_id":definition.prompt_template_id,"prompt_template_version":definition.prompt_template_version,"output_schema_version":definition.output_schema_version,"redaction_profile":definition.redaction_profile[0],"redaction_profile_version":definition.redaction_profile[1],"governed_input_json":governed_json,"input_fingerprint":fingerprint(json.loads(governed_json)),"request_fingerprint":request_fingerprint,"status":"blocked" if error else "reserved","prompt_tokens":None,"completion_tokens":None,"provider_request_id":None,"error_code":None if error is None else error[0],"error_detail":None if error is None else error[1],"idempotency_key":key,"correlation_id":correlation,"started_at":None,"finished_at":stamp if error else None,"created_at":stamp}
        tx.insert_run(row);self._audit(tx,"ai_run",run_id,"blocked" if error else "reserved",None,row,correlation);return {**row,"max_completion_tokens":limits["max_completion_tokens"],"timeout_seconds":preflight.get("timeout_seconds",30)}
    def _start(self,tx,run_id,preflight):
        row=tx.run(run_id)
        if row is None:raise AiNotFoundError("AI run was not found.")
        settings=tx.settings(); limits=self._limit_values(self.actions.require(row["action_type"]),tx.action_limit(row["action_type"])); connection=None if row["connection_id"] is None else tx.model_connection(row["connection_id"])
        error=self._policy_error(self.actions.require(row["action_type"]),settings,limits,connection)
        if error is None and (limits.get("connection_id") or settings["default_connection_id"]) != row["connection_id"]:error=("ai_configuration_changed","AI connection selection changed before dispatch.")
        if error is None and (not self._same_configuration(connection,preflight.get("connection")) or not self._matches_run_configuration(row,connection)):error=("ai_configuration_changed","AI connection changed before dispatch.")
        if error is None:error=preflight.get("error")
        if error is None:
            error=self._supersession_error(tx,row["action_type"],row["source_entity_type"],row["source_entity_id"],row["requested_supersedes_draft_id"])
        if error is not None:
            after={**row,"status":"blocked","error_code":error[0],"error_detail":error[1],"finished_at":self._now()}
            tx.update_run(run_id,{"status":"blocked","error_code":error[0],"error_detail":error[1],"finished_at":after["finished_at"]})
            self._audit(tx,"ai_run",run_id,"blocked",row,after,row["correlation_id"])
            return False
        tx.update_run(run_id,{"status":"running","started_at":self._now()});self._audit(tx,"ai_run",run_id,"started",row,{**row,"status":"running"},row["correlation_id"])
        return True
    def _succeed(self,tx,run_id,definition,payload,prompt_tokens,completion_tokens,provider_request_id,preflight,supersedes_draft_id=None):
        row=tx.run(run_id)
        if row is None:raise AiNotFoundError("AI run was not found.")
        settings=tx.settings(); limits=self._limit_values(definition,tx.action_limit(definition.action_type)); connection=None if row["connection_id"] is None else tx.model_connection(row["connection_id"])
        if self._policy_error(definition,settings,limits,connection) is not None or (limits.get("connection_id") or settings["default_connection_id"]) != row["connection_id"] or not self._same_configuration(connection,preflight.get("connection")) or not self._matches_run_configuration(row,connection) or preflight.get("error") is not None:return self._blocked_late(tx,row)
        if not isinstance(payload,Mapping):return self._failed(tx,row,"ai_output_invalid","AI provider output is invalid.")
        try:definition.validate_payload(payload);payload_json=canonical_json(payload,maximum_bytes=definition.max_provider_request_bytes)
        except Exception:return self._failed(tx,row,"ai_output_invalid","AI provider output is invalid.")
        supersession_error=self._supersession_error(tx,row["action_type"],row["source_entity_type"],row["source_entity_id"],supersedes_draft_id)
        if supersession_error is not None:
            return self._failed(tx,row,supersession_error[0],supersession_error[1])
        predecessor=None if supersedes_draft_id is None else tx.draft(supersedes_draft_id)
        stamp=self._now()
        tx.update_run(run_id,{"status":"succeeded","prompt_tokens":prompt_tokens,"completion_tokens":completion_tokens,"provider_request_id":provider_request_id,"finished_at":stamp})
        draft={"id":str(uuid4()),"run_id":run_id,"entity_kind":definition.entity_kind,"draft_payload":payload_json,"confidence":None,"status":"proposed","supersedes_draft_id":supersedes_draft_id,"version":1,"terminal_at":None,"created_at":stamp,"updated_at":stamp}
        tx.insert_draft(draft)
        if predecessor is not None:
            replaced={**predecessor,"status":"superseded","terminal_at":stamp,"updated_at":stamp}
            tx.update_draft(predecessor["id"],{"status":"superseded","terminal_at":stamp,"updated_at":stamp})
            self._audit(tx,"ai_draft",predecessor["id"],"superseded",predecessor,replaced,row["correlation_id"],actor="ai_assistant")
        self._audit(tx,"ai_run",run_id,"succeeded",row,{**row,"status":"succeeded"},row["correlation_id"],actor="ai_assistant")
        self._audit(tx,"ai_draft",draft["id"],"created",None,draft,row["correlation_id"],actor="ai_assistant")
        return self._run_view({**row,"status":"succeeded"},{**draft,"action_type":row["action_type"],"owning_module":row["owning_module"],"source_entity_type":row["source_entity_type"],"source_entity_id":row["source_entity_id"]})
    @staticmethod
    def _supersession_error(tx, action_type, source_type, source_id, predecessor_id):
        if predecessor_id is None:return None
        predecessor=tx.draft(predecessor_id)
        if predecessor is None or predecessor["status"] not in {"proposed","edited"}:
            return ("ai_draft_not_supersedable","The draft can no longer be superseded.")
        predecessor_run=tx.run(predecessor["run_id"])
        if predecessor_run is None or (predecessor_run["action_type"],predecessor_run["source_entity_type"],predecessor_run["source_entity_id"]) != (action_type,source_type,source_id):
            return ("ai_draft_supersession_mismatch","The replacement must retain action and source identity.")
        return None
    def _fail(self,run_id,code,detail):return self.unit_of_work.write(lambda tx:self._failed(tx,tx.run(run_id),code,detail))
    def _failed(self,tx,row,code,detail):
        if row is None:raise AiNotFoundError("AI run was not found.")
        stamp=self._now();after={**row,"status":"failed","error_code":code,"error_detail":detail,"finished_at":stamp};tx.update_run(row["id"],{"status":"failed","error_code":code,"error_detail":detail,"finished_at":stamp});self._audit(tx,"ai_run",row["id"],"failed",row,after,row["correlation_id"]);return self._run_view(after)
    def _blocked_late(self,tx,row):
        stamp=self._now();after={**row,"status":"blocked","error_code":"ai_result_blocked","error_detail":"AI output was blocked by current workspace controls.","finished_at":stamp}
        tx.update_run(row["id"],{"status":"blocked","error_code":"ai_result_blocked","error_detail":"AI output was blocked by current workspace controls.","finished_at":stamp})
        self._audit(tx,"ai_run",row["id"],"blocked",row,after,row["correlation_id"])
        return self._run_view(after)
    def _preflight(self, definition, governed):
        """Do potentially slow/keyring work without any database transaction."""
        state={"settings":self.unit_of_work.settings_row(),"limit":self.unit_of_work.action_limit_row(definition.action_type)}
        settings=state["settings"]; limits=self._limit_values(definition,state["limit"])
        connection_id=limits.get("connection_id") or settings["default_connection_id"]
        connection=None if connection_id is None else self.unit_of_work.connection_row(connection_id)
        error=self._policy_error(definition,settings,limits,connection)
        timeout=30
        if error is None:
            try:
                adapter=self.adapters.require(connection["adapter_id"],connection["adapter_version"]); timeout=adapter.timeout_seconds
                if adapter.requires_credential and (self.credentials is None or not self.credentials.get_credential(self.workspace_id,connection["id"])):
                    error=("ai_credential_unavailable","AI credential is unavailable.")
                provider=self.providers.get(connection["adapter_id"])
                if error is None and provider is None:error=("ai_provider_unavailable","Configured AI provider is unavailable.")
                if error is None and provider.estimate_input_tokens(governed,connection["model_identifier"])>limits["max_prompt_tokens"]:error=("ai_prompt_limit_exceeded","AI prompt exceeds its configured limit.")
            except AiValidationError as exc:error=("ai_configuration_invalid",str(exc))
            except Exception:error=("ai_preflight_unavailable","AI provider preflight is unavailable.")
        return {"connection":connection,"error":error,"timeout_seconds":timeout}
    def _policy_error(self, definition, settings, limits, connection):
        if settings is None or settings["kill_switch"]:return ("ai_kill_switch_enabled","AI assistance is paused.")
        if not settings["built_in_enabled"]:return ("ai_built_in_disabled","Built-in AI assistance is disabled.")
        if not limits["enabled"]:return ("ai_action_disabled","AI action is disabled.")
        if connection is None or not connection["enabled"]:return ("ai_connection_unavailable","AI model connection is unavailable.")
        if connection["model_identifier"] not in json.loads(limits["allowed_models"]) or connection["execution_location"] not in definition.permitted_locations:return ("ai_model_not_allowed","AI model is not permitted for this action.")
        if connection["execution_location"]=="cloud" and (not connection["disclosure_version"] or not definition.required_data_classes<=set(json.loads(connection["cloud_data_classes"]))):return ("ai_disclosure_required","AI disclosure is required for this destination.")
        return None
    @staticmethod
    def _same_configuration(left,right):
        if left is None or right is None:return left is right
        return all(left.get(key)==right.get(key) for key in ("id","revision","adapter_id","adapter_version","model_identifier","execution_location","enabled","disclosure_version","cloud_data_classes"))
    @staticmethod
    def _matches_run_configuration(run, connection):
        if connection is None:return run["connection_id"] is None
        return (run["connection_id"],run["configuration_revision"],run["transport_provider"],run["adapter_version"],run["model_identifier"],run["execution_location"],run["model_artifact_digest"],run["quantization"],run["runtime_id"],run["runtime_version"]) == (connection["id"],connection["revision"],connection["adapter_id"],connection["adapter_version"],connection["model_identifier"],connection["execution_location"],connection["model_artifact_digest"],connection["quantization"],connection["runtime_id"],connection["runtime_version"])
    def _decide(self,draft_id,version,decision,payload,note):
        if type(version) is not int or version<1:raise AiValidationError("Draft version must be a positive integer.")
        if note is not None:_text(note,"Operator note",1000)
        def operation(tx):
            draft=tx.draft(draft_id)
            if not draft:raise AiNotFoundError("AI draft was not found.")
            if draft["status"] not in {"proposed","edited"}:raise AiConflictError("ai_draft_terminal")
            if draft["version"]!=version:raise AiConflictError("ai_draft_version_conflict")
            run=tx.run(draft["run_id"]);definition=self.actions.require(run["action_type"]);stamp=self._now();before=dict(draft)
            if decision=="edited":
                if not isinstance(payload,Mapping):raise AiValidationError("Draft payload must be an object.")
                definition.validate_payload(payload);after={**draft,"draft_payload":canonical_json(payload,maximum_bytes=definition.max_provider_request_bytes),"status":"edited","version":version+1,"updated_at":stamp};after_version=version+1
            else:after={**draft,"status":"dismissed","terminal_at":stamp,"updated_at":stamp};after_version=version
            tx.update_draft(draft_id,{key:value for key,value in after.items() if key not in {"id","run_id","entity_kind","created_at"}});record={"id":str(uuid4()),"draft_id":draft_id,"decision":decision,"draft_version_before":version,"draft_version_after":after_version,"operator_note":note,"result_entity_type":None,"result_entity_id":None,"correlation_id":run["correlation_id"],"decided_at":stamp};tx.insert_decision(record);self._audit(tx,"ai_draft",draft_id,decision,before,after,run["correlation_id"]);self._audit(tx,"ai_review_decision",record["id"],decision,None,record,run["correlation_id"]);return self._draft_view({**after,"action_type":run["action_type"],"owning_module":run["owning_module"],"source_entity_type":run["source_entity_type"],"source_entity_id":run["source_entity_id"]})
        return self.unit_of_work.write(operation)
    def _settings_row(self,row):return {"killSwitch":bool(row["kill_switch"]),"builtInEnabled":bool(row["built_in_enabled"]),"defaultConnectionId":row["default_connection_id"],"updatedAt":row["updated_at"]}
    def _connection_view(self,row):
        present=False
        if self.credentials is not None:
            try:present=self.credentials.get_credential(self.workspace_id,row["id"]) is not None
            except Exception:present=False
        return {"id":row["id"],"label":row["label"],"revision":row["revision"],"adapterId":row["adapter_id"],"adapterVersion":row["adapter_version"],"modelIdentifier":row["model_identifier"],"executionLocation":row["execution_location"],"enabled":bool(row["enabled"]),"cloudDataClasses":json.loads(row["cloud_data_classes"]),"disclosureVersion":row["disclosure_version"],"disclosureAcceptedAt":row["disclosure_accepted_at"],"credentialPresent":present,"createdAt":row["created_at"],"updatedAt":row["updated_at"]}
    def _limit_values(self,d,o):return {"enabled":d.max_runs_per_utc_day>0,"connection_id":None,"max_runs_per_utc_day":d.max_runs_per_utc_day,"max_prompt_tokens":d.max_prompt_tokens,"max_completion_tokens":d.max_completion_tokens,"allowed_models":canonical_json(sorted(d.allowed_models))} if o is None else dict(o)
    def _limit_view(self,d,o):
        x=self._limit_values(d,o);return {"actionType":d.action_type,"enabled":bool(x["enabled"]),"connectionId":x["connection_id"],"maxRunsPerUtcDay":x["max_runs_per_utc_day"],"maxPromptTokens":x["max_prompt_tokens"],"maxCompletionTokens":x["max_completion_tokens"],"allowedModels":json.loads(x["allowed_models"]),"updatedAt":None if o is None else o["updated_at"]}
    def _run_view(self,row,draft=None):return {"id":row["id"],"actionType":row["action_type"],"status":row["status"],"errorCode":row.get("error_code"),"errorDetail":row.get("error_detail"),"correlationId":row["correlation_id"],"draft":None if draft is None else self._draft_view(draft)}
    def _draft_view(self,row,detail=False):
        result={"id":row["id"],"runId":row["run_id"],"entityKind":row["entity_kind"],"status":row["status"],"version":row["version"],"sourceEntityType":row.get("source_entity_type"),"sourceEntityId":row.get("source_entity_id"),"actionType":row.get("action_type"),"owningModule":row.get("owning_module"),"updatedAt":row["updated_at"]}
        if detail:result.update(draftPayload=json.loads(row["draft_payload"]),confidence=None if row["confidence"] is None else json.loads(row["confidence"]),governedInput=json.loads(row["governed_input_json"]),sourceRevision=row["source_revision"],sourceFingerprint=row["source_fingerprint"])
        return result
    def _decision_view(self,row):return {"id":row["id"],"decision":row["decision"],"draftVersionBefore":row["draft_version_before"],"draftVersionAfter":row["draft_version_after"],"operatorNote":row["operator_note"],"resultEntityType":row["result_entity_type"],"resultEntityId":row["result_entity_id"],"correlationId":row["correlation_id"],"decidedAt":row["decided_at"]}
    def _audit(self,tx,entity_type,entity_id,action,before,after,correlation,actor="local_operator"):
        tx.record_audit(entity_type=entity_type,entity_id=entity_id,action=action,
                        before=_audit_safe(before),after=_audit_safe(after),
                        actor=actor,reason=f"ai_{action}",correlation_id=correlation)
    def _now(self):
        value=self._clock()
        if value.tzinfo is None or value.utcoffset() is None:raise ValueError("AI clock must be timezone-aware.")
        return value.astimezone(UTC).isoformat()
    @staticmethod
    def _local_fields(data,location):
        if location=="on_device" and not all(isinstance(data.get(key),str) and data[key].strip() for key in ("model_artifact_digest","quantization","runtime_id","runtime_version")):raise AiValidationError("On-device AI configurations require validated runtime provenance.")


class AiConfigurationService:
    """Workspace configuration and bounded action-limit administration."""
    def __init__(self, runtime: _AiGovernanceRuntime) -> None: self._runtime=runtime
    def settings(self): return self._runtime.settings()
    def update_settings(self, **values): return self._runtime.update_settings(**values)
    def connections(self): return self._runtime.connections()
    def create_connection(self, data): return self._runtime.create_connection(data)
    def update_connection(self, connection_id, **values): return self._runtime.update_connection(connection_id,**values)
    def set_disclosure(self, connection_id, **values): return self._runtime.set_disclosure(connection_id,**values)
    def set_credential(self, connection_id, credential): return self._runtime.set_credential(connection_id,credential)
    def delete_credential(self, connection_id): return self._runtime.delete_credential(connection_id)
    def test_connection(self, connection_id): return self._runtime.test_connection(connection_id)
    def limits(self): return self._runtime.limits()
    def put_limit(self, action_type, data): return self._runtime.put_limit(action_type,data)


class AiGenerationCoordinator:
    """Preflight, reservation, provider dispatch, admission, and recovery."""
    def __init__(self, runtime: _AiGovernanceRuntime) -> None: self._runtime=runtime
    def run(self, **command): return self._runtime.run(**command)
    def recover_interrupted(self): return self._runtime.recover_interrupted()


class AiDraftReviewService:
    """Read and decision boundary for generated drafts."""
    def __init__(self, runtime: _AiGovernanceRuntime) -> None: self._runtime=runtime
    def list_drafts(self, **filters): return self._runtime.list_drafts(**filters)
    def draft_detail(self, draft_id): return self._runtime.draft_detail(draft_id)
    def edit_draft(self, draft_id, **command): return self._runtime.edit_draft(draft_id,**command)
    def dismiss_draft(self, draft_id, **command): return self._runtime.dismiss_draft(draft_id,**command)
    def approve_draft(self, draft_id, **command): return self._runtime.approve_draft(draft_id,**command)


class AiGovernanceService:
    """Composition root retained for the HTTP/bootstrap surface.

    The three focused services intentionally own configuration, provider-run
    coordination, and review behavior respectively.  This facade contains no
    workflow policy and preserves the original public API during migration.
    """
    def __init__(self, unit_of_work: AiGovernanceUnitOfWork, **dependencies: Any) -> None:
        self._runtime=_AiGovernanceRuntime(unit_of_work,**dependencies)
        self.configuration=AiConfigurationService(self._runtime)
        self.generation=AiGenerationCoordinator(self._runtime)
        self.drafts=AiDraftReviewService(self._runtime)

    @property
    def actions(self): return self._runtime.actions
    @property
    def profiles(self): return self._runtime.profiles
    @property
    def adapters(self): return self._runtime.adapters
    @property
    def approval_handlers(self): return self._runtime.approval_handlers
    @property
    def unit_of_work(self): return self._runtime.unit_of_work
    def settings(self): return self.configuration.settings()
    def update_settings(self, **values): return self.configuration.update_settings(**values)
    def connections(self): return self.configuration.connections()
    def create_connection(self, data): return self.configuration.create_connection(data)
    def update_connection(self, connection_id, **values): return self.configuration.update_connection(connection_id,**values)
    def set_disclosure(self, connection_id, **values): return self.configuration.set_disclosure(connection_id,**values)
    def set_credential(self, connection_id, credential): return self.configuration.set_credential(connection_id,credential)
    def delete_credential(self, connection_id): return self.configuration.delete_credential(connection_id)
    def test_connection(self, connection_id): return self.configuration.test_connection(connection_id)
    def limits(self): return self.configuration.limits()
    def put_limit(self, action_type, data): return self.configuration.put_limit(action_type,data)
    def run(self, **command): return self.generation.run(**command)
    def recover_interrupted(self): return self.generation.recover_interrupted()
    def list_drafts(self, **filters): return self.drafts.list_drafts(**filters)
    def draft_detail(self, draft_id): return self.drafts.draft_detail(draft_id)
    def edit_draft(self, draft_id, **command): return self.drafts.edit_draft(draft_id,**command)
    def dismiss_draft(self, draft_id, **command): return self.drafts.dismiss_draft(draft_id,**command)
    def approve_draft(self, draft_id, **command): return self.drafts.approve_draft(draft_id,**command)

class _NoProvider:
    def estimate_input_tokens(self,*args):return 10**9

def _day(value):
    return (value.date().isoformat() if isinstance(value,datetime) else value[:10])+"T00:00:00+00:00"
def _text(value,name,limit):
    if not isinstance(value,str) or not (item:=value.strip()) or len(item)>limit:raise AiValidationError(f"{name} must contain bounded text.")
    return item
def _audit_safe(value):
    if value is None:return None
    hidden={"governed_input_json","draft_payload","error_detail","operator_note"};return {key:("[redacted]" if key in hidden else child) for key,child in value.items()}

def _settings_fingerprint(value):
    """Settings contain connection UUIDs, which are identifiers—not AI input."""
    return sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def _operation_fingerprint(value):
    return _settings_fingerprint(value)

def _settings_json(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)

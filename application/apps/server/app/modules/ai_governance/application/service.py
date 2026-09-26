"""Synchronous coordinator for bounded, reviewable AI generations."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import re
from typing import Any, Callable, Mapping
from uuid import uuid4
from app.modules.ai_governance.application.ports import AiApprovalContext, AiApprovalHandler, AiGovernanceUnitOfWork, AiProviderError, AiProviderPort, AiTransportCredentialStore
from app.modules.ai_governance.domain.audit_policy import ai_audit_snapshot
from app.modules.ai_governance.domain.models import AiActionDefinition, AiActionRegistry, AiConflictError, AiNotFoundError, AiValidationError, RedactionProfileRegistry, canonical_json, fingerprint, qualified_model_identity, validate_provider_metadata, validate_uuid

_UNSET = object()


@dataclass(frozen=True)
class AiAdapterDefinition:
    adapter_id: str; adapter_version: str; execution_location: str; models: frozenset[str]
    requires_credential: bool = True; timeout_seconds: int = 30
    capabilities: frozenset[str] = frozenset({"structured_output"})
    input_modalities: frozenset[str] = frozenset({"text"})


@dataclass(frozen=True)
class AiRunReservation:
    """Named, validated immutable input to the short durable reservation phase."""
    definition: AiActionDefinition
    governed_input_json: str
    source_entity_type: str
    source_entity_id: str
    source_revision: str
    source_fingerprint: str
    idempotency_key: str
    request_fingerprint: str
    run_id: str
    correlation_id: str
    created_at: str
    supersedes_draft_id: str | None = None

    def __post_init__(self) -> None:
        for value, label, limit in (
            (self.source_entity_type, "source entity type", 80),
            (self.source_entity_id, "source entity ID", 120),
            (self.source_revision, "source revision", 120),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise AiValidationError(f"AI {label} must contain bounded text.")
        for value, label in ((self.idempotency_key, "idempotencyKey"), (self.run_id, "runId"), (self.correlation_id, "correlationId")):
            validate_uuid(value, label)
        if self.supersedes_draft_id is not None:
            validate_uuid(self.supersedes_draft_id, "supersedesDraftId")
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in (self.source_fingerprint, self.request_fingerprint)):
            raise AiValidationError("AI reservation fingerprints must be lowercase SHA-256 values.")
        try:
            if canonical_json(json.loads(self.governed_input_json)) != self.governed_input_json:
                raise ValueError
        except Exception as error:
            raise AiValidationError("AI governed input must be canonical JSON.") from error

    def run_record(self, connection: Mapping[str, Any] | None, error: tuple[str, str] | None) -> dict[str, Any]:
        return {
            "id": self.run_id, "execution_kind": "provider_generation", "action_type": self.definition.action_type,
            "owning_module": self.definition.owning_module, "source_entity_type": self.source_entity_type,
            "source_entity_id": self.source_entity_id, "source_revision": self.source_revision,
            "source_fingerprint": self.source_fingerprint, "requested_supersedes_draft_id": self.supersedes_draft_id,
            "connection_id": None if connection is None else connection["id"],
            "configuration_revision": None if connection is None else connection["revision"],
            "transport_provider": None if connection is None else connection["adapter_id"],
            "adapter_version": None if connection is None else connection["adapter_version"],
            "model_identifier": None if connection is None else connection["model_identifier"],
            "execution_location": None if connection is None else connection["execution_location"],
            "model_artifact_digest": None if connection is None else connection["model_artifact_digest"],
            "quantization": None if connection is None else connection["quantization"],
            "runtime_id": None if connection is None else connection["runtime_id"],
            "runtime_version": None if connection is None else connection["runtime_version"],
            "assistant_name": None, "assistant_connection_id": None, "delegation_id": None,
            "reported_model_identifier": None, "prompt_template_id": self.definition.prompt_template_id,
            "prompt_template_version": self.definition.prompt_template_version,
            "output_schema_version": self.definition.output_schema_version,
            "redaction_profile": self.definition.redaction_profile[0],
            "redaction_profile_version": self.definition.redaction_profile[1],
            "governed_input_json": self.governed_input_json,
            "input_fingerprint": fingerprint(json.loads(self.governed_input_json)),
            "request_fingerprint": self.request_fingerprint, "status": "blocked" if error else "reserved",
            "prompt_tokens": None, "completion_tokens": None, "provider_request_id": None,
            "error_code": None if error is None else error[0], "error_detail": None if error is None else error[1],
            "idempotency_key": self.idempotency_key, "correlation_id": self.correlation_id,
            "started_at": None, "finished_at": self.created_at if error else None, "created_at": self.created_at,
        }


class AiAdapterRegistry:
    def __init__(self, definitions: tuple[AiAdapterDefinition,...]=()) -> None:
        self._items={(item.adapter_id,item.adapter_version):item for item in definitions}
        if len(self._items)!=len(definitions): raise ValueError("Duplicate AI adapter definition.")
    def require(self, adapter_id:str, adapter_version:str) -> AiAdapterDefinition:
        try:return self._items[(adapter_id,adapter_version)]
        except KeyError as error: raise AiValidationError("AI model adapter is not registered.") from error
    def all(self)->tuple[AiAdapterDefinition,...]:return tuple(self._items[key] for key in sorted(self._items))


class AiGenerationCoordinator:
    def __init__(self, unit_of_work: AiGovernanceUnitOfWork, *, workspace_id: str,
                 actions: AiActionRegistry, profiles: RedactionProfileRegistry,
                 adapters: AiAdapterRegistry, providers: Mapping[str,AiProviderPort] | None=None,
                 credentials: AiTransportCredentialStore | None=None,
                 now: Callable[[],datetime] | None=None) -> None:
        self.unit_of_work=unit_of_work; self.workspace_id=workspace_id; self.actions=actions; self.profiles=profiles; self.adapters=adapters
        self.providers=dict(providers or {}); self.credentials=credentials; self._clock=now or (lambda:datetime.now(UTC))

    def run(self, *, action_type:str, source_entity_type:str, source_entity_id:str, source_revision:str, source_fingerprint:str, candidate:Mapping[str,Any], idempotency_key:str, supersedes_draft_id: str | None = None)->dict[str,Any]:
        definition=self.actions.require(action_type);validate_uuid(idempotency_key,"idempotencyKey");definition.validate_candidate(candidate)
        if source_entity_type not in definition.source_entity_types:raise AiValidationError("Source entity type is not allowed for this AI action.")
        profile=self.profiles.require(*definition.redaction_profile); governed=profile.redact(candidate)
        if definition.validate_provider_request is not None:
            try: definition.validate_provider_request(governed)
            except Exception as error: raise AiValidationError("AI provider request does not match its registered schema.") from error
        governed_json=canonical_json(governed,maximum_bytes=definition.max_provider_request_bytes)
        request_fingerprint=_operation_fingerprint({"action":action_type,"source":source_entity_type,"sourceId":source_entity_id,"sourceRevision":source_revision,"sourceFingerprint":source_fingerprint,"governedInput":governed,"profile":definition.redaction_profile,"supersedesDraftId":supersedes_draft_id})
        stamp=_utc_now(self._clock);run_id=str(uuid4());correlation=str(uuid4())
        reservation_input=AiRunReservation(
            definition=definition, governed_input_json=governed_json,
            source_entity_type=source_entity_type, source_entity_id=source_entity_id,
            source_revision=source_revision, source_fingerprint=source_fingerprint,
            idempotency_key=idempotency_key, request_fingerprint=request_fingerprint,
            run_id=run_id, correlation_id=correlation, created_at=stamp,
            supersedes_draft_id=supersedes_draft_id,
        )
        # Keyring and adapter work happen before *every* short write phase.
        # Reservation itself only rechecks SQLite-owned mutable policy.
        preflight=self._preflight(definition, governed)
        reservation=self.unit_of_work.write(lambda tx:self._reserve(tx,reservation_input,preflight))
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
        except AiProviderError as error:
            return self._fail(run_id,_provider_error_code(error),_provider_error_detail(error))
        except Exception:return self._fail(run_id,"ai_provider_failure","The AI provider did not complete the request.")
        admission_preflight=self._preflight(definition, governed)
        return self.unit_of_work.write(lambda tx:self._succeed(tx,run_id,definition,result.payload,result.confidence,result.prompt_tokens,result.completion_tokens,result.provider_request_id,admission_preflight,supersedes_draft_id))

    def recover_interrupted(self)->int:
        def operation(tx):
            rows=tx.interrupted_runs();stamp=_utc_now(self._clock)
            for row in rows:
                # Both stranded states are failures.  A null started_at
                # records that this failure never reached provider transport.
                status="failed"
                after={**row,"status":status,"error_code":"ai_run_interrupted","error_detail":"The application stopped before the AI run completed.","finished_at":stamp}
                tx.update_run(row["id"],{"status":status,"error_code":"ai_run_interrupted","error_detail":"The application stopped before the AI run completed.","finished_at":stamp})
                _record_audit(tx,"ai_run",row["id"],"interrupted",row,after,row["correlation_id"],"system")
            return len(rows)
        return self.unit_of_work.write(operation)

    def _reserve(self, tx, reservation: AiRunReservation, preflight):
        prior=tx.run_by_key(reservation.idempotency_key)
        if prior:
            if prior["request_fingerprint"]!=reservation.request_fingerprint:raise AiConflictError("ai_idempotency_conflict")
            draft=tx.draft_for_run(prior["id"])
            if draft is not None:
                draft={**draft,"action_type":prior["action_type"],"owning_module":prior["owning_module"],"source_entity_type":prior["source_entity_type"],"source_entity_id":prior["source_entity_id"]}
            return {"replay":True,"result":self._run_view(prior,draft)}
        definition=reservation.definition
        settings=tx.settings(); override=tx.action_limit(definition.action_type);limits=_limit_values(definition,override)
        effective_connection=limits.get("connection_id") or settings["default_connection_id"]
        connection=None if effective_connection is None else tx.model_connection(effective_connection)
        error=self._policy_error(definition,settings,limits,connection)
        if error is None:
            try:
                # The source owner reads through this very transaction.  This
                # is deliberately after durable-key replay, so a completed
                # request remains replayable when the source later changes.
                tx.validate_current_source(
                    source_entity_type=reservation.source_entity_type, source_entity_id=reservation.source_entity_id,
                    source_revision=reservation.source_revision, source_fingerprint=reservation.source_fingerprint,
                )
            except Exception:
                error=("ai_source_stale","The source changed before AI reservation.")
        # The preflight proves non-database readiness.  A changed connection
        # revision/model must not inherit a prior credential/disclosure check.
        if error is None and not self._same_configuration(connection,preflight.get("connection")):
            error=("ai_configuration_changed","AI connection changed before reservation.")
        if error is None and preflight.get("error") is not None:error=preflight["error"]
        if error is None:
            error=self._supersession_error(tx,definition.action_type,reservation.source_entity_type,reservation.source_entity_id,reservation.supersedes_draft_id)
        if error is None and tx.active_run_count(definition.action_type,_day(reservation.created_at),_day(datetime.fromisoformat(reservation.created_at)+timedelta(days=1)))>=limits["max_runs_per_utc_day"]:
            error=("ai_daily_limit_reached","AI daily run limit has been reached.")
        row=reservation.run_record(connection,error)
        tx.insert_run(row);_record_audit(tx,"ai_run",reservation.run_id,"blocked" if error else "reserved",None,row,reservation.correlation_id,"local_operator");return {**row,"max_completion_tokens":limits["max_completion_tokens"],"timeout_seconds":preflight.get("timeout_seconds",30)}
    def _start(self,tx,run_id,preflight):
        row=tx.run(run_id)
        if row is None:raise AiNotFoundError("AI run was not found.")
        settings=tx.settings(); limits=_limit_values(self.actions.require(row["action_type"]),tx.action_limit(row["action_type"])); connection=None if row["connection_id"] is None else tx.model_connection(row["connection_id"])
        error=self._policy_error(self.actions.require(row["action_type"]),settings,limits,connection)
        if error is None and (limits.get("connection_id") or settings["default_connection_id"]) != row["connection_id"]:error=("ai_configuration_changed","AI connection selection changed before dispatch.")
        if error is None and (not self._same_configuration(connection,preflight.get("connection")) or not self._matches_run_configuration(row,connection)):error=("ai_configuration_changed","AI connection changed before dispatch.")
        if error is None:error=preflight.get("error")
        if error is None:
            error=self._supersession_error(tx,row["action_type"],row["source_entity_type"],row["source_entity_id"],row["requested_supersedes_draft_id"])
        if error is not None:
            after={**row,"status":"blocked","error_code":error[0],"error_detail":error[1],"finished_at":_utc_now(self._clock)}
            tx.update_run(run_id,{"status":"blocked","error_code":error[0],"error_detail":error[1],"finished_at":after["finished_at"]})
            _record_audit(tx,"ai_run",run_id,"blocked",row,after,row["correlation_id"],"local_operator")
            return False
        stamp=_utc_now(self._clock); after={**row,"status":"running","started_at":stamp}
        tx.update_run(run_id,{"status":"running","started_at":stamp});_record_audit(tx,"ai_run",run_id,"started",row,after,row["correlation_id"],"local_operator")
        return True
    def _succeed(self,tx,run_id,definition,payload,confidence,prompt_tokens,completion_tokens,provider_request_id,preflight,supersedes_draft_id=None):
        row=tx.run(run_id)
        if row is None:raise AiNotFoundError("AI run was not found.")
        settings=tx.settings(); limits=_limit_values(definition,tx.action_limit(definition.action_type)); connection=None if row["connection_id"] is None else tx.model_connection(row["connection_id"])
        if self._policy_error(definition,settings,limits,connection) is not None or (limits.get("connection_id") or settings["default_connection_id"]) != row["connection_id"] or not self._same_configuration(connection,preflight.get("connection")) or not self._matches_run_configuration(row,connection) or preflight.get("error") is not None:return self._blocked_late(tx,row)
        if not isinstance(payload,Mapping):return self._failed(tx,row,"ai_output_invalid","AI provider output is invalid.")
        try:
            definition.validate_payload(payload);payload_json=canonical_json(payload,maximum_bytes=definition.max_provider_request_bytes)
            definition.validate_confidence(confidence)
            confidence_json=None if confidence is None else canonical_json(confidence,maximum_bytes=1_024)
        except Exception:return self._failed(tx,row,"ai_output_invalid","AI provider output is invalid.")
        supersession_error=self._supersession_error(tx,row["action_type"],row["source_entity_type"],row["source_entity_id"],supersedes_draft_id)
        if supersession_error is not None:
            return self._failed(tx,row,supersession_error[0],supersession_error[1])
        try:
            prompt_tokens, completion_tokens, provider_request_id=validate_provider_metadata(prompt_tokens,completion_tokens,provider_request_id)
        except AiValidationError:
            return self._failed(tx,row,"ai_output_invalid","AI provider metadata is invalid.")
        predecessor=None if supersedes_draft_id is None else tx.draft(supersedes_draft_id)
        stamp=_utc_now(self._clock)
        succeeded={**row,"status":"succeeded","prompt_tokens":prompt_tokens,"completion_tokens":completion_tokens,"provider_request_id":provider_request_id,"finished_at":stamp}
        tx.update_run(run_id,{"status":"succeeded","prompt_tokens":prompt_tokens,"completion_tokens":completion_tokens,"provider_request_id":provider_request_id,"finished_at":stamp})
        draft={"id":str(uuid4()),"run_id":run_id,"entity_kind":definition.entity_kind,"draft_payload":payload_json,"confidence":confidence_json,"status":"proposed","supersedes_draft_id":supersedes_draft_id,"version":1,"terminal_at":None,"created_at":stamp,"updated_at":stamp}
        tx.insert_draft(draft)
        if predecessor is not None:
            replaced={**predecessor,"status":"superseded","terminal_at":stamp,"updated_at":stamp}
            tx.update_draft(predecessor["id"],{"status":"superseded","terminal_at":stamp,"updated_at":stamp})
            _record_audit(tx,"ai_draft",predecessor["id"],"superseded",predecessor,replaced,row["correlation_id"],"ai_assistant")
        _record_audit(tx,"ai_run",run_id,"succeeded",row,succeeded,row["correlation_id"],"ai_assistant")
        _record_audit(tx,"ai_draft",draft["id"],"created",None,draft,row["correlation_id"],"ai_assistant")
        return self._run_view(succeeded,{**draft,"action_type":row["action_type"],"owning_module":row["owning_module"],"source_entity_type":row["source_entity_type"],"source_entity_id":row["source_entity_id"]})
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
        stamp=_utc_now(self._clock);after={**row,"status":"failed","error_code":code,"error_detail":detail,"finished_at":stamp};tx.update_run(row["id"],{"status":"failed","error_code":code,"error_detail":detail,"finished_at":stamp});_record_audit(tx,"ai_run",row["id"],"failed",row,after,row["correlation_id"],"local_operator");return self._run_view(after)
    def _blocked_late(self,tx,row):
        stamp=_utc_now(self._clock);after={**row,"status":"blocked","error_code":"ai_result_blocked","error_detail":"AI output was blocked by current workspace controls.","finished_at":stamp}
        tx.update_run(row["id"],{"status":"blocked","error_code":"ai_result_blocked","error_detail":"AI output was blocked by current workspace controls.","finished_at":stamp})
        _record_audit(tx,"ai_run",row["id"],"blocked",row,after,row["correlation_id"],"local_operator")
        return self._run_view(after)
    def _preflight(self, definition, governed):
        """Do potentially slow/keyring work without any database transaction."""
        state={"settings":self.unit_of_work.settings_row(),"limit":self.unit_of_work.action_limit_row(definition.action_type)}
        settings=state["settings"]; limits=_limit_values(definition,state["limit"])
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
        model_identity=qualified_model_identity(connection["adapter_id"],connection["adapter_version"],connection["model_identifier"])
        if model_identity not in json.loads(limits["allowed_models"]) or connection["execution_location"] not in definition.permitted_locations:return ("ai_model_not_allowed","AI model is not permitted for this action.")
        try: adapter=self.adapters.require(connection["adapter_id"],connection["adapter_version"])
        except AiValidationError:return ("ai_adapter_unregistered","AI model adapter is not registered.")
        if not definition.required_capabilities <= adapter.capabilities or not definition.required_input_modalities <= adapter.input_modalities:
            return ("ai_capability_not_allowed","AI adapter does not support this action's required capabilities or input modalities.")
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
    def _run_view(self,row,draft=None):return {"id":row["id"],"actionType":row["action_type"],"status":row["status"],"errorCode":row.get("error_code"),"errorDetail":row.get("error_detail"),"correlationId":row["correlation_id"],"draft":None if draft is None else _draft_view(draft)}
class AiConfigurationService:
    """Workspace configuration and bounded action-limit administration."""
    def __init__(self, unit_of_work: AiGovernanceUnitOfWork, *, workspace_id: str,
                 actions: AiActionRegistry, adapters: AiAdapterRegistry,
                 providers: Mapping[str, AiProviderPort] | None = None,
                 credentials: AiTransportCredentialStore | None = None,
                 now: Callable[[], datetime] | None = None) -> None:
        self.unit_of_work=unit_of_work; self.workspace_id=workspace_id
        self.actions=actions; self.adapters=adapters; self.providers=dict(providers or {})
        self.credentials=credentials; self._clock=now or (lambda: datetime.now(UTC))
    def _settings_row(self,row):return {"killSwitch":bool(row["kill_switch"]),"builtInEnabled":bool(row["built_in_enabled"]),"defaultConnectionId":row["default_connection_id"],"updatedAt":row["updated_at"]}
    def _connection_view(self,row):
        present=False
        if self.credentials is not None:
            try:present=self.credentials.get_credential(self.workspace_id,row["id"]) is not None
            except Exception:present=False
        return {"id":row["id"],"label":row["label"],"revision":row["revision"],"adapterId":row["adapter_id"],"adapterVersion":row["adapter_version"],"modelIdentifier":row["model_identifier"],"executionLocation":row["execution_location"],"enabled":bool(row["enabled"]),"cloudDataClasses":json.loads(row["cloud_data_classes"]),"disclosureVersion":row["disclosure_version"],"disclosureAcceptedAt":row["disclosure_accepted_at"],"credentialPresent":present,"createdAt":row["created_at"],"updatedAt":row["updated_at"]}
    def _limit_view(self,d,o):
        x=_limit_values(d,o);return {"actionType":d.action_type,"enabled":bool(x["enabled"]),"connectionId":x["connection_id"],"maxRunsPerUtcDay":x["max_runs_per_utc_day"],"maxPromptTokens":x["max_prompt_tokens"],"maxCompletionTokens":x["max_completion_tokens"],"allowedModels":json.loads(x["allowed_models"]),"updatedAt":None if o is None else o["updated_at"]}
    def _audit(self,tx,entity_type,entity_id,action,before,after,correlation):
        _record_audit(tx,entity_type,entity_id,action,before,after,correlation,"local_operator")
    @staticmethod
    def _local_fields(data,location):
        if location=="on_device" and not all(isinstance(data.get(key),str) and data[key].strip() for key in ("model_artifact_digest","quantization","runtime_id","runtime_version")):raise AiValidationError("On-device AI configurations require validated runtime provenance.")
    def settings(self):
        value=self._settings_row(self.unit_of_work.settings_row())
        connection_id=value["defaultConnectionId"]
        readiness={"ready":False,"reason":"no_default_connection"} if connection_id is None else self.test_connection(connection_id)
        return {**value,"readiness":readiness,"registeredAdapters":[{"adapterId":x.adapter_id,"adapterVersion":x.adapter_version,"executionLocation":x.execution_location,"models":sorted(x.models),"credentialRequired":x.requires_credential,"capabilities":sorted(x.capabilities),"inputModalities":sorted(x.input_modalities)} for x in self.adapters.all()],"actions":[{"actionType":x.action_type,"owningModule":x.owning_module,"maxRunsPerUtcDay":x.max_runs_per_utc_day,"maxPromptTokens":x.max_prompt_tokens,"maxCompletionTokens":x.max_completion_tokens,"requiredCapabilities":sorted(x.required_capabilities),"requiredInputModalities":sorted(x.required_input_modalities)} for x in self.actions.all()]}
    def update_settings(self, *, kill_switch=None,built_in_enabled=None,default_connection_id=_UNSET,idempotency_key=None):
        if kill_switch is not None and type(kill_switch) is not bool:raise AiValidationError("killSwitch must be a boolean.")
        if built_in_enabled is not None and type(built_in_enabled) is not bool:raise AiValidationError("builtInEnabled must be a boolean.")
        if idempotency_key is not None:validate_uuid(idempotency_key,"idempotencyKey")
        stamp=_utc_now(self._clock); requested={"kill_switch":kill_switch,"built_in_enabled":built_in_enabled,"default_connection_provided":default_connection_id is not _UNSET,"default_connection_id":None if default_connection_id is _UNSET else default_connection_id}; request_fingerprint=_settings_fingerprint(requested)
        def operation(tx):
            before=tx.settings(); values={"updated_at":stamp}; prior=None if idempotency_key is None else tx.settings_operation(idempotency_key)
            if prior:
                if prior["request_fingerprint"] != request_fingerprint:raise AiConflictError("ai_idempotency_conflict")
                return json.loads(prior["result_json"])
            if kill_switch is not None:values["kill_switch"]=kill_switch
            if built_in_enabled is not None:values["built_in_enabled"]=built_in_enabled
            if default_connection_id is not _UNSET:
                if default_connection_id is not None and (not isinstance(default_connection_id,str) or tx.model_connection(default_connection_id) is None):raise AiNotFoundError("AI model connection was not found.")
                values["default_connection_id"]=default_connection_id
            after={**before,**values}; result=self._settings_row(after)
            if idempotency_key is not None:tx.insert_settings_operation({"idempotency_key":idempotency_key,"request_fingerprint":request_fingerprint,"result_json":_settings_json(result),"created_at":stamp})
            tx.update_settings(values);_record_audit(tx,"ai_settings","1","updated",before,after,str(uuid4()),"local_operator");return result
        return self.unit_of_work.write(operation)
    def connections(self):return [self._connection_view(row) for row in self.unit_of_work.connection_rows()]
    def create_connection(self,data):
        stamp=_utc_now(self._clock); ident=str(uuid4()); adapter=self.adapters.require(str(data.get("adapter_id")),str(data.get("adapter_version"))); model=str(data.get("model_identifier","")); location=str(data.get("execution_location",""))
        if model not in adapter.models or location != adapter.execution_location:raise AiValidationError("AI model connection is not an approved adapter configuration.")
        self._local_fields(data,location); row={"id":ident,"label":_text(data.get("label"),"Connection label",120),"revision":1,"adapter_id":adapter.adapter_id,"adapter_version":adapter.adapter_version,"model_identifier":model,"execution_location":location,"model_artifact_digest":data.get("model_artifact_digest"),"quantization":data.get("quantization"),"runtime_id":data.get("runtime_id"),"runtime_version":data.get("runtime_version"),"enabled":bool(data.get("enabled",True)),"cloud_data_classes":"[]","disclosure_version":None,"disclosure_accepted_at":None,"created_at":stamp,"updated_at":stamp}
        def operation(tx):tx.insert_connection(row);_record_audit(tx,"ai_model_connection",ident,"created",None,row,str(uuid4()),"local_operator");return row
        return self._connection_view(self.unit_of_work.write(operation))
    def update_connection(self,connection_id,*,expected_revision,data):
        if type(expected_revision) is not int or expected_revision<1:raise AiValidationError("expectedRevision must be a positive integer.")
        def operation(tx):
            before=tx.model_connection(connection_id)
            if not before:raise AiNotFoundError("AI model connection was not found.")
            if before["revision"] != expected_revision:raise AiConflictError("ai_connection_revision_conflict")
            allowed={"label","enabled","model_artifact_digest","quantization","runtime_id","runtime_version"}
            if set(data)-allowed:raise AiValidationError("Unsupported AI connection field.")
            values=dict(data)
            if "label" in values:values["label"]=_text(values["label"],"Connection label",120)
            if "enabled" in values and type(values["enabled"]) is not bool:raise AiValidationError("enabled must be a boolean.")
            if any(k in values for k in {"model_artifact_digest","quantization","runtime_id","runtime_version"}):self._local_fields({**before,**values},before["execution_location"])
            values.update(revision=before["revision"]+1,updated_at=_utc_now(self._clock),cloud_data_classes="[]",disclosure_version=None,disclosure_accepted_at=None); tx.replace_connection(connection_id,values);after={**before,**values};_record_audit(tx,"ai_model_connection",connection_id,"updated",before,after,str(uuid4()),"local_operator");return after
        return self._connection_view(self.unit_of_work.write(operation))
    def set_disclosure(self,connection_id,*,expected_revision,disclosure_version,data_classes):
        if not disclosure_version.strip() or len(disclosure_version)>80 or not all(isinstance(x,str) and x for x in data_classes):raise AiValidationError("Invalid AI disclosure.")
        def operation(tx):
            before=tx.model_connection(connection_id)
            if not before:raise AiNotFoundError("AI model connection was not found.")
            if before["revision"]!=expected_revision:raise AiConflictError("ai_connection_revision_conflict")
            if before["execution_location"]!="cloud":raise AiValidationError("Only cloud connections require disclosure.")
            stamp=_utc_now(self._clock);values={"cloud_data_classes":canonical_json(sorted(set(data_classes))),"disclosure_version":disclosure_version,"disclosure_accepted_at":stamp,"revision":before["revision"]+1,"updated_at":stamp};tx.replace_connection(connection_id,values);after={**before,**values};_record_audit(tx,"ai_model_connection",connection_id,"disclosure_recorded",before,after,str(uuid4()),"local_operator");return after
        return self._connection_view(self.unit_of_work.write(operation))
    def set_credential(self,connection_id,credential):
        if self.credentials is None:raise AiValidationError("AI credential storage is unavailable.")
        if self.unit_of_work.connection_row(connection_id) is None:raise AiNotFoundError("AI model connection was not found.")
        try: replaced=self.credentials.get_credential(self.workspace_id,connection_id) is not None
        except Exception: replaced=False
        self.credentials.set_credential(self.workspace_id,connection_id,credential)
        self._record_credential_audit(connection_id,"credential_replaced" if replaced else "credential_set",False,True)
    def delete_credential(self,connection_id):
        if self.credentials is None:raise AiValidationError("AI credential storage is unavailable.")
        if self.unit_of_work.connection_row(connection_id) is None:raise AiNotFoundError("AI model connection was not found.")
        try: present=self.credentials.get_credential(self.workspace_id,connection_id) is not None
        except Exception: present=False
        self.credentials.delete_credential(self.workspace_id,connection_id)
        self._record_credential_audit(connection_id,"credential_deleted",present,False)
    def _record_credential_audit(self, connection_id, action, before_present, after_present):
        def operation(tx):
            if tx.model_connection(connection_id) is None:
                raise AiNotFoundError("AI model connection was not found.")
            _record_audit(
                tx, "ai_model_connection", connection_id, action,
                {"id": connection_id, "credentialPresent": before_present},
                {"id": connection_id, "credentialPresent": after_present},
                str(uuid4()), "local_operator",
            )
        self.unit_of_work.write(operation)
    def test_connection(self,connection_id):
        row=self.unit_of_work.connection_row(connection_id)
        if row is None:raise AiNotFoundError("AI model connection was not found.")
        try:adapter=self.adapters.require(row["adapter_id"],row["adapter_version"])
        except AiValidationError:return {"ready":False,"reason":"adapter_unregistered"}
        if not row["enabled"]:return {"ready":False,"reason":"connection_disabled"}
        try:present=self.credentials is not None and self.credentials.get_credential(self.workspace_id,connection_id) is not None
        except Exception:present=False
        if adapter.requires_credential and not present:
            return {"ready":False,"reason":"credential_unavailable"}
        provider=self.providers.get(row["adapter_id"])
        if provider is None:
            return {"ready":False,"reason":"provider_unavailable"}
        try:
            # Probe is an explicit transport check; estimating a local JSON
            # shape is not evidence that the configured provider is reachable.
            probe=provider.probe(
                {"kind":"connection_probe","input":"health check"},
                row["model_identifier"],adapter.timeout_seconds,
            )
            if not isinstance(probe.payload, Mapping) or probe.payload.get("status") != "ok":
                raise ValueError("Probe did not return a structured response.")
            canonical_json(probe.payload, maximum_bytes=1_024)
            validate_provider_metadata(
                probe.prompt_tokens, probe.completion_tokens, probe.provider_request_id,
            )
        except Exception:
            return {"ready":False,"reason":"provider_check_failed"}
        return {"ready":True,"reason":None}
    def limits(self):
        overrides={row["action_type"]:row for row in self.unit_of_work.action_limit_rows()};return [self._limit_view(x,overrides.get(x.action_type)) for x in self.actions.all()]
    def put_limit(self,action_type,data):
        definition=self.actions.require(action_type);allowed={"enabled","connection_id","max_runs_per_utc_day","max_prompt_tokens","max_completion_tokens","allowed_models"}
        if set(data)-allowed:raise AiValidationError("Unsupported AI action limit field.")
        def operation(tx):
            old=tx.action_limit(action_type);base=_limit_values(definition,old);base.update(data)
            for name,ceiling in (("max_runs_per_utc_day",definition.max_runs_per_utc_day),("max_prompt_tokens",definition.max_prompt_tokens),("max_completion_tokens",definition.max_completion_tokens)):
                if type(base[name]) is not int or not 1<=base[name]<=ceiling:raise AiValidationError("AI action limit exceeds its registered ceiling.")
            if type(base["enabled"]) is not bool:raise AiValidationError("enabled must be a boolean.")
            models=json.loads(base["allowed_models"]) if isinstance(base["allowed_models"],str) else base["allowed_models"]
            if not isinstance(models,list) or not models or not set(models)<=definition.allowed_model_identities:raise AiValidationError("AI allowed models must narrow the registered set.")
            if base.get("connection_id") and tx.model_connection(base["connection_id"]) is None:raise AiNotFoundError("AI model connection was not found.")
            row={**base,"action_type":action_type,"allowed_models":canonical_json(sorted(models)),"updated_at":_utc_now(self._clock)};tx.put_action_limit(row);_record_audit(tx,"ai_action_limit",action_type,"updated",old,row,str(uuid4()),"local_operator");return self._limit_view(definition,row)
        return self.unit_of_work.write(operation)


class AiDraftReviewService:
    """Read and decision boundary for generated drafts."""
    def __init__(self, unit_of_work: AiGovernanceUnitOfWork, *, actions: AiActionRegistry,
                 approval_handlers: Mapping[str, AiApprovalHandler] | None = None,
                 source_projections: Mapping[str, Any] | None = None,
                 now: Callable[[], datetime] | None = None) -> None:
        self.unit_of_work=unit_of_work; self.actions=actions
        self.approval_handlers=dict(approval_handlers or {}); self.source_projections=dict(source_projections or {})
        self._clock=now or (lambda: datetime.now(UTC))
    @staticmethod
    def _draft_view(row,detail=False): return _draft_view(row,detail)
    @staticmethod
    def _decision_view(row):return {"id":row["id"],"decision":row["decision"],"draftVersionBefore":row["draft_version_before"],"draftVersionAfter":row["draft_version_after"],"operatorNote":row["operator_note"],"resultEntityType":row["result_entity_type"],"resultEntityId":row["result_entity_id"],"correlationId":row["correlation_id"],"decidedAt":row["decided_at"]}
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
        projection=self.source_projections.get(row["source_entity_type"])
        value["currentSource"]=None if projection is None else projection.source_state(source_entity_type=row["source_entity_type"],source_entity_id=row["source_entity_id"])
        value["reviewHistory"]=[self._decision_view(item) for item in self.unit_of_work.draft_decision_rows(draft_id)]
        return value
    def edit_draft(self,draft_id:str,*,version:int,payload:Mapping[str,Any],operator_note:str|None=None)->dict[str,Any]:
        return self._decide(draft_id,version,"edited",payload,operator_note)
    def dismiss_draft(self,draft_id:str,*,version:int,operator_note:str|None=None)->dict[str,Any]:
        return self._decide(draft_id,version,"dismissed",None,operator_note)
    def approve_draft(self,draft_id:str,*,version:int,operator_note:str|None=None)->dict[str,Any]:
        if type(version) is not int or version<1: raise AiValidationError("Draft version must be a positive integer.")
        if operator_note is not None:_text(operator_note,"Operator note",1000)
        row=self.unit_of_work.approval_context_row(draft_id)
        if row is None: raise AiNotFoundError("AI draft was not found.")
        if row["status"] not in {"proposed","edited"}: raise AiConflictError("ai_draft_terminal")
        if row["version"] != version: raise AiConflictError("ai_draft_version_conflict")
        context=AiApprovalContext(draft_id=row["id"],draft_version=row["version"],action_type=row["action_type"],draft_payload=json.loads(row["draft_payload"]),source_entity_type=row["source_entity_type"],source_entity_id=row["source_entity_id"],source_revision=row["source_revision"],source_fingerprint=row["source_fingerprint"],correlation_id=row["correlation_id"],operator_note=operator_note)
        handler=self.approval_handlers.get(context.action_type)
        if handler is None: raise AiConflictError("ai_approval_unavailable")
        return dict(handler.approve(context))
    def _decide(self,draft_id,version,decision,payload,note):
        if type(version) is not int or version<1:raise AiValidationError("Draft version must be a positive integer.")
        if note is not None:_text(note,"Operator note",1000)
        def operation(tx):
            draft=tx.draft(draft_id)
            if not draft:raise AiNotFoundError("AI draft was not found.")
            if draft["status"] not in {"proposed","edited"}:raise AiConflictError("ai_draft_terminal")
            if draft["version"]!=version:raise AiConflictError("ai_draft_version_conflict")
            run=tx.run(draft["run_id"]);definition=self.actions.require(run["action_type"]);stamp=_utc_now(self._clock);before=dict(draft)
            if decision=="edited":
                if not isinstance(payload,Mapping):raise AiValidationError("Draft payload must be an object.")
                definition.validate_payload(payload);after={**draft,"draft_payload":canonical_json(payload,maximum_bytes=definition.max_provider_request_bytes),"status":"edited","version":version+1,"updated_at":stamp};after_version=version+1
            else:after={**draft,"status":"dismissed","terminal_at":stamp,"updated_at":stamp};after_version=version
            tx.update_draft(draft_id,{key:value for key,value in after.items() if key not in {"id","run_id","entity_kind","created_at"}});record={"id":str(uuid4()),"draft_id":draft_id,"decision":decision,"draft_version_before":version,"draft_version_after":after_version,"operator_note":note,"result_entity_type":None,"result_entity_id":None,"correlation_id":run["correlation_id"],"decided_at":stamp};tx.insert_decision(record);_record_audit(tx,"ai_draft",draft_id,decision,before,after,run["correlation_id"],"local_operator");_record_audit(tx,"ai_review_decision",record["id"],decision,None,record,run["correlation_id"],"local_operator");return self._draft_view({**after,"action_type":run["action_type"],"owning_module":run["owning_module"],"source_entity_type":run["source_entity_type"],"source_entity_id":run["source_entity_id"]})
        return self.unit_of_work.write(operation)


def _day(value):
    return (value.date().isoformat() if isinstance(value,datetime) else value[:10])+"T00:00:00+00:00"
def _text(value,name,limit):
    if not isinstance(value,str) or not (item:=value.strip()) or len(item)>limit:raise AiValidationError(f"{name} must contain bounded text.")
    return item


def _utc_now(clock: Callable[[], datetime]) -> str:
    value=clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("AI clock must be timezone-aware.")
    return value.astimezone(UTC).isoformat()


def _limit_values(definition: AiActionDefinition, override: Mapping[str, Any] | None) -> dict[str, Any]:
    if override is not None:
        return dict(override)
    return {
        "enabled":definition.max_runs_per_utc_day>0,
        "connection_id":None,
        "max_runs_per_utc_day":definition.max_runs_per_utc_day,
        "max_prompt_tokens":definition.max_prompt_tokens,
        "max_completion_tokens":definition.max_completion_tokens,
        "allowed_models":canonical_json(sorted(definition.allowed_model_identities)),
    }


def _record_audit(tx: Any, entity_type: str, entity_id: str, action: str,
                  before: Mapping[str, Any] | None, after: Mapping[str, Any] | None,
                  correlation: str, actor: str) -> None:
    tx.record_audit(entity_type=entity_type,entity_id=entity_id,action=action,
                    before=ai_audit_snapshot(before),after=ai_audit_snapshot(after),
                    actor=actor,reason=f"ai_{action}",correlation_id=correlation)


def _draft_view(row, detail=False):
    """The one shared draft projection for run responses and review reads."""
    result={"id":row["id"],"runId":row["run_id"],"entityKind":row["entity_kind"],"status":row["status"],"version":row["version"],"sourceEntityType":row.get("source_entity_type"),"sourceEntityId":row.get("source_entity_id"),"actionType":row.get("action_type"),"owningModule":row.get("owning_module"),"updatedAt":row["updated_at"]}
    if detail:result.update(draftPayload=json.loads(row["draft_payload"]),confidence=None if row["confidence"] is None else json.loads(row["confidence"]),governedInput=json.loads(row["governed_input_json"]),sourceRevision=row["source_revision"],sourceFingerprint=row["source_fingerprint"])
    return result
def _settings_fingerprint(value):
    """Settings contain connection UUIDs, which are identifiers—not AI input."""
    return sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def _operation_fingerprint(value):
    return _settings_fingerprint(value)

def _provider_error_code(error: AiProviderError) -> str:
    code=getattr(error,"code",None)
    return code if isinstance(code,str) and re.fullmatch(r"ai_[a-z0-9_]{1,61}",code) else "ai_provider_failure"

def _provider_error_detail(error: AiProviderError) -> str:
    """Never retain provider response text, headers, or credentials."""
    code=_provider_error_code(error)
    return {
        "ai_provider_timeout":"The AI provider timed out.",
        "ai_provider_unavailable":"The AI provider is unavailable.",
    }.get(code,"The AI provider did not complete the request.")

def _settings_json(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)

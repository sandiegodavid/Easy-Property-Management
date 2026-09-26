"""Fail closed on unsupported governed-AI retained state."""
from __future__ import annotations
import json
import re
from hashlib import sha256
from datetime import UTC, datetime
from sqlalchemy import text
from app.modules.ai_governance.domain.audit_policy import ai_audit_snapshot
from app.modules.ai_governance.domain.models import AiActionRegistry, RedactionProfileRegistry, canonical_json, fingerprint, qualified_model_identity, validate_provider_metadata
from app.platform.migration_errors import MigrationSchemaError
from app.modules.ai_governance.infrastructure.sqlalchemy_models import AiSettingsModel, AiSettingsOperationModel, AiModelConnectionModel, AiActionLimitModel, AiRunModel, AiDraftModel, AiReviewDecisionModel


def validate_ai_governance_schema(connection, actions: AiActionRegistry | None = None, profiles: RedactionProfileRegistry | None = None, adapters=None, approval_validators=None, source_validators=None) -> None:
    # A release with no registered capability may restore settings, but must
    # never silently accept a historical governed run it cannot interpret.
    actions = actions or AiActionRegistry()
    profiles = profiles or RedactionProfileRegistry()
    approval_validators = approval_validators or {}
    source_validators = source_validators or {}
    tables={row["name"] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).mappings()}
    required={"ai_settings","ai_settings_operations","ai_model_connections","ai_action_limits","ai_runs","ai_drafts","ai_review_decisions"}
    if not required <= tables: raise MigrationSchemaError("AI governance schema is incomplete.")
    _validate_exact_schema(connection)
    settings=connection.execute(text("SELECT COUNT(*) FROM ai_settings WHERE singleton=1")).scalar_one()
    if settings!=1:raise MigrationSchemaError("AI settings singleton is invalid.")
    settings_row=connection.execute(text("SELECT * FROM ai_settings WHERE singleton=1")).mappings().one()
    if settings_row["default_connection_id"] and connection.execute(text("SELECT 1 FROM ai_model_connections WHERE id=:id"),{"id":settings_row["default_connection_id"]}).first() is None:raise MigrationSchemaError("AI settings reference an unknown connection.")
    _utc_timestamp(settings_row["updated_at"])
    for limit in connection.execute(text("SELECT * FROM ai_action_limits")).mappings():
        try:
            action=actions.require(limit["action_type"])
            models=json.loads(limit["allowed_models"])
            if not isinstance(models,list) or not models or not set(models)<=action.allowed_model_identities:raise ValueError
            if not all(1<=limit[name]<=ceiling for name,ceiling in (("max_runs_per_utc_day",action.max_runs_per_utc_day),("max_prompt_tokens",action.max_prompt_tokens),("max_completion_tokens",action.max_completion_tokens))):raise ValueError
            if limit["connection_id"] and connection.execute(text("SELECT 1 FROM ai_model_connections WHERE id=:id"),{"id":limit["connection_id"]}).first() is None:raise ValueError
            _utc_timestamp(limit["updated_at"])
        except Exception as error:raise MigrationSchemaError("AI action-limit retained data is incompatible.") from error
    for model in connection.execute(text("SELECT * FROM ai_model_connections")).mappings():
        try:
            classes=json.loads(model["cloud_data_classes"])
            if not isinstance(classes,list) or not all(isinstance(item,str) and item for item in classes):raise ValueError
            if model["execution_location"]=="cloud" and bool(model["disclosure_version"]) != bool(model["disclosure_accepted_at"]):raise ValueError
            if model["execution_location"]=="on_device" and not all(model[key] for key in ("model_artifact_digest","quantization","runtime_id","runtime_version")):raise ValueError
            created_at=_utc_timestamp(model["created_at"]); updated_at=_utc_timestamp(model["updated_at"])
            if updated_at < created_at: raise ValueError
            if model["disclosure_accepted_at"]: _utc_timestamp(model["disclosure_accepted_at"])
            if adapters is not None:
                adapter=adapters.require(model["adapter_id"],model["adapter_version"])
                if model["execution_location"] != adapter.execution_location or model["model_identifier"] not in adapter.models:raise ValueError
        except Exception as error:raise MigrationSchemaError("AI model-connection retained data is incompatible.") from error
    for run in connection.execute(text("SELECT * FROM ai_runs")).mappings():
        try:
            governed=json.loads(run["governed_input_json"])
            if canonical_json(governed)!=run["governed_input_json"]:raise ValueError
            action=actions.require(run["action_type"])
            source_validator=source_validators.get(run["source_entity_type"])
            if source_validator is None:raise ValueError
            source_validator.validate_retained_source(connection,source_entity_type=run["source_entity_type"],source_entity_id=run["source_entity_id"],source_revision=run["source_revision"],source_fingerprint=run["source_fingerprint"])
            if action.owning_module!=run["owning_module"] or action.output_schema_version!=run["output_schema_version"] or action.redaction_profile != (run["redaction_profile"],run["redaction_profile_version"]) or action.prompt_template_id != run["prompt_template_id"] or action.prompt_template_version != run["prompt_template_version"]:raise ValueError
            profiles.require(run["redaction_profile"],run["redaction_profile_version"])
            if run["execution_kind"]=="provider_generation":
                if not all(run[key] for key in ("connection_id","configuration_revision","transport_provider","adapter_version","model_identifier","execution_location","prompt_template_id","prompt_template_version")):raise ValueError
                if adapters is not None:
                    adapter=adapters.require(run["transport_provider"],run["adapter_version"])
                    if run["execution_location"] != adapter.execution_location or run["model_identifier"] not in adapter.models:raise ValueError
                    if not action.required_capabilities <= adapter.capabilities or not action.required_input_modalities <= adapter.input_modalities:raise ValueError
                if qualified_model_identity(run["transport_provider"],run["adapter_version"],run["model_identifier"]) not in action.allowed_model_identities:raise ValueError
                if action.validate_provider_request is not None:action.validate_provider_request(governed)
            if fingerprint(governed) != run["input_fingerprint"]: raise ValueError
            request={"action":run["action_type"],"source":run["source_entity_type"],"sourceId":run["source_entity_id"],"sourceRevision":run["source_revision"],"sourceFingerprint":run["source_fingerprint"],"governedInput":governed,"profile":(run["redaction_profile"],run["redaction_profile_version"]),"supersedesDraftId":run["requested_supersedes_draft_id"]}
            if sha256(json.dumps(request,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest() != run["request_fingerprint"]: raise ValueError
            # A recovered reservation is a failed attempt which never reached
            # provider transport.  It is the sole terminal state with no
            # started_at and is deliberately retained for recovery evidence.
            validate_provider_metadata(run["prompt_tokens"],run["completion_tokens"],run["provider_request_id"])
            if run["status"] == "reserved" and (run["started_at"] or run["finished_at"] or run["error_code"] or run["error_detail"]): raise ValueError
            if run["status"] == "running" and (not run["started_at"] or run["finished_at"] or run["error_code"] or run["error_detail"]): raise ValueError
            if run["status"] == "succeeded" and (not run["started_at"] or not run["finished_at"] or run["error_code"] or run["error_detail"]): raise ValueError
            if run["status"] in {"failed","blocked"} and (not run["finished_at"] or not isinstance(run["error_detail"],str) or not run["error_detail"].strip()): raise ValueError
            if run["status"] == "failed" and not run["started_at"] and run["error_code"] != "ai_run_interrupted": raise ValueError
            created_at=_utc_timestamp(run["created_at"])
            started_at=None if run["started_at"] is None else _utc_timestamp(run["started_at"])
            finished_at=None if run["finished_at"] is None else _utc_timestamp(run["finished_at"])
            if (started_at is not None and started_at < created_at) or (finished_at is not None and (finished_at < created_at or (started_at is not None and finished_at < started_at))):
                raise ValueError
        except Exception as error:raise MigrationSchemaError("AI run retained data is incompatible.") from error
        draft=connection.execute(text("SELECT * FROM ai_drafts WHERE run_id=:id"),{"id":run["id"]}).mappings().first()
        if (run["status"]=="succeeded") != (draft is not None):raise MigrationSchemaError("AI run/draft lifecycle is incompatible.")
        _validate_run_audits(connection, run)
    for draft in connection.execute(text("SELECT * FROM ai_drafts")).mappings():
        try:
            payload=json.loads(draft["draft_payload"])
            if canonical_json(payload)!=draft["draft_payload"]:raise ValueError
            run=connection.execute(text("SELECT * FROM ai_runs WHERE id=:id"),{"id":draft["run_id"]}).mappings().one()
            action=actions.require(run["action_type"]); action.validate_payload(payload)
            if draft["entity_kind"] != action.entity_kind:raise ValueError
            confidence=None if draft["confidence"] is None else json.loads(draft["confidence"])
            action.validate_confidence(confidence)
            created_at=_utc_timestamp(draft["created_at"]); updated_at=_utc_timestamp(draft["updated_at"])
            terminal_at=None if draft["terminal_at"] is None else _utc_timestamp(draft["terminal_at"])
            if updated_at < created_at or (terminal_at is not None and terminal_at < created_at): raise ValueError
        except Exception as error:raise MigrationSchemaError("AI draft payload is incompatible.") from error
        terminal=connection.execute(text("SELECT COUNT(*) FROM ai_review_decisions WHERE draft_id=:id AND decision IN ('approved','dismissed')"),{"id":draft["id"]}).scalar_one()
        if terminal>1 or ((draft["status"] in {"approved","dismissed"}) != (terminal==1)):raise MigrationSchemaError("AI draft decision history is incompatible.")
        decisions=list(connection.execute(text("SELECT * FROM ai_review_decisions WHERE draft_id=:id ORDER BY decided_at,id"),{"id":draft["id"]}).mappings())
        expected=1
        expected_status="proposed"
        previous_decided_at=created_at
        for decision in decisions:
            decided_at=_utc_timestamp(decision["decided_at"])
            if decided_at < previous_decided_at: raise MigrationSchemaError("AI review timestamp is incompatible.")
            previous_decided_at=decided_at
            if decision["correlation_id"] != run["correlation_id"]:
                raise MigrationSchemaError("AI review decision is not correlated to its run.")
            if decision["draft_version_before"] != expected:raise MigrationSchemaError("AI draft review version history is incompatible.")
            expected=decision["draft_version_after"]
            if decision["decision"]=="edited" and decision["draft_version_after"] != decision["draft_version_before"] + 1:raise MigrationSchemaError("AI draft edit version history is incompatible.")
            if decision["decision"] in {"approved","dismissed"} and decision["draft_version_after"] != decision["draft_version_before"]:raise MigrationSchemaError("AI terminal decision version history is incompatible.")
            if decision["decision"]=="approved" and action.requires_result_reference and not (decision["result_entity_type"] and decision["result_entity_id"]):raise MigrationSchemaError("AI approval result reference is incomplete.")
            audit=connection.execute(text("SELECT 1 FROM audit_events WHERE entity_type='ai_review_decision' AND entity_id=:id AND action=:action AND correlation_id=:correlation LIMIT 1"),{"id":decision["id"],"action":decision["decision"],"correlation":decision["correlation_id"]}).first()
            if audit is None:raise MigrationSchemaError("AI review audit history is incomplete.")
            draft_audit=connection.execute(text("SELECT 1 FROM audit_events WHERE entity_type='ai_draft' AND entity_id=:id AND action=:action AND correlation_id=:correlation LIMIT 1"),{"id":draft["id"],"action":decision["decision"],"correlation":decision["correlation_id"]}).first()
            if draft_audit is None:raise MigrationSchemaError("AI draft lifecycle audit history is incomplete.")
            expected_status=decision["decision"]
            if decision["decision"] == "approved" and action.approval_effect != "advisory_only":
                validator=approval_validators.get(action.action_type)
                if validator is None:raise MigrationSchemaError("AI approval lacks an owning-domain retained-data validator.")
                try: validator.validate_approval_evidence(connection,action_type=action.action_type,decision=decision,run=run)
                except Exception as error:raise MigrationSchemaError("AI approval owning-domain audit history is incompatible.") from error
        if draft["status"] == "superseded":
            expected_status="superseded"
            superseded=connection.execute(text("SELECT 1 FROM audit_events WHERE entity_type='ai_draft' AND entity_id=:id AND action='superseded' LIMIT 1"),{"id":draft["id"]}).first()
            if superseded is None:raise MigrationSchemaError("AI draft supersession audit history is incomplete.")
        if draft["version"] != expected or draft["status"] != expected_status:raise MigrationSchemaError("AI draft final state is incompatible.")
        if draft["status"] in {"approved","dismissed"} and terminal_at is not None and decisions and terminal_at != _utc_timestamp(decisions[-1]["decided_at"]):
            raise MigrationSchemaError("AI draft terminal timestamp is incompatible.")
        created=connection.execute(text("SELECT 1 FROM audit_events WHERE entity_type='ai_draft' AND entity_id=:id AND action='created' AND correlation_id=:correlation LIMIT 1"),{"id":draft["id"],"correlation":run["correlation_id"]}).first()
        if created is None:raise MigrationSchemaError("AI draft creation audit history is incomplete.")
        seen={draft["id"]};cursor=draft["supersedes_draft_id"]
        while cursor:
            if cursor in seen:raise MigrationSchemaError("AI draft supersession contains a cycle.")
            seen.add(cursor);target=connection.execute(text("SELECT supersedes_draft_id FROM ai_drafts WHERE id=:id"),{"id":cursor}).mappings().first()
            if target is None:raise MigrationSchemaError("AI draft supersession target is missing.")
            cursor=target["supersedes_draft_id"]
        if draft["supersedes_draft_id"]:
            predecessor=connection.execute(text("SELECT d.status,r.action_type,r.source_entity_type,r.source_entity_id FROM ai_drafts d JOIN ai_runs r ON r.id=d.run_id WHERE d.id=:id"),{"id":draft["supersedes_draft_id"]}).mappings().one()
            if predecessor["status"] != "superseded" or any(predecessor[key] != run[key] for key in ("action_type","source_entity_type","source_entity_id")):
                raise MigrationSchemaError("AI draft supersession lineage is incompatible.")
    broken=connection.execute(text("SELECT 1 FROM ai_review_decisions WHERE decision!='approved' AND (result_entity_type IS NOT NULL OR result_entity_id IS NOT NULL) LIMIT 1")).first()
    if broken:raise MigrationSchemaError("AI review result references are incompatible.")


def _validate_exact_schema(connection) -> None:
    models=(AiSettingsModel,AiSettingsOperationModel,AiModelConnectionModel,AiActionLimitModel,AiRunModel,AiDraftModel,AiReviewDecisionModel)
    for model in models:
        expected=model.__table__
        actual=list(connection.exec_driver_sql(f"PRAGMA table_info({expected.name})").mappings())
        shape=[(row["name"],row["type"].upper(),bool(row["notnull"]),row["pk"]) for row in actual]
        # Preserve declaration order for non-PK columns while accurately
        # comparing nullable/type/primary-key metadata.
        wanted=[(column.name,str(column.type).upper(),not column.nullable,1 if column.primary_key else 0) for column in expected.columns]
        if shape != wanted: raise MigrationSchemaError(f"AI table {expected.name} has an unsupported column shape.")
        actual_fks={(row["from"],row["table"],row["to"]) for row in connection.exec_driver_sql(f"PRAGMA foreign_key_list({expected.name})").mappings()}
        wanted_fks={(fk.parent.name,fk.column.table.name,fk.column.name) for fk in expected.foreign_keys}
        if actual_fks != wanted_fks: raise MigrationSchemaError(f"AI table {expected.name} has unsupported foreign keys.")
        actual_indexes=[]
        for index in connection.exec_driver_sql(f"PRAGMA index_list({expected.name})").mappings():
            if index["origin"] == "pk": continue
            columns=tuple(row["name"] for row in connection.exec_driver_sql(f"PRAGMA index_info({index['name']})").mappings())
            actual_indexes.append((bool(index["unique"]),columns,index["origin"] == "c"))
        expected_indexes=[]
        for index in expected.indexes:
            expected_indexes.append((bool(index.unique),tuple(column.name for column in index.columns),True))
        for column in expected.columns:
            if column.unique:
                expected_indexes.append((True,(column.name,),False))
        for constraint in expected.constraints:
            if constraint.__class__.__name__ == "UniqueConstraint":
                expected_indexes.append((True,tuple(column.name for column in constraint.columns),False))
        actual_index_shapes={(unique,columns) for unique,columns,_ in actual_indexes}
        expected_index_shapes={(unique,columns) for unique,columns,_ in expected_indexes}
        if actual_index_shapes != expected_index_shapes:
            raise MigrationSchemaError(f"AI table {expected.name} has unsupported uniqueness or indexes.")
        create_sql=connection.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"),{"name":expected.name}).scalar_one().upper()
        for constraint in expected.constraints:
            if constraint.__class__.__name__ == "CheckConstraint":
                clause=" ".join(str(constraint.sqltext).upper().split())
                normalized=" ".join(create_sql.split())
                if clause not in normalized: raise MigrationSchemaError(f"AI table {expected.name} is missing a check constraint.")
    triggers={row["name"]:row["sql"] for row in connection.execute(text("SELECT name, sql FROM sqlite_master WHERE type='trigger'")).mappings()}
    expected_triggers={
        "ai_settings_operations_no_update":"CREATE TRIGGER AI_SETTINGS_OPERATIONS_NO_UPDATE BEFORE UPDATE ON AI_SETTINGS_OPERATIONS BEGIN SELECT RAISE(ABORT, 'AI SETTINGS OPERATIONS ARE IMMUTABLE'); END",
        "ai_settings_operations_no_delete":"CREATE TRIGGER AI_SETTINGS_OPERATIONS_NO_DELETE BEFORE DELETE ON AI_SETTINGS_OPERATIONS BEGIN SELECT RAISE(ABORT, 'AI SETTINGS OPERATIONS ARE IMMUTABLE'); END",
    }
    if not set(expected_triggers) <= set(triggers):
        raise MigrationSchemaError("AI settings operations are not immutable.")
    for name, expected in expected_triggers.items():
        if _normalized_sql(triggers[name]) != _normalized_sql(expected):
            raise MigrationSchemaError("AI settings-operation trigger body is unsupported.")


def _utc_timestamp(value: str) -> datetime:
    parsed=datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise MigrationSchemaError("AI retained timestamp is not UTC.")
    return parsed


def _normalized_sql(value: str) -> str:
    return "".join(value.upper().split())


def _validate_run_audits(connection, run) -> None:
    """Reconstruct the one legal, ordered audit trail for a durable run."""
    if run["status"] == "reserved": actions=("reserved",)
    elif run["status"] == "running": actions=("reserved","started")
    elif run["status"] == "succeeded": actions=("reserved","started","succeeded")
    elif run["status"] == "failed":
        actions=(("reserved","started","interrupted") if run["started_at"] else ("reserved","interrupted")) if run["error_code"] == "ai_run_interrupted" else ("reserved","started","failed")
    elif run["started_at"]: actions=("reserved","started","blocked")
    else:
        # A policy denial may be recorded before reservation, or a policy
        # change may block an already reserved run before transport starts.
        actions=None
    events=list(connection.execute(text(
        "SELECT action,before_snapshot,after_snapshot,correlation_id FROM audit_events "
        "WHERE entity_type='ai_run' AND entity_id=:id "
        "ORDER BY occurred_at,id"
    ),{"id":run["id"]}).mappings())
    if any(event["correlation_id"] != run["correlation_id"] for event in events):
        raise MigrationSchemaError("AI run audit history has a mismatched correlation.")
    actual=tuple(event["action"] for event in events)
    if actions is None:
        if actual not in {("blocked",),("reserved","blocked")}:
            raise MigrationSchemaError("AI run audit history has an illegal blocked sequence.")
    elif actual != actions:
        raise MigrationSchemaError("AI run audit history is incomplete or contradictory.")
    if not events:
        raise MigrationSchemaError("AI run audit history is incomplete.")
    previous_after=None
    for index,event in enumerate(events):
        try:
            before=None if event["before_snapshot"] is None else json.loads(event["before_snapshot"])
            after=None if event["after_snapshot"] is None else json.loads(event["after_snapshot"])
        except Exception as error:
            raise MigrationSchemaError("AI run audit snapshots are invalid.") from error
        expected_status=_run_status_after(event["action"])
        if expected_status is None or not isinstance(after,dict) or after.get("status") != expected_status:
            raise MigrationSchemaError("AI run audit state transition is invalid.")
        if index == 0:
            if before is not None:
                raise MigrationSchemaError("AI run creation audit has an invalid before-state.")
        elif before != previous_after:
            raise MigrationSchemaError("AI run audit before/after states are not contiguous.")
        previous_after=after
    if previous_after != _audit_snapshot(run):
        raise MigrationSchemaError("AI run terminal audit does not match retained state.")


def _run_status_after(action: str) -> str | None:
    return {"reserved":"reserved","started":"running","succeeded":"succeeded",
            "failed":"failed","interrupted":"failed","blocked":"blocked"}.get(action)


def _audit_snapshot(row) -> dict:
    return ai_audit_snapshot(dict(row))

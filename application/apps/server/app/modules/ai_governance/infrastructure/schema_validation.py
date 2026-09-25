"""Fail closed on unsupported governed-AI retained state."""
from __future__ import annotations
import json
from hashlib import sha256
from sqlalchemy import text
from app.modules.ai_governance.domain.models import AiActionRegistry, RedactionProfileRegistry, canonical_json, fingerprint
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
    for operation in connection.execute(text("SELECT * FROM ai_settings_operations")).mappings():
        try:
            import re
            if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",operation["idempotency_key"]): raise ValueError
            result=json.loads(operation["result_json"])
            if json.dumps(result,sort_keys=True,separators=(",",":"),ensure_ascii=False) != operation["result_json"] or not re.fullmatch(r"[0-9a-f]{64}",operation["request_fingerprint"]) or set(result) != {"killSwitch","builtInEnabled","defaultConnectionId","updatedAt"} or type(result["killSwitch"]) is not bool or type(result["builtInEnabled"]) is not bool or (result["defaultConnectionId"] is not None and not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",result["defaultConnectionId"])):
                raise ValueError
            from datetime import datetime
            if datetime.fromisoformat(operation["created_at"]).tzinfo is None: raise ValueError
        except Exception as error: raise MigrationSchemaError("AI settings operation retained data is incompatible.") from error
    for limit in connection.execute(text("SELECT * FROM ai_action_limits")).mappings():
        try:
            action=actions.require(limit["action_type"])
            models=json.loads(limit["allowed_models"])
            if not isinstance(models,list) or not models or not set(models)<=action.allowed_models:raise ValueError
            if not all(1<=limit[name]<=ceiling for name,ceiling in (("max_runs_per_utc_day",action.max_runs_per_utc_day),("max_prompt_tokens",action.max_prompt_tokens),("max_completion_tokens",action.max_completion_tokens))):raise ValueError
            if limit["connection_id"] and connection.execute(text("SELECT 1 FROM ai_model_connections WHERE id=:id"),{"id":limit["connection_id"]}).first() is None:raise ValueError
        except Exception as error:raise MigrationSchemaError("AI action-limit retained data is incompatible.") from error
    for model in connection.execute(text("SELECT * FROM ai_model_connections")).mappings():
        try:
            classes=json.loads(model["cloud_data_classes"])
            if not isinstance(classes,list) or not all(isinstance(item,str) and item for item in classes):raise ValueError
            if model["execution_location"]=="cloud" and bool(model["disclosure_version"]) != bool(model["disclosure_accepted_at"]):raise ValueError
            if model["execution_location"]=="on_device" and not all(model[key] for key in ("model_artifact_digest","quantization","runtime_id","runtime_version")):raise ValueError
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
            source_validator.validate_source(connection,source_entity_type=run["source_entity_type"],source_entity_id=run["source_entity_id"],source_revision=run["source_revision"],source_fingerprint=run["source_fingerprint"])
            if action.owning_module!=run["owning_module"] or action.output_schema_version!=run["output_schema_version"] or action.redaction_profile != (run["redaction_profile"],run["redaction_profile_version"]) or action.prompt_template_id != run["prompt_template_id"] or action.prompt_template_version != run["prompt_template_version"]:raise ValueError
            profiles.require(run["redaction_profile"],run["redaction_profile_version"])
            if run["execution_kind"]=="provider_generation":
                if not all(run[key] for key in ("connection_id","configuration_revision","transport_provider","adapter_version","model_identifier","execution_location","prompt_template_id","prompt_template_version")):raise ValueError
                if adapters is not None:
                    adapter=adapters.require(run["transport_provider"],run["adapter_version"])
                    if run["execution_location"] != adapter.execution_location or run["model_identifier"] not in adapter.models:raise ValueError
                if action.validate_provider_request is not None:action.validate_provider_request(governed)
            if fingerprint(governed) != run["input_fingerprint"]: raise ValueError
            request={"action":run["action_type"],"source":run["source_entity_type"],"sourceId":run["source_entity_id"],"sourceRevision":run["source_revision"],"sourceFingerprint":run["source_fingerprint"],"governedInput":governed,"profile":(run["redaction_profile"],run["redaction_profile_version"]),"supersedesDraftId":run["requested_supersedes_draft_id"]}
            if sha256(json.dumps(request,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest() != run["request_fingerprint"]: raise ValueError
            # A recovered reservation is a failed attempt which never reached
            # provider transport.  It is the sole terminal state with no
            # started_at and is deliberately retained for recovery evidence.
            if run["status"] in {"running","succeeded"} and not run["started_at"]: raise ValueError
            if run["status"] == "failed" and not run["started_at"] and run["error_code"] != "ai_run_interrupted": raise ValueError
            if run["status"] in {"succeeded","failed","blocked"} and not run["finished_at"]: raise ValueError
        except Exception as error:raise MigrationSchemaError("AI run retained data is incompatible.") from error
        draft=connection.execute(text("SELECT * FROM ai_drafts WHERE run_id=:id"),{"id":run["id"]}).mappings().first()
        if (run["status"]=="succeeded") != (draft is not None):raise MigrationSchemaError("AI run/draft lifecycle is incompatible.")
    for draft in connection.execute(text("SELECT * FROM ai_drafts")).mappings():
        try:
            payload=json.loads(draft["draft_payload"])
            if canonical_json(payload)!=draft["draft_payload"]:raise ValueError
            run=connection.execute(text("SELECT * FROM ai_runs WHERE id=:id"),{"id":draft["run_id"]}).mappings().one()
            action=actions.require(run["action_type"]); action.validate_payload(payload)
            if draft["entity_kind"] != action.entity_kind:raise ValueError
            if draft["confidence"] is not None:
                confidence=json.loads(draft["confidence"])
                if not isinstance(confidence,dict) or confidence.get("label") not in action.allowed_confidence_labels:raise ValueError
        except Exception as error:raise MigrationSchemaError("AI draft payload is incompatible.") from error
        terminal=connection.execute(text("SELECT COUNT(*) FROM ai_review_decisions WHERE draft_id=:id AND decision IN ('approved','dismissed')"),{"id":draft["id"]}).scalar_one()
        if terminal>1 or ((draft["status"] in {"approved","dismissed"}) != (terminal==1)):raise MigrationSchemaError("AI draft decision history is incompatible.")
        decisions=list(connection.execute(text("SELECT * FROM ai_review_decisions WHERE draft_id=:id ORDER BY decided_at,id"),{"id":draft["id"]}).mappings())
        expected=1
        expected_status="proposed"
        for decision in decisions:
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
        created=connection.execute(text("SELECT 1 FROM audit_events WHERE entity_type='ai_draft' AND entity_id=:id AND action='created' LIMIT 1"),{"id":draft["id"]}).first()
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
        wanted=[(column.name,str(column.type).upper(),not column.nullable,index + 1 if column.primary_key else 0) for index,column in enumerate(expected.primary_key.columns)]
        # Preserve declaration order for non-PK columns while accurately
        # comparing nullable/type/primary-key metadata.
        wanted=[(column.name,str(column.type).upper(),not column.nullable,1 if column.primary_key else 0) for column in expected.columns]
        if shape != wanted: raise MigrationSchemaError(f"AI table {expected.name} has an unsupported column shape.")
        actual_fks={(row["from"],row["table"],row["to"]) for row in connection.exec_driver_sql(f"PRAGMA foreign_key_list({expected.name})").mappings()}
        wanted_fks={(fk.parent.name,fk.column.table.name,fk.column.name) for fk in expected.foreign_keys}
        if actual_fks != wanted_fks: raise MigrationSchemaError(f"AI table {expected.name} has unsupported foreign keys.")
        actual_indexes={row["name"] for row in connection.exec_driver_sql(f"PRAGMA index_list({expected.name})").mappings()}
        expected_indexes={index.name for index in expected.indexes if index.name}
        if not expected_indexes <= actual_indexes: raise MigrationSchemaError(f"AI table {expected.name} is missing an index.")
        create_sql=connection.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"),{"name":expected.name}).scalar_one().upper()
        for constraint in expected.constraints:
            if constraint.__class__.__name__ == "CheckConstraint":
                clause=" ".join(str(constraint.sqltext).upper().split())
                normalized=" ".join(create_sql.split())
                if clause not in normalized: raise MigrationSchemaError(f"AI table {expected.name} is missing a check constraint.")
    triggers={row["name"] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'")).mappings()}
    if not {"ai_settings_operations_no_update","ai_settings_operations_no_delete"} <= triggers:
        raise MigrationSchemaError("AI settings operations are not immutable.")

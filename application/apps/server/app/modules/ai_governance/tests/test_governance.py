from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4
from sqlalchemy import text

from app.modules.ai_governance.application.ports import AiProviderResult
from app.modules.ai_governance.application.service import AiAdapterDefinition, AiAdapterRegistry, AiGovernanceService, _operation_fingerprint
from app.modules.ai_governance.domain.models import AiActionDefinition, AiActionRegistry, AiConflictError, RedactionProfile, RedactionProfileRegistry, RedactionRule, fingerprint
from app.modules.ai_governance.infrastructure.unit_of_work import SQLiteAiGovernanceUnitOfWork
from app.modules.ai_governance.infrastructure.schema_validation import validate_ai_governance_schema
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.platform.product_migrations import initialize_latest_schema, validate_latest_schema
from app.platform.sqlite_engine import create_sqlite_engine


class _Provider:
    def __init__(self): self.calls=0
    def estimate_input_tokens(self, request, model): return 2
    def generate(self, request, model, maximum, timeout):
        self.calls+=1; return AiProviderResult({"summary": request["message"]})


class _SyntheticApprovalHandler:
    """A tiny owning-domain UoW stand-in: all three writes share one transaction."""
    def __init__(self, unit_of_work): self.unit_of_work=unit_of_work
    def approve(self, context):
        def operation(tx):
            source=tx.connection.exec_driver_sql("SELECT revision, fingerprint, tombstoned FROM synthetic_ai_sources WHERE id=:id",{"id":context.source_entity_id}).mappings().first()
            if source is None or source["tombstoned"] or (source["revision"],source["fingerprint"]) != (context.source_revision,context.source_fingerprint):
                raise AiConflictError("ai_source_stale")
            result_id=str(uuid4())
            tx.connection.exec_driver_sql(
                "INSERT INTO synthetic_ai_results (id, draft_id) VALUES (:id,:draft_id)",
                {"id":result_id,"draft_id":context.draft_id},
            )
            tx.record_audit(entity_type="synthetic_ai_result",entity_id=result_id,
                            action="created",before=None,after={"id":result_id,"draftId":context.draft_id},
                            correlation_id=context.correlation_id,actor="local_operator",reason="synthetic_approved")
            draft=tx.review_operations().complete_approval(
                draft_id=context.draft_id,expected_version=context.draft_version,
                result_entity_type="synthetic_ai_result",result_entity_id=result_id,
                operator_note=context.operator_note,
            )
            return {"status":draft["status"],"resultEntityId":result_id}
        return self.unit_of_work.write(operation)


class _SyntheticApprovalEvidence:
    def validate_approval_evidence(self, connection, *, action_type, decision, run):
        result=connection.execute(text("SELECT 1 FROM synthetic_ai_results WHERE id=:id"),{"id":decision["result_entity_id"]}).first()
        audit=connection.execute(text("SELECT 1 FROM audit_events WHERE entity_type='synthetic_ai_result' AND entity_id=:id AND action='created' AND correlation_id=:correlation"),{"id":decision["result_entity_id"],"correlation":decision["correlation_id"]}).first()
        if result is None or audit is None: raise ValueError("missing owning-domain approval evidence")


class _SyntheticSource:
    def source_state(self, *, source_entity_type, source_entity_id):
        return {"revision":"1","fingerprint":"a"*64,"tombstoned":False,"availability":"available","comparisonState":"current"}
    def validate_source(self, connection, *, source_entity_type, source_entity_id, source_revision, source_fingerprint):
        source=connection.execute(text("SELECT revision,fingerprint,tombstoned FROM synthetic_ai_sources WHERE id=:id"),{"id":source_entity_id}).mappings().first()
        # Workspace validation accepts an explicit tombstone as retained
        # historical evidence; runtime generation rejects it separately.
        if source_entity_type != "synthetic" or source is None or (source["revision"],source["fingerprint"]) != (source_revision,source_fingerprint):
            raise ValueError("source is stale or missing")


class AiGovernanceTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); self.database=Path(self.temp.name)/"workspace.sqlite"; initialize_latest_schema(self.database)
        self.provider=_Provider()
        action=AiActionDefinition("synthetic_action","test",frozenset({"synthetic"}),("synthetic_profile",1),"synthetic",1,1,"synthetic",lambda value:None,lambda value: None if isinstance(value.get("summary"),str) else (_ for _ in ()).throw(ValueError()),allowed_models=frozenset({"synthetic-model"}),approval_effect="create",requires_result_reference=True)
        profile=RedactionProfile("synthetic_profile",1,{"message":RedactionRule("allow"),"private":RedactionRule("drop")},{"message":"included","private":"dropped"})
        self.service=AiGovernanceService(SQLiteAiGovernanceUnitOfWork(self.database,AuditRecorder(SQLiteAuditRepository(self.database))),workspace_id="test",actions=AiActionRegistry((action,)),profiles=RedactionProfileRegistry((profile,)),adapters=AiAdapterRegistry((AiAdapterDefinition("synthetic","1","on_device",frozenset({"synthetic-model"}),False),)),providers={"synthetic":self.provider},source_projections={"synthetic":_SyntheticSource()})
        connection=self.service.create_connection({"label":"Synthetic","adapter_id":"synthetic","adapter_version":"1","model_identifier":"synthetic-model","execution_location":"on_device","model_artifact_digest":"digest","quantization":"q","runtime_id":"runtime","runtime_version":"1"})
        self.service.update_settings(built_in_enabled=True,default_connection_id=connection["id"])
        with create_sqlite_engine(self.database).begin() as connection:
            connection.exec_driver_sql("CREATE TABLE synthetic_ai_results (id TEXT PRIMARY KEY, draft_id TEXT NOT NULL)")
            connection.exec_driver_sql("CREATE TABLE synthetic_ai_sources (id TEXT PRIMARY KEY, revision TEXT NOT NULL, fingerprint TEXT NOT NULL, tombstoned INTEGER NOT NULL)")
            connection.exec_driver_sql("INSERT INTO synthetic_ai_sources (id,revision,fingerprint,tombstoned) VALUES ('source','1',:fingerprint,0)",{"fingerprint":"a"*64})
        self.service.approval_handlers["synthetic_action"]=_SyntheticApprovalHandler(self.service.unit_of_work)
    def tearDown(self): self.temp.cleanup()
    def test_run_retains_only_redacted_input_and_replays_same_request(self):
        key=str(uuid4()); arguments=dict(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe","private":"do not send"},idempotency_key=key)
        result=self.service.run(**arguments); replay=self.service.run(**arguments)
        self.assertEqual(1,self.provider.calls); self.assertEqual(result,replay)
        detail=self.service.draft_detail(result["draft"]["id"])
        self.assertEqual({"message":"safe"},detail["governedInput"])
        self.assertNotIn("private",detail["governedInput"])
        with self.assertRaises(AiConflictError): self.service.run(**{**arguments,"candidate":{"message":"changed","private":"do not send"}})
    def test_dismissal_is_terminal_and_schema_stays_valid(self):
        result=self.service.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe","private":"ignored"},idempotency_key=str(uuid4()))
        draft=result["draft"]; dismissed=self.service.dismiss_draft(draft["id"],version=1,operator_note="not applicable")
        self.assertEqual("dismissed",dismissed["status"])
        with self.assertRaises(AiConflictError): self.service.edit_draft(draft["id"],version=1,payload={"summary":"later"})
        with create_sqlite_engine(self.database).connect() as connection:
            validate_ai_governance_schema(connection,self.service.actions,self.service.profiles,self.service.adapters,source_validators={"synthetic":_SyntheticSource()})
    def test_value_error_from_output_validator_fails_the_run(self):
        self.provider.generate=lambda *args: AiProviderResult({"wrong":"shape"})
        result=self.service.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe","private":"ignored"},idempotency_key=str(uuid4()))
        self.assertEqual("failed",result["status"])
        self.assertEqual("ai_output_invalid",result["errorCode"])

    def test_settings_replay_and_changed_reuse_are_durable(self):
        key=str(uuid4())
        connection_id=self.service.connections()[0]["id"]
        first=self.service.update_settings(kill_switch=False,default_connection_id=connection_id,idempotency_key=key)
        self.service.update_settings(kill_switch=True,idempotency_key=str(uuid4()))
        replay=self.service.update_settings(kill_switch=False,default_connection_id=connection_id,idempotency_key=key)
        self.assertEqual(first,replay)
        self.assertTrue(self.service.settings()["killSwitch"])
        with self.assertRaises(AiConflictError):
            self.service.update_settings(kill_switch=True,idempotency_key=key)

    def test_recovered_reservation_is_failed_without_transport_start(self):
        request_fingerprint=_operation_fingerprint({"action":"synthetic_action","source":"synthetic","sourceId":"source","sourceRevision":"1","sourceFingerprint":"a"*64,"governedInput":{"message":"safe"},"profile":("synthetic_profile",1),"supersedesDraftId":None})
        result=self.service.unit_of_work.write(lambda tx: self.service._runtime._reserve(
            tx,self.service.actions.require("synthetic_action"),'{"message":"safe"}',"synthetic","source","1","a"*64,
            str(uuid4()),request_fingerprint,str(uuid4()),str(uuid4()),self.service._runtime._now(),
            self.service._runtime._preflight(self.service.actions.require("synthetic_action"),{"message":"safe"}),None,
        ))
        self.assertEqual("reserved",result["status"])
        self.assertEqual(1,self.service.recover_interrupted())
        row=self.service.unit_of_work.run_row(result["id"])
        self.assertEqual("failed",row["status"]); self.assertIsNone(row["started_at"])
        with create_sqlite_engine(self.database).connect() as connection:
            validate_ai_governance_schema(connection,self.service.actions,self.service.profiles,self.service.adapters,source_validators={"synthetic":_SyntheticSource()})

    def test_successful_retry_supersedes_its_predecessor_atomically(self):
        base=dict(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"})
        original=self.service.run(**base,idempotency_key=str(uuid4()))
        replacement=self.service.run(**base,idempotency_key=str(uuid4()),supersedes_draft_id=original["draft"]["id"])
        predecessor=self.service.draft_detail(original["draft"]["id"])
        self.assertEqual("superseded",predecessor["status"])
        self.assertEqual("proposed",replacement["draft"]["status"])
        with create_sqlite_engine(self.database).connect() as connection:
            validate_ai_governance_schema(connection,self.service.actions,self.service.profiles,self.service.adapters,source_validators={"synthetic":_SyntheticSource()})

    def test_non_advisory_approval_keeps_domain_and_ai_evidence_in_one_transaction(self):
        result=self.service.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"},idempotency_key=str(uuid4()))
        approved=self.service.approve_draft(result["draft"]["id"],version=1,operator_note="confirmed")
        self.assertEqual("approved",approved["status"])
        with create_sqlite_engine(self.database).connect() as connection:
            validate_ai_governance_schema(connection,self.service.actions,self.service.profiles,self.service.adapters,{"synthetic_action":_SyntheticApprovalEvidence()},{"synthetic":_SyntheticSource()})

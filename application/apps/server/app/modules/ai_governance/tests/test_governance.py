from __future__ import annotations
from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import json
import threading
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4
from sqlalchemy import text

from app.modules.ai_governance.application.ports import AiProviderError, AiProviderResult
from app.modules.ai_governance.application.service import AiAdapterDefinition, AiAdapterRegistry, AiConfigurationService, AiDraftReviewService, AiGenerationCoordinator, AiRunReservation, _operation_fingerprint
from app.modules.ai_governance.domain.models import AiActionDefinition, AiActionRegistry, AiConflictError, AiValidationError, ConfidenceContract, RedactionProfile, RedactionProfileRegistry, RedactionRule, fingerprint, qualified_model_identity
from app.modules.ai_governance.infrastructure.unit_of_work import SQLiteAiGovernanceUnitOfWork
from app.modules.ai_governance.infrastructure.schema_validation import validate_ai_governance_schema
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.platform.product_migrations import initialize_latest_schema, validate_latest_schema
from app.platform.migration_errors import MigrationSchemaError
from app.platform.sqlite_engine import create_sqlite_engine
from app.platform.config import LocalConfig
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.modules.workspace.tests.test_backup_service import MemorySecretStore


class _Provider:
    def __init__(self): self.calls=0; self.before_generate=None
    def estimate_input_tokens(self, request, model): return 2
    def probe(self, request, model, timeout):
        if request != {"kind":"connection_probe","input":"health check"}:
            raise ValueError("unexpected connection probe")
        return AiProviderResult({"status":"ok"})
    def generate(self, request, model, maximum, timeout):
        self.calls+=1
        if self.before_generate is not None:
            self.before_generate()
        return AiProviderResult({"summary": request["message"]})


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
    def validate_current_source(self, connection, *, source_entity_type, source_entity_id, source_revision, source_fingerprint):
        source=connection.execute(text("SELECT revision,fingerprint,tombstoned FROM synthetic_ai_sources WHERE id=:id"),{"id":source_entity_id}).mappings().first()
        if source_entity_type != "synthetic" or source is None or source["tombstoned"] or (source["revision"],source["fingerprint"]) != (source_revision,source_fingerprint):
            raise ValueError("source is stale or missing")
    def validate_retained_source(self, connection, *, source_entity_type, source_entity_id, source_revision, source_fingerprint):
        source=connection.execute(text("SELECT tombstoned FROM synthetic_ai_sources WHERE id=:id"),{"id":source_entity_id}).mappings().first()
        # Historical run facts remain valid after a later source update or an
        # explicit tombstone, but never after an unaccounted-for deletion.
        if source_entity_type != "synthetic" or source is None:
            raise ValueError("source evidence is missing")


class _PartySource:
    """A product-table source validator used by the archive acceptance test."""
    def source_state(self, *, source_entity_type, source_entity_id): return None
    def validate_current_source(self, connection, *, source_entity_type, source_entity_id, source_revision, source_fingerprint):
        row=connection.execute(text("SELECT updated_at, archived_at FROM parties WHERE id=:id"),{"id":source_entity_id}).mappings().first()
        if source_entity_type != "party" or row is None or row["archived_at"] is not None or row["updated_at"] != source_revision or source_fingerprint != "b"*64:
            raise ValueError("party source is stale")
    def validate_retained_source(self, connection, *, source_entity_type, source_entity_id, source_revision, source_fingerprint):
        row=connection.execute(text("SELECT 1 FROM parties WHERE id=:id"),{"id":source_entity_id}).first()
        if source_entity_type != "party" or row is None or source_fingerprint != "b"*64:
            raise ValueError("party source evidence is missing")


class _Credentials:
    def __init__(self): self.values={}
    def get_credential(self, workspace_id, connection_id): return self.values.get((workspace_id,connection_id))
    def set_credential(self, workspace_id, connection_id, credential): self.values[(workspace_id,connection_id)]=credential
    def delete_credential(self, workspace_id, connection_id): self.values.pop((workspace_id,connection_id),None)


class _Services:
    """Test-only ergonomic holder; production composes focused services directly."""
    def __init__(self, unit_of_work, **dependencies):
        approval_handlers=dependencies.pop("approval_handlers",None)
        source_projections=dependencies.pop("source_projections",None)
        self.generation=AiGenerationCoordinator(unit_of_work,**dependencies)
        self.configuration=AiConfigurationService(
            self.generation.unit_of_work, workspace_id=self.generation.workspace_id,
            actions=self.generation.actions, adapters=self.generation.adapters,
            providers=self.generation.providers, credentials=self.generation.credentials,
        )
        self.drafts=AiDraftReviewService(
            self.generation.unit_of_work, actions=self.generation.actions,
            approval_handlers=approval_handlers, source_projections=source_projections,
        )
class AiGovernanceTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); self.database=Path(self.temp.name)/"workspace.sqlite"; initialize_latest_schema(self.database)
        self.provider=_Provider()
        action=AiActionDefinition("synthetic_action","test",frozenset({"synthetic"}),("synthetic_profile",1),"synthetic",1,1,"synthetic",lambda value:None,lambda value: None if isinstance(value.get("summary"),str) else (_ for _ in ()).throw(ValueError()),allowed_model_identities=frozenset({qualified_model_identity("synthetic","1","synthetic-model")}),approval_effect="create",requires_result_reference=True)
        profile=RedactionProfile("synthetic_profile",1,{"message":RedactionRule("allow"),"private":RedactionRule("drop")},{"message":"included","private":"dropped"})
        source=_SyntheticSource()
        self.service=_Services(SQLiteAiGovernanceUnitOfWork(self.database,AuditRecorder(SQLiteAuditRepository(self.database)),{"synthetic":source}),workspace_id="test",actions=AiActionRegistry((action,)),profiles=RedactionProfileRegistry((profile,)),adapters=AiAdapterRegistry((AiAdapterDefinition("synthetic","1","on_device",frozenset({"synthetic-model"}),False),)),providers={"synthetic":self.provider},source_projections={"synthetic":source})
        self.generation=self.service.generation; self.configuration=self.service.configuration; self.drafts=self.service.drafts
        self.actions=self.generation.actions; self.profiles=self.generation.profiles; self.adapters=self.generation.adapters; self.unit_of_work=self.generation.unit_of_work
        connection=self.configuration.create_connection({"label":"Synthetic","adapter_id":"synthetic","adapter_version":"1","model_identifier":"synthetic-model","execution_location":"on_device","model_artifact_digest":"digest","quantization":"q","runtime_id":"runtime","runtime_version":"1"})
        self.configuration.update_settings(built_in_enabled=True,default_connection_id=connection["id"])
        with create_sqlite_engine(self.database).begin() as connection:
            connection.exec_driver_sql("CREATE TABLE synthetic_ai_results (id TEXT PRIMARY KEY, draft_id TEXT NOT NULL)")
            connection.exec_driver_sql("CREATE TABLE synthetic_ai_sources (id TEXT PRIMARY KEY, revision TEXT NOT NULL, fingerprint TEXT NOT NULL, tombstoned INTEGER NOT NULL)")
            connection.exec_driver_sql("INSERT INTO synthetic_ai_sources (id,revision,fingerprint,tombstoned) VALUES ('source','1',:fingerprint,0)",{"fingerprint":"a"*64})
        handler=_SyntheticApprovalHandler(self.unit_of_work)
        self.drafts.approval_handlers["synthetic_action"]=handler
    def tearDown(self): self.temp.cleanup()
    def test_run_retains_only_redacted_input_and_replays_same_request(self):
        key=str(uuid4()); arguments=dict(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe","private":"do not send"},idempotency_key=key)
        result=self.generation.run(**arguments); replay=self.generation.run(**arguments)
        self.assertEqual(1,self.provider.calls); self.assertEqual(result,replay)
        detail=self.drafts.draft_detail(result["draft"]["id"])
        self.assertEqual({"message":"safe"},detail["governedInput"])
        self.assertNotIn("private",detail["governedInput"])
        with self.assertRaises(AiConflictError): self.generation.run(**{**arguments,"candidate":{"message":"changed","private":"do not send"}})

    def test_concurrent_same_key_reserves_once_and_calls_provider_once(self):
        entered=threading.Event(); release=threading.Event()
        self.provider.before_generate=lambda: (entered.set(),release.wait(5))
        arguments=dict(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"},idempotency_key=str(uuid4()))
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.generation.run,**arguments)
            self.assertTrue(entered.wait(5))
            second=pool.submit(self.generation.run,**arguments)
            release.set()
            results=(first.result(timeout=10),second.result(timeout=10))
        self.assertEqual(1,self.provider.calls)
        self.assertIn("succeeded",{item["status"] for item in results})

    def test_retained_run_rejects_duplicate_or_contradictory_audit_events(self):
        result=self.generation.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"},idempotency_key=str(uuid4()))
        with create_sqlite_engine(self.database).begin() as connection:
            connection.execute(text(
                "INSERT INTO audit_events "
                "(id,occurred_at,entity_type,entity_id,action,before_snapshot,after_snapshot,changed_fields,reason,actor_kind,actor_reference,correlation_id,schema_version) "
                "SELECT :id,occurred_at,entity_type,entity_id,'failed',before_snapshot,after_snapshot,changed_fields,reason,actor_kind,actor_reference,correlation_id,schema_version "
                "FROM audit_events WHERE entity_type='ai_run' AND entity_id=:run_id LIMIT 1"
            ),{"id":str(uuid4()),"run_id":result["id"]})
        with create_sqlite_engine(self.database).connect() as connection:
            with self.assertRaises(MigrationSchemaError):
                validate_ai_governance_schema(connection,self.actions,self.profiles,self.adapters,source_validators={"synthetic":_SyntheticSource()})

    def test_retained_run_rejects_lifecycle_event_with_another_correlation(self):
        result=self.generation.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"},idempotency_key=str(uuid4()))
        with create_sqlite_engine(self.database).begin() as connection:
            connection.execute(text(
                "INSERT INTO audit_events (id,occurred_at,entity_type,entity_id,action,before_snapshot,after_snapshot,changed_fields,reason,actor_kind,actor_reference,correlation_id,schema_version) "
                "SELECT :id,occurred_at,entity_type,entity_id,action,before_snapshot,after_snapshot,changed_fields,reason,actor_kind,actor_reference,:correlation,schema_version "
                "FROM audit_events WHERE entity_type='ai_run' AND entity_id=:run_id LIMIT 1"
            ),{"id":str(uuid4()),"correlation":str(uuid4()),"run_id":result["id"]})
        with create_sqlite_engine(self.database).connect() as connection:
            with self.assertRaises(MigrationSchemaError):
                validate_ai_governance_schema(connection,self.actions,self.profiles,self.adapters,source_validators={"synthetic":_SyntheticSource()})

    def test_explicit_connection_switches_provider_and_never_falls_back(self):
        original=self.actions.require("synthetic_action")
        action=replace(original,allowed_model_identities=frozenset({qualified_model_identity("synthetic","1","synthetic-model"),qualified_model_identity("alternate","1","alternate-model")}),required_data_classes=frozenset({"public"}))
        alternate=AiAdapterDefinition("alternate","1","cloud",frozenset({"alternate-model"}),False)
        self.actions=AiActionRegistry((action,)); self.adapters=AiAdapterRegistry((self.adapters.require("synthetic","1"),alternate))
        self.generation.actions=self.actions; self.configuration.actions=self.actions
        self.generation.adapters=self.adapters; self.configuration.adapters=self.adapters
        alternate_provider=_Provider(); self.generation.providers["alternate"]=alternate_provider; self.configuration.providers["alternate"]=alternate_provider
        first=self.generation.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"first"},idempotency_key=str(uuid4()))
        cloud=self.configuration.create_connection({"label":"Cloud","adapter_id":"alternate","adapter_version":"1","model_identifier":"alternate-model","execution_location":"cloud"})
        self.configuration.update_settings(default_connection_id=cloud["id"],idempotency_key=str(uuid4()))
        blocked=self.generation.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"blocked"},idempotency_key=str(uuid4()))
        self.assertEqual("ai_disclosure_required",blocked["errorCode"])
        self.configuration.set_disclosure(cloud["id"],expected_revision=1,disclosure_version="v1",data_classes=["public"])
        second=self.generation.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"second"},idempotency_key=str(uuid4()))
        self.assertEqual("succeeded",second["status"]); self.assertEqual(1,alternate_provider.calls)
        with create_sqlite_engine(self.database).connect() as connection:
            rows=list(connection.execute(text("SELECT transport_provider,model_identifier FROM ai_runs WHERE id IN (:first,:second) ORDER BY created_at,id"),{"first":first["id"],"second":second["id"]}).mappings())
        self.assertEqual([("synthetic","synthetic-model"),("alternate","alternate-model")],[(row["transport_provider"],row["model_identifier"]) for row in rows])
        del self.generation.providers["alternate"]
        unavailable=self.generation.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"no fallback"},idempotency_key=str(uuid4()))
        self.assertEqual("ai_provider_unavailable",unavailable["errorCode"])
        self.assertEqual(1,alternate_provider.calls)
        self.assertEqual(1,self.provider.calls)

    def test_model_allowlist_requires_adapter_and_version_identity(self):
        original=self.actions.require("synthetic_action")
        alternate=AiAdapterDefinition("alternate","1","on_device",frozenset({"synthetic-model"}),False)
        self.adapters=AiAdapterRegistry((self.adapters.require("synthetic","1"),alternate))
        self.generation.adapters=self.adapters; self.configuration.adapters=self.adapters
        connection=self.configuration.create_connection({"label":"Same model, other adapter","adapter_id":"alternate","adapter_version":"1","model_identifier":"synthetic-model","execution_location":"on_device","model_artifact_digest":"digest","quantization":"q","runtime_id":"runtime","runtime_version":"1"})
        self.configuration.update_settings(default_connection_id=connection["id"])
        result=self.generation.run(action_type=original.action_type,source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"},idempotency_key=str(uuid4()))
        self.assertEqual("ai_model_not_allowed",result["errorCode"])

    def test_confidence_requires_registered_calibration_provenance(self):
        action=replace(self.actions.require("synthetic_action"),confidence_contract=ConfidenceContract(frozenset({"high"}),"calibration-2026",frozenset({"dataset"})))
        self.actions=AiActionRegistry((action,)); self.generation.actions=self.actions
        self.provider.generate=lambda *args: AiProviderResult({"summary":"safe"},confidence={"label":"high","score":0.9,"calibration_source":"calibration-2026","dataset":"holdout"})
        result=self.generation.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"},idempotency_key=str(uuid4()))
        self.assertEqual({"label":"high","score":0.9,"calibration_source":"calibration-2026","dataset":"holdout"},self.drafts.draft_detail(result["draft"]["id"])["confidence"])
        self.provider.generate=lambda *args: AiProviderResult({"summary":"safe"},confidence={"label":"high","score":0.9,"calibration_source":"other","dataset":"holdout"})
        invalid=self.generation.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"},idempotency_key=str(uuid4()))
        self.assertEqual("ai_output_invalid",invalid["errorCode"])

    def test_credential_changes_are_audited_without_secret_content(self):
        connection_id=self.configuration.connections()[0]["id"]
        self.configuration.credentials=_Credentials()
        self.configuration.set_credential(connection_id,"very-secret-value")
        self.configuration.set_credential(connection_id,"another-secret-value")
        self.configuration.delete_credential(connection_id)
        with create_sqlite_engine(self.database).connect() as connection:
            rows=list(connection.execute(text("SELECT action,before_snapshot,after_snapshot FROM audit_events WHERE entity_type='ai_model_connection' AND entity_id=:id AND action LIKE 'credential_%' ORDER BY occurred_at,id"),{"id":connection_id}).mappings())
        self.assertEqual(["credential_set","credential_replaced","credential_deleted"],[row["action"] for row in rows])
        self.assertNotIn("secret",json.dumps([dict(row) for row in rows]))

    def test_approval_note_is_bounded_before_owning_domain_dispatch(self):
        result=self.generation.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"},idempotency_key=str(uuid4()))
        with self.assertRaises(AiValidationError):
            self.drafts.approve_draft(result["draft"]["id"],version=1,operator_note="x"*1001)

    def test_same_key_replays_after_the_source_changes(self):
        arguments=dict(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"},idempotency_key=str(uuid4()))
        original=self.generation.run(**arguments)
        with create_sqlite_engine(self.database).begin() as connection:
            connection.execute(text("UPDATE synthetic_ai_sources SET revision='2' WHERE id='source'"))
        self.assertEqual(original,self.generation.run(**arguments))
        stale=self.generation.run(**{**arguments,"idempotency_key":str(uuid4())})
        self.assertEqual("blocked",stale["status"])
        self.assertEqual("ai_source_stale",stale["errorCode"])
        # Restore validates retained source evidence, not a mutable current
        # revision.  The original run remains historical evidence.
        with create_sqlite_engine(self.database).connect() as connection:
            validate_ai_governance_schema(connection,self.actions,self.profiles,self.adapters,source_validators={"synthetic":_SyntheticSource()})

    def test_provider_failure_never_retains_provider_text(self):
        class SensitiveFailure(AiProviderError):
            code="ai_provider_timeout"
            def __str__(self): return "Authorization: Bearer secret-token; HTTP body: private"
        self.provider.generate=lambda *args: (_ for _ in ()).throw(SensitiveFailure())
        result=self.generation.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"},idempotency_key=str(uuid4()))
        self.assertEqual("failed",result["status"])
        self.assertEqual("The AI provider timed out.",result["errorDetail"])
        self.assertNotIn("secret-token",result["errorDetail"])

    def test_tombstone_blocks_new_generation_but_preserves_retained_evidence(self):
        arguments=dict(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"})
        self.generation.run(**arguments,idempotency_key=str(uuid4()))
        with create_sqlite_engine(self.database).begin() as connection:
            connection.execute(text("UPDATE synthetic_ai_sources SET tombstoned=1 WHERE id='source'"))
        blocked=self.generation.run(**arguments,idempotency_key=str(uuid4()))
        self.assertEqual("ai_source_stale",blocked["errorCode"])
        with create_sqlite_engine(self.database).connect() as connection:
            validate_ai_governance_schema(connection,self.actions,self.profiles,self.adapters,source_validators={"synthetic":_SyntheticSource()})
    def test_dismissal_is_terminal_and_schema_stays_valid(self):
        result=self.generation.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe","private":"ignored"},idempotency_key=str(uuid4()))
        draft=result["draft"]; dismissed=self.drafts.dismiss_draft(draft["id"],version=1,operator_note="not applicable")
        self.assertEqual("dismissed",dismissed["status"])
        with self.assertRaises(AiConflictError): self.drafts.edit_draft(draft["id"],version=1,payload={"summary":"later"})
        with create_sqlite_engine(self.database).connect() as connection:
            validate_ai_governance_schema(connection,self.actions,self.profiles,self.adapters,source_validators={"synthetic":_SyntheticSource()})
    def test_value_error_from_output_validator_fails_the_run(self):
        self.provider.generate=lambda *args: AiProviderResult({"wrong":"shape"})
        result=self.generation.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe","private":"ignored"},idempotency_key=str(uuid4()))
        self.assertEqual("failed",result["status"])
        self.assertEqual("ai_output_invalid",result["errorCode"])

    def test_invalid_provider_metadata_is_not_persisted(self):
        self.provider.generate=lambda *args: AiProviderResult({"summary":"safe"},prompt_tokens=-1,provider_request_id="Bearer secret-token")
        result=self.generation.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"},idempotency_key=str(uuid4()))
        self.assertEqual("failed",result["status"])
        self.assertEqual("ai_output_invalid",result["errorCode"])

    def test_action_requires_adapter_capability_and_modality(self):
        action=AiActionDefinition("restricted","test",frozenset({"synthetic"}),("synthetic_profile",1),"synthetic",1,1,"synthetic",lambda value:None,lambda value:None,allowed_model_identities=frozenset({qualified_model_identity("synthetic","1","synthetic-model")}),required_capabilities=frozenset({"vision"}),required_input_modalities=frozenset({"image"}))
        self.generation.actions=AiActionRegistry((self.actions.require("synthetic_action"),action))
        result=self.generation.run(action_type="restricted",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"},idempotency_key=str(uuid4()))
        self.assertEqual("blocked",result["status"])
        self.assertEqual("ai_capability_not_allowed",result["errorCode"])

    def test_settings_replay_and_changed_reuse_are_durable(self):
        key=str(uuid4())
        connection_id=self.configuration.connections()[0]["id"]
        first=self.configuration.update_settings(kill_switch=False,default_connection_id=connection_id,idempotency_key=key)
        self.configuration.update_settings(kill_switch=True,idempotency_key=str(uuid4()))
        replay=self.configuration.update_settings(kill_switch=False,default_connection_id=connection_id,idempotency_key=key)
        self.assertEqual(first,replay)
        self.assertTrue(self.configuration.settings()["killSwitch"])
        with self.assertRaises(AiConflictError):
            self.configuration.update_settings(kill_switch=True,idempotency_key=key)

    def test_recovered_reservation_is_failed_without_transport_start(self):
        request_fingerprint=_operation_fingerprint({"action":"synthetic_action","source":"synthetic","sourceId":"source","sourceRevision":"1","sourceFingerprint":"a"*64,"governedInput":{"message":"safe"},"profile":("synthetic_profile",1),"supersedesDraftId":None})
        definition=self.actions.require("synthetic_action")
        reservation=AiRunReservation(
            definition=definition, governed_input_json='{"message":"safe"}',
            source_entity_type="synthetic", source_entity_id="source", source_revision="1",
            source_fingerprint="a"*64, idempotency_key=str(uuid4()),
            request_fingerprint=request_fingerprint, run_id=str(uuid4()), correlation_id=str(uuid4()),
            created_at=datetime.now(UTC).isoformat(),
        )
        result=self.unit_of_work.write(lambda tx: self.generation._reserve(
            tx, reservation, self.generation._preflight(definition,{"message":"safe"}),
        ))
        self.assertEqual("reserved",result["status"])
        self.assertEqual(1,self.generation.recover_interrupted())
        row=self.unit_of_work.run_row(result["id"])
        self.assertEqual("failed",row["status"]); self.assertIsNone(row["started_at"])
        with create_sqlite_engine(self.database).connect() as connection:
            validate_ai_governance_schema(connection,self.actions,self.profiles,self.adapters,source_validators={"synthetic":_SyntheticSource()})

    def test_successful_retry_supersedes_its_predecessor_atomically(self):
        base=dict(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"})
        original=self.generation.run(**base,idempotency_key=str(uuid4()))
        replacement=self.generation.run(**base,idempotency_key=str(uuid4()),supersedes_draft_id=original["draft"]["id"])
        predecessor=self.drafts.draft_detail(original["draft"]["id"])
        self.assertEqual("superseded",predecessor["status"])
        self.assertEqual("proposed",replacement["draft"]["status"])
        with create_sqlite_engine(self.database).connect() as connection:
            validate_ai_governance_schema(connection,self.actions,self.profiles,self.adapters,source_validators={"synthetic":_SyntheticSource()})

    def test_non_advisory_approval_keeps_domain_and_ai_evidence_in_one_transaction(self):
        result=self.generation.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"},idempotency_key=str(uuid4()))
        approved=self.drafts.approve_draft(result["draft"]["id"],version=1,operator_note="confirmed")
        self.assertEqual("approved",approved["status"])
        with create_sqlite_engine(self.database).connect() as connection:
            validate_ai_governance_schema(connection,self.actions,self.profiles,self.adapters,{"synthetic_action":_SyntheticApprovalEvidence()},{"synthetic":_SyntheticSource()})

    def test_stale_source_rejects_approval_without_a_terminal_review_write(self):
        result=self.generation.run(action_type="synthetic_action",source_entity_type="synthetic",source_entity_id="source",source_revision="1",source_fingerprint="a"*64,candidate={"message":"safe"},idempotency_key=str(uuid4()))
        with create_sqlite_engine(self.database).begin() as connection:
            connection.execute(text("UPDATE synthetic_ai_sources SET revision='2' WHERE id='source'"))
        with self.assertRaises(AiConflictError):
            self.drafts.approve_draft(result["draft"]["id"],version=1,operator_note="confirmed")
        detail=self.drafts.draft_detail(result["draft"]["id"])
        self.assertEqual("proposed",detail["status"])
        self.assertEqual([],detail["reviewHistory"])

    @fast_backup_encryption()
    def test_encrypted_backup_restores_all_governance_tables_without_credentials(self):
        root=Path(self.temp.name)/"portable"; config=LocalConfig(root/"config.json",root/"workspace",root/"backups")
        workspace=WorkspaceService(config); workspace.initialize()
        stamp="2026-01-02T12:00:00+00:00"; party_id=str(uuid4())
        with create_sqlite_engine(workspace.paths.database).begin() as connection:
            connection.execute(text("INSERT INTO parties (id,party_kind,display_name,created_at,updated_at,archived_at) VALUES (:id,'individual','Archive source',:stamp,:stamp,NULL)"),{"id":party_id,"stamp":stamp})
        action=AiActionDefinition("backup_action","test",frozenset({"party"}),("backup_profile",1),"backup",1,1,"backup",lambda value:None,lambda value:None,allowed_model_identities=frozenset({qualified_model_identity("backup","1","backup-model")}))
        profile=RedactionProfile("backup_profile",1,{"message":RedactionRule("allow")},{"message":"included"})
        actions=AiActionRegistry((action,)); profiles=RedactionProfileRegistry((profile,)); adapters=AiAdapterRegistry((AiAdapterDefinition("backup","1","on_device",frozenset({"backup-model"}),True),))
        credentials=_Credentials(); recorder=AuditRecorder(SQLiteAuditRepository(workspace.paths.database))
        service=_Services(SQLiteAiGovernanceUnitOfWork(workspace.paths.database,recorder,{"party":_PartySource()}),workspace_id="archive",actions=actions,profiles=profiles,adapters=adapters,providers={"backup":self.provider},credentials=credentials,source_projections={"party":_PartySource()})
        backup_configuration=service.configuration; backup_generation=service.generation; backup_drafts=service.drafts
        connection=backup_configuration.create_connection({"label":"Backup","adapter_id":"backup","adapter_version":"1","model_identifier":"backup-model","execution_location":"on_device","model_artifact_digest":"digest","quantization":"q","runtime_id":"runtime","runtime_version":"1"})
        connection_id=connection["id"]
        backup_configuration.set_credential(connection_id,"not-in-the-workspace")
        backup_configuration.update_settings(built_in_enabled=True,default_connection_id=connection_id,idempotency_key=str(uuid4()))
        backup_configuration.put_limit("backup_action",{"enabled":True,"connection_id":connection_id,"max_runs_per_utc_day":1,"max_prompt_tokens":10,"max_completion_tokens":10,"allowed_models":[qualified_model_identity("backup","1","backup-model")]})
        run=backup_generation.run(action_type="backup_action",source_entity_type="party",source_entity_id=party_id,source_revision=stamp,source_fingerprint="b"*64,candidate={"message":"archive"},idempotency_key=str(uuid4()))
        backup_drafts.dismiss_draft(run["draft"]["id"],version=1,operator_note="archived")
        with create_sqlite_engine(workspace.paths.database).connect() as connection:
            expected={
                "settings": dict(connection.execute(text("SELECT kill_switch,built_in_enabled,default_connection_id FROM ai_settings WHERE singleton=1")).mappings().one()),
                "limit": dict(connection.execute(text("SELECT action_type,connection_id,max_runs_per_utc_day,max_prompt_tokens,max_completion_tokens,allowed_models FROM ai_action_limits WHERE action_type='backup_action'")).mappings().one()),
                "run": dict(connection.execute(text("SELECT id,governed_input_json,correlation_id,request_fingerprint FROM ai_runs")).mappings().one()),
                "draft": dict(connection.execute(text("SELECT id,draft_payload,status,version,supersedes_draft_id FROM ai_drafts")).mappings().one()),
                "decision": dict(connection.execute(text("SELECT draft_id,decision,correlation_id,operator_note FROM ai_review_decisions")).mappings().one()),
            }
        import app.platform.product_migrations as migrations
        with patch.multiple(migrations,ACTION_REGISTRY=actions,REDACTION_PROFILE_REGISTRY=profiles,ADAPTER_REGISTRY=adapters,SOURCE_VALIDATORS={"party":_PartySource()},APPROVAL_EVIDENCE_VALIDATORS={}):
            backups=BackupService(workspace,recorder,lambda database:AuditRecorder(SQLiteAuditRepository(database)),MemorySecretStore())
            archive=backups.create_backup("a long test backup passphrase")
            restored=backups.restore(archive.archive_path,"a long test backup passphrase",root/"restored")
        with create_sqlite_engine(restored.workspace_path/"database"/"property-management.sqlite").connect() as connection:
            self.assertEqual(1,connection.execute(text("SELECT COUNT(*) FROM ai_settings")).scalar_one())
            self.assertEqual(1,connection.execute(text("SELECT COUNT(*) FROM ai_settings_operations")).scalar_one())
            self.assertEqual(1,connection.execute(text("SELECT COUNT(*) FROM ai_model_connections")).scalar_one())
            self.assertEqual(1,connection.execute(text("SELECT COUNT(*) FROM ai_action_limits")).scalar_one())
            self.assertEqual(1,connection.execute(text("SELECT COUNT(*) FROM ai_runs")).scalar_one())
            self.assertEqual(1,connection.execute(text("SELECT COUNT(*) FROM ai_drafts")).scalar_one())
            self.assertEqual(1,connection.execute(text("SELECT COUNT(*) FROM ai_review_decisions")).scalar_one())
            self.assertEqual(expected["settings"],dict(connection.execute(text("SELECT kill_switch,built_in_enabled,default_connection_id FROM ai_settings WHERE singleton=1")).mappings().one()))
            self.assertEqual(expected["limit"],dict(connection.execute(text("SELECT action_type,connection_id,max_runs_per_utc_day,max_prompt_tokens,max_completion_tokens,allowed_models FROM ai_action_limits WHERE action_type='backup_action'")).mappings().one()))
            self.assertEqual(expected["run"],dict(connection.execute(text("SELECT id,governed_input_json,correlation_id,request_fingerprint FROM ai_runs")).mappings().one()))
            self.assertEqual(expected["draft"],dict(connection.execute(text("SELECT id,draft_payload,status,version,supersedes_draft_id FROM ai_drafts")).mappings().one()))
            self.assertEqual(expected["decision"],dict(connection.execute(text("SELECT draft_id,decision,correlation_id,operator_note FROM ai_review_decisions")).mappings().one()))
        restored_service=_Services(SQLiteAiGovernanceUnitOfWork(restored.workspace_path/"database"/"property-management.sqlite",AuditRecorder(SQLiteAuditRepository(restored.workspace_path/"database"/"property-management.sqlite")),{"party":_PartySource()}),workspace_id="archive",actions=actions,profiles=profiles,adapters=adapters,providers={"backup":self.provider},credentials=_Credentials(),source_projections={"party":_PartySource()})
        self.assertEqual({"ready":False,"reason":"credential_unavailable"},restored_service.configuration.test_connection(connection_id))

"""Slice 38: real AI receipts, owning-transaction approval and portable OPS state."""

from dataclasses import dataclass
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from app.platform.testing_client import LocalApiClient as TestClient
from sqlalchemy import event, text

from app.bootstrap.operator_ai_commands import compose_ai_forms
from app.bootstrap.operator_recovery import OperatorRecoveryReferences, RecoverySourcePorts
from app.bootstrap.operator_recovery_composition import compose_recovery_bindings
from app.modules.ai_governance.api.router import build_router as ai_router
from app.modules.ai_governance.application.external_effects import AiExternalEffectService
from app.modules.ai_governance.application.service import (
    AiConfigurationService,
    AiDraftReviewService,
    AiGenerationCoordinator,
    AiAdapterDefinition,
    AiAdapterRegistry,
    AiModelSpecification,
)
from app.modules.ai_governance.domain.models import (
    AiActionDefinition,
    AiActionRegistry,
    RedactionProfile,
    RedactionProfileRegistry,
    RedactionRule,
    qualified_model_identity,
    AiConflictError,
)
from app.modules.ai_governance.infrastructure.recovery_reader import SQLiteAiRecoveryReader
from app.modules.ai_governance.infrastructure.unit_of_work import (
    SQLiteAiGovernanceUnitOfWork,
    AiGovernanceTransaction,
)
from app.modules.ai_governance.tests.test_governance import _PartySource, _Provider, _Credentials
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.operator.api.router import build_router
from app.modules.operator.application.ai_forms import AI_SCHEMAS, ai_source_kind
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.recovery_schemas import validate_payload
from app.modules.operator.application.service import OperatorService
from app.modules.operator.domain.models import OperatorConflict, OperatorError
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork
from app.modules.parties.application.service import (
    PartyIdentityService,
    PartyCreateCommand,
    PartyPatchCommand,
)
from app.modules.parties.infrastructure.unit_of_work import (
    SQLitePartyUnitOfWork,
    SQLitePartyOperations,
    SQLitePartyReadOperations,
)
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.tasks.application.service import TaskCreateCommand, new_task
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.api_errors import register_api_error_handlers
from app.platform.config import LocalConfig
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema


class TaskApproval:
    """Test-only registered owning handler using product-valid Party/Task records."""

    def __init__(self, uow, recorder):
        self.uow, self.recorder = uow, recorder

    def approve(self, context):
        def operation(tx):
            review = AiGovernanceTransaction(tx.connection, self.recorder).review_operations()
            prior = review.approval_replay(context)
            if prior is not None:
                return prior
            try:
                _PartySource().validate_current_source(
                    tx.connection,
                    source_entity_type=context.source_entity_type,
                    source_entity_id=context.source_entity_id,
                    source_revision=context.source_revision,
                    source_fingerprint=context.source_fingerprint,
                )
            except ValueError as error:
                raise AiConflictError("ai_source_stale") from error
            task = new_task(
                TaskCreateCommand.from_mapping({"title": context.draft_payload["summary"]})
            )
            tx.insert_task(task)
            tx.record_change(
                entity_type="task",
                entity_id=task.id,
                action="created",
                before=None,
                after=task.to_dict(),
                reason="task_created",
                correlation_id=context.correlation_id,
            )
            return review.complete_approval(
                draft_id=context.draft_id,
                expected_version=context.draft_version,
                result_entity_type="task",
                result_entity_id=task.id,
                operator_note=context.operator_note,
                command=context.command,
            )

        return self.uow.write(operation)


class TaskApprovalEvidence:
    def validate_approval_evidence(self, connection, *, action_type, decision, run):
        exists = connection.execute(
            text("SELECT 1 FROM tasks WHERE id=:id"), {"id": decision["result_entity_id"]}
        ).first()
        audit = connection.execute(
            text(
                "SELECT 1 FROM audit_events WHERE entity_type='task' AND entity_id=:id AND action='created' AND correlation_id=:correlation"
            ),
            {"id": decision["result_entity_id"], "correlation": run["correlation_id"]},
        ).first()
        if exists is None or audit is None:
            raise ValueError("Missing owning Task approval evidence.")


@dataclass
class Ready:
    workspace: object
    ops: OperatorService
    client: TestClient
    recorder: AuditRecorder
    uow: SQLiteAiGovernanceUnitOfWork
    configuration: AiConfigurationService
    generation: AiGenerationCoordinator
    drafts: AiDraftReviewService
    actions: AiActionRegistry
    party: dict
    identities: PartyIdentityService


@pytest.fixture
def ready(tmp_path):
    workspace = WorkspaceService(LocalConfig(tmp_path / "config.json", tmp_path / "workspace"))
    manifest = workspace.initialize()
    recorder = AuditRecorder(SQLiteAuditRepository(workspace.paths.database))
    party_uow = SQLitePartyUnitOfWork(workspace.paths.database, recorder)
    party_operations = SQLitePartyOperations(workspace.paths.database)
    identities = PartyIdentityService(party_uow, SQLitePartyReadOperations(party_operations))
    party = identities.create(
        PartyCreateCommand("individual", "AI source"),
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    identity = qualified_model_identity("test", "1", "test-model")
    actions = AiActionRegistry(
        (
            AiActionDefinition(
                "test_action",
                "tasks",
                frozenset({"party"}),
                ("test_profile", 1),
                "test",
                1,
                1,
                "task",
                lambda value: None,
                lambda value: None,
                allowed_model_identities=frozenset({identity}),
                approval_effect="create",
                requires_result_reference=True,
            ),
        )
    )
    profiles = RedactionProfileRegistry(
        (
            RedactionProfile(
                "test_profile", 1, {"message": RedactionRule("allow")}, {"message": "included"}
            ),
        )
    )
    adapters = AiAdapterRegistry(
        tuple(
            AiAdapterDefinition(
                name,
                "1",
                location,
                frozenset({"test-model"}),
                False,
                model_specs={"test-model": AiModelSpecification(16384, 4096)},
            )
            for name, location in (("test", "on_device"), ("cloud", "cloud"))
        )
    )
    uow = SQLiteAiGovernanceUnitOfWork(
        workspace.paths.database, recorder, {"party": _PartySource()}
    )
    credentials = _Credentials()
    provider = _Provider()
    configuration = AiConfigurationService(
        uow,
        workspace_id=manifest.workspace_id,
        actions=actions,
        adapters=adapters,
        providers={"test": provider, "cloud": provider},
        credentials=credentials,
    )
    generation = AiGenerationCoordinator(
        uow,
        workspace_id=manifest.workspace_id,
        actions=actions,
        profiles=profiles,
        adapters=adapters,
        providers={"test": provider, "cloud": provider},
        credentials=credentials,
    )
    task_uow = SQLiteTaskUnitOfWork(workspace.paths.database, recorder)
    drafts = AiDraftReviewService(
        uow,
        actions=actions,
        approval_handlers={"test_action": TaskApproval(task_uow, recorder)},
        source_projections={"party": _PartySource()},
    )
    bindings = compose_recovery_bindings() | compose_ai_forms(actions)
    references = OperatorRecoveryReferences(
        RecoverySourcePorts(SQLitePortfolioContextReader(), None, None),
        None,
        None,
        None,
        commands=bindings,
    )
    ops_uow = SQLiteOperatorUnitOfWork(
        workspace.paths.database, recorder, references, SQLiteAuditReadMarker()
    )
    writer_id = str(uuid4())
    ops = OperatorService(
        ops_uow, runtime=lambda: RuntimeIdentity("ready", manifest.workspace_id, writer_id, True)
    )
    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_router(ops))
    app.include_router(
        ai_router(
            configuration,
            generation,
            drafts,
            SimpleNamespace(ready=True, error=None, can_write=True),
            AiExternalEffectService(
                uow,
                workspace_id=manifest.workspace_id,
                adapters=adapters,
                providers={"test": provider, "cloud": provider},
                credentials=credentials,
            ),
        )
    )
    import app.platform.product_migrations as migrations

    with (
        patch.multiple(
            migrations,
            ACTION_REGISTRY=actions,
            REDACTION_PROFILE_REGISTRY=profiles,
            ADAPTER_REGISTRY=adapters,
            SOURCE_VALIDATORS={"party": _PartySource()},
            APPROVAL_EVIDENCE_VALIDATORS={"test_action": TaskApprovalEvidence()},
        ),
        TestClient(app) as client,
    ):
        yield Ready(
            workspace,
            ops,
            client,
            recorder,
            uow,
            configuration,
            generation,
            drafts,
            actions,
            party,
            identities,
        )
    for engine in (
        uow.engine,
        party_uow.engine,
        party_operations.engine,
        ops_uow.engine,
        task_uow.engine,
    ):
        engine.dispose()


def begin(ready, form, values, source=None):
    record, key = str(uuid4()), str(uuid4())
    response = ready.client.put(
        f"/api/operator/recovery/{record}",
        json={
            "formKey": form,
            "schemaVersion": 1,
            "payload": values,
            "expectedRevision": 0,
            "idempotencyKey": str(uuid4()),
            "sourceKind": ai_source_kind(form),
            "sourceId": source,
            "baseSourceRevision": str(values.get("expectedRevision", values.get("version")))
            if source
            else None,
        },
    )
    if response.status_code == 409:
        raise OperatorConflict(response.json()["detail"]["message"])
    assert response.status_code == 200, response.text
    ready.ops.prepare_attempt(
        record, attempt_key=key, expected_revision=1, idempotency_key=str(uuid4())
    )
    return record, key


def run(ready, form, method, path, values, source=None):
    record, key = begin(ready, form, values, source)
    with pytest.raises(OperatorConflict):
        ready.ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    body = values | {"idempotencyKey": key}
    response = ready.client.request(method, path, json=body)
    assert response.status_code in {200, 201}, response.text
    original = response.json()
    result = ready.ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    receipt = result["receipt"]
    assert receipt["receiptId"] == original["operationId"]
    assert receipt["attemptKey"] == key
    assert receipt["sourceId"] == (source or original["id"])
    assert receipt["result"]["targetId"] == receipt["sourceId"]
    assert receipt["sourceKind"] == (ai_source_kind(form) or "ai_connection")
    assert receipt["result"]["revision"] == original.get("revision", original.get("version"))
    assert receipt["result"]["status"] == original.get("status")
    assert ready.client.get(f"/api/operator/recovery/{record}").status_code == 200
    assert ready.client.request(method, path, json=body).json() == original
    return original, record, key


def connection(ready, cloud=False):
    return run(
        ready,
        "ai.connection.create",
        "POST",
        "/api/ai/connections",
        {
            "expectedRevision": 0,
            "label": " Test ",
            "adapterId": "cloud" if cloud else "test",
            "adapterVersion": "1",
            "modelIdentifier": "test-model",
            "executionLocation": "cloud" if cloud else "on_device",
            **(
                {}
                if cloud
                else {
                    "modelArtifactDigest": "digest",
                    "quantization": "q",
                    "runtimeId": "test",
                    "runtimeVersion": "1",
                }
            ),
        },
    )


def draft(ready):
    if not ready.configuration.settings()["defaultConnectionId"]:
        result, _, _ = connection(ready)
        revision = ready.configuration.settings()["revision"]
        run(
            ready,
            "ai.settings.update",
            "PUT",
            "/api/ai/settings",
            {
                "expectedRevision": revision,
                "defaultConnectionId": result["id"],
                "builtInEnabled": True,
            },
            "1",
        )
    return ready.generation.run(
        action_type="test_action",
        source_entity_type="party",
        source_entity_id=ready.party["id"],
        source_revision=ready.party["updatedAt"],
        source_fingerprint="b" * 64,
        candidate={"message": "Suggested task"},
        idempotency_key=str(uuid4()),
    )["draft"]["id"]


def exercise_configuration(ready):
    original, record, key = connection(ready)
    run(
        ready,
        "ai.connection.update",
        "PATCH",
        f"/api/ai/connections/{original['id']}",
        {"expectedRevision": 1, "label": " Later "},
        original["id"],
    )
    run(
        ready,
        "ai.connection.update",
        "PATCH",
        f"/api/ai/connections/{original['id']}",
        {"expectedRevision": 2, "label": "Later"},
        original["id"],
    )
    cloud, _, _ = connection(ready, cloud=True)
    run(
        ready,
        "ai.connection.disclosure",
        "PUT",
        f"/api/ai/connections/{cloud['id']}/disclosure",
        {
            "expectedRevision": 1,
            "disclosureVersion": "v1",
            "dataClasses": ["notes", "notes", "names"],
        },
        cloud["id"],
    )
    settings, _, _ = run(
        ready,
        "ai.settings.update",
        "PUT",
        "/api/ai/settings",
        {"expectedRevision": 1, "defaultConnectionId": original["id"], "builtInEnabled": True},
        "1",
    )
    run(
        ready,
        "ai.settings.update",
        "PUT",
        "/api/ai/settings",
        {"expectedRevision": settings["revision"], "defaultConnectionId": None},
        "1",
    )
    run(
        ready,
        "ai.action_limit.update",
        "PUT",
        "/api/ai/limits/test_action",
        {
            "expectedRevision": 0,
            "enabled": True,
            "connectionId": original["id"],
            "maxRunsPerUtcDay": 5,
            "maxPromptTokens": 100,
            "maxCompletionTokens": 100,
            "allowedModels": [qualified_model_identity("test", "1", "test-model")],
        },
        "test_action",
    )
    assert ready.client.get(f"/api/ai/command-operations/by-key/{key}").json()["result"] == original
    assert ready.ops.recovery(record)["receipt"]["result"]["revision"] == 1
    validate_latest_schema(ready.workspace.paths.database)


def test_configuration_forms_and_original_metadata(ready):
    exercise_configuration(ready)


def test_draft_review_original_approval_and_audits(ready):
    target = draft(ready)
    edited, _, edit_key = run(
        ready,
        "ai.draft.edit",
        "PATCH",
        f"/api/ai/drafts/{target}",
        {"version": 1, "draftPayload": {"summary": "Edit"}, "operatorNote": "Context"},
        target,
    )
    approved, _, _ = run(
        ready,
        "ai.draft.approve",
        "POST",
        f"/api/ai/drafts/{target}/approve",
        {"version": 2, "operatorNote": "Approved"},
        target,
    )
    assert approved["resultEntityType"] == "task"
    assert (
        ready.client.get(f"/api/ai/command-operations/by-key/{edit_key}").json()["result"] == edited
    )
    other = draft(ready)
    run(
        ready,
        "ai.draft.dismiss",
        "POST",
        f"/api/ai/drafts/{other}/dismiss",
        {"version": 1, "operatorNote": "Not needed"},
        other,
    )
    with ready.uow.engine.connect() as c:
        correlation = c.exec_driver_sql(
            "SELECT correlation_id FROM ai_command_operations WHERE id=?",
            (approved["operationId"],),
        ).scalar_one()
        types = set(
            c.exec_driver_sql(
                "SELECT entity_type FROM audit_events WHERE correlation_id=?", (correlation,)
            ).scalars()
        )
    assert {"task", "ai_draft", "ai_review_decision", "ai_command_operation"} <= types
    validate_latest_schema(ready.workspace.paths.database)


def test_owning_approval_rollback_and_unknown_attempt(ready):
    target = draft(ready)
    record, key = begin(ready, "ai.draft.approve", {"version": 1}, target)
    before = portable_rows(ready.workspace.paths.database)
    with patch.object(
        AiGovernanceTransaction, "insert_command", side_effect=RuntimeError("receipt failure")
    ):
        with pytest.raises(RuntimeError, match="receipt failure"):
            ready.client.post(
                f"/api/ai/drafts/{target}/approve", json={"version": 1, "idempotencyKey": key}
            )
    assert portable_rows(ready.workspace.paths.database) == before
    with pytest.raises(OperatorConflict):
        ready.ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    response = ready.client.post(
        f"/api/ai/drafts/{target}/approve", json={"version": 1, "idempotencyKey": key}
    )
    assert response.status_code == 200, response.text
    assert (
        ready.ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))[
            "receipt"
        ]["receiptId"]
        == response.json()["operationId"]
    )


def portable_rows(database):
    with sqlite3.connect(database) as c:
        rows = {
            table: c.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in (
                "ai_settings",
                "ai_model_connections",
                "ai_action_limits",
                "ai_runs",
                "ai_drafts",
                "ai_review_decisions",
                "ai_command_operations",
                "ai_external_operations",
                "tasks",
                "operator_recovery_records",
                "operator_operations",
            )
        }
        rows["audit_events"] = c.execute(
            "SELECT * FROM audit_events WHERE entity_type LIKE 'ai_%' OR entity_type LIKE 'task%' OR entity_type LIKE 'operator%' ORDER BY rowid"
        ).fetchall()
        return rows


def test_indexed_receipts_encrypted_restore_and_tampering(ready, tmp_path):
    exercise_configuration(ready)
    exercise_external_effects(ready)
    external_target = ready.configuration.connections()[0]
    unknown_values = {"expectedRevision": external_target["revision"]}
    unknown_record, unknown_key = begin(
        ready, "ai.connection.probe", unknown_values, external_target["id"]
    )
    with patch.object(
        ready.configuration.providers["test"], "probe", side_effect=TimeoutError("not retained")
    ):
        unknown_response = ready.client.post(
            f"/api/ai/connections/{external_target['id']}/test",
            json={**unknown_values, "idempotencyKey": unknown_key},
        )
    assert unknown_response.json()["status"] == "outcome_unknown"
    target = draft(ready)
    run(
        ready,
        "ai.draft.edit",
        "PATCH",
        f"/api/ai/drafts/{target}",
        {"version": 1, "draftPayload": {"summary": "Edited"}},
        target,
    )
    original, record, key = run(
        ready,
        "ai.draft.approve",
        "POST",
        f"/api/ai/drafts/{target}/approve",
        {"version": 2},
        target,
    )
    other = draft(ready)
    run(ready, "ai.draft.dismiss", "POST", f"/api/ai/drafts/{other}/dismiss", {"version": 1}, other)
    statements = []

    def capture(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    with ready.uow.engine.connect() as c:
        event.listen(ready.uow.engine, "before_cursor_execute", capture)
        try:
            with patch.object(
                ready.uow.engine, "connect", side_effect=AssertionError("nested connection")
            ):
                result = SQLiteAiRecoveryReader("ai_draft", ready.actions).outcome(
                    c, key, family="ai"
                )
            assert len(statements) == 1
            assert (
                result.result.status == "approved"
                and result.operation_id == original["operationId"]
            )
        finally:
            event.remove(ready.uow.engine, "before_cursor_execute", capture)
    before = portable_rows(ready.workspace.paths.database)
    backup = BackupService(
        ready.workspace,
        ready.recorder,
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    with fast_backup_encryption():
        archive = backup.create_backup(
            "a sufficiently long passphrase", output_path=tmp_path / "ai.epm-backup"
        )
        backup.restore(
            archive.archive_path, "a sufficiently long passphrase", tmp_path / "restored"
        )
    restored = tmp_path / "restored/database/property-management.sqlite"
    validate_latest_schema(restored)
    assert portable_rows(restored) == before
    restored_uow = SQLiteAiGovernanceUnitOfWork(restored, ready.recorder)
    restored_external = AiExternalEffectService(
        restored_uow,
        workspace_id="new-device",
        adapters=ready.configuration.adapters,
        providers={},
        credentials=_Credentials(),
    )
    with sqlite3.connect(restored) as c:
        operation_id = c.execute("SELECT id FROM ai_external_operations LIMIT 1").fetchone()[0]
    assert restored_external.receipt(operation_id=operation_id)["requiresDeviceValidation"] is True
    assert restored_external.receipt(key=unknown_key)["status"] == "outcome_unknown"
    # A restored retry is an original intent read, not another device effect.
    assert (
        restored_external.execute(
            "connection_probe",
            external_target["id"],
            expected_revision=unknown_values["expectedRevision"],
            idempotency_key=unknown_key,
        )["status"]
        == "outcome_unknown"
    )
    restored_uow.engine.dispose()
    with sqlite3.connect(restored) as c:
        c.execute(
            "UPDATE operator_recovery_records SET request_fingerprint=? WHERE id=?",
            ("0" * 64, record),
        )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(restored)


def test_external_recovery_is_one_indexed_caller_connection_read(ready):
    exercise_external_effects(ready)
    with ready.uow.engine.connect() as c:
        key = c.exec_driver_sql(
            "SELECT idempotency_key FROM ai_external_operations WHERE action='credential_set'"
        ).scalar_one()
        queries = []

        def capture(connection, cursor, statement, parameters, context, many):
            if statement.lstrip().upper().startswith("SELECT"):
                queries.append(statement)

        event.listen(ready.uow.engine, "before_cursor_execute", capture)
        try:
            with patch.object(
                ready.uow.engine, "connect", side_effect=AssertionError("nested connection")
            ):
                outcome = SQLiteAiRecoveryReader("ai_connection", ready.actions).outcome(
                    c, key, family="ai_external"
                )
            assert len(queries) == 1
            assert outcome.result.status == "completed" and outcome.result.revision == 2
        finally:
            event.remove(ready.uow.engine, "before_cursor_execute", capture)


def test_external_http_contract_requires_metadata_and_forbids_secret_ops_payload(ready):
    connection(ready)
    target = ready.configuration.connections()[0]
    path = f"/api/ai/connections/{target['id']}"
    assert ready.client.post(path + "/test").status_code == 422
    assert ready.client.put(path + "/credential", json={"credential": "secret"}).status_code == 422
    assert ready.client.request("DELETE", path + "/credential").status_code == 422
    assert (
        ready.client.post(
            path + "/test", json={"expectedRevision": True, "idempotencyKey": str(uuid4())}
        ).status_code
        == 422
    )
    with pytest.raises(OperatorError):
        validate_payload(
            "ai.connection.credential.set", 1, {"expectedRevision": 1, "credential": "secret"}
        )
    schema = ready.client.app.openapi()
    for suffix, method, operation_id in (
        ("credential", "put", "setAiCredential"),
        ("credential", "delete", "deleteAiCredential"),
        ("test", "post", "testAiConnection"),
    ):
        operation = schema["paths"]["/api/ai/connections/{connection_id}/" + suffix][method]
        assert operation["operationId"] == operation_id
        assert operation["requestBody"]["required"]
        assert "409" in operation["responses"]
    with ready.uow.engine.connect() as c:
        assert c.exec_driver_sql("SELECT count(*) FROM ai_external_operations").scalar_one() == 0


def exercise_external_effects(ready):
    if not ready.configuration.connections():
        connection(ready)
    target = ready.configuration.connections()[0]
    values = {"expectedRevision": target["revision"]}
    record, key = begin(ready, "ai.connection.credential.set", values, target["id"])
    body = {**values, "idempotencyKey": key, "credential": "write-only-secret"}
    first = ready.client.put(f"/api/ai/connections/{target['id']}/credential", json=body)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "completed"
    result = ready.ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    assert result["receipt"]["receiptId"] == first.json()["operationId"]
    assert (
        ready.client.put(f"/api/ai/connections/{target['id']}/credential", json=body).json()
        == first.json()
    )
    for form, method, suffix in (
        ("ai.connection.credential.delete", "DELETE", "credential"),
        ("ai.connection.probe", "POST", "test"),
    ):
        values = {"expectedRevision": ready.configuration.connections()[0]["revision"]}
        run(
            ready,
            form,
            method,
            f"/api/ai/connections/{target['id']}/{suffix}",
            values,
            target["id"],
        )
    with sqlite3.connect(ready.workspace.paths.database) as c:
        retained = c.execute("SELECT payload_json FROM operator_recovery_records").fetchall()
        assert "write-only-secret" not in str(retained)


def test_external_recovery_and_unknown_acknowledgement(ready):
    exercise_external_effects(ready)
    target = ready.configuration.connections()[0]
    values = {"expectedRevision": target["revision"]}
    record, key = begin(ready, "ai.connection.probe", values, target["id"])
    with patch.object(
        ready.configuration.providers["test"],
        "probe",
        side_effect=TimeoutError("secret transport error"),
    ) as probe:
        response = ready.client.post(
            f"/api/ai/connections/{target['id']}/test", json={**values, "idempotencyKey": key}
        )
        assert response.json()["status"] == "outcome_unknown"
        assert (
            ready.client.post(
                f"/api/ai/connections/{target['id']}/test", json={**values, "idempotencyKey": key}
            ).json()
            == response.json()
        )
        assert probe.call_count == 1
    with pytest.raises(OperatorConflict):
        ready.ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    acknowledgement = ready.client.post(
        f"/api/ai/external-operations/{response.json()['operationId']}/acknowledge-unknown",
        json={"acknowledgeUnknownOutcome": True},
    )
    assert acknowledgement.status_code == 200, acknowledgement.text
    result = ready.ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    assert result["receipt"]["result"]["status"] == "abandoned"
    validate_latest_schema(ready.workspace.paths.database)


@pytest.mark.parametrize(
    "form,payload",
    [
        ("settings.update", {"expectedRevision": True}),
        ("connection.create", {"label": "x" * 121}),
        ("connection.update", {"credential": "secret"}),
        ("action_limit.update", {"allowedModels": ["x"] * 101}),
        ("draft.edit", {"version": "1"}),
        ("draft.approve", {"operatorNote": "x" * 1001}),
    ],
)
def test_invalid_typed_forms(form, payload):
    with pytest.raises(OperatorError):
        validate_payload("ai." + form, 1, payload)


def test_stale_revisions_terminal_drafts_and_source_freshness(ready):
    target = draft(ready)
    run(
        ready,
        "ai.draft.edit",
        "PATCH",
        f"/api/ai/drafts/{target}",
        {"version": 1, "draftPayload": {"summary": "Edit"}},
        target,
    )
    with pytest.raises(OperatorConflict):
        begin(ready, "ai.draft.approve", {"version": 1}, target)
    record, key = begin(ready, "ai.draft.approve", {"version": 2}, target)
    ready.identities.patch(
        ready.party["id"],
        PartyPatchCommand("Changed source"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    before = portable_rows(ready.workspace.paths.database)
    response = ready.client.post(
        f"/api/ai/drafts/{target}/approve", json={"version": 2, "idempotencyKey": key}
    )
    assert response.status_code == 409
    assert portable_rows(ready.workspace.paths.database) == before
    with pytest.raises(OperatorConflict):
        ready.ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    run(
        ready,
        "ai.draft.dismiss",
        "POST",
        f"/api/ai/drafts/{target}/dismiss",
        {"version": 2},
        target,
    )
    with pytest.raises(OperatorConflict):
        begin(ready, "ai.draft.approve", {"version": 2}, target)


def test_settings_presence_is_part_of_fingerprint(ready):
    record, key = begin(ready, "ai.settings.update", {"expectedRevision": 1}, "1")
    response = ready.client.put(
        "/api/ai/settings",
        json={"expectedRevision": 1, "defaultConnectionId": None, "idempotencyKey": key},
    )
    assert response.status_code == 200
    with pytest.raises(OperatorConflict):
        ready.ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    assert ready.ops.recovery(record)["reuseState"] == "outcome_unknown"


@pytest.mark.parametrize(
    "form,values",
    [
        ("ai.connection.create", {"expectedRevision": 0}),
        ("ai.draft.edit", {"version": 1}),
        ("ai.connection.disclosure", {"expectedRevision": 1}),
    ],
)
def test_incomplete_forms_cannot_prepare(ready, form, values):
    source = None
    if form == "ai.draft.edit":
        source = draft(ready)
    elif form == "ai.connection.disclosure":
        source = connection(ready, cloud=True)[0]["id"]
    with pytest.raises(OperatorError):
        begin(ready, form, values, source)


@pytest.mark.parametrize(
    "kind,source",
    [("ai_settings", "2"), ("ai_action_limit", "Bad Action"), ("task", "test_action")],
)
def test_identity_contract_does_not_relax_other_sources(ready, kind, source):
    response = ready.client.put(
        f"/api/operator/recovery/{uuid4()}",
        json={
            "formKey": "ai.settings.update",
            "schemaVersion": 1,
            "payload": {},
            "expectedRevision": 0,
            "idempotencyKey": str(uuid4()),
            "sourceKind": kind,
            "sourceId": source,
        },
    )
    assert response.status_code == 422


def test_no_workspace_openapi_and_closed_scope():
    first, second = FastAPI(), FastAPI()
    for app in (first, second):
        app.include_router(build_router(None))
        app.include_router(ai_router(None, None, None, None, None))
    assert first.openapi() == second.openapi()
    assert len(AI_SCHEMAS) == 11 and set(AI_SCHEMAS) <= set(compose_recovery_bindings())
    assert "ai.generate" not in AI_SCHEMAS
    schema = first.openapi()
    models = schema["components"]["schemas"]
    selected = {
        "updateAiSettings",
        "createAiConnection",
        "updateAiConnection",
        "recordAiDisclosure",
        "updateAiActionLimit",
        "editAiDraft",
        "approveAiDraft",
        "dismissAiDraft",
    }
    operations = [
        operation
        for methods in schema["paths"].values()
        for operation in methods.values()
        if operation.get("operationId") in selected
    ]
    assert len(operations) == 8
    for operation in operations:
        assert "409" in operation["responses"]
        request = models[
            operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
        ]
        assert "idempotencyKey" in request["required"]
        assert {"version", "expectedRevision"} & set(request["required"])

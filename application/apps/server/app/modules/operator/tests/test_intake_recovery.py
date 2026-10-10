"""Slice 32: real Intake receipts, attachment replay and bounded OPS recovery."""

import hashlib
import json
import sqlite3
from unittest.mock import patch
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from app.platform.testing_client import LocalApiClient as TestClient
from sqlalchemy import event

from app.bootstrap.operator_recovery import OperatorRecoveryReferences, RecoverySourcePorts
from app.bootstrap.operator_recovery_composition import compose_recovery_bindings
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.application.service import FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.modules.files.infrastructure.file_link_reader import SQLiteFileLinkReader
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.intake.application.file_links import IntakeSourceFileLinkValidator
from app.modules.intake.api.router import build_router as build_intake_router
from app.modules.intake.application.service import (
    AttachmentInput,
    IntakeAdmissionCommand,
    IntakeService,
)
from app.modules.intake.domain.models import EvidenceEnvelope
from app.modules.intake.infrastructure.attention_operations import SQLiteIntakeAttentionOperations
from app.modules.intake.infrastructure.source_reader import SQLiteIntakeSourceReader
from app.modules.intake.infrastructure.unit_of_work import SQLiteIntakeUnitOfWork
from app.modules.intake.infrastructure.recovery_reader import SQLiteIntakeRecoveryReader
from app.modules.operator.api.router import build_router
from app.modules.operator.application.intake_forms import INTAKE_SCHEMAS
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.service import OperatorService
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.api_errors import register_api_error_handlers
from app.platform.config import LocalConfig
from app.platform.product_migrations import validate_latest_schema
from app.platform.migration_errors import MigrationSchemaError
from app.platform.sqlite_engine import create_sqlite_engine


@pytest.fixture
def ready(tmp_path):
    workspace = WorkspaceService(LocalConfig(tmp_path / "config.json", tmp_path / "workspace"))
    manifest = workspace.initialize()
    recorder = AuditRecorder(SQLiteAuditRepository(workspace.paths.database))
    store = FilesystemContentStore(workspace.paths.files)
    files = FileService(
        workspace,
        store,
        SQLiteFileUnitOfWork(workspace.paths.database, recorder),
        link_validators=(IntakeSourceFileLinkValidator(),),
    )
    intake_uow = SQLiteIntakeUnitOfWork(workspace.paths.database, recorder, SQLiteFileLinkReader())
    intake = IntakeService(
        intake_uow,
        files,
        attention_operations=SQLiteIntakeAttentionOperations(recorder, SQLiteIntakeSourceReader()),
    )
    references = OperatorRecoveryReferences(
        RecoverySourcePorts(SQLitePortfolioContextReader(), None, None),
        None,
        None,
        None,
        commands=compose_recovery_bindings(),
    )
    ops_uow = SQLiteOperatorUnitOfWork(
        workspace.paths.database, recorder, references, SQLiteAuditReadMarker()
    )
    ops = OperatorService(
        ops_uow, runtime=lambda: RuntimeIdentity("ready", manifest.workspace_id, str(uuid4()), True)
    )
    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_router(ops))
    app.include_router(
        build_intake_router(intake, SimpleNamespace(ready=True, error=None, can_write=True))
    )
    with TestClient(app) as client:
        yield workspace, intake, ops, client, store
    intake_uow.engine.dispose()
    ops_uow.engine.dispose()


def evidence(body="Evidence"):
    return EvidenceEnvelope("operator_note", "internal", body, "2026-01-01T12:00:00-05:00")


def payload(envelope):
    return {
        "expectedRevision": 0,
        "sourceKind": envelope.source_kind,
        "channel": envelope.channel,
        "body": envelope.body,
        "occurredAtUtc": envelope.occurred_at_context,
        "originSystem": "manual",
    }


def save(client, form, values, source=None):
    record = str(uuid4())
    response = client.put(
        "/api/operator/recovery/" + record,
        json={
            "formKey": form,
            "schemaVersion": 1,
            "payload": values,
            "expectedRevision": 0,
            "idempotencyKey": str(uuid4()),
            "sourceKind": "intake_source" if source else None,
            "sourceId": source["sourceId"] if source else None,
            "baseSourceRevision": str(source["sourceRevision"]) if source else None,
        },
    )
    return record, response


def prepare(client, record, key):
    return client.post(
        "/api/operator/recovery/" + record + "/attempt",
        json={
            "attemptKey": key,
            "expectedRevision": 1,
            "idempotencyKey": str(uuid4()),
        },
    )


def reconcile(client, record):
    return client.post(
        "/api/operator/recovery/" + record + "/reconcile",
        json={
            "expectedRevision": 2,
            "idempotencyKey": str(uuid4()),
        },
    )


@pytest.mark.parametrize("action", ["admit", "import", "correct", "supersede", "dismiss", "reopen"])
def test_all_six_commands_reconcile_original_receipts_after_later_mutations(
    ready, tmp_path, action
):
    workspace, intake, _, client, store = ready
    original = evidence()
    values = payload(original)
    attachments = ()
    source = None
    if action in {"correct", "supersede", "dismiss", "reopen"}:
        initial_attachments = ()
        if action == "correct":
            path = tmp_path / "original.txt"
            path.write_bytes(b"retained correction attachment")
            initial_attachments = (AttachmentInput(path, "original.txt", "text/plain"),)
        source = intake.admit(
            IntakeAdmissionCommand(original, "manual", str(uuid4()), initial_attachments)
        )
        if action == "reopen":
            source = intake.attention(
                source["sourceId"],
                target="dismissed",
                reason="reviewed",
                idempotency_key=str(uuid4()),
                expected_revision=source["revision"],
                expected_source_revision=source["sourceRevision"],
                expected_status="unprocessed",
            )
        values.update(
            expectedRevision=source["sourceRevision"], expectedEvidenceRevisionId=source["revision"]
        )
    if action in {"dismiss", "reopen"}:
        values = {
            "expectedRevision": source["sourceRevision"],
            "expectedEvidenceRevisionId": source["revision"],
            "expectedStatus": source["attentionStatus"],
            "reason": "reviewed",
        }
    if action == "correct":
        original = evidence("Corrected evidence")
        values.update(body=original.body, correctionReason="clarified")
    if action == "import":
        path = tmp_path / "evidence.txt"
        path.write_bytes(b"exact attachment")
        attachments = (AttachmentInput(path, "evidence.txt", "text/plain", "raw_source"),)
        values["attachments"] = [
            {"role": "raw_source", "contentSha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        ]
    record, saved = save(client, "intake.source." + action, values, source)
    assert saved.status_code == 200, saved.text
    key = str(uuid4())
    attempt = prepare(client, record, key)
    assert attempt.status_code == 200, attempt.text
    unknown = reconcile(client, record)
    assert unknown.status_code == 409
    command = IntakeAdmissionCommand(original, "manual", key, attachments)
    if action == "correct":
        result = intake.correct(
            source["sourceId"],
            original,
            "clarified",
            key,
            expected_source_revision=source["sourceRevision"],
            expected_evidence_revision_id=source["revision"],
        )
    elif action == "supersede":
        result = intake.supersede(
            source["sourceId"],
            command,
            expected_source_revision=source["sourceRevision"],
            expected_evidence_revision_id=source["revision"],
        )
    elif action in {"dismiss", "reopen"}:
        result = intake.attention(
            source["sourceId"],
            target="dismissed" if action == "dismiss" else "unprocessed",
            reason="reviewed",
            idempotency_key=key,
            expected_revision=source["revision"],
            expected_source_revision=source["sourceRevision"],
            expected_status=source["attentionStatus"],
        )
    else:
        result = intake.admit(command)
    assert intake.receipt_by_key(key) == result
    intake.correct(
        result["sourceId"],
        evidence("Later evidence"),
        "later",
        str(uuid4()),
        expected_source_revision=result["sourceRevision"],
        expected_evidence_revision_id=result["revision"],
    )
    with patch.object(store, "store", side_effect=AssertionError("Recovery must not publish")):
        recovered = reconcile(client, record)
    assert recovered.status_code == 200, recovered.text
    receipt = recovered.json()["receipt"]
    assert receipt["result"] == {
        "targetId": result["sourceId"],
        "revision": result["sourceRevision"],
        "status": result["technicalStatus"],
        "operationId": result["operationId"],
        "evidenceRevisionId": result["revision"],
    }
    assert "body" not in json.dumps(receipt)
    validate_latest_schema(workspace.paths.database)


@pytest.mark.parametrize(
    "field,value",
    [
        ("expectedRevision", 99),
        ("expectedEvidenceRevisionId", "00000000-0000-0000-0000-000000000001"),
        ("expectedStatus", "dismissed"),
    ],
)
def test_stale_attention_guards_reject_saved_forms(ready, field, value):
    _, intake, _, client, _ = ready
    source = intake.admit(IntakeAdmissionCommand(evidence(), "manual", str(uuid4())))
    values = {
        "expectedRevision": source["sourceRevision"],
        "expectedEvidenceRevisionId": source["revision"],
        "expectedStatus": "unprocessed",
        "reason": "reviewed",
    }
    values[field] = value
    _, response = save(client, "intake.source.dismiss", values, source)
    assert response.status_code == 409


@pytest.mark.parametrize(
    "values",
    [
        {"expectedRevision": True},
        {"attachments": [{"role": "raw_source", "contentSha256": "bad"}]},
        {"attachments": [], "path": "/private/evidence"},
        {"occurredAtUtc": "2026-01-01T12:00:00"},
    ],
)
def test_malformed_imports_are_not_saved(ready, values):
    _, _, _, client, _ = ready
    _, response = save(client, "intake.source.import", values)
    assert response.status_code == 422, response.text


def test_incomplete_forms_autosave_but_cannot_begin_attempt(ready):
    _, _, _, client, _ = ready
    record, saved = save(client, "intake.source.admit", {"body": "Work in progress"})
    assert saved.status_code == 200
    assert prepare(client, record, str(uuid4())).status_code == 422


def test_receipt_lookup_uses_one_select_without_new_connection(ready):
    _, intake, _, _, _ = ready
    command = IntakeAdmissionCommand(evidence(), "manual", str(uuid4()))
    result = intake.admit(command)
    statements = []
    engine = intake.unit_of_work.engine

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    with engine.connect() as connection:
        event.listen(engine, "before_cursor_execute", capture)
        try:
            with patch.object(engine, "connect", side_effect=AssertionError("Nested connection")):
                outcome = SQLiteIntakeRecoveryReader().outcome(
                    connection, command.idempotency_key, family="intake"
                )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert outcome.result.evidence_revision_id == result["revision"]


def test_registration_is_deterministic_without_workspace():
    app = FastAPI()
    app.include_router(build_router(None))
    assert app.openapi() == app.openapi()
    assert set(INTAKE_SCHEMAS) <= set(compose_recovery_bindings())


def test_http_admission_fingerprint_preserves_offset_and_nullable_participants(ready):
    _, _, _, client, _ = ready
    values = payload(evidence()) | {
        "occurredAtUtc": "2026-01-01T12:00:00Z",
        "participants": [{"role": "reporter", "display": "Reporter", "address": None}],
    }
    record, saved = save(client, "intake.source.admit", values)
    assert saved.status_code == 200
    key = str(uuid4())
    assert prepare(client, record, key).status_code == 200
    request = {field: value for field, value in values.items() if field != "expectedRevision"} | {
        "idempotencyKey": key
    }
    original = client.post("/api/intake/sources", json=request)
    assert original.status_code == 200, original.text
    assert client.post("/api/intake/sources", json=request).json() == original.json()
    response = reconcile(client, record)
    assert response.status_code == 200, response.text
    assert response.json()["receipt"]["receiptId"] == original.json()["operationId"]


def test_changed_source_payload_cannot_reconcile_an_existing_key(ready):
    _, intake, _, client, _ = ready
    record, saved = save(client, "intake.source.admit", payload(evidence()))
    assert saved.status_code == 200
    key = str(uuid4())
    attempt = prepare(client, record, key)
    assert attempt.status_code == 200
    intake.admit(IntakeAdmissionCommand(evidence("Different request"), "manual", key))
    assert reconcile(client, record).status_code == 409
    with intake.unit_of_work.engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT status FROM operator_recovery_records WHERE id=?", (record,)
            ).scalar_one()
            == "outcome_unknown"
        )


def test_duplicate_hashes_and_excess_manifest_entries_are_rejected(ready):
    _, _, _, client, _ = ready
    entry = {"role": "raw_source", "contentSha256": "a" * 64}
    record, saved = save(
        client, "intake.source.import", payload(evidence()) | {"attachments": [entry, entry]}
    )
    assert saved.status_code == 200  # incomplete form; source semantic validation at preparation
    assert prepare(client, record, str(uuid4())).status_code == 422
    _, response = save(client, "intake.source.import", {"attachments": [entry] * 21})
    assert response.status_code in {413, 422}


def test_retained_validation_rejects_rewritten_prepared_manifest(ready):
    workspace, _, _, client, _ = ready
    record, saved = save(client, "intake.source.import", payload(evidence()))
    assert saved.status_code == 200
    assert prepare(client, record, str(uuid4())).status_code == 200
    with sqlite3.connect(workspace.paths.database) as connection:
        connection.execute(
            "UPDATE operator_recovery_records SET request_fingerprint=? WHERE id=?",
            ("a" * 64, record),
        )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(workspace.paths.database)


def test_audit_failure_rolls_back_source_and_leaves_attempt_unknown(ready):
    workspace, intake, _, client, _ = ready
    record, saved = save(client, "intake.source.admit", payload(evidence()))
    assert saved.status_code == 200
    key = str(uuid4())
    assert prepare(client, record, key).status_code == 200
    with patch.object(
        intake.unit_of_work.recorder, "record_change", side_effect=RuntimeError("audit unavailable")
    ):
        with pytest.raises(RuntimeError):
            intake.admit(IntakeAdmissionCommand(evidence(), "manual", key))
    assert reconcile(client, record).status_code == 409
    with sqlite3.connect(workspace.paths.database) as connection:
        assert (
            connection.execute("SELECT count(*) FROM intake_source_operations").fetchone()[0] == 0
        )


def test_encrypted_restore_preserves_import_attempt_receipt_and_exact_evidence(ready, tmp_path):
    workspace, intake, _, client, _ = ready
    path = tmp_path / "content.txt"
    path.write_bytes(b"portable evidence")
    values = payload(evidence()) | {
        "attachments": [
            {"role": "raw_source", "contentSha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        ]
    }
    record, saved = save(client, "intake.source.import", values)
    assert saved.status_code == 200
    key = str(uuid4())
    assert prepare(client, record, key).status_code == 200
    intake.admit(
        IntakeAdmissionCommand(
            evidence(),
            "manual",
            key,
            (AttachmentInput(path, "content.txt", "text/plain", "raw_source"),),
        )
    )
    assert reconcile(client, record).status_code == 200
    tables = (
        "operator_recovery_records",
        "intake_source_operations",
        "intake_evidence_revisions",
        "intake_revision_file_links",
        "file_records",
        "file_links",
    )

    def retained(database):
        with sqlite3.connect(database) as connection:
            return {
                table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in tables
            }

    before = retained(workspace.paths.database)
    backups = BackupService(
        workspace,
        intake.unit_of_work.recorder,
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    with fast_backup_encryption():
        archive = backups.create_backup(
            "a sufficiently long passphrase", output_path=tmp_path / "evidence.epm-backup"
        )
        backups.restore(
            archive.archive_path, "a sufficiently long passphrase", tmp_path / "restored"
        )
    database = tmp_path / "restored/database/property-management.sqlite"
    validate_latest_schema(database)
    assert retained(database) == before
    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        assert SQLiteIntakeRecoveryReader().outcome(connection, key, family="intake") is not None
    engine.dispose()

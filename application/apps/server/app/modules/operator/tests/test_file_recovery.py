"""Slice 33: real public Files commands, immutable OPS recovery and portability."""

import hashlib
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.bootstrap.file_link_policies import build_file_link_policy_registry
from app.bootstrap.operator_recovery import OperatorRecoveryReferences, RecoverySourcePorts
from app.bootstrap.operator_recovery_composition import compose_recovery_bindings
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.api.router import build_router as build_file_router
from app.modules.files.application.service import FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.files.infrastructure.recovery_reader import SQLiteFileRecoveryReader
from app.modules.maintenance.tests import test_workflow as maintenance_fixtures
from app.modules.operator.api.router import build_router
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.file_forms import FILE_SCHEMAS
from app.modules.operator.application.service import OperatorService
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.api_errors import register_api_error_handlers
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema


@pytest.fixture
def ready():
    fixture = maintenance_fixtures.MaintenanceWorkflowTests()
    fixture.setUp()
    workspace = fixture.workspace
    issue = fixture.issue()
    recorder = AuditRecorder(SQLiteAuditRepository(workspace.paths.database))
    policies = build_file_link_policy_registry()
    store = FilesystemContentStore(workspace.paths.files)
    file_uow = SQLiteFileUnitOfWork(workspace.paths.database, recorder)
    files = FileService(
        workspace,
        store,
        file_uow,
        link_validators=tuple(dict.fromkeys(policies.as_mapping().values())),
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
    identity = RuntimeIdentity("ready", workspace.open().workspace_id, str(uuid4()), True)
    ops = OperatorService(ops_uow, runtime=lambda: identity)
    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_router(ops))
    app.include_router(
        build_file_router(files, SimpleNamespace(ready=True, error=None, can_write=True))
    )
    try:
        with TestClient(app) as client:
            yield workspace, files, client, issue["id"]
    finally:
        file_uow.engine.dispose()
        ops_uow.engine.dispose()
        fixture.doCleanups()


def upload_values(issue_id):
    return {
        "expectedRevision": 0,
        "originalName": "  cafe\u0301.txt  ",
        "mediaType": " TEXT/PLAIN ",
        "contentSha256": hashlib.sha256(b"Evidence").hexdigest(),
        "entityType": "maintenance_issue",
        "entityId": issue_id,
        "purpose": "supporting_document",
    }


def save(client, form, payload, link_id=None, revision=1):
    record = str(uuid4())
    response = client.put(
        "/api/operator/recovery/" + record,
        json={
            "formKey": form,
            "schemaVersion": 1,
            "payload": payload,
            "sourceKind": "file_link" if link_id else None,
            "sourceId": link_id,
            "baseSourceRevision": str(revision) if link_id else None,
            "expectedRevision": 0,
            "idempotencyKey": str(uuid4()),
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


def upload(client, target, key, content=b"Evidence"):
    return client.post(
        "/api/files",
        data={
            "entity_type": "maintenance_issue",
            "entity_id": target,
            "purpose": "supporting_document",
            "idempotency_key": key,
        },
        files={"file": ("cafe\u0301.txt", content, "text/plain")},
    )


def archive(client, link_id, key, reason="Wrong evidence"):
    return client.post(
        "/api/file-links/" + link_id + "/archive",
        json={
            "confirmed": True,
            "reason": reason,
            "expectedRevision": 1,
            "idempotencyKey": key,
        },
    )


def test_public_upload_and_archive_recover_original_states_without_publication(ready):
    workspace, files, client, issue_id = ready
    record, saved = save(client, "file.upload", upload_values(issue_id))
    assert saved.status_code == 200, saved.text
    key = str(uuid4())
    attempt_request = {"attemptKey": key, "expectedRevision": 1, "idempotencyKey": str(uuid4())}
    attempt = client.post("/api/operator/recovery/" + record + "/attempt", json=attempt_request)
    assert attempt.status_code == 200, attempt.text
    assert (
        client.post("/api/operator/recovery/" + record + "/attempt", json=attempt_request).json()
        == attempt.json()
    )
    assert reconcile(client, record).status_code == 409
    original = upload(client, issue_id, key)
    assert original.status_code == 201, original.text
    first = original.json()
    assert first["originalName"] == "café.txt"
    link_id = first["links"][0]["id"]
    archive_record, saved = save(
        client,
        "file.link.archive",
        {"expectedRevision": 1, "confirmed": True, "reason": "Wrong evidence"},
        link_id,
    )
    assert saved.status_code == 200, saved.text
    archive_key = str(uuid4())
    assert prepare(client, archive_record, archive_key).status_code == 200
    archived = archive(client, link_id, archive_key)
    assert archived.status_code == 200, archived.text
    with patch.object(files.content_store, "store", side_effect=AssertionError("must not publish")):
        assert upload(client, issue_id, key).json() == first
        assert archive(client, link_id, archive_key).json() == archived.json()
        upload_recovery = reconcile(client, record)
        archive_recovery = reconcile(client, archive_record)
    assert upload_recovery.status_code == 200, upload_recovery.text
    assert archive_recovery.status_code == 200, archive_recovery.text
    for response, revision, status, operation, target in (
        (upload_recovery, 1, "available", first["operationId"], first["id"]),
        (archive_recovery, 2, "archived", archived.json()["operationId"], link_id),
    ):
        assert response.json()["receipt"]["result"] == {
            "targetId": target,
            "revision": revision,
            "status": status,
            "operationId": operation,
            "fileId": first["id"],
            "linkId": link_id,
        }
    assert "archiveReason" not in json.dumps(archive_recovery.json()["receipt"])
    validate_latest_schema(workspace.paths.database)


@pytest.mark.parametrize(
    "changes",
    [
        {"storageProvider": "s3"},
        {"path": "/private/content"},
        {"bytes": "secret bytes"},
        {"expectedRevision": True},
        {"expectedRevision": 1},
        {"contentSha256": "not-a-hash"},
    ],
)
def test_malformed_and_provider_selecting_upload_forms_are_rejected(ready, changes):
    _, _, client, issue_id = ready
    _, response = save(client, "file.upload", upload_values(issue_id) | changes)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "changes",
    [
        {"entityType": "condition_observation"},
        {"entityType": "intake_source"},
        {"entityId": "00000000-0000-0000-0000-000000000001"},
        {"purpose": "invalid-purpose"},
        {"entityType": "unknown-type"},
    ],
)
def test_upload_policy_guards_fail_closed(ready, changes):
    _, _, client, issue_id = ready
    _, response = save(client, "file.upload", upload_values(issue_id) | changes)
    assert response.status_code == 409, response.text


def test_incomplete_upload_autosaves_but_cannot_prepare(ready):
    _, _, client, _ = ready
    record, response = save(client, "file.upload", {"originalName": "Draft.txt"})
    assert response.status_code == 200
    assert prepare(client, record, str(uuid4())).status_code == 422


def test_archived_and_stale_associations_cannot_begin_attempts(ready):
    _, _, client, issue_id = ready
    result = upload(client, issue_id, str(uuid4())).json()
    link = result["links"][0]["id"]
    _, response = save(
        client,
        "file.link.archive",
        {"expectedRevision": 2, "confirmed": True, "reason": "wrong"},
        link,
    )
    assert response.status_code == 409
    assert archive(client, link, str(uuid4())).status_code == 200
    _, response = save(
        client,
        "file.link.archive",
        {"expectedRevision": 2, "confirmed": True, "reason": "wrong"},
        link,
        revision=2,
    )
    assert response.status_code == 409


def test_upload_changed_content_under_attempt_key_cannot_reconcile(ready):
    _, _, client, issue_id = ready
    record, saved = save(client, "file.upload", upload_values(issue_id))
    assert saved.status_code == 200
    key = str(uuid4())
    assert prepare(client, record, key).status_code == 200
    assert upload(client, issue_id, key, b"Changed content").status_code == 201
    assert reconcile(client, record).status_code == 409


def test_publication_commit_failure_rolls_back_and_keeps_attempt_unknown(ready):
    workspace, files, client, issue_id = ready
    record, saved = save(client, "file.upload", upload_values(issue_id))
    assert saved.status_code == 200
    key = str(uuid4())
    assert prepare(client, record, key).status_code == 200
    engine = files.unit_of_work.engine

    def fail_commit(connection):
        raise RuntimeError("commit unavailable")

    event.listen(engine, "commit", fail_commit)
    try:
        with pytest.raises(RuntimeError):
            upload(client, issue_id, key)
    finally:
        event.remove(engine, "commit", fail_commit)
    assert reconcile(client, record).status_code == 409
    assert not list((workspace.paths.files / "managed").iterdir())
    with sqlite3.connect(workspace.paths.database) as connection:
        assert connection.execute("SELECT count(*) FROM file_records").fetchone()[0] == 0


def test_indexed_receipt_lookup_uses_one_caller_owned_select(ready):
    _, files, client, issue_id = ready
    key = str(uuid4())
    original = upload(client, issue_id, key).json()
    statements = []
    engine = files.unit_of_work.engine

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    with engine.connect() as connection:
        event.listen(engine, "before_cursor_execute", capture)
        try:
            with patch.object(
                engine, "connect", side_effect=AssertionError("no nested connections")
            ):
                result = SQLiteFileRecoveryReader(build_file_link_policy_registry()).outcome(
                    connection, key, family="file"
                )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert result.operation_id == original["operationId"]


def test_postcommit_release_failure_still_reconciles_without_reupload(ready):
    _, files, client, issue_id = ready
    record, saved = save(client, "file.upload", upload_values(issue_id))
    assert saved.status_code == 200
    key = str(uuid4())
    assert prepare(client, record, key).status_code == 200
    original_store = files.content_store.store

    def failing_release(source):
        lease = original_store(source)
        release = lease.commit

        def commit():
            release()
            raise OSError("release failed")

        lease.commit = commit
        return lease

    with patch.object(files.content_store, "store", side_effect=failing_release):
        response = upload(client, issue_id, key)
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "publication_cleanup_incomplete"
    with patch.object(files.content_store, "store", side_effect=AssertionError("no republication")):
        result = reconcile(client, record)
    assert result.status_code == 200, result.text
    assert result.json()["receipt"]["result"]["status"] == "available"


def test_deterministic_no_workspace_contract_and_exact_registry():
    app = FastAPI()
    app.include_router(build_router(None))
    assert app.openapi() == app.openapi()
    assert set(FILE_SCHEMAS) <= set(compose_recovery_bindings())


def test_encrypted_backup_preserves_upload_archive_and_ops_receipts(ready, tmp_path):
    workspace, files, client, issue_id = ready
    record, saved = save(client, "file.upload", upload_values(issue_id))
    assert saved.status_code == 200
    key = str(uuid4())
    assert prepare(client, record, key).status_code == 200
    result = upload(client, issue_id, key).json()
    link = result["links"][0]["id"]
    archived_record, saved = save(
        client,
        "file.link.archive",
        {"expectedRevision": 1, "confirmed": True, "reason": "Wrong evidence"},
        link,
    )
    assert saved.status_code == 200
    archived_key = str(uuid4())
    assert prepare(client, archived_record, archived_key).status_code == 200
    assert archive(client, link, archived_key).status_code == 200
    assert reconcile(client, record).status_code == 200
    assert reconcile(client, archived_record).status_code == 200
    tables = (
        "operator_recovery_records",
        "file_records",
        "file_links",
        "file_content_locations",
        "file_command_operations",
    )

    def retained(database):
        with sqlite3.connect(database) as connection:
            return {
                table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in tables
            }

    before = retained(workspace.paths.database)
    backup = BackupService(
        workspace,
        files.unit_of_work.recorder,
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    with fast_backup_encryption():
        archive_result = backup.create_backup(
            "a sufficiently long passphrase", output_path=tmp_path / "files.epm-backup"
        )
        backup.restore(
            archive_result.archive_path, "a sufficiently long passphrase", tmp_path / "restored"
        )
    database = tmp_path / "restored/database/property-management.sqlite"
    validate_latest_schema(database)
    assert retained(database) == before


def test_retained_validation_rejects_changed_prepared_identity(ready):
    workspace, _, client, issue_id = ready
    record, saved = save(client, "file.upload", upload_values(issue_id))
    assert saved.status_code == 200
    assert prepare(client, record, str(uuid4())).status_code == 200
    with sqlite3.connect(workspace.paths.database) as connection:
        connection.execute(
            "UPDATE operator_recovery_records SET request_fingerprint=? WHERE id=?",
            ("b" * 64, record),
        )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(workspace.paths.database)

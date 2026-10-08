"""Slice 17: real SQLite publication, immutable recovery, and portability."""

from concurrent.futures import ThreadPoolExecutor
import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from app.bootstrap.file_link_policies import build_file_link_policy_registry
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.api.router import build_router
from app.modules.files.application.commands import FileRevisionConflict
from app.modules.files.application.errors import FileError, PublicationCleanupIncomplete
from app.modules.files.application.service import FileService
from app.modules.files.domain.audit_policy import FILE_COMMAND_ACTIVITY_SNAPSHOT_POLICY
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.files.infrastructure.command_triggers import FILE_COMMAND_TRIGGERS
from app.modules.maintenance.tests import test_workflow
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema


@pytest.fixture
def context():
    fixture = test_workflow.MaintenanceWorkflowTests()
    fixture.setUp()
    try:
        issue = fixture.issue()
        workspace = fixture.workspace
        recorder = AuditRecorder(SQLiteAuditRepository(workspace.paths.database))
        policies = tuple(dict.fromkeys(build_file_link_policy_registry().as_mapping().values()))
        files = FileService(
            workspace,
            FilesystemContentStore(workspace.paths.files),
            SQLiteFileUnitOfWork(workspace.paths.database, recorder),
            link_validators=policies,
        )
        source = workspace.paths.root / "test-upload.txt"
        source.write_bytes(b"Recoverable attachment")
        yield fixture, files, source, issue["id"]
    finally:
        fixture.doCleanups()


def upload(files, source, issue_id, key):
    return files.upload(
        source,
        "evidence.txt",
        "text/plain",
        entity_type="maintenance_issue",
        entity_id=issue_id,
        purpose="supporting_document",
        idempotency_key=key,
    )


def archive(files, result, key, expected_revision=1, reason="Wrong attachment"):
    return files.archive_command(
        result["links"][0]["id"],
        confirmed=True,
        reason=reason,
        expected_revision=expected_revision,
        idempotency_key=key,
    )


def test_original_upload_and_archive_results_survive_later_state_and_restart(context):
    fixture, files, source, target = context
    key, archive_key = str(uuid4()), str(uuid4())
    first = upload(files, source, target, key)
    archived = archive(files, first, archive_key)
    assert archived["revision"] == 2
    assert files.get(first["id"]).links[0]["revision"] == 2
    with patch.object(
        files.content_store, "store", side_effect=AssertionError("must not republish")
    ):
        assert upload(files, source, target, key) == first
        assert files.recover_command(key=key) == first
    assert archive(files, first, archive_key) == archived
    assert files.recover_command(operation_id=archived["operationId"]) == archived
    with pytest.raises(FileRevisionConflict) as stale:
        archive(files, first, str(uuid4()))
    assert stale.value.current["revision"] == 2
    with pytest.raises(FileError, match="different command"):
        archive(files, first, archive_key, reason="Changed reason")
    restarted = SQLiteFileUnitOfWork(fixture.workspace.paths.database, files.unit_of_work.recorder)
    assert restarted.command_receipt(key=key).result() == first
    validate_latest_schema(fixture.workspace.paths.database)


def test_changed_upload_and_invalid_direct_commands_fail_before_publication(context):
    _, files, source, target = context
    key = str(uuid4())
    upload(files, source, target, key)
    source.write_bytes(b"changed bytes")
    with patch.object(files.content_store, "store", side_effect=AssertionError("must not publish")):
        with pytest.raises(FileError, match="different command"):
            upload(files, source, target, key)
        with pytest.raises(FileError, match="canonical UUID"):
            upload(files, source, target, "bad-key")
    for revision in (True, "1", 0, -1):
        with pytest.raises(FileError, match="positive integer"):
            files.archive_command(
                str(uuid4()),
                confirmed=True,
                reason="reason",
                expected_revision=revision,
                idempotency_key=str(uuid4()),
            )


def test_invalid_target_rolls_back_publication_and_reserves_no_key(context):
    _, files, source, _target = context
    key = str(uuid4())
    with pytest.raises(FileError) as failure:
        upload(files, source, str(uuid4()), key)
    assert failure.value.code == "file_lifecycle_conflict"
    assert files.unit_of_work.command_receipt(key=key) is None
    assert not list((files.workspace.paths.files / "managed").iterdir())


def test_concurrent_duplicate_uploads_create_one_logical_file_and_receipt(context):
    _, files, source, target = context
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: upload(files, source, target, key), range(2)))
    assert results[0] == results[1]
    with files.unit_of_work.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM file_records")).scalar_one() == 1
        assert (
            connection.execute(text("SELECT count(*) FROM file_command_operations")).scalar_one()
            == 1
        )
    assert len(list((files.workspace.paths.files / "managed").iterdir())) == 1


@pytest.mark.parametrize("failure", ["audit", "commit"])
def test_publication_rolls_back_when_atomic_receipt_or_commit_fails(context, failure):
    _, files, source, target = context
    key = str(uuid4())
    if failure == "commit":

        def fail_commit(connection):
            raise RuntimeError("commit failure")

        event.listen(files.unit_of_work.engine, "commit", fail_commit)
        try:
            with pytest.raises(RuntimeError, match="commit failure"):
                upload(files, source, target, key)
        finally:
            event.remove(files.unit_of_work.engine, "commit", fail_commit)
    else:
        original = files.unit_of_work.recorder.record_change

        def fail_receipt(*args, **kwargs):
            if kwargs["entity_type"] == "file_command_operation":
                raise RuntimeError("receipt audit failure")
            return original(*args, **kwargs)

        with patch.object(files.unit_of_work.recorder, "record_change", side_effect=fail_receipt):
            with pytest.raises(RuntimeError, match="receipt audit failure"):
                upload(files, source, target, key)
    assert files.unit_of_work.command_receipt(key=key) is None
    with files.unit_of_work.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM file_records")).scalar_one() == 0
    assert not list((files.workspace.paths.files / "managed").iterdir())


def test_postcommit_release_failure_recovers_committed_result_without_republication(context):
    _, files, source, target = context
    key = str(uuid4())
    original = files.content_store.store

    def prepare(path):
        lease = original(path)
        lease.commit = lambda: (_ for _ in ()).throw(OSError("release failed"))
        return lease

    with patch.object(files.content_store, "store", side_effect=prepare):
        with pytest.raises(PublicationCleanupIncomplete):
            upload(files, source, target, key)
    recovered = files.recover_command(key=key)
    with patch.object(
        files.content_store, "store", side_effect=AssertionError("duplicate publication")
    ):
        assert upload(files, source, target, key) == recovered
    assert len(files.unit_of_work.outstanding_cleanup_attentions()) == 1


def test_receipt_queries_are_bounded_and_activity_hides_evidence(context):
    _, files, source, target = context
    key = str(uuid4())
    result = upload(files, source, target, key)
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(files.unit_of_work.engine, "before_cursor_execute", capture)
    try:
        assert files.recover_command(key=key) == result
    finally:
        event.remove(files.unit_of_work.engine, "before_cursor_execute", capture)
    assert len([s for s in statements if s.lstrip().upper().startswith("SELECT")]) == 1
    operation = files.unit_of_work.command_receipt(key=key)
    presented = FILE_COMMAND_ACTIVITY_SNAPSHOT_POLICY.redact(
        {
            "action": operation.action,
            "request_json": operation.request_json,
            "result_json": operation.result_json,
            "created_at": operation.created_at,
        }
    )
    assert set(presented) == {"action", "created_at"}
    assert "evidence.txt" not in str(presented)


def test_receipt_tampering_and_missing_correlated_audit_are_rejected(context):
    fixture, files, source, target = context
    upload(files, source, target, str(uuid4()))
    with files.unit_of_work.engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(text("UPDATE file_command_operations SET action='archive_link'"))
    validate_latest_schema(fixture.workspace.paths.database)
    with files.unit_of_work.engine.begin() as connection:
        connection.execute(text("DROP TRIGGER audit_events_no_delete"))
        connection.execute(
            text("DELETE FROM audit_events WHERE entity_type='file_command_operation'")
        )
        connection.execute(
            text(
                "CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"
            )
        )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(fixture.workspace.paths.database)


def test_rewritten_original_result_is_rejected_even_with_restored_triggers(context):
    fixture, files, source, target = context
    key = str(uuid4())
    result = upload(files, source, target, key)
    with files.unit_of_work.engine.begin() as connection:
        connection.execute(text("DROP TRIGGER file_command_operations_no_update"))
        connection.execute(
            text("UPDATE file_command_operations SET result_json=:result"),
            {
                "result": json.dumps(
                    result | {"originalName": "rewritten.txt"},
                    sort_keys=True,
                    separators=(",", ":"),
                )
            },
        )
        connection.execute(text(FILE_COMMAND_TRIGGERS["file_command_operations_no_update"]))
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(fixture.workspace.paths.database)


def test_api_typed_commands_and_recovery_contract(context):
    _, files, source, target = context

    class Runtime:
        ready = can_write = True
        error = None

    app = FastAPI()
    app.include_router(build_router(files, Runtime()))
    data = {
        "entity_type": "maintenance_issue",
        "entity_id": target,
        "purpose": "supporting_document",
    }
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/files", data=data, files={"file": ("evidence.txt", b"bytes", "text/plain")}
            ).status_code
            == 422
        )
        key = str(uuid4())
        response = client.post(
            "/api/files",
            data=data | {"idempotency_key": key},
            files={"file": ("evidence.txt", source.read_bytes(), "text/plain")},
        )
        assert response.status_code == 201, response.text
        result = response.json()
        recovered = client.get(f"/api/files/commands/by-key/{key}")
        assert recovered.json() == result
        link_id = result["links"][0]["id"]
        assert (
            client.post(
                f"/api/file-links/{link_id}/archive", json={"confirmed": True, "reason": "wrong"}
            ).status_code
            == 422
        )
        payload = {
            "confirmed": True,
            "reason": "wrong",
            "expectedRevision": 1,
            "idempotencyKey": str(uuid4()),
        }
        archived = client.post(f"/api/file-links/{link_id}/archive", json=payload)
        assert archived.status_code == 200, archived.text
        assert (
            client.post(f"/api/file-links/{link_id}/archive", json=payload).json()
            == archived.json()
        )
        conflict = client.post(
            f"/api/file-links/{link_id}/archive", json=payload | {"idempotencyKey": str(uuid4())}
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["current"]["revision"] == 2
        assert client.get(f"/api/files/commands/{uuid4()}").status_code == 404
        contract = client.get("/openapi.json").json()
        assert contract["paths"]["/api/files"]["post"]["operationId"] == "uploadFile"


def test_encrypted_backup_restores_original_upload_and_archive_receipts(context):
    fixture, files, source, target = context
    key, archive_key = str(uuid4()), str(uuid4())
    result = upload(files, source, target, key)
    archived = archive(files, result, archive_key)
    backups = BackupService(
        fixture.workspace,
        files.unit_of_work.recorder,
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    output = fixture.workspace.paths.root.parent / "files.epm-backup"
    restored_root = fixture.workspace.paths.root.parent / "restored-files"
    with fast_backup_encryption():
        backup = backups.create_backup(
            "a sufficiently long files backup passphrase", output_path=output
        )
        backups.restore(
            backup.archive_path, "a sufficiently long files backup passphrase", restored_root
        )
    database = restored_root / "database" / "property-management.sqlite"
    restored = SQLiteFileUnitOfWork(database, AuditRecorder(SQLiteAuditRepository(database)))
    assert restored.command_receipt(key=key).result() == result
    assert restored.command_receipt(key=archive_key).result() == archived
    assert restored.get(result["id"]).links[0]["archiveReason"] == "Wrong attachment"
    validate_latest_schema(database)

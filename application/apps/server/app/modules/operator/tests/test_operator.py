"""OPS foundation acceptance through real current-format SQLite workspaces."""

import json
import hashlib
import sqlite3
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from threading import Barrier

import pytest
from fastapi import FastAPI
from app.platform.testing_client import LocalApiClient as TestClient
from sqlalchemy import event, text

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.operator.api.router import BootstrapResponse, build_router
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.service import OperatorService
from app.modules.operator.domain.models import (
    OperatorConflict,
    OperatorError,
    OperatorStorageFailure,
    OperatorUnavailable,
    DESTINATIONS,
    canonical,
)
from app.modules.operator.infrastructure.schema_validation import validate_operator_schema
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork
from app.modules.workspace.application.service import WorkspaceError, WorkspaceService
from app.platform.config import LocalConfig
from app.platform.product_migrations import validate_latest_schema
from app.platform.migration_errors import MigrationSchemaError
from app.platform.api_errors import register_api_error_handlers


class References:
    def validate(self, connection, value):
        return "available"

    def resolve_attempt(self, connection, form_key, key, request_fingerprint):
        return {
            "sourceKind": "communication",
            "sourceId": str(uuid4()),
            "receiptId": str(uuid4()),
            "attemptKey": key,
        }


@pytest.fixture
def foundation():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        workspace = WorkspaceService(LocalConfig(root / "config.json", root / "workspace"))
        manifest = workspace.initialize()
        uow = SQLiteOperatorUnitOfWork(
            workspace.paths.database,
            AuditRecorder(SQLiteAuditRepository(workspace.paths.database)),
            References(),
            SQLiteAuditReadMarker(),
        )
        instant = datetime(2026, 10, 7, 19, tzinfo=UTC)
        identity = RuntimeIdentity("ready", manifest.workspace_id, str(uuid4()), True)
        service = OperatorService(uow, runtime=lambda: identity, now=lambda: instant)
        yield workspace, uow, service
        uow.engine.dispose()


def save(service, **changes):
    data = {
        "record_id": str(uuid4()),
        "form_key": "task.create",
        "schema_version": 1,
        "payload": {"title": "Call owner"},
        "expected_revision": 0,
        "idempotency_key": str(uuid4()),
    }
    data.update(changes)
    return service.save_recovery(**data)


def preferences(service, **changes):
    data = {
        "appearance": "dark",
        "destination_order": DESTINATIONS,
        "hidden_destination_ids": ("owners",),
        "expected_revision": 0,
        "idempotency_key": str(uuid4()),
    }
    data.update(changes)
    return service.update_preferences(**data)


def test_read_defaults_does_not_write(foundation):
    workspace, uow, service = foundation
    statements = []
    event.listen(uow.engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    assert service.preferences()["revision"] == 0
    assert service.bootstrap()["preferences"]["appearance"] == "light"
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements
    )
    validate_latest_schema(workspace.paths.database)


def test_preferences_replay_and_conflict(foundation):
    workspace, uow, service = foundation
    key = str(uuid4())
    first = preferences(service, idempotency_key=key)
    preferences(service, appearance="light", expected_revision=1)
    assert preferences(service, idempotency_key=key) == first
    assert service.preferences()["appearance"] == "light"
    with pytest.raises(OperatorConflict):
        preferences(service, idempotency_key=key, appearance="light")
    with pytest.raises(OperatorConflict) as error:
        preferences(service)
    assert error.value.current_revision == 2
    validate_latest_schema(workspace.paths.database)


@pytest.mark.parametrize(
    "order,hidden",
    [
        (("owners", "home"), ()),
        (DESTINATIONS, ("home",)),
        (DESTINATIONS, ("settings",)),
        (("money", "money"), ()),
        (("imaginary",), ()),
    ],
)
def test_invalid_preferences(foundation, order, hidden):
    with pytest.raises(OperatorError):
        preferences(foundation[2], destination_order=order, hidden_destination_ids=hidden)


@pytest.mark.parametrize(
    "form,payload",
    [
        ("task.create", {"notes": "unfinished"}),
        (
            "maintenance.issue.create",
            {"summary": "Leak", "reporter": {"subjectKind": "local_operator"}},
        ),
        ("communication.record", {"subject": "Call", "body": "operator-only private text"}),
    ],
)
def test_registered_form_roundtrip_and_audit_privacy(foundation, form, payload):
    workspace, uow, service = foundation
    value = save(service, form_key=form, payload=payload)
    assert service.recovery(value["id"])["payload"] == payload
    with uow.engine.connect() as connection:
        events = (
            connection.execute(
                text("SELECT after_snapshot FROM audit_events WHERE entity_type LIKE 'operator_%'")
            )
            .scalars()
            .all()
        )
        assert all(
            "operator-only private text" not in event and '"payload"' not in event
            for event in events
        )
    validate_latest_schema(workspace.paths.database)


@pytest.mark.parametrize(
    "payload",
    [
        {"apiKey": "secret"},
        {"fileBytes": "binary"},
        {"domainDraftId": str(uuid4())},
        {"status": "completed"},
    ],
)
def test_recovery_rejects_unregistered_fields(foundation, payload):
    with pytest.raises(OperatorError):
        save(foundation[2], payload=payload)


def test_recovery_replay_stale_and_rollback(foundation):
    workspace, uow, service = foundation
    record_id, key = str(uuid4()), str(uuid4())
    first = save(service, record_id=record_id, idempotency_key=key)
    assert save(service, record_id=record_id, idempotency_key=key) == first
    with pytest.raises(OperatorConflict):
        save(service, record_id=record_id)
    with patch.object(uow.recorder, "record_change", side_effect=RuntimeError("audit unavailable")):
        with pytest.raises(RuntimeError):
            save(service, record_id=record_id, expected_revision=1, payload={"title": "Changed"})
    assert service.recovery(record_id)["revision"] == 1
    validate_latest_schema(workspace.paths.database)


def test_unknown_outcomes_do_not_expire_or_discard(foundation):
    workspace, uow, service = foundation
    value = save(service, form_key="communication.record", payload={"subject": "Call"})
    attempted = service.prepare_attempt(
        value["id"],
        attempt_key=str(uuid4()),
        request_fingerprint="a" * 64,
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    with pytest.raises(OperatorConflict):
        service.discard_recovery(value["id"], expected_revision=2, idempotency_key=str(uuid4()))
    service.now = lambda: datetime(2026, 12, 7, tzinfo=UTC)
    assert service.expire_recovery()["expiredCount"] == 0
    assert service.recovery(value["id"])["reuseState"] == "outcome_unknown"
    reconciled = service.reconcile_recovery(
        value["id"], expected_revision=2, idempotency_key=str(uuid4())
    )
    assert reconciled["receipt"]["attemptKey"] == attempted["attemptKey"]
    assert service.expire_recovery()["expiredCount"] == 1
    validate_latest_schema(workspace.paths.database)


def test_expiry_is_explicit_and_bounded(foundation):
    workspace, uow, service = foundation
    first = save(service)
    second = save(service)
    service.now = lambda: datetime(2026, 10, 7, 19, tzinfo=UTC) + timedelta(days=30)
    assert service.recovery(first["id"])["reuseState"] == "expired"
    assert service.recovery_page()["matchingTotal"] == 2
    assert service.expire_recovery(limit=1)["expiredCount"] == 1
    assert service.recovery_page()["matchingTotal"] == 1
    service.expire_recovery()
    assert service.recovery(second["id"])["status"] == "expired"
    validate_latest_schema(workspace.paths.database)


def test_readiness_prevents_database_access(foundation):
    workspace, uow, service = foundation
    service.runtime = lambda: RuntimeIdentity(
        "unavailable", None, str(uuid4()), False, "workspace_unavailable"
    )
    with patch.object(uow, "read", side_effect=AssertionError("must not touch storage")):
        assert service.bootstrap()["preferencesState"] == "unavailable"
        assert service.bootstrap()["preferences"] is None
        with pytest.raises(OperatorUnavailable):
            service.preferences()
    with patch.object(uow, "write", side_effect=AssertionError("must not touch storage")):
        with pytest.raises(OperatorUnavailable):
            save(service)


def test_tampered_payload_rejected(foundation):
    workspace, uow, service = foundation
    value = save(service)
    with uow.engine.begin() as connection:
        connection.execute(
            text("UPDATE operator_recovery_records SET payload_json=:payload WHERE id=:id"),
            {
                "payload": json.dumps({"title": "tampered"}, separators=(",", ":")),
                "id": value["id"],
            },
        )
    with uow.engine.connect() as connection, pytest.raises(MigrationSchemaError):
        validate_operator_schema(connection)


def reconciled_recovery(service):
    value = save(
        service,
        form_key="communication.record",
        payload={"subject": "Call"},
        source_kind="party",
        source_id=str(uuid4()),
        base_source_revision="original",
    )
    service.prepare_attempt(
        value["id"],
        attempt_key=str(uuid4()),
        request_fingerprint="a" * 64,
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    return service.reconcile_recovery(
        value["id"], expected_revision=2, idempotency_key=str(uuid4())
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("form_key", "maintenance.issue.create"),
        ("schema_version", 2),
        ("source_kind", "space"),
        ("source_id", str(uuid4())),
        ("base_source_revision", "rewritten"),
        ("attempt_key", str(uuid4())),
        ("request_fingerprint", "b" * 64),
        ("receipt_json", "changed_receipt"),
    ],
    ids=[
        "form_key",
        "schema_version",
        "source_kind",
        "source_id",
        "base_source_revision",
        "attempt_key",
        "request_fingerprint",
        "receipt_json",
    ],
)
def test_workspace_rejects_all_recovery_metadata_divergence(foundation, field, value):
    workspace, uow, service = foundation
    record = reconciled_recovery(service)
    validate_latest_schema(workspace.paths.database)
    if field == "receipt_json":
        value = canonical({**record["receipt"], "receiptId": str(uuid4())})
    with uow.engine.begin() as connection:
        connection.execute(
            text(f"UPDATE operator_recovery_records SET {field}=:value WHERE id=:id"),
            {"value": value, "id": record["id"]},
        )
    with pytest.raises(MigrationSchemaError, match="Retained Operator data"):
        validate_latest_schema(workspace.paths.database)
    with pytest.raises(WorkspaceError, match="Retained Operator data"):
        workspace.open()


@pytest.mark.parametrize("tamper", ["source", "receipt", "illegal_transition", "changed_form"])
def test_later_operation_cannot_legitimize_rewritten_history(foundation, tamper):
    workspace, uow, service = foundation
    record = reconciled_recovery(service)
    fields = {
        "source": {"source_id": str(uuid4())},
        "receipt": {"receipt_json": canonical({**record["receipt"], "receiptId": str(uuid4())})},
        "illegal_transition": {"status": "active"},
        "changed_form": {"status": "active", "form_key": "task.create"},
    }[tamper]
    with uow.engine.begin() as connection:
        assignments = ", ".join(f"{field}=:{field}" for field in fields)
        connection.execute(
            text(f"UPDATE operator_recovery_records SET {assignments} WHERE id=:id"),
            {**fields, "id": record["id"]},
        )
    if tamper == "changed_form":
        save(service, record_id=record["id"], expected_revision=3)
    else:
        service.discard_recovery(record["id"], expected_revision=3, idempotency_key=str(uuid4()))
    with pytest.raises(MigrationSchemaError, match="Retained Operator data"):
        validate_latest_schema(workspace.paths.database)


def test_recovery_history_allows_active_saves_and_reconciled_discard(foundation):
    workspace, uow, service = foundation
    record = save(service)
    save(
        service,
        record_id=record["id"],
        expected_revision=1,
        source_kind="party",
        source_id=str(uuid4()),
        base_source_revision="new",
        payload={"notes": "Updated incomplete form"},
    )
    reconciled = reconciled_recovery(service)
    service.discard_recovery(reconciled["id"], expected_revision=3, idempotency_key=str(uuid4()))
    validate_latest_schema(workspace.paths.database)


def test_restore_rejects_authenticated_archive_with_rewritten_recovery_identity(foundation):
    from app.modules.workspace.application.backup_models import BackupError
    from app.modules.workspace.application.backup_service import BackupService
    from app.modules.workspace.infrastructure.encrypted_archive import (
        decrypt_archive_to_zip,
        make_header,
        write_encrypted_archive,
    )

    workspace, uow, service = foundation
    record = reconciled_recovery(service)
    backup = BackupService(
        workspace, uow.recorder, lambda database: AuditRecorder(SQLiteAuditRepository(database))
    )
    passphrase = "a long encrypted operator test passphrase"
    original = backup.create_backup(
        passphrase, output_path=workspace.paths.root.parent / "original.epmbackup"
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        payload = root / "payload.zip"
        decrypt_archive_to_zip(original.archive_path, passphrase, payload)
        with zipfile.ZipFile(payload) as package:
            files = {
                item.filename: package.read(item)
                for item in package.infolist()
                if not item.is_dir()
            }
        database_key = "workspace/database/property-management.sqlite"
        database = root / "tampered.sqlite"
        database.write_bytes(files[database_key])
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute(
                "UPDATE operator_recovery_records SET base_source_revision=? WHERE id=?",
                ("fabricated", record["id"]),
            )
        files[database_key] = database.read_bytes()
        manifest = json.loads(files["backup-manifest.json"])
        for item in manifest["files"]:
            if item["path"] == database_key:
                item.update(
                    bytes=len(files[database_key]),
                    sha256=hashlib.sha256(files[database_key]).hexdigest(),
                )
        files["backup-manifest.json"] = (json.dumps(manifest, sort_keys=True) + "\n").encode()
        with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as package:
            for name, contents in files.items():
                package.writestr(name, contents)
        archive = root / "tampered.epmbackup"
        write_encrypted_archive(
            payload,
            archive,
            make_header(workspace_id=service.runtime().workspace_id, package_type="backup"),
            passphrase,
        )
        with pytest.raises(BackupError, match="Retained Operator data"):
            backup.validate_archive(archive, passphrase)
        destination = root / "restored"
        with pytest.raises(BackupError, match="Retained Operator data"):
            backup.restore(archive, passphrase, destination)
        assert not destination.exists()


def test_strict_api_and_success(foundation):
    service = foundation[2]
    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_router(service))
    with TestClient(app) as client:
        response = client.put(
            "/api/operator/preferences",
            json={
                "appearance": "dark",
                "destinationOrder": ["money"],
                "expectedRevision": 0,
                "idempotencyKey": str(uuid4()),
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["destinationOrder"][0] == "home"
        assert response.json()["operationId"]
        response = client.put(
            "/api/operator/recovery/" + str(uuid4()),
            json={
                "formKey": "task.create",
                "schemaVersion": 1,
                "payload": {"title": "Save me"},
                "expectedRevision": 0,
                "idempotencyKey": str(uuid4()),
            },
        )
        assert response.status_code == 200, response.text
        response = client.put(
            "/api/operator/preferences",
            json={
                "appearance": "dark",
                "destinationOrder": [],
                "expectedRevision": True,
                "idempotencyKey": str(uuid4()),
                "unknown": 1,
            },
        )
        assert response.status_code == 422
        schema = app.openapi()
        assert (
            schema["paths"]["/api/operator/bootstrap"]["get"]["operationId"]
            == "getOperatorBootstrap"
        )


def test_recovery_cursor_no_gaps_and_freshness(foundation):
    workspace, uow, service = foundation
    expected = {save(service)["id"] for _ in range(3)}
    first = service.recovery_page(limit=1)
    second = service.recovery_page(limit=1, cursor=first["nextCursor"])
    third = service.recovery_page(limit=1, cursor=second["nextCursor"])
    assert {page["items"][0]["id"] for page in (first, second, third)} == expected
    assert first["matchingTotal"] == second["matchingTotal"] == third["matchingTotal"] == 3
    assert first["asOf"] == second["asOf"] == third["asOf"]
    assert third["nextCursor"] is None
    with pytest.raises(OperatorConflict):
        service.recovery_page(limit=2, cursor=first["nextCursor"])
    save(service)
    with pytest.raises(OperatorConflict):
        service.recovery_page(limit=1, cursor=first["nextCursor"])


def test_cursor_expiry_and_runtime_epoch(foundation):
    service = foundation[2]
    save(service)
    save(service)
    first = service.recovery_page(limit=1)
    service.now = lambda: datetime(2026, 10, 7, 19, 15, tzinfo=UTC)
    with pytest.raises(OperatorConflict):
        service.recovery_page(limit=1, cursor=first["nextCursor"])
    service.now = lambda: datetime(2026, 10, 7, 19, tzinfo=UTC)
    identity = service.runtime()
    service.runtime = lambda: RuntimeIdentity("ready", identity.workspace_id, str(uuid4()), True)
    with pytest.raises(OperatorConflict):
        service.recovery_page(limit=1, cursor=first["nextCursor"])
    with pytest.raises(OperatorError):
        service.recovery_page(cursor="not a cursor")


def test_recovery_capacity_and_query_budget(foundation):
    workspace, uow, service = foundation
    for _ in range(100):
        save(service)
    with pytest.raises(OperatorConflict):
        save(service)
    statements = []

    def listener(*args):
        statements.append(args[2])

    event.listen(uow.engine, "before_cursor_execute", listener)
    first = service.recovery_page(limit=1)
    one_count = len(statements)
    statements.clear()
    full = service.recovery_page(limit=100)
    assert first["matchingTotal"] == full["matchingTotal"] == 100
    assert len(statements) == one_count <= 4
    assert len(full["items"]) == 100
    assert all("payload" not in item for item in full["items"])
    assert not any("payload_json" in sql for sql in statements)
    event.remove(uow.engine, "before_cursor_execute", listener)
    service.discard_recovery(
        full["items"][0]["id"], expected_revision=1, idempotency_key=str(uuid4())
    )
    save(service)
    validate_latest_schema(workspace.paths.database)


def test_oversized_recovery_is_413(foundation):
    from app.modules.operator.domain.models import OperatorTooLarge

    with pytest.raises(OperatorTooLarge):
        save(foundation[2], form_key="communication.record", payload={"body": "a" * 65537})


@pytest.mark.parametrize(
    "form,payload,status,code",
    [
        ("task.create", {"title": "a" * 241}, 413, "operator_payload_too_large"),
        ("task.create", {"notes": "a" * 10001}, 413, "operator_payload_too_large"),
        ("communication.record", {"body": "a" * 10001}, 413, "operator_payload_too_large"),
        (
            "maintenance.issue.create",
            {"reporter": {"historicalSelectionReason": "a" * 1001}},
            413,
            "operator_payload_too_large",
        ),
        (
            "communication.record",
            {"participants": [{"partyId": str(uuid4()), "role": "sender"}] * 101},
            413,
            "operator_payload_too_large",
        ),
        (
            "communication.record",
            {"links": [{"entityType": "party", "entityId": str(uuid4())}] * 101},
            413,
            "operator_payload_too_large",
        ),
        (
            "task.create",
            {"title": "a" * 241, "priority": "invalid"},
            413,
            "operator_payload_too_large",
        ),
        ("task.create", {"priority": "invalid"}, 422, "operator_validation"),
        ("task.create", {"title": 123}, 422, "operator_validation"),
        ("task.create", {"unknown": "field"}, 422, "operator_validation"),
        (
            "communication.record",
            {"participants": [{"partyId": "invalid", "role": "sender"}]},
            422,
            "operator_validation",
        ),
        (
            "maintenance.issue.create",
            {"reporter": {"unknown": "field"}},
            422,
            "operator_validation",
        ),
    ],
)
def test_nested_recovery_validation_api_status_and_no_writes(
    foundation, form, payload, status, code
):
    workspace, uow, service = foundation
    assert len(json.dumps(payload).encode()) < 65536
    assert_recovery_api_rejection(uow, service, form, payload, status, code)


def assert_recovery_api_rejection(uow, service, form, payload, status, code):
    tables = ("operator_recovery_records", "operator_operations", "audit_events")
    with uow.engine.connect() as connection:
        before = {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in tables
        }
    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_router(service))
    with TestClient(app) as client:
        response = client.put(
            "/api/operator/recovery/" + str(uuid4()),
            json={
                "formKey": form,
                "schemaVersion": 1,
                "payload": payload,
                "expectedRevision": 0,
                "idempotencyKey": str(uuid4()),
            },
        )
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code
    with uow.engine.connect() as connection:
        for table in tables:
            assert (
                connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                == before[table]
            )


def test_whole_recovery_payload_limit_api(foundation):
    assert_recovery_api_rejection(
        foundation[1],
        foundation[2],
        "communication.record",
        {"body": "a" * 65537},
        413,
        "operator_payload_too_large",
    )


def test_recovery_field_size_boundaries_are_accepted(foundation):
    workspace, uow, service = foundation
    payload = {
        "subject": "a" * 240,
        "body": "a" * 10000,
        "participants": [{"partyId": str(uuid4()), "role": "sender"}] * 100,
        "links": [{"entityType": "party", "entityId": str(uuid4())}] * 100,
    }
    result = save(service, form_key="communication.record", payload=payload)
    assert result["payload"] == payload
    validate_latest_schema(workspace.paths.database)


def test_production_composition_and_missing_reference(foundation):
    from app.bootstrap.api import create_app

    workspace = foundation[0]
    workspace.config.config_path.write_text(
        json.dumps({"localWorkspacePath": str(workspace.paths.root)}), encoding="utf-8"
    )
    app = create_app(workspace.config.config_path)
    with TestClient(app) as client:
        bootstrap = client.get("/api/operator/bootstrap")
        assert bootstrap.status_code == 200, bootstrap.text
        assert bootstrap.json()["state"] == "ready"
        record = client.put(
            "/api/operator/recovery/" + str(uuid4()),
            json={
                "formKey": "maintenance.issue.create",
                "schemaVersion": 1,
                "payload": {"propertyId": str(uuid4()), "summary": "Leak"},
                "expectedRevision": 0,
                "idempotencyKey": str(uuid4()),
            },
        )
        assert record.status_code == 409, record.text
        response = client.put(
            "/api/operator/recovery/" + str(uuid4()),
            json={
                "formKey": "communication.record",
                "schemaVersion": 1,
                "payload": {"subject": "unfinished call"},
                "expectedRevision": 0,
                "idempotencyKey": str(uuid4()),
            },
        )
        assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    ("failure", "state", "reason_code", "ordinary_status"),
    [
        (OperatorUnavailable, "busy", "workspace_busy", 503),
        (OperatorStorageFailure, "unavailable", "operator_storage_failure", 500),
    ],
)
def test_bootstrap_preserves_envelope_after_storage_read_failure(
    foundation, failure, state, reason_code, ordinary_status
):
    from app.bootstrap.api import create_app

    workspace = foundation[0]
    workspace.config.config_path.write_text(
        json.dumps({"localWorkspacePath": str(workspace.paths.root)}), encoding="utf-8"
    )
    app = create_app(workspace.config.config_path)
    with TestClient(app) as client:
        original = client.get("/api/operator/bootstrap").json()
        assert original["state"] == "ready"
        assert app.state.workspace_runtime.ready
        with patch.object(
            app.state.operator_service.unit_of_work,
            "read",
            side_effect=failure("Private storage path and driver details"),
        ):
            response = client.get("/api/operator/bootstrap")
            assert response.status_code == 200, response.text
            result = BootstrapResponse.model_validate(response.json())
            assert result.state == state
            assert result.reasonCode == reason_code
            assert result.preferencesState == "unavailable"
            assert result.preferences is None
            assert result.canWrite is False
            assert result.capabilities == []
            assert str(result.workspaceId) == original["workspaceId"]
            assert str(result.runtimeEpoch) == original["runtimeEpoch"]
            assert [action.action for action in result.recoveryActions] == ["getOperatorBootstrap"]
            assert "Private storage" not in response.text
            assert client.get("/api/operator/preferences").status_code == ordinary_status
            assert app.state.workspace_runtime.ready
        assert client.get("/api/operator/bootstrap").json() == original


def test_bootstrap_does_not_hide_unexpected_read_errors(foundation):
    service = foundation[2]
    app = FastAPI()
    app.include_router(build_router(service))
    with (
        TestClient(app) as client,
        patch.object(
            service.unit_of_work, "read", side_effect=RuntimeError("Unexpected programming failure")
        ),
    ):
        with pytest.raises(RuntimeError, match="Unexpected programming failure"):
            client.get("/api/operator/bootstrap")


def test_encrypted_backup_restore_preserves_records_and_replay(foundation):
    from app.modules.workspace.application.backup_service import BackupService
    from app.modules.workspace.application.service import WorkspacePaths

    workspace, uow, service = foundation
    preference_key = str(uuid4())
    original_preference = preferences(service, idempotency_key=preference_key)
    record = save(
        service,
        form_key="communication.record",
        payload={"subject": "Unfinished", "body": "Private recovery text"},
    )
    tables = ("operator_preferences", "operator_recovery_records", "operator_operations")
    with uow.engine.connect() as connection:
        before = {
            table: connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings().all()
            for table in tables
        }
        before_audits = (
            connection.execute(
                text("SELECT * FROM audit_events WHERE entity_type LIKE 'operator_%' ORDER BY id")
            )
            .mappings()
            .all()
        )
    backup = BackupService(
        workspace, uow.recorder, lambda database: AuditRecorder(SQLiteAuditRepository(database))
    )
    passphrase = "a long encrypted operator test passphrase"
    archive = backup.create_backup(
        passphrase, output_path=workspace.paths.root.parent / "operator.epmbackup"
    )
    restored = workspace.paths.root.parent / "restored"
    backup.restore(archive.archive_path, passphrase, restored)
    restored_uow = SQLiteOperatorUnitOfWork(
        WorkspacePaths(restored).database,
        AuditRecorder(SQLiteAuditRepository(WorkspacePaths(restored).database)),
        References(),
        SQLiteAuditReadMarker(),
    )
    try:
        with restored_uow.engine.connect() as connection:
            after = {
                table: connection.execute(text(f"SELECT * FROM {table} ORDER BY id"))
                .mappings()
                .all()
                for table in tables
            }
            after_audits = (
                connection.execute(
                    text(
                        "SELECT * FROM audit_events WHERE entity_type LIKE 'operator_%' ORDER BY id"
                    )
                )
                .mappings()
                .all()
            )
        assert before == after
        assert before_audits == after_audits
        restored_service = OperatorService(
            restored_uow,
            runtime=lambda: RuntimeIdentity(
                "ready", service.runtime().workspace_id, str(uuid4()), True
            ),
            now=service.now,
        )
        assert restored_service.operation(preference_key) == original_preference
        assert restored_service.recovery(record["id"])["payload"] == record["payload"]
        validate_latest_schema(WorkspacePaths(restored).database)
    finally:
        restored_uow.engine.dispose()


def test_concurrent_same_key_saves_one_receipt(foundation):
    workspace, uow, service = foundation
    barrier = Barrier(2)
    key, record_id = str(uuid4()), str(uuid4())

    def submit():
        barrier.wait(timeout=5)
        return save(service, record_id=record_id, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = pool.submit(submit), pool.submit(submit)
        assert one.result(timeout=10) == two.result(timeout=10)
    with uow.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM operator_operations")).scalar_one() == 1
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM audit_events WHERE entity_type='operator_recovery'")
            ).scalar_one()
            == 1
        )
    validate_latest_schema(workspace.paths.database)


def test_collection_count_and_slice_share_snapshot(foundation):
    workspace, uow, service = foundation
    original = save(service)
    triggered = False

    def between_reads(connection, cursor, statement, parameters, context, executemany):
        nonlocal triggered
        if triggered or "count(*)" not in statement or "operator_recovery_records" not in statement:
            return
        triggered = True
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(save, service).result(timeout=10)

    event.listen(uow.engine, "after_cursor_execute", between_reads)
    try:
        result = service.recovery_page()
    finally:
        event.remove(uow.engine, "after_cursor_execute", between_reads)
    assert triggered
    assert result["matchingTotal"] == 1
    assert [item["id"] for item in result["items"]] == [original["id"]]
    assert service.recovery_page()["matchingTotal"] == 2


def test_no_op_append_only_trigger_is_rejected(foundation):
    workspace, uow, service = foundation
    with uow.engine.begin() as connection:
        connection.execute(text("DROP TRIGGER operator_operations_no_update"))
        connection.execute(
            text(
                "CREATE TRIGGER operator_operations_no_update BEFORE UPDATE ON operator_operations BEGIN SELECT 1; END"
            )
        )
    with uow.engine.connect() as connection, pytest.raises(MigrationSchemaError):
        validate_operator_schema(connection)

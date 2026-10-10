"""Slice 37: source-owned concern commands and atomic original-result recovery."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import patch
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
from app.modules.operator.api.router import build_router
from app.modules.operator.application.command_forms import COMMAND_SCHEMAS, command_source_kind
from app.modules.operator.application.concern_forms import CONCERN_SCHEMAS
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.recovery_schemas import validate_payload
from app.modules.operator.application.service import OperatorService
from app.modules.operator.domain.models import OperatorConflict, OperatorError
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork
from app.modules.owner_management.api.router import build_router as concern_router
from app.modules.owner_management.infrastructure.recovery_reader import (
    SQLiteOwnerConcernRecoveryReader,
)
from app.modules.owner_management.tests import test_owner_concerns as fixtures
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.api_errors import register_api_error_handlers
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema


@pytest.fixture
def ready():
    fixture = fixtures.OwnerConcernTests()
    fixture.setUp()
    workspace = fixture.workspace
    workspace_id = workspace.open().workspace_id
    writer_id = str(uuid4())
    recorder = AuditRecorder(SQLiteAuditRepository(workspace.paths.database))
    references = OperatorRecoveryReferences(
        RecoverySourcePorts(SQLitePortfolioContextReader(), None, None),
        None,
        None,
        None,
        commands=compose_recovery_bindings(),
    )
    uow = SQLiteOperatorUnitOfWork(
        workspace.paths.database, recorder, references, SQLiteAuditReadMarker()
    )
    ops = OperatorService(
        uow,
        runtime=lambda: RuntimeIdentity("ready", workspace_id, writer_id, True),
    )
    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_router(ops))
    app.include_router(
        concern_router(fixture.service, SimpleNamespace(ready=True, error=None, can_write=True))
    )
    try:
        with TestClient(app) as client:
            yield fixture, ops, client, recorder
    finally:
        uow.engine.dispose()
        fixture.service.unit_of_work.engine.dispose()
        fixture.doCleanups()


def begin(ops, form, values, source=None):
    record, key = str(uuid4()), str(uuid4())
    ops.save_recovery(
        record,
        form_key=form,
        schema_version=1,
        payload=values,
        expected_revision=0,
        idempotency_key=str(uuid4()),
        source_kind=command_source_kind(form),
        source_id=source,
        base_source_revision=str(values["expectedRevision"]) if source else None,
    )
    ops.prepare_attempt(record, attempt_key=key, expected_revision=1, idempotency_key=str(uuid4()))
    return record, key


def run(ready, action, values, source=None):
    fixture, ops, client, recorder = ready
    record, key = begin(ops, "owner_concern." + action, values, source)
    with pytest.raises(OperatorConflict):
        ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    suffix = {
        "in_progress": "start",
        "open": "reopen",
        "resolved": "resolve",
        "dismissed": "dismiss",
        "follow_up": "follow-ups",
    }
    path = "/api/owner-concerns" + (f"/{source}" if source else "")
    if action in suffix:
        path += "/" + suffix[action]
    body = values | {"idempotencyKey": key}
    response = client.request("PATCH" if action == "patch" else "POST", path, json=body)
    assert response.status_code == 200, response.text
    original = response.json()
    receipt = ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))[
        "receipt"
    ]
    assert receipt["receiptId"] == original["operationId"]
    assert receipt["result"] == {
        "targetId": original["id"],
        "revision": original["revision"],
        "status": original["status"],
        "operationId": original["operationId"],
    }
    assert (
        client.request("PATCH" if action == "patch" else "POST", path, json=body).json() == original
    )
    return original, record, key


def create(ready, **changes):
    fixture = ready[0]
    return run(
        ready,
        "create",
        {
            "expectedRevision": 0,
            "ownerPartyId": fixture.owner.id,
            "propertyId": fixture.property.id,
            "concernType": "general_rental",
            "summary": "Concern",
            "description": "Details",
            "raisedAtUtc": fixture.now.isoformat(),
            **changes,
        },
    )


def test_all_forms_original_results_and_tasks(ready):
    fixture, ops, client, recorder = ready
    original, record, key = create(ready, followUp={"title": "Call owner", "priority": "high"})
    source = original["id"]
    patched, _, _ = run(ready, "patch", {"expectedRevision": 1, "summary": " Edited "}, source)
    noop, _, _ = run(ready, "patch", {"expectedRevision": 2, "summary": "Edited"}, source)
    assert noop["revision"] == patched["revision"]
    run(
        ready,
        "in_progress",
        {"expectedRevision": 2, "confirmed": True, "summary": "Ignored by start"},
        source,
    )
    run(ready, "open", {"expectedRevision": 3, "confirmed": True}, source)
    run(
        ready,
        "resolved",
        {"expectedRevision": 4, "confirmed": True, "summary": " Handled "},
        source,
    )
    run(
        ready,
        "open",
        {"expectedRevision": 5, "confirmed": True, "summary": " Follow-up needed "},
        source,
    )
    run(
        ready,
        "dismissed",
        {"expectedRevision": 6, "confirmed": True, "summary": " No further action "},
        source,
    )
    followed, _, _ = run(
        ready,
        "follow_up",
        {
            "expectedRevision": 7,
            "title": " Historical follow-up ",
            "notes": " Context ",
            "dueAtUtc": "2026-09-23T10:00:00-07:00",
            "dueTimezone": "America/Los_Angeles",
        },
        source,
    )
    assert followed["followUpTask"]["relatedEntityId"] == source
    assert followed["followUpTask"]["title"] == "Historical follow-up"
    assert client.get(f"/api/owner-concerns/operations/by-key/{key}").json() == original
    assert (
        client.get(f"/api/owner-concerns/operations/{original['operationId']}").json() == original
    )
    assert ops.recovery(record)["receipt"]["result"]["revision"] == 1
    validate_latest_schema(fixture.workspace.paths.database)


@pytest.mark.parametrize("action", ["create", "follow_up"])
def test_task_and_concern_rollback_then_recovery(ready, action):
    fixture, ops, client, recorder = ready
    source = None if action == "create" else create(ready)[0]["id"]
    values = (
        {"expectedRevision": 1, "title": "Call owner"}
        if source
        else {
            "expectedRevision": 0,
            "ownerPartyId": fixture.owner.id,
            "propertyId": fixture.property.id,
            "concernType": "general_rental",
            "summary": "Concern",
            "description": "Details",
            "raisedAtUtc": fixture.now.isoformat(),
            "followUp": {"title": "Call owner"},
        }
    )
    record, key = begin(ops, "owner_concern." + action, values, source)
    before = portable_rows(fixture.workspace.paths.database)
    with patch(
        "app.modules.owner_management.infrastructure.unit_of_work._Tx.insert_command_operation",
        side_effect=RuntimeError("receipt write failed"),
    ):
        with pytest.raises(RuntimeError, match="receipt write failed"):
            client.post(
                "/api/owner-concerns" + (f"/{source}/follow-ups" if source else ""),
                json=values | {"idempotencyKey": key},
            )
    assert portable_rows(fixture.workspace.paths.database) == before
    with pytest.raises(OperatorConflict):
        ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    response = client.post(
        "/api/owner-concerns" + (f"/{source}/follow-ups" if source else ""),
        json=values | {"idempotencyKey": key},
    )
    assert response.status_code == 200, response.text
    result = ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    assert result["receipt"]["receiptId"] == response.json()["operationId"]


def portable_rows(database):
    with sqlite3.connect(database) as connection:
        rows = {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in (
                "owner_concerns",
                "owner_concern_follow_up_operations",
                "owner_concern_command_operations",
                "tasks",
                "operator_recovery_records",
                "operator_operations",
            )
        }
        rows["audit_events"] = connection.execute(
            "SELECT * FROM audit_events WHERE entity_type LIKE 'owner_concern%' OR entity_type LIKE 'task%' OR entity_type LIKE 'operator%' ORDER BY rowid"
        ).fetchall()
        return rows


def test_original_indexed_receipt_backup_and_tampering(ready, tmp_path):
    fixture, ops, client, recorder = ready
    original, record, key = create(ready, followUp={"title": "Call"})
    run(
        ready,
        "resolved",
        {"expectedRevision": 1, "confirmed": True, "summary": "Handled"},
        original["id"],
    )
    uow = fixture.service.unit_of_work
    statements = []

    def capture(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    with uow.engine.connect() as connection:
        event.listen(uow.engine, "before_cursor_execute", capture)
        try:
            with patch.object(
                uow.engine, "connect", side_effect=AssertionError("nested connection")
            ):
                outcome = SQLiteOwnerConcernRecoveryReader().outcome(
                    connection, key, family="owner_concern"
                )
            assert len(statements) == 1
            assert outcome.result.revision == 1 and outcome.result.status == "open"
            assert outcome.operation_id == original["operationId"]
        finally:
            event.remove(uow.engine, "before_cursor_execute", capture)
    before = portable_rows(fixture.workspace.paths.database)
    backup = BackupService(
        fixture.workspace, recorder, lambda database: AuditRecorder(SQLiteAuditRepository(database))
    )
    with fast_backup_encryption():
        archive = backup.create_backup(
            "a sufficiently long passphrase", output_path=tmp_path / "concerns.epm-backup"
        )
        backup.restore(
            archive.archive_path, "a sufficiently long passphrase", tmp_path / "restored"
        )
    restored = tmp_path / "restored/database/property-management.sqlite"
    validate_latest_schema(restored)
    assert portable_rows(restored) == before
    with sqlite3.connect(restored) as connection:
        connection.execute(
            "UPDATE operator_recovery_records SET request_fingerprint=? WHERE id=?",
            ("0" * 64, record),
        )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(restored)


def test_stale_lifecycle_and_changed_receipt(ready):
    fixture, ops, client, recorder = ready
    original, _, _ = create(ready)
    source = original["id"]
    record, key = begin(
        ops, "owner_concern.patch", {"expectedRevision": 1, "summary": "Intended"}, source
    )
    response = client.patch(
        f"/api/owner-concerns/{source}",
        json={"expectedRevision": 1, "summary": "Different", "idempotencyKey": key},
    )
    assert response.status_code == 200
    with pytest.raises(OperatorConflict):
        ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    assert ops.recovery(record)["reuseState"] == "outcome_unknown"
    with pytest.raises(OperatorConflict):
        begin(ops, "owner_concern.patch", {"expectedRevision": 1, "summary": "Stale"}, source)
    run(
        ready,
        "dismissed",
        {"expectedRevision": 2, "confirmed": True, "summary": "Dismissed"},
        source,
    )
    with pytest.raises(OperatorConflict):
        begin(ops, "owner_concern.patch", {"expectedRevision": 3, "summary": "Terminal"}, source)
    record, key = begin(
        ops, "owner_concern.open", {"expectedRevision": 3, "confirmed": True}, source
    )
    response = client.post(
        f"/api/owner-concerns/{source}/reopen",
        json={"expectedRevision": 3, "confirmed": True, "idempotencyKey": key},
    )
    assert response.status_code == 400
    with pytest.raises(OperatorConflict):
        ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))


@pytest.mark.parametrize(
    "form,payload",
    [
        ("create", {"expectedRevision": True}),
        ("create", {"ownerPartyId": "invalid"}),
        ("create", {"description": "x" * 10001}),
        ("patch", {"unexpected": "field"}),
        ("resolved", {"confirmed": 1}),
        ("follow_up", {"dueAtUtc": "2026-09-21T10:00:00"}),
    ],
)
def test_invalid_typed_forms(form, payload):
    with pytest.raises(OperatorError):
        validate_payload("owner_concern." + form, 1, payload)


@pytest.mark.parametrize(
    "action,values",
    [
        ("create", {"expectedRevision": 0}),
        ("follow_up", {"expectedRevision": 1}),
        ("follow_up", {"expectedRevision": 1, "title": "Call", "dueAtUtc": "2026-09-23T10:00:00Z"}),
        ("resolved", {"expectedRevision": 1, "confirmed": True}),
        ("in_progress", {"expectedRevision": 1, "confirmed": False}),
    ],
)
def test_incomplete_forms_cannot_prepare(ready, action, values):
    ops = ready[1]
    source = None if action == "create" else create(ready)[0]["id"]
    with pytest.raises((OperatorError, OperatorConflict)):
        begin(ops, "owner_concern." + action, values, source)


def test_no_workspace_openapi_contract():
    first, second = FastAPI(), FastAPI()
    for app in (first, second):
        app.include_router(build_router(None))
        app.include_router(concern_router(None, None))
    assert first.openapi() == second.openapi()
    assert len(CONCERN_SCHEMAS) == 7
    assert set(CONCERN_SCHEMAS) <= set(COMMAND_SCHEMAS) == set(compose_recovery_bindings())
    schema = first.openapi()
    models = schema["components"]["schemas"]
    assert (
        "owner_concern" in models["RecoveryInput"]["properties"]["sourceKind"]["anyOf"][0]["enum"]
    )
    mutations = [
        operation
        for path, methods in schema["paths"].items()
        if path.startswith("/api/owner-concerns")
        for method, operation in methods.items()
        if method in {"post", "patch"}
    ]
    assert len(mutations) == 7
    for operation in mutations:
        assert operation["operationId"] and "409" in operation["responses"]
        request = models[
            operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
        ]
        assert {"expectedRevision", "idempotencyKey"} <= set(request["required"])
        response = models[
            operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].split(
                "/"
            )[-1]
        ]
        assert {"revision", "operationId"} <= set(response["required"])

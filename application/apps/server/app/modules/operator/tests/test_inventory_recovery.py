"""Slice 41: source-owned inventory receipts through real OPS/HTTP boundaries."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.bootstrap.operator_recovery import OperatorRecoveryReferences, RecoverySourcePorts
from app.bootstrap.operator_recovery_composition import compose_recovery_bindings
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.operator.api.router import build_router as ops_router
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.service import OperatorService
from app.modules.operator.application.recovery_schemas import validate_payload
from app.modules.operator.application.inventory_forms import INVENTORY_SCHEMAS
from app.modules.operator.application.command_forms import COMMAND_SCHEMAS, command_source_kind
from app.modules.operator.domain.models import OperatorConflict, OperatorError
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork
from app.modules.portfolio.api.router import build_router
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.portfolio.tests import test_portfolio as portfolio_fixtures
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.test_backup_service import MemorySecretStore
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.platform.api_errors import register_api_error_handlers
from app.platform.product_migrations import validate_latest_schema
from app.platform.migration_errors import MigrationSchemaError

EXPECTED_EXPLICIT_FORM_COUNT = 192
APPROVED_INVENTORY_FORM_COUNT = 9


@pytest.fixture
def fixture():
    case = portfolio_fixtures.PortfolioTests()
    case.setUp()
    try:
        yield case
    finally:
        case.service.unit_of_work.engine.dispose()
        case.doCleanups()


@pytest.fixture
def ready(fixture):
    manifest = fixture.workspace.open()
    references = OperatorRecoveryReferences(
        RecoverySourcePorts(SQLitePortfolioContextReader(), None, None),
        None,
        None,
        None,
        commands=compose_recovery_bindings(),
    )
    uow = SQLiteOperatorUnitOfWork(
        fixture.workspace.paths.database,
        AuditRecorder(fixture.audit),
        references,
        SQLiteAuditReadMarker(),
    )
    ops = OperatorService(
        uow,
        runtime=lambda: RuntimeIdentity(
            "ready",
            manifest.workspace_id,
            "slice41-writer",
            True,
        ),
    )
    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(ops_router(ops))
    app.include_router(
        build_router(fixture.service, SimpleNamespace(ready=True, error=None, can_write=True))
    )
    with TestClient(app) as client:
        yield SimpleNamespace(case=fixture, ops=ops, client=client, uow=uow)
    uow.engine.dispose()


def begin(ready, form, payload, source=None):
    record, key = str(uuid4()), str(uuid4())
    ready.ops.save_recovery(
        record,
        form_key=form,
        schema_version=1,
        payload=payload,
        expected_revision=0,
        idempotency_key=str(uuid4()),
        source_kind="property" if source else None,
        source_id=source,
        base_source_revision=str(payload["expectedPropertyRevision"]) if source else None,
    )
    ready.ops.prepare_attempt(
        record, attempt_key=key, expected_revision=1, idempotency_key=str(uuid4())
    )
    return record, key


def run(ready, form, destination, payload, *, source=None):
    method, path = destination
    record, key = begin(ready, form, payload, source)
    body = {k: v for k, v in payload.items() if k not in {"spaceId", "changes"}}
    body.update(payload.get("changes") or {})
    body["idempotencyKey"] = key
    response = ready.client.request(method, path, json=body)
    assert response.status_code in {200, 201}, response.text
    original = response.json()
    recovered = ready.ops.reconcile_recovery(
        record, expected_revision=2, idempotency_key=str(uuid4())
    )
    receipt = recovered["receipt"]
    assert receipt["receiptId"] == original["operationId"]
    assert receipt["sourceKind"] == "property"
    assert receipt["sourceId"] == (source or original["id"])
    assert receipt["result"]["targetId"] == original["id"]
    assert receipt["result"]["revision"] == original["propertyRevision"]
    assert ready.client.request(method, path, json=body).json() == original
    return original, record, body


def create(ready, name="Recovery office"):
    return run(
        ready,
        "portfolio.property.create",
        ("POST", "/api/properties"),
        {
            "expectedPropertyRevision": 0,
            "displayName": name,
            "addressLine1": "10 Oak Road",
            "city": "Portland",
            "region": "OR",
            "countryCode": "US",
            "propertyType": "office",
            "inventoryLayout": "office_suites",
            "ownerships": [{"ownerKind": "local_operator"}],
            "spaces": [
                {"displayName": "Suite A", "availability": {"availabilityStatus": "not_available"}}
            ],
        },
    )


def test_all_nine_commands_original_receipts_and_later_replay(ready):
    original, _, create_body = create(ready)
    parent, child = original["id"], original["spaces"][0]["id"]
    revision = original["propertyRevision"]
    replays = []
    operations = [
        ("property.patch", "PATCH", f"/api/properties/{parent}", {"changes": {"notes": "edit"}}),
        (
            "ownerships.replace",
            "PUT",
            f"/api/properties/{parent}/ownerships",
            {
                "effectiveOn": original["effectiveLocalDate"],
                "ownerships": [
                    {
                        "ownerKind": "client_owner",
                        "inlineParty": {"partyKind": "individual", "displayName": "Inline Owner"},
                    }
                ],
            },
        ),
        ("space.create", "POST", f"/api/properties/{parent}/spaces", {"displayName": "Suite B"}),
        (
            "space.patch",
            "PATCH",
            f"/api/spaces/{child}",
            {"spaceId": child, "changes": {"notes": "child edit"}},
        ),
        (
            "space.archive",
            "POST",
            f"/api/spaces/{child}/archive",
            {"spaceId": child, "confirmed": True},
        ),
        ("space.restore", "POST", f"/api/spaces/{child}/restore", {"spaceId": child}),
        ("property.archive", "POST", f"/api/properties/{parent}/archive", {"confirmed": True}),
        ("property.restore", "POST", f"/api/properties/{parent}/restore", {}),
    ]
    for suffix, method, path, values in operations:
        result, _, body = run(
            ready,
            f"portfolio.{suffix}",
            (method, path),
            {"expectedPropertyRevision": revision, **values},
            source=parent,
        )
        revision = result["propertyRevision"]
        replays.append((method, path, body, result))
    for method, path, body, result in replays:
        assert ready.client.request(method, path, json=body).json() == result
    assert ready.client.post("/api/properties", json=create_body).json() == original
    changed = ready.client.post("/api/properties", json={**create_body, "displayName": "Changed"})
    assert changed.status_code == status.HTTP_409_CONFLICT
    validate_latest_schema(ready.case.workspace.paths.database)


def test_incomplete_foreign_child_and_stale_preparation(ready):
    record = str(uuid4())
    ready.ops.save_recovery(
        record,
        form_key="portfolio.property.create",
        schema_version=1,
        payload={},
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    with pytest.raises(OperatorError):
        ready.ops.prepare_attempt(
            record, attempt_key=str(uuid4()), expected_revision=1, idempotency_key=str(uuid4())
        )
    first, _, _ = create(ready)
    second, _, _ = create(ready, "Other")
    with pytest.raises(OperatorConflict):
        begin(
            ready,
            "portfolio.space.patch",
            {
                "expectedPropertyRevision": 1,
                "spaceId": second["spaces"][0]["id"],
                "changes": {"notes": "foreign"},
            },
            first["id"],
        )
    with pytest.raises(OperatorConflict):
        begin(
            ready,
            "portfolio.property.patch",
            {"expectedPropertyRevision": 0, "changes": {"notes": "stale"}},
            first["id"],
        )


@pytest.mark.parametrize("form", list(INVENTORY_SCHEMAS))
def test_forms_are_bounded_and_explicit(form):
    assert validate_payload(form, 1, {}) == {}
    with pytest.raises(OperatorError):
        validate_payload(form, 1, {"secret": "not permitted"})


def test_registry_count_and_existing_status_contracts():
    bindings = compose_recovery_bindings()
    assert set(bindings) == set(COMMAND_SCHEMAS)
    assert len(COMMAND_SCHEMAS) == EXPECTED_EXPLICIT_FORM_COUNT
    assert len(INVENTORY_SCHEMAS) == APPROVED_INVENTORY_FORM_COUNT
    for form in INVENTORY_SCHEMAS:
        assert bindings[form].source_kind == command_source_kind(form)
    status_forms = {key for key, binding in bindings.items() if binding.family == "status"}
    assert status_forms == {
        "portfolio.occupancy.change",
        "portfolio.occupancy.cancel",
        "portfolio.occupancy.replace",
        "portfolio.occupancy.correct",
        "portfolio.occupancy.reschedule",
        "portfolio.availability.change",
        "portfolio.space.classify",
    }


def test_failed_domain_audit_rolls_back_receipt_and_inventory(ready):
    original, _, _ = create(ready)
    parent = original["id"]
    values = {"expectedPropertyRevision": 1, "changes": {"notes": "rollback"}}
    record, key = begin(ready, "portfolio.property.patch", values, parent)
    recorder = ready.case.service.unit_of_work.recorder
    original_record = recorder.record_change

    def fail_operation(*args, **kwargs):
        if kwargs.get("entity_type") == "portfolio_inventory_operation":
            raise RuntimeError("required audit unavailable")
        return original_record(*args, **kwargs)

    body = {"expectedPropertyRevision": 1, "notes": "rollback", "idempotencyKey": key}
    with patch.object(recorder, "record_change", side_effect=fail_operation):
        with pytest.raises(RuntimeError, match="required audit unavailable"):
            ready.client.patch(f"/api/properties/{parent}", json=body)
    assert ready.case.service.unit_of_work.get_property(parent).property_revision == 1
    with pytest.raises(OperatorConflict):
        ready.ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))
    response = ready.client.patch(f"/api/properties/{parent}", json=body)
    assert response.status_code == status.HTTP_200_OK
    ready.ops.reconcile_recovery(record, expected_revision=2, idempotency_key=str(uuid4()))


def test_nested_limits_and_revision_types():
    for payload in (
        {"expectedPropertyRevision": True},
        {"spaces": [{"displayName": "A"}] * 101},
        {"ownerships": [{"ownerKind": "local_operator"}] * 101},
        {"spaces": [{"occupancy": {"idempotencyKey": "not an initial-status field"}}]},
    ):
        with pytest.raises(OperatorError):
            validate_payload("portfolio.property.create", 1, payload)


def test_indexed_single_query_on_caller_snapshot(ready):
    original, _, body = create(ready)
    reader = compose_recovery_bindings()["portfolio.property.create"].reader
    engine = ready.case.service.unit_of_work.engine
    statements = []

    def listener(conn, cursor, sql, *args):
        statements.append(sql)

    event.listen(engine, "before_cursor_execute", listener)
    try:
        with (
            engine.connect() as connection,
            patch.object(engine, "connect", side_effect=AssertionError("nested")),
        ):
            result = reader.outcome(connection, body["idempotencyKey"], family="inventory")
            assert result.operation_id == original["operationId"]
            plan = connection.exec_driver_sql(
                "EXPLAIN QUERY PLAN SELECT id FROM portfolio_inventory_operations "
                "WHERE idempotency_key=?",
                (body["idempotencyKey"],),
            ).fetchall()
            assert any("INDEX" in row[3] for row in plan)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert sum(sql.lstrip().upper().startswith("SELECT") for sql in statements) == 1


def test_ops_and_inventory_encrypted_portability_and_tampering(ready, tmp_path):
    original, _, body = create(ready)
    database = ready.case.workspace.paths.database
    tables = ("portfolio_inventory_operations", "operator_recovery_records", "operator_operations")

    def rows(path):
        with sqlite3.connect(path) as connection:
            retained = {
                table: connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                for table in tables
            }
            retained["audits"] = connection.execute(
                "SELECT * FROM audit_events WHERE entity_type IN "
                "('property','space','property_ownership','portfolio_inventory_operation') "
                "ORDER BY id"
            ).fetchall()
            return retained

    expected = rows(database)
    backups = BackupService(
        ready.case.workspace,
        AuditRecorder(ready.case.audit),
        lambda path: AuditRecorder(SQLiteAuditRepository(path)),
        MemorySecretStore(),
    )
    with fast_backup_encryption():
        archive = backups.create_backup(
            "Slice41 encrypted recovery", output_path=tmp_path / "inventory.epmbackup"
        )
        restored = backups.restore(
            archive.archive_path, "Slice41 encrypted recovery", tmp_path / "restored"
        )
    restored_database = restored.workspace_path / "database" / "property-management.sqlite"
    assert rows(restored_database) == expected
    validate_latest_schema(restored_database)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE operator_recovery_records SET payload_json='{}'")
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(database)
    assert original["id"] and body["idempotencyKey"]

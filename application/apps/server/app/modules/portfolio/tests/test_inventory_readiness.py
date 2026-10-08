"""Real SQLite command-safety proofs for UI-001 Slice 14."""

import inspect
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.portfolio.application.ports import PortfolioConflictError
from app.modules.portfolio.application.service import (
    AvailabilityCommand,
    OwnershipInput,
    PortfolioError,
    PortfolioNotFoundError,
    PortfolioService,
    PropertyCreateCommand,
    SpaceCreateCommand,
)
from app.modules.portfolio.infrastructure.inventory_triggers import INVENTORY_TRIGGERS
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioUnitOfWork
from app.modules.portfolio.tests import test_portfolio as fixtures
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.test_backup_service import MemorySecretStore
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema
from app.platform.sqlite_engine import immediate_transaction


@pytest.fixture
def fixture():
    case = fixtures.PortfolioTests()
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()


def _command():
    return PropertyCreateCommand(
        "Slice 14 office",
        "10 Oak Road",
        "Portland",
        "US",
        "office",
        (OwnershipInput("local_operator"),),
        region="OR",
        inventory_layout="office_suites",
        spaces=(SpaceCreateCommand("Suite A"), SpaceCreateCommand("Suite B")),
    )


def _create(fixture, key="create"):
    return fixture.service.create_property(_command(), expected_revision=0, idempotency_key=key)


def _call(service, action, target, *args, **kwargs):
    property_id = target
    if action in {"patch_space", "archive_space", "restore_space"}:
        property_id = service.unit_of_work.get_space(target).property_id
    return getattr(service, action)(
        target,
        *args,
        expected_revision=service.unit_of_work.get_property(property_id).property_revision,
        idempotency_key=str(uuid4()),
        **kwargs,
    )


def test_creation_original_replay_and_space_changes_share_parent_revision(fixture):
    original = _create(fixture)
    space_id = original["spaces"][0]["id"]
    patched = fixture.service.patch_space(
        space_id, {"notes": "first"}, expected_revision=1, idempotency_key="space-edit"
    )
    assert patched["propertyRevision"] == 2
    later = _call(fixture.service, "patch_property", original["id"], {"notes": "later"})
    assert later["propertyRevision"] == 3
    assert _create(fixture) == original
    assert (
        fixture.service.patch_space(
            space_id, {"notes": "first"}, expected_revision=1, idempotency_key="space-edit"
        )
        == patched
    )
    assert (
        fixture.service.get_inventory_operation(operation_id=patched["operationId"])["result"]
        == patched
    )
    with pytest.raises(PortfolioConflictError) as conflict:
        fixture.service.archive_space(
            space_id, confirmed=True, expected_revision=1, idempotency_key="stale"
        )
    assert conflict.value.code == "portfolio_inventory_revision_conflict"
    assert conflict.value.current_status["propertyRevision"] == 3
    assert fixture.service.get_space_status(space_id)["revision"] == 0
    validate_latest_schema(fixture.workspace.paths.database)


def test_noop_commands_preserve_timestamps_and_revision(fixture):
    original = _create(fixture)
    instant = datetime.fromisoformat(original["updatedAt"]) + timedelta(hours=1)
    with patch.object(fixture.service, "_instant", return_value=instant):
        noops = [
            _call(
                fixture.service,
                "patch_property",
                original["id"],
                {"displayName": original["displayName"]},
            ),
            _call(fixture.service, "restore_property", original["id"]),
            _call(fixture.service, "patch_space", original["spaces"][0]["id"], {"notes": None}),
            _call(fixture.service, "restore_space", original["spaces"][0]["id"]),
            _call(
                fixture.service,
                "replace_ownerships",
                original["id"],
                (OwnershipInput("local_operator"),),
                original["effectiveLocalDate"],
            ),
        ]
    for result in noops:
        assert result["propertyRevision"] == 1
        assert result["updatedAt"] == original["updatedAt"]
        assert (
            fixture.service.get_inventory_operation(operation_id=result["operationId"])["effective"]
            is False
        )
    validate_latest_schema(fixture.workspace.paths.database)


def test_independent_status_revision_does_not_change_property_revision(fixture):
    original = _create(fixture)
    space_id = original["spaces"][0]["id"]
    fixture.service.change_availability(
        space_id,
        AvailabilityCommand("available_now"),
        expected_revision=0,
        idempotency_key="status",
    )
    patched = fixture.service.patch_space(
        space_id, {"notes": "inventory"}, expected_revision=1, idempotency_key="inventory"
    )
    assert patched["propertyRevision"] == 2
    assert patched["revision"] == 1
    assert fixture.service.get_property(original["id"])["propertyRevision"] == 2
    validate_latest_schema(fixture.workspace.paths.database)


def test_lifecycle_cascades_increment_once_and_replay_without_recascading(fixture):
    original = _create(fixture)
    property_id, first_space = original["id"], original["spaces"][0]["id"]
    manual = _call(fixture.service, "archive_space", first_space, confirmed=True)
    assert manual["propertyRevision"] == 2
    added = _call(fixture.service, "add_space", property_id, SpaceCreateCommand("Suite C"))
    assert added["propertyRevision"] == 3
    archived = fixture.service.archive_property(
        property_id, confirmed=True, expected_revision=3, idempotency_key="cascade"
    )
    assert archived["propertyRevision"] == 4
    assert all(item["status"] == "archived" for item in archived["spaces"])
    restored = _call(fixture.service, "restore_property", property_id)
    assert restored["propertyRevision"] == 5
    assert (
        next(item for item in restored["spaces"] if item["id"] == first_space)["status"]
        == "archived"
    )
    before_audits = len(fixture.audit.history())
    assert (
        fixture.service.archive_property(
            property_id, confirmed=True, expected_revision=3, idempotency_key="cascade"
        )
        == archived
    )
    assert len(fixture.audit.history()) == before_audits
    assert fixture.service.get_property(property_id)["status"] == "active"
    validate_latest_schema(fixture.workspace.paths.database)


def test_space_restore_and_global_changed_reuse(fixture):
    original = _create(fixture)
    space_id = original["spaces"][0]["id"]
    _call(fixture.service, "archive_space", space_id, confirmed=True)
    restored = fixture.service.restore_space(
        space_id, expected_revision=2, idempotency_key="restore-space"
    )
    assert restored["propertyRevision"] == 3 and restored["status"] == "active"
    _call(fixture.service, "archive_space", space_id, confirmed=True)
    assert (
        fixture.service.restore_space(
            space_id, expected_revision=2, idempotency_key="restore-space"
        )
        == restored
    )
    with pytest.raises(PortfolioConflictError) as conflict:
        fixture.service.restore_space(
            original["spaces"][1]["id"], expected_revision=2, idempotency_key="restore-space"
        )
    assert conflict.value.code == "portfolio_inventory_payload_conflict"
    validate_latest_schema(fixture.workspace.paths.database)


def test_ownership_replacement_is_atomic_keyed_and_property_local(fixture):
    instant = datetime(2026, 10, 9, 1, 0, tzinfo=UTC)
    with patch.object(fixture.service, "_instant", return_value=instant):
        original = _create(fixture)
        assert original["effectiveLocalDate"] == "2026-10-08"
        owner = fixture._party()
        inputs = (OwnershipInput("client_owner", owner.id),)
        result = fixture.service.replace_ownerships(
            original["id"], inputs, "2026-10-08", expected_revision=1, idempotency_key="ownership"
        )
    assert result["asOf"] == instant.isoformat()
    assert result["updatedAt"] == instant.isoformat()
    assert result["ownershipContext"] == "managed_for_owner"
    assert result["propertyRevision"] == 2
    assert (
        fixture.service.replace_ownerships(
            original["id"], inputs, "2026-10-08", expected_revision=1, idempotency_key="ownership"
        )
        == result
    )
    with pytest.raises(PortfolioConflictError):
        fixture.service.replace_ownerships(
            original["id"], inputs, "2026-10-09", expected_revision=1, idempotency_key="ownership"
        )
    validate_latest_schema(fixture.workspace.paths.database)


@pytest.mark.parametrize("failure", ["receipt_audit", "commit"])
def test_receipt_audit_and_commit_failure_roll_back_cascade(fixture, failure):
    original = _create(fixture)
    recorder = fixture.service.unit_of_work.recorder
    real = recorder.record_change

    def reject(*args, **kwargs):
        if kwargs.get("entity_type") == "portfolio_inventory_operation":
            raise RuntimeError("receipt audit failure")
        return real(*args, **kwargs)

    @contextmanager
    def failed_commit(engine):
        with immediate_transaction(engine) as connection:
            yield connection
            raise RuntimeError("commit failure")

    context = (
        patch.object(recorder, "record_change", side_effect=reject)
        if failure == "receipt_audit"
        else patch(
            "app.modules.portfolio.infrastructure.unit_of_work.immediate_transaction", failed_commit
        )
    )
    audit_count = len(fixture.audit.history())
    with context, pytest.raises(RuntimeError):
        fixture.service.archive_property(
            original["id"], confirmed=True, expected_revision=1, idempotency_key="failed"
        )
    current = fixture.service.get_property(original["id"])
    assert current["status"] == "active" and current["propertyRevision"] == 1
    assert all(item["status"] == "active" for item in current["spaces"])
    assert len(fixture.audit.history()) == audit_count
    with pytest.raises(PortfolioNotFoundError):
        fixture.service.get_inventory_operation(idempotency_key="failed")
    validate_latest_schema(fixture.workspace.paths.database)


def test_one_indexed_query_recovery_is_read_only(fixture):
    original = _create(fixture)
    statements = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement)

    engine = fixture.service.unit_of_work.engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        receipt = fixture.service.get_inventory_operation(operation_id=original["operationId"])
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert receipt["result"] == original
    selects = [
        statement for statement in statements if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(selects) == 1
    assert not any(
        statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for statement in statements
    )


def test_application_signatures_and_invalid_metadata(fixture):
    actions = (
        "create_property",
        "patch_property",
        "archive_property",
        "restore_property",
        "replace_ownerships",
        "add_space",
        "patch_space",
        "archive_space",
        "restore_space",
    )
    for action in actions:
        signature = inspect.signature(getattr(fixture.service, action))
        for name in ("expected_revision", "idempotency_key"):
            assert signature.parameters[name].default is inspect.Parameter.empty
    for revision in (True, -1, "0", None):
        with pytest.raises(PortfolioError):
            fixture.service.create_property(
                _command(), expected_revision=revision, idempotency_key="bad"
            )
    for key in ("", " ", " spaced ", "x" * 201, None):
        with pytest.raises(PortfolioError):
            fixture.service.create_property(_command(), expected_revision=0, idempotency_key=key)


def test_concurrent_same_key_creation_has_one_effect(fixture):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _create(fixture), range(2)))
    assert results[0] == results[1]
    with sqlite3.connect(fixture.workspace.paths.database) as connection:
        assert (
            connection.execute("SELECT count(*) FROM portfolio_inventory_operations").fetchone()[0]
            == 1
        )
        assert connection.execute("SELECT count(*) FROM properties").fetchone()[0] == 1
    validate_latest_schema(fixture.workspace.paths.database)


def test_api_required_contracts_conflict_and_original_response_recovery(fixture):
    config = Path(fixture.temp.name) / "inventory-api.json"
    config.write_text(json.dumps({"localWorkspacePath": str(fixture.workspace.paths.root)}))
    payload = {
        "displayName": "API home",
        "addressLine1": "1 Main Street",
        "city": "Portland",
        "region": "OR",
        "countryCode": "US",
        "propertyType": "single_family_home",
        "ownerships": [{"ownerKind": "local_operator"}],
    }
    with TestClient(create_app(config)) as client:
        assert client.post("/api/properties", json=payload).status_code == 422
        payload.update(expectedPropertyRevision=0, idempotencyKey="api-create")
        original = client.post("/api/properties", json=payload)
        assert original.status_code == 201, original.text
        property_id = original.json()["id"]
        stale = client.patch(
            f"/api/properties/{property_id}",
            json={"notes": "stale", "expectedPropertyRevision": 0, "idempotencyKey": "stale"},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["currentStatus"]["propertyRevision"] == 1
        assert (
            client.patch(
                f"/api/properties/{property_id}",
                json={"notes": "later", "expectedPropertyRevision": 1, "idempotencyKey": "later"},
            ).status_code
            == 200
        )
        assert client.post("/api/properties", json=payload).json() == original.json()
        by_id = client.get(f"/api/portfolio/inventory-operations/{original.json()['operationId']}")
        by_key = client.get(
            f"/api/properties/{property_id}/inventory-operations/by-key",
            params={"idempotencyKey": "api-create"},
        )
        assert by_id.status_code == 200 and by_id.json() == by_key.json()
        assert (
            client.get(
                "/api/portfolio/inventory-operations/by-key",
                params={"idempotencyKey": "api-create"},
            ).json()
            == by_id.json()
        )
        assert by_id.json()["result"] == original.json()
        schema = client.get("/openapi.json").json()
        assert (
            schema["paths"]["/api/properties"]["post"]["operationId"] == "createPortfolioProperty"
        )
        assert {"propertyRevision", "operationId"}.issubset(
            schema["components"]["schemas"]["PropertyMutationResponse"]["required"]
        )
        assert (
            client.post(
                "/api/properties", json={**payload, "expectedPropertyRevision": True}
            ).status_code
            == 422
        )
    validate_latest_schema(fixture.workspace.paths.database)


@pytest.mark.parametrize("tamper", ["inventory", "receipt", "audit", "trigger"])
def test_retained_tampering_rejected(fixture, tamper):
    _create(fixture)
    with sqlite3.connect(fixture.workspace.paths.database) as connection:
        if tamper == "inventory":
            connection.execute("UPDATE spaces SET notes='offline rewrite'")
        elif tamper == "receipt":
            connection.execute("DROP TRIGGER portfolio_inventory_operations_no_update")
            connection.execute("UPDATE portfolio_inventory_operations SET response_json='{}'")
            connection.execute(INVENTORY_TRIGGERS["portfolio_inventory_operations_no_update"])
        elif tamper == "audit":
            connection.execute("DROP TRIGGER audit_events_no_delete")
            connection.execute(
                "DELETE FROM audit_events WHERE entity_type='portfolio_inventory_operation'"
            )
            connection.execute(
                "CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"
            )
        else:
            connection.execute("DROP TRIGGER portfolio_inventory_operations_no_update")
            connection.execute(
                "CREATE TRIGGER portfolio_inventory_operations_no_update BEFORE UPDATE ON portfolio_inventory_operations BEGIN SELECT 1; END"
            )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(fixture.workspace.paths.database)


def test_receipts_reject_update_delete_and_replace(fixture):
    _create(fixture)
    with sqlite3.connect(fixture.workspace.paths.database) as connection:
        for sql in (
            "UPDATE portfolio_inventory_operations SET action='patch_property'",
            "DELETE FROM portfolio_inventory_operations",
            "INSERT OR REPLACE INTO portfolio_inventory_operations SELECT * FROM portfolio_inventory_operations",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                connection.execute(sql)


def test_encrypted_backup_preserves_history_and_original_replay(fixture):
    original = _create(fixture)
    _call(fixture.service, "archive_property", original["id"], confirmed=True)
    _call(fixture.service, "restore_property", original["id"])
    with sqlite3.connect(fixture.workspace.paths.database) as connection:
        expected = connection.execute(
            "SELECT * FROM portfolio_inventory_operations ORDER BY id"
        ).fetchall()
    backups = BackupService(
        fixture.workspace,
        AuditRecorder(fixture.audit),
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
        MemorySecretStore(),
    )
    archive = backups.create_backup(
        "slice14 encrypted receipt portability",
        output_path=Path(fixture.temp.name) / "inventory.epmbackup",
    )
    restored = backups.restore(
        archive.archive_path,
        "slice14 encrypted receipt portability",
        Path(fixture.temp.name) / "restored",
    )
    database = restored.workspace_path / "database" / "property-management.sqlite"
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT * FROM portfolio_inventory_operations ORDER BY id"
            ).fetchall()
            == expected
        )
    service = PortfolioService(
        SQLitePortfolioUnitOfWork(database, AuditRecorder(SQLiteAuditRepository(database))),
        time_zone_resolver=BundledAddressTimeZoneResolver(),
    )
    assert (
        service.create_property(_command(), expected_revision=0, idempotency_key="create")
        == original
    )
    assert (
        service.get_inventory_operation(operation_id=original["operationId"])["result"] == original
    )
    validate_latest_schema(database)

"""Slice 21 real SQLite identity commands and portable immutable receipts."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.parties.api.router import build_router
from app.modules.parties.application.service import (
    ContactMethodCommand,
    PartyConflictError,
    PartyContactService,
    PartyCreateCommand,
    PartyIdentityService,
    PartyPatchCommand,
    PartyValidationError,
)
from app.modules.parties.infrastructure.unit_of_work import (
    SQLitePartyOperations,
    SQLitePartyReadOperations,
    SQLitePartyUnitOfWork,
)
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema
from app.platform.sqlite_engine import create_sqlite_engine
from app.modules.parties.infrastructure.schema_validation import validate_party_schema


@pytest.fixture
def identities(tmp_path):
    workspace = WorkspaceService(
        LocalConfig(
            config_path=tmp_path / "config.json",
            workspace_path=tmp_path / "workspace",
            backup_destination_path=tmp_path / "backups",
        )
    )
    workspace.initialize()
    database = workspace.paths.database
    recorder = AuditRecorder(SQLiteAuditRepository(database))
    uow = SQLitePartyUnitOfWork(database, recorder)
    reads = SQLitePartyOperations(database)
    service = PartyIdentityService(uow, SQLitePartyReadOperations(reads))
    yield workspace, service, recorder
    uow.engine.dispose()
    reads.engine.dispose()


def create(service, key=None):
    return service.create(
        PartyCreateCommand("individual", "Original"),
        contacts=(ContactMethodCommand("email", "original@example.test"),),
        expected_revision=0,
        idempotency_key=key or str(uuid4()),
    )


def test_original_receipts_replay_after_later_changes_and_recover(identities):
    workspace, service, _ = identities
    key = str(uuid4())
    first = create(service, key)
    patch_key, archive_key, restore_key = (str(uuid4()) for _ in range(3))
    edited = service.patch(
        first["id"], PartyPatchCommand("Edited"), expected_revision=1, idempotency_key=patch_key
    )
    archived = service.archive(
        first["id"], confirmed=True, expected_revision=2, idempotency_key=archive_key
    )
    restored = service.restore(first["id"], expected_revision=3, idempotency_key=restore_key)
    assert [r["revision"] for r in (first, edited, archived, restored)] == [1, 2, 3, 4]
    assert create(service, key) == first
    assert (
        service.patch(
            first["id"], PartyPatchCommand("Edited"), expected_revision=1, idempotency_key=patch_key
        )
        == edited
    )
    assert (
        service.archive(
            first["id"], confirmed=True, expected_revision=2, idempotency_key=archive_key
        )
        == archived
    )
    assert (
        service.restore(first["id"], expected_revision=3, idempotency_key=restore_key) == restored
    )
    assert service.recovery(key=key) == first
    assert service.recovery(operation_id=archived["operationId"]) == archived
    with service.unit_of_work.engine.connect() as connection:
        correlation = connection.execute(
            text("SELECT correlation_id FROM party_command_operations WHERE id=:id"),
            {"id": first["operationId"]},
        ).scalar_one()
        events = connection.execute(
            text(
                "SELECT entity_type, after_snapshot FROM audit_events WHERE correlation_id=:correlation"
            ),
            {"correlation": correlation},
        ).all()
        assert {event[0] for event in events} == {
            "party",
            "party_contact_method",
            "party_command_operation",
        }
        snapshot = next(
            snapshot for entity, snapshot in events if entity == "party_command_operation"
        )
        assert "original@example.test" not in snapshot and "request_json" not in snapshot
    validate_latest_schema(workspace.paths.database)


def test_noop_receipt_does_not_change_party_or_write_mutation_audit(identities):
    workspace, service, _ = identities
    first = create(service)
    result = service.patch(
        first["id"],
        PartyPatchCommand("Original"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    assert result["revision"] == 1
    assert result["updatedAt"] == first["updatedAt"]
    with service.unit_of_work.engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM audit_events WHERE entity_type='party'")
            ).scalar_one()
            == 1
        )
    validate_latest_schema(workspace.paths.database)


def test_stale_changed_key_and_direct_boundary_validation(identities):
    _, service, _ = identities
    key = str(uuid4())
    first = create(service, key)
    with pytest.raises(PartyConflictError) as error:
        service.create(
            PartyCreateCommand("individual", "Changed"), expected_revision=0, idempotency_key=key
        )
    assert error.value.code == "party_idempotency_conflict"
    with pytest.raises(PartyConflictError) as error:
        service.patch(
            first["id"],
            PartyPatchCommand("Changed"),
            expected_revision=2,
            idempotency_key=str(uuid4()),
        )
    assert error.value.current == service.get(first["id"])[0].identity_snapshot()
    for revision, bad_key in (
        (True, str(uuid4())),
        (-1, str(uuid4())),
        ("1", str(uuid4())),
        (0, "bad"),
    ):
        with pytest.raises(PartyValidationError):
            service.create(
                PartyCreateCommand("individual", "Invalid"),
                expected_revision=revision,
                idempotency_key=bad_key,
            )


def test_audit_failure_rolls_back_party_contacts_and_receipt(identities):
    _, service, recorder = identities
    original = recorder.record_change

    def fail_receipt(*args, **kwargs):
        if kwargs["entity_type"] == "party_command_operation":
            raise RuntimeError("audit failed")
        return original(*args, **kwargs)

    with (
        patch.object(recorder, "record_change", side_effect=fail_receipt),
        pytest.raises(RuntimeError),
    ):
        create(service)
    with service.unit_of_work.engine.connect() as connection:
        for table in ("parties", "party_contact_methods", "party_command_operations"):
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM audit_events WHERE entity_type IN ('party','party_contact_method','party_command_operation')"
                )
            ).scalar_one()
            == 0
        )


def test_recovery_uses_one_indexed_read_and_no_writes(identities):
    _, service, _ = identities
    first = create(service)
    statements = []

    def capture(connection, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(service.unit_of_work.engine, "before_cursor_execute", capture)
    try:
        assert service.recovery(operation_id=first["operationId"]) == first
    finally:
        event.remove(service.unit_of_work.engine, "before_cursor_execute", capture)
    assert len([s for s in statements if s.lstrip().upper().startswith("SELECT")]) == 1
    assert not any(
        s.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")) for s in statements
    )


def test_concurrent_same_key_and_stale_edits_are_serialized(identities):
    workspace, service, _ = identities
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create, service, key) for _ in range(2)]
        first, replay = [future.result() for future in futures]
    assert first == replay

    def edit(name):
        try:
            return service.patch(
                first["id"],
                PartyPatchCommand(name),
                expected_revision=1,
                idempotency_key=str(uuid4()),
            )
        except PartyConflictError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(edit, ("One", "Two")))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert "party_revision_conflict" in results
    validate_latest_schema(workspace.paths.database)


def test_role_guard_rejection_and_patch_audit_failure_leave_no_receipt(identities):
    _, service, recorder = identities
    first = create(service)

    class Guard:
        def conflict(self, connection, party_id):
            return "Active role blocks archival."

    service.unit_of_work.role_activity_guards = (Guard(),)
    with pytest.raises(PartyConflictError, match="Active role"):
        service.archive(
            first["id"], confirmed=True, expected_revision=1, idempotency_key=str(uuid4())
        )
    with (
        patch.object(recorder, "record_change", side_effect=RuntimeError("audit unavailable")),
        pytest.raises(RuntimeError),
    ):
        service.patch(
            first["id"],
            PartyPatchCommand("Failed"),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
    assert service.get(first["id"])[0].identity_snapshot() == {
        k: v for k, v in first.items() if k != "operationId"
    }
    with service.unit_of_work.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM party_command_operations")).scalar_one()
            == 1
        )


def test_retained_tampering_and_append_only_constraints(identities):
    workspace, service, _ = identities
    first = create(service)
    with service.unit_of_work.engine.begin() as connection:
        trigger = connection.execute(
            text(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='audit_events_no_delete'"
            )
        ).scalar_one()
        connection.execute(text("DROP TRIGGER audit_events_no_delete"))
        connection.execute(
            text("DELETE FROM audit_events WHERE entity_type='party_command_operation'")
        )
        connection.execute(text(trigger))
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(workspace.paths.database)
    with service.unit_of_work.engine.connect() as connection, pytest.raises(MigrationSchemaError):
        validate_party_schema(connection)
    with pytest.raises(IntegrityError, match="immutable"):
        with service.unit_of_work.engine.begin() as connection:
            connection.execute(
                text("UPDATE party_command_operations SET result_json='{}' WHERE id=:id"),
                {"id": first["operationId"]},
            )


def test_api_required_contract_and_original_result(identities):
    _, service, _ = identities
    app = FastAPI()
    app.include_router(
        build_router(
            service,
            PartyContactService(service.unit_of_work),
            SimpleNamespace(ready=True, error=None, can_write=True),
        )
    )
    client = TestClient(app)
    payload = {
        "partyKind": "individual",
        "displayName": "API",
        "expectedRevision": 0,
        "idempotencyKey": str(uuid4()),
    }
    result = client.post("/api/parties", json=payload)
    assert result.status_code == 201, result.text
    first = result.json()
    changed = client.patch(
        f"/api/parties/{first['id']}",
        json={"displayName": "Later", "expectedRevision": 1, "idempotencyKey": str(uuid4())},
    )
    assert changed.status_code == 200
    assert client.post("/api/parties", json=payload).json() == first
    assert client.get(f"/api/parties/operations/{first['operationId']}").json() == first
    stale = client.post(
        f"/api/parties/{first['id']}/archive",
        json={"confirmed": True, "expectedRevision": 1, "idempotencyKey": str(uuid4())},
    )
    assert stale.status_code == 409 and stale.json()["detail"]["current"]["revision"] == 2
    assert (
        client.post(
            "/api/parties", json={"partyKind": "individual", "displayName": "Invalid"}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/parties", json={**payload, "expectedRevision": True}).status_code == 422
    )
    archived = client.post(
        f"/api/parties/{first['id']}/archive",
        json={"confirmed": True, "expectedRevision": 2, "idempotencyKey": str(uuid4())},
    )
    assert archived.status_code == 200
    restored = client.post(
        f"/api/parties/{first['id']}/restore",
        json={"expectedRevision": 3, "idempotencyKey": str(uuid4())},
    )
    assert restored.status_code == 200 and restored.json()["revision"] == 4
    schema = app.openapi()
    assert (
        schema["paths"]["/api/parties/operations/{operation_id}"]["get"]["operationId"]
        == "getPartyOperation"
    )


def test_encrypted_restore_preserves_receipts_and_correlated_history(identities, tmp_path):
    workspace, service, recorder = identities
    first = create(service)
    service.archive(first["id"], confirmed=True, expected_revision=1, idempotency_key=str(uuid4()))
    with service.unit_of_work.engine.connect() as connection:
        before = [
            dict(r)
            for r in connection.execute(
                text("SELECT * FROM party_command_operations ORDER BY id")
            ).mappings()
        ]
        audits = [
            dict(r)
            for r in connection.execute(text("SELECT * FROM audit_events ORDER BY id")).mappings()
        ]

    class Secrets:
        def get_passphrase(self, workspace_id):
            return None

    backups = BackupService(
        workspace,
        recorder,
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
        Secrets(),
    )
    archive = backups.create_backup("a long test backup passphrase")
    restored = tmp_path / "restored"
    backups.restore(archive.archive_path, "a long test backup passphrase", restored)
    engine = create_sqlite_engine(restored / "database" / "property-management.sqlite")
    try:
        with engine.connect() as connection:
            assert [
                dict(r)
                for r in connection.execute(
                    text("SELECT * FROM party_command_operations ORDER BY id")
                ).mappings()
            ] == before
            retained = {
                r["id"]: dict(r)
                for r in connection.execute(text("SELECT * FROM audit_events")).mappings()
            }
            assert all(retained[r["id"]] == r for r in audits)
    finally:
        engine.dispose()

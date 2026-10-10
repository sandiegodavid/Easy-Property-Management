"""Slice 23: real Tenant receipts, concurrency, rollback and portability."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from app.platform.testing_client import LocalApiClient as TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.leases.infrastructure.unit_of_work import SQLiteLeaseParticipationGuard
from app.modules.parties.application.service import (
    ContactMethodCommand,
    ContactReferenceResolution,
    PartyContactService,
    PartyConflictError,
    SharedPartyFactory,
)
from app.modules.parties.application.service import PartyCreateCommand
from app.modules.parties.application.service import PartyIdentityService
from app.modules.parties.infrastructure.unit_of_work import (
    SQLitePartyOperations,
    SQLitePartyReadOperations,
    SQLitePartyUnitOfWork,
)
from app.modules.tenants.application.service import (
    TenantService,
    TenantCreateCommand,
    TenantProfilePatchCommand,
    TenantConflictError,
    TenantError,
)
from app.modules.tenants.infrastructure.unit_of_work import (
    SQLiteTenantUnitOfWork,
    SQLiteTenantContactReferenceGuard,
)
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.config import LocalConfig
from app.platform.product_migrations import validate_latest_schema
from app.platform.migration_errors import MigrationSchemaError


@pytest.fixture
def tenant_services(tmp_path):
    workspace = WorkspaceService(LocalConfig(tmp_path / "config.json", tmp_path / "workspace"))
    workspace.initialize()
    audit = SQLiteAuditRepository(workspace.paths.database)
    recorder = AuditRecorder(audit)
    parties = SQLitePartyOperations(workspace.paths.database)
    tenants = TenantService(
        SQLiteTenantUnitOfWork(
            workspace.paths.database,
            recorder,
            SQLiteLeaseParticipationGuard(),
            parties,
            SQLitePartyReadOperations(parties),
        ),
        SharedPartyFactory(),
    )
    contacts = PartyContactService(
        SQLitePartyUnitOfWork(
            workspace.paths.database, recorder, (SQLiteTenantContactReferenceGuard(recorder),)
        )
    )
    return workspace, tenants, contacts, audit


def create(tenants, **fields):
    return tenants.create(
        TenantCreateCommand("individual", "Tenant", **fields),
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )


def test_create_replay_is_original_after_profile_and_party_changes(tenant_services):
    workspace, tenants, contacts, _ = tenant_services
    key, command = str(uuid4()), TenantCreateCommand("individual", "Original")
    first = tenants.create(command, expected_revision=0, idempotency_key=key)
    tenants.update_profile(
        first["id"],
        TenantProfilePatchCommand(notes="later"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    contacts.add(
        first["id"],
        ContactMethodCommand("email", "later@example.test"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    assert tenants.create(command, expected_revision=0, idempotency_key=key) == first
    assert tenants.recover(key=key) == tenants.recover(operation_id=first["operationId"]) == first
    with pytest.raises(TenantConflictError, match="another command"):
        tenants.create(
            replace(command, display_name="different"), expected_revision=0, idempotency_key=key
        )
    validate_latest_schema(workspace.paths.database)


def test_designation_uses_existing_contacts_and_original_receipt(tenant_services):
    workspace, tenants, contacts, _ = tenant_services
    identity = PartyIdentityService(
        contacts.unit_of_work, SQLitePartyReadOperations(tenants.unit_of_work.party_operations)
    )
    party = identity.create(
        PartyCreateCommand("individual", "Existing"),
        contacts=(ContactMethodCommand("email", "existing@example.test"),),
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    key = str(uuid4())
    first = tenants.designate(
        party["id"], notes="evenings", expected_revision=0, idempotency_key=key
    )
    assert len(first["contactMethods"]) == 1 and first["partyRevision"] == 1
    tenants.update_profile(
        party["id"],
        TenantProfilePatchCommand(notes="changed"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    assert (
        tenants.designate(party["id"], notes="evenings", expected_revision=0, idempotency_key=key)
        == first
    )
    with pytest.raises(TenantConflictError):
        tenants.designate(
            party["id"], notes="new", expected_revision=0, idempotency_key=str(uuid4())
        )
    validate_latest_schema(workspace.paths.database)


def test_noop_presence_sensitive_payload_and_lifecycle_replay(tenant_services):
    workspace, tenants, _, audit = tenant_services
    first = create(tenants)
    key = str(uuid4())
    noop = tenants.update_profile(
        first["id"], TenantProfilePatchCommand(notes=None), expected_revision=1, idempotency_key=key
    )
    assert noop["revision"] == 1 and noop["profile"]["updatedAt"] == first["profile"]["updatedAt"]
    assert len(audit.history("tenant_profile", first["id"])) == 1
    with pytest.raises(TenantConflictError):
        tenants.update_profile(
            first["id"],
            TenantProfilePatchCommand(do_not_contact=False),
            expected_revision=1,
            idempotency_key=key,
        )
    archive_key = str(uuid4())
    archived = tenants.archive(
        first["id"], confirmed=True, expected_revision=1, idempotency_key=archive_key
    )
    restored = tenants.restore(first["id"], expected_revision=2, idempotency_key=str(uuid4()))
    assert restored["revision"] == 3
    assert (
        tenants.archive(
            first["id"], confirmed=True, expected_revision=1, idempotency_key=archive_key
        )
        == archived
    )
    with pytest.raises(TenantConflictError) as error:
        tenants.update_profile(
            first["id"],
            TenantProfilePatchCommand(notes="stale"),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
    assert error.value.current == restored["profile"]
    validate_latest_schema(workspace.paths.database)


@pytest.mark.parametrize("revision", [True, -1, "1", None])
def test_direct_call_contract_rejects_invalid_revision(tenant_services, revision):
    _, tenants, _, _ = tenant_services
    with pytest.raises(TenantError):
        tenants.create(
            TenantCreateCommand("individual", "Bad"),
            expected_revision=revision,
            idempotency_key=str(uuid4()),
        )
    with pytest.raises(TenantError):
        tenants.create(
            TenantCreateCommand("individual", "Bad"), expected_revision=0, idempotency_key="bad"
        )


def test_concurrent_duplicates_create_once_and_stale_edits_conflict(tenant_services):
    _, tenants, _, _ = tenant_services
    barrier, key = Barrier(2), str(uuid4())

    def submit():
        barrier.wait()
        return tenants.create(
            TenantCreateCommand("individual", "Same"), expected_revision=0, idempotency_key=key
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert results[0] == results[1]
    barrier = Barrier(2)

    def edit(note):
        barrier.wait()
        try:
            return tenants.update_profile(
                results[0]["id"],
                TenantProfilePatchCommand(notes=note),
                expected_revision=1,
                idempotency_key=str(uuid4()),
            )
        except TenantConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        changed = list(pool.map(edit, ["one", "two"]))
    assert sum(result is not None for result in changed) == 1


def test_contact_resolution_requires_tenant_revision_and_rolls_back(tenant_services):
    workspace, tenants, contacts, audit = tenant_services
    first = create(tenants, contacts=(ContactMethodCommand("email", "old@example.test"),))
    method = first["contactMethods"][0]["id"]
    current = tenants.update_profile(
        first["id"],
        TenantProfilePatchCommand(preferred_contact_method_id=method),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    key = str(uuid4())
    with pytest.raises(PartyConflictError) as error:
        contacts.archive(
            first["id"],
            method,
            confirmed=True,
            expected_revision=1,
            idempotency_key=key,
            reference_resolutions=(
                ContactReferenceResolution(
                    "tenant", first["id"], clear=True, expected_tenant_revision=1
                ),
            ),
        )
    assert error.value.current_tenant == current["profile"]
    assert contacts.list(first["id"])[0]["status"] == "active"
    resolution = ContactReferenceResolution(
        "tenant", first["id"], clear=True, expected_tenant_revision=2
    )
    archived = contacts.archive(
        first["id"],
        method,
        confirmed=True,
        expected_revision=1,
        idempotency_key=key,
        reference_resolutions=(resolution,),
    )
    assert tenants.get(first["id"])["revision"] == 3
    assert (
        contacts.archive(
            first["id"],
            method,
            confirmed=True,
            expected_revision=1,
            idempotency_key=key,
            reference_resolutions=(resolution,),
        )
        == archived
    )
    correlation = audit.history("party_contact_method", method)[-1].correlation_id
    assert {e.entity_type for e in audit.history(correlation_id=correlation)} == {
        "party",
        "party_contact_method",
        "party_command_operation",
        "tenant_profile",
        "tenant_command_operation",
    }
    validate_latest_schema(workspace.paths.database)


def test_receipt_audit_failure_rolls_back_identity_and_profile(tenant_services):
    _, tenants, _, _ = tenant_services
    with tenants.unit_of_work.engine.connect() as connection:
        baseline_audits = connection.execute(text("SELECT COUNT(*) FROM audit_events")).scalar_one()
    original = tenants.unit_of_work.recorder.record_change

    def fail(connection, **change):
        if change["entity_type"] == "tenant_command_operation":
            raise RuntimeError("receipt audit unavailable")
        return original(connection, **change)

    with (
        patch.object(tenants.unit_of_work.recorder, "record_change", side_effect=fail),
        pytest.raises(RuntimeError),
    ):
        create(tenants, contacts=(ContactMethodCommand("email", "rollback@example.test"),))
    with tenants.unit_of_work.engine.connect() as connection:
        for table in (
            "parties",
            "party_contact_methods",
            "tenant_profiles",
            "tenant_command_operations",
            "audit_events",
        ):
            assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == (
                baseline_audits if table == "audit_events" else 0
            )


def test_indexed_recovery_and_tampered_history_rejected(tenant_services):
    workspace, tenants, _, _ = tenant_services
    first = create(tenants)
    reads = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            reads.append(statement)

    event.listen(tenants.unit_of_work.engine, "before_cursor_execute", capture)
    try:
        assert tenants.recover(operation_id=first["operationId"]) == first
    finally:
        event.remove(tenants.unit_of_work.engine, "before_cursor_execute", capture)
    assert len(reads) == 1 and "WHERE tenant_command_operations.id" in reads[0]
    with tenants.unit_of_work.engine.begin() as connection:
        connection.execute(text("UPDATE tenant_profiles SET notes='unaudited'"))
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(workspace.paths.database)


@pytest.mark.parametrize("tampering", ["fingerprint", "audit", "result", "trigger", "preference"])
def test_retained_receipt_corruption_is_rejected(tenant_services, tampering):
    workspace, tenants, _, _ = tenant_services
    first = create(tenants)
    with tenants.unit_of_work.engine.begin() as connection:
        if tampering == "audit":
            trigger = connection.execute(
                text(
                    "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_events' AND upper(sql) LIKE '%BEFORE DELETE%'"
                )
            ).one()
            connection.exec_driver_sql(f'DROP TRIGGER "{trigger.name}"')
            connection.execute(
                text("DELETE FROM audit_events WHERE entity_type='tenant_command_operation'")
            )
            connection.exec_driver_sql(trigger.sql)
        elif tampering == "preference":
            connection.execute(text("UPDATE tenant_profiles SET revision=revision+1"))
        else:
            connection.execute(text("DROP TRIGGER tenant_command_operations_no_update"))
            if tampering == "fingerprint":
                connection.execute(
                    text("UPDATE tenant_command_operations SET request_fingerprint=:fingerprint"),
                    {"fingerprint": "0" * 64},
                )
            elif tampering == "result":
                result = {**first, "partyRevision": 999}
                connection.execute(
                    text("UPDATE tenant_command_operations SET result_json=:result"),
                    {"result": json.dumps(result, sort_keys=True, separators=(",", ":"))},
                )
            if tampering != "trigger":
                from app.modules.tenants.infrastructure.sqlalchemy_models import (
                    TENANT_COMMAND_TRIGGERS,
                )

                connection.exec_driver_sql(
                    TENANT_COMMAND_TRIGGERS["tenant_command_operations_no_update"]
                )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(workspace.paths.database)


def test_ledger_prevents_update_delete_and_replace(tenant_services):
    _, tenants, _, _ = tenant_services
    first = create(tenants)
    with tenants.unit_of_work.engine.connect() as connection:
        for sql in (
            "UPDATE tenant_command_operations SET created_at=created_at",
            "DELETE FROM tenant_command_operations",
            "INSERT OR REPLACE INTO tenant_command_operations SELECT * FROM tenant_command_operations",
        ):
            with pytest.raises(IntegrityError):
                connection.execute(text(sql))
    assert tenants.recover(operation_id=first["operationId"]) == first


def test_api_required_contract_conflict_and_recovery(tenant_services, tmp_path):
    workspace, _, _, _ = tenant_services
    config = tmp_path / "http-config.json"
    config.write_text(json.dumps({"localWorkspacePath": str(workspace.paths.root)}))
    with TestClient(create_app(config)) as client:
        payload = {
            "partyKind": "individual",
            "displayName": "HTTP",
            "expectedRevision": 0,
            "idempotencyKey": str(uuid4()),
        }
        created = client.post("/api/tenants", json=payload)
        assert created.status_code == 201
        original = created.json()
        assert client.post("/api/tenants", json=payload).json() == original
        assert client.get(f"/api/tenants/operations/{original['operationId']}").json() == original
        assert (
            client.get(f"/api/tenants/operations/by-key/{payload['idempotencyKey']}").json()
            == original
        )
        assert (
            client.patch(
                f"/api/tenants/{original['id']}", json={"notes": "no metadata"}
            ).status_code
            == 422
        )
        updated = client.patch(
            f"/api/tenants/{original['id']}",
            json={"notes": "new", "expectedRevision": 1, "idempotencyKey": str(uuid4())},
        )
        conflict = client.patch(
            f"/api/tenants/{original['id']}",
            json={"notes": "stale", "expectedRevision": 1, "idempotencyKey": str(uuid4())},
        )
        assert (
            conflict.status_code == 409
            and conflict.json()["detail"]["current"] == updated.json()["profile"]
        )


def test_encrypted_restore_preserves_receipts_and_revisions(tenant_services, tmp_path):
    workspace, tenants, _, audit = tenant_services
    first = create(tenants)
    changed = tenants.update_profile(
        first["id"],
        TenantProfilePatchCommand(notes="portable"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    with tenants.unit_of_work.engine.connect() as connection:
        before = [
            tuple(row)
            for row in connection.execute(
                text("SELECT * FROM tenant_command_operations ORDER BY rowid")
            )
        ]
    backups = BackupService(
        workspace,
        AuditRecorder(audit),
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    with fast_backup_encryption():
        backup = backups.create_backup(
            "a sufficiently long backup passphrase", output_path=tmp_path / "backup"
        )
        backups.restore(
            backup.archive_path, "a sufficiently long backup passphrase", tmp_path / "restored"
        )
    restored_workspace = WorkspaceService(
        LocalConfig(tmp_path / "restored-config.json", tmp_path / "restored")
    )
    parties = SQLitePartyOperations(restored_workspace.paths.database)
    restored = SQLiteTenantUnitOfWork(
        restored_workspace.paths.database,
        AuditRecorder(SQLiteAuditRepository(restored_workspace.paths.database)),
        SQLiteLeaseParticipationGuard(),
        parties,
        SQLitePartyReadOperations(parties),
    )
    service = TenantService(restored, SharedPartyFactory())
    assert service.recover(operation_id=first["operationId"]) == first
    assert service.recover(operation_id=changed["operationId"]) == changed
    assert service.get(first["id"])["revision"] == 2
    with restored.engine.connect() as connection:
        assert [
            tuple(row)
            for row in connection.execute(
                text("SELECT * FROM tenant_command_operations ORDER BY rowid")
            )
        ] == before

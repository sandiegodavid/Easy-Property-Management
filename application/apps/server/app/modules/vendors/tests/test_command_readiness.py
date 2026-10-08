"""Slice 24: Provider-owned receipts across real SQLite transaction boundaries."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.parties.application.service import (
    ContactMethodCommand,
    PartyCreateCommand,
    PartyIdentityService,
    PartyPatchCommand,
)
from app.modules.parties.infrastructure.unit_of_work import (
    SQLitePartyOperations,
    SQLitePartyReadOperations,
    SQLitePartyUnitOfWork,
)
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioLeaseOperations
from app.modules.vendors.application.service import (
    ProviderError,
    ProviderLifecycleConflict,
    ProviderProfileCommand,
    ProviderProfilePatchCommand,
    ProviderService,
    ReferenceCommand,
    ReputationLinkCommand,
    ServiceAreaCommand,
    ServiceCommand,
    WorkHistoryCommand,
)
from app.modules.vendors.infrastructure.sqlalchemy_models import PROVIDER_COMMAND_TRIGGERS
from app.modules.vendors.infrastructure.unit_of_work import SQLiteProviderUnitOfWork
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.config import LocalConfig
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema


@pytest.fixture
def provider_services(tmp_path):
    workspace = WorkspaceService(LocalConfig(tmp_path / "config.json", tmp_path / "workspace"))
    workspace.initialize()
    audit = SQLiteAuditRepository(workspace.paths.database)
    recorder = AuditRecorder(audit)
    service = ProviderService(
        SQLiteProviderUnitOfWork(
            workspace.paths.database,
            recorder,
            SQLitePartyOperations(workspace.paths.database),
            SQLitePortfolioLeaseOperations(workspace.paths.database),
        )
    )
    return workspace, service, audit


def create(service, **fields):
    return service.create(
        PartyCreateCommand("organization", "Provider"),
        ProviderProfileCommand(),
        expected_revision=0,
        idempotency_key=str(uuid4()),
        **fields,
    )


def identities(workspace, service):
    return PartyIdentityService(
        SQLitePartyUnitOfWork(workspace.paths.database, service.unit_of_work.recorder),
        SQLitePartyReadOperations(service.unit_of_work.party_operations),
    )


def test_compound_creation_and_original_replay_after_later_changes(provider_services):
    workspace, service, audit = provider_services
    key = str(uuid4())
    fields = dict(
        contacts=(ContactMethodCommand("email", "provider@example.test"),),
        services=(ServiceCommand("Plumbing"),),
        areas=(ServiceAreaCommand("Portland", "us"),),
        work_history=(WorkHistoryCommand("2025-01-01", "Prior work"),),
        references=(ReferenceCommand(reference_name="Reference"),),
    )
    with service.unit_of_work.engine.connect() as connection:
        category = connection.execute(
            text("SELECT id FROM provider_categories LIMIT 1")
        ).scalar_one()
    fields["category_ids"] = (category,)
    command = PartyCreateCommand("organization", "Original")
    first = service.create(
        command, ProviderProfileCommand(), expected_revision=0, idempotency_key=key, **fields
    )
    party = first["party"]["id"]
    assert set(first) == {"party", "profile", "revision", "partyRevision", "operationId"}
    service.update_profile(
        party,
        ProviderProfilePatchCommand(notes="later"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    service.add_service(
        party, ServiceCommand("Electrical"), expected_revision=2, idempotency_key=str(uuid4())
    )
    identities(workspace, service).patch(
        party, PartyPatchCommand("Renamed"), expected_revision=1, idempotency_key=str(uuid4())
    )
    assert (
        service.create(
            command, ProviderProfileCommand(), expected_revision=0, idempotency_key=key, **fields
        )
        == first
    )
    assert service.recover(key=key) == service.recover(operation_id=first["operationId"]) == first
    with pytest.raises(ProviderLifecycleConflict, match="another command"):
        service.create(
            command,
            ProviderProfileCommand(notes="different"),
            expected_revision=0,
            idempotency_key=key,
            **fields,
        )
    correlation = audit.history("provider_command_operation", first["operationId"])[
        0
    ].correlation_id
    assert {e.entity_type for e in audit.history(correlation_id=correlation)} == {
        "party",
        "party_contact_method",
        "provider_profile",
        "provider_service",
        "provider_service_area",
        "provider_work_history",
        "provider_reference",
        "provider_category_assignment",
        "provider_command_operation",
    }
    metadata = audit.history("provider_command_operation", first["operationId"])[0].after_snapshot
    assert "notes" not in metadata and "request" not in metadata
    validate_latest_schema(workspace.paths.database)


def test_designation_and_all_lifecycle_receipts_replay_original_results(provider_services):
    workspace, service, _ = provider_services
    identity = identities(workspace, service)
    party = identity.create(
        PartyCreateCommand("individual", "Existing"),
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )
    key = str(uuid4())
    first = service.designate(
        party["id"], ProviderProfileCommand(), expected_revision=0, idempotency_key=key
    )
    noop = service.update_profile(
        party["id"],
        ProviderProfilePatchCommand(notes=None),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    assert noop["revision"] == 1 and noop["profile"]["updatedAt"] == first["profile"]["updatedAt"]
    archive_key = str(uuid4())
    archived = service.archive(
        party["id"], confirmed=True, expected_revision=1, idempotency_key=archive_key
    )
    restored = service.restore(party["id"], expected_revision=2, idempotency_key=str(uuid4()))
    assert restored["revision"] == 3
    assert (
        service.designate(
            party["id"], ProviderProfileCommand(), expected_revision=0, idempotency_key=key
        )
        == first
    )
    assert (
        service.archive(
            party["id"], confirmed=True, expected_revision=1, idempotency_key=archive_key
        )
        == archived
    )
    with pytest.raises(ProviderLifecycleConflict) as error:
        service.update_profile(
            party["id"],
            ProviderProfilePatchCommand(notes="stale"),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
    assert error.value.current == restored["profile"]
    validate_latest_schema(workspace.paths.database)


@pytest.mark.parametrize("revision", [True, -1, "0", None])
def test_direct_call_contract(provider_services, revision):
    _, service, _ = provider_services
    with pytest.raises(ProviderError):
        service.create(
            PartyCreateCommand("individual", "Invalid"),
            ProviderProfileCommand(),
            expected_revision=revision,
            idempotency_key=str(uuid4()),
        )
    with pytest.raises(ProviderError):
        service.create(
            PartyCreateCommand("individual", "Invalid"),
            ProviderProfileCommand(),
            expected_revision=0,
            idempotency_key="invalid",
        )


def test_presence_sensitive_noop_and_lifecycle_guards(provider_services):
    workspace, service, audit = provider_services
    first = create(service)
    party, key = first["party"]["id"], str(uuid4())
    noop = service.update_profile(
        party, ProviderProfilePatchCommand(notes=None), expected_revision=1, idempotency_key=key
    )
    assert noop["revision"] == 1 and len(audit.history("provider_profile", party)) == 1
    with pytest.raises(ProviderLifecycleConflict):
        service.update_profile(
            party,
            ProviderProfilePatchCommand(selection_reason=None),
            expected_revision=1,
            idempotency_key=key,
        )
    with pytest.raises(ProviderError):
        service.archive(party, confirmed=False, expected_revision=1, idempotency_key=str(uuid4()))
    service.archive(party, confirmed=True, expected_revision=1, idempotency_key=str(uuid4()))
    with pytest.raises(ProviderLifecycleConflict):
        service.update_profile(
            party,
            ProviderProfilePatchCommand(notes="invalid"),
            expected_revision=2,
            idempotency_key=str(uuid4()),
        )
    validate_latest_schema(workspace.paths.database)


def test_restore_requires_active_shared_identity(provider_services):
    workspace, service, _ = provider_services
    first = create(service)
    party = first["party"]["id"]
    service.archive(party, confirmed=True, expected_revision=1, idempotency_key=str(uuid4()))
    identity = identities(workspace, service)
    identity.archive(party, confirmed=True, expected_revision=1, idempotency_key=str(uuid4()))
    with pytest.raises(ProviderLifecycleConflict, match="Restore the party"):
        service.restore(party, expected_revision=2, idempotency_key=str(uuid4()))
    identity.restore(party, expected_revision=2, idempotency_key=str(uuid4()))
    assert (
        service.restore(party, expected_revision=2, idempotency_key=str(uuid4()))["revision"] == 3
    )
    validate_latest_schema(workspace.paths.database)


def test_concurrent_same_key_and_competing_profile_edits(provider_services):
    _, service, _ = provider_services
    barrier, key = Barrier(2), str(uuid4())

    def submit(_):
        barrier.wait()
        return service.create(
            PartyCreateCommand("individual", "Concurrent"),
            ProviderProfileCommand(),
            expected_revision=0,
            idempotency_key=key,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert results[0] == results[1]
    barrier = Barrier(2)

    def edit(note):
        barrier.wait()
        try:
            return service.update_profile(
                results[0]["party"]["id"],
                ProviderProfilePatchCommand(notes=note),
                expected_revision=1,
                idempotency_key=str(uuid4()),
            )
        except ProviderLifecycleConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        edited = list(pool.map(edit, ["one", "two"]))
    assert sum(item is not None for item in edited) == 1


def test_receipt_audit_failure_rolls_back_compound_creation(provider_services):
    _, service, _ = provider_services
    original = service.unit_of_work.recorder.record_change

    def fail(connection, **change):
        if change["entity_type"] == "provider_command_operation":
            raise RuntimeError("receipt audit unavailable")
        return original(connection, **change)

    with (
        patch.object(service.unit_of_work.recorder, "record_change", side_effect=fail),
        pytest.raises(RuntimeError),
    ):
        create(
            service,
            contacts=(ContactMethodCommand("email", "rollback@example.test"),),
            services=(ServiceCommand("Plumbing"),),
            areas=(ServiceAreaCommand("Metro"),),
            work_history=(WorkHistoryCommand("2025-01-01", "Work"),),
            references=(ReferenceCommand(reference_name="Ref"),),
        )
    with service.unit_of_work.engine.connect() as connection:
        for table in (
            "parties",
            "party_contact_methods",
            "provider_profiles",
            "provider_services",
            "provider_service_areas",
            "provider_work_history",
            "provider_references",
            "provider_command_operations",
        ):
            assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0


def test_receipt_failure_rolls_back_existing_profile_mutation(provider_services):
    workspace, service, audit = provider_services
    first = create(service)
    original = service.unit_of_work.recorder.record_change

    def fail(connection, **change):
        if change["entity_type"] == "provider_command_operation":
            raise RuntimeError("receipt audit unavailable")
        return original(connection, **change)

    with (
        patch.object(service.unit_of_work.recorder, "record_change", side_effect=fail),
        pytest.raises(RuntimeError),
    ):
        service.update_profile(
            first["party"]["id"],
            ProviderProfilePatchCommand(notes="rollback"),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
    assert service.detail(first["party"]["id"])["profile"] == first["profile"]
    assert len(audit.history("provider_profile", first["party"]["id"])) == 1
    validate_latest_schema(workspace.paths.database)


def test_recovery_is_one_indexed_read_and_mutations_do_not_hydrate_detail(provider_services):
    _, service, _ = provider_services
    with patch.object(service.unit_of_work, "detail", side_effect=AssertionError("detail read")):
        first = create(service)
        service.update_profile(
            first["party"]["id"],
            ProviderProfilePatchCommand(notes="safe"),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
    reads = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            reads.append(statement)

    event.listen(service.unit_of_work.engine, "before_cursor_execute", capture)
    try:
        assert service.recover(operation_id=first["operationId"]) == first
    finally:
        event.remove(service.unit_of_work.engine, "before_cursor_execute", capture)
    assert len(reads) == 1 and "WHERE provider_command_operations.id" in reads[0]


@pytest.mark.parametrize("tampering", ["fingerprint", "result", "audit", "revision", "trigger"])
def test_retained_corruption_is_rejected(provider_services, tampering):
    workspace, service, _ = provider_services
    first = create(service)
    with service.unit_of_work.engine.begin() as connection:
        if tampering == "audit":
            trigger = connection.execute(
                text(
                    "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_events' AND upper(sql) LIKE '%BEFORE DELETE%'"
                )
            ).one()
            connection.exec_driver_sql(f'DROP TRIGGER "{trigger.name}"')
            connection.execute(
                text("DELETE FROM audit_events WHERE entity_type='provider_command_operation'")
            )
            connection.exec_driver_sql(trigger.sql)
        elif tampering == "revision":
            connection.execute(text("UPDATE provider_profiles SET revision=revision+1"))
        else:
            connection.execute(text("DROP TRIGGER provider_command_operations_no_update"))
            if tampering == "fingerprint":
                connection.execute(
                    text("UPDATE provider_command_operations SET request_fingerprint=:value"),
                    {"value": "0" * 64},
                )
            elif tampering == "result":
                connection.execute(
                    text("UPDATE provider_command_operations SET result_json=:value"),
                    {
                        "value": json.dumps(
                            {**first, "partyRevision": 999}, sort_keys=True, separators=(",", ":")
                        )
                    },
                )
            if tampering != "trigger":
                connection.exec_driver_sql(
                    PROVIDER_COMMAND_TRIGGERS["provider_command_operations_no_update"]
                )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(workspace.paths.database)


def test_receipts_are_append_only(provider_services):
    _, service, _ = provider_services
    first = create(service)
    with service.unit_of_work.engine.connect() as connection:
        for sql in (
            "UPDATE provider_command_operations SET created_at=created_at",
            "DELETE FROM provider_command_operations",
            "INSERT OR REPLACE INTO provider_command_operations SELECT * FROM provider_command_operations",
        ):
            with pytest.raises(IntegrityError):
                connection.execute(text(sql))
    assert service.recover(operation_id=first["operationId"]) == first


def test_http_contract_and_original_recovery(provider_services, tmp_path):
    workspace, _, _ = provider_services
    config = tmp_path / "http-config.json"
    config.write_text(json.dumps({"localWorkspacePath": str(workspace.paths.root)}))
    with TestClient(create_app(config)) as client:
        payload = {
            "party": {"partyKind": "organization", "displayName": "HTTP"},
            "expectedRevision": 0,
            "idempotencyKey": str(uuid4()),
        }
        created = client.post("/api/providers", json=payload)
        assert created.status_code == 201, created.text
        first = created.json()
        party = first["party"]["id"]
        assert client.post("/api/providers", json=payload).json() == first
        assert client.patch(f"/api/providers/{party}", json={"notes": "missing"}).status_code == 422
        changed = client.patch(
            f"/api/providers/{party}",
            json={"notes": "new", "expectedRevision": 1, "idempotencyKey": str(uuid4())},
        )
        assert changed.status_code == 200, changed.text
        stale = client.patch(
            f"/api/providers/{party}",
            json={"notes": "old", "expectedRevision": 1, "idempotencyKey": str(uuid4())},
        )
        assert (
            stale.status_code == 409
            and stale.json()["detail"]["current"] == changed.json()["profile"]
        )
        assert client.get(f"/api/providers/operations/{first['operationId']}").json() == first
        assert (
            client.get(f"/api/providers/operations/by-key/{payload['idempotencyKey']}").json()
            == first
        )


def test_encrypted_restore_preserves_original_receipts_and_correlations(
    provider_services, tmp_path
):
    workspace, service, audit = provider_services
    first = create(service)
    changed = service.update_profile(
        first["party"]["id"],
        ProviderProfilePatchCommand(notes="portable"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    child_results = []
    revision = 2
    for suffix, command in (
        ("service", ServiceCommand("Portable service")),
        ("area", ServiceAreaCommand("Portable area", "US")),
        ("work_history", WorkHistoryCommand("2025-01-01", "Portable work")),
        ("reference", ReferenceCommand(reference_name="Portable reference")),
        ("reputation_link", ReputationLinkCommand("google", "https://portable.example/reviews")),
    ):
        child = getattr(service, f"add_{suffix}")(
            first["party"]["id"], command, expected_revision=revision, idempotency_key=str(uuid4())
        )
        child_results.append(child)
        archived = getattr(service, f"archive_{suffix}")(
            first["party"]["id"],
            child["item"]["id"],
            confirmed=True,
            expected_revision=revision + 1,
            idempotency_key=str(uuid4()),
        )
        child_results.append(archived)
        revision += 2
    detail_before = service.detail(first["party"]["id"], include_archived=True)
    with service.unit_of_work.engine.connect() as connection:
        before = [
            tuple(row)
            for row in connection.execute(
                text("SELECT * FROM provider_command_operations ORDER BY rowid")
            )
        ]
        correlations = [
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT * FROM audit_events WHERE entity_type LIKE 'provider_%' ORDER BY rowid"
                )
            )
        ]
    backups = BackupService(
        workspace,
        AuditRecorder(audit),
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    with fast_backup_encryption():
        backup = backups.create_backup(
            "a sufficiently long passphrase", output_path=tmp_path / "backup"
        )
        backups.restore(
            backup.archive_path, "a sufficiently long passphrase", tmp_path / "restored"
        )
    restored_workspace = WorkspaceService(
        LocalConfig(tmp_path / "restored-config.json", tmp_path / "restored")
    )
    database = restored_workspace.paths.database
    restored = ProviderService(
        SQLiteProviderUnitOfWork(
            database,
            AuditRecorder(SQLiteAuditRepository(database)),
            SQLitePartyOperations(database),
            SQLitePortfolioLeaseOperations(database),
        )
    )
    assert restored.recover(operation_id=first["operationId"]) == first
    assert restored.recover(operation_id=changed["operationId"]) == changed
    assert restored.detail(first["party"]["id"], include_archived=True) == detail_before
    for original in child_results:
        assert restored.recover(operation_id=original["operationId"]) == original
    with restored.unit_of_work.engine.connect() as connection:
        assert [
            tuple(row)
            for row in connection.execute(
                text("SELECT * FROM provider_command_operations ORDER BY rowid")
            )
        ] == before
        assert [
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT * FROM audit_events WHERE entity_type LIKE 'provider_%' ORDER BY rowid"
                )
            )
        ] == correlations

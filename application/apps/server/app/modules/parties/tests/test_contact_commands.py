"""Slice 22: real Party revision, contact receipts and owning reference effects."""

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.modules.parties.api.router import build_router
from app.modules.parties.application.service import (
    ContactMethodCommand,
    ContactReferenceResolution,
    PartyContactService,
    PartyConflictError,
    PartyValidationError,
    PartyPatchCommand,
    PartyNotFoundError,
    SharedPartyFactory,
)
from app.modules.parties.infrastructure.unit_of_work import (
    SQLitePartyOperations,
    SQLitePartyReadOperations,
)
from app.modules.parties.infrastructure.schema_validation import validate_party_schema
from app.modules.parties.tests.test_identity_commands import identities as identities, create
from app.modules.tenants.application.service import (
    TenantService,
    TenantCreateCommand,
    TenantProfilePatchCommand,
)
from app.modules.tenants.infrastructure.unit_of_work import (
    SQLiteTenantUnitOfWork,
    SQLiteTenantContactReferenceGuard,
)
from app.modules.leases.infrastructure.unit_of_work import SQLiteLeaseParticipationGuard
from app.modules.workspace.application.backup_service import BackupService
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.platform.product_migrations import validate_latest_schema
from app.platform.sqlite_engine import create_sqlite_engine
from app.platform.migration_errors import MigrationSchemaError


def test_all_contact_receipts_replay_after_later_mutations(identities):
    workspace, identity, _ = identities
    party = create(identity)
    contacts = PartyContactService(identity.unit_of_work)
    keys = [str(uuid4()) for _ in range(4)]
    added = contacts.add(
        party["id"],
        ContactMethodCommand("phone", "5035550199"),
        expected_revision=1,
        idempotency_key=keys[0],
    )
    edited = contacts.update(
        party["id"],
        added["id"],
        ContactMethodCommand("phone", "5035550188"),
        expected_revision=2,
        idempotency_key=keys[1],
    )
    archived = contacts.archive(
        party["id"], added["id"], confirmed=True, expected_revision=3, idempotency_key=keys[2]
    )
    restored = contacts.restore(
        party["id"], added["id"], expected_revision=4, idempotency_key=keys[3]
    )
    assert [item["revision"] for item in (added, edited, archived, restored)] == [2, 3, 4, 5]
    identity.patch(
        party["id"], PartyPatchCommand("Later"), expected_revision=5, idempotency_key=str(uuid4())
    )
    assert (
        contacts.add(
            party["id"],
            ContactMethodCommand("phone", "5035550199"),
            expected_revision=1,
            idempotency_key=keys[0],
        )
        == added
    )
    assert (
        contacts.update(
            party["id"],
            added["id"],
            ContactMethodCommand("phone", "5035550188"),
            expected_revision=2,
            idempotency_key=keys[1],
        )
        == edited
    )
    assert (
        contacts.archive(
            party["id"], added["id"], confirmed=True, expected_revision=3, idempotency_key=keys[2]
        )
        == archived
    )
    assert (
        contacts.restore(party["id"], added["id"], expected_revision=4, idempotency_key=keys[3])
        == restored
    )
    for key, result in zip(keys, (added, edited, archived, restored), strict=True):
        assert identity.recovery(key=key) == result
        assert identity.recovery(operation_id=result["operationId"]) == result
    validate_latest_schema(workspace.paths.database)


def test_noop_edit_keeps_parent_and_contact_timestamp_but_records_receipt(identities):
    workspace, identity, _ = identities
    party = create(identity)
    contacts = PartyContactService(identity.unit_of_work)
    contact = contacts.list(party["id"])[0]
    result = contacts.update(
        party["id"],
        contact["id"],
        ContactMethodCommand("email", contact["displayValue"]),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    assert result["revision"] == 1 and result["updatedAt"] == contact["updatedAt"]
    assert identity.get(party["id"])[0].updated_at == party["updatedAt"]
    with identity.unit_of_work.engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM audit_events WHERE entity_type='party_contact_method'")
            ).scalar_one()
            == 1
        )
    validate_latest_schema(workspace.paths.database)


def test_required_direct_contract_and_shared_key_conflicts(identities):
    _, identity, _ = identities
    party = create(identity)
    contacts = PartyContactService(identity.unit_of_work)
    for revision, key in (
        (True, str(uuid4())),
        (0, str(uuid4())),
        ("1", str(uuid4())),
        (1, "invalid"),
    ):
        with pytest.raises(PartyValidationError):
            contacts.add(
                party["id"],
                ContactMethodCommand("phone", "5035550111"),
                expected_revision=revision,
                idempotency_key=key,
            )
    key = str(uuid4())
    added = contacts.add(
        party["id"],
        ContactMethodCommand("phone", "5035550111"),
        expected_revision=1,
        idempotency_key=key,
    )
    with pytest.raises(PartyConflictError) as error:
        contacts.add(
            party["id"],
            ContactMethodCommand("phone", "5035550112"),
            expected_revision=1,
            idempotency_key=key,
        )
    assert error.value.code == "party_idempotency_conflict"
    with pytest.raises(PartyConflictError) as error:
        identity.patch(
            party["id"], PartyPatchCommand("Reuse"), expected_revision=2, idempotency_key=key
        )
    assert error.value.code == "party_idempotency_conflict"
    with pytest.raises(PartyConflictError) as error:
        contacts.archive(
            party["id"],
            added["id"],
            confirmed=True,
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
    assert error.value.current["revision"] == 2
    with pytest.raises(PartyValidationError):
        contacts.restore(party["id"], "bad-id", expected_revision=2, idempotency_key=str(uuid4()))


def _tenant(identities):
    workspace, identity, recorder = identities
    operations = SQLitePartyOperations(workspace.paths.database)
    service = TenantService(
        SQLiteTenantUnitOfWork(
            workspace.paths.database,
            recorder,
            SQLiteLeaseParticipationGuard(),
            operations,
            SQLitePartyReadOperations(operations),
        ),
        SharedPartyFactory(),
    )
    from app.modules.tenants.tests.command_helpers import current_tenant_command

    tenant = current_tenant_command(
        service,
        "create",
        TenantCreateCommand(
            "individual",
            "Referenced",
            contacts=(
                ContactMethodCommand("email", "one@example.test"),
                ContactMethodCommand("phone", "5035550188"),
            ),
        ),
    )
    old, replacement = tenant["contactMethods"]
    current_tenant_command(
        service,
        "update_profile",
        tenant["id"],
        TenantProfilePatchCommand(preferred_contact_method_id=old["id"]),
    )
    identity.unit_of_work.contact_reference_guards = (SQLiteTenantContactReferenceGuard(recorder),)
    return service, tenant, old, replacement


@pytest.mark.parametrize("clear", [False, True])
def test_preference_coordination_is_atomic_correlated_and_replayable(identities, clear):
    workspace, identity, _ = identities
    tenants, tenant, old, replacement = _tenant(identities)
    contacts = PartyContactService(identity.unit_of_work)
    resolution = ContactReferenceResolution(
        "tenant",
        tenant["id"],
        None if clear else replacement["id"],
        clear,
        expected_tenant_revision=2,
    )
    with pytest.raises(PartyValidationError):
        contacts.archive(
            tenant["id"],
            old["id"],
            confirmed=True,
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
    key = str(uuid4())
    result = contacts.archive(
        tenant["id"],
        old["id"],
        confirmed=True,
        expected_revision=1,
        idempotency_key=key,
        reference_resolutions=(resolution,),
    )
    assert result["revision"] == 2
    assert (
        tenants.get(tenant["id"])["profile"]["preferredContactMethodId"]
        == resolution.replacement_contact_method_id
    )
    assert (
        contacts.archive(
            tenant["id"],
            old["id"],
            confirmed=True,
            expected_revision=1,
            idempotency_key=key,
            reference_resolutions=(resolution,),
        )
        == result
    )
    with identity.unit_of_work.engine.connect() as connection:
        correlation = connection.execute(
            text("SELECT correlation_id FROM party_command_operations WHERE id=:id"),
            {"id": result["operationId"]},
        ).scalar_one()
        events = connection.execute(
            text(
                "SELECT entity_type, after_snapshot FROM audit_events WHERE correlation_id=:correlation"
            ),
            {"correlation": correlation},
        ).all()
        assert {kind for kind, snapshot in events} == {
            "party",
            "party_contact_method",
            "tenant_profile",
            "tenant_command_operation",
            "party_command_operation",
        }
        metadata = next(snapshot for kind, snapshot in events if kind == "party_command_operation")
        assert "one@example.test" not in metadata
    validate_latest_schema(workspace.paths.database)


def test_reference_effects_roll_back_on_receipt_audit_failure(identities):
    _, identity, recorder = identities
    tenants, tenant, old, replacement = _tenant(identities)
    contacts = PartyContactService(identity.unit_of_work)
    record = recorder.record_change

    def fail_receipt(*args, **kwargs):
        if kwargs["entity_type"] == "party_command_operation":
            raise RuntimeError("receipt audit failed")
        return record(*args, **kwargs)

    with (
        patch.object(recorder, "record_change", side_effect=fail_receipt),
        pytest.raises(RuntimeError),
    ):
        contacts.archive(
            tenant["id"],
            old["id"],
            confirmed=True,
            expected_revision=1,
            idempotency_key=str(uuid4()),
            reference_resolutions=(
                ContactReferenceResolution(
                    "tenant", tenant["id"], replacement["id"], expected_tenant_revision=2
                ),
            ),
        )
    assert tenants.get(tenant["id"])["profile"]["preferredContactMethodId"] == old["id"]
    assert contacts.list(tenant["id"])[0]["status"] == "active"
    assert identity.get(tenant["id"])[0].revision == 1
    with identity.unit_of_work.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM party_command_operations")).scalar_one()
            == 0
        )


def test_concurrent_duplicate_contact_submissions_publish_once(identities):
    _, identity, _ = identities
    party = create(identity)
    contacts = PartyContactService(identity.unit_of_work)
    key = str(uuid4())

    def submit(_):
        return contacts.add(
            party["id"],
            ContactMethodCommand("phone", "5035550133"),
            expected_revision=1,
            idempotency_key=key,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, range(2)))
    assert results[0] == results[1]
    assert len(contacts.list(party["id"])) == 2
    assert identity.get(party["id"])[0].revision == 2


def test_contacts_and_identity_share_concurrency_and_lifecycle_guards(identities):
    _, identity, _ = identities
    party = create(identity)
    contacts = PartyContactService(identity.unit_of_work)
    old = contacts.list(party["id"])[0]

    def edit_identity():
        return identity.patch(
            party["id"],
            PartyPatchCommand("Competing"),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )

    def edit_contact():
        return contacts.update(
            party["id"],
            old["id"],
            ContactMethodCommand("email", "competing@example.test"),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(operation) for operation in (edit_identity, edit_contact)]
        winners, conflicts = [], []
        for future in futures:
            try:
                winners.append(future.result())
            except PartyConflictError as error:
                conflicts.append(error.code)
    assert len(winners) == 1 and conflicts == ["party_revision_conflict"]
    identity.archive(party["id"], confirmed=True, expected_revision=2, idempotency_key=str(uuid4()))
    for operation in (
        lambda: contacts.add(
            party["id"],
            ContactMethodCommand("phone", "5035550122"),
            expected_revision=3,
            idempotency_key=str(uuid4()),
        ),
        lambda: contacts.update(
            party["id"],
            old["id"],
            ContactMethodCommand("email", "blocked@example.test"),
            expected_revision=3,
            idempotency_key=str(uuid4()),
        ),
        lambda: contacts.restore(
            party["id"], old["id"], expected_revision=3, idempotency_key=str(uuid4())
        ),
    ):
        with pytest.raises(PartyConflictError):
            operation()
    with pytest.raises(PartyNotFoundError):
        contacts.archive(
            party["id"],
            str(uuid4()),
            confirmed=True,
            expected_revision=3,
            idempotency_key=str(uuid4()),
        )


def test_current_contact_rewrite_is_rejected_by_retained_validation(identities):
    _, identity, _ = identities
    party = create(identity)
    contacts = PartyContactService(identity.unit_of_work)
    result = contacts.add(
        party["id"],
        ContactMethodCommand("phone", "5035550133"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    with identity.unit_of_work.engine.begin() as connection:
        connection.execute(
            text("UPDATE party_contact_methods SET label='rewritten' WHERE id=:id"),
            {"id": result["id"]},
        )
    with identity.unit_of_work.engine.connect() as connection, pytest.raises(MigrationSchemaError):
        validate_party_schema(connection)


def test_contact_receipt_recovery_is_one_select(identities):
    _, identity, _ = identities
    party = create(identity)
    result = PartyContactService(identity.unit_of_work).add(
        party["id"],
        ContactMethodCommand("phone", "5035550144"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    statements = []

    def capture(connection, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(identity.unit_of_work.engine, "before_cursor_execute", capture)
    try:
        assert identity.recovery(operation_id=result["operationId"]) == result
    finally:
        event.remove(identity.unit_of_work.engine, "before_cursor_execute", capture)
    assert len([s for s in statements if s.lstrip().upper().startswith("SELECT")]) == 1
    assert not any(
        s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements
    )


def test_replacement_ownership_and_restore_uniqueness_fail_without_effects(identities):
    workspace, identity, _ = identities
    _, tenant, old, replacement = _tenant(identities)
    contacts = PartyContactService(identity.unit_of_work)
    other = create(identity)
    foreign = contacts.list(other["id"])[0]
    for target in (old["id"], foreign["id"], str(uuid4())):
        with pytest.raises(PartyValidationError):
            contacts.archive(
                tenant["id"],
                old["id"],
                confirmed=True,
                expected_revision=1,
                idempotency_key=str(uuid4()),
                reference_resolutions=(
                    ContactReferenceResolution(
                        "tenant", tenant["id"], target, expected_tenant_revision=2
                    ),
                ),
            )
    contacts.archive(
        tenant["id"],
        old["id"],
        confirmed=True,
        expected_revision=1,
        idempotency_key=str(uuid4()),
        reference_resolutions=(
            ContactReferenceResolution(
                "tenant", tenant["id"], replacement["id"], expected_tenant_revision=2
            ),
        ),
    )
    contacts.add(
        tenant["id"],
        ContactMethodCommand("email", old["displayValue"]),
        expected_revision=2,
        idempotency_key=str(uuid4()),
    )
    with pytest.raises(PartyConflictError):
        contacts.restore(tenant["id"], old["id"], expected_revision=3, idempotency_key=str(uuid4()))
    assert identity.get(tenant["id"])[0].revision == 3
    validate_latest_schema(workspace.paths.database)


def test_http_contract_required_fields_conflict_and_union_recovery(identities):
    _, identity, _ = identities
    party = create(identity)
    app = FastAPI()
    app.include_router(
        build_router(
            identity,
            PartyContactService(identity.unit_of_work),
            SimpleNamespace(ready=True, can_write=True, error=None),
        )
    )
    client = TestClient(app)
    endpoint = f"/api/parties/{party['id']}/contact-methods"
    assert (
        client.post(endpoint, json={"methodKind": "phone", "value": "5035550133"}).status_code
        == 422
    )
    payload = {
        "methodKind": "phone",
        "value": "5035550133",
        "expectedRevision": 1,
        "idempotencyKey": str(uuid4()),
    }
    response = client.post(endpoint, json=payload)
    assert response.status_code == 201, response.text
    result = response.json()
    assert client.post(endpoint, json=payload).json() == result
    assert client.get(f"/api/parties/operations/{result['operationId']}").json() == result
    stale = client.patch(
        f"{endpoint}/{result['id']}",
        json={**payload, "value": "5035550134", "idempotencyKey": str(uuid4())},
    )
    assert stale.status_code == 409 and stale.json()["detail"]["current"]["revision"] == 2
    assert client.post(endpoint, json={**payload, "expectedRevision": True}).status_code == 422


def test_contact_retained_history_rejects_tampered_owner_evidence(identities):
    _, identity, _ = identities
    _, tenant, old, replacement = _tenant(identities)
    result = PartyContactService(identity.unit_of_work).archive(
        tenant["id"],
        old["id"],
        confirmed=True,
        expected_revision=1,
        idempotency_key=str(uuid4()),
        reference_resolutions=(
            ContactReferenceResolution(
                "tenant", tenant["id"], replacement["id"], expected_tenant_revision=2
            ),
        ),
    )
    with identity.unit_of_work.engine.begin() as connection:
        trigger = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name='audit_events_no_delete'")
        ).scalar_one()
        connection.execute(text("DROP TRIGGER audit_events_no_delete"))
        connection.execute(
            text(
                "DELETE FROM audit_events WHERE entity_type='tenant_profile' AND correlation_id=(SELECT correlation_id FROM party_command_operations WHERE id=:id)"
            ),
            {"id": result["operationId"]},
        )
        connection.execute(text(trigger))
    with identity.unit_of_work.engine.connect() as connection, pytest.raises(MigrationSchemaError):
        validate_party_schema(connection)


def test_encrypted_backup_preserves_contacts_resolutions_and_receipts(identities, tmp_path):
    workspace, identity, recorder = identities
    _, tenant, old, replacement = _tenant(identities)
    result = PartyContactService(identity.unit_of_work).archive(
        tenant["id"],
        old["id"],
        confirmed=True,
        expected_revision=1,
        idempotency_key=str(uuid4()),
        reference_resolutions=(
            ContactReferenceResolution(
                "tenant", tenant["id"], replacement["id"], expected_tenant_revision=2
            ),
        ),
    )
    with identity.unit_of_work.engine.connect() as connection:
        before = {
            table: [
                dict(row)
                for row in connection.execute(
                    text(f"SELECT * FROM {table} ORDER BY rowid")
                ).mappings()
            ]
            for table in (
                "parties",
                "party_contact_methods",
                "tenant_profiles",
                "party_command_operations",
                "audit_events",
            )
        }
    backups = BackupService(
        workspace, recorder, lambda database: AuditRecorder(SQLiteAuditRepository(database))
    )
    archive = backups.create_backup("contact recovery backup passphrase")
    destination = tmp_path / "restored"
    backups.restore(archive.archive_path, "contact recovery backup passphrase", destination)
    engine = create_sqlite_engine(destination / "database" / "property-management.sqlite")
    try:
        with engine.connect() as connection:
            for table, rows in before.items():
                restored = {
                    row["id"] if "id" in row else row["party_id"]: dict(row)
                    for row in connection.execute(text(f"SELECT * FROM {table}")).mappings()
                }
                assert all(restored[row.get("id", row.get("party_id"))] == row for row in rows)
            stored = connection.execute(
                text("SELECT result_json FROM party_command_operations WHERE id=:id"),
                {"id": result["operationId"]},
            ).scalar_one()
            assert json.loads(stored) == result
            validate_party_schema(connection)
    finally:
        engine.dispose()

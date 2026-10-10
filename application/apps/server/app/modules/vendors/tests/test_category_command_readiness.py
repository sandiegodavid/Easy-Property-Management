"""Slice 26: category and assignment receipts across actual SQLite boundaries."""

import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from app.platform.testing_client import LocalApiClient as TestClient

from app.bootstrap.api import create_app

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.vendors.application.service import (
    ProviderCategoryAssignmentCommand,
    ProviderCategoryCommand,
    ProviderCategoryPatchCommand,
    ProviderError,
    ProviderLifecycleConflict,
    ProviderService,
)
from app.modules.vendors.infrastructure.unit_of_work import (
    _Transaction,
    SQLiteProviderUnitOfWork,
)
from app.modules.vendors.infrastructure.sqlalchemy_models import CATEGORY_COMMAND_TRIGGERS
from app.modules.vendors.tests.test_command_readiness import (
    create,
    provider_services as provider_services,
)
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema


def category(service, name="Specialty"):
    return service.create_category(
        ProviderCategoryCommand(name, 8, str(uuid4())), expected_revision=0
    )


def validate(service):
    validate_latest_schema(Path(service.unit_of_work.engine.url.database))


def test_original_category_result_noops_counts_and_seed_revision(provider_services):
    _, service, audit = provider_services
    created = category(service)
    cid = created["category"]["id"]
    first = create(service, category_ids=(cid,))
    key = str(uuid4())
    unchanged = service.update_category(
        cid,
        ProviderCategoryPatchCommand(display_name="Specialty"),
        expected_revision=1,
        idempotency_key=key,
    )
    assert unchanged["revision"] == 1
    assert unchanged["category"]["updatedAt"] == created["category"]["updatedAt"]
    assert unchanged["category"]["effectiveProviderCount"] == 1
    assert len(audit.history("provider_category", cid)) == 1
    archived = service.archive_category(
        cid, confirmed=True, reason="Retired", expected_revision=1, idempotency_key=str(uuid4())
    )
    assert archived["revision"] == 2
    assert archived["category"]["effectiveProviderCount"] == 0
    assert service.recover_category(operation_id=unchanged["operationId"]) == unchanged
    assert (
        service.update_category(
            cid,
            ProviderCategoryPatchCommand(display_name="Specialty"),
            expected_revision=1,
            idempotency_key=key,
        )
        == unchanged
    )
    with pytest.raises(ProviderLifecycleConflict) as changed:
        service.update_category(
            cid,
            ProviderCategoryPatchCommand(description="changed"),
            expected_revision=1,
            idempotency_key=key,
        )
    assert changed.value.code == "provider_category_idempotency_conflict"
    retried = service.archive_category(
        cid, confirmed=True, reason="Retired", expected_revision=2, idempotency_key=str(uuid4())
    )
    assert retried["revision"] == 2
    assert retried["category"] == archived["category"]
    with pytest.raises(ProviderLifecycleConflict):
        service.archive_category(
            cid, confirmed=True, reason="changed", expected_revision=2, idempotency_key=str(uuid4())
        )
    restored = service.restore_category(
        cid, confirmed=True, expected_revision=2, idempotency_key=str(uuid4())
    )
    assert restored["revision"] == 3
    assert restored["category"]["effectiveProviderCount"] == 1
    assert service.detail(first["party"]["id"])["profile"]["revision"] == 1
    seed = service.list_categories()[0]
    assert seed["revision"] == 1
    edited = service.update_category(
        seed["id"],
        ProviderCategoryPatchCommand(description="seed"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    assert edited["revision"] == 2
    validate(service)


def test_assignment_shared_revision_category_freshness_and_original_replay(provider_services):
    _, service, audit = provider_services
    c = category(service)["category"]
    p = create(service)["party"]["id"]
    command = ProviderCategoryAssignmentCommand(c["id"], str(uuid4()))
    assigned = service.assign_category(
        p, command, expected_revision=1, expected_category_revision=1
    )
    assert assigned["revision"] == assigned["profile"]["revision"] == 2
    assert assigned["category"] == {k: v for k, v in c.items() if k != "effectiveProviderCount"}
    aid = assigned["item"]["id"]
    archived = service.archive_category_assignment(
        p,
        aid,
        confirmed=True,
        reason="Not offered",
        expected_revision=2,
        idempotency_key=str(uuid4()),
    )
    assert archived["revision"] == 3
    assert (
        service.assign_category(p, command, expected_revision=1, expected_category_revision=1)
        == assigned
    )
    assert service.recover(operation_id=assigned["operationId"]) == assigned
    noop = service.archive_category_assignment(
        p,
        aid,
        confirmed=True,
        reason="Not offered",
        expected_revision=3,
        idempotency_key=str(uuid4()),
    )
    assert noop["revision"] == 3
    assert noop["item"] == archived["item"]
    service.update_category(
        c["id"],
        ProviderCategoryPatchCommand(description="New"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    with pytest.raises(ProviderLifecycleConflict) as stale:
        service.restore_category_assignment(
            p,
            aid,
            confirmed=True,
            expected_revision=3,
            expected_category_revision=1,
            idempotency_key=str(uuid4()),
        )
    assert stale.value.code == "provider_category_revision_conflict"
    assert stale.value.current["revision"] == 2
    restored = service.restore_category_assignment(
        p,
        aid,
        confirmed=True,
        expected_revision=3,
        expected_category_revision=2,
        idempotency_key=str(uuid4()),
    )
    assert restored["revision"] == 4
    with pytest.raises(ProviderLifecycleConflict) as stale_provider:
        service.archive_category_assignment(
            p,
            aid,
            confirmed=True,
            reason="Stale",
            expected_revision=3,
            idempotency_key=str(uuid4()),
        )
    assert stale_provider.value.current["revision"] == 4
    for result in (assigned, archived, noop, restored):
        receipt = audit.history("provider_command_operation", result["operationId"])
        assert len(receipt) == 1
        assert "Not offered" not in json.dumps(receipt[0].after_snapshot)
    validate(service)


@pytest.mark.parametrize("revision", [True, -1, "1", None])
def test_public_commands_reject_invalid_concurrency(provider_services, revision):
    _, service, _ = provider_services
    seed = service.list_categories()[0]
    with pytest.raises(ProviderError):
        service.update_category(
            seed["id"],
            ProviderCategoryPatchCommand(description="x"),
            expected_revision=revision,
            idempotency_key=str(uuid4()),
        )
    p = create(service)["party"]["id"]
    with pytest.raises(ProviderError):
        service.assign_category(
            p,
            ProviderCategoryAssignmentCommand(seed["id"], str(uuid4())),
            expected_revision=1,
            expected_category_revision=revision,
        )


def test_concurrent_category_edits_and_assignment_retries(provider_services):
    _, service, _ = provider_services
    cid = category(service)["category"]["id"]
    barrier = Barrier(2)

    def edit(value):
        barrier.wait()
        try:
            return service.update_category(
                cid,
                ProviderCategoryPatchCommand(description=value),
                expected_revision=1,
                idempotency_key=str(uuid4()),
            )
        except ProviderLifecycleConflict as exc:
            return exc

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(edit, ["one", "two"]))
    assert sum(isinstance(r, dict) for r in results) == 1
    p = create(service)["party"]["id"]
    cmd = ProviderCategoryAssignmentCommand(cid, str(uuid4()))
    barrier = Barrier(2)

    def assign(_):
        barrier.wait()
        return service.assign_category(p, cmd, expected_revision=1, expected_category_revision=2)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(assign, range(2)))
    assert results[0] == results[1]
    assert service.detail(p)["profile"]["revision"] == 2
    validate(service)


def test_receipt_audit_failure_rolls_back_category_and_assignment(provider_services):
    _, service, _ = provider_services
    cid = category(service)["category"]["id"]
    p = create(service)["party"]["id"]
    original = _Transaction.record_change

    def fail(tx, **fields):
        if fields["entity_type"].endswith("command_operation"):
            raise RuntimeError("receipt audit unavailable")
        return original(tx, **fields)

    with patch.object(_Transaction, "record_change", fail):
        with pytest.raises(RuntimeError):
            service.update_category(
                cid,
                ProviderCategoryPatchCommand(description="rollback"),
                expected_revision=1,
                idempotency_key=str(uuid4()),
            )
        with pytest.raises(RuntimeError):
            service.assign_category(
                p,
                ProviderCategoryAssignmentCommand(cid, str(uuid4())),
                expected_revision=1,
                expected_category_revision=1,
            )
    assert next(c for c in service.list_categories() if c["id"] == cid)["revision"] == 1
    assert service.detail(p)["categories"] == []
    assert service.detail(p)["profile"]["revision"] == 1
    validate(service)


def test_category_receipts_are_immutable_and_recovery_is_one_query(provider_services):
    _, service, _ = provider_services
    result = category(service)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(service.unit_of_work.engine, "before_cursor_execute", capture)
    try:
        assert service.recover_category(operation_id=result["operationId"]) == result
    finally:
        event.remove(service.unit_of_work.engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    with pytest.raises(IntegrityError), service.unit_of_work.engine.begin() as connection:
        connection.execute(text("UPDATE provider_category_command_operations SET action='patch'"))
    with pytest.raises(IntegrityError), service.unit_of_work.engine.begin() as connection:
        connection.execute(text("DELETE FROM provider_category_command_operations"))
    validate(service)


def test_category_and_assignment_history_survives_encrypted_restore(provider_services, tmp_path):
    workspace, service, audit = provider_services
    created = category(service)
    cid = created["category"]["id"]
    party = create(service)["party"]["id"]
    assigned = service.assign_category(
        party,
        ProviderCategoryAssignmentCommand(cid, str(uuid4())),
        expected_revision=1,
        expected_category_revision=1,
    )
    service.archive_category_assignment(
        party,
        assigned["item"]["id"],
        confirmed=True,
        reason="Portable reason",
        expected_revision=2,
        idempotency_key=str(uuid4()),
    )
    tables = (
        "provider_categories",
        "provider_category_assignments",
        "provider_category_command_operations",
        "provider_command_operations",
    )

    def rows(engine):
        with engine.connect() as connection:
            snapshot = {
                table: list(
                    map(tuple, connection.execute(text(f"SELECT * FROM {table} ORDER BY rowid")))
                )
                for table in tables
            }
            snapshot["audits"] = list(
                map(
                    tuple,
                    connection.execute(
                        text(
                            "SELECT * FROM audit_events WHERE entity_type LIKE 'provider_%' ORDER BY rowid"
                        )
                    ),
                )
            )
            return snapshot

    before = rows(service.unit_of_work.engine)
    backups = BackupService(
        workspace,
        AuditRecorder(audit),
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    with fast_backup_encryption():
        archive = backups.create_backup(
            "a sufficiently long passphrase", output_path=tmp_path / "backup"
        )
        backups.restore(
            archive.archive_path, "a sufficiently long passphrase", tmp_path / "restored"
        )
    db = tmp_path / "restored" / workspace.paths.database.relative_to(workspace.paths.root)
    restored = ProviderService(
        SQLiteProviderUnitOfWork(
            db,
            AuditRecorder(SQLiteAuditRepository(db)),
            service.unit_of_work.party_operations,
            service.unit_of_work.properties,
        )
    )
    assert rows(restored.unit_of_work.engine) == before
    assert restored.recover_category(operation_id=created["operationId"]) == created
    assert restored.recover(operation_id=assigned["operationId"]) == assigned
    validate(restored)


def test_tampered_category_result_is_rejected(provider_services):
    _, service, _ = provider_services
    result = category(service)
    with service.unit_of_work.engine.begin() as connection:
        connection.execute(text("DROP TRIGGER provider_category_command_operations_no_update"))
        result["category"]["effectiveProviderCount"] = 17
        connection.execute(
            text("UPDATE provider_category_command_operations SET result_json=:result"),
            {"result": json.dumps(result, sort_keys=True, separators=(",", ":"))},
        )
        connection.execute(
            text(CATEGORY_COMMAND_TRIGGERS["provider_category_command_operations_no_update"])
        )
    with pytest.raises(MigrationSchemaError):
        validate(service)


@pytest.mark.parametrize("action", ["create", "patch", "archive", "restore"])
def test_all_category_commands_fail_closed_on_receipt_write(provider_services, action):
    _, service, _ = provider_services
    category_state = category(service)["category"]
    cid = category_state["id"]
    revision = 1
    if action == "restore":
        service.archive_category(
            cid, confirmed=True, reason="Prior", expected_revision=1, idempotency_key=str(uuid4())
        )
        revision = 2
    before = service.list_categories(archive_state="all")
    key = str(uuid4())

    def execute():
        if action == "create":
            return service.create_category(
                ProviderCategoryCommand("Another", 9, key), expected_revision=0
            )
        if action == "patch":
            return service.update_category(
                cid,
                ProviderCategoryPatchCommand(description="new"),
                expected_revision=revision,
                idempotency_key=key,
            )
        return getattr(service, action + "_category")(
            cid,
            confirmed=True,
            expected_revision=revision,
            idempotency_key=key,
            **({"reason": "Archived"} if action == "archive" else {}),
        )

    with patch.object(
        _Transaction, "insert_category_operation", side_effect=RuntimeError("receipt")
    ):
        with pytest.raises(RuntimeError, match="receipt"):
            execute()
    assert service.list_categories(archive_state="all") == before
    validate(service)


@pytest.mark.parametrize("action", ["create", "archive", "restore"])
def test_all_assignment_commands_fail_closed_on_receipt_write(provider_services, action):
    _, service, _ = provider_services
    cid = category(service)["category"]["id"]
    party = create(service)["party"]["id"]
    revision, assignment = 1, None
    if action != "create":
        assignment = service.assign_category(
            party,
            ProviderCategoryAssignmentCommand(cid, str(uuid4())),
            expected_revision=1,
            expected_category_revision=1,
        )["item"]["id"]
        revision = 2
    if action == "restore":
        service.archive_category_assignment(
            party,
            assignment,
            confirmed=True,
            reason="Prior",
            expected_revision=2,
            idempotency_key=str(uuid4()),
        )
        revision = 3
    before = service.detail(party, include_archived=True)
    with patch.object(_Transaction, "insert_operation", side_effect=RuntimeError("receipt")):
        with pytest.raises(RuntimeError, match="receipt"):
            if action == "create":
                service.assign_category(
                    party,
                    ProviderCategoryAssignmentCommand(cid, str(uuid4())),
                    expected_revision=revision,
                    expected_category_revision=1,
                )
            else:
                getattr(service, action + "_category_assignment")(
                    party,
                    assignment,
                    confirmed=True,
                    expected_revision=revision,
                    idempotency_key=str(uuid4()),
                    **(
                        {"reason": "Archived"}
                        if action == "archive"
                        else {"expected_category_revision": 1}
                    ),
                )
    assert service.detail(party, include_archived=True) == before
    validate(service)


def test_api_required_metadata_conflicts_and_read_only_recovery(provider_services, tmp_path):
    workspace, service, _ = provider_services
    config = tmp_path / "api-config.json"
    config.write_text(json.dumps({"localWorkspacePath": str(workspace.paths.root)}))
    with TestClient(create_app(config)) as client:
        assert (
            client.post("/api/provider-categories", json={"displayName": "API"}).status_code == 422
        )
        request = {
            "displayName": "API",
            "displayOrder": 8,
            "expectedRevision": 0,
            "idempotencyKey": str(uuid4()),
        }
        response = client.post("/api/provider-categories", json=request)
        assert response.status_code == 201
        original = response.json()
        cid = original["category"]["id"]
        changed = client.patch(
            f"/api/provider-categories/{cid}",
            json={"description": "new", "expectedRevision": 1, "idempotencyKey": str(uuid4())},
        )
        assert changed.status_code == 200
        stale = client.patch(
            f"/api/provider-categories/{cid}",
            json={"description": "stale", "expectedRevision": 1, "idempotencyKey": str(uuid4())},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["current"]["revision"] == 2
        assert client.post("/api/provider-categories", json=request).json() == original
        assert (
            client.get(f"/api/provider-categories/operations/{original['operationId']}").json()
            == original
        )
        assert (
            client.get(
                f"/api/provider-categories/operations/by-key/{request['idempotencyKey']}"
            ).json()
            == original
        )
        p = create(service)["party"]["id"]
        body = {"categoryId": cid, "expectedRevision": 1, "idempotencyKey": str(uuid4())}
        assert client.post(f"/api/providers/{p}/category-assignments", json=body).status_code == 422
        body["expectedCategoryRevision"] = 1
        assert client.post(f"/api/providers/{p}/category-assignments", json=body).status_code == 409
        body["expectedCategoryRevision"] = 2
        result = client.post(f"/api/providers/{p}/category-assignments", json=body)
        assert result.status_code == 201
        assert result.json()["revision"] == 2
        assert (
            client.get(f"/api/providers/operations/{result.json()['operationId']}").json()
            == result.json()
        )
    validate(service)


@pytest.mark.parametrize(
    "damage", ["category_revision", "assignment_result", "receipt_correlation"]
)
def test_retained_validation_rejects_rewritten_source_or_receipt_history(provider_services, damage):
    _, service, _ = provider_services
    cid = category(service)["category"]["id"]
    party = create(service)["party"]["id"]
    assigned = service.assign_category(
        party,
        ProviderCategoryAssignmentCommand(cid, str(uuid4())),
        expected_revision=1,
        expected_category_revision=1,
    )
    with service.unit_of_work.engine.begin() as connection:
        if damage == "category_revision":
            connection.execute(
                text("UPDATE provider_categories SET revision=7 WHERE id=:id"), {"id": cid}
            )
        else:
            trigger = connection.execute(
                text(
                    "SELECT sql FROM sqlite_master WHERE name='provider_command_operations_no_update'"
                )
            ).scalar_one()
            connection.execute(text("DROP TRIGGER provider_command_operations_no_update"))
            if damage == "assignment_result":
                assigned["category"]["revision"] = 7
                connection.execute(
                    text("UPDATE provider_command_operations SET result_json=:result WHERE id=:id"),
                    {
                        "result": json.dumps(assigned, sort_keys=True, separators=(",", ":")),
                        "id": assigned["operationId"],
                    },
                )
            else:
                connection.execute(
                    text(
                        "UPDATE provider_command_operations SET correlation_id=:correlation WHERE id=:id"
                    ),
                    {"correlation": str(uuid4()), "id": assigned["operationId"]},
                )
            connection.execute(text(trigger))
    with pytest.raises(MigrationSchemaError):
        validate(service)

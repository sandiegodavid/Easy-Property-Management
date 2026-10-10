"""Slice 28 matrix: commands, retries, rollback, schema, restore and query budget."""

import json
from concurrent.futures import ThreadPoolExecutor
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
from app.modules.finance.application.expense_service import ExpenseService
from app.modules.finance.domain.expense_models import CategoryCreateCommand, CategoryPatchCommand
from app.modules.finance.domain.models import FinanceConflictError, FinanceError, VoidCommand
from app.modules.finance.infrastructure.expense_unit_of_work import SQLiteExpenseUnitOfWork
from app.modules.finance.tests import test_expenses as fixtures
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema


@pytest.fixture
def category_context():
    context = fixtures.ExpenseWorkflowTests()
    context.setUp()
    try:
        yield context
    finally:
        context.expenses.unit_of_work.engine.dispose()
        context.doCleanups()


def create(service, name="Specialty"):
    return service.create_category(
        CategoryCreateCommand(name), expected_revision=0, idempotency_key=str(uuid4())
    )


def snapshot(service):
    with service.unit_of_work.engine.connect() as connection:
        return {
            table: connection.exec_driver_sql(f"SELECT * FROM {table} ORDER BY id").all()
            for table in (
                "expense_categories",
                "expense_category_command_operations",
                "audit_events",
            )
        }


def test_original_results_replay_after_later_status_and_semantic_noop(category_context):
    service = category_context.expenses
    assert all(c["revision"] == 1 for c in service.list_categories())
    key = str(uuid4())
    command = CategoryCreateCommand("Specialty")
    created = service.create_category(command, expected_revision=0, idempotency_key=key)
    cid = created["id"]
    patch_key = str(uuid4())
    unchanged_command = CategoryPatchCommand(frozenset({"display_name"}), display_name="Specialty")
    unchanged = service.patch_category(
        cid, unchanged_command, expected_revision=1, idempotency_key=patch_key
    )
    assert unchanged["revision"] == 1
    assert unchanged["updatedAt"] == created["updatedAt"]
    assert unchanged["operationId"] != created["operationId"]
    assert len(category_context.audit.history("expense_category", cid)) == 1
    archived_key = str(uuid4())
    lifecycle = VoidCommand(True, "Retired")
    archived = service.archive_category(
        cid, lifecycle, expected_revision=1, idempotency_key=archived_key
    )
    restored_key = str(uuid4())
    restored = service.restore_category(
        cid, lifecycle, expected_revision=2, idempotency_key=restored_key
    )
    changed = service.patch_category(
        cid,
        CategoryPatchCommand(frozenset({"description"}), description="Later"),
        expected_revision=3,
        idempotency_key=str(uuid4()),
    )
    assert changed["revision"] == 4
    before = snapshot(service)
    for action, args, revision, receipt_key, original in (
        ("create_category", (command,), 0, key, created),
        ("patch_category", (cid, unchanged_command), 1, patch_key, unchanged),
        ("archive_category", (cid, lifecycle), 1, archived_key, archived),
        ("restore_category", (cid, lifecycle), 2, restored_key, restored),
    ):
        assert (
            getattr(service, action)(*args, expected_revision=revision, idempotency_key=receipt_key)
            == original
        )
        assert service.category_operation(original["operationId"]) == original
        assert service.category_operation_by_key(receipt_key) == original
    assert snapshot(service) == before
    validate_latest_schema(category_context.workspace.paths.database)


@pytest.mark.parametrize("action", ["create", "patch", "archive", "restore"])
def test_all_actions_rollback_receipt_and_audit_failures(category_context, action):
    service = category_context.expenses
    created = create(service)
    cid, revision = created["id"], 1
    if action == "restore":
        archived = service.archive_category(
            cid, VoidCommand(True, "Prior"), expected_revision=1, idempotency_key=str(uuid4())
        )
        revision = archived["revision"]
    args = (
        (CategoryCreateCommand("Another"),)
        if action == "create"
        else (
            cid,
            CategoryPatchCommand(frozenset({"description"}), description="Changed")
            if action == "patch"
            else VoidCommand(True, "Lifecycle"),
        )
    )
    if action == "create":
        revision = 0
    before = snapshot(service)
    engine = service.unit_of_work.engine
    for table in ("expense_category_command_operations", "audit_events"):
        condition = (
            "WHEN NEW.entity_type = 'expense_category_command_operation'"
            if table == "audit_events"
            else ""
        )
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE TRIGGER slice28_fail BEFORE INSERT ON {table} {condition} BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
            )
        try:
            with pytest.raises(FinanceConflictError):
                getattr(service, action + "_category")(
                    *args, expected_revision=revision, idempotency_key=str(uuid4())
                )
        finally:
            with engine.begin() as connection:
                connection.exec_driver_sql("DROP TRIGGER slice28_fail")
        assert snapshot(service) == before
    validate_latest_schema(category_context.workspace.paths.database)


def test_stale_and_changed_key_reuse_leave_no_writes(category_context):
    service = category_context.expenses
    created = create(service)
    cid, key = created["id"], str(uuid4())
    command = CategoryPatchCommand(frozenset({"description"}), description="First")
    service.patch_category(cid, command, expected_revision=1, idempotency_key=key)
    before = snapshot(service)
    with pytest.raises(FinanceConflictError) as stale:
        service.archive_category(
            cid, VoidCommand(True, "Stale"), expected_revision=1, idempotency_key=str(uuid4())
        )
    assert stale.value.code == "expense_category_revision_conflict"
    current = next(c for c in service.list_categories() if c["id"] == cid)
    assert stale.value.details["currentCategory"] == current
    assert stale.value.details["currentRevision"] == 2
    for args, revision in (
        ((cid, CategoryPatchCommand(frozenset({"description"}), description="Different")), 1),
        ((cid, command), 2),
    ):
        with pytest.raises(FinanceConflictError) as reused:
            service.patch_category(*args, expected_revision=revision, idempotency_key=key)
        assert reused.value.code == "expense_category_idempotency_conflict"
    assert snapshot(service) == before


@pytest.mark.parametrize("action", ["create", "patch", "archive", "restore"])
def test_required_metadata_and_canonical_key_validation(category_context, action):
    service = category_context.expenses
    cid = create(service)["id"]
    args = (
        (CategoryCreateCommand("Another"),)
        if action == "create"
        else (
            cid,
            CategoryPatchCommand(frozenset({"description"}), description="x")
            if action == "patch"
            else VoidCommand(True, "Lifecycle"),
        )
    )
    execute = getattr(service, action + "_category")
    with pytest.raises(TypeError):
        execute(*args)
    before = snapshot(service)
    revisions = (True, -1, "1", None, 1) if action == "create" else (True, -1, "1", None, 0)
    for revision in revisions:
        with pytest.raises(FinanceError):
            execute(*args, expected_revision=revision, idempotency_key=str(uuid4()))
    for key in ("", "invalid", str(uuid4()).upper(), uuid4().hex):
        with pytest.raises(FinanceError):
            execute(*args, expected_revision=0 if action == "create" else 1, idempotency_key=key)
    assert snapshot(service) == before


def test_concurrent_edits_and_exact_retries(category_context):
    service = category_context.expenses
    cid = create(service)["id"]
    barrier = Barrier(2)

    def edit(value):
        barrier.wait()
        try:
            return service.patch_category(
                cid,
                CategoryPatchCommand(frozenset({"description"}), description=value),
                expected_revision=1,
                idempotency_key=str(uuid4()),
            )
        except FinanceConflictError as error:
            return error

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(edit, ("one", "two")))
    assert sum(isinstance(result, dict) for result in results) == 1
    conflict = next(result for result in results if isinstance(result, FinanceConflictError))
    assert conflict.code == "expense_category_revision_conflict"
    barrier = Barrier(2)
    key = str(uuid4())

    def retry(_):
        barrier.wait()
        return service.archive_category(
            cid, VoidCommand(True, "Retired"), expected_revision=2, idempotency_key=key
        )

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(retry, range(2)))
    assert results[0] == results[1]
    assert len(category_context.audit.history("expense_category", cid)) == 3
    validate_latest_schema(category_context.workspace.paths.database)


@pytest.mark.parametrize("action", ["create", "patch", "archive", "restore"])
def test_all_actions_concurrent_exact_retries_have_one_receipt(category_context, action):
    service = category_context.expenses
    cid = create(service)["id"]
    revision = 0 if action == "create" else 1
    if action == "restore":
        service.archive_category(
            cid, VoidCommand(True, "Prior"), expected_revision=1, idempotency_key=str(uuid4())
        )
        revision = 2
    args = (
        (CategoryCreateCommand("Concurrent"),)
        if action == "create"
        else (
            cid,
            CategoryPatchCommand(frozenset({"description"}), description="Concurrent")
            if action == "patch"
            else VoidCommand(True, "Concurrent"),
        )
    )
    key = str(uuid4())
    barrier = Barrier(2)

    def execute(_):
        barrier.wait()
        return getattr(service, action + "_category")(
            *args, expected_revision=revision, idempotency_key=key
        )

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(execute, range(2)))
    assert results[0] == results[1]
    with service.unit_of_work.engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM expense_category_command_operations WHERE idempotency_key = :key"
                ),
                {"key": key},
            ).scalar_one()
            == 1
        )
    assert (
        len(
            category_context.audit.history(
                "expense_category_command_operation", results[0]["operationId"]
            )
        )
        == 1
    )
    validate_latest_schema(category_context.workspace.paths.database)


def test_invalid_lifecycle_and_empty_patch_have_no_receipts(category_context):
    service = category_context.expenses
    cid = create(service)["id"]
    before = snapshot(service)
    with pytest.raises(FinanceError):
        CategoryPatchCommand(frozenset())
    with pytest.raises(FinanceConflictError):
        service.restore_category(
            cid,
            VoidCommand(True, "Already active"),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
    assert snapshot(service) == before
    service.archive_category(
        cid, VoidCommand(True, "Retired"), expected_revision=1, idempotency_key=str(uuid4())
    )
    before = snapshot(service)
    with pytest.raises(FinanceConflictError):
        service.archive_category(
            cid,
            VoidCommand(True, "Already archived"),
            expected_revision=2,
            idempotency_key=str(uuid4()),
        )
    assert snapshot(service) == before


@pytest.mark.parametrize("lookup", ["id", "idempotency_key"])
def test_recovery_is_one_indexed_select(category_context, lookup):
    service = category_context.expenses
    key = str(uuid4())
    created = service.create_category(
        CategoryCreateCommand("Specialty"), expected_revision=0, idempotency_key=key
    )
    statements = []
    engine = service.unit_of_work.engine

    def capture(_connection, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = (
            service.category_operation(created["operationId"])
            if lookup == "id"
            else service.category_operation_by_key(key)
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result == created
    assert len(statements) == 1
    with engine.connect() as connection:
        plan = connection.exec_driver_sql(
            f"EXPLAIN QUERY PLAN SELECT * FROM expense_category_command_operations WHERE {lookup} = ?",
            (created["operationId"] if lookup == "id" else key,),
        ).all()
    assert "SEARCH" in str(plan) and "INDEX" in str(plan)


def test_append_only_and_tampered_result_rejected(category_context):
    service = category_context.expenses
    created = create(service)
    validate_latest_schema(category_context.workspace.paths.database)
    engine = service.unit_of_work.engine
    for mutation in (
        "UPDATE expense_category_command_operations SET action = 'patch'",
        "DELETE FROM expense_category_command_operations",
        "INSERT OR REPLACE INTO expense_category_command_operations SELECT * FROM expense_category_command_operations",
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.exec_driver_sql(mutation)
    with engine.begin() as connection:
        trigger = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE name = 'expense_category_command_operations_no_update'"
        ).scalar_one()
        connection.exec_driver_sql("DROP TRIGGER expense_category_command_operations_no_update")
        created["revision"] = 999
        connection.execute(
            text("UPDATE expense_category_command_operations SET result_json = :result"),
            {"result": json.dumps(created, sort_keys=True, separators=(",", ":"))},
        )
        connection.exec_driver_sql(trigger)
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(category_context.workspace.paths.database)


def test_seed_first_before_snapshot_is_anchored_to_registered_baseline(category_context):
    service = category_context.expenses
    seed = service.list_categories()[0]
    result = service.patch_category(
        seed["id"],
        CategoryPatchCommand(frozenset({"description"}), description="First edit"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    assert result["revision"] == 2
    validate_latest_schema(category_context.workspace.paths.database)
    engine = service.unit_of_work.engine
    with engine.begin() as connection:
        event_row = (
            connection.execute(
                text(
                    "SELECT id, before_snapshot FROM audit_events WHERE entity_type = 'expense_category' AND entity_id = :id"
                ),
                {"id": seed["id"]},
            )
            .mappings()
            .one()
        )
        baseline = json.loads(event_row["before_snapshot"])
        assert baseline == seed
        baseline["description"] = "Invented initial description"
        trigger = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE name = 'audit_events_no_update'"
        ).scalar_one()
        connection.exec_driver_sql("DROP TRIGGER audit_events_no_update")
        connection.execute(
            text("UPDATE audit_events SET before_snapshot = :snapshot WHERE id = :id"),
            {
                "id": event_row["id"],
                "snapshot": json.dumps(baseline, sort_keys=True, separators=(",", ":")),
            },
        )
        connection.exec_driver_sql(trigger)
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(category_context.workspace.paths.database)


def test_archived_patch_retains_lifecycle_and_validates_history(category_context):
    service = category_context.expenses
    created = create(service)
    cid = created["id"]
    archived = service.archive_category(
        cid, VoidCommand(True, "Retired"), expected_revision=1, idempotency_key=str(uuid4())
    )
    key = str(uuid4())
    command = CategoryPatchCommand(frozenset({"description"}), description="Archived metadata")
    updated = service.patch_category(cid, command, expected_revision=2, idempotency_key=key)
    assert updated["revision"] == 3
    assert updated["archivedAt"] == archived["archivedAt"]
    assert updated["description"] == "Archived metadata"
    assert all(c["id"] != cid for c in service.list_categories())
    assert (
        next(c for c in service.list_categories(include_archived=True) if c["id"] == cid)[
            "revision"
        ]
        == 3
    )
    noop = service.patch_category(cid, command, expected_revision=3, idempotency_key=str(uuid4()))
    assert noop["revision"] == 3
    assert noop["updatedAt"] == updated["updatedAt"]
    assert noop["operationId"] != updated["operationId"]
    service.restore_category(
        cid, VoidCommand(True, "Restore"), expected_revision=3, idempotency_key=str(uuid4())
    )
    assert service.patch_category(cid, command, expected_revision=2, idempotency_key=key) == updated
    assert service.category_operation(updated["operationId"]) == updated
    validate_latest_schema(category_context.workspace.paths.database)


def test_encrypted_restore_retains_ledger_audits_and_original_results(category_context, tmp_path):
    service = category_context.expenses
    created = create(service)
    archived = service.archive_category(
        created["id"],
        VoidCommand(True, "Retired"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    before = snapshot(service)
    backups = BackupService(
        category_context.workspace,
        AuditRecorder(category_context.audit),
        lambda db: AuditRecorder(SQLiteAuditRepository(db)),
    )
    with fast_backup_encryption():
        backup = backups.create_backup(
            "a sufficiently long passphrase", output_path=tmp_path / "backup"
        )
        backups.restore(
            backup.archive_path, "a sufficiently long passphrase", tmp_path / "restored"
        )
    database = tmp_path / "restored" / "database" / "property-management.sqlite"
    source = service.unit_of_work
    restored = ExpenseService(
        SQLiteExpenseUnitOfWork(
            database,
            AuditRecorder(SQLiteAuditRepository(database)),
            source.portfolio,
            source.providers,
            source.parties,
            source.files,
        )
    )
    try:
        # Backup activity adds workspace audits; category-owned history stays identical.
        after = snapshot(restored)
        for table in ("expense_categories", "expense_category_command_operations"):
            assert after[table] == before[table]
        assert all(row in after["audit_events"] for row in before["audit_events"])
        for result in (created, archived):
            assert restored.category_operation(result["operationId"]) == result
        validate_latest_schema(database)
    finally:
        restored.unit_of_work.engine.dispose()


def test_http_metadata_replay_conflict_and_read_only_recovery(category_context):
    with TestClient(create_app(category_context.config)) as client:
        payload = {
            "displayName": "API category",
            "expectedRevision": 0,
            "idempotencyKey": str(uuid4()),
        }
        for invalid in (
            {k: v for k, v in payload.items() if k != "expectedRevision"},
            {k: v for k, v in payload.items() if k != "idempotencyKey"},
            {**payload, "expectedRevision": True},
            {**payload, "expectedRevision": 1},
            {**payload, "idempotencyKey": payload["idempotencyKey"].upper()},
        ):
            assert client.post("/api/expense-categories", json=invalid).status_code == 422
        response = client.post("/api/expense-categories", json=payload)
        assert response.status_code == 201, response.text
        created = response.json()
        cid = created["id"]
        assert created["revision"] == 1
        assert client.post("/api/expense-categories", json=payload).json() == created
        metadata = {"expectedRevision": 1, "idempotencyKey": str(uuid4())}
        assert client.patch(f"/api/expense-categories/{cid}", json=metadata).status_code == 422
        updated = client.patch(
            f"/api/expense-categories/{cid}", json={**metadata, "description": "Changed"}
        )
        assert updated.status_code == 200, updated.text
        stale = client.post(
            f"/api/expense-categories/{cid}/archive",
            json={**metadata, "idempotencyKey": str(uuid4()), "confirmed": True, "reason": "Stale"},
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["code"] == "expense_category_revision_conflict"
        assert stale.json()["detail"]["currentCategory"]["revision"] == 2
        assert stale.json()["detail"]["currentRevision"] == 2
        lifecycle = {
            "expectedRevision": 2,
            "idempotencyKey": str(uuid4()),
            "confirmed": True,
            "reason": "Retired",
        }
        archived = client.post(f"/api/expense-categories/{cid}/archive", json=lifecycle)
        assert archived.status_code == 200, archived.text
        assert archived.json()["revision"] == 3
        restore_input = {**lifecycle, "expectedRevision": 3, "idempotencyKey": str(uuid4())}
        restored = client.post(f"/api/expense-categories/{cid}/restore", json=restore_input)
        assert restored.status_code == 200, restored.text
        assert restored.json()["revision"] == 4
        assert restored.json()["archivedAt"] is None
        assert (
            client.post(f"/api/expense-categories/{cid}/archive", json=lifecycle).json()
            == archived.json()
        )
        assert (
            client.post(f"/api/expense-categories/{cid}/restore", json=restore_input).json()
            == restored.json()
        )
        before = snapshot(category_context.expenses)
        runtime = client.app.state.workspace_runtime
        with patch.object(
            type(runtime), "can_write", new_callable=lambda: property(lambda _: False)
        ):
            for path in (
                f"operations/{created['operationId']}",
                f"operations/by-key/{payload['idempotencyKey']}",
            ):
                recovered = client.get(f"/api/expense-categories/{path}")
                assert recovered.status_code == 200, recovered.text
                assert recovered.json() == created
        assert snapshot(category_context.expenses) == before
        assert client.get(f"/api/expense-categories/operations/{uuid4()}").status_code == 404
        assert client.get(f"/api/expense-categories/operations/by-key/{uuid4()}").status_code == 404

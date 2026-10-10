"""Recoverable creation uses real SQLite receipts, audit and portable history."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from app.platform.testing_client import LocalApiClient as TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.tasks.api.router import build_router
from app.modules.tasks.application.service import TaskConflictError, TaskError, TaskService
from app.modules.tasks.application.mutations import TaskMutationCommand, TaskMutationService
from app.modules.tasks.application.waiting import (
    WaitingCommand,
    WaitingConflict,
    WaitingError,
    WaitingNotFound,
)
from app.modules.tasks.application.waiting_service import TaskWaitingService
from app.modules.tasks.infrastructure.creation_receipt_reader import SQLiteTaskCreationReceiptReader
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceService, WorkspacePaths
from app.platform.config import LocalConfig
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema


@pytest.fixture
def creation(tmp_path):
    workspace = WorkspaceService(LocalConfig(tmp_path / "config.json", tmp_path / "workspace"))
    workspace.initialize()
    recorder = AuditRecorder(SQLiteAuditRepository(workspace.paths.database))
    uow = SQLiteTaskUnitOfWork(workspace.paths.database, recorder)
    service = TaskService(uow, now=lambda: datetime(2026, 10, 8, 12, tzinfo=UTC))
    yield workspace, service
    uow.engine.dispose()


def submit(service, key, **changes):
    return service.create_command(
        {"title": "Call owner", **changes}, expected_revision=0, idempotency_key=key
    )


def test_original_response_replay_after_task_changes(creation):
    workspace, service = creation
    key = str(uuid4())
    result = submit(service, key)
    assert result["revision"] == 1 and result["operationId"]
    service.transition(result["id"], "completed", "Done")
    assert submit(service, key) == result == service.creation_receipt(key)
    with pytest.raises(TaskConflictError):
        submit(service, key, title="Different")
    assert len(service.list()) == 1
    validate_latest_schema(workspace.paths.database)


@pytest.mark.parametrize("revision", [True, None, -1, 1, "0"])
def test_creation_revision_is_exact_zero(creation, revision):
    _, service = creation
    with pytest.raises(TaskError):
        service.create_command(
            {"title": "x"}, expected_revision=revision, idempotency_key=str(uuid4())
        )
    assert service.list() == []


@pytest.mark.parametrize("failure", ["audit", "receipt"])
def test_failure_rolls_back_task_receipt_and_audits(creation, failure):
    _, service = creation
    key = str(uuid4())

    def fail_receipt(_connection, _cursor, statement, *_args):
        if statement.startswith("INSERT INTO task_creation_operations"):
            raise RuntimeError("receipt unavailable")

    @contextmanager
    def failing_write():
        if failure == "audit":
            with patch.object(
                service.unit_of_work.recorder,
                "record_change",
                side_effect=RuntimeError("audit unavailable"),
            ):
                yield
        else:
            event.listen(service.unit_of_work.engine, "before_cursor_execute", fail_receipt)
            try:
                yield
            finally:
                event.remove(service.unit_of_work.engine, "before_cursor_execute", fail_receipt)

    with failing_write(), pytest.raises(RuntimeError):
        submit(service, key)
    assert service.list() == []
    assert service.unit_of_work.creation_operation(key) is None
    assert submit(service, key)["revision"] == 1


def test_concurrent_duplicate_creates_one_task(creation):
    workspace, service = creation
    key, barrier = str(uuid4()), Barrier(2)

    def run(_):
        barrier.wait()
        return submit(service, key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert results[0] == results[1]
    assert len(service.list()) == 1
    validate_latest_schema(workspace.paths.database)


def test_typed_http_contract_requires_identity_and_exposes_receipt(creation):
    _, service = creation
    app = FastAPI()
    app.include_router(
        build_router(service, SimpleNamespace(ready=True, error=None, can_write=True))
    )
    payload = {"title": "Call owner", "expectedRevision": 0, "idempotencyKey": str(uuid4())}
    with TestClient(app) as client:
        assert client.post("/api/tasks", json={"title": "x"}).status_code == 422
        assert (
            client.post("/api/tasks", json={**payload, "expectedRevision": True}).status_code == 422
        )
        first = client.post("/api/tasks", json=payload)
        assert first.status_code == 201
        assert client.post("/api/tasks", json=payload).json() == first.json()
        assert (
            client.get(f"/api/tasks/creation-operations/{payload['idempotencyKey']}").json()
            == first.json()
        )
        assert client.post("/api/tasks", json={**payload, "title": "Changed"}).status_code == 409
    schema = app.openapi()
    assert schema["paths"]["/api/tasks"]["post"]["operationId"] == "createTask"
    assert {"expectedRevision", "idempotencyKey"} <= set(
        schema["components"]["schemas"]["TaskCreationRequest"]["required"]
    )


def test_retained_receipt_is_append_only_and_correlated(creation):
    workspace, service = creation
    result = submit(service, str(uuid4()))
    with pytest.raises(DBAPIError), service.unit_of_work.engine.begin() as connection:
        connection.execute(text("DELETE FROM task_creation_operations"))
    with service.unit_of_work.engine.begin() as connection:
        connection.execute(text("DROP TRIGGER task_creation_operations_no_update"))
        connection.execute(
            text("UPDATE task_creation_operations SET request_fingerprint=:fingerprint"),
            {"fingerprint": "f" * 64},
        )
        connection.execute(
            text(
                "CREATE TRIGGER task_creation_operations_no_update BEFORE UPDATE ON task_creation_operations BEGIN SELECT RAISE(ABORT, 'task creation operations are append-only'); END"
            )
        )
    with pytest.raises(MigrationSchemaError, match="Task creation"):
        validate_latest_schema(workspace.paths.database)
    assert result["operationId"]


def test_encrypted_backup_preserves_creation_receipt_and_replay(creation, tmp_path):
    workspace, service = creation
    key = str(uuid4())
    result = submit(service, key)
    backup = BackupService(
        workspace,
        service.unit_of_work.recorder,
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    archive = backup.create_backup(
        "task creation portable passphrase", output_path=tmp_path / "tasks.epmbackup"
    )
    target = tmp_path / "restored"
    backup.restore(archive.archive_path, "task creation portable passphrase", target)
    database = WorkspacePaths(target).database
    restored = SQLiteTaskUnitOfWork(database, AuditRecorder(SQLiteAuditRepository(database)))
    try:
        assert submit(TaskService(restored), key) == result
        assert restored.creation_operation(key) == service.unit_of_work.creation_operation(key)
        validate_latest_schema(database)
    finally:
        restored.engine.dispose()


def test_receipt_projection_uses_one_query_on_callers_connection(creation):
    _, service = creation
    key = str(uuid4())
    result = submit(service, key)
    statements = []

    def count(_connection, _cursor, statement, *_args):
        statements.append(statement)

    engine = service.unit_of_work.engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        with engine.connect() as connection, connection.begin():
            value = SQLiteTaskCreationReceiptReader().receipt(connection, key)
        assert value["id"] == result["operationId"]
        assert sum(statement.lstrip().upper().startswith("SELECT") for statement in statements) <= 1
    finally:
        event.remove(engine, "before_cursor_execute", count)


def test_deleted_receipt_rejected_with_valid_schema(creation):
    workspace, service = creation
    submit(service, str(uuid4()))
    with service.unit_of_work.engine.begin() as connection:
        connection.execute(text("DROP TRIGGER task_creation_operations_no_delete"))
        connection.execute(text("DELETE FROM task_creation_operations"))
        connection.execute(
            text(
                "CREATE TRIGGER task_creation_operations_no_delete BEFORE DELETE ON task_creation_operations BEGIN SELECT RAISE(ABORT, 'task creation operations are append-only'); END"
            )
        )
    with pytest.raises(MigrationSchemaError, match="Task creation"):
        validate_latest_schema(workspace.paths.database)


def mutation_service(service):
    return TaskMutationService(service.unit_of_work, now=service.instant)


def change(service, task, action, **fields):
    command = TaskMutationCommand(task["id"], action, task["revision"], str(uuid4()), **fields)
    return mutation_service(service).mutate(command), command


def test_lifecycle_and_reminder_commands_replay_original_complete_results(creation):
    workspace, service = creation
    task = submit(service, str(uuid4()))
    originals = []
    for action in ("start", "complete", "reopen", "cancel", "reopen"):
        result, command = change(service, task, action, confirmed=action != "start")
        assert result["revision"] == task["revision"] + 1
        originals.append((command, result))
        task = result["task"]
    for action in ("acknowledge", "dismiss"):
        created, command = change(
            service, task, "add_reminder", remind_at_utc="2026-10-08T12:00:00+00:00"
        )
        originals.append((command, created))
        result, command = change(
            service, created["task"], action, reminder_id=created["reminder"]["id"], confirmed=True
        )
        originals.append((command, result))
        task = result["task"]
        assert result["reminder"]["status"] == (
            "acknowledged" if action == "acknowledge" else "dismissed"
        )
    mutations = mutation_service(service)
    for command, original in originals:
        assert mutations.mutate(command) == original == mutations.operation(command.idempotency_key)
    validate_latest_schema(workspace.paths.database)


def test_mutation_conflicts_and_exact_revision_validation(creation):
    _, service = creation
    task = submit(service, str(uuid4()))
    result, command = change(service, task, "start")
    mutations = mutation_service(service)
    from dataclasses import replace

    with pytest.raises(WaitingConflict):
        mutations.mutate(replace(command, action="complete", confirmed=True))
    with pytest.raises(WaitingConflict) as stale:
        mutations.mutate(replace(command, idempotency_key=str(uuid4())))
    assert stale.value.current_revision == result["revision"]
    for value in (True, None, "1", 0, -1):
        with pytest.raises(WaitingError):
            replace(command, expected_revision=value)


def test_completion_rolls_back_reminder_dismissal_and_receipt_on_audit_failure(creation):
    workspace, service = creation
    task = submit(service, str(uuid4()))
    pending, _ = change(service, task, "add_reminder", remind_at_utc="2026-10-08T12:00:00+00:00")
    command = TaskMutationCommand(
        task["id"], "complete", pending["revision"], str(uuid4()), confirmed=True
    )
    mutations = mutation_service(service)
    original = service.unit_of_work.recorder.record_change

    def fail_operation(*args, **values):
        if values["entity_type"] == "task_mutation_operation":
            raise RuntimeError("receipt audit unavailable")
        return original(*args, **values)

    with (
        patch.object(service.unit_of_work.recorder, "record_change", side_effect=fail_operation),
        pytest.raises(RuntimeError),
    ):
        mutations.mutate(command)
    assert service.get(task["id"]).revision == pending["revision"]
    assert service.unit_of_work.reminders(task["id"])[0].status == "pending"
    assert service.unit_of_work.mutation_operation(command.idempotency_key) is None
    result = mutations.mutate(command)
    assert result["revision"] == pending["revision"] + 1
    assert service.unit_of_work.reminders(task["id"])[0].status == "dismissed"
    validate_latest_schema(workspace.paths.database)


def test_concurrent_duplicate_mutation_advances_revision_once(creation):
    workspace, service = creation
    task = submit(service, str(uuid4()))
    command = TaskMutationCommand(task["id"], "start", task["revision"], str(uuid4()))
    barrier = Barrier(2)

    def run(_):
        barrier.wait()
        return mutation_service(service).mutate(command)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert results[0] == results[1]
    assert service.get(task["id"]).revision == 2
    validate_latest_schema(workspace.paths.database)


def test_typed_mutations_require_identity_and_expose_original_receipt(creation):
    _, service = creation
    task = submit(service, str(uuid4()))
    app = FastAPI()
    app.include_router(
        build_router(
            service,
            SimpleNamespace(ready=True, error=None, can_write=True),
            mutations=mutation_service(service),
        )
    )
    payload = {"expectedRevision": 1, "idempotencyKey": str(uuid4())}
    with TestClient(app) as client:
        url = f"/api/tasks/{task['id']}/start"
        assert client.post(url).status_code == 422
        assert client.post(url, json={**payload, "expectedRevision": True}).status_code == 422
        response = client.post(url, json=payload)
        assert response.status_code == 200
        assert client.post(url, json=payload).json() == response.json()
        assert (
            client.get(f"/api/tasks/mutation-operations/{payload['idempotencyKey']}").json()
            == response.json()
        )
        stale = client.post(url, json={**payload, "idempotencyKey": str(uuid4())})
        assert stale.status_code == 409 and stale.json()["detail"]["currentRevision"] == 2
    schema = app.openapi()
    assert schema["paths"]["/api/tasks/{task_id}/start"]["post"]["operationId"] == "startTask"


@pytest.mark.parametrize("action", ["complete", "delete"])
def test_mutation_history_survives_encrypted_backup(creation, tmp_path, action):
    workspace, service = creation
    task = submit(service, str(uuid4()))
    fields = {"outcome_note": "Done"} if action == "complete" else {}
    result, command = change(service, task, action, confirmed=True, **fields)
    backup = BackupService(
        workspace,
        service.unit_of_work.recorder,
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    archive = backup.create_backup(
        "task mutation portable passphrase", output_path=tmp_path / "mutation.epmbackup"
    )
    target = tmp_path / "restored-mutations"
    backup.restore(archive.archive_path, "task mutation portable passphrase", target)
    database = WorkspacePaths(target).database
    restored = SQLiteTaskUnitOfWork(database, AuditRecorder(SQLiteAuditRepository(database)))
    try:
        assert mutation_service(TaskService(restored)).mutate(command) == result
        assert restored.mutation_operation(
            command.idempotency_key
        ) == service.unit_of_work.mutation_operation(command.idempotency_key)
        if action == "delete":
            assert restored.get(task["id"]) is None
            assert restored.list(status=None) == []
        validate_latest_schema(database)
    finally:
        restored.engine.dispose()


def test_mutation_receipt_tampering_rejected(creation):
    workspace, service = creation
    task = submit(service, str(uuid4()))
    change(service, task, "start")
    with pytest.raises(DBAPIError), service.unit_of_work.engine.begin() as connection:
        connection.execute(text("DELETE FROM task_mutation_operations"))
    with service.unit_of_work.engine.begin() as connection:
        connection.execute(text("DROP TRIGGER task_mutation_operations_no_update"))
        connection.execute(
            text("UPDATE task_mutation_operations SET request_fingerprint=:hash"),
            {"hash": "f" * 64},
        )
        connection.execute(
            text(
                "CREATE TRIGGER task_mutation_operations_no_update BEFORE UPDATE ON task_mutation_operations BEGIN SELECT RAISE(ABORT, 'task mutation operations are append-only'); END"
            )
        )
    with pytest.raises(MigrationSchemaError, match="Task mutation"):
        validate_latest_schema(workspace.paths.database)


def test_waiting_and_reminder_commands_share_parent_revision(creation):
    workspace, service = creation
    task = submit(service, str(uuid4()))
    waiting = TaskWaitingService(
        service.unit_of_work,
        now=service.instant,
        read_identity=lambda: (str(uuid4()), str(uuid4())),
    )
    result = waiting.mutate(
        WaitingCommand(task["id"], "set", 1, str(uuid4()), kind="person", label="Owner")
    )
    with pytest.raises(WaitingConflict):
        change(service, task, "add_reminder", remind_at_utc="2026-10-08T12:00:00+00:00")
    completed, command = change(service, result, "complete", confirmed=True)
    assert completed["revision"] == 3 and completed["task"]["isWaiting"] is False
    assert mutation_service(service).mutate(command) == completed
    validate_latest_schema(workspace.paths.database)


def test_missing_and_inactive_reminder_commands_are_typed(creation):
    _, service = creation
    task = submit(service, str(uuid4()))
    with pytest.raises(WaitingNotFound):
        change(service, task, "dismiss", reminder_id=str(uuid4()), confirmed=True)
    result, _ = change(service, task, "complete", confirmed=True)
    with pytest.raises(WaitingConflict):
        change(service, result["task"], "add_reminder", remind_at_utc="2026-10-08T12:00:00+00:00")
    assert service.get(task["id"]).revision == 2


def test_terminal_command_select_budget_does_not_grow_with_reminders(creation):
    _, service = creation
    counts = []
    for size in (1, 50):
        task = submit(service, str(uuid4()))
        for _ in range(size):
            service.add_reminder(task["id"], "2026-10-08T12:00:00+00:00")
        statements = []

        def count(_connection, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        engine = service.unit_of_work.engine
        event.listen(engine, "before_cursor_execute", count)
        try:
            change(service, task, "complete", confirmed=True)
        finally:
            event.remove(engine, "before_cursor_execute", count)
        counts.append(len(statements))
    assert counts[0] == counts[1] and counts[1] <= 3


def test_task_patch_preserves_waiting_and_normalizes_complete_result(creation):
    workspace, service = creation
    task = submit(service, str(uuid4()))
    waiting = TaskWaitingService(
        service.unit_of_work,
        now=service.instant,
        read_identity=lambda: (str(uuid4()), str(uuid4())),
    )
    task = waiting.mutate(
        WaitingCommand(task["id"], "set", 1, str(uuid4()), kind="event", label="Inspection")
    )
    result, command = change(
        service,
        task,
        "edit",
        changes=(
            ("title", "  Updated task  "),
            ("notes", "  Operator note  "),
            ("priority", "urgent"),
            ("due_at_utc", "2026-10-09T13:00:00-07:00"),
            ("due_timezone", "America/Los_Angeles"),
            ("is_all_day", True),
            ("related_entity_type", "maintenance_issue"),
            ("related_entity_id", str(uuid4())),
            ("related_label", "  Repair  "),
        ),
    )
    updated = result["task"]
    assert updated["title"] == "Updated task" and updated["notes"] == "Operator note"
    assert (
        updated["dueAtUtc"] == "2026-10-09T07:00:00+00:00" and updated["relatedLabel"] == "Repair"
    )
    assert (
        updated["revision"] == 3
        and updated["isWaiting"]
        and updated["waitingFor"] == task["waitingFor"]
    )
    later, _ = change(service, updated, "edit", changes=(("notes", None),))
    assert later["task"]["notes"] is None
    assert mutation_service(service).mutate(command) == result
    validate_latest_schema(workspace.paths.database)


def test_unchanged_patch_records_receipt_without_change_audit_or_revision(creation):
    workspace, service = creation
    task = submit(service, str(uuid4()))
    result, command = change(service, task, "edit", changes=(("title", "Call owner"),))
    assert result["task"] == {key: value for key, value in task.items() if key != "operationId"}
    assert result["revision"] == 1
    second, _ = change(service, result["task"], "edit", changes=(("title", "Call owner"),))
    assert second["revision"] == 1 and second["operationId"] != result["operationId"]
    with service.unit_of_work.engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM audit_events WHERE entity_type='task' AND action='updated'"
                )
            )
            == 0
        )
    from dataclasses import replace

    with pytest.raises(WaitingConflict):
        mutation_service(service).mutate(replace(command, changes=(("notes", None),)))
    change(service, result["task"], "edit", changes=(("title", "New title"),))
    assert mutation_service(service).mutate(command) == result
    validate_latest_schema(workspace.paths.database)


@pytest.mark.parametrize(
    "changes",
    [
        (),
        (("status", "cancelled"),),
        (("title", None),),
        (("priority", []),),
        (("is_all_day", 1),),
        (("due_at_utc", "2026-10-08T12:00:00"),),
        (("due_timezone", "unknown/zone"),),
        (("related_entity_id", "not-uuid"),),
        (("notes", "x" * 10001),),
    ],
)
def test_invalid_edit_command_never_writes(creation, changes):
    _, service = creation
    task = submit(service, str(uuid4()))
    with pytest.raises(WaitingError):
        change(service, task, "edit", changes=changes)
    assert service.get(task["id"]).revision == 1


def test_edit_requires_valid_resulting_pairs_and_active_task(creation):
    _, service = creation
    task = submit(service, str(uuid4()))
    with pytest.raises(WaitingError):
        change(service, task, "edit", changes=(("due_at_utc", "2026-10-08T12:00:00+00:00"),))
    with pytest.raises(WaitingError):
        change(service, task, "edit", changes=(("related_entity_type", "lease"),))
    terminal, _ = change(service, task, "complete", confirmed=True)
    with pytest.raises(WaitingConflict):
        change(service, terminal["task"], "edit", changes=(("title", "Edit completed"),))


def test_delete_tombstone_hides_task_and_preserves_original_receipts(creation):
    workspace, service = creation
    key = str(uuid4())
    task = submit(service, key, dueAtUtc="2026-10-08T12:00:00+00:00", dueTimezone="UTC")
    updated, edit = change(service, task, "edit", changes=(("priority", "high"),))
    deleted, command = change(service, updated["task"], "delete", confirmed=True)
    assert (
        deleted["revision"] == 3
        and deleted["task"]["deletedAtUtc"] == deleted["task"]["updatedAtUtc"]
    )
    from app.modules.tasks.application.service import TaskNotFoundError

    with pytest.raises(TaskNotFoundError):
        service.get(task["id"])
    assert service.list() == [] and service.page()[0] == []
    assert service.summary()["dueRemindersTotal"] == 0
    assert service.summary()["todayTotal"] == 0
    assert submit(service, key, dueAtUtc="2026-10-08T12:00:00+00:00", dueTimezone="UTC") == task
    assert mutation_service(service).mutate(edit) == updated
    assert mutation_service(service).mutate(command) == deleted
    with pytest.raises(WaitingNotFound):
        change(service, deleted["task"], "edit", changes=(("title", "Changed"),))
    validate_latest_schema(workspace.paths.database)


def test_delete_enforces_reminder_history_and_clears_waiting(creation):
    workspace, service = creation
    task = submit(service, str(uuid4()))
    created, _ = change(service, task, "add_reminder", remind_at_utc="2026-10-08T12:00:00+00:00")
    with pytest.raises(WaitingConflict):
        change(service, created["task"], "delete", confirmed=True)
    dismissed, _ = change(
        service, created["task"], "dismiss", reminder_id=created["reminder"]["id"], confirmed=True
    )
    waiting = TaskWaitingService(
        service.unit_of_work,
        now=service.instant,
        read_identity=lambda: (str(uuid4()), str(uuid4())),
    )
    task = waiting.mutate(
        WaitingCommand(
            task["id"], "set", dismissed["revision"], str(uuid4()), kind="person", label="Owner"
        )
    )
    deleted, command = change(service, task, "delete", confirmed=True)
    assert not deleted["task"]["isWaiting"] and deleted["revision"] == task["revision"] + 1
    assert mutation_service(service).mutate(command) == deleted
    validate_latest_schema(workspace.paths.database)


@pytest.mark.parametrize(
    "action", ["complete", "cancel", "reopen", "acknowledge", "dismiss", "delete"]
)
@pytest.mark.parametrize("confirmed", [False, 1, "true"])
def test_consequential_commands_require_strict_confirmation(creation, action, confirmed):
    _, service = creation
    task = submit(service, str(uuid4()))
    with pytest.raises(WaitingError):
        change(service, task, action, confirmed=confirmed)


def test_edit_and_delete_api_contract_and_rollback(creation):
    workspace, service = creation
    task = submit(service, str(uuid4()))
    app = FastAPI()
    app.include_router(
        build_router(
            service,
            SimpleNamespace(ready=True, error=None, can_write=True),
            mutations=mutation_service(service),
        )
    )
    with TestClient(app) as client:
        url = f"/api/tasks/{task['id']}"
        patch_payload = {"expectedRevision": 1, "idempotencyKey": str(uuid4()), "title": "Edited"}
        assert client.patch(url, json={"title": "Edited"}).status_code == 422
        for changes in ({}, {"title": None}, {"priority": None}, {"isAllDay": None}):
            assert (
                client.patch(
                    url, json={"expectedRevision": 1, "idempotencyKey": str(uuid4()), **changes}
                ).status_code
                == 422
            )
        assert client.patch(url, json={**patch_payload, "status": "cancelled"}).status_code == 422
        result = client.patch(url, json=patch_payload)
        assert result.status_code == 200 and result.json()["revision"] == 2
        payload = {"expectedRevision": 2, "idempotencyKey": str(uuid4()), "confirmed": True}
        assert client.request("DELETE", url, json={**payload, "confirmed": 1}).status_code == 422
        command = TaskMutationCommand(
            task["id"], "delete", 2, payload["idempotencyKey"], confirmed=True
        )
        with (
            patch.object(
                service.unit_of_work.recorder,
                "record_change",
                side_effect=RuntimeError("audit unavailable"),
            ),
            pytest.raises(RuntimeError),
        ):
            mutation_service(service).mutate(command)
        assert service.get(task["id"]).revision == 2
        deleted = client.request("DELETE", url, json=payload)
        assert deleted.status_code == 200
        assert client.get(url).status_code == 404
        assert client.request("DELETE", url, json=payload).json() == deleted.json()
        assert (
            client.get(f"/api/tasks/mutation-operations/{payload['idempotencyKey']}").json()
            == deleted.json()
        )
    schema = app.openapi()
    assert schema["paths"]["/api/tasks/{task_id}"]["patch"]["operationId"] == "editTask"
    assert schema["paths"]["/api/tasks/{task_id}"]["delete"]["operationId"] == "deleteTask"
    validate_latest_schema(workspace.paths.database)


def test_deleted_task_is_hidden_from_source_projections_but_retained_context_exists(creation):
    from app.modules.tasks.infrastructure.context_reader import SQLiteTaskContextReader
    from app.modules.tasks.infrastructure.search_reader import SQLiteTaskSearchReader
    from app.platform.context_reads import ReadWindow
    from app.platform.metadata_search import SearchTerm

    workspace, service = creation
    parent = str(uuid4())
    task = submit(
        service,
        str(uuid4()),
        title="Call owner",
        related_entity_type="property",
        related_entity_id=parent,
        related_label="Property",
    )
    change(service, task, "delete", confirmed=True)
    reader = SQLiteTaskContextReader()
    with service.unit_of_work.engine.connect() as connection:
        assert reader.task(connection, task["id"])["deleted_at_utc"] is not None
        assert reader.tasks_for_related_entities(connection, "property", [parent]) == {}
        assert reader.active_related_entity_ids(connection, "property", [parent]) == set()
        previews = reader.previews_for_related_entities(
            connection, "property", [parent], now=service.instant()
        )
        assert previews[parent].total == 0 and previews[parent].items == []
        search = SQLiteTaskSearchReader().search(
            connection, SearchTerm("Call"), ReadWindow(service.instant())
        )
        assert search.total == 0 and search.items == []
    validate_latest_schema(workspace.paths.database)


def test_mutation_receipt_cannot_be_replaced_with_recursive_triggers_disabled(creation):
    workspace, service = creation
    task = submit(service, str(uuid4()))
    result, command = change(service, task, "edit", changes=(("title", "Edited"),))
    with service.unit_of_work.engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA recursive_triggers=OFF")
        with pytest.raises(DBAPIError, match="append-only"):
            connection.exec_driver_sql(
                "INSERT OR REPLACE INTO task_mutation_operations "
                "SELECT * FROM task_mutation_operations"
            )
    assert mutation_service(service).operation(command.idempotency_key) == result
    validate_latest_schema(workspace.paths.database)

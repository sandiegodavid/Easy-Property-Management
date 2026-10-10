"""Slice 27 matrix: replay, validation, rollback, schema, portability and query budget."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from app.platform.testing_client import LocalApiClient as TestClient
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError

from app.bootstrap.owner_concern_context import SQLiteOwnerConcernContext
from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.owner_management.application.service import OwnerConcernService
from app.modules.owner_management.domain.models import (
    FollowUpInput,
    OwnerConcernConflictError,
    OwnerConcernError,
)
from app.modules.owner_management.infrastructure.unit_of_work import SQLiteOwnerConcernUnitOfWork
from app.modules.owner_management.tests import test_owner_concerns as fixtures
from app.modules.tasks.application.mutations import TaskMutationCommand, TaskMutationService
from app.modules.tasks.domain.models import Task
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel
from app.modules.tasks.infrastructure.transaction_operations import SQLiteTaskTransactionOperations
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceError, WorkspaceService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.config import LocalConfig


@pytest.fixture
def context():
    fixture = fixtures.OwnerConcernTests()
    fixture.setUp()
    try:
        yield fixture
    finally:
        fixture.doCleanups()


def create_concern(context, **changes):
    return context.service.create(
        context._command(idempotency_key=str(uuid4()), **changes), expected_revision=0
    )


def database_snapshot(context, *, source_audits_only=False):
    """Compare all compound-write boundaries, including unrelated baseline audits."""
    with context.service.unit_of_work.engine.connect() as connection:
        return {
            table: list(
                connection.exec_driver_sql(
                    f"SELECT * FROM {table}"
                    + (
                        " WHERE entity_type LIKE 'owner_concern%' OR entity_type LIKE 'task%'"
                        if table == "audit_events" and source_audits_only
                        else ""
                    )
                    + " ORDER BY rowid"
                )
            )
            for table in (
                "owner_concerns",
                "owner_concern_follow_up_operations",
                "owner_concern_command_operations",
                "tasks",
                "audit_events",
            )
        }


def test_original_results_survive_later_concern_and_task_state(context):
    service = context.service
    command = context._command(idempotency_key=str(uuid4()), follow_up=FollowUpInput("Call"))
    created = service.create(command, expected_revision=0)
    patch_key, lifecycle_key, followup_key = (str(uuid4()) for _ in range(3))
    edited = service.patch(
        created["id"], {"summary": "Edited"}, expected_revision=1, idempotency_key=patch_key
    )
    started = service.transition(
        created["id"],
        "in_progress",
        confirmed=True,
        expected_revision=2,
        idempotency_key=lifecycle_key,
    )
    followup = FollowUpInput("Second call", notes="Full task snapshot", priority="high")
    followed = service.follow_up(created["id"], followup, followup_key, expected_revision=3)
    assert [item["revision"] for item in (created, edited, started, followed)] == [1, 2, 3, 4]
    service.transition(
        created["id"],
        "resolved",
        confirmed=True,
        narrative="Handled",
        expected_revision=4,
        idempotency_key=str(uuid4()),
    )
    tasks = TaskMutationService(
        SQLiteTaskUnitOfWork(
            context.workspace.paths.database,
            AuditRecorder(SQLiteAuditRepository(context.workspace.paths.database)),
        ),
        now=lambda: datetime.now(UTC),
    )
    for original in (created, followed):
        task = original["followUpTask"]
        assert task["status"] == "open"
        assert {"id", "revision", "title", "notes", "priority", "relatedEntityId"} <= set(task)
        with service.unit_of_work.engine.connect() as connection:
            row = (
                connection.execute(select(TaskModel.__table__).where(TaskModel.id == task["id"]))
                .mappings()
                .one()
            )
        assert task == Task(**dict(row)).to_dict()
        tasks.mutate(
            TaskMutationCommand(
                task["id"],
                "complete",
                task["revision"],
                str(uuid4()),
                confirmed=True,
            )
        )
    assert service.create(command, expected_revision=0) == created
    assert (
        service.patch(
            created["id"], {"summary": "Edited"}, expected_revision=1, idempotency_key=patch_key
        )
        == edited
    )
    assert (
        service.transition(
            created["id"],
            "in_progress",
            confirmed=True,
            expected_revision=2,
            idempotency_key=lifecycle_key,
        )
        == started
    )
    assert service.follow_up(created["id"], followup, followup_key, expected_revision=3) == followed
    for original, key in zip(
        (created, edited, started, followed),
        (command.idempotency_key, patch_key, lifecycle_key, followup_key),
        strict=True,
    ):
        assert service.command_operation(original["operationId"]) == original
        assert service.command_operation_by_key(key) == original
    context.workspace.open()


@pytest.mark.parametrize("action", ["create", "patch", "transition", "follow_up"])
@pytest.mark.parametrize("invalid", [True, False, -1, "1", None])
def test_direct_revision_validation_is_fail_closed(context, action, invalid):
    item = create_concern(context)
    before = database_snapshot(context)
    with pytest.raises(OwnerConcernError):
        if action == "create":
            context.service.create(
                context._command(idempotency_key=str(uuid4())), expected_revision=invalid
            )
        elif action == "patch":
            context.service.patch(
                item["id"],
                {"summary": "Invalid"},
                expected_revision=invalid,
                idempotency_key=str(uuid4()),
            )
        elif action == "transition":
            context.service.transition(
                item["id"],
                "in_progress",
                confirmed=True,
                expected_revision=invalid,
                idempotency_key=str(uuid4()),
            )
        else:
            context.service.follow_up(
                item["id"], FollowUpInput("Invalid"), str(uuid4()), expected_revision=invalid
            )
    assert database_snapshot(context) == before


@pytest.mark.parametrize(
    "action", ["create", "patch", "transition", "follow_up", "operation", "key"]
)
def test_malformed_uuid_validation(context, action):
    item = create_concern(context)
    before = database_snapshot(context)
    with pytest.raises(OwnerConcernError):
        if action == "create":
            context.service.create(
                context._command(idempotency_key="not-a-uuid"), expected_revision=0
            )
        elif action == "patch":
            context.service.patch(item["id"], {}, expected_revision=1, idempotency_key="not-a-uuid")
        elif action == "transition":
            context.service.transition(
                item["id"],
                "in_progress",
                confirmed=True,
                expected_revision=1,
                idempotency_key="not-a-uuid",
            )
        elif action == "follow_up":
            context.service.follow_up(
                item["id"], FollowUpInput("Invalid"), "not-a-uuid", expected_revision=1
            )
        elif action == "operation":
            context.service.command_operation("not-a-uuid")
        else:
            context.service.command_operation_by_key("not-a-uuid")
    assert database_snapshot(context) == before


def test_stale_revision_contains_current_snapshot(context):
    item = create_concern(context)
    changed = context.service.patch(
        item["id"], {"summary": "Current"}, expected_revision=1, idempotency_key=str(uuid4())
    )
    before = database_snapshot(context)
    with pytest.raises(OwnerConcernConflictError) as conflict:
        context.service.follow_up(
            item["id"], FollowUpInput("Stale"), str(uuid4()), expected_revision=1
        )
    assert conflict.value.code == "owner_concern_revision_conflict"
    assert conflict.value.details["current"]["revision"] == changed["revision"]
    assert conflict.value.details["current"] == context.service.get(item["id"])
    assert database_snapshot(context) == before


def test_changed_key_reuse_and_global_action_namespace(context):
    command = context._command(idempotency_key=str(uuid4()))
    item = context.service.create(command, expected_revision=0)
    before = database_snapshot(context)
    for invoke in (
        lambda: context.service.create(replace(command, summary="Changed"), expected_revision=0),
        lambda: context.service.patch(
            item["id"], {}, expected_revision=1, idempotency_key=command.idempotency_key
        ),
        lambda: context.service.transition(
            item["id"],
            "in_progress",
            confirmed=True,
            expected_revision=1,
            idempotency_key=command.idempotency_key,
        ),
        lambda: context.service.follow_up(
            item["id"], FollowUpInput("Changed"), command.idempotency_key, expected_revision=1
        ),
    ):
        with pytest.raises(OwnerConcernConflictError) as conflict:
            invoke()
        assert conflict.value.code == "idempotency_conflict"
        assert database_snapshot(context) == before


def test_noop_has_own_receipt_without_incrementing_revision(context):
    item = create_concern(context)
    key = str(uuid4())
    noop = context.service.patch(
        item["id"], {"summary": item["summary"]}, expected_revision=1, idempotency_key=key
    )
    assert noop["revision"] == item["revision"]
    assert noop["operationId"] != item["operationId"]
    context.service.patch(
        item["id"], {"summary": "Later"}, expected_revision=1, idempotency_key=str(uuid4())
    )
    assert (
        context.service.patch(
            item["id"], {"summary": item["summary"]}, expected_revision=1, idempotency_key=key
        )
        == noop
    )
    assert context.service.command_operation_by_key(key) == noop
    context.workspace.open()


@pytest.mark.parametrize(
    "action",
    ["create", "patch", "noop", "in_progress", "resolved", "dismissed", "open", "follow_up"],
)
@pytest.mark.parametrize("failure", ["receipt", "audit"])
def test_receipt_and_audit_failure_roll_back_all_writes(context, action, failure):
    item = create_concern(context)
    if action == "open":
        item = context.service.transition(
            item["id"],
            "resolved",
            confirmed=True,
            narrative="Closed before reopen",
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
    before = database_snapshot(context)

    def fail(_connection, _cursor, statement, _parameters, _context, _many):
        normalized = statement.lstrip().lower()
        if (
            failure == "receipt"
            and normalized.startswith("insert")
            and "owner_concern_command_operations" in normalized
        ):
            raise RuntimeError("injected write failure")

    recorder = context.service.unit_of_work.recorder
    original_record = recorder.record_change

    def fail_receipt_audit(connection, **change):
        if change["entity_type"] == "owner_concern_command_operation":
            raise RuntimeError("injected write failure")
        return original_record(connection, **change)

    audit_failure = (
        patch.object(recorder, "record_change", side_effect=fail_receipt_audit)
        if failure == "audit"
        else nullcontext()
    )
    engine = context.service.unit_of_work.engine
    event.listen(engine, "before_cursor_execute", fail)
    try:
        with audit_failure, pytest.raises(RuntimeError, match="injected write failure"):
            if action == "create":
                create_concern(
                    context,
                    duplicate_confirmed=True,
                    duplicate_reason="Separate",
                    follow_up=FollowUpInput("Rollback"),
                )
            elif action in {"patch", "noop"}:
                context.service.patch(
                    item["id"],
                    {"summary": "Rollback" if action == "patch" else item["summary"]},
                    expected_revision=item["revision"],
                    idempotency_key=str(uuid4()),
                )
            elif action in {"in_progress", "resolved", "dismissed", "open"}:
                context.service.transition(
                    item["id"],
                    action,
                    confirmed=True,
                    narrative="Rollback lifecycle",
                    expected_revision=item["revision"],
                    idempotency_key=str(uuid4()),
                )
            else:
                context.service.follow_up(
                    item["id"], FollowUpInput("Rollback"), str(uuid4()), expected_revision=1
                )
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert database_snapshot(context) == before
    context.workspace.open()


def test_all_lifecycle_results_replay_after_reopen(context):
    item = create_concern(context)
    results = []
    for target in ("in_progress", "resolved", "open", "dismissed", "open"):
        revision, key = item["revision"], str(uuid4())
        item = context.service.transition(
            item["id"],
            target,
            confirmed=True,
            narrative="Lifecycle narrative",
            expected_revision=revision,
            idempotency_key=key,
        )
        results.append((target, revision, key, item))
    assert item["revision"] == 6
    for target, revision, key, original in results:
        assert (
            context.service.transition(
                item["id"],
                target,
                confirmed=True,
                narrative="Lifecycle narrative",
                expected_revision=revision,
                idempotency_key=key,
            )
            == original
        )
        assert context.service.command_operation(original["operationId"]) == original
    context.workspace.open()


@pytest.mark.parametrize("terminal", ["resolved", "dismissed"])
def test_terminal_followup_preserves_lifecycle_and_replays_original_result(context, terminal):
    item = create_concern(context)
    item = context.service.transition(
        item["id"],
        terminal,
        confirmed=True,
        narrative="Closed",
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    before = database_snapshot(context)
    follow_up, key = FollowUpInput("Follow up after closure"), str(uuid4())
    followed = context.service.follow_up(
        item["id"], follow_up, key, expected_revision=item["revision"]
    )
    assert followed["revision"] == item["revision"] + 1
    terminal_fields = (
        "status",
        "resolvedAtUtc",
        "resolutionSummary",
        "dismissedAtUtc",
        "dismissalReason",
    )
    assert {field: followed[field] for field in terminal_fields} == {
        field: item[field] for field in terminal_fields
    }
    assert followed["followUpTask"]["status"] == "open"
    assert followed["followUpTask"]["relatedEntityId"] == item["id"]
    after = database_snapshot(context)
    for table in (
        "tasks",
        "owner_concern_follow_up_operations",
        "owner_concern_command_operations",
    ):
        assert len(after[table]) == len(before[table]) + 1
    assert (
        context.service.follow_up(item["id"], follow_up, key, expected_revision=item["revision"])
        == followed
    )
    assert database_snapshot(context) == after
    context.workspace.open()

    later = context.service.follow_up(
        item["id"],
        FollowUpInput("Another independent follow-up"),
        str(uuid4()),
        expected_revision=followed["revision"],
    )
    assert later["revision"] == followed["revision"] + 1
    assert {field: later[field] for field in terminal_fields} == {
        field: item[field] for field in terminal_fields
    }
    before_replay = database_snapshot(context)
    assert (
        context.service.follow_up(item["id"], follow_up, key, expected_revision=item["revision"])
        == followed
    )
    assert context.service.command_operation(followed["operationId"]) == followed
    assert context.service.command_operation_by_key(key) == followed
    assert database_snapshot(context) == before_replay
    context.workspace.open()


@pytest.mark.parametrize("action", ["create", "follow_up"])
def test_task_insert_failure_rolls_back_concern_and_evidence(context, action):
    item = create_concern(context)
    before = database_snapshot(context)

    def fail_task(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith("insert into tasks"):
            raise RuntimeError("injected task failure")

    engine = context.service.unit_of_work.engine
    event.listen(engine, "before_cursor_execute", fail_task)
    try:
        with pytest.raises(RuntimeError, match="injected task failure"):
            if action == "create":
                create_concern(
                    context,
                    duplicate_confirmed=True,
                    duplicate_reason="Independent",
                    follow_up=FollowUpInput("Rolled back task"),
                )
            else:
                context.service.follow_up(
                    item["id"],
                    FollowUpInput("Rolled back task"),
                    str(uuid4()),
                    expected_revision=1,
                )
    finally:
        event.remove(engine, "before_cursor_execute", fail_task)
    assert database_snapshot(context) == before
    context.workspace.open()


@pytest.mark.parametrize("action", ["create", "follow_up"])
def test_same_key_concurrency_commits_one_result_and_task(context, action):
    item = create_concern(context)
    command = context._command(
        idempotency_key=str(uuid4()),
        duplicate_confirmed=True,
        duplicate_reason="Separate",
        follow_up=FollowUpInput("Concurrent"),
    )
    key, barrier = str(uuid4()), Barrier(2)
    before = database_snapshot(context)

    def submit(_):
        barrier.wait(timeout=10)
        if action == "create":
            return context.service.create(command, expected_revision=0)
        return context.service.follow_up(
            item["id"], FollowUpInput("Concurrent"), key, expected_revision=1
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert results[0] == results[1]
    after = database_snapshot(context)
    assert len(after["tasks"]) == len(before["tasks"]) + 1
    assert (
        len(after["owner_concern_command_operations"])
        == len(before["owner_concern_command_operations"]) + 1
    )
    assert len(after["owner_concerns"]) == len(before["owner_concerns"]) + (action == "create")
    context.workspace.open()


@pytest.mark.parametrize("lookup", ["id", "key"])
def test_recovery_is_one_indexed_read(context, lookup):
    command = context._command(idempotency_key=str(uuid4()))
    item = context.service.create(command, expected_revision=0)
    reads = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            reads.append((statement, parameters))

    engine = context.service.unit_of_work.engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        if lookup == "id":
            assert context.service.command_operation(item["operationId"]) == item
        else:
            assert context.service.command_operation_by_key(command.idempotency_key) == item
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(reads) == 1
    statement, parameters = reads[0]
    with engine.connect() as connection:
        plan = connection.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters).all()
    assert any("SEARCH" in row[3] and "INDEX" in row[3] for row in plan)
    assert all("SCAN" not in row[3] for row in plan)


def test_receipts_are_append_only(context):
    item = create_concern(context)
    for sql in (
        "UPDATE owner_concern_command_operations SET id=id",
        "DELETE FROM owner_concern_command_operations",
        "INSERT OR REPLACE INTO owner_concern_command_operations SELECT * FROM owner_concern_command_operations",
    ):
        with context.service.unit_of_work.engine.begin() as connection:
            with pytest.raises(IntegrityError):
                connection.exec_driver_sql(sql)
    assert context.service.command_operation(item["operationId"]) == item


@pytest.mark.parametrize(
    "tamper", ["result", "fingerprint", "revision", "audit", "trigger", "index"]
)
def test_workspace_rejects_schema_and_receipt_tampering(context, tamper):
    item = create_concern(context)
    if tamper == "audit":
        context._delete_audit("entity_type='owner_concern_command_operation'", {})
    with context.service.unit_of_work.engine.begin() as connection:
        if tamper in {"result", "fingerprint", "trigger"}:
            trigger = connection.exec_driver_sql(
                "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='owner_concern_command_operations' AND upper(sql) LIKE '%BEFORE UPDATE%'"
            ).one()
            connection.exec_driver_sql(f'DROP TRIGGER "{trigger.name}"')
            if tamper == "result":
                connection.execute(
                    text("UPDATE owner_concern_command_operations SET result_json=:value"),
                    {"value": json.dumps(item | {"revision": 999})},
                )
            elif tamper == "fingerprint":
                connection.execute(
                    text("UPDATE owner_concern_command_operations SET request_fingerprint=:value"),
                    {"value": "0" * 64},
                )
            if tamper != "trigger":
                connection.exec_driver_sql(trigger.sql)
        elif tamper == "revision":
            connection.exec_driver_sql("UPDATE owner_concerns SET revision=revision+1")
        elif tamper == "index":
            index = connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='owner_concerns' AND sql IS NOT NULL LIMIT 1"
            ).scalar_one()
            connection.exec_driver_sql(f'DROP INDEX "{index}"')
    with pytest.raises(WorkspaceError, match="Workspace database is invalid"):
        context.workspace.open()


def test_encrypted_backup_restores_original_results_and_evidence(context, tmp_path):
    created = create_concern(context, follow_up=FollowUpInput("Portable"))
    patched = context.service.patch(
        created["id"],
        {"summary": "Portable edit"},
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    followed = context.service.follow_up(
        created["id"], FollowUpInput("Portable second task"), str(uuid4()), expected_revision=2
    )
    terminal = context.service.transition(
        created["id"],
        "resolved",
        confirmed=True,
        narrative="Done",
        expected_revision=3,
        idempotency_key=str(uuid4()),
    )
    before = database_snapshot(context, source_audits_only=True)
    backups = BackupService(
        context.workspace,
        AuditRecorder(SQLiteAuditRepository(context.workspace.paths.database)),
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    with fast_backup_encryption():
        backup = backups.create_backup(
            "a sufficiently long passphrase", output_path=tmp_path / "encrypted"
        )
        backups.restore(
            backup.archive_path, "a sufficiently long passphrase", tmp_path / "restored"
        )
    workspace = WorkspaceService(
        LocalConfig(tmp_path / "restored-config.json", tmp_path / "restored")
    )
    workspace.open()
    service = OwnerConcernService(
        SQLiteOwnerConcernUnitOfWork(
            workspace.paths.database,
            AuditRecorder(SQLiteAuditRepository(workspace.paths.database)),
            SQLiteOwnerConcernContext(SQLiteTaskTransactionOperations()),
        ),
        now=lambda: context.now,
    )
    for original in (created, patched, followed, terminal):
        assert service.command_operation(original["operationId"]) == original
    with patch.object(context, "service", service):
        assert database_snapshot(context, source_audits_only=True) == before


def test_real_api_success_required_metadata_and_original_recovery(context, tmp_path):
    payload = {
        "ownerPartyId": context.owner.id,
        "propertyId": context.property.id,
        "concernType": "general_rental",
        "summary": "API concern",
        "description": "API details",
        "raisedAtUtc": context.now.replace(hour=20).isoformat(),
        "expectedRevision": 0,
        "idempotencyKey": str(uuid4()),
        "followUp": {"title": "First API task"},
    }
    config = tmp_path / "api-config.json"
    config.write_text(json.dumps({"localWorkspacePath": str(context.workspace.paths.root)}))
    with TestClient(create_app(config)) as client:
        base = "/api/owner-concerns"
        for field in ("expectedRevision", "idempotencyKey"):
            assert (
                client.post(
                    base, json={key: value for key, value in payload.items() if key != field}
                ).status_code
                == 422
            )
        response = client.post(base, json=payload)
        assert response.status_code == 200, response.text
        first = response.json()
        assert first["revision"] == 1
        assert first["followUpTask"]["title"] == "First API task"
        path = f"{base}/{first['id']}"
        for method, url, body in (
            ("patch", path, {"summary": "Missing metadata"}),
            ("post", f"{path}/start", {"confirmed": True}),
            ("post", f"{path}/follow-ups", {"title": "Missing metadata"}),
        ):
            assert client.request(method, url, json=body).status_code == 422
        patch_payload = {
            "summary": "API edit",
            "expectedRevision": 1,
            "idempotencyKey": str(uuid4()),
        }
        changed = client.patch(path, json=patch_payload)
        assert changed.status_code == 200, changed.text
        assert changed.json()["revision"] == 2
        follow_payload = {
            "title": "Second API task",
            "expectedRevision": 2,
            "idempotencyKey": str(uuid4()),
        }
        followed = client.post(f"{path}/follow-ups", json=follow_payload)
        assert followed.status_code == 200, followed.text
        assert followed.json()["revision"] == 3
        assert followed.json()["followUpTask"]["relatedEntityId"] == first["id"]
        assert client.post(base, json=payload).json() == first
        assert client.patch(path, json=patch_payload).json() == changed.json()
        assert client.post(f"{path}/follow-ups", json=follow_payload).json() == followed.json()
        assert client.get(f"{base}/operations/{first['operationId']}").json() == first
        assert client.get(f"{base}/operations/by-key/{payload['idempotencyKey']}").json() == first
        stale = client.patch(path, json=patch_payload | {"idempotencyKey": str(uuid4())})
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["current"]["revision"] == 3


def test_composed_communication_links_and_correction_preserve_concern_revision(context, tmp_path):
    config = tmp_path / "links-api-config.json"
    config.write_text(json.dumps({"localWorkspacePath": str(context.workspace.paths.root)}))
    with TestClient(create_app(config)) as client:
        concern_response = client.post(
            "/api/owner-concerns",
            json={
                "ownerPartyId": context.owner.id,
                "propertyId": context.property.id,
                "concernType": "general_rental",
                "summary": "Concern with communication",
                "description": "Owner called",
                "raisedAtUtc": context.now.replace(hour=20).isoformat(),
                "expectedRevision": 0,
                "idempotencyKey": str(uuid4()),
            },
        )
        assert concern_response.status_code == 200, concern_response.text
        concern = concern_response.json()
        concern_path = f"/api/owner-concerns/{concern['id']}"
        payload = {
            "direction": "inbound",
            "channel": "phone",
            "subject": "Owner called about concern",
            "body": "Original call details",
            "occurredAtUtc": context.now.isoformat(),
            "occurredTimezone": "America/Los_Angeles",
            "participants": [{"partyId": context.owner.id, "role": "sender"}],
            "links": [{"entityType": "owner_concern", "entityId": concern["id"]}],
            "record": True,
            "expectedRevision": 0,
            "idempotencyKey": str(uuid4()),
        }
        communication_response = client.post("/api/communications", json=payload)
        assert communication_response.status_code == 200, communication_response.text
        communication = communication_response.json()
        assert communication["revision"] == 1
        assert len(communication["links"]) == 1
        link = communication["links"][0]
        assert (link["entityType"], link["entityId"]) == ("owner_concern", concern["id"])
        detail = client.get(concern_path).json()
        assert detail["revision"] == concern["revision"]
        assert detail["linkedCommunicationCount"] == 1
        assert [item["id"] for item in detail["recentCommunications"]] == [communication["id"]]
        started = client.post(
            f"{concern_path}/start",
            json={
                "confirmed": True,
                "expectedRevision": 1,
                "idempotencyKey": str(uuid4()),
            },
        )
        assert started.status_code == 200, started.text
        assert started.json()["revision"] == 2
        assert client.post("/api/communications", json=payload).json() == communication
        assert (
            client.get(f"/api/communications/operations/{communication['operationId']}").json()
            == communication
        )
        correction_payload = {key: value for key, value in payload.items() if key != "record"} | {
            "subject": "Corrected owner call",
            "body": "Corrected call details",
            "correctionReason": "Clarified the owner request",
            "expectedRevision": communication["revision"],
            "idempotencyKey": str(uuid4()),
        }
        correction_path = f"/api/communications/{communication['id']}/correct"
        correction_response = client.post(correction_path, json=correction_payload)
        assert correction_response.status_code == 200, correction_response.text
        correction = correction_response.json()
        assert correction["supersedesCommunicationId"] == communication["id"]
        assert correction["links"][0]["entityId"] == concern["id"]
        assert client.get(concern_path).json()["revision"] == 2
        resolved = client.post(
            f"{concern_path}/resolve",
            json={
                "confirmed": True,
                "summary": "Handled",
                "expectedRevision": 2,
                "idempotencyKey": str(uuid4()),
            },
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["revision"] == 3
        assert client.post(correction_path, json=correction_payload).json() == correction
        assert client.post("/api/communications", json=payload).json() == communication
        assert (
            client.get(f"/api/communications/operations/{correction['operationId']}").json()
            == correction
        )
        assert client.get(concern_path).json()["revision"] == 3
        assert (
            client.get(f"/api/owner-concerns/operations/{concern['operationId']}").json() == concern
        )
    context.workspace.open()

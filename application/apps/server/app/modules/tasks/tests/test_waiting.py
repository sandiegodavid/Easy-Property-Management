"""TASK-002 acceptance tests through real SQLite boundaries."""

import json
import hashlib
import sqlite3
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from app.modules.audit.application.recorder import AuditRecorder
from app.bootstrap.api import create_app
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.tasks.api.router import build_router
from app.modules.tasks.application.service import TaskService
from app.modules.tasks.application.waiting import (
    FollowUpQuery,
    WaitingCommand,
    WaitingConflict,
    WaitingError,
    WaitingNotFound,
    WaitingUnavailable,
    WaitingStorageFailure,
)
from app.modules.tasks.application.waiting_service import TaskWaitingService
from app.modules.tasks.domain.models import waiting_facts
from app.modules.tasks.infrastructure.context_reader import SQLiteTaskContextReader
from app.modules.tasks.infrastructure.schema_validation import validate_task_schema
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork
from app.modules.workspace.application.backup_service import BackupService, BackupError
from app.modules.workspace.infrastructure.encrypted_archive import (
    decrypt_archive_to_zip,
    make_header,
    write_encrypted_archive,
)
from app.modules.workspace.application.service import WorkspaceService, WorkspacePaths
from app.modules.workspace.application.service import WorkspaceError
from app.platform.config import LocalConfig
from app.platform.migration_errors import MigrationSchemaError
from app.platform.api_errors import register_api_error_handlers
from app.platform.secrets import BackupSecretStore


class MemorySecrets(BackupSecretStore):
    def get_passphrase(self, workspace_id):
        return None

    def set_passphrase(self, workspace_id, passphrase):
        pass

    def delete_passphrase(self, workspace_id):
        pass


class WaitingTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / "config.json").write_text(
            json.dumps({"localWorkspacePath": str(root / "workspace")}), encoding="utf-8"
        )
        self.workspace = WorkspaceService(
            LocalConfig(
                root / "config.json", root / "workspace", backup_destination_path=root / "backups"
            )
        )
        manifest = self.workspace.initialize()
        self.now = datetime(2026, 10, 7, 19, tzinfo=UTC)
        self.audit = SQLiteAuditRepository(self.workspace.paths.database)
        self.recorder = AuditRecorder(self.audit)
        self.uow = SQLiteTaskUnitOfWork(self.workspace.paths.database, self.recorder)
        self.tasks = TaskService(self.uow, now=lambda: self.now)
        self.identity = (manifest.workspace_id, str(uuid4()))
        self.waiting = TaskWaitingService(
            self.uow, read_identity=lambda: self.identity, now=lambda: self.now
        )
        self.task = self.tasks.create(
            {
                "title": "Ask owner",
                "priority": "urgent",
                "dueAtUtc": "2026-10-06T19:00:00+00:00",
                "dueTimezone": "America/Los_Angeles",
            }
        )

    def command(self, action="set", **kwargs):
        values = {
            "task_id": self.task.id,
            "action": action,
            "expected_revision": self.tasks.get(self.task.id).revision,
            "idempotency_key": str(uuid4()),
        }
        if action == "set":
            values.update(kind="person", label="Owner")
        if action == "clear":
            values["confirmed"] = True
        values.update(kwargs)
        return WaitingCommand(**values)

    def test_set_replay_conflict_and_independent_deadline_reminders(self):
        reminder = self.tasks.add_reminder(self.task.id, self.now.isoformat())
        command = self.command(
            follow_up_at=(self.now + timedelta(hours=1)).isoformat(), timezone="America/Los_Angeles"
        )
        first = self.waiting.mutate(command)
        self.assertEqual(first["revision"], 2)
        self.assertEqual(first["taskDeadlineState"], "overdue")
        self.assertEqual(first["priority"], "urgent")
        self.assertEqual(first["followUpState"], "scheduled")
        self.assertTrue(first["followUpDueToday"])
        self.assertFalse(first["followUpActionable"])
        self.assertEqual(first["dueAtUtc"], self.task.due_at_utc)
        self.assertEqual(self.uow.reminders(self.task.id)[0], reminder)
        before = len(self.audit.history("task", self.task.id))
        self.now += timedelta(days=2)
        self.assertEqual(self.waiting.mutate(command), first)
        self.assertEqual(self.waiting.operation(command.idempotency_key), first)
        self.assertEqual(len(self.audit.history("task", self.task.id)), before)
        with self.assertRaises(WaitingConflict):
            self.waiting.mutate(replace(command, label="Other"))
        with self.assertRaises(WaitingConflict) as caught:
            self.waiting.mutate(replace(command, idempotency_key=str(uuid4())))
        self.assertEqual(caught.exception.current_revision, 2)

    def test_semantic_noop_retains_receipt_without_new_change(self):
        first = self.waiting.mutate(self.command())
        before = len(self.audit.history("task", self.task.id))
        second = self.waiting.mutate(self.command())
        self.assertEqual(second["revision"], first["revision"])
        self.assertNotEqual(second["operationId"], first["operationId"])
        self.assertEqual(len(self.audit.history("task", self.task.id)), before)

    def test_reschedule_remove_clear_and_lifecycle_history(self):
        self.waiting.mutate(self.command())
        episode = self.tasks.get(self.task.id).waiting_set_at_utc
        self.now += timedelta(hours=1)
        dated = self.waiting.mutate(
            self.command(
                "reschedule",
                follow_up_at="2026-10-07T12:00:00-07:00",
                timezone="America/Los_Angeles",
            )
        )
        self.assertEqual(dated["followUpState"], "overdue")
        self.assertEqual(dated["waitingSetAtUtc"], episode)
        removed = self.waiting.mutate(self.command("reschedule", clear_follow_up=True))
        self.assertEqual(removed["followUpState"], "unscheduled")
        started = self.tasks.transition(self.task.id, "in_progress")
        self.assertEqual(started.revision, removed["revision"] + 1)
        self.assertEqual(started.waiting_set_at_utc, episode)
        reminder = self.tasks.add_reminder(self.task.id, self.now.isoformat())
        completed = self.tasks.transition(self.task.id, "completed")
        self.assertIsNone(completed.waiting_for_kind)
        self.assertEqual(completed.revision, started.revision + 1)
        self.assertEqual(completed.waiting_cleared_at_utc, self.now.isoformat())
        events = self.audit.history("task", self.task.id)
        clear = next(e for e in reversed(events) if e.action == "task_waiting_cleared")
        self.assertEqual(clear.reason, "task_completed")
        self.assertEqual(
            clear.correlation_id,
            self.audit.history("task_reminder", reminder.id)[-1].correlation_id,
        )
        reopened = self.tasks.transition(self.task.id, "open")
        self.assertIsNone(reopened.waiting_for_kind)
        self.assertEqual(self.uow.reminders(self.task.id)[0].status, "dismissed")
        self.waiting.mutate(self.command())
        cleared = self.waiting.mutate(self.command("clear"))
        self.assertFalse(cleared["isWaiting"])
        with self.uow.engine.connect() as connection:
            validate_task_schema(connection)

    def test_receipt_or_audit_failure_rolls_back(self):
        from app.modules.tasks.infrastructure.unit_of_work import _SQLiteTaskTransaction

        for target in ("insert_waiting_operation", "record_change"):
            with (
                self.subTest(target=target),
                patch.object(
                    _SQLiteTaskTransaction,
                    target,
                    side_effect=sqlite3.DatabaseError("write failed"),
                ),
            ):
                with self.assertRaises(WaitingStorageFailure) as caught:
                    self.waiting.mutate(self.command())
                self.assertIsInstance(caught.exception.__cause__, sqlite3.DatabaseError)
            self.assertEqual(self.tasks.get(self.task.id), self.task)
        with self.uow.engine.connect() as connection:
            self.assertEqual(
                connection.scalar(text("SELECT count(*) FROM task_waiting_operations")), 0
            )

    def test_invalid_direct_commands_and_terminal_state(self):
        for kwargs in (
            {"expected_revision": True},
            {"idempotency_key": "bad"},
            {"kind": "unknown"},
            {"label": " "},
            {"label": "x" * 256},
            {"follow_up_at": "2026-10-07", "timezone": "UTC"},
            {"follow_up_at": self.now.isoformat(), "timezone": "bad-zone"},
            {"follow_up_at": self.now.isoformat()},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(WaitingError):
                self.command(**kwargs)
        with self.assertRaises(WaitingConflict):
            self.waiting.mutate(self.command("reschedule", clear_follow_up=True))
        self.tasks.transition(self.task.id, "cancelled")
        with self.assertRaises(WaitingConflict):
            self.waiting.mutate(self.command())

    def test_time_boundaries_and_all_day_deadline(self):
        for delta, state, actionable in (
            (-1, "overdue", True),
            (0, "due", True),
            (1, "scheduled", False),
        ):
            result = self.waiting.mutate(
                self.command(
                    follow_up_at=(self.now + timedelta(seconds=delta)).isoformat(),
                    timezone="Asia/Tokyo",
                )
            )
            self.assertEqual(result["followUpState"], state)
            self.assertEqual(result["followUpActionable"], actionable)
        task = replace(
            self.tasks.get(self.task.id), due_at_utc="2026-10-07T07:00:00+00:00", is_all_day=True
        )
        self.assertEqual(waiting_facts(task, self.now)["taskDeadlineState"], "today")
        self.assertEqual(
            waiting_facts(task, self.now + timedelta(days=1))["taskDeadlineState"], "overdue"
        )

    def test_bounded_pages_ordering_counts_and_cursor_freshness(self):
        offsets = (-10, 0, 10, None, 86400)
        for index, offset in enumerate(offsets):
            task = self.tasks.create({"title": str(index)})
            self.waiting.mutate(
                WaitingCommand(
                    task.id,
                    "set",
                    1,
                    str(uuid4()),
                    "event",
                    "Reply",
                    (self.now + timedelta(seconds=offset)).isoformat()
                    if offset is not None
                    else None,
                    "UTC" if offset is not None else None,
                )
            )
        statements = []

        def count(_conn, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(self.uow.engine, "before_cursor_execute", count)
        self.addCleanup(event.remove, self.uow.engine, "before_cursor_execute", count)
        first = self.waiting.follow_ups(FollowUpQuery(limit=1))
        self.assertLessEqual(len(statements), 4)
        self.assertEqual(first["matchingTotal"], 5)
        seen, page = [], first
        while True:
            seen.extend(item["title"] for item in page["items"])
            self.assertEqual(page["matchingTotal"], 5)
            self.assertEqual(page["asOf"], first["asOf"])
            if page["nextCursor"] is None:
                break
            page = self.waiting.follow_ups(FollowUpQuery(limit=1, cursor=page["nextCursor"]))
        self.assertEqual(seen, ["0", "1", "2", "3", "4"])
        actionable = self.waiting.follow_ups(FollowUpQuery(actionable=True))
        self.assertEqual(actionable["matchingTotal"], 2)
        self.tasks.create({"title": "Changes marker"})
        with self.assertRaises(WaitingConflict):
            self.waiting.follow_ups(FollowUpQuery(limit=1, cursor=first["nextCursor"]))

    def test_expired_epoch_and_unavailable_before_database(self):
        for index in range(2):
            task = self.tasks.create({"title": str(index)})
            self.waiting.mutate(WaitingCommand(task.id, "set", 1, str(uuid4()), "other", "Event"))
        first = self.waiting.follow_ups(FollowUpQuery(limit=1))
        self.now += timedelta(minutes=16)
        with self.assertRaises(WaitingConflict):
            self.waiting.follow_ups(FollowUpQuery(cursor=first["nextCursor"]))
        self.now -= timedelta(minutes=16)
        self.identity = (self.identity[0], str(uuid4()))
        with self.assertRaises(WaitingConflict):
            self.waiting.follow_ups(FollowUpQuery(cursor=first["nextCursor"]))
        self.identity = ("", "")
        with (
            patch.object(self.uow, "read_follow_ups") as read,
            patch.object(self.uow, "write_waiting") as write,
        ):
            with self.assertRaises(WaitingUnavailable):
                self.waiting.follow_ups(FollowUpQuery())
            with self.assertRaises(WaitingUnavailable):
                self.waiting.mutate(self.command())
            read.assert_not_called()
            write.assert_not_called()

    def test_typed_routes_and_receipt_lookup(self):
        app = FastAPI()
        register_api_error_handlers(app)
        runtime = type("Runtime", (), {"ready": True, "error": None, "can_write": True})()
        app.include_router(build_router(self.tasks, runtime, self.waiting))
        payload = {
            "waitingForKind": "person",
            "waitingForLabel": "Owner",
            "expectedRevision": 1,
            "idempotencyKey": str(uuid4()),
        }
        with TestClient(app) as client:
            result = client.post(f"/api/tasks/{self.task.id}/waiting", json=payload)
            self.assertEqual(result.status_code, 200, result.text)
            replay = client.get(f"/api/tasks/waiting-operations/{payload['idempotencyKey']}")
            self.assertEqual(result.json(), replay.json())
            self.assertEqual(client.get("/api/tasks/follow-ups").status_code, 200)
            self.assertEqual(
                client.post(
                    f"/api/tasks/{self.task.id}/waiting", json={**payload, "extra": True}
                ).status_code,
                422,
            )
            self.assertEqual(
                client.post(
                    f"/api/tasks/{self.task.id}/waiting/clear",
                    json={
                        "expectedRevision": 2,
                        "idempotencyKey": str(uuid4()),
                        "confirmed": False,
                    },
                ).status_code,
                422,
            )
            stale = client.post(
                f"/api/tasks/{self.task.id}/waiting",
                json={**payload, "idempotencyKey": str(uuid4())},
            )
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(stale.json()["detail"]["currentRevision"], 2)
            schema = client.get("/openapi.json").json()
            oversized = client.post(
                f"/api/tasks/{self.task.id}/waiting", json={**payload, "waitingForLabel": "x" * 256}
            )
            self.assertEqual(oversized.status_code, 413)
            self.assertEqual(
                schema["paths"]["/api/tasks/follow-ups"]["get"]["operationId"], "getTaskFollowUps"
            )

    def waiting_api_client(self):
        app = FastAPI()
        register_api_error_handlers(app)
        runtime = type("Runtime", (), {"ready": True, "error": None, "can_write": True})()
        app.include_router(build_router(self.tasks, runtime, self.waiting))
        return TestClient(app)

    def waiting_payload(self, key=None):
        return {
            "waitingForKind": "person",
            "waitingForLabel": "Owner",
            "expectedRevision": self.task.revision,
            "idempotencyKey": key or str(uuid4()),
        }

    def assert_storage_response(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(set(response.json()), {"detail"})
        self.assertEqual(set(response.json()["detail"]), {"code", "message"})
        self.assertEqual(response.json()["detail"]["code"], code)
        self.assertNotIn("private-driver-detail", response.text)
        self.assertNotIn(str(self.workspace.paths.database), response.text)

    def short_database_timeout(self, dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA busy_timeout=10")

    def test_http_writer_contention_is_typed_503_and_retry_commits_once(self):
        self.uow.engine.dispose()
        event.listen(self.uow.engine, "connect", self.short_database_timeout)
        self.addCleanup(event.remove, self.uow.engine, "connect", self.short_database_timeout)
        payload = self.waiting_payload()
        with self.waiting_api_client() as client:
            with closing(sqlite3.connect(self.workspace.paths.database)) as blocker:
                blocker.execute("BEGIN IMMEDIATE")
                response = client.post(f"/api/tasks/{self.task.id}/waiting", json=payload)
                self.assert_storage_response(response, 503, "task_waiting_busy")
                blocker.rollback()
            self.assertEqual(self.tasks.get(self.task.id), self.task)
            self.assertEqual(len(self.audit.history("task", self.task.id)), 1)
            first = client.post(f"/api/tasks/{self.task.id}/waiting", json=payload)
            self.assertEqual(first.status_code, 200, first.text)
            retry = client.post(f"/api/tasks/{self.task.id}/waiting", json=payload)
            self.assertEqual(retry.json(), first.json())
            self.assertEqual(self.tasks.get(self.task.id).revision, 2)

    def test_http_follow_up_and_receipt_reads_translate_real_exclusive_lock(self):
        command = self.command()
        result = self.waiting.mutate(command)
        self.uow.engine.dispose()
        with closing(sqlite3.connect(self.workspace.paths.database)) as connection:
            connection.execute("PRAGMA journal_mode=DELETE")
        event.listen(self.uow.engine, "connect", self.short_database_timeout)
        self.addCleanup(event.remove, self.uow.engine, "connect", self.short_database_timeout)
        with self.waiting_api_client() as client:
            with closing(sqlite3.connect(self.workspace.paths.database)) as blocker:
                blocker.execute("BEGIN EXCLUSIVE")
                for path in (
                    "/api/tasks/follow-ups",
                    f"/api/tasks/waiting-operations/{command.idempotency_key}",
                ):
                    with self.subTest(path=path):
                        self.assert_storage_response(client.get(path), 503, "task_waiting_busy")
                blocker.rollback()
            self.assertEqual(client.get("/api/tasks/follow-ups").status_code, 200)
            receipt = client.get(f"/api/tasks/waiting-operations/{command.idempotency_key}")
            self.assertEqual(receipt.status_code, 200)
            self.assertEqual(str(receipt.json()["operationId"]), result["operationId"])

    def test_http_database_failures_are_sanitized_on_waiting_write_and_reads(self):
        from app.modules.tasks.infrastructure.unit_of_work import (
            _SQLiteTaskTransaction,
            _FollowUpReadTransaction,
        )

        command = self.command()
        self.waiting.mutate(command)
        failures = (
            (sqlite3.SQLITE_LOCKED, 503, "task_waiting_busy"),
            (sqlite3.SQLITE_BUSY | (2 << 8), 503, "task_waiting_busy"),
            (sqlite3.SQLITE_CORRUPT, 500, "task_waiting_storage_failure"),
            (None, 500, "task_waiting_storage_failure"),
        )
        with self.waiting_api_client() as client:
            for code, status, expected in failures:
                driver = sqlite3.OperationalError(
                    "private-driver-detail " + str(self.workspace.paths.database)
                )
                if code is not None:
                    driver.sqlite_errorcode = code
                errors = (driver, OperationalError("SELECT private-driver-detail", {}, driver))
                for error in errors:
                    paths = (
                        (
                            _SQLiteTaskTransaction,
                            "waiting_operation",
                            lambda: client.post(
                                f"/api/tasks/{self.task.id}/waiting",
                                json=self.waiting_payload(command.idempotency_key),
                            ),
                        ),
                        (
                            _SQLiteTaskTransaction,
                            "waiting_operation",
                            lambda: client.get(
                                f"/api/tasks/waiting-operations/{command.idempotency_key}"
                            ),
                        ),
                        (
                            _FollowUpReadTransaction,
                            "marker",
                            lambda: client.get("/api/tasks/follow-ups"),
                        ),
                    )
                    for adapter, method, call in paths:
                        with (
                            self.subTest(
                                code=code,
                                wrapped=isinstance(error, OperationalError),
                                method=method,
                            ),
                            patch.object(adapter, method, side_effect=error),
                        ):
                            self.assert_storage_response(call(), status, expected)

    def test_http_database_failure_after_task_write_rolls_back_and_keeps_key_reusable(self):
        payload = self.waiting_payload()

        def fail_receipt(_connection, _cursor, statement, *_args):
            if statement.startswith("INSERT INTO task_waiting_operations"):
                raise sqlite3.DatabaseError("private-driver-detail")

        with self.waiting_api_client() as client:
            event.listen(self.uow.engine, "before_cursor_execute", fail_receipt)
            try:
                response = client.post(f"/api/tasks/{self.task.id}/waiting", json=payload)
            finally:
                event.remove(self.uow.engine, "before_cursor_execute", fail_receipt)
            self.assert_storage_response(response, 500, "task_waiting_storage_failure")
            self.assertEqual(self.tasks.get(self.task.id), self.task)
            self.assertEqual(len(self.audit.history("task", self.task.id)), 1)
            with self.uow.engine.connect() as connection:
                self.assertEqual(
                    connection.scalar(text("SELECT count(*) FROM task_waiting_operations")), 0
                )
            retry = client.post(f"/api/tasks/{self.task.id}/waiting", json=payload)
            self.assertEqual(retry.status_code, 200, retry.text)

    def test_http_commit_failure_rolls_back_and_keeps_key_reusable(self):
        payload = self.waiting_payload()

        def fail_commit(_connection):
            raise sqlite3.DatabaseError("private-driver-detail")

        with self.waiting_api_client() as client:
            event.listen(self.uow.engine, "commit", fail_commit)
            try:
                response = client.post(f"/api/tasks/{self.task.id}/waiting", json=payload)
            finally:
                event.remove(self.uow.engine, "commit", fail_commit)
            self.assert_storage_response(response, 500, "task_waiting_storage_failure")
            self.assertEqual(self.tasks.get(self.task.id), self.task)
            self.assertEqual(len(self.audit.history("task", self.task.id)), 1)
            with self.uow.engine.connect() as connection:
                self.assertEqual(
                    connection.scalar(text("SELECT count(*) FROM task_waiting_operations")), 0
                )
            retry = client.post(f"/api/tasks/{self.task.id}/waiting", json=payload)
            self.assertEqual(retry.status_code, 200, retry.text)

    def test_waiting_boundary_does_not_hide_domain_or_programming_errors(self):
        conflict = WaitingConflict("domain conflict", 1)
        for method, operation in (
            (self.uow.write_waiting, lambda _tx: (_ for _ in ()).throw(conflict)),
            (self.uow.read_follow_ups, lambda _tx: (_ for _ in ()).throw(conflict)),
        ):
            with self.assertRaises(WaitingConflict) as caught:
                method(operation)
            self.assertIs(caught.exception, conflict)
        with self.assertRaisesRegex(RuntimeError, "programming failure"):
            self.uow.write_waiting(
                lambda _tx: (_ for _ in ()).throw(RuntimeError("programming failure"))
            )

    def test_http_follow_up_rejects_non_iso_or_offsetless_input_before_mutation(self):
        app = FastAPI()
        register_api_error_handlers(app)
        runtime = type("Runtime", (), {"ready": True, "error": None, "can_write": True})()
        app.include_router(build_router(self.tasks, runtime, self.waiting))
        self.waiting.mutate(self.command())
        revision = self.tasks.get(self.task.id).revision
        invalid_values = (
            1791399600,
            1791399600.5,
            1791399600000,
            "1791399600",
            "1791399600.5",
            "1791399600000",
            "2026-10-07T19:00:00",
            "2026-10-07",
            "not-a-timestamp",
            True,
        )
        with TestClient(app) as client, patch.object(self.waiting, "mutate") as mutate:
            for route in ("waiting", "waiting/follow-up"):
                for value in invalid_values:
                    with self.subTest(route=route, value=value):
                        payload = {
                            "expectedRevision": revision,
                            "idempotencyKey": str(uuid4()),
                            "followUpAt": value,
                            "followUpTimezone": "America/Los_Angeles",
                        }
                        if route == "waiting":
                            payload.update(waitingForKind="person", waitingForLabel="Owner")
                        response = client.post(f"/api/tasks/{self.task.id}/{route}", json=payload)
                        self.assertEqual(response.status_code, 422, response.text)
                        self.assertEqual(response.json()["detail"]["code"], "request_validation")
            mutate.assert_not_called()

    def test_http_follow_up_iso_input_normalizes_and_preserves_optional_dates(self):
        app = FastAPI()
        register_api_error_handlers(app)
        runtime = type("Runtime", (), {"ready": True, "error": None, "can_write": True})()
        app.include_router(build_router(self.tasks, runtime, self.waiting))
        with TestClient(app) as client:
            for route in ("waiting", "waiting/follow-up"):
                for value in ("2026-10-07T12:00:00-07:00", "2026-10-07T19:00:00Z"):
                    with self.subTest(route=route, value=value):
                        payload = {
                            "expectedRevision": self.tasks.get(self.task.id).revision,
                            "idempotencyKey": str(uuid4()),
                            "followUpAt": value,
                            "followUpTimezone": "America/Los_Angeles",
                        }
                        if route == "waiting":
                            payload.update(waitingForKind="person", waitingForLabel="Owner")
                        response = client.post(f"/api/tasks/{self.task.id}/{route}", json=payload)
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(
                            self.tasks.get(self.task.id).follow_up_at_utc,
                            "2026-10-07T19:00:00+00:00",
                        )
            for route in ("waiting", "waiting/follow-up"):
                payload = {
                    "expectedRevision": self.tasks.get(self.task.id).revision,
                    "idempotencyKey": str(uuid4()),
                    "followUpAt": None,
                    "followUpTimezone": None,
                }
                if route == "waiting":
                    payload.update(waitingForKind="person", waitingForLabel="Owner")
                else:
                    payload["clearFollowUp"] = True
                response = client.post(f"/api/tasks/{self.task.id}/{route}", json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIsNone(self.tasks.get(self.task.id).follow_up_at_utc)

    def test_parent_preview_bounds_counts_and_no_notes(self):
        parent = str(uuid4())
        for index in range(5):
            self.tasks.create(
                {
                    "title": str(index),
                    "notes": "private",
                    "relatedEntityType": "property",
                    "relatedEntityId": parent,
                }
            )
        reader = SQLiteTaskContextReader()
        with self.uow.engine.connect() as connection:
            results = reader.previews_for_related_entities(
                connection, "property", [parent], now=self.now, limit_per_parent=2
            )
            self.assertEqual(results[parent].total, 5)
            self.assertEqual(len(results[parent].items), 2)
            self.assertFalse(hasattr(results[parent].items[0], "notes"))
            with self.assertRaises(WaitingError):
                reader.previews_for_related_entities(
                    connection, "property", [str(uuid4()) for _ in range(101)], now=self.now
                )

    def test_concurrent_same_key_commits_once(self):
        command = self.command()
        barrier = Barrier(2)

        def submit():
            barrier.wait(timeout=5)
            return self.waiting.mutate(command)

        with ThreadPoolExecutor(max_workers=2) as pool:
            one, two = pool.submit(submit), pool.submit(submit)
            self.assertEqual(one.result(timeout=10), two.result(timeout=10))
        self.assertEqual(self.tasks.get(self.task.id).revision, 2)
        self.assertEqual(
            sum(
                event.action == "task_waiting_set"
                for event in self.audit.history("task", self.task.id)
            ),
            1,
        )

    def test_completion_racing_reschedule_cannot_retain_waiting(self):
        self.waiting.mutate(self.command())
        command = self.command("reschedule", follow_up_at=self.now.isoformat(), timezone="UTC")
        barrier = Barrier(2)

        def complete():
            barrier.wait(timeout=5)
            return self.tasks.transition(self.task.id, "completed")

        def reschedule():
            barrier.wait(timeout=5)
            try:
                return self.waiting.mutate(command)
            except WaitingConflict:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            one, two = pool.submit(complete), pool.submit(reschedule)
            one.result(timeout=10)
            two.result(timeout=10)
        task = self.tasks.get(self.task.id)
        self.assertEqual(task.status, "completed")
        self.assertIsNone(task.waiting_for_kind)
        with self.uow.engine.connect() as connection:
            validate_task_schema(connection)

    def test_schema_rejects_waiting_pairs_terminal_waiting_and_bad_timestamps(self):
        self.waiting.mutate(self.command())
        with sqlite3.connect(self.workspace.paths.database) as connection:
            for clause in (
                "revision=0",
                "waiting_for_label=NULL",
                "status='completed'",
                "follow_up_at_utc='2026-10-07T19:00:00+00:00'",
            ):
                with self.subTest(clause=clause), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(f"UPDATE tasks SET {clause} WHERE id=?", (self.task.id,))
            connection.execute(
                "UPDATE tasks SET waiting_set_at_utc='2026-10-07T19:00:00' WHERE id=?",
                (self.task.id,),
            )
        with self.uow.engine.connect() as connection, self.assertRaises(MigrationSchemaError):
            validate_task_schema(connection)

    def test_runtime_stop_failed_refresh_and_restart_guard_direct_callers(self):
        with TestClient(create_app(self.workspace.config.config_path)) as client:
            service = client.app.state.task_waiting_service
            service.clock = lambda: self.now
            runtime = client.app.state.workspace_runtime
            self.assertEqual(service.follow_ups(FollowUpQuery())["matchingTotal"], 0)
            with patch.object(
                runtime.service, "open", side_effect=WorkspaceError("validation failed")
            ):
                runtime.refresh()
            with patch.object(service.unit_of_work, "read_follow_ups") as read:
                with self.assertRaises(WaitingUnavailable):
                    service.follow_ups(FollowUpQuery())
                read.assert_not_called()
            runtime.refresh()
            self.assertTrue(runtime.ready)
            service.follow_ups(FollowUpQuery())
            runtime.stop()
            with self.assertRaises(WaitingUnavailable):
                service.mutate(self.command())
            runtime.start()
            result = service.mutate(self.command())
            self.assertTrue(result["isWaiting"])

    def test_waiting_stays_in_summary_obligation_and_reminder_buckets(self):
        self.tasks.add_reminder(self.task.id, self.now.isoformat())
        result = self.waiting.mutate(
            self.command(follow_up_at=(self.now + timedelta(days=7)).isoformat(), timezone="UTC")
        )
        summary = self.tasks.summary()
        self.assertEqual(summary["overdueTotal"], 1)
        self.assertEqual(summary["dueRemindersTotal"], 1)
        self.assertEqual(summary["overdue"][0]["revision"], result["revision"])
        self.assertTrue(summary["overdue"][0]["isWaiting"])
        self.assertEqual(summary["dueReminders"][0]["taskRevision"], result["revision"])
        self.assertEqual(summary["dueReminders"][0]["taskFollowUpState"], "scheduled")

    def test_populated_page_query_budget_and_plan(self):
        for index in range(101):
            task = self.tasks.create({"title": str(index)})
            self.waiting.mutate(WaitingCommand(task.id, "set", 1, str(uuid4()), "event", "Reply"))
        statements = []

        def capture(*args):
            if args[2].lstrip().upper().startswith("SELECT"):
                statements.append(args[2])

        event.listen(self.uow.engine, "before_cursor_execute", capture)
        try:
            small = self.waiting.follow_ups(FollowUpQuery(limit=1))
            small_count = len(statements)
            statements.clear()
            large = self.waiting.follow_ups(FollowUpQuery(limit=100))
            self.assertEqual(len(statements), small_count)
            self.assertLessEqual(small_count, 4)
            self.assertEqual(small["matchingTotal"], large["matchingTotal"])
            self.assertEqual(len(large["items"]), 100)
            self.assertIn("LIMIT", statements[-1].upper())
        finally:
            event.remove(self.uow.engine, "before_cursor_execute", capture)
        with self.uow.engine.connect() as connection:
            plan = connection.execute(
                text(
                    "EXPLAIN QUERY PLAN SELECT id FROM tasks WHERE status='open' AND waiting_for_kind='event' AND follow_up_at_utc IS NULL LIMIT 100"
                )
            ).all()
            self.assertIn("tasks_waiting_follow_up", " ".join(str(row) for row in plan))

    def test_follow_up_counts_and_page_use_one_snapshot(self):
        self.waiting.mutate(self.command())
        with sqlite3.connect(self.workspace.paths.database) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        selects = 0

        def change_after_count(*args):
            nonlocal selects
            if args[2].lstrip().upper().startswith("SELECT"):
                selects += 1
                if selects == 3:
                    self.waiting.mutate(self.command("clear"))

        event.listen(self.uow.engine, "before_cursor_execute", change_after_count)
        try:
            result = self.waiting.follow_ups(FollowUpQuery())
        finally:
            event.remove(self.uow.engine, "before_cursor_execute", change_after_count)
        self.assertEqual(result["matchingTotal"], 1)
        self.assertEqual(len(result["items"]), 1)
        self.assertTrue(result["items"][0]["isWaiting"])
        self.assertEqual(self.waiting.follow_ups(FollowUpQuery())["matchingTotal"], 0)

    def test_retained_tampering_and_append_only_receipts(self):
        self.waiting.mutate(self.command())
        with self.uow.engine.connect() as connection:
            validate_task_schema(connection)
        with sqlite3.connect(self.workspace.paths.database) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM task_waiting_operations")
            connection.execute(
                "UPDATE tasks SET waiting_for_label='Fabricated' WHERE id=?", (self.task.id,)
            )
        with self.uow.engine.connect() as connection, self.assertRaises(MigrationSchemaError):
            validate_task_schema(connection)

    @staticmethod
    def delete_receipt_with_valid_schema(database, operation_id):
        with closing(sqlite3.connect(database)) as connection, connection:
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='task_waiting_operations_no_delete'"
            ).fetchone()[0]
            connection.execute("DROP TRIGGER task_waiting_operations_no_delete")
            connection.execute("DELETE FROM task_waiting_operations WHERE id=?", (operation_id,))
            connection.execute(trigger)

    def assert_missing_receipt_rejected(self, *, noop):
        command = self.command()
        original = self.waiting.mutate(command)
        if noop:
            command = self.command()
            original = self.waiting.mutate(command)
        with self.uow.engine.connect() as connection:
            validate_task_schema(connection)
        self.delete_receipt_with_valid_schema(
            self.workspace.paths.database, original["operationId"]
        )
        with (
            self.uow.engine.connect() as connection,
            self.assertRaisesRegex(MigrationSchemaError, "Retained Task waiting data"),
        ):
            validate_task_schema(connection)
        with self.assertRaises(WorkspaceError):
            self.workspace.open(integrity_check=True)
        with self.assertRaises(WaitingNotFound):
            self.waiting.operation(command.idempotency_key)

    def test_missing_mutation_receipt_is_rejected_with_restored_triggers(self):
        self.assert_missing_receipt_rejected(noop=False)

    def test_missing_noop_receipt_is_rejected_with_restored_triggers(self):
        self.assert_missing_receipt_rejected(noop=True)

    def test_explicit_waiting_mutation_requires_receipt_even_without_operation_audit(self):
        result = self.waiting.mutate(self.command())
        self.delete_receipt_with_valid_schema(self.workspace.paths.database, result["operationId"])
        # Leave the task mutation as the surviving evidence, with exact audit schema restored.
        with sqlite3.connect(self.workspace.paths.database) as connection:
            triggers = connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_events'"
            ).fetchall()
            for name, _sql in triggers:
                connection.execute(f'DROP TRIGGER "{name}"')
            connection.execute(
                "DELETE FROM audit_events WHERE entity_type='task_waiting_operation' AND entity_id=?",
                (result["operationId"],),
            )
            for _name, sql in triggers:
                connection.execute(sql)
        with self.uow.engine.connect() as connection, self.assertRaises(MigrationSchemaError):
            validate_task_schema(connection)

    def test_encrypted_restore_rejects_missing_mutation_and_noop_receipts(self):
        command = self.command()
        changed = self.waiting.mutate(command)
        noop_command = self.command()
        noop = self.waiting.mutate(noop_command)
        backups = BackupService(
            self.workspace,
            self.recorder,
            lambda database: AuditRecorder(SQLiteAuditRepository(database)),
            MemorySecrets(),
        )
        passphrase = "a long encrypted task passphrase"
        archive = backups.create_backup(passphrase)
        for label, result in (("mutation", changed), ("noop", noop)):
            with (
                self.subTest(label=label),
                tempfile.TemporaryDirectory(dir=self.temp.name) as temporary,
            ):
                root = Path(temporary)
                payload = root / "payload.zip"
                decrypt_archive_to_zip(archive.archive_path, passphrase, payload)
                with zipfile.ZipFile(payload) as package:
                    files = {
                        info.filename: package.read(info.filename)
                        for info in package.infolist()
                        if not info.is_dir()
                    }
                database_name = "workspace/database/property-management.sqlite"
                database = root / "tampered.sqlite"
                database.write_bytes(files[database_name])
                self.delete_receipt_with_valid_schema(database, result["operationId"])
                files[database_name] = database.read_bytes()
                manifest = json.loads(files["backup-manifest.json"])
                for item in manifest["files"]:
                    if item["path"] == database_name:
                        item["bytes"] = len(files[database_name])
                        item["sha256"] = hashlib.sha256(files[database_name]).hexdigest()
                files["backup-manifest.json"] = (
                    json.dumps(manifest, sort_keys=True) + "\n"
                ).encode()
                with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as package:
                    for name, content in files.items():
                        package.writestr(name, content)
                corrupted = root / "missing-receipt.epm-backup"
                write_encrypted_archive(
                    payload,
                    corrupted,
                    make_header(workspace_id=self.identity[0], package_type="backup"),
                    passphrase,
                )
                with self.assertRaisesRegex(BackupError, "Retained Task waiting data"):
                    backups.validate_archive(corrupted, passphrase)
                destination = root / "restored"
                with self.assertRaisesRegex(BackupError, "Retained Task waiting data"):
                    backups.restore(corrupted, passphrase, destination)
                self.assertFalse(destination.exists())
                self.assertEqual(self.waiting.operation(command.idempotency_key), changed)
                self.assertEqual(self.waiting.operation(noop_command.idempotency_key), noop)

    def test_encrypted_backup_restore_preserves_waiting_receipts_and_history(self):
        command = self.command(follow_up_at=self.now.isoformat(), timezone="UTC")
        original = self.waiting.mutate(command)
        tables = ("tasks", "task_waiting_operations", "audit_events")
        with sqlite3.connect(self.workspace.paths.database) as connection:
            before = {
                table: connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                for table in tables
            }
        backups = BackupService(
            self.workspace,
            self.recorder,
            lambda database: AuditRecorder(SQLiteAuditRepository(database)),
            MemorySecrets(),
        )
        archive = backups.create_backup("a long encrypted task passphrase")
        restored = Path(self.temp.name) / "restored"
        backups.restore(archive.archive_path, "a long encrypted task passphrase", restored)
        database = WorkspacePaths(restored).database
        with sqlite3.connect(database) as connection:
            after = {
                table: connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                for table in tables
            }
        for table in ("tasks", "task_waiting_operations"):
            self.assertEqual(before[table], after[table])
        self.assertTrue(all(row in after["audit_events"] for row in before["audit_events"]))
        restored_uow = SQLiteTaskUnitOfWork(
            database, AuditRecorder(SQLiteAuditRepository(database))
        )
        replay = TaskWaitingService(
            restored_uow, read_identity=lambda: (self.identity[0], str(uuid4()))
        )
        self.assertEqual(replay.operation(command.idempotency_key), original)
        with restored_uow.engine.connect() as connection:
            validate_task_schema(connection)

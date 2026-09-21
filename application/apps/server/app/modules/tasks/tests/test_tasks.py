from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.tasks.application.service import TaskError, TaskService
from app.modules.tasks.api.router import build_router
from app.modules.tasks.domain.models import Task, TaskReminder, dismiss
from app.modules.tasks.infrastructure.transaction_operations import SQLiteTaskTransactionOperations
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig


class TaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); service = WorkspaceService(LocalConfig(root / "config.json", root / "workspace")); service.initialize()
        self.audit = SQLiteAuditRepository(service.paths.database); self.tasks = TaskService(SQLiteTaskUnitOfWork(service.paths.database, AuditRecorder(self.audit)))

    def test_transitions_reminders_and_time_normalization(self) -> None:
        task = self.tasks.create({"title": "Deposit check", "dueAtUtc": "2999-01-01T00:05:00-05:00", "dueTimezone": "America/New_York", "priority": "high"})
        self.assertTrue(task.due_at_utc.endswith("+00:00")); self.assertEqual(self.tasks.summary()["overdue"], [])
        reminder = self.tasks.add_reminder(task.id, "2999-01-01T00:00:00-05:00")
        self.assertEqual(self.tasks.set_reminder_status(task.id, reminder.id, "acknowledged").status, "acknowledged")
        self.assertEqual(self.tasks.transition(task.id, "completed", "Deposited").status, "completed")
        self.assertEqual(self.audit.history("task", task.id)[-1].action, "status_changed")

    def test_audit_failure_rolls_back_task_write(self) -> None:
        with patch.object(self.tasks.unit_of_work.recorder, "record_change", side_effect=sqlite3.DatabaseError("audit unavailable")):
            with self.assertRaises(sqlite3.DatabaseError): self.tasks.create({"title": "Must not persist"})
        self.assertEqual(self.tasks.list(), [])

    def test_terminal_tasks_dismiss_reminders_and_reject_new_ones(self) -> None:
        task = self.tasks.create({"title": "Follow up"}); reminder = self.tasks.add_reminder(task.id, "2999-01-01T00:00:00+00:00")
        self.tasks.transition(task.id, "cancelled", "No longer needed")
        self.assertEqual(self.tasks.summary()["dueReminders"], [])
        with self.assertRaises(TaskError): self.tasks.add_reminder(task.id, reminder.remind_at_utc)

    def test_terminal_task_and_automatic_reminder_events_share_a_correlation_id(self) -> None:
        task = self.tasks.create({"title": "Follow up"})
        reminder = self.tasks.add_reminder(task.id, "2999-01-01T00:00:00+00:00")
        self.tasks.transition(task.id, "completed", "Done")
        task_event = self.audit.history("task", task.id)[-1]
        reminder_event = self.audit.history("task_reminder", reminder.id)[-1]
        self.assertEqual(task_event.correlation_id, reminder_event.correlation_id)

    def test_direct_callers_cannot_bypass_task_input_or_lifecycle_rules(self) -> None:
        for payload in (
            {"title": None},
            {"title": "x", "isAllDay": "false"},
            {"title": "x", "relatedEntityType": "lease"},
            {"title": "x", "relatedEntityType": "", "relatedEntityId": ""},
            {"title": "x", "relatedLabel": "Lease A"},
            {"title": "x", "dueTimezone": "UTC"},
            {"title": "x", "isAllDay": True},
            {"title": "x", "dueAtUtc": "2999-01-01T00:00:00+00:00"},
        ):
            with self.assertRaises(TaskError): self.tasks.create(payload)
        task = self.tasks.create({"title": "Rule check"})
        with self.assertRaises(TaskError): self.tasks.transition(task.id, "open")
        with self.assertRaises(TaskError): self.tasks.list("unknown")

    def test_related_record_page_is_bounded_and_cursor_paginated(self) -> None:
        concern_id = "00000000-0000-4000-8000-000000000901"
        other_id = "00000000-0000-4000-8000-000000000902"
        for number in range(25):
            self.tasks.create({
                "title": f"Concern follow-up {number}",
                "relatedEntityType": "owner_concern",
                "relatedEntityId": concern_id,
            })
        self.tasks.create({
            "title": "Other follow-up",
            "relatedEntityType": "owner_concern",
            "relatedEntityId": other_id,
        })
        first, cursor = self.tasks.page(
            related_entity_type="owner_concern", related_entity_id=concern_id, page_size=10,
        )
        second, cursor = self.tasks.page(
            related_entity_type="owner_concern", related_entity_id=concern_id, page_size=10, cursor=cursor,
        )
        third, final = self.tasks.page(
            related_entity_type="owner_concern", related_entity_id=concern_id, page_size=10, cursor=cursor,
        )
        self.assertIsNone(final)
        self.assertEqual(len(first), 10)
        self.assertEqual(len(second), 10)
        self.assertEqual(len(third), 5)
        self.assertEqual({task.id for task in first + second + third}, {task.id for task in self.tasks.list() if task.related_entity_id == concern_id})
        with self.assertRaises(TaskError):
            self.tasks.page(related_entity_type="owner_concern")

    def test_task_route_filters_related_record_and_returns_a_page(self) -> None:
        concern_id = "00000000-0000-4000-8000-000000000911"
        for number in range(3):
            self.tasks.create({
                "title": f"Concern task {number}",
                "relatedEntityType": "owner_concern",
                "relatedEntityId": concern_id,
            })
        app = FastAPI()
        app.include_router(build_router(self.tasks, type("Runtime", (), {"ready": True, "error": None, "can_write": True})()))
        with TestClient(app) as client:
            response = client.get("/api/tasks", params={
                "relatedEntityType": "owner_concern", "relatedEntityId": concern_id, "pageSize": 2,
            })
            incomplete = client.get("/api/tasks", params={"relatedEntityType": "owner_concern"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 2)
        self.assertIsNotNone(response.json()["nextCursor"])
        self.assertEqual(incomplete.status_code, 422)

    def test_task_route_defaults_to_active_and_applies_combined_history_filters(self) -> None:
        concern_id = "00000000-0000-4000-8000-000000000912"
        now = datetime.now(UTC).replace(microsecond=0)
        due = datetime.combine(now.date(), time(12), tzinfo=UTC).isoformat()
        high = self.tasks.create({
            "title": "High concern follow-up", "priority": "high", "dueAtUtc": due,
            "dueTimezone": "UTC", "relatedEntityType": "owner_concern", "relatedEntityId": concern_id,
        })
        no_due = self.tasks.create({
            "title": "Undated concern follow-up", "relatedEntityType": "owner_concern", "relatedEntityId": concern_id,
        })
        completed = self.tasks.create({
            "title": "Completed concern follow-up", "relatedEntityType": "owner_concern", "relatedEntityId": concern_id,
        })
        self.tasks.transition(completed.id, "completed", "Done")
        day = now.date().isoformat()
        app = FastAPI()
        app.include_router(build_router(self.tasks, type("Runtime", (), {"ready": True, "error": None, "can_write": True})()))
        with TestClient(app) as client:
            default = client.get("/api/tasks", params={
                "relatedEntityType": "owner_concern", "relatedEntityId": concern_id,
            })
            combined = client.get("/api/tasks", params={
                "relatedEntityType": "owner_concern", "relatedEntityId": concern_id,
                "status": "open,in_progress", "priority": "high", "due": f"{day},{day}",
            })
            terminal = client.get("/api/tasks", params={
                "relatedEntityType": "owner_concern", "relatedEntityId": concern_id,
                "status": "completed", "includeVoided": "true",
            })
            no_date = client.get("/api/tasks", params={
                "relatedEntityType": "owner_concern", "relatedEntityId": concern_id, "due": "nodate",
            })
        self.assertEqual(default.status_code, 200)
        self.assertEqual({item["id"] for item in default.json()["items"]}, {high.id, no_due.id})
        self.assertEqual([item["id"] for item in combined.json()["items"]], [high.id])
        self.assertEqual([item["id"] for item in terminal.json()["items"]], [completed.id])
        self.assertEqual([item["id"] for item in no_date.json()["items"]], [no_due.id])

    def test_due_filters_capture_one_clock_instant_and_bound_empty_scans(self) -> None:
        class PagedTasks:
            def __init__(self, tasks):
                self.tasks = tasks
                self.calls = 0

            def page(self, *, limit, cursor, **_):
                self.calls += 1
                start = 0 if cursor is None else next(
                    index + 1 for index, task in enumerate(self.tasks) if task.id == cursor[3]
                )
                return self.tasks[start:start + limit]

        def task(number: int, due: str) -> Task:
            return Task(
                f"task-{number:04d}", f"Task {number}", None, "open", "normal", due,
                "America/Los_Angeles", False, None, None, None, None, None, None,
                "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
            )

        clock_calls = 0
        def fixed_clock():
            nonlocal clock_calls
            clock_calls += 1
            return datetime(2026, 1, 15, 1, 30, tzinfo=UTC)

        candidates = PagedTasks([task(number, "2026-01-20T20:00:00+00:00") for number in range(1_001)])
        service = TaskService(candidates, now=fixed_clock)
        items, cursor = service.page(due="nodate", page_size=10)
        self.assertEqual(items, [])
        self.assertIsNotNone(cursor)
        self.assertEqual(candidates.calls, 10)
        self.assertEqual(clock_calls, 1)

        local_today, _ = TaskService(PagedTasks([
            task(2_001, "2026-01-14T20:00:00+00:00"),
            task(2_002, "2026-01-15T20:00:00+00:00"),
        ]), now=fixed_clock).page(due="today")
        self.assertEqual([item.id for item in local_today], ["task-2001"])

    def test_due_filter_cursor_continues_through_empty_and_partial_pages(self) -> None:
        class PagedTasks:
            def __init__(self, tasks):
                self.tasks = tasks

            def page(self, *, limit, cursor, **_):
                start = 0 if cursor is None else next(
                    index + 1 for index, task in enumerate(self.tasks) if task.id == cursor[3]
                )
                return self.tasks[start:start + limit]

        def task(number: int, due: str | None) -> Task:
            return Task(
                f"task-{number:04d}", f"Task {number}", None, "open", "normal", due,
                "America/Los_Angeles" if due else None, False, None, None, None, None, None, None,
                "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
            )

        future_due = "2026-01-20T20:00:00+00:00"
        candidates = [task(number, future_due) for number in range(1, 1_001)]
        expected_ids = []
        for number in range(1_001, 1_006):
            candidates.append(task(number, None))
            expected_ids.append(f"task-{number:04d}")
        candidates.extend(task(number, future_due) for number in range(1_006, 2_001))
        for number in range(2_001, 2_016):
            candidates.append(task(number, None))
            expected_ids.append(f"task-{number:04d}")

        service = TaskService(
            PagedTasks(candidates), now=lambda: datetime(2026, 1, 15, 1, 30, tzinfo=UTC),
        )
        cursor = None
        pages: list[list[str]] = []
        while True:
            page, cursor = service.page(due="nodate", page_size=10, cursor=cursor)
            pages.append([item.id for item in page])
            if cursor is None:
                break

        self.assertEqual(pages[0], [])
        self.assertEqual(len(pages[1]), 5)
        self.assertEqual(len(pages[2]), 10)
        self.assertEqual(len(pages[3]), 5)
        returned_ids = [task_id for page in pages for task_id in page]
        self.assertEqual(returned_ids, expected_ids)
        self.assertEqual(len(returned_ids), len(set(returned_ids)))

    def test_transaction_operations_keep_prepaid_reminder_persistence_statement_counts(self) -> None:
        operations = SQLiteTaskTransactionOperations()
        task = Task(
            "task-1", "Deposit prepaid check", None, "open", "normal",
            "2026-01-01T08:00:00+00:00", "UTC", True, None, None, None,
            "prepaid_check", "check-1", "Prepaid check", "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
        )
        reminders = [
            TaskReminder(f"reminder-{number}", task.id, task.due_at_utc, "pending", None, None, task.created_at_utc)
            for number in (1, 2)
        ]
        statements = []
        engine = self.tasks.unit_of_work.engine
        def capture_statement(*args):
            statements.append(args[2])
        event.listen(engine, "before_cursor_execute", capture_statement)
        try:
            with engine.begin() as connection:
                operations.insert_task(connection, task)
                for reminder in reminders:
                    operations.insert_reminder(connection, reminder)
                pending = operations.pending_reminders(connection, task.id)
                for reminder in pending:
                    operations.replace_reminder(connection, dismiss(reminder, "2026-01-01T01:00:00+00:00"))
                self.assertEqual(operations.latest_reminder_status(connection, task.id), "dismissed")
        finally:
            event.remove(engine, "before_cursor_execute", capture_statement)
        self.assertEqual(sum(statement.lstrip().upper().startswith("INSERT INTO TASKS") for statement in statements), 1)
        self.assertEqual(sum(statement.lstrip().upper().startswith("INSERT INTO TASK_REMINDERS") for statement in statements), 2)
        self.assertEqual(sum(statement.lstrip().upper().startswith("UPDATE TASK_REMINDERS") for statement in statements), 2)
        self.assertEqual(sum(statement.lstrip().upper().startswith("SELECT") for statement in statements), 2)

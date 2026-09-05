from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.tasks.application.service import TaskError, TaskService
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

"""TASK-001 operations available to Finance inside its existing transaction."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.modules.tasks.domain.models import Task, TaskReminder
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel, TaskReminderModel


class SQLiteTaskFinanceOperations:
    """Persistence adapter; Finance keeps the prepaid-check workflow policy."""

    def create_prepaid_check_reminder(self, connection, *, check_id: str, due_at_utc: str,
                                      due_timezone: str, correlation_id: str, record_change):
        now = datetime.now(UTC).isoformat()
        task = Task(
            str(uuid4()), "Deposit prepaid check", None, "open", "normal",
            due_at_utc, due_timezone, True, None, None, None,
            "prepaid_check", check_id, "Prepaid check", now, now,
        )
        reminder = TaskReminder(str(uuid4()), task.id, due_at_utc, "pending", None, None, now)
        connection.execute(TaskModel.__table__.insert().values(**{**task.__dict__, "is_all_day": 1}))
        connection.execute(TaskReminderModel.__table__.insert().values(**reminder.__dict__))
        record_change(entity_type="task", entity_id=task.id, action="created", before=None,
                      after=task.to_dict(), reason="prepaid_check_reminder_created", correlation_id=correlation_id)
        record_change(entity_type="task_reminder", entity_id=reminder.id, action="created", before=None,
                      after=reminder.to_dict(), reason="prepaid_check_reminder_created", correlation_id=correlation_id)
        return task.id

    def dismiss_prepaid_check_reminder(self, connection, task_id: str | None, *, correlation_id: str, record_change) -> None:
        if task_id is None:
            return
        rows = connection.execute(TaskReminderModel.__table__.select().where(
            TaskReminderModel.task_id == task_id, TaskReminderModel.status == "pending"
        )).mappings().all()
        now = datetime.now(UTC).isoformat()
        for row in rows:
            before = TaskReminder(**dict(row))
            after = TaskReminder(before.id, before.task_id, before.remind_at_utc, "dismissed", None, now, before.created_at_utc)
            connection.execute(TaskReminderModel.__table__.update().where(TaskReminderModel.id == after.id).values(**after.__dict__))
            record_change(entity_type="task_reminder", entity_id=after.id, action="dismissed",
                          before=before.to_dict(), after=after.to_dict(),
                          reason="prepaid_check_lifecycle_changed", correlation_id=correlation_id)

    def prepaid_check_reminder_status(self, connection, task_id: str | None) -> str | None:
        if task_id is None:
            return None
        row = connection.execute(
            TaskReminderModel.__table__.select()
            .where(TaskReminderModel.task_id == task_id)
            .order_by(TaskReminderModel.created_at_utc.desc(), TaskReminderModel.id.desc())
            .limit(1)
        ).mappings().first()
        return None if row is None else str(row["status"])

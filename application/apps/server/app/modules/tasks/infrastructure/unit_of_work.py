"""SQLite implementation of the task unit of work."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.tasks.application.ports import TaskTransaction
from app.modules.tasks.domain.models import Task, TaskReminder
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel, TaskReminderModel
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

Result = TypeVar("Result")


class SQLiteTaskUnitOfWork:
    """Keeps SQLite concerns behind a transaction boundary for TaskService."""

    def __init__(self, database, recorder: AuditRecorder) -> None:
        self.engine = create_sqlite_engine(database)
        self.recorder = recorder

    def write(self, operation: Callable[[TaskTransaction], Result]) -> Result:
        with immediate_transaction(self.engine) as connection:
            return operation(_SQLiteTaskTransaction(connection, self.recorder))

    def get(self, task_id: str) -> Task | None:
        with Session(self.engine) as session:
            row = session.get(TaskModel, task_id)
            return _task(row) if row else None

    def list(self, status: str | None = None) -> list[Task]:
        with Session(self.engine) as session:
            query = select(TaskModel).order_by(
                TaskModel.due_at_utc.is_(None), TaskModel.due_at_utc, TaskModel.created_at_utc
            )
            if status:
                query = query.where(TaskModel.status == status)
            return [_task(row) for row in session.execute(query).scalars()]

    def reminders(self, task_id: str | None = None) -> list[TaskReminder]:
        with Session(self.engine) as session:
            query = select(TaskReminderModel).order_by(TaskReminderModel.remind_at_utc)
            if task_id:
                query = query.where(TaskReminderModel.task_id == task_id)
            return [_reminder(row) for row in session.execute(query).scalars()]


class _SQLiteTaskTransaction:
    def __init__(self, connection: Any, recorder: AuditRecorder) -> None:
        self.connection = connection
        self.recorder = recorder

    def get_task(self, task_id: str) -> Task | None:
        row = self.connection.execute(
            TaskModel.__table__.select().where(TaskModel.id == task_id)
        ).mappings().first()
        return _task_mapping(row) if row else None

    def insert_task(self, task: Task) -> None:
        self.connection.execute(TaskModel.__table__.insert().values(**_task_values(task)))

    def replace_task(self, task: Task) -> None:
        self.connection.execute(
            TaskModel.__table__.update().where(TaskModel.id == task.id).values(**_task_values(task))
        )

    def pending_reminders(self, task_id: str) -> list[TaskReminder]:
        rows = self.connection.execute(
            TaskReminderModel.__table__.select().where(
                TaskReminderModel.task_id == task_id, TaskReminderModel.status == "pending"
            )
        ).mappings().all()
        return [TaskReminder(**dict(row)) for row in rows]

    def insert_reminder(self, reminder: TaskReminder) -> None:
        self.connection.execute(TaskReminderModel.__table__.insert().values(**reminder.__dict__))

    def get_reminder(self, task_id: str, reminder_id: str) -> TaskReminder | None:
        row = self.connection.execute(
            TaskReminderModel.__table__.select().where(
                TaskReminderModel.id == reminder_id, TaskReminderModel.task_id == task_id
            )
        ).mappings().first()
        return TaskReminder(**dict(row)) if row else None

    def replace_reminder(self, reminder: TaskReminder) -> None:
        self.connection.execute(
            TaskReminderModel.__table__.update().where(TaskReminderModel.id == reminder.id).values(**reminder.__dict__)
        )

    def record_change(self, *, entity_type: str, entity_id: str, action: str,
                      before: dict[str, Any] | None, after: dict[str, Any] | None,
                      reason: str, correlation_id: str) -> None:
        self.recorder.record_change(
            self.connection.connection.driver_connection,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before=before,
            after=after,
            reason=reason,
            correlation_id=correlation_id,
        )


def _task(row: TaskModel) -> Task:
    values = {column: getattr(row, column) for column in Task.__dataclass_fields__}
    values["is_all_day"] = bool(values["is_all_day"])
    return Task(**values)


def _task_mapping(row: Any) -> Task:
    values = dict(row)
    values["is_all_day"] = bool(values["is_all_day"])
    return Task(**values)


def _reminder(row: TaskReminderModel) -> TaskReminder:
    return TaskReminder(**{column: getattr(row, column) for column in TaskReminder.__dataclass_fields__})


def _task_values(task: Task) -> dict[str, Any]:
    return {**task.__dict__, "is_all_day": int(task.is_all_day)}

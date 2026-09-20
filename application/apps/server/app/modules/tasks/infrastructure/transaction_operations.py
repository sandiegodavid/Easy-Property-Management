"""Generic SQLite task persistence for caller-owned transactions."""

from typing import Any

from app.modules.tasks.domain.models import Task, TaskReminder
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel, TaskReminderModel


class SQLiteTaskTransactionOperations:
    def insert_task(self, connection: Any, task: Task) -> None:
        connection.execute(TaskModel.__table__.insert().values(**_task_values(task)))

    def insert_reminder(self, connection: Any, reminder: TaskReminder) -> None:
        connection.execute(TaskReminderModel.__table__.insert().values(**reminder.__dict__))

    def pending_reminders(self, connection: Any, task_id: str) -> list[TaskReminder]:
        rows = connection.execute(
            TaskReminderModel.__table__.select().where(
                TaskReminderModel.task_id == task_id,
                TaskReminderModel.status == "pending",
            )
        ).mappings()
        return [TaskReminder(**dict(row)) for row in rows]

    def replace_reminder(self, connection: Any, reminder: TaskReminder) -> None:
        connection.execute(
            TaskReminderModel.__table__.update()
            .where(TaskReminderModel.id == reminder.id)
            .values(**reminder.__dict__)
        )

    def latest_reminder_status(self, connection: Any, task_id: str) -> str | None:
        return connection.execute(
            TaskReminderModel.__table__.select()
            .with_only_columns(TaskReminderModel.status)
            .where(TaskReminderModel.task_id == task_id)
            .order_by(TaskReminderModel.created_at_utc.desc(), TaskReminderModel.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def create_task(self, connection: Any, command: Any, *, correlation_id: str,
                    record_change: Any) -> Task:
        """Apply TASK-001's command validation and creation policy in a caller transaction."""
        from app.modules.tasks.application.service import TaskCreateCommand, new_task

        validated = command if isinstance(command, TaskCreateCommand) else TaskCreateCommand.from_mapping(command)
        task = new_task(validated)
        self.insert_task(connection, task)
        record_change(
            entity_type="task", entity_id=task.id, action="created", before=None,
            after=task.to_dict(), reason="task_created", correlation_id=correlation_id,
        )
        return task


def _task_values(task: Task) -> dict[str, Any]:
    return {**task.__dict__, "is_all_day": int(task.is_all_day)}

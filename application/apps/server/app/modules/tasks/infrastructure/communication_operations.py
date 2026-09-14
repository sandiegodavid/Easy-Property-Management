"""TASK-001 transaction operation used by COM-001 composition."""

from __future__ import annotations

from app.modules.tasks.application.service import TaskCreateCommand, new_task
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel


class SQLiteTaskCommunicationOperations:
    """Creates a COM follow-up with TASK-001 command validation and normalization."""

    def create_follow_up(self, connection, *, communication_id: str, label: str, title: str,
                         notes: str | None, due_at_utc: str | None, due_timezone: str | None) -> dict[str, object]:
        command = TaskCreateCommand(
            title=title, notes=notes, status="open", priority="normal",
            due_at_utc=due_at_utc, due_timezone=due_timezone, is_all_day=False,
            related_entity_type="communication", related_entity_id=communication_id, related_label=label,
        )
        task = new_task(command)
        connection.execute(TaskModel.__table__.insert().values(**{**task.__dict__, "is_all_day": 0}))
        return task.to_dict()

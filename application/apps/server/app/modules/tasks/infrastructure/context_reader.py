"""Consumer-neutral TASK-001 summaries for caller-owned transactions."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select

from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel


class SQLiteTaskContextReader:
    def task(self, connection: Any, task_id: str) -> dict[str, Any] | None:
        row = connection.execute(
            TaskModel.__table__.select().where(TaskModel.id == task_id)
        ).mappings().first()
        return None if row is None else _summary(row)

    def tasks_for_related_entities(self, connection: Any, entity_type: str,
                                   entity_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not entity_ids:
            return {}
        rows = connection.execute(
            select(
                TaskModel.id, TaskModel.title, TaskModel.status, TaskModel.priority,
                TaskModel.due_at_utc, TaskModel.due_timezone, TaskModel.is_all_day,
                TaskModel.related_entity_type, TaskModel.related_entity_id,
            ).where(
                TaskModel.related_entity_type == entity_type,
                TaskModel.related_entity_id.in_(set(entity_ids)),
            ).order_by(TaskModel.created_at_utc.desc(), TaskModel.id.desc())
        ).mappings()
        result: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            result[row["related_entity_id"]].append(_summary(row))
        return dict(result)

    def related_entity_ids_with_active_tasks(self, connection: Any, entity_type: str) -> set[str]:
        return set(connection.execute(
            TaskModel.__table__.select().with_only_columns(TaskModel.related_entity_id).where(
                TaskModel.related_entity_type == entity_type,
                TaskModel.status.in_(("open", "in_progress")),
            )
        ).scalars())

    def active_related_entity_ids(self, connection: Any, entity_type: str, entity_ids: list[str]) -> set[str]:
        if not entity_ids:
            return set()
        return set(connection.execute(
            TaskModel.__table__.select().with_only_columns(TaskModel.related_entity_id).where(
                TaskModel.related_entity_type == entity_type,
                TaskModel.related_entity_id.in_(set(entity_ids)),
                TaskModel.status.in_(("open", "in_progress")),
            )
        ).scalars())


def _summary(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"], "title": row["title"], "status": row["status"],
        "priority": row["priority"], "due_at_utc": row["due_at_utc"],
        "due_timezone": row["due_timezone"], "is_all_day": bool(row["is_all_day"]),
        "related_entity_type": row["related_entity_type"],
        "related_entity_id": row["related_entity_id"],
    }

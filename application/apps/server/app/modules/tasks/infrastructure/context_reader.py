"""Consumer-neutral TASK-001 summaries for caller-owned transactions."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select

from app.modules.tasks.application.ports import TaskParentPreview, TaskPreview
from app.modules.tasks.application.waiting import WaitingError
from app.modules.tasks.domain.models import Task, waiting_facts

from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel


class SQLiteTaskContextReader:
    def previews_for_related_entities(
        self, connection, entity_type, entity_ids, *, now, limit_per_parent=10
    ):
        ids = set(entity_ids)
        if len(ids) > 100 or type(limit_per_parent) is not int or not 1 <= limit_per_parent <= 50:
            raise WaitingError("Task previews allow 100 parents and 1–50 items per parent.")
        if now.tzinfo is None or now.utcoffset() is None:
            raise WaitingError("Task previews require an aware captured instant.")
        if not ids:
            return {}
        columns = [c for c in TaskModel.__table__.columns if c.name != "notes"]
        ranked = (
            select(
                *columns,
                func.row_number()
                .over(
                    partition_by=TaskModel.related_entity_id,
                    order_by=(TaskModel.created_at_utc.desc(), TaskModel.id),
                )
                .label("position"),
                func.count().over(partition_by=TaskModel.related_entity_id).label("total"),
            )
            .where(
                TaskModel.related_entity_type == entity_type,
                TaskModel.related_entity_id.in_(ids),
                TaskModel.deleted_at_utc.is_(None),
            )
            .subquery()
        )
        rows = connection.execute(
            select(ranked)
            .where(ranked.c.position <= limit_per_parent)
            .order_by(ranked.c.related_entity_id, ranked.c.position)
        ).mappings()
        result = {key: TaskParentPreview(0, []) for key in ids}
        for row in rows:
            values = {key: row[key] for key in Task.__dataclass_fields__ if key != "notes"}
            task = Task(**values, notes=None)
            facts = waiting_facts(task, now)
            preview = TaskPreview(
                **{
                    key: values[key]
                    for key in (
                        "id",
                        "title",
                        "status",
                        "priority",
                        "revision",
                        "due_at_utc",
                        "due_timezone",
                        "is_all_day",
                        "waiting_for_kind",
                        "waiting_for_label",
                        "follow_up_at_utc",
                        "follow_up_timezone",
                    )
                },
                follow_up_state=facts["followUpState"],
                follow_up_due_today=facts["followUpDueToday"],
                follow_up_actionable=facts["followUpActionable"],
                task_deadline_state=facts["taskDeadlineState"],
                as_of=facts["asOf"],
            )
            key = row["related_entity_id"]
            result[key].items.append(preview)
            result[key] = TaskParentPreview(row["total"], result[key].items)
        return result

    def task(self, connection: Any, task_id: str) -> dict[str, Any] | None:
        row = (
            connection.execute(TaskModel.__table__.select().where(TaskModel.id == task_id))
            .mappings()
            .first()
        )
        return None if row is None else _summary(row)

    def tasks_for_related_entities(
        self, connection: Any, entity_type: str, entity_ids: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        if not entity_ids:
            return {}
        rows = connection.execute(
            select(
                TaskModel.id,
                TaskModel.title,
                TaskModel.status,
                TaskModel.priority,
                TaskModel.due_at_utc,
                TaskModel.due_timezone,
                TaskModel.is_all_day,
                TaskModel.related_entity_type,
                TaskModel.related_entity_id,
                TaskModel.deleted_at_utc,
            )
            .where(
                TaskModel.related_entity_type == entity_type,
                TaskModel.related_entity_id.in_(set(entity_ids)),
                TaskModel.deleted_at_utc.is_(None),
            )
            .order_by(TaskModel.created_at_utc.desc(), TaskModel.id.desc())
        ).mappings()
        result: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            result[row["related_entity_id"]].append(_summary(row))
        return dict(result)

    def related_entity_ids_with_active_tasks(self, connection: Any, entity_type: str) -> set[str]:
        return set(
            connection.execute(
                TaskModel.__table__.select()
                .with_only_columns(TaskModel.related_entity_id)
                .where(
                    TaskModel.related_entity_type == entity_type,
                    TaskModel.status.in_(("open", "in_progress")),
                    TaskModel.deleted_at_utc.is_(None),
                )
            ).scalars()
        )

    def active_related_entity_ids(
        self, connection: Any, entity_type: str, entity_ids: list[str]
    ) -> set[str]:
        if not entity_ids:
            return set()
        return set(
            connection.execute(
                TaskModel.__table__.select()
                .with_only_columns(TaskModel.related_entity_id)
                .where(
                    TaskModel.related_entity_type == entity_type,
                    TaskModel.related_entity_id.in_(set(entity_ids)),
                    TaskModel.status.in_(("open", "in_progress")),
                    TaskModel.deleted_at_utc.is_(None),
                )
            ).scalars()
        )


def _summary(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "priority": row["priority"],
        "due_at_utc": row["due_at_utc"],
        "due_timezone": row["due_timezone"],
        "is_all_day": bool(row["is_all_day"]),
        "related_entity_type": row["related_entity_type"],
        "related_entity_id": row["related_entity_id"],
        "deleted_at_utc": row["deleted_at_utc"],
    }

"""Capped related-task facts with deadline/waiting policy owned by Tasks."""

from sqlalchemy import and_, exists, select, literal
from app.modules.tasks.domain.models import Task, waiting_facts
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel
from app.platform.context_reads import ReadPage
from app.platform.sql_context_reads import bounded_page


class SQLiteTaskSummaryReader:
    def references(self, scope):
        t = TaskModel.__table__
        return (
            select(literal("task").label("entity_type"), t.c.id.label("entity_id"))
            .where(_membership(scope))
            .subquery("related_task_references")
        )

    def page(self, connection, scope, window):
        t = TaskModel.__table__
        columns = [column for column in t.c if column.name not in {"notes", "outcome_note"}]
        selection = select(*columns, t.c.created_at_utc.label("sort_key")).where(_membership(scope))
        if not window.include_history:
            selection = selection.where(t.c.status.in_(("open", "in_progress")))
        page = bounded_page(connection, selection, window, descending=True)
        items = []
        for row in page.items:
            task = Task(
                **{
                    key: row[key]
                    for key in Task.__dataclass_fields__
                    if key not in {"notes", "outcome_note"}
                },
                notes=None,
                outcome_note=None,
            )
            facts = waiting_facts(task, window.as_of)
            items.append(
                {
                    **row,
                    "is_all_day": bool(row["is_all_day"]),
                    "follow_up_state": facts["followUpState"],
                    "follow_up_due_today": facts["followUpDueToday"],
                    "follow_up_actionable": facts["followUpActionable"],
                    "task_deadline_state": facts["taskDeadlineState"],
                    "as_of": facts["asOf"],
                }
            )
        return ReadPage(page.total, items, page.next_key)


def _membership(scope):
    t, refs = TaskModel.__table__, scope.references.c
    return and_(
        t.c.deleted_at_utc.is_(None),
        exists(
            select(1).where(
                and_(
                    refs.entity_type == t.c.related_entity_type,
                    refs.entity_id == t.c.related_entity_id,
                )
            )
        ),
    )

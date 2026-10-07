"""SQLite implementation of the task unit of work."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
import sqlite3
from typing import Any, TypeVar

from sqlalchemy import and_, case, event, func, or_, select, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.tasks.application.waiting import (
    WaitingBusy,
    WaitingOperation,
    WaitingStorageFailure,
)
from app.modules.tasks.application.ports import DueReminderSummary, TaskSummary, TaskTransaction
from app.modules.tasks.domain.models import Task, TaskReminder, due_bucket, waiting_facts
from app.modules.tasks.infrastructure.sqlalchemy_models import (
    TaskModel,
    TaskReminderModel,
    TaskWaitingOperationModel,
)
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

Result = TypeVar("Result")


class SQLiteTaskUnitOfWork:
    """Keeps SQLite concerns behind a transaction boundary for TaskService."""

    def __init__(self, database, recorder: AuditRecorder) -> None:
        self.engine = create_sqlite_engine(database)
        self.recorder = recorder

        @event.listens_for(self.engine, "connect")
        def task_due_bucket(dbapi_connection, _connection_record) -> None:
            dbapi_connection.create_function("task_due_bucket", 4, _task_due_bucket)
            dbapi_connection.create_function("task_follow_up_today", 3, _follow_up_today)

    def read_follow_ups(self, operation):
        with _waiting_storage_errors(), self.engine.connect() as connection, connection.begin():
            return operation(_FollowUpReadTransaction(connection))

    def waiting_operation(self, key):
        with _waiting_storage_errors(), self.engine.connect() as connection:
            return _SQLiteTaskTransaction(connection, self.recorder).waiting_operation(key)

    def write_waiting(self, operation: Callable[[TaskTransaction], Result]) -> Result:
        with _waiting_storage_errors():
            return self.write(operation)

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

    def page(
        self,
        *,
        statuses: tuple[str, ...],
        priorities: tuple[str, ...] | None,
        related_entity_type: str | None,
        related_entity_id: str | None,
        limit: int,
        cursor: tuple[int, str | None, str, str] | None,
    ) -> list[Task]:
        with Session(self.engine) as session:
            no_due = TaskModel.due_at_utc.is_(None)
            query = select(TaskModel)
            query = query.where(TaskModel.status.in_(statuses))
            if priorities is not None:
                query = query.where(TaskModel.priority.in_(priorities))
            if related_entity_type is not None:
                query = query.where(
                    TaskModel.related_entity_type == related_entity_type,
                    TaskModel.related_entity_id == related_entity_id,
                )
            if cursor is not None:
                cursor_no_due, cursor_due, cursor_created, cursor_id = cursor
                later_same_due = or_(
                    TaskModel.created_at_utc < cursor_created,
                    and_(TaskModel.created_at_utc == cursor_created, TaskModel.id < cursor_id),
                )
                if cursor_no_due:
                    query = query.where(and_(no_due, later_same_due))
                else:
                    query = query.where(
                        or_(
                            no_due,
                            TaskModel.due_at_utc > cursor_due,
                            and_(TaskModel.due_at_utc == cursor_due, later_same_due),
                        )
                    )
            query = query.order_by(
                no_due, TaskModel.due_at_utc, TaskModel.created_at_utc.desc(), TaskModel.id.desc()
            ).limit(limit)
            return [_task(row) for row in session.execute(query).scalars()]

    def reminders(self, task_id: str | None = None) -> list[TaskReminder]:
        with Session(self.engine) as session:
            query = select(TaskReminderModel).order_by(TaskReminderModel.remind_at_utc)
            if task_id:
                query = query.where(TaskReminderModel.task_id == task_id)
            return [_reminder(row) for row in session.execute(query).scalars()]

    def summary(self, *, now: datetime, limit: int) -> TaskSummary:
        """Read all dashboard buckets from one SQLite snapshot."""
        with self.engine.connect() as connection:
            with connection.begin():
                overdue_total, overdue = _summary_tasks(
                    connection, bucket="overdue", now=now, limit=limit
                )
                today_total, today = _summary_tasks(
                    connection, bucket="today", now=now, limit=limit
                )
                next7days_total, next7days = _summary_tasks(
                    connection, bucket="next7days", now=now, limit=limit
                )
                due_reminders_total, due_reminders = _due_reminders_summary(
                    connection, now=now, limit=limit
                )
        return TaskSummary(
            overdue_total=overdue_total,
            overdue=overdue,
            today_total=today_total,
            today=today,
            next7days_total=next7days_total,
            next7days=next7days,
            due_reminders_total=due_reminders_total,
            due_reminders=due_reminders,
        )


@contextmanager
def _waiting_storage_errors():
    """Translate only database failures, after transaction cleanup has run."""
    try:
        yield
    except (DBAPIError, sqlite3.Error) as error:
        driver_error = error.orig if isinstance(error, DBAPIError) else error
        code = getattr(driver_error, "sqlite_errorcode", None)
        if isinstance(code, int) and code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            raise WaitingBusy() from error
        raise WaitingStorageFailure() from error


def _summary_tasks(
    connection: Any, *, bucket: str, now: datetime, limit: int
) -> tuple[int, list[Task]]:
    condition = and_(
        TaskModel.status.in_(("open", "in_progress")),
        TaskModel.due_at_utc.is_not(None),
        func.task_due_bucket(
            TaskModel.due_at_utc,
            TaskModel.due_timezone,
            TaskModel.is_all_day,
            now.isoformat(),
        )
        == bucket,
    )
    total = connection.scalar(select(func.count()).select_from(TaskModel).where(condition)) or 0
    rows = connection.execute(
        TaskModel.__table__.select()
        .where(condition)
        .order_by(
            TaskModel.due_at_utc,
            TaskModel.created_at_utc,
            TaskModel.id,
        )
        .limit(limit)
    ).mappings()
    return total, [_task_mapping(row) for row in rows]


def _due_reminders_summary(
    connection: Any, *, now: datetime, limit: int
) -> tuple[int, list[DueReminderSummary]]:
    condition = and_(
        TaskReminderModel.status == "pending",
        TaskReminderModel.remind_at_utc <= now.isoformat(),
    )
    columns = (
        TaskReminderModel.id,
        TaskReminderModel.task_id,
        TaskReminderModel.remind_at_utc,
        TaskReminderModel.status,
        TaskReminderModel.acknowledged_at_utc,
        TaskReminderModel.dismissed_at_utc,
        TaskReminderModel.created_at_utc,
        TaskModel.title.label("task_title"),
        TaskModel.due_at_utc.label("task_due_at_utc"),
        TaskModel.due_timezone.label("task_due_timezone"),
        TaskModel.is_all_day.label("task_is_all_day"),
        TaskModel.related_label.label("related_label"),
        *(
            column.label(f"parent_{column.name}")
            for column in TaskModel.__table__.columns
            if column.name != "notes"
        ),
    )
    total = (
        connection.scalar(
            select(func.count()).select_from(TaskReminderModel).join(TaskModel).where(condition)
        )
        or 0
    )
    rows = connection.execute(
        select(*columns)
        .join(TaskModel)
        .where(condition)
        .order_by(
            TaskReminderModel.remind_at_utc,
            TaskReminderModel.id,
        )
        .limit(limit)
    ).mappings()
    return total, [_due_reminder_summary(row, now) for row in rows]


class _SQLiteTaskTransaction:
    def __init__(self, connection: Any, recorder: AuditRecorder) -> None:
        self.connection = connection
        self.recorder = recorder

    def get_task(self, task_id: str) -> Task | None:
        row = (
            self.connection.execute(TaskModel.__table__.select().where(TaskModel.id == task_id))
            .mappings()
            .first()
        )
        return _task_mapping(row) if row else None

    def insert_task(self, task: Task) -> None:
        self.connection.execute(TaskModel.__table__.insert().values(**_task_values(task)))

    def replace_task(self, task: Task) -> None:
        self.connection.execute(
            TaskModel.__table__.update().where(TaskModel.id == task.id).values(**_task_values(task))
        )

    def waiting_operation(self, key):
        row = (
            self.connection.execute(
                TaskWaitingOperationModel.__table__.select().where(
                    TaskWaitingOperationModel.idempotency_key == key
                )
            )
            .mappings()
            .first()
        )
        return WaitingOperation(**row) if row else None

    def insert_waiting_operation(self, operation):
        self.connection.execute(
            TaskWaitingOperationModel.__table__.insert().values(**operation.__dict__)
        )

    def pending_reminders(self, task_id: str) -> list[TaskReminder]:
        rows = (
            self.connection.execute(
                TaskReminderModel.__table__.select().where(
                    TaskReminderModel.task_id == task_id, TaskReminderModel.status == "pending"
                )
            )
            .mappings()
            .all()
        )
        return [TaskReminder(**dict(row)) for row in rows]

    def insert_reminder(self, reminder: TaskReminder) -> None:
        self.connection.execute(TaskReminderModel.__table__.insert().values(**reminder.__dict__))

    def get_reminder(self, task_id: str, reminder_id: str) -> TaskReminder | None:
        row = (
            self.connection.execute(
                TaskReminderModel.__table__.select().where(
                    TaskReminderModel.id == reminder_id, TaskReminderModel.task_id == task_id
                )
            )
            .mappings()
            .first()
        )
        return TaskReminder(**dict(row)) if row else None

    def replace_reminder(self, reminder: TaskReminder) -> None:
        self.connection.execute(
            TaskReminderModel.__table__.update()
            .where(TaskReminderModel.id == reminder.id)
            .values(**reminder.__dict__)
        )

    def record_change(
        self,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        reason: str,
        correlation_id: str,
    ) -> None:
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
    return TaskReminder(
        **{column: getattr(row, column) for column in TaskReminder.__dataclass_fields__}
    )


def _task_values(task: Task) -> dict[str, Any]:
    return {**task.__dict__, "is_all_day": int(task.is_all_day)}


def _task_due_bucket(
    due_at_utc: str | None, due_timezone: str | None, is_all_day: int, now: str
) -> str | None:
    """SQLite UDF: retain set-based filtering while respecting each stored IANA zone."""
    if due_at_utc is None or due_timezone is None:
        return None
    return due_bucket(
        status="open",
        due_at_utc=due_at_utc,
        due_timezone=due_timezone,
        is_all_day=bool(is_all_day),
        now=datetime.fromisoformat(now),
    )


def _due_reminder_summary(row: Any, now: datetime) -> DueReminderSummary:
    parent = Task(
        **{key: row[f"parent_{key}"] for key in Task.__dataclass_fields__ if key != "notes"},
        notes=None,
    )
    facts = waiting_facts(parent, now)
    return DueReminderSummary(
        id=row["id"],
        task_id=row["task_id"],
        remind_at_utc=row["remind_at_utc"],
        status=row["status"],
        acknowledged_at_utc=row["acknowledged_at_utc"],
        dismissed_at_utc=row["dismissed_at_utc"],
        created_at_utc=row["created_at_utc"],
        task_title=row["task_title"],
        task_due_at_utc=row["task_due_at_utc"],
        task_due_timezone=row["task_due_timezone"],
        task_is_all_day=bool(row["task_is_all_day"]),
        related_label=row["related_label"],
        task_revision=parent.revision,
        task_waiting_for_kind=parent.waiting_for_kind,
        task_waiting_for_label=parent.waiting_for_label,
        task_follow_up_at_utc=parent.follow_up_at_utc,
        task_follow_up_timezone=parent.follow_up_timezone,
        task_follow_up_state=facts["followUpState"],
        task_follow_up_due_today=facts["followUpDueToday"],
        task_follow_up_actionable=facts["followUpActionable"],
        task_deadline_state=facts["taskDeadlineState"],
    )


def _follow_up_today(value, zone, now):
    from zoneinfo import ZoneInfo

    if value is None:
        return 0
    timezone = ZoneInfo(zone)
    return int(
        datetime.fromisoformat(value).astimezone(timezone).date()
        == datetime.fromisoformat(now).astimezone(timezone).date()
    )


class _FollowUpReadTransaction:
    def __init__(self, connection):
        self.connection = connection

    def marker(self):
        return SQLiteAuditReadMarker().marker(self.connection)

    def page(self, query, now, after):
        table = TaskModel.__table__
        stamp = now.isoformat()
        date = TaskModel.follow_up_at_utc
        rank = case(
            (date < stamp, 0),
            (date == stamp, 1),
            (func.task_follow_up_today(date, TaskModel.follow_up_timezone, stamp) == 1, 2),
            (date.is_(None), 3),
            else_=4,
        )
        state = case(
            (date.is_(None), "unscheduled"),
            (date < stamp, "overdue"),
            (date == stamp, "due"),
            else_="scheduled",
        )
        predicates = [
            TaskModel.status.in_(("open", "in_progress")),
            TaskModel.waiting_for_kind.is_not(None),
        ]
        if query.state is not None:
            predicates.append(state == query.state)
        if query.actionable is not None:
            predicates.append(
                and_(date.is_not(None), date <= stamp)
                if query.actionable
                else or_(date.is_(None), date > stamp)
            )
        if query.priority:
            predicates.append(TaskModel.priority == query.priority)
        if query.related_entity_type:
            predicates.extend(
                (
                    TaskModel.related_entity_type == query.related_entity_type,
                    TaskModel.related_entity_id == query.related_entity_id,
                )
            )
        total = self.connection.scalar(select(func.count()).select_from(table).where(*predicates))
        sort_date = func.coalesce(date, "")
        if after is not None:
            predicates.append(tuple_(rank, sort_date, TaskModel.id) > after)
        rows = self.connection.execute(
            table.select()
            .where(*predicates)
            .order_by(rank, sort_date, TaskModel.id)
            .limit(query.limit + 1)
        ).mappings()
        return total, [_task_mapping(row) for row in rows]

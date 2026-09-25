"""Application use cases and commands for local tasks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from base64 import urlsafe_b64decode, urlsafe_b64encode
from json import dumps, loads
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.modules.tasks.application.ports import DueReminderSummary, TaskTransaction, TaskUnitOfWork
from app.modules.tasks.domain.models import ACTIVE_TASK_STATUSES, Task, TaskReminder, dismiss, due_bucket, is_terminal, transition

TASK_STATUSES = {"open", "in_progress", "completed", "cancelled"}
INITIAL_TASK_STATUSES = ACTIVE_TASK_STATUSES
TASK_PRIORITIES = {"low", "normal", "high", "urgent"}
MAX_DUE_FILTER_SCAN_CANDIDATES = 1_000


class TaskError(RuntimeError):
    pass


class TaskNotFoundError(TaskError):
    pass


class TaskConflictError(TaskError):
    pass


@dataclass(frozen=True)
class TaskCreateCommand:
    title: str
    notes: str | None
    status: str
    priority: str
    due_at_utc: str | None
    due_timezone: str | None
    is_all_day: bool
    related_entity_type: str | None
    related_entity_id: str | None
    related_label: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not (title := self.title.strip()) or len(title) > 240:
            raise TaskError("Task title must contain 1 to 240 characters.")
        if title != self.title:
            object.__setattr__(self, "title", title)
        if self.notes is not None and not isinstance(self.notes, str):
            raise TaskError("Task notes must be text.")
        if self.status not in INITIAL_TASK_STATUSES or self.priority not in TASK_PRIORITIES:
            raise TaskError("Invalid task status or priority.")
        if not isinstance(self.is_all_day, bool):
            raise TaskError("isAllDay must be a boolean.")
        has_due_at = self.due_at_utc not in (None, "")
        if not has_due_at and (self.due_timezone is not None or self.is_all_day):
            raise TaskError("dueTimezone and isAllDay require dueAtUtc.")
        if has_due_at and (not isinstance(self.due_at_utc, str) or not self.due_at_utc.strip()):
            raise TaskError("dueAtUtc must be nonblank text.")
        if has_due_at and (not isinstance(self.due_timezone, str) or not self.due_timezone.strip()):
            raise TaskError("dueAtUtc requires a nonblank dueTimezone.")
        related_type = _optional_trimmed_text(self.related_entity_type, "Related entity type")
        related_id = _optional_trimmed_text(self.related_entity_id, "Related entity ID")
        related_label = _optional_trimmed_text(self.related_label, "Related label")
        if (related_type is None) != (related_id is None):
            raise TaskError("Related entity type and ID must be provided together as text.")
        if related_label is not None and related_type is None:
            raise TaskError("A related label requires a related entity type and ID.")
        object.__setattr__(self, "related_entity_type", related_type)
        object.__setattr__(self, "related_entity_id", related_id)
        object.__setattr__(self, "related_label", related_label)

    @classmethod
    def from_mapping(cls, data: object) -> "TaskCreateCommand":
        if not isinstance(data, dict):
            raise TaskError("Task input must be an object.")
        return cls(
            title=data.get("title"),
            notes=data.get("notes"),
            status=data.get("status", "open"),
            priority=data.get("priority", "normal"),
            due_at_utc=data.get("dueAtUtc"),
            due_timezone=data.get("dueTimezone"),
            is_all_day=data.get("isAllDay", False),
            related_entity_type=data.get("relatedEntityType"),
            related_entity_id=data.get("relatedEntityId"),
            related_label=data.get("relatedLabel"),
        )


class TaskService:
    """Owns task and reminder lifecycle rules; adapters only persist changes."""

    def __init__(self, unit_of_work: TaskUnitOfWork,
                 now: Callable[[], datetime] | None = None) -> None:
        self.unit_of_work = unit_of_work
        self._clock = now or (lambda: datetime.now(UTC))

    def create(self, data: TaskCreateCommand | dict) -> Task:
        command = data if isinstance(data, TaskCreateCommand) else TaskCreateCommand.from_mapping(data)
        task = new_task(command, now=self._now())
        correlation_id = str(uuid4())

        def create_in_transaction(transaction: TaskTransaction) -> Task:
            transaction.insert_task(task)
            transaction.record_change(
                entity_type="task", entity_id=task.id, action="created",
                before=None, after=task.to_dict(), reason="task_created", correlation_id=correlation_id,
            )
            return task

        return self.unit_of_work.write(create_in_transaction)

    def get(self, task_id: str) -> Task:
        task = self.unit_of_work.get(task_id)
        if task is None:
            raise TaskNotFoundError("Task was not found.")
        return task

    def list(self, status: str | None = None) -> list[Task]:
        if status is not None and status not in TASK_STATUSES:
            raise TaskError("Invalid task status.")
        return self.unit_of_work.list(status)

    def page(self, *, status: str | None = None, due: str | None = None,
             priority: str | None = None, include_voided: bool = False,
             related_entity_type: str | None = None, related_entity_id: str | None = None,
             page_size: int = 100, cursor: str | None = None) -> tuple[list[Task], str | None]:
        statuses = _query_values(status, TASK_STATUSES, "status")
        priorities = _query_values(priority, TASK_PRIORITIES, "priority")
        if type(include_voided) is not bool:
            raise TaskError("includeVoided must be a boolean.")
        if statuses is None:
            statuses = tuple(sorted(INITIAL_TASK_STATUSES if not include_voided else TASK_STATUSES))
        elif not include_voided:
            statuses = tuple(value for value in statuses if value in INITIAL_TASK_STATUSES)
        related_type = _optional_trimmed_text(related_entity_type, "Related entity type")
        related_id = _optional_trimmed_text(related_entity_id, "Related entity ID")
        if (related_type is None) != (related_id is None):
            raise TaskError("relatedEntityType and relatedEntityId must be supplied together.")
        if type(page_size) is not int or not 1 <= page_size <= 500:
            raise TaskError("Page size must be between 1 and 500.")
        due_filter = _due_filter(due, self._instant())
        scan_cursor = _task_cursor(cursor) if cursor else None
        matched: list[Task] = []
        chunk_size = max(100, page_size + 1)
        scanned = 0
        while scanned < MAX_DUE_FILTER_SCAN_CANDIDATES:
            limit = min(chunk_size, MAX_DUE_FILTER_SCAN_CANDIDATES - scanned)
            tasks = self.unit_of_work.page(
                statuses=statuses, priorities=priorities, related_entity_type=related_type,
                related_entity_id=related_id, limit=limit, cursor=scan_cursor,
            )
            scanned += len(tasks)
            matched.extend(task for task in tasks if due_filter(task))
            if len(matched) > page_size:
                page = matched[:page_size]
                return page, _encode_task_cursor(page[-1])
            if len(tasks) < limit:
                return matched, None
            scan_cursor = _task_values_for_cursor(tasks[-1])
        return matched, _encode_task_cursor_values(scan_cursor) if scan_cursor else None

    def transition(self, task_id: str, status: str, outcome_note: str | None = None) -> Task:
        if status not in TASK_STATUSES or (outcome_note is not None and not isinstance(outcome_note, str)):
            raise TaskError("Invalid task transition.")
        now = self._now()
        correlation_id = str(uuid4())

        def transition_in_transaction(transaction: TaskTransaction) -> Task:
            existing = transaction.get_task(task_id)
            if existing is None:
                raise KeyError("Task was not found.")
            updated = transition(existing, status, outcome_note, now)
            transaction.replace_task(updated)
            transaction.record_change(
                entity_type="task", entity_id=updated.id, action="status_changed",
                before=existing.to_dict(), after=updated.to_dict(), reason="task_updated", correlation_id=correlation_id,
            )
            if is_terminal(updated):
                self._dismiss_pending_reminders(transaction, updated, now, correlation_id)
            return updated

        try:
            return self.unit_of_work.write(transition_in_transaction)
        except KeyError as error:
            raise TaskNotFoundError(str(error)) from error
        except ValueError as error:
            raise TaskConflictError(str(error)) from error

    def add_reminder(self, task_id: str, remind_at_utc: str) -> TaskReminder:
        instant, _ = _timestamp(remind_at_utc, "UTC", required=True)
        reminder = TaskReminder(str(uuid4()), task_id, instant, "pending", None, None, self._now())
        correlation_id = str(uuid4())

        def create_in_transaction(transaction: TaskTransaction) -> TaskReminder:
            parent = transaction.get_task(task_id)
            if parent is None or parent.status not in INITIAL_TASK_STATUSES:
                raise ValueError("Reminders can only be added to active tasks.")
            transaction.insert_reminder(reminder)
            transaction.record_change(
                entity_type="task_reminder", entity_id=reminder.id, action="created",
                before=None, after=reminder.to_dict(), reason="reminder_created", correlation_id=correlation_id,
            )
            return reminder

        try:
            return self.unit_of_work.write(create_in_transaction)
        except ValueError as error:
            raise TaskConflictError(str(error)) from error

    def set_reminder_status(self, task_id: str, reminder_id: str, status: str) -> TaskReminder:
        if status not in {"acknowledged", "dismissed"}:
            raise TaskError("Reminder status is invalid.")
        now = self._now()
        correlation_id = str(uuid4())

        def transition_in_transaction(transaction: TaskTransaction) -> TaskReminder:
            reminder = transaction.get_reminder(task_id, reminder_id)
            if reminder is None:
                raise KeyError("Reminder was not found.")
            if reminder.status != "pending":
                raise ValueError("Reminder is no longer pending.")
            updated = TaskReminder(
                reminder.id, reminder.task_id, reminder.remind_at_utc, status,
                now if status == "acknowledged" else None,
                now if status == "dismissed" else None,
                reminder.created_at_utc,
            )
            transaction.replace_reminder(updated)
            transaction.record_change(
                entity_type="task_reminder", entity_id=updated.id, action="status_changed",
                before=reminder.to_dict(), after=updated.to_dict(), reason="reminder_updated", correlation_id=correlation_id,
            )
            return updated

        try:
            return self.unit_of_work.write(transition_in_transaction)
        except KeyError as error:
            raise TaskNotFoundError(str(error)) from error
        except ValueError as error:
            raise TaskConflictError(str(error)) from error

    def summary(self, *, limit_per_bucket: int = 20) -> dict[str, object]:
        if type(limit_per_bucket) is not int or not 1 <= limit_per_bucket <= 100:
            raise TaskError("limitPerBucket must be between 1 and 100.")
        summary = self.unit_of_work.summary(now=self._instant(), limit=limit_per_bucket)
        return {
            "overdue": [task.to_dict() for task in summary.overdue], "overdueTotal": summary.overdue_total,
            "today": [task.to_dict() for task in summary.today], "todayTotal": summary.today_total,
            "next7days": [task.to_dict() for task in summary.next7days], "next7daysTotal": summary.next7days_total,
            "dueReminders": [_due_reminder_dict(reminder) for reminder in summary.due_reminders],
            "dueRemindersTotal": summary.due_reminders_total,
        }

    def _instant(self) -> datetime:
        instant = self._clock()
        if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
            raise TaskError("Task clock must return an aware timestamp.")
        return instant.astimezone(UTC)

    def _now(self) -> str:
        return self._instant().isoformat()

    @staticmethod
    def _dismiss_pending_reminders(transaction: TaskTransaction, task: Task, now: str, correlation_id: str) -> None:
        for reminder in transaction.pending_reminders(task.id):
            dismissed = dismiss(reminder, now)
            transaction.replace_reminder(dismissed)
            transaction.record_change(
                entity_type="task_reminder", entity_id=dismissed.id, action="dismissed",
                before=reminder.to_dict(), after=dismissed.to_dict(), reason="task_updated", correlation_id=correlation_id,
            )


def new_task(command: TaskCreateCommand, *, task_id: str | None = None, now: str | None = None) -> Task:
    """Public TASK-001 factory for transaction-aware owning-domain adapters."""
    due_at, timezone = _timestamp(command.due_at_utc, command.due_timezone, required=False)
    created_at = now or _now()
    return Task(
        task_id or str(uuid4()), command.title, command.notes, command.status, command.priority,
        due_at, timezone, command.is_all_day, None, None, None,
        command.related_entity_type, command.related_entity_id, command.related_label, created_at, created_at,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _due_reminder_dict(reminder: DueReminderSummary) -> dict[str, object]:
    return {
        "id": reminder.id, "taskId": reminder.task_id, "remindAtUtc": reminder.remind_at_utc,
        "status": reminder.status, "acknowledgedAtUtc": reminder.acknowledged_at_utc,
        "dismissedAtUtc": reminder.dismissed_at_utc, "createdAtUtc": reminder.created_at_utc,
        "taskTitle": reminder.task_title, "taskDueAtUtc": reminder.task_due_at_utc,
        "taskDueTimezone": reminder.task_due_timezone, "taskIsAllDay": reminder.task_is_all_day,
        "relatedLabel": reminder.related_label,
    }


def _query_values(value: str | None, allowed: set[str], label: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TaskError(f"{label} must be a nonblank comma-separated list.")
    values = tuple(part.strip() for part in value.split(","))
    if not all(values) or len(set(values)) != len(values) or any(part not in allowed for part in values):
        raise TaskError(f"Invalid task {label} filter.")
    return values


def _due_filter(value: str | None, now: datetime):
    if value is None:
        return lambda task: True
    if not isinstance(value, str) or not value.strip():
        raise TaskError("due must be a supported period or ISO date range.")
    value = value.strip()
    if value in {"overdue", "today", "next7days", "nodate"}:
        def named(task: Task) -> bool:
            if value == "nodate":
                return task.due_at_utc is None
            return due_bucket(
                status=task.status, due_at_utc=task.due_at_utc, due_timezone=task.due_timezone,
                is_all_day=task.is_all_day, now=now,
            ) == value
        return named
    parts = tuple(part.strip() for part in value.split(","))
    if len(parts) != 2 or not all(parts):
        raise TaskError("due date range must be YYYY-MM-DD,YYYY-MM-DD.")
    try:
        start, end = (date.fromisoformat(part) for part in parts)
    except ValueError as error:
        raise TaskError("due date range must use ISO calendar dates.") from error
    if end < start:
        raise TaskError("due date range must not end before it starts.")
    def ranged(task: Task) -> bool:
        if task.due_at_utc is None:
            return False
        return start <= _parse(task.due_at_utc).astimezone(ZoneInfo(task.due_timezone or "UTC")).date() <= end
    return ranged


def _optional_trimmed_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not (trimmed := value.strip()):
        raise TaskError(f"{label} must be nonblank text.")
    return trimmed


def _parse(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise TaskError("Timestamp must be ISO-8601.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TaskError("Timestamp must include a timezone offset.")
    return parsed.astimezone(UTC)


def _timestamp(value: object, timezone: object, *, required: bool) -> tuple[str | None, str | None]:
    if value in (None, ""):
        if required:
            raise TaskError("A reminder timestamp is required.")
        return None, None
    if not isinstance(value, str) or (timezone is not None and not isinstance(timezone, str)):
        raise TaskError("Timestamp values must be text.")
    label = timezone
    assert isinstance(label, str)
    try:
        ZoneInfo(label)
    except ZoneInfoNotFoundError as error:
        raise TaskError("dueTimezone must be a valid IANA timezone.") from error
    return _parse(value).isoformat(), label


def _task_cursor(value: str) -> tuple[int, str | None, str, str]:
    if not isinstance(value, str):
        raise TaskError("Cursor is invalid.")
    try:
        no_due, due, created, task_id = loads(urlsafe_b64decode(value.encode()).decode())
        if type(no_due) is not int or no_due not in {0, 1}:
            raise ValueError
        if (no_due == 0 and not isinstance(due, str)) or (no_due == 1 and due is not None):
            raise ValueError
        if due is not None:
            _parse(due)
        _parse(created)
        if not isinstance(task_id, str) or not task_id:
            raise ValueError
        return no_due, due, created, task_id
    except (TypeError, ValueError, UnicodeDecodeError) as error:
        raise TaskError("Cursor is invalid.") from error


def _encode_task_cursor(task: Task) -> str:
    values = _task_values_for_cursor(task)
    return _encode_task_cursor_values(values)


def _encode_task_cursor_values(values: tuple[int, str | None, str, str]) -> str:
    return urlsafe_b64encode(dumps(values, separators=(",", ":")).encode()).decode()


def _task_values_for_cursor(task: Task) -> tuple[int, str | None, str, str]:
    return int(task.due_at_utc is None), task.due_at_utc, task.created_at_utc, task.id

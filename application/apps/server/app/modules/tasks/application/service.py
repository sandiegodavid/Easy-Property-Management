"""Application use cases and commands for local tasks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.modules.tasks.application.ports import TaskTransaction, TaskUnitOfWork
from app.modules.tasks.domain.models import Task, TaskReminder, dismiss, is_terminal, transition

TASK_STATUSES = {"open", "in_progress", "completed", "cancelled"}
INITIAL_TASK_STATUSES = {"open", "in_progress"}
TASK_PRIORITIES = {"low", "normal", "high", "urgent"}


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

    def __init__(self, unit_of_work: TaskUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def create(self, data: TaskCreateCommand | dict) -> Task:
        command = data if isinstance(data, TaskCreateCommand) else TaskCreateCommand.from_mapping(data)
        due_at, timezone = _timestamp(command.due_at_utc, command.due_timezone, required=False)
        now = _now()
        correlation_id = str(uuid4())
        task = Task(
            str(uuid4()), command.title, command.notes, command.status, command.priority,
            due_at, timezone, command.is_all_day, None, None, None,
            command.related_entity_type, command.related_entity_id, command.related_label, now, now,
        )

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

    def transition(self, task_id: str, status: str, outcome_note: str | None = None) -> Task:
        if status not in TASK_STATUSES or (outcome_note is not None and not isinstance(outcome_note, str)):
            raise TaskError("Invalid task transition.")
        now = _now()
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
        reminder = TaskReminder(str(uuid4()), task_id, instant, "pending", None, None, _now())
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
        now = _now()
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

    def summary(self) -> dict[str, object]:
        now = datetime.now(UTC)
        active = [task for task in self.unit_of_work.list() if task.status in INITIAL_TASK_STATUSES]
        active_ids = {task.id for task in active}
        return {
            "overdue": [task.to_dict() for task in active if task.due_at_utc and _parse(task.due_at_utc) < now],
            "dueReminders": [
                reminder.to_dict()
                for reminder in self.unit_of_work.reminders()
                if reminder.task_id in active_ids and reminder.status == "pending" and _parse(reminder.remind_at_utc) <= now
            ],
        }

    @staticmethod
    def _dismiss_pending_reminders(transaction: TaskTransaction, task: Task, now: str, correlation_id: str) -> None:
        for reminder in transaction.pending_reminders(task.id):
            dismissed = dismiss(reminder, now)
            transaction.replace_reminder(dismissed)
            transaction.record_change(
                entity_type="task_reminder", entity_id=dismissed.id, action="dismissed",
                before=reminder.to_dict(), after=dismissed.to_dict(), reason="task_updated", correlation_id=correlation_id,
            )


def _now() -> str:
    return datetime.now(UTC).isoformat()


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

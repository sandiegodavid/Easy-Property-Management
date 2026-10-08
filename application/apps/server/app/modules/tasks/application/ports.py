"""Ports for transactional task persistence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping, Protocol, TypeVar

if TYPE_CHECKING:
    from app.modules.tasks.application.creation import TaskCreationOperation
    from app.modules.tasks.application.mutations import TaskMutationOperation

from app.modules.tasks.domain.models import Task, TaskReminder
from app.modules.tasks.application.waiting import FollowUpQuery, WaitingOperation

Result = TypeVar("Result")


@dataclass(frozen=True)
class DueReminderSummary:
    id: str
    task_id: str
    remind_at_utc: str
    status: str
    acknowledged_at_utc: str | None
    dismissed_at_utc: str | None
    created_at_utc: str
    task_title: str
    task_due_at_utc: str | None
    task_due_timezone: str | None
    task_is_all_day: bool
    related_label: str | None
    task_revision: int
    task_waiting_for_kind: str | None
    task_waiting_for_label: str | None
    task_follow_up_at_utc: str | None
    task_follow_up_timezone: str | None
    task_follow_up_state: str | None
    task_follow_up_due_today: bool
    task_follow_up_actionable: bool
    task_deadline_state: str


@dataclass(frozen=True)
class TaskSummary:
    overdue_total: int
    overdue: list[Task]
    today_total: int
    today: list[Task]
    next7days_total: int
    next7days: list[Task]
    due_reminders_total: int
    due_reminders: list[DueReminderSummary]


class TaskTransactionOperations(Protocol):
    """Task persistence used inside another module's existing transaction."""

    def insert_task(self, connection: Any, task: Task) -> None: ...
    def insert_reminder(self, connection: Any, reminder: TaskReminder) -> None: ...
    def pending_reminders(self, connection: Any, task_id: str) -> list[TaskReminder]: ...
    def replace_reminder(self, connection: Any, reminder: TaskReminder) -> None: ...
    def latest_reminder_status(self, connection: Any, task_id: str) -> str | None: ...
    def create_task(
        self,
        connection: Any,
        command: Any,
        *,
        correlation_id: str,
        record_change: Callable[..., None],
    ) -> Task: ...


class TaskContextReader(Protocol):
    """Read-only task summaries for another aggregate's projection."""

    def task(self, connection: Any, task_id: str) -> dict[str, Any] | None: ...
    def previews_for_related_entities(
        self,
        connection: Any,
        entity_type: str,
        entity_ids: list[str],
        *,
        now: datetime,
        limit_per_parent: int = 10,
    ) -> Mapping[str, "TaskParentPreview"]: ...
    def tasks_for_related_entities(
        self, connection: Any, entity_type: str, entity_ids: list[str]
    ) -> dict[str, list[dict[str, Any]]]: ...
    def related_entity_ids_with_active_tasks(
        self, connection: Any, entity_type: str
    ) -> set[str]: ...
    def active_related_entity_ids(
        self, connection: Any, entity_type: str, entity_ids: list[str]
    ) -> set[str]: ...


class TaskTransaction(Protocol):
    """A single write transaction; it contains no task lifecycle policy."""

    def get_task(self, task_id: str) -> Task | None: ...
    def has_non_dismissed_reminders(self, task_id: str) -> bool: ...
    def mutation_operation(self, key: str) -> TaskMutationOperation | None: ...
    def insert_mutation_operation(self, operation: TaskMutationOperation) -> None: ...
    def creation_operation(self, key: str) -> TaskCreationOperation | None: ...
    def insert_creation_operation(self, operation: TaskCreationOperation) -> None: ...
    def insert_task(self, task: Task) -> None: ...
    def replace_task(self, task: Task) -> None: ...
    def waiting_operation(self, key: str) -> WaitingOperation | None: ...
    def insert_waiting_operation(self, operation: WaitingOperation) -> None: ...
    def pending_reminders(self, task_id: str) -> list[TaskReminder]: ...
    def insert_reminder(self, reminder: TaskReminder) -> None: ...
    def get_reminder(self, task_id: str, reminder_id: str) -> TaskReminder | None: ...
    def replace_reminder(self, reminder: TaskReminder) -> None: ...
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
    ) -> None: ...


class TaskUnitOfWork(Protocol):
    """Executes an application-owned task change atomically."""

    def write(self, operation: Callable[[TaskTransaction], Result]) -> Result: ...
    def write_waiting(self, operation: Callable[[TaskTransaction], Result]) -> Result:
        """Write atomically with the TASK-002 typed storage-failure boundary."""
        ...

    def read_follow_ups(
        self, operation: Callable[["FollowUpReadTransaction"], Result]
    ) -> Result: ...
    def waiting_operation(self, key: str) -> WaitingOperation | None: ...
    def get(self, task_id: str) -> Task | None: ...
    def creation_operation(self, key: str) -> TaskCreationOperation | None: ...
    def mutation_operation(self, key: str) -> TaskMutationOperation | None: ...
    def list(self, status: str | None = None) -> list[Task]: ...
    def page(
        self,
        *,
        statuses: tuple[str, ...],
        priorities: tuple[str, ...] | None,
        related_entity_type: str | None,
        related_entity_id: str | None,
        limit: int,
        cursor: tuple[int, str | None, str, str] | None,
    ) -> list[Task]: ...
    def reminders(self, task_id: str | None = None) -> list[TaskReminder]: ...
    def summary(self, *, now: datetime, limit: int) -> TaskSummary: ...


class FollowUpReadTransaction(Protocol):
    def marker(self) -> str: ...
    def page(
        self, query: FollowUpQuery, now: datetime, after: tuple[int, str, str] | None
    ) -> tuple[int, list[Task]]: ...


@dataclass(frozen=True)
class TaskPreview:
    id: str
    title: str
    status: str
    priority: str
    revision: int
    due_at_utc: str | None
    due_timezone: str | None
    is_all_day: bool
    waiting_for_kind: str | None
    waiting_for_label: str | None
    follow_up_at_utc: str | None
    follow_up_timezone: str | None
    follow_up_state: str | None
    follow_up_due_today: bool
    follow_up_actionable: bool
    task_deadline_state: str
    as_of: str


@dataclass(frozen=True)
class TaskParentPreview:
    total: int
    items: list[TaskPreview]

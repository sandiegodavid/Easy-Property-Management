from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

ACTIVE_TASK_STATUSES = frozenset({"open", "in_progress"})


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    notes: str | None
    status: str
    priority: str
    due_at_utc: str | None
    due_timezone: str | None
    is_all_day: bool
    completed_at_utc: str | None
    cancelled_at_utc: str | None
    outcome_note: str | None
    related_entity_type: str | None
    related_entity_id: str | None
    related_label: str | None
    created_at_utc: str
    updated_at_utc: str
    revision: int = 1
    waiting_for_kind: str | None = None
    waiting_for_label: str | None = None
    follow_up_at_utc: str | None = None
    follow_up_timezone: str | None = None
    waiting_set_at_utc: str | None = None
    waiting_cleared_at_utc: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "notes": self.notes,
            "status": self.status,
            "priority": self.priority,
            "dueAtUtc": self.due_at_utc,
            "dueTimezone": self.due_timezone,
            "isAllDay": self.is_all_day,
            "completedAtUtc": self.completed_at_utc,
            "cancelledAtUtc": self.cancelled_at_utc,
            "outcomeNote": self.outcome_note,
            "relatedEntityType": self.related_entity_type,
            "relatedEntityId": self.related_entity_id,
            "relatedLabel": self.related_label,
            "createdAtUtc": self.created_at_utc,
            "updatedAtUtc": self.updated_at_utc,
            "revision": self.revision,
            "waitingForKind": self.waiting_for_kind,
            "waitingForLabel": self.waiting_for_label,
            "followUpAt": self.follow_up_at_utc,
            "followUpTimezone": self.follow_up_timezone,
            "waitingSetAtUtc": self.waiting_set_at_utc,
            "waitingClearedAtUtc": self.waiting_cleared_at_utc,
        }


@dataclass(frozen=True)
class TaskReminder:
    id: str
    task_id: str
    remind_at_utc: str
    status: str
    acknowledged_at_utc: str | None
    dismissed_at_utc: str | None
    created_at_utc: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "taskId": self.task_id,
            "remindAtUtc": self.remind_at_utc,
            "status": self.status,
            "acknowledgedAtUtc": self.acknowledged_at_utc,
            "dismissedAtUtc": self.dismissed_at_utc,
            "createdAtUtc": self.created_at_utc,
        }


def transition(task: Task, status: str, outcome_note: str | None, now: str) -> Task:
    allowed = {
        "open": {"in_progress", "completed", "cancelled"},
        "in_progress": {"open", "completed", "cancelled"},
        "completed": {"open"},
        "cancelled": {"open"},
    }
    if status not in allowed.get(task.status, set()):
        raise ValueError(f"Cannot transition a {task.status} task to {status}.")
    if status in {"completed", "cancelled"}:
        return replace(
            clear_waiting(task, now) if task.waiting_for_kind else task,
            status=status,
            completed_at_utc=now if status == "completed" else None,
            cancelled_at_utc=now if status == "cancelled" else None,
            outcome_note=outcome_note,
            updated_at_utc=now,
            revision=task.revision + 1,
        )
    return replace(
        task,
        status=status,
        completed_at_utc=None,
        cancelled_at_utc=None,
        outcome_note=None,
        updated_at_utc=now,
        revision=task.revision + 1,
    )


def clear_waiting(task: Task, now: str) -> Task:
    return replace(
        task,
        waiting_for_kind=None,
        waiting_for_label=None,
        follow_up_at_utc=None,
        follow_up_timezone=None,
        waiting_set_at_utc=None,
        waiting_cleared_at_utc=now,
    )


def waiting_facts(task: Task, now: datetime) -> dict[str, object]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Task classification requires an aware instant.")
    now = now.astimezone(UTC)
    active = task.status in ACTIVE_TASK_STATUSES
    waiting = active and task.waiting_for_kind is not None
    state = None
    today = actionable = False
    if waiting:
        state = "unscheduled"
        if task.follow_up_at_utc is not None:
            instant = datetime.fromisoformat(task.follow_up_at_utc)
            state = "overdue" if instant < now else "due" if instant == now else "scheduled"
            zone = ZoneInfo(task.follow_up_timezone)
            today = instant.astimezone(zone).date() == now.astimezone(zone).date()
            actionable = instant <= now
    deadline = "inactive" if not active else "none"
    if active and task.due_at_utc:
        bucket = due_bucket(
            status=task.status,
            due_at_utc=task.due_at_utc,
            due_timezone=task.due_timezone,
            is_all_day=task.is_all_day,
            now=now,
        )
        deadline = bucket if bucket in {"overdue", "today"} else "upcoming"
    return {
        "isWaiting": waiting,
        "waitingFor": (
            {"kind": task.waiting_for_kind, "label": task.waiting_for_label} if waiting else None
        ),
        "followUpState": state,
        "followUpDueToday": today,
        "followUpActionable": actionable,
        "taskDeadlineState": deadline,
        "asOf": now.isoformat(),
    }


def follow_up_rank(task: Task, now: datetime) -> int:
    facts = waiting_facts(task, now)
    if facts["followUpState"] == "overdue":
        return 0
    if facts["followUpState"] == "due":
        return 1
    if facts["followUpDueToday"]:
        return 2
    return 3 if task.follow_up_at_utc is None else 4


def is_terminal(task: Task) -> bool:
    return task.status in {"completed", "cancelled"}


def dismiss(reminder: TaskReminder, now: str) -> TaskReminder:
    if reminder.status != "pending":
        raise ValueError("Reminder is no longer pending.")
    return TaskReminder(
        reminder.id,
        reminder.task_id,
        reminder.remind_at_utc,
        "dismissed",
        None,
        now,
        reminder.created_at_utc,
    )


def due_bucket(
    *,
    status: str,
    due_at_utc: str | None,
    due_timezone: str | None,
    is_all_day: bool,
    now: datetime,
) -> str | None:
    """Classify an active task's due state under TASK-001's local-time rules."""
    if status not in ACTIVE_TASK_STATUSES or due_at_utc is None or due_timezone is None:
        return None
    instant = datetime.fromisoformat(due_at_utc).astimezone(UTC)
    timezone = ZoneInfo(due_timezone)
    local_today = now.astimezone(timezone).date()
    local_day = instant.astimezone(timezone).date()
    if (is_all_day and local_day < local_today) or (not is_all_day and instant < now):
        return "overdue"
    if local_day == local_today:
        return "today"
    if local_today < local_day <= local_today + timedelta(days=7):
        return "next7days"
    return None

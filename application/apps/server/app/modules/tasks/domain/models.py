from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    id: str; title: str; notes: str | None; status: str; priority: str
    due_at_utc: str | None; due_timezone: str | None; is_all_day: bool
    completed_at_utc: str | None; cancelled_at_utc: str | None; outcome_note: str | None
    related_entity_type: str | None; related_entity_id: str | None; related_label: str | None
    created_at_utc: str; updated_at_utc: str
    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "title": self.title, "notes": self.notes, "status": self.status,
                "priority": self.priority, "dueAtUtc": self.due_at_utc, "dueTimezone": self.due_timezone,
                "isAllDay": self.is_all_day, "completedAtUtc": self.completed_at_utc,
                "cancelledAtUtc": self.cancelled_at_utc, "outcomeNote": self.outcome_note,
                "relatedEntityType": self.related_entity_type, "relatedEntityId": self.related_entity_id,
                "relatedLabel": self.related_label, "createdAtUtc": self.created_at_utc, "updatedAtUtc": self.updated_at_utc}


@dataclass(frozen=True)
class TaskReminder:
    id: str; task_id: str; remind_at_utc: str; status: str; acknowledged_at_utc: str | None; dismissed_at_utc: str | None; created_at_utc: str
    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "taskId": self.task_id, "remindAtUtc": self.remind_at_utc, "status": self.status,
                "acknowledgedAtUtc": self.acknowledged_at_utc, "dismissedAtUtc": self.dismissed_at_utc, "createdAtUtc": self.created_at_utc}


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
        return Task(task.id, task.title, task.notes, status, task.priority, task.due_at_utc, task.due_timezone, task.is_all_day,
                    now if status == "completed" else None, now if status == "cancelled" else None, outcome_note,
                    task.related_entity_type, task.related_entity_id, task.related_label, task.created_at_utc, now)
    return Task(task.id, task.title, task.notes, status, task.priority, task.due_at_utc, task.due_timezone, task.is_all_day,
                None, None, None, task.related_entity_type, task.related_entity_id, task.related_label, task.created_at_utc, now)


def is_terminal(task: Task) -> bool:
    return task.status in {"completed", "cancelled"}


def dismiss(reminder: TaskReminder, now: str) -> TaskReminder:
    if reminder.status != "pending":
        raise ValueError("Reminder is no longer pending.")
    return TaskReminder(reminder.id, reminder.task_id, reminder.remind_at_utc, "dismissed", None, now, reminder.created_at_utc)

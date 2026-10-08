"""Source-owned, recoverable lifecycle and reminder commands."""

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from json import loads
from uuid import UUID, uuid4

from app.modules.tasks.application.creation import canonical
from app.modules.tasks.application.editing import edit_task, normalize_changes
from app.modules.tasks.application.ports import TaskUnitOfWork
from app.modules.tasks.application.waiting import WaitingConflict, WaitingError, WaitingNotFound
from app.modules.tasks.domain.models import (
    ACTIVE_TASK_STATUSES,
    TaskReminder,
    dismiss,
    is_terminal,
    transition,
    waiting_facts,
    clear_waiting,
)

STATUSES = {
    "start": "in_progress",
    "reopen": "open",
    "complete": "completed",
    "cancel": "cancelled",
}


@dataclass(frozen=True)
class TaskMutationCommand:
    task_id: str
    action: str
    expected_revision: int
    idempotency_key: str
    outcome_note: str | None = None
    reminder_id: str | None = None
    remind_at_utc: str | None = None
    changes: tuple[tuple[str, object], ...] = ()
    confirmed: bool = False

    def __post_init__(self):
        for field in ("task_id", "idempotency_key", "reminder_id"):
            value = getattr(self, field)
            if field == "reminder_id" and value is None:
                continue
            try:
                if not isinstance(value, str) or str(UUID(value)) != value:
                    raise ValueError
            except (ValueError, TypeError, AttributeError) as error:
                raise WaitingError("Command identifiers must be canonical UUIDs.") from error
        if type(self.expected_revision) is not int or self.expected_revision < 1:
            raise WaitingError("expectedRevision must be a positive integer.")
        if self.action not in {
            *STATUSES,
            "add_reminder",
            "acknowledge",
            "dismiss",
            "edit",
            "delete",
        }:
            raise WaitingError("Unknown Task command.")
        confirmation_required = self.action in {
            "complete",
            "cancel",
            "reopen",
            "acknowledge",
            "dismiss",
            "delete",
        }
        if type(self.confirmed) is not bool or self.confirmed != confirmation_required:
            raise WaitingError("This Task action requires the appropriate explicit confirmation.")
        if self.action == "edit":
            object.__setattr__(self, "changes", normalize_changes(self.changes))
        elif self.changes:
            raise WaitingError("Only edits accept changed fields.")
        if self.outcome_note is not None and (
            self.action not in {"complete", "cancel"}
            or not isinstance(self.outcome_note, str)
            or not 1 <= len(self.outcome_note.strip()) <= 4000
        ):
            raise WaitingError("Outcome notes require complete/cancel and 1–4000 characters.")
        if self.outcome_note is not None:
            object.__setattr__(self, "outcome_note", self.outcome_note.strip())
        if (self.reminder_id is not None) != (self.action in {"acknowledge", "dismiss"}):
            raise WaitingError("Reminder identity is required only for reminder transitions.")
        if (self.remind_at_utc is not None) != (self.action == "add_reminder"):
            raise WaitingError("Reminder creation requires a timestamp.")
        if self.remind_at_utc is not None:
            try:
                instant = datetime.fromisoformat(self.remind_at_utc)
                if instant.tzinfo is None or instant.utcoffset() is None:
                    raise ValueError
            except (TypeError, ValueError) as error:
                raise WaitingError("Reminder timestamp must be offset-bearing.") from error
            object.__setattr__(self, "remind_at_utc", instant.astimezone(UTC).isoformat())

    def fingerprint(self):
        return sha256(canonical(asdict(self)).encode()).hexdigest()


@dataclass(frozen=True)
class TaskMutationOperation:
    id: str
    idempotency_key: str
    task_id: str
    action: str
    expected_revision: int
    resulting_revision: int
    request_fingerprint: str
    request_json: str
    result_json: str
    correlation_id: str
    created_at_utc: str

    def audit_snapshot(self):
        return {
            "taskId": self.task_id,
            "action": self.action,
            "expectedRevision": self.expected_revision,
            "revision": self.resulting_revision,
        }


class TaskMutationService:
    def __init__(self, unit_of_work: TaskUnitOfWork, *, now):
        self.unit_of_work = unit_of_work
        self.clock = now

    def operation(self, key: str):
        try:
            if str(UUID(key)) != key:
                raise ValueError
        except (ValueError, TypeError, AttributeError) as error:
            raise WaitingError("Operation key must be a canonical UUID.") from error
        operation = self.unit_of_work.mutation_operation(key)
        if operation is None:
            raise WaitingNotFound("Task operation was not found.")
        return loads(operation.result_json)

    def mutate(self, command: TaskMutationCommand):
        instant = self.clock()
        if (
            not isinstance(instant, datetime)
            or instant.tzinfo is None
            or instant.utcoffset() is None
        ):
            raise WaitingError("Task clock must return an aware instant.")
        instant = instant.astimezone(UTC)

        def write(tx):
            prior = tx.mutation_operation(command.idempotency_key)
            if prior:
                if prior.request_fingerprint != command.fingerprint():
                    raise WaitingConflict("Idempotency key was used with another command.")
                return loads(prior.result_json)
            task = tx.get_task(command.task_id)
            if task is None:
                raise WaitingNotFound("Task was not found.")
            if task.revision != command.expected_revision:
                raise WaitingConflict("Task changed. Refresh before retrying.", task.revision)
            stamp, correlation = instant.isoformat(), str(uuid4())
            reminder = None
            try:
                if command.action in STATUSES:
                    updated = transition(
                        task, STATUSES[command.action], command.outcome_note, stamp
                    )
                elif command.action == "edit":
                    updated = edit_task(task, command.changes, stamp)
                elif command.action == "delete":
                    if task.status != "open" or tx.has_non_dismissed_reminders(task.id):
                        raise WaitingConflict(
                            "Only open Tasks without non-dismissed reminders can be deleted.",
                            task.revision,
                        )
                    updated = replace(
                        clear_waiting(task, stamp) if task.waiting_for_kind else task,
                        deleted_at_utc=stamp,
                        updated_at_utc=stamp,
                        revision=task.revision + 1,
                    )
                else:
                    reminder = self._reminder_change(tx, task, command, stamp, correlation)
                    updated = replace(task, revision=task.revision + 1, updated_at_utc=stamp)
            except WaitingError:
                raise
            except ValueError as error:
                raise WaitingConflict(str(error), task.revision) from error
            if updated != task:
                tx.replace_task(updated)
                tx.record_change(
                    entity_type="task",
                    entity_id=task.id,
                    action=mutation_action(command.action),
                    before=task.to_dict(),
                    after=updated.to_dict(),
                    reason="task_mutation_command",
                    correlation_id=correlation,
                )
            if (command.action in STATUSES and is_terminal(updated)) or command.action == "delete":
                self._terminal_effects(tx, task, updated, stamp, correlation)
            operation_id = str(uuid4())
            result = {
                "task": {**updated.to_dict(), **waiting_facts(updated, instant)},
                "reminder": reminder.to_dict() if reminder else None,
                "revision": updated.revision,
                "operationId": operation_id,
            }
            operation = TaskMutationOperation(
                operation_id,
                command.idempotency_key,
                task.id,
                command.action,
                task.revision,
                updated.revision,
                command.fingerprint(),
                canonical(asdict(command)),
                canonical(result),
                correlation,
                stamp,
            )
            tx.insert_mutation_operation(operation)
            tx.record_change(
                entity_type="task_mutation_operation",
                entity_id=operation.id,
                action="recorded",
                before=None,
                after=operation.audit_snapshot(),
                reason="task_command_recorded",
                correlation_id=correlation,
            )
            return result

        return self.unit_of_work.write_waiting(write)

    @staticmethod
    def _reminder_change(tx, task, command, stamp, correlation):
        if task.status not in ACTIVE_TASK_STATUSES:
            raise ValueError("Reminder commands require an active Task.")
        before = None
        if command.action == "add_reminder":
            reminder = TaskReminder(
                str(uuid4()), task.id, command.remind_at_utc, "pending", None, None, stamp
            )
            tx.insert_reminder(reminder)
        else:
            before = tx.get_reminder(task.id, command.reminder_id)
            if before is None:
                raise WaitingNotFound("Reminder was not found.")
            if before.status != "pending":
                raise ValueError("Reminder is no longer pending.")
            reminder = (
                dismiss(before, stamp)
                if command.action == "dismiss"
                else replace(
                    before,
                    status="acknowledged",
                    acknowledged_at_utc=stamp,
                )
            )
            tx.replace_reminder(reminder)
        tx.record_change(
            entity_type="task_reminder",
            entity_id=reminder.id,
            action="created" if before is None else "status_changed",
            before=before.to_dict() if before else None,
            after=reminder.to_dict(),
            reason="task_mutation_command",
            correlation_id=correlation,
        )
        return reminder

    @staticmethod
    def _terminal_effects(tx, before, updated, stamp, correlation):
        if before.waiting_for_kind:
            tx.record_change(
                entity_type="task",
                entity_id=updated.id,
                action="task_waiting_cleared",
                before=before.to_dict(),
                after=updated.to_dict(),
                reason="task_deleted"
                if updated.deleted_at_utc
                else "task_completed"
                if updated.status == "completed"
                else "task_cancelled",
                correlation_id=correlation,
            )
        if updated.deleted_at_utc:
            return
        for reminder in tx.pending_reminders(updated.id):
            changed = dismiss(reminder, stamp)
            tx.replace_reminder(changed)
            tx.record_change(
                entity_type="task_reminder",
                entity_id=changed.id,
                action="dismissed",
                before=reminder.to_dict(),
                after=changed.to_dict(),
                reason="task_updated",
                correlation_id=correlation,
            )


def mutation_action(action):
    if action in STATUSES:
        return "status_changed"
    return {"edit": "updated", "delete": "deleted"}.get(action, "reminder_changed")

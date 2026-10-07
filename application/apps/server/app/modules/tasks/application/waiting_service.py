"""Atomic waiting mutations and revision-bound, snapshot follow-up reads."""

from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from json import dumps, loads
from uuid import UUID, uuid4

from app.modules.tasks.application.ports import TaskUnitOfWork
from app.modules.tasks.application.waiting import (
    FollowUpQuery,
    WaitingCommand,
    WaitingConflict,
    WaitingError,
    WaitingNotFound,
    WaitingOperation,
    WaitingUnavailable,
)
from app.modules.tasks.domain.models import (
    ACTIVE_TASK_STATUSES,
    clear_waiting,
    follow_up_rank,
    waiting_facts,
)


def task_view(task, now):
    return {**task.to_dict(), **waiting_facts(task, now)}


class TaskWaitingService:
    def __init__(
        self,
        unit_of_work: TaskUnitOfWork,
        *,
        read_identity: Callable[[], tuple[str, str]],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.unit_of_work = unit_of_work
        self.read_identity = read_identity
        self.clock = now

    def _instant(self):
        instant = self.clock()
        if (
            not isinstance(instant, datetime)
            or instant.tzinfo is None
            or instant.utcoffset() is None
        ):
            raise WaitingError("Task clock must return an aware instant.")
        return instant.astimezone(UTC)

    def _identity(self):
        workspace, epoch = self.read_identity()
        try:
            UUID(workspace)
            UUID(epoch)
        except (ValueError, TypeError, AttributeError) as error:
            raise WaitingUnavailable("Workspace is unavailable.") from error
        return workspace, epoch

    def mutate(self, command: WaitingCommand) -> dict:
        self._identity()
        now = self._instant()
        fingerprint = command.fingerprint()

        def change(tx):
            retained = tx.waiting_operation(command.idempotency_key)
            if retained:
                if retained.request_fingerprint != fingerprint:
                    raise WaitingConflict("Idempotency key was used with another payload.")
                return loads(retained.result_json)
            task = tx.get_task(command.task_id)
            if task is None:
                raise WaitingNotFound("Task was not found.")
            if task.revision != command.expected_revision:
                raise WaitingConflict("Task has changed. Refresh before retrying.", task.revision)
            if task.status not in ACTIVE_TASK_STATUSES:
                raise WaitingConflict(
                    "Only active tasks may change waiting context.", task.revision
                )
            stamp = now.isoformat()
            if command.action == "set":
                business = (command.kind, command.label, command.follow_up_at, command.timezone)
                existing = (
                    task.waiting_for_kind,
                    task.waiting_for_label,
                    task.follow_up_at_utc,
                    task.follow_up_timezone,
                )
                updated = (
                    task
                    if business == existing
                    else replace(
                        task,
                        waiting_for_kind=command.kind,
                        waiting_for_label=command.label,
                        follow_up_at_utc=command.follow_up_at,
                        follow_up_timezone=command.timezone,
                        waiting_set_at_utc=stamp,
                        waiting_cleared_at_utc=None,
                    )
                )
                action, reason = "task_waiting_set", "waiting_context_set"
            elif command.action == "clear":
                updated = clear_waiting(task, stamp) if task.waiting_for_kind else task
                action, reason = "task_waiting_cleared", "waiting_cleared"
            else:
                if not task.waiting_for_kind:
                    raise WaitingConflict("Task is not waiting.", task.revision)
                updated = replace(
                    task, follow_up_at_utc=command.follow_up_at, follow_up_timezone=command.timezone
                )
                action = "task_follow_up_rescheduled"
                reason = "follow_up_removed" if command.clear_follow_up else "follow_up_rescheduled"
            correlation, operation_id = str(uuid4()), str(uuid4())
            if updated != task:
                updated = replace(updated, revision=task.revision + 1, updated_at_utc=stamp)
                tx.replace_task(updated)
                tx.record_change(
                    entity_type="task",
                    entity_id=task.id,
                    action=action,
                    before=task.to_dict(),
                    after=updated.to_dict(),
                    reason=reason,
                    correlation_id=correlation,
                )
            result = {**task_view(updated, now), "operationId": operation_id}
            receipt = WaitingOperation(
                id=operation_id,
                idempotency_key=command.idempotency_key,
                task_id=task.id,
                action=command.action,
                request_fingerprint=fingerprint,
                expected_revision=command.expected_revision,
                resulting_revision=updated.revision,
                result_json=dumps(result, sort_keys=True, separators=(",", ":")),
                correlation_id=correlation,
                created_at_utc=stamp,
                request_json=dumps(command.__dict__, sort_keys=True, separators=(",", ":")),
            )
            tx.insert_waiting_operation(receipt)
            tx.record_change(
                entity_type="task_waiting_operation",
                entity_id=operation_id,
                action="recorded",
                before=None,
                after={
                    "taskId": task.id,
                    "action": command.action,
                    "revision": updated.revision,
                    "requestFingerprint": fingerprint,
                },
                reason="waiting_operation_recorded",
                correlation_id=correlation,
            )
            return result

        return self.unit_of_work.write_waiting(change)

    def operation(self, key: str):
        self._identity()
        try:
            key = str(UUID(key))
        except (ValueError, TypeError, AttributeError) as error:
            raise WaitingError("Operation key must be a UUID.") from error
        receipt = self.unit_of_work.waiting_operation(key)
        if receipt is None:
            raise WaitingNotFound("Operation was not found.")
        return loads(receipt.result_json)

    def follow_ups(self, query: FollowUpQuery):
        workspace, epoch = self._identity()
        evaluated = self._instant()

        def read(tx):
            marker = tx.marker()
            now, after = evaluated, None
            if query.cursor:
                try:
                    cursor = loads(urlsafe_b64decode(query.cursor.encode()))
                    if set(cursor) != {
                        "endpoint",
                        "workspace",
                        "epoch",
                        "filters",
                        "marker",
                        "asOf",
                        "after",
                    }:
                        raise ValueError
                    now = datetime.fromisoformat(cursor["asOf"])
                    if now.tzinfo is None or now.utcoffset() != timedelta(0):
                        raise ValueError
                    after = tuple(cursor["after"])
                    if len(after) != 3 or type(after[0]) is not int or after[0] not in range(5):
                        raise ValueError
                    if not isinstance(after[1], str):
                        raise ValueError
                    UUID(after[2])
                except (ValueError, TypeError, KeyError, UnicodeDecodeError) as error:
                    raise WaitingError("Invalid follow-up cursor.") from error
                if (
                    cursor["endpoint"] != "task-follow-ups-v1"
                    or cursor["workspace"] != workspace
                    or cursor["epoch"] != epoch
                    or cursor["filters"] != query.filters()
                    or cursor["marker"] != marker
                    or not timedelta(0) <= evaluated - now <= timedelta(minutes=15)
                ):
                    raise WaitingConflict(
                        "Follow-up continuation changed or expired; restart with the same filters."
                    )
            total, tasks = tx.page(query, now, after)
            next_cursor = None
            items = tasks[: query.limit]
            if len(tasks) > query.limit:
                last = items[-1]
                values = {
                    "endpoint": "task-follow-ups-v1",
                    "workspace": workspace,
                    "epoch": epoch,
                    "filters": query.filters(),
                    "marker": marker,
                    "asOf": now.isoformat(),
                    "after": [follow_up_rank(last, now), last.follow_up_at_utc or "", last.id],
                }
                next_cursor = urlsafe_b64encode(dumps(values, sort_keys=True).encode()).decode()
            return {
                "items": [task_view(task, now) for task in items],
                "matchingTotal": total,
                "nextCursor": next_cursor,
                "asOf": now.isoformat(),
                "evaluatedAt": evaluated.isoformat(),
                "filters": query.filters(),
            }

        return self.unit_of_work.read_follow_ups(read)

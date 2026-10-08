"""Validate immutable Task mutation receipts against correlated domain history."""

from dataclasses import asdict, fields, replace
from json import loads

from sqlalchemy import text

from app.modules.tasks.application.creation import canonical
from app.modules.tasks.application.mutations import (
    STATUSES,
    TaskMutationCommand,
    TaskMutationOperation,
    mutation_action,
)
from app.modules.tasks.application.editing import edit_task
from app.modules.tasks.domain.models import (
    Task,
    TaskReminder,
    clear_waiting,
    dismiss,
    transition,
    waiting_facts,
)
from app.modules.tasks.infrastructure.sqlalchemy_models import (
    TaskMutationOperationModel,
    TaskReminderModel,
)
from app.platform.migration_errors import MigrationSchemaError


def _task(snapshot):
    names = {}
    for field in fields(Task):
        first, *rest = field.name.split("_")
        names[field.name] = first + "".join(part.title() for part in rest)
    names["follow_up_at_utc"] = "followUpAt"
    return Task(**{name: snapshot[key] for name, key in names.items()})


def _reminder(snapshot):
    return TaskReminder(
        snapshot["id"],
        snapshot["taskId"],
        snapshot["remindAtUtc"],
        snapshot["status"],
        snapshot["acknowledgedAtUtc"],
        snapshot["dismissedAtUtc"],
        snapshot["createdAtUtc"],
    )


def validate_mutations(connection, uuid_validator, utc_validator):
    try:
        operations = (
            connection.execute(TaskMutationOperationModel.__table__.select()).mappings().all()
        )
        for row in operations:
            _validate_operation(connection, row, uuid_validator, utc_validator)
        by_id = {row["id"]: row for row in operations}
        correlations = {(row["task_id"], row["correlation_id"]) for row in operations}
        for audit in connection.execute(
            text(
                "SELECT * FROM audit_events WHERE entity_type='task_mutation_operation' "
                "OR (entity_type='task' AND reason='task_mutation_command')"
            )
        ).mappings():
            if audit["entity_type"] == "task_mutation_operation":
                row = by_id.get(audit["entity_id"])
                if row is None or row["correlation_id"] != audit["correlation_id"]:
                    raise ValueError("Orphaned Task operation audit.")
            elif (audit["entity_id"], audit["correlation_id"]) not in correlations:
                raise ValueError("Task command lost its receipt.")
    except (ValueError, TypeError, KeyError) as error:
        raise MigrationSchemaError("Retained Task mutation data is invalid.") from error


def _validate_operation(connection, row, uuid_validator, utc_validator):
    for name in ("id", "task_id", "idempotency_key", "correlation_id"):
        uuid_validator(row[name])
    instant = utc_validator(row["created_at_utc"])
    command = TaskMutationCommand(**loads(row["request_json"]))
    if (
        canonical(asdict(command)) != row["request_json"]
        or command.fingerprint() != row["request_fingerprint"]
        or any(
            getattr(command, key) != row[key]
            for key in ("task_id", "action", "expected_revision", "idempotency_key")
        )
        or row["resulting_revision"] not in {row["expected_revision"], row["expected_revision"] + 1}
    ):
        raise ValueError("Task command identity is invalid.")
    events = (
        connection.execute(
            text(
                "SELECT rowid AS sequence, * FROM audit_events WHERE correlation_id=:correlation ORDER BY rowid"
            ),
            {"correlation": row["correlation_id"]},
        )
        .mappings()
        .all()
    )
    operation_events = [
        event for event in events if event["entity_type"] == "task_mutation_operation"
    ]
    if len(operation_events) != 1:
        raise ValueError("Missing operation audit.")
    audit = operation_events[0]
    if (
        audit["entity_id"] != row["id"]
        or audit["action"] != "recorded"
        or audit["before_snapshot"] is not None
        or loads(audit["after_snapshot"]) != TaskMutationOperation(**row).audit_snapshot()
    ):
        raise ValueError("Operation audit differs from receipt.")
    if command.action == "edit" and row["resulting_revision"] == row["expected_revision"]:
        _validate_unchanged_edit(connection, row, command, events, instant)
        return
    action = mutation_action(command.action)
    changes = [
        event for event in events if event["entity_type"] == "task" and event["action"] == action
    ]
    if len(changes) != 1 or changes[0]["entity_id"] != row["task_id"]:
        raise ValueError("Missing correlated Task change.")
    before, after = (
        _task(loads(changes[0]["before_snapshot"])),
        _task(loads(changes[0]["after_snapshot"])),
    )
    stamp = row["created_at_utc"]
    if before.revision != row["expected_revision"]:
        raise ValueError("Invalid command revision.")
    if before.deleted_at_utc:
        raise ValueError("Command changed a deleted Task.")
    if command.action in STATUSES:
        expected = transition(before, STATUSES[command.action], command.outcome_note, stamp)
    elif command.action == "edit":
        expected = edit_task(before, command.changes, stamp)
    elif command.action == "delete":
        if before.status != "open":
            raise ValueError("Only open Tasks can be deleted.")
        expected = replace(
            clear_waiting(before, stamp) if before.waiting_for_kind else before,
            revision=before.revision + 1,
            updated_at_utc=stamp,
            deleted_at_utc=stamp,
        )
    else:
        expected = replace(before, revision=before.revision + 1, updated_at_utc=stamp)
    if after != expected:
        raise ValueError("Task command did not apply its declared transition.")
    result = loads(row["result_json"])
    expected_result = {
        "task": {**after.to_dict(), **waiting_facts(after, instant)},
        "reminder": None,
        "revision": after.revision,
        "operationId": row["id"],
    }
    if command.action in {"add_reminder", "acknowledge", "dismiss"}:
        reminder_events = [event for event in events if event["entity_type"] == "task_reminder"]
        if len(reminder_events) != 1 or before.status not in {"open", "in_progress"}:
            raise ValueError("Invalid reminder command history.")
        event = reminder_events[0]
        reminder = _reminder(loads(event["after_snapshot"]))
        uuid_validator(reminder.id)
        utc_validator(reminder.remind_at_utc)
        if command.action == "add_reminder":
            expected_reminder = TaskReminder(
                reminder.id, before.id, command.remind_at_utc, "pending", None, None, stamp
            )
            if event["before_snapshot"] is not None or event["action"] != "created":
                raise ValueError("Invalid reminder creation.")
        else:
            previous = _reminder(loads(event["before_snapshot"]))
            if (
                previous.id != command.reminder_id
                or previous.status != "pending"
                or event["action"] != "status_changed"
            ):
                raise ValueError("Invalid reminder transition.")
            expected_reminder = (
                dismiss(previous, stamp)
                if command.action == "dismiss"
                else replace(
                    previous,
                    status="acknowledged",
                    acknowledged_at_utc=stamp,
                )
            )
        if (
            reminder != expected_reminder
            or reminder.task_id != before.id
            or event["entity_id"] != reminder.id
        ):
            raise ValueError("Reminder audit differs from command.")
        expected_result["reminder"] = reminder.to_dict()
        _validate_reminder_history(connection, reminder.id)
        if len(events) != 3:
            raise ValueError("Unexpected reminder command audits.")
    elif after.status in {"completed", "cancelled"} or command.action == "delete":
        _validate_terminal_effects(connection, before, after, changes[0], events)
    elif len(events) != 2:
        raise ValueError("Unexpected lifecycle command audits.")
    if result != expected_result or canonical(result) != row["result_json"]:
        raise ValueError("Task command replay differs from its original state.")
    current_revision = connection.scalar(
        text("SELECT revision FROM tasks WHERE id=:id"), {"id": before.id}
    )
    if current_revision is None or current_revision < after.revision:
        raise ValueError("Task command lost its resulting Task.")


def _validate_reminder_history(connection, reminder_id):
    retained = (
        connection.execute(
            TaskReminderModel.__table__.select().where(TaskReminderModel.id == reminder_id)
        )
        .mappings()
        .first()
    )
    if retained is None:
        raise ValueError("Reminder command lost its Reminder.")
    history = (
        connection.execute(
            text(
                "SELECT before_snapshot, after_snapshot FROM audit_events "
                "WHERE entity_type='task_reminder' AND entity_id=:id ORDER BY rowid"
            ),
            {"id": reminder_id},
        )
        .mappings()
        .all()
    )
    previous = None
    for event in history:
        before = _reminder(loads(event["before_snapshot"])) if event["before_snapshot"] else None
        after = _reminder(loads(event["after_snapshot"]))
        if before != previous:
            raise ValueError("Reminder history is discontinuous.")
        previous = after
    if previous != TaskReminder(**retained):
        raise ValueError("Reminder state differs from retained history.")


def _validate_unchanged_edit(connection, row, command, events, instant):
    result = loads(row["result_json"])
    task = _task(result["task"])
    if (
        len(events) != 1
        or task.deleted_at_utc
        or task.revision != command.expected_revision
        or edit_task(task, command.changes, row["created_at_utc"]) != task
    ):
        raise ValueError("Invalid unchanged edit result.")
    historical = connection.execute(
        text(
            "SELECT after_snapshot FROM audit_events WHERE entity_type='task' AND entity_id=:task "
            "AND rowid < :sequence AND action IN ('created','status_changed','updated','reminder_changed','task_waiting_set','task_waiting_cleared','task_follow_up_rescheduled') ORDER BY rowid DESC LIMIT 1"
        ),
        {"task": task.id, "sequence": events[0]["sequence"]},
    ).scalar()
    expected = {
        "task": {**task.to_dict(), **waiting_facts(task, instant)},
        "reminder": None,
        "revision": task.revision,
        "operationId": row["id"],
    }
    if (
        historical is None
        or loads(historical) != task.to_dict()
        or result != expected
        or canonical(result) != row["result_json"]
    ):
        raise ValueError("Unchanged edit differs from retained history.")


def _validate_terminal_effects(connection, before, after, change, events):
    history = connection.execute(
        text(
            "SELECT after_snapshot FROM (SELECT after_snapshot, "
            "row_number() OVER (PARTITION BY entity_id ORDER BY rowid DESC) AS position "
            "FROM audit_events WHERE entity_type='task_reminder' AND rowid < :sequence "
            "AND json_extract(after_snapshot, '$.taskId')=:task) WHERE position=1"
        ),
        {"sequence": change["sequence"], "task": before.id},
    ).scalars()
    pending = {
        reminder.id: reminder
        for value in history
        if (reminder := _reminder(loads(value))).status == "pending"
    }
    if after.deleted_at_utc:
        retained_history = connection.execute(
            text(
                "SELECT after_snapshot FROM (SELECT after_snapshot, row_number() OVER (PARTITION BY entity_id ORDER BY rowid DESC) AS position "
                "FROM audit_events WHERE entity_type='task_reminder' AND rowid < :sequence AND json_extract(after_snapshot, '$.taskId')=:task) WHERE position=1"
            ),
            {"sequence": change["sequence"], "task": before.id},
        ).scalars()
        if any(_reminder(loads(value)).status != "dismissed" for value in retained_history):
            raise ValueError("Deleted Task retained a non-dismissed Reminder.")
    dismissals = [event for event in events if event["entity_type"] == "task_reminder"]
    if len(dismissals) != len(pending):
        raise ValueError("Terminal command lost its reminder effects.")
    for event in dismissals:
        reminder = pending.pop(event["entity_id"], None)
        if (
            reminder is None
            or event["action"] != "dismissed"
            or loads(event["before_snapshot"]) != reminder.to_dict()
            or loads(event["after_snapshot"]) != dismiss(reminder, after.updated_at_utc).to_dict()
        ):
            raise ValueError("Invalid terminal reminder effect.")
        _validate_reminder_history(connection, reminder.id)
    clears = [
        event
        for event in events
        if event["entity_type"] == "task" and event["action"] == "task_waiting_cleared"
    ]
    if len(clears) != int(before.waiting_for_kind is not None):
        raise ValueError("Terminal command lost its waiting effect.")
    if len(events) != 2 + len(dismissals) + len(clears):
        raise ValueError("Unexpected terminal command audit.")

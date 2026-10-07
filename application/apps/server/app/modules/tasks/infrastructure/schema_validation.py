"""Exact TASK schema and retained waiting/audit/receipt integrity."""

import json
import re
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, text

from app.modules.tasks.infrastructure.sqlalchemy_models import (
    TaskModel,
    TaskReminderModel,
    TaskWaitingOperationModel,
)
from app.modules.tasks.application.waiting import WaitingCommand
from app.modules.tasks.domain.models import Task, waiting_facts
from app.platform.migration_errors import MigrationSchemaError


def _normalized(value):
    return "".join(str(value).lower().replace("(", "").replace(")", "").split())


def validate_task_schema(connection):
    inspector = inspect(connection)
    for model in (TaskModel, TaskReminderModel, TaskWaitingOperationModel):
        table = model.__table__
        if not inspector.has_table(table.name):
            raise MigrationSchemaError("Task schema is incomplete.")
        columns = inspector.get_columns(table.name)
        if {c["name"] for c in columns} != set(table.columns.keys()) or any(
            str(c["type"]) != str(table.c[c["name"]].type)
            or (not c["primary_key"] and bool(c["nullable"]) != table.c[c["name"]].nullable)
            for c in columns
        ):
            raise MigrationSchemaError("Task columns are incompatible.")
        if inspector.get_pk_constraint(table.name)["constrained_columns"] != ["id"]:
            raise MigrationSchemaError("Task primary key is incompatible.")
        checks = {_normalized(c["sqltext"]) for c in inspector.get_check_constraints(table.name)}
        if checks != {
            _normalized(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)
        }:
            raise MigrationSchemaError("Task checks are incompatible.")
        indexes = {
            (i["name"], tuple(i["column_names"]), bool(i["unique"]))
            for i in inspector.get_indexes(table.name)
        }
        if indexes != {
            (i.name, tuple(c.name for c in i.columns), bool(i.unique)) for i in table.indexes
        }:
            raise MigrationSchemaError("Task indexes are incompatible.")
        uniques = {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table.name)}
        if uniques != {
            tuple(col.name for col in c.columns)
            for c in table.constraints
            if isinstance(c, UniqueConstraint)
        }:
            raise MigrationSchemaError("Task uniqueness is incompatible.")
        foreign = {
            (tuple(c["constrained_columns"]), c["referred_table"], tuple(c["referred_columns"]))
            for c in inspector.get_foreign_keys(table.name)
        }
        expected = {
            ((fk.parent.name,), fk.column.table.name, (fk.column.name,))
            for fk in table.foreign_keys
        }
        if foreign != expected:
            raise MigrationSchemaError("Task foreign keys are incompatible.")
    triggers = dict(
        connection.execute(
            text(
                "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='task_waiting_operations'"
            )
        ).all()
    )
    for action in ("UPDATE", "DELETE"):
        name = f"task_waiting_operations_no_{action.lower()}"
        expected = f"CREATE TRIGGER {name} BEFORE {action} ON task_waiting_operations BEGIN SELECT RAISE(ABORT, 'task waiting operations are append-only'); END"
        if _normalized(triggers.get(name)) != _normalized(expected):
            raise MigrationSchemaError("Task operation immutability is incompatible.")
    if len(triggers) != 2:
        raise MigrationSchemaError("Unexpected Task operation triggers.")
    validate_task_data(connection)


def _uuid(value):
    if str(UUID(value)) != value:
        raise ValueError("Noncanonical UUID.")


def _utc(value):
    parsed = datetime.fromisoformat(value)
    if (
        parsed.tzinfo is None
        or parsed.utcoffset().total_seconds() != 0
        or parsed.astimezone(UTC).isoformat() != value
    ):
        raise ValueError("Noncanonical UTC instant.")
    return parsed


WAITING_FIELDS = {
    "waiting_for_kind": "waitingForKind",
    "waiting_for_label": "waitingForLabel",
    "follow_up_at_utc": "followUpAt",
    "follow_up_timezone": "followUpTimezone",
    "waiting_set_at_utc": "waitingSetAtUtc",
    "waiting_cleared_at_utc": "waitingClearedAtUtc",
}
WAITING_ACTIONS = {
    "set": "task_waiting_set",
    "clear": "task_waiting_cleared",
    "reschedule": "task_follow_up_rescheduled",
}


def validate_task_data(connection):
    try:
        tasks = {
            row["id"]: row for row in connection.execute(TaskModel.__table__.select()).mappings()
        }
        for row in tasks.values():
            _uuid(row["id"])
            if type(row["revision"]) is not int or row["revision"] < 1:
                raise ValueError("Invalid revision.")
            for key in (
                "created_at_utc",
                "updated_at_utc",
                "completed_at_utc",
                "cancelled_at_utc",
                "due_at_utc",
                "waiting_set_at_utc",
                "waiting_cleared_at_utc",
                "follow_up_at_utc",
            ):
                if row[key] is not None:
                    _utc(row[key])
            if _utc(row["updated_at_utc"]) < _utc(row["created_at_utc"]):
                raise ValueError("Invalid task timestamps.")
            for field in ("due_timezone", "follow_up_timezone"):
                if row[field] is not None:
                    ZoneInfo(row[field])
            waiting = row["waiting_for_kind"] is not None
            if waiting:
                if row["status"] not in {"open", "in_progress"} or row["waiting_for_kind"] not in {
                    "person",
                    "organization",
                    "event",
                    "other",
                }:
                    raise ValueError("Invalid waiting lifecycle.")
                label = row["waiting_for_label"]
                if (
                    not isinstance(label, str)
                    or label != label.strip()
                    or not 1 <= len(label) <= 255
                    or row["waiting_set_at_utc"] is None
                    or row["waiting_cleared_at_utc"] is not None
                ):
                    raise ValueError("Invalid waiting episode.")
            elif any(
                row[key] is not None
                for key in (
                    "waiting_for_label",
                    "waiting_set_at_utc",
                    "follow_up_at_utc",
                    "follow_up_timezone",
                )
            ):
                raise ValueError("Inactive waiting contains active fields.")
            if (row["follow_up_at_utc"] is None) != (row["follow_up_timezone"] is None):
                raise ValueError("Invalid follow-up pair.")
            events = (
                connection.execute(
                    text(
                        "SELECT * FROM audit_events WHERE entity_type='task' AND entity_id=:id ORDER BY rowid"
                    ),
                    {"id": row["id"]},
                )
                .mappings()
                .all()
            )
            _validate_task_history(row, events)
            waiting_events = [
                event for event in events if event["action"] in WAITING_ACTIONS.values()
            ]
            if waiting_events:
                latest = json.loads(waiting_events[-1]["after_snapshot"])
                if any(latest.get(api) != row[stored] for stored, api in WAITING_FIELDS.items()):
                    raise ValueError("Waiting history differs from retained state.")
            elif waiting or row["waiting_cleared_at_utc"]:
                raise ValueError("Missing waiting history.")
        operations = (
            connection.execute(TaskWaitingOperationModel.__table__.select()).mappings().all()
        )
        for row in operations:
            for key in ("id", "idempotency_key", "task_id", "correlation_id"):
                _uuid(row[key])
            _utc(row["created_at_utc"])
            if not re.fullmatch("[0-9a-f]{64}", row["request_fingerprint"]):
                raise ValueError("Invalid operation fingerprint.")
            command = WaitingCommand(**json.loads(row["request_json"]))
            if (
                json.dumps(command.__dict__, sort_keys=True, separators=(",", ":"))
                != row["request_json"]
            ):
                raise ValueError("Operation request is not canonical.")
            if (
                command.fingerprint() != row["request_fingerprint"]
                or command.task_id != row["task_id"]
                or command.action != row["action"]
                or command.idempotency_key != row["idempotency_key"]
                or command.expected_revision != row["expected_revision"]
            ):
                raise ValueError("Invalid retained command.")
            result = json.loads(row["result_json"])
            if json.dumps(result, sort_keys=True, separators=(",", ":")) != row["result_json"]:
                raise ValueError("Operation result is not canonical.")
            if (
                row["task_id"] not in tasks
                or result["id"] != row["task_id"]
                or result["operationId"] != row["id"]
                or result["revision"] != row["resulting_revision"]
                or row["action"] not in WAITING_ACTIONS
                or row["resulting_revision"]
                not in {row["expected_revision"], row["expected_revision"] + 1}
                or row["resulting_revision"] > tasks[row["task_id"]]["revision"]
            ):
                raise ValueError("Invalid operation result.")
            _utc(result["asOf"])
            historical = (
                connection.execute(
                    text(
                        "SELECT after_snapshot FROM audit_events WHERE entity_type='task' AND entity_id=:id ORDER BY rowid DESC"
                    ),
                    {"id": row["task_id"]},
                )
                .scalars()
                .all()
            )
            state = next(
                (
                    snapshot
                    for value in historical
                    if (snapshot := json.loads(value)).get("revision") == row["resulting_revision"]
                ),
                None,
            )
            if state is None:
                raise ValueError("Operation has no retained task state.")
            state_task = Task(
                **{
                    key: state[api]
                    for key, api in (
                        ("id", "id"),
                        ("title", "title"),
                        ("notes", "notes"),
                        ("status", "status"),
                        ("priority", "priority"),
                        ("due_at_utc", "dueAtUtc"),
                        ("due_timezone", "dueTimezone"),
                        ("is_all_day", "isAllDay"),
                        ("completed_at_utc", "completedAtUtc"),
                        ("cancelled_at_utc", "cancelledAtUtc"),
                        ("outcome_note", "outcomeNote"),
                        ("related_entity_type", "relatedEntityType"),
                        ("related_entity_id", "relatedEntityId"),
                        ("related_label", "relatedLabel"),
                        ("created_at_utc", "createdAtUtc"),
                        ("updated_at_utc", "updatedAtUtc"),
                        ("revision", "revision"),
                        *WAITING_FIELDS.items(),
                    )
                }
            )
            expected_result = {
                **state,
                **waiting_facts(state_task, _utc(result["asOf"])),
                "operationId": row["id"],
            }
            if result != expected_result:
                raise ValueError("Operation response differs from retained task facts.")
            audits = (
                connection.execute(
                    text(
                        "SELECT * FROM audit_events WHERE entity_type='task_waiting_operation' AND entity_id=:id"
                    ),
                    {"id": row["id"]},
                )
                .mappings()
                .all()
            )
            if (
                len(audits) != 1
                or audits[0]["action"] != "recorded"
                or audits[0]["correlation_id"] != row["correlation_id"]
            ):
                raise ValueError("Missing operation audit.")
            audit_result = json.loads(audits[0]["after_snapshot"])
            if audit_result != {
                "taskId": row["task_id"],
                "action": row["action"],
                "revision": row["resulting_revision"],
                "requestFingerprint": row["request_fingerprint"],
            }:
                raise ValueError("Operation audit differs from receipt.")
            if result["asOf"] != row["created_at_utc"]:
                raise ValueError("Operation instant differs from result.")
            if row["resulting_revision"] > row["expected_revision"]:
                changes = (
                    connection.execute(
                        text(
                            "SELECT * FROM audit_events WHERE entity_type='task' AND entity_id=:id AND correlation_id=:correlation AND action=:action"
                        ),
                        {
                            "id": row["task_id"],
                            "correlation": row["correlation_id"],
                            "action": WAITING_ACTIONS[row["action"]],
                        },
                    )
                    .mappings()
                    .all()
                )
                if (
                    len(changes) != 1
                    or json.loads(changes[0]["after_snapshot"])["revision"]
                    != row["resulting_revision"]
                ):
                    raise ValueError("Missing correlated waiting mutation.")
        _validate_receipt_references(connection, operations)
    except (ValueError, TypeError, KeyError) as error:
        raise MigrationSchemaError("Retained Task waiting data is invalid.") from error


def _validate_receipt_references(connection, operations):
    """Every operation audit and explicit change must retain its replay receipt."""
    by_id = {operation["id"]: operation for operation in operations}
    by_change = {}
    for operation in operations:
        if operation["resulting_revision"] == operation["expected_revision"]:
            continue
        key = (
            operation["task_id"],
            operation["correlation_id"],
            WAITING_ACTIONS[operation["action"]],
        )
        if key in by_change:
            raise ValueError("Waiting mutation has multiple operation receipts.")
        by_change[key] = operation
    events = (
        connection.execute(
            text(
                "SELECT * FROM audit_events WHERE entity_type='task_waiting_operation' "
                "OR (entity_type='task' AND action IN "
                "('task_waiting_set','task_waiting_cleared','task_follow_up_rescheduled','status_changed'))"
            )
        )
        .mappings()
        .all()
    )
    lifecycle_by_change = {}
    for event in events:
        if event["entity_type"] == "task" and event["action"] == "status_changed":
            key = (event["entity_id"], event["correlation_id"])
            lifecycle_by_change.setdefault(key, []).append(event)
    for event in events:
        if event["entity_type"] == "task_waiting_operation":
            operation = by_id.get(event["entity_id"])
            if (
                operation is None
                or event["action"] != "recorded"
                or event["correlation_id"] != operation["correlation_id"]
            ):
                raise ValueError("Operation audit has no matching retained receipt.")
        elif event["action"] in WAITING_ACTIONS.values():
            if event["action"] == "task_waiting_cleared" and event["reason"] in {
                "task_completed",
                "task_cancelled",
            }:
                lifecycle = lifecycle_by_change.get(
                    (event["entity_id"], event["correlation_id"]), []
                )
                expected_status = (
                    "completed" if event["reason"] == "task_completed" else "cancelled"
                )
                if (
                    len(lifecycle) != 1
                    or lifecycle[0]["before_snapshot"] != event["before_snapshot"]
                    or lifecycle[0]["after_snapshot"] != event["after_snapshot"]
                    or json.loads(event["after_snapshot"])["status"] != expected_status
                ):
                    raise ValueError("Automatic waiting clear lacks its terminal transition.")
                continue
            operation = by_change.get(
                (event["entity_id"], event["correlation_id"], event["action"])
            )
            if (
                operation is None
                or json.loads(event["before_snapshot"])["revision"]
                != operation["expected_revision"]
                or json.loads(event["after_snapshot"])["revision"]
                != operation["resulting_revision"]
            ):
                raise ValueError("Explicit waiting mutation has no matching retained receipt.")


def _validate_task_history(row, events):
    previous = None
    previous_correlation = None
    for event in events:
        if event["action"] not in {"created", "status_changed", *WAITING_ACTIONS.values()}:
            continue
        before = json.loads(event["before_snapshot"]) if event["before_snapshot"] else None
        after = json.loads(event["after_snapshot"])
        if event["action"] == "created":
            if previous is not None or before is not None or after["revision"] != 1:
                raise ValueError("Invalid task creation history.")
        elif event["action"] == "task_waiting_cleared" and event["reason"] in {
            "task_completed",
            "task_cancelled",
        }:
            if previous != after or previous_correlation != event["correlation_id"]:
                raise ValueError("Automatic clearing is not correlated with lifecycle.")
        elif previous != before or after["revision"] != before["revision"] + 1:
            raise ValueError("Invalid task mutation chain.")
        previous, previous_correlation = after, event["correlation_id"]
    if previous is not None and previous != Task(**row).to_dict():
        raise ValueError("Task state differs from mutation history.")
    if previous is None and row["revision"] > 1:
        raise ValueError("Task revision lacks mutation history.")

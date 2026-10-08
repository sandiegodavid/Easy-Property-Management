"""Validate original Concern command results and their correlated durable evidence."""

from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, date, datetime
from json import loads
from uuid import UUID

from sqlalchemy import text

from app.modules.tasks.domain.models import Task
from app.platform.migration_errors import MigrationSchemaError

from ..application.commands import ConcernCommand, canonical, fingerprint, receipt_audit
from ..domain.models import Concern, ConcernCreateCommand, FollowUpInput, OwnerConcernError
from ..domain.models import text as concern_text
from .sqlalchemy_models import COMMAND_TRIGGERS as COMMAND_TRIGGERS

STATE_FIELDS = frozenset(
    field.split("_")[0] + "".join(part.title() for part in field.split("_")[1:])
    for field in Concern.__dataclass_fields__
    if field not in {"idempotency_key", "request_fingerprint"}
)
BUSINESS_ACTIONS = {"created", "updated", "status_changed", "follow_up_created"}
VIEW_FIELDS = frozenset(
    {
        "followUpTasks",
        "linkedCommunicationCount",
        "predecessor",
        "successor",
        "originatingCommunicationState",
        "currentSourceState",
        "recentCommunications",
    }
)


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Noncanonical command UUID.")


def _utc(value):
    instant = datetime.fromisoformat(value)
    if (
        instant.tzinfo is None
        or instant.utcoffset() != UTC.utcoffset(instant)
        or instant.isoformat() != value
    ):
        raise ValueError("Invalid command UTC timestamp.")
    return instant


def _snapshot(event, field):
    value = event[field]
    return loads(value) if value is not None else None


def _state(snapshot):
    if not isinstance(snapshot, dict) or not STATE_FIELDS <= set(snapshot):
        raise ValueError("Incomplete Concern snapshot.")
    if type(snapshot["revision"]) is not int or snapshot["revision"] < 1:
        raise ValueError("Invalid Concern snapshot revision.")
    return {key: snapshot[key] for key in STATE_FIELDS}


def validate_commands(connection):
    try:
        _validate_history(connection)
    except (ValueError, TypeError, KeyError, AttributeError, OwnerConcernError) as error:
        raise MigrationSchemaError("Owner concern command history is incompatible.") from error


def _validate_history(connection):
    operations = (
        connection.execute(text("SELECT * FROM owner_concern_command_operations ORDER BY rowid"))
        .mappings()
        .all()
    )
    concerns = {
        row["id"]: row
        for row in connection.execute(text("SELECT * FROM owner_concerns")).mappings()
    }
    audits = connection.execute(text("SELECT * FROM audit_events ORDER BY rowid")).mappings().all()
    by_correlation = defaultdict(list)
    by_entity = defaultdict(list)
    for event in audits:
        by_correlation[event["correlation_id"]].append(event)
        by_entity[event["entity_type"], event["entity_id"]].append(event)
    follow_ups = (
        connection.execute(text("SELECT * FROM owner_concern_follow_up_operations"))
        .mappings()
        .all()
    )
    tasks = {
        row["id"]: row
        for row in connection.execute(
            text("SELECT id,related_entity_type,related_entity_id FROM tasks")
        ).mappings()
    }
    tips, correlations, keys, ids, used_follow_ups = {}, set(), set(), set(), set()
    for row in operations:
        for field in ("id", "concern_id", "idempotency_key", "correlation_id"):
            _uuid(row[field])
        now = _utc(row["created_at_utc"])
        if (
            row["id"] in ids
            or row["idempotency_key"] in keys
            or row["correlation_id"] in correlations
        ):
            raise ValueError("Duplicate command identity.")
        ids.add(row["id"])
        keys.add(row["idempotency_key"])
        correlations.add(row["correlation_id"])
        request, result = loads(row["request_json"]), loads(row["result_json"])
        if (
            not isinstance(request, dict)
            or set(request) != {"action", "concernId", "expectedRevision", "payload"}
            or not isinstance(request["payload"], dict)
            or canonical(request) != row["request_json"]
            or fingerprint(request) != row["request_fingerprint"]
            or not isinstance(result, dict)
            or canonical(result) != row["result_json"]
        ):
            raise ValueError("Noncanonical command evidence.")
        command = ConcernCommand(
            request["action"],
            request["concernId"],
            request["expectedRevision"],
            row["idempotency_key"],
            request["payload"],
        )
        if command.action == "create":
            concern = concerns[row["concern_id"]]
            legacy_payload = {**command.payload, "idempotency_key": row["idempotency_key"]}
            if concern["idempotency_key"] != row["idempotency_key"] or concern[
                "request_fingerprint"
            ] != fingerprint(legacy_payload):
                raise ValueError("Concern creation identity differs from its command.")
        previous = tips.get(row["concern_id"])
        if (
            command.action != row["action"]
            or command.concern_id != (None if command.action == "create" else row["concern_id"])
            or command.expected_revision != row["expected_revision"]
            or command.expected_revision != (previous["revision"] if previous else 0)
            or (command.action == "create") != (previous is None)
            or type(row["resulting_revision"]) is not int
            or type(result.get("revision")) is not int
            or result["revision"] != row["resulting_revision"]
            or result.get("operationId") != row["id"]
            or result.get("id") != row["concern_id"]
            or set(result) - {"operationId", "followUpTask"} != STATE_FIELDS | VIEW_FIELDS
        ):
            raise ValueError("Command identity or revision lineage differs.")
        state = _state(result)
        _validate_view(result)
        correlated = by_correlation[row["correlation_id"]]
        markers = by_entity["owner_concern_command_operation", row["id"]]
        if (
            len(markers) != 1
            or markers[0]["action"] != "recorded"
            or markers[0]["correlation_id"] != row["correlation_id"]
            or markers[0]["before_snapshot"] is not None
            or _snapshot(markers[0], "after_snapshot") != receipt_audit(row)
        ):
            raise ValueError("Command receipt audit differs.")
        _transition(command, state, previous, row["created_at_utc"])
        changed = state != previous
        if state["revision"] != command.expected_revision + int(changed):
            raise ValueError("Command revision differs from effective mutation.")
        if _utc(state["updatedAtUtc"]) > now or _utc(state["recordedAtUtc"]) > now:
            raise ValueError("Command result timestamp exceeds its receipt.")
        business = [
            event
            for event in correlated
            if event["entity_type"] == "owner_concern" and event["entity_id"] == row["concern_id"]
        ]
        _business_audits(command, state, previous, business, changed)
        follow_up = result.get("followUpTask")
        payload_follow_up = (
            command.payload.get("follow_up")
            if command.action == "create"
            else (command.payload if command.action == "follow_up" else None)
        )
        if (payload_follow_up is not None) != ("followUpTask" in result):
            raise ValueError("Follow-up result is missing or unexpected.")
        if follow_up is not None:
            used_follow_ups.add(
                _follow_up(
                    row,
                    state,
                    follow_up,
                    payload_follow_up,
                    correlated,
                    follow_ups,
                    tasks,
                )
            )
        tips[row["concern_id"]] = state
    if set(tips) != set(concerns) or any(
        Concern(**dict(row)).to_dict() != tips[concern_id] for concern_id, row in concerns.items()
    ):
        raise ValueError("Current Concern differs from command history.")
    if used_follow_ups != {row["id"] for row in follow_ups}:
        raise ValueError("Follow-up operation lacks a command receipt.")
    owned = {(row["concern_id"], row["correlation_id"]) for row in operations}
    if any(
        (
            event["entity_type"] == "owner_concern"
            and event["action"] in BUSINESS_ACTIONS
            and (event["entity_id"], event["correlation_id"]) not in owned
        )
        or (
            event["entity_type"] == "owner_concern_command_operation"
            and event["entity_id"] not in ids
        )
        for event in audits
    ):
        raise ValueError("Orphan Concern command audit.")


def _transition(command, state, previous, now):
    payload = command.payload
    if command.action == "create":
        fields = dict(payload)
        if fields.get("follow_up") is not None:
            fields["follow_up"] = FollowUpInput(**fields["follow_up"])
        fields["idempotency_key"] = command.idempotency_key
        normalized = asdict(ConcernCreateCommand(**fields))
        normalized.pop("idempotency_key")
        if normalized != payload:
            raise ValueError("Creation payload is not normalized.")
        for name in (
            "owner_party_id",
            "property_id",
            "concern_type",
            "summary",
            "description",
            "raised_at_utc",
            "space_id",
            "lease_id",
            "tenant_party_id",
            "originating_communication_id",
            "priority",
            "replaces_concern_id",
        ):
            key = name.split("_")[0] + "".join(part.title() for part in name.split("_")[1:])
            if state[key] != normalized[name]:
                raise ValueError("Creation result differs from request.")
        if (
            state["revision"] != 1
            or state["status"] != "open"
            or state["recordedAtUtc"] != now
            or state["updatedAtUtc"] != now
            or any(
                state[k] is not None
                for k in (
                    "resolvedAtUtc",
                    "resolutionSummary",
                    "dismissedAtUtc",
                    "dismissalReason",
                )
            )
        ):
            raise ValueError("Initial Concern state differs.")
        return
    expected = dict(previous)
    if command.action == "patch":
        if not set(payload) <= {"summary", "description", "priority"} or previous["status"] not in {
            "open",
            "in_progress",
        }:
            raise ValueError("Invalid Concern patch.")
        expected.update(
            {
                key: concern_text(value, key, 240 if key == "summary" else 10_000, required=True)
                if key in {"summary", "description"}
                else value
                for key, value in payload.items()
            }
        )
    elif command.action == "follow_up":
        if asdict(FollowUpInput(**payload)) != payload:
            raise ValueError("Follow-up request is not normalized.")
    else:
        allowed = {
            "open": {"in_progress", "resolved", "dismissed"},
            "in_progress": {"open", "resolved", "dismissed"},
            "resolved": {"open"},
            "dismissed": {"open"},
        }
        if (
            set(payload) != {"confirmed", "narrative"}
            or payload["confirmed"] is not True
            or command.action not in allowed[previous["status"]]
        ):
            raise ValueError("Invalid Concern lifecycle request.")
        narrative = payload["narrative"]
        if command.action in {"resolved", "dismissed"} or previous["status"] in {
            "resolved",
            "dismissed",
        }:
            narrative = concern_text(narrative, "Lifecycle narrative", 4000, required=True)
        expected.update(
            status=command.action,
            resolvedAtUtc=now if command.action == "resolved" else None,
            resolutionSummary=narrative if command.action == "resolved" else None,
            dismissedAtUtc=now if command.action == "dismissed" else None,
            dismissalReason=narrative if command.action == "dismissed" else None,
        )
    if expected != previous or command.action == "follow_up":
        expected.update(updatedAtUtc=now, revision=previous["revision"] + 1)
    if state != expected:
        raise ValueError("Concern result differs from requested transition.")


def _object(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("Retained detail object fields differ.")


def _text(value, maximum=None):
    if (
        not isinstance(value, str)
        or not value.strip()
        or (maximum is not None and len(value) > maximum)
    ):
        raise ValueError("Invalid retained detail text.")


def _enum(value, allowed, *, optional=False):
    if value is None and optional:
        return
    if not isinstance(value, str) or value not in allowed:
        raise ValueError("Invalid retained detail status.")


def _date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Invalid retained detail date.")


def _validate_view(result):
    count = result["linkedCommunicationCount"]
    if type(count) is not int or count < 0:
        raise ValueError("Invalid retained communication count.")
    for field, keys in (
        ("followUpTasks", {"id", "status", "title", "dueAtUtc"}),
        ("recentCommunications", {"id", "subject", "status", "occurredAtUtc"}),
    ):
        items = result[field]
        if not isinstance(items, list) or len(items) > 20:
            raise ValueError("Invalid retained detail summary list.")
        seen = set()
        for item in items:
            _object(item, keys)
            _uuid(item["id"])
            if item["id"] in seen:
                raise ValueError("Duplicate retained detail summary.")
            seen.add(item["id"])
            if field == "followUpTasks":
                _enum(item["status"], {"open", "in_progress", "completed", "cancelled"})
                _text(item["title"], 255)
                if item["dueAtUtc"] is not None:
                    _utc(item["dueAtUtc"])
            else:
                _enum(item["status"], {"draft", "recorded", "superseded"})
                _text(item["subject"], 240)
                _utc(item["occurredAtUtc"])
    for field in ("predecessor", "successor"):
        item = result[field]
        if item is not None:
            _object(item, {"id", "status", "summary"})
            _uuid(item["id"])
            _enum(item["status"], {"open", "in_progress", "resolved", "dismissed"})
            _text(item["summary"], 240)
    source = result["originatingCommunicationState"]
    if source is not None:
        _object(source, {"id", "status", "supersededByCommunicationId"})
        _uuid(source["id"])
        _enum(source["status"], {"recorded", "superseded"})
        if source["supersededByCommunicationId"] is not None:
            _uuid(source["supersededByCommunicationId"])
    _source_state(result["currentSourceState"])


def _source_state(state):
    text_fields = {
        "propertyDisplayName",
        "ownerDisplayName",
        "spaceDisplayName",
        "tenantDisplayName",
    }
    bool_fields = {"ownerArchived", "tenantArchived", "tenantProfileActive"}
    date_fields = {"leaseActualMoveOutOn", "availableOn"}
    enum_fields = {
        "propertyStatus": {"active", "archived"},
        "spaceStatus": {"active", "archived"},
        "leaseStatus": {"draft", "executed", "ended", "terminated", "void"},
        "occupancyStatus": {"occupied", "vacant", "unknown"},
        "availabilityStatus": {"available_now", "available_on", "not_available", "unknown"},
    }
    _object(
        state,
        text_fields | bool_fields | date_fields | set(enum_fields) | {"tenantParticipationActive"},
    )
    for field in text_fields:
        if state[field] is not None:
            _text(state[field], 120 if field == "spaceDisplayName" else 240)
    for field in bool_fields:
        if type(state[field]) is not bool:
            raise ValueError("Invalid retained source-state boolean.")
    if (
        state["tenantParticipationActive"] is not None
        and type(state["tenantParticipationActive"]) is not bool
    ):
        raise ValueError("Invalid retained tenant participation.")
    for field in date_fields:
        if state[field] is not None:
            _date(state[field])
    for field, allowed in enum_fields.items():
        _enum(state[field], allowed, optional=True)


def _business_audits(command, state, previous, events, changed):
    action = (
        "created"
        if command.action == "create"
        else "updated"
        if command.action == "patch"
        else "follow_up_created"
        if command.action == "follow_up"
        else "status_changed"
    )
    primary = [event for event in events if event["action"] == action]
    if not changed:
        if command.action != "patch" or events:
            raise ValueError("No-op command has business audits.")
        return
    if len(primary) != 1:
        raise ValueError("Command business audit is missing or duplicated.")
    event = primary[0]
    before = _snapshot(event, "before_snapshot")
    after = _snapshot(event, "after_snapshot")
    if (None if before is None else _state(before)) != previous or _state(after) != state:
        raise ValueError("Command original result differs from audit transition.")
    expected_after = dict(state)
    if command.action == "create":
        expected_after.update(
            historicalSelectionReason=command.payload["historical_selection_reason"],
            duplicateReason=command.payload["duplicate_reason"],
        )
    elif command.action == "open" and previous["status"] in {"resolved", "dismissed"}:
        expected_after["reopenReason"] = concern_text(
            command.payload["narrative"],
            "Reopen reason",
            4000,
            required=True,
        )
    elif command.action == "follow_up":
        _uuid(after["taskId"])
        expected_after["taskId"] = after["taskId"]
    if before != previous or after != expected_after:
        raise ValueError("Command business audit context differs from request.")
    extra = [event for event in events if event is not primary[0]]
    if command.action == "create" and command.payload.get("follow_up") is not None:
        if len(extra) != 1 or extra[0]["action"] != "follow_up_created":
            raise ValueError("Initial follow-up audit differs.")
        if (
            extra[0]["before_snapshot"] is not None
            or _state(_snapshot(extra[0], "after_snapshot")) != state
        ):
            raise ValueError("Initial follow-up must preserve the creation revision.")
    elif extra:
        raise ValueError("Unexpected Concern business audits.")


def _follow_up(row, state, task, payload, events, operations, tasks):
    if not isinstance(task, dict):
        raise ValueError("Invalid Task result.")
    _uuid(task["id"])
    expected = Task(
        id=task["id"],
        title=payload["title"],
        notes=payload["notes"],
        status="open",
        priority=payload["priority"],
        due_at_utc=payload["due_at_utc"],
        due_timezone=payload["due_timezone"],
        is_all_day=False,
        completed_at_utc=None,
        cancelled_at_utc=None,
        outcome_note=None,
        related_entity_type="owner_concern",
        related_entity_id=row["concern_id"],
        related_label=state["summary"],
        created_at_utc=task["createdAtUtc"],
        updated_at_utc=task["createdAtUtc"],
    ).to_dict()
    if (
        task != expected
        or type(task.get("isAllDay")) is not bool
        or type(task.get("revision")) is not int
    ):
        raise ValueError("Original Task result differs from request.")
    _utc(task["createdAtUtc"])
    current = tasks.get(task["id"])
    if (
        current is None
        or current["related_entity_type"] != "owner_concern"
        or current["related_entity_id"] != row["concern_id"]
    ):
        raise ValueError("Task operation foreign-key ownership differs.")
    linked = [
        operation
        for operation in operations
        if operation["correlation_id"] == row["correlation_id"]
    ]
    if len(linked) != 1:
        raise ValueError("Follow-up operation is missing or duplicated.")
    operation = linked[0]
    if (
        operation["concern_id"] != row["concern_id"]
        or operation["task_id"] != task["id"]
        or operation["idempotency_key"] != row["idempotency_key"]
        or operation["request_fingerprint"] != row["request_fingerprint"]
        or operation["created_at_utc"] != row["created_at_utc"]
    ):
        raise ValueError("Follow-up operation differs from its command.")
    for entity, item_id, action, snapshot in (
        ("task", task["id"], "created", task),
        (
            "owner_concern_follow_up_operation",
            operation["id"],
            "created",
            {"id": operation["id"], "concernId": row["concern_id"], "taskId": task["id"]},
        ),
    ):
        matching = [
            event
            for event in events
            if event["entity_type"] == entity
            and event["entity_id"] == item_id
            and event["action"] == action
        ]
        if (
            len(matching) != 1
            or matching[0]["before_snapshot"] is not None
            or _snapshot(matching[0], "after_snapshot") != snapshot
        ):
            raise ValueError("Original follow-up audit snapshot differs.")
    concern_events = [
        event
        for event in events
        if event["entity_type"] == "owner_concern"
        and event["entity_id"] == row["concern_id"]
        and event["action"] == "follow_up_created"
    ]
    if (
        len(concern_events) != 1
        or _snapshot(concern_events[0], "after_snapshot").get("taskId") != task["id"]
    ):
        raise ValueError("Concern follow-up Task identity differs.")
    return operation["id"]

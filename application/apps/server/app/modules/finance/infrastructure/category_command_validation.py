"""Reconstruct expense category receipts from original requests and audit evidence."""

from collections import defaultdict
from dataclasses import asdict
from json import loads

from sqlalchemy import text

from app.modules.finance.application.category_commands import (
    ExpenseCategoryCommand,
    category_receipt_audit,
)
from app.modules.finance.application.commands import canonical_json, canonical_uuid, fingerprint
from app.modules.finance.domain.category_seeds import (
    EXPENSE_CATEGORY_SEEDS,
    EXPENSE_CATEGORY_SEED_TIMESTAMP,
)
from app.modules.finance.domain.expense_models import (
    CategoryCreateCommand,
    CategoryPatchCommand,
    ExpenseCategory,
    category_normalized_name,
)
from app.modules.finance.domain.models import FinanceError, VoidCommand
from app.modules.finance.infrastructure.command_validation import _utc
from app.modules.finance.infrastructure.sqlalchemy_models import (
    CATEGORY_COMMAND_TRIGGERS,
    ExpenseCategoryCommandOperationModel,
    ExpenseCategoryModel,
)
from app.platform.migration_errors import MigrationSchemaError


def validate_category_triggers(connection):
    actual = dict(
        connection.execute(
            text(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'expense_category_command_operations'"
            )
        ).all()
    )

    def normalize(value):
        return " ".join(value.strip().split()).lower()

    if {key: normalize(value) for key, value in actual.items()} != {
        key: normalize(value) for key, value in CATEGORY_COMMAND_TRIGGERS.items()
    }:
        raise MigrationSchemaError("Expense category receipt triggers are incompatible.")


def validate_category_commands(connection):
    validate_category_triggers(connection)
    try:
        _history(connection)
    except (FinanceError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise MigrationSchemaError("Expense category command history is invalid.") from error


def _same(actual, expected):
    if canonical_json(actual) != canonical_json(expected):
        raise ValueError("Expense category evidence differs from original command.")


def _state(state):
    if not isinstance(state, dict):
        raise ValueError("Category state must be an object.")
    canonical_uuid(state["id"])
    command = CategoryCreateCommand(
        state["displayName"], state["description"], state["displayOrder"]
    )
    _same(
        asdict(command),
        {
            "display_name": state["displayName"],
            "description": state["description"],
            "display_order": state["displayOrder"],
        },
    )
    if (
        state["normalizedName"] != category_normalized_name(command.display_name)
        or type(state["revision"]) is not int
        or state["revision"] < 1
        or _utc(state["updatedAt"]) < _utc(state["createdAt"])
    ):
        raise ValueError("Category state is invalid.")
    if state["archivedAt"] is not None and (
        _utc(state["archivedAt"]) < _utc(state["createdAt"])
        or _utc(state["archivedAt"]) > _utc(state["updatedAt"])
    ):
        raise ValueError("Category lifecycle timestamps are invalid.")


def _transition(command, previous, category_id, stamp):
    payload = command.payload
    if command.action == "create":
        if previous is not None:
            raise ValueError("Category was already created.")
        normalized = CategoryCreateCommand(**payload)
        _same(payload, asdict(normalized))
        return ExpenseCategory(
            id=category_id,
            display_name=normalized.display_name,
            normalized_name=category_normalized_name(normalized.display_name),
            description=normalized.description,
            display_order=normalized.display_order,
            archived_at=None,
            created_at=stamp,
            updated_at=stamp,
            revision=1,
        ).to_dict()
    if previous is None or _utc(stamp) < _utc(previous["updatedAt"]):
        raise ValueError("Category command lacks its predecessor.")
    state = dict(previous)
    if command.action == "patch":
        normalized = CategoryPatchCommand(fields=frozenset(payload), **payload)
        _same(payload, {field: getattr(normalized, field) for field in normalized.fields})
        names = {
            "display_name": "displayName",
            "description": "description",
            "display_order": "displayOrder",
        }
        state.update({names[field]: value for field, value in payload.items()})
        state["normalizedName"] = category_normalized_name(state["displayName"])
    else:
        normalized = VoidCommand(**payload)
        _same(payload, asdict(normalized))
        if (previous["archivedAt"] is not None) == (command.action == "archive"):
            raise ValueError("Duplicate category lifecycle command.")
        state["archivedAt"] = stamp if command.action == "archive" else None
    if state != previous:
        state.update(updatedAt=stamp, revision=previous["revision"] + 1)
    return state


def _audit(event, row, *, entity_type, entity_id, action, before, after):
    _utc(event["occurred_at"])
    if (
        event["entity_type"] != entity_type
        or event["entity_id"] != entity_id
        or event["action"] != action
        or event["correlation_id"] != row["correlation_id"]
        or event["schema_version"] != 1
    ):
        raise ValueError("Category audit identity differs.")
    _same(loads(event["before_snapshot"]) if event["before_snapshot"] is not None else None, before)
    _same(loads(event["after_snapshot"]) if event["after_snapshot"] is not None else None, after)


def _history(connection):
    current = {
        row["id"]: ExpenseCategory(**row).to_dict()
        for row in connection.execute(ExpenseCategoryModel.__table__.select()).mappings()
    }
    tips = {
        seed[0]: ExpenseCategory(
            id=seed[0],
            display_name=seed[1],
            normalized_name=seed[2],
            description=None,
            display_order=order,
            archived_at=None,
            created_at=EXPENSE_CATEGORY_SEED_TIMESTAMP,
            updated_at=EXPENSE_CATEGORY_SEED_TIMESTAMP,
            revision=1,
        ).to_dict()
        for order, seed in enumerate(EXPENSE_CATEGORY_SEEDS)
    }
    audits = (
        connection.execute(
            text(
                "SELECT rowid AS position, * FROM audit_events WHERE entity_type IN ('expense_category','expense_category_command_operation') ORDER BY rowid"
            )
        )
        .mappings()
        .all()
    )
    correlated = defaultdict(list)
    for event in audits:
        correlated[event["correlation_id"]].append(event)
    seen, correlations, ids, keys = set(), set(), set(), set()
    operations = connection.execute(
        ExpenseCategoryCommandOperationModel.__table__.select().order_by(text("rowid"))
    ).mappings()
    last_position = 0
    for row in operations:
        for field in ("id", "category_id", "idempotency_key", "correlation_id"):
            canonical_uuid(row[field])
        _utc(row["created_at"])
        if (
            row["id"] in ids
            or row["idempotency_key"] in keys
            or row["correlation_id"] in correlations
        ):
            raise ValueError("Category command identity is reused.")
        ids.add(row["id"])
        keys.add(row["idempotency_key"])
        correlations.add(row["correlation_id"])
        request, result = loads(row["request_json"]), loads(row["result_json"])
        if (
            not isinstance(request, dict)
            or set(request) != {"action", "categoryId", "expectedRevision", "payload"}
            or not isinstance(request["payload"], dict)
            or canonical_json(request) != row["request_json"]
            or fingerprint(row["request_json"]) != row["request_fingerprint"]
            or not isinstance(result, dict)
            or canonical_json(result) != row["result_json"]
        ):
            raise ValueError("Category request or result is not canonical.")
        command = ExpenseCategoryCommand(
            request["action"],
            request["categoryId"],
            request["expectedRevision"],
            row["idempotency_key"],
            request["payload"],
        )
        previous = tips.get(row["category_id"])
        if (
            command.action != row["action"]
            or command.category_id != (None if command.action == "create" else row["category_id"])
            or type(row["expected_revision"]) is not int
            or command.expected_revision != row["expected_revision"]
            or command.expected_revision != (previous["revision"] if previous else 0)
            or type(row["resulting_revision"]) is not int
        ):
            raise ValueError("Category revision lineage differs.")
        state = _transition(command, previous, row["category_id"], row["created_at"])
        _state(state)
        _same(result, {**state, "operationId": row["id"]})
        if state["revision"] != row["resulting_revision"]:
            raise ValueError("Category result revision differs.")
        if state["archivedAt"] is None and any(
            item["id"] != state["id"]
            and item["archivedAt"] is None
            and item["normalizedName"] == state["normalizedName"]
            for item in tips.values()
        ):
            raise ValueError("Category command duplicates an active name.")
        events = correlated[row["correlation_id"]]
        changed = state != previous
        if len(events) != (2 if changed else 1) or events[0]["position"] <= last_position:
            raise ValueError("Category correlated audit count or order differs.")
        if changed:
            after = dict(state)
            if command.action in {"archive", "restore"}:
                after["lifecycleReason"] = command.payload["reason"]
            _audit(
                events[0],
                row,
                entity_type="expense_category",
                entity_id=state["id"],
                action={
                    "create": "created",
                    "patch": "updated",
                    "archive": "archived",
                    "restore": "restored",
                }[command.action],
                before=previous,
                after=after,
            )
        _audit(
            events[-1],
            row,
            entity_type="expense_category_command_operation",
            entity_id=row["id"],
            action="recorded",
            before=None,
            after=category_receipt_audit(row),
        )
        last_position = events[-1]["position"]
        seen.update(event["id"] for event in events)
        tips[state["id"]] = state
    _same(current, tips)
    if seen != {event["id"] for event in audits}:
        raise ValueError("Category audit lacks its command receipt.")

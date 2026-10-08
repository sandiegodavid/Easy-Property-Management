"""Exact current schema and retained inventory command history."""

from datetime import UTC, datetime
from json import loads
from uuid import UUID

from sqlalchemy import CheckConstraint, inspect

from app.modules.portfolio.api.router import (
    PropertyMutationResponse,
    SpaceInventoryMutationResponse,
)
from app.modules.portfolio.application.inventory_commands import (
    INVENTORY_ACTIONS,
    canonical_json,
    fingerprint,
    inventory_state,
    receipt_audit,
)
from app.modules.portfolio.domain.models import Property, PropertyOwnership, Space
from app.modules.portfolio.infrastructure.inventory_triggers import INVENTORY_TRIGGERS
from app.modules.portfolio.infrastructure.sqlalchemy_models import PortfolioInventoryOperationModel
from app.platform.migration_errors import MigrationSchemaError

BUSINESS_EVENTS = {
    "create_property": {
        ("property", "created"),
        ("property_ownership", "created"),
        ("space", "created"),
    },
    "patch_property": {("property", "updated")},
    "archive_property": {("property", "status_changed"), ("space", "status_changed")},
    "restore_property": {("property", "status_changed"), ("space", "status_changed")},
    "replace_ownerships": {("property", "ownership_changed"), ("property_ownership", "created")},
    "add_space": {("space", "created")},
    "patch_space": {("space", "updated")},
    "archive_space": {("space", "status_changed")},
    "restore_space": {("space", "status_changed")},
}


def _normalise(sql):
    return "".join(sql.lower().split())


def validate_inventory_commands(connection):
    try:
        _schema(connection)
        _history(connection)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise MigrationSchemaError(
            "Portfolio inventory command schema or history is invalid."
        ) from error


def _schema(connection):
    table = PortfolioInventoryOperationModel.__table__
    inspector = inspect(connection)
    if not inspector.has_table(table.name):
        raise ValueError("Inventory receipts are missing.")
    columns = inspector.get_columns(table.name)
    if {item["name"] for item in columns} != set(table.columns.keys()):
        raise ValueError("Inventory receipt columns differ.")
    for item in columns:
        expected = table.columns[item["name"]]
        if (
            bool(item["nullable"]) != expected.nullable
            or bool(item["primary_key"]) != expected.primary_key
            or str(item["type"]).upper() != str(expected.type).upper()
        ):
            raise ValueError("Inventory column definition differs.")
    if {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)} != {
        ("idempotency_key",)
    }:
        raise ValueError("Inventory keys must be globally unique.")
    keys = {
        (
            tuple(item["constrained_columns"]),
            item["referred_table"],
            tuple(item["referred_columns"]),
        )
        for item in inspector.get_foreign_keys(table.name)
    }
    if keys != {(("property_id",), "properties", ("id",))}:
        raise ValueError("Inventory receipt references differ.")
    checks = {
        _normalise(str(item.sqltext))
        for item in table.constraints
        if isinstance(item, CheckConstraint)
    }
    if {
        _normalise(item["sqltext"]) for item in inspector.get_check_constraints(table.name)
    } != checks:
        raise ValueError("Inventory receipt checks differ.")
    indexes = inspector.get_indexes(table.name)
    if len(indexes) != 1 or (
        indexes[0]["name"],
        tuple(indexes[0]["column_names"]),
        bool(indexes[0]["unique"]),
        _normalise(str(indexes[0].get("dialect_options", {}).get("sqlite_where", ""))),
    ) != ("inventory_property_revision", ("property_id", "result_revision"), True, "effective=1"):
        raise ValueError("Inventory revision index differs.")
    triggers = dict(
        connection.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='portfolio_inventory_operations'"
        ).all()
    )
    if {key: _normalise(value) for key, value in triggers.items()} != {
        key: _normalise(value) for key, value in INVENTORY_TRIGGERS.items()
    }:
        raise ValueError("Inventory immutability triggers differ.")


def _uuid(value):
    if str(UUID(value)) != value:
        raise ValueError("Inventory identity is not canonical.")


def _utc(value):
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() != UTC.utcoffset(instant):
        raise ValueError("Inventory timestamp must be UTC.")
    return instant


def _history(connection):
    properties = {
        row["id"]: Property(**dict(row))
        for row in connection.exec_driver_sql("SELECT * FROM properties").mappings()
    }
    spaces, ownerships = {}, {}
    for row in connection.exec_driver_sql("SELECT * FROM spaces").mappings():
        item = Space(**dict(row))
        spaces.setdefault(item.property_id, []).append(item)
    for row in connection.exec_driver_sql("SELECT * FROM property_ownerships").mappings():
        item = PropertyOwnership(**dict(row))
        ownerships.setdefault(item.property_id, []).append(item)
    audits, effects, business = {}, {}, {}
    for event in connection.exec_driver_sql(
        "SELECT * FROM audit_events WHERE entity_type IN ('portfolio_inventory_operation', 'property', 'space', 'property_ownership')"
    ).mappings():
        if event["entity_type"] == "portfolio_inventory_operation":
            audits.setdefault(event["entity_id"], []).append(event)
        elif event["action"] == "inventory_command_applied":
            effects.setdefault((event["entity_id"], event["correlation_id"]), []).append(event)
        else:
            business.setdefault(event["correlation_id"], []).append(event)
    revisions, snapshots, recorded = {}, {}, set()
    for row in connection.exec_driver_sql(
        "SELECT * FROM portfolio_inventory_operations ORDER BY property_id, result_revision, effective DESC, created_at, id"
    ).mappings():
        receipt = dict(row)
        recorded.add(receipt["id"])
        for field in ("id", "property_id", "correlation_id"):
            _uuid(receipt[field])
        committed = _utc(receipt["created_at"])
        if (
            not isinstance(receipt["idempotency_key"], str)
            or not receipt["idempotency_key"].strip()
            or receipt["idempotency_key"] != receipt["idempotency_key"].strip()
            or len(receipt["idempotency_key"]) > 200
        ):
            raise ValueError("Invalid inventory key.")
        request, response = loads(receipt["request_json"]), loads(receipt["response_json"])
        for name, value in (("request", request), ("response", response)):
            if (
                canonical_json(value) != receipt[f"{name}_json"]
                or fingerprint(receipt[f"{name}_json"]) != receipt[f"{name}_fingerprint"]
            ):
                raise ValueError("Inventory payload was rewritten.")
        action, property_id = receipt["action"], receipt["property_id"]
        previous = revisions.get(property_id, 0)
        if (
            action not in INVENTORY_ACTIONS
            or type(receipt["expected_revision"]) is not int
            or receipt["expected_revision"] != previous
            or type(receipt["effective"]) is not int
            or receipt["effective"] not in {0, 1}
            or type(receipt["result_revision"]) is not int
            or receipt["result_revision"] != previous + receipt["effective"]
            or (previous == 0) != (action == "create_property")
        ):
            raise ValueError("Inventory revision chain differs.")
        if (
            set(request) != {"action", "targetId", "expectedPropertyRevision", "payload"}
            or request["action"] != action
            or type(request["expectedPropertyRevision"]) is not int
            or request["expectedPropertyRevision"] != previous
            or not isinstance(request["payload"], dict)
        ):
            raise ValueError("Inventory request identity differs.")
        target = request["targetId"]
        if action == "create_property":
            if target is not None:
                raise ValueError("Creation target must be unassigned.")
        elif action in {"patch_space", "archive_space", "restore_space"}:
            if target not in {item.id for item in spaces.get(property_id, [])}:
                raise ValueError("Space target belongs to another property.")
        elif target != property_id:
            raise ValueError("Property target differs.")
        if (
            response.get("operationId") != receipt["id"]
            or type(response.get("propertyRevision")) is not int
            or response["propertyRevision"] != receipt["result_revision"]
            or response.get("asOf") != receipt["created_at"]
        ):
            raise ValueError("Inventory response identity differs.")
        if "propertyId" in response:
            SpaceInventoryMutationResponse.model_validate(response)
            if response["propertyId"] != property_id or (
                action != "add_space" and response["id"] != target
            ):
                raise ValueError("Space result target differs.")
        else:
            PropertyMutationResponse.model_validate(response)
            if response["id"] != property_id:
                raise ValueError("Property result target differs.")
        if _utc(response["updatedAt"]) > committed:
            raise ValueError("Inventory result timestamp follows commit.")
        events = audits.get(receipt["id"], [])
        if (
            len(events) != 1
            or events[0]["action"] != "recorded"
            or events[0]["before_snapshot"] is not None
            or events[0]["correlation_id"] != receipt["correlation_id"]
            or loads(events[0]["after_snapshot"]) != receipt_audit(receipt)
        ):
            raise ValueError("Inventory receipt audit differs.")
        witnesses = effects.pop((property_id, receipt["correlation_id"]), [])
        if len(witnesses) != 1:
            raise ValueError("Inventory effect evidence differs.")
        event = witnesses[0]
        before = loads(event["before_snapshot"]) if event["before_snapshot"] else None
        after = loads(event["after_snapshot"])
        if (
            before != snapshots.get(property_id)
            or after["property"]["propertyRevision"] != receipt["result_revision"]
            or (receipt["effective"] == 0 and after != before)
            or (
                receipt["effective"] == 1
                and after["property"]["updatedAt"] != receipt["created_at"]
            )
        ):
            raise ValueError("Inventory effect chain differs.")
        events = business.get(receipt["correlation_id"], [])
        if receipt["effective"] and not BUSINESS_EVENTS[action].issubset(
            {(item["entity_type"], item["action"]) for item in events}
        ):
            raise ValueError("Correlated inventory workflow audit is missing.")
        for space in after["spaces"]:
            if space["propertyId"] != property_id:
                raise ValueError("Inventory witness has a foreign space.")
        if "propertyId" in response:
            expected_space = next(item for item in after["spaces"] if item["id"] == response["id"])
            if any(
                response.get(key) != value
                for key, value in expected_space.items()
                if key not in {"normalizedName", "archivedByPropertyOperationId"}
            ):
                raise ValueError("Space response and inventory effect differ.")
        elif any(response.get(key) != value for key, value in after["property"].items()):
            raise ValueError("Property response and inventory effect differ.")
        revisions[property_id], snapshots[property_id] = receipt["result_revision"], after
    if set(audits) != recorded or effects:
        raise ValueError("Unsupported inventory audit evidence.")
    for property_id, property in properties.items():
        current = inventory_state(
            (property, ownerships.get(property_id, []), {}, spaces.get(property_id, []))
        )
        if (
            revisions.get(property_id) != property.property_revision
            or snapshots.get(property_id) != current
        ):
            raise ValueError("Retained inventory differs from command history.")

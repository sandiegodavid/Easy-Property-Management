"""Validate immutable financial receipt history at open, export, and restore."""

from datetime import UTC, datetime
from json import loads

from sqlalchemy import select, text

from app.modules.finance.application.commands import (
    SCOPE_REVISION_FIELDS,
    FinanceCommandIdentity,
    FinanceScope,
    canonical_json,
    canonical_uuid,
    fingerprint,
    receipt_audit,
)
from app.modules.finance.domain.models import FinanceError
from app.modules.finance.infrastructure.command_models import (
    FINANCE_COMMAND_TRIGGERS,
    FinanceCommandOperationModel,
    FinanceCommandRevisionModel,
)
from app.modules.finance.infrastructure.consumer_command_validation import validate_consumer_result
from app.platform.migration_errors import MigrationSchemaError


def _normalise(value: str) -> str:
    return " ".join(value.strip().split()).lower()


def _utc(value: str) -> datetime:
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() != UTC.utcoffset(instant):
        raise ValueError("Financial receipt time must be UTC.")
    if instant.astimezone(UTC).isoformat() != value:
        raise ValueError("Financial receipt time is not canonical.")
    return instant


def validate_finance_commands(connection) -> None:
    try:
        _triggers(connection)
        _history(connection)
    except (FinanceError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise MigrationSchemaError("Financial command history is invalid.") from error


def _triggers(connection):
    actual = dict(
        connection.execute(
            text(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'finance_command_operations'"
            )
        ).all()
    )
    if {key: _normalise(value) for key, value in actual.items()} != {
        key: _normalise(value) for key, value in FINANCE_COMMAND_TRIGGERS.items()
    }:
        raise ValueError("Financial command receipts must be append-only.")


def _history(connection):
    _required_roots(connection)
    scopes = {
        (row["scope_kind"], row["scope_id"]): row
        for row in connection.execute(select(FinanceCommandRevisionModel.__table__)).mappings()
    }
    operation_events = {}
    effects = {}
    business = {}
    for event in connection.execute(
        text(
            "SELECT * FROM audit_events WHERE entity_type IN ('finance_command_operation', 'finance_command_scope')"
        )
    ).mappings():
        if event["entity_type"] == "finance_command_operation":
            operation_events.setdefault(event["entity_id"], []).append(event)
        else:
            after = loads(event["after_snapshot"])
            key = (after["scope_kind"], event["entity_id"], event["correlation_id"])
            effects.setdefault(key, []).append(event)
    for event in connection.execute(
        text(
            "SELECT * FROM audit_events WHERE entity_type IN ('rent_expectation', 'rent_receipt', 'rent_receipt_allocation', 'rent_expectation_timeliness_review', 'expense', 'expense_refund', 'prepaid_check', 'task', 'task_reminder', 'security_deposit_account', 'security_deposit_receipt', 'security_deposit_settlement', 'security_deposit_deduction', 'security_deposit_credit', 'security_deposit_deduction_source', 'security_deposit_refund')"
        )
    ).mappings():
        business.setdefault(event["correlation_id"], []).append(event)
    prior_states = {}
    recorded_ids = set()
    rows = connection.execute(
        select(FinanceCommandOperationModel.__table__).order_by(
            FinanceCommandOperationModel.sequence
        )
    ).mappings()
    for row in rows:
        receipt = {key: value for key, value in row.items() if key != "sequence"}
        recorded_ids.add(receipt["id"])
        for column in ("id", "scope_id", "target_id", "idempotency_key", "correlation_id"):
            canonical_uuid(receipt[column])
        _utc(receipt["created_at"])
        key = (receipt["scope_kind"], receipt["scope_id"])
        request = loads(receipt["request_json"])
        response = loads(receipt["response_json"])
        if set(request) != {
            "scopeKind",
            "scopeId",
            "action",
            "targetId",
            "expectedRevision",
            "payload",
        }:
            raise ValueError("Financial request shape differs.")
        identity = FinanceCommandIdentity(
            FinanceScope(request["scopeKind"], request["scopeId"]),
            request["action"],
            request["targetId"],
            request["expectedRevision"],
            receipt["idempotency_key"],
            request["payload"],
        )
        if (
            identity.request_json != receipt["request_json"]
            or fingerprint(identity.request_json) != receipt["request_fingerprint"]
            or canonical_json(response) != receipt["response_json"]
            or fingerprint(receipt["response_json"]) != receipt["response_fingerprint"]
            or (identity.scope.kind, identity.scope.id) != key
            or identity.action != receipt["action"]
            or identity.target_id != receipt["target_id"]
            or identity.expected_revision != receipt["expected_revision"]
        ):
            raise ValueError("Financial command payload was rewritten.")
        prior = prior_states.get(key)
        expected = 0 if prior is None else prior["revision"]
        revision = receipt["result_revision"]
        effective = receipt["effective"]
        if (
            type(effective) is not int
            or effective not in {0, 1}
            or receipt["expected_revision"] != expected
            or revision != expected + effective
            or not isinstance(response, dict)
            or type(response.get(SCOPE_REVISION_FIELDS[key[0]])) is not int
            or response[SCOPE_REVISION_FIELDS[key[0]]] != revision
            or response.get("operationId") != receipt["id"]
        ):
            raise ValueError("Financial revision chain or original result is invalid.")
        if key[0] == "rent_ledger" and receipt["action"] in {
            "synchronize_expectations",
            "record_receipt",
            "void_receipt",
            "void_expectation",
            "review_timeliness",
        }:
            _rent_result(receipt, response, business.get(receipt["correlation_id"], []))
        else:
            validate_consumer_result(
                connection, receipt, response, business.get(receipt["correlation_id"], [])
            )
        state = {
            "scope_kind": key[0],
            "scope_id": key[1],
            "revision": revision,
            "updated_at": receipt["created_at"]
            if prior is None or effective
            else prior["updated_at"],
        }
        events = operation_events.get(receipt["id"], [])
        correlated = effects.pop((*key, receipt["correlation_id"]), [])
        if (
            len(events) != 1
            or events[0]["action"] != "recorded"
            or events[0]["correlation_id"] != receipt["correlation_id"]
            or events[0]["before_snapshot"] is not None
            or loads(events[0]["after_snapshot"]) != receipt_audit(receipt)
            or len(correlated) != 1
            or correlated[0]["action"] != "command_applied"
            or loads(correlated[0]["after_snapshot"]) != state
            or (
                None
                if correlated[0]["before_snapshot"] is None
                else loads(correlated[0]["before_snapshot"])
            )
            != prior
        ):
            raise ValueError("Correlated financial command audit history is invalid.")
        prior_states[key] = state
    if set(scopes) != set(prior_states) or set(operation_events) != recorded_ids or effects:
        raise ValueError("Financial receipt history has unsupported or missing records.")
    for key, row in scopes.items():
        _utc(row["updated_at"])
        if {column: row[column] for column in prior_states[key]} != prior_states[key]:
            raise ValueError("Current financial revision differs from recorded history.")


def _required_roots(connection):
    for table, kind, action in (
        ("expenses", "expense", "record_expense"),
        ("security_deposit_accounts", "deposit_account", "create_account"),
    ):
        missing = connection.execute(
            text(
                f"SELECT 1 FROM {table} root WHERE NOT EXISTS ("
                "SELECT 1 FROM finance_command_operations operation WHERE operation.scope_kind=:kind "
                "AND operation.scope_id=root.id AND operation.action=:action AND operation.expected_revision=0) LIMIT 1"
            ),
            {"kind": kind, "action": action},
        ).first()
        if missing:
            raise ValueError("Financial aggregate is missing its creation command.")
    if connection.execute(
        text(
            "SELECT 1 FROM prepaid_check_operations legacy LEFT JOIN finance_command_operations operation "
            "ON operation.id=legacy.id AND operation.idempotency_key=legacy.idempotency_key "
            "AND operation.correlation_id=legacy.correlation_id "
            "AND operation.action=legacy.action || '_prepaid_check' WHERE operation.id IS NULL LIMIT 1"
        )
    ).first():
        raise ValueError("Prepaid history is missing its shared-ledger command.")


def _rent_result(receipt, response, events):
    from app.modules.finance.api.router import (
        ExpectationMutationResponse,
        ReceiptMutationResponse,
        SynchronizeResponse,
    )

    action = receipt["action"]
    model = (
        SynchronizeResponse
        if action == "synchronize_expectations"
        else (
            ReceiptMutationResponse
            if action in {"record_receipt", "void_receipt"}
            else ExpectationMutationResponse
        )
    )
    model.model_validate(response)
    if action == "synchronize_expectations":
        items = response["items"]
        if bool(items) != bool(receipt["effective"]) or any(
            item["leaseId"] != receipt["scope_id"] for item in items
        ):
            raise ValueError("Synchronization effect or Lease identity differs.")
        expected = {("rent_expectation", item["id"], "created") for item in items}
    else:
        if response["leaseId"] != receipt["scope_id"] or not receipt["effective"]:
            raise ValueError("Financial mutation must belong to its Lease and be effective.")
        if action == "record_receipt":
            if (
                response["idempotencyKey"] != receipt["idempotency_key"]
                or response["voidedAt"] is not None
            ):
                raise ValueError("Receipt creation result is invalid.")
            expected = {("rent_receipt", response["id"], "recorded")} | {
                ("rent_receipt_allocation", item["id"], "created")
                for item in response["allocations"]
            }
        elif action in {"void_receipt", "void_expectation"}:
            if (
                response["id"] != receipt["target_id"]
                or response["voidedAt"] != receipt["created_at"]
            ):
                raise ValueError("Void result differs from the committed command.")
            entity = "rent_receipt" if action == "void_receipt" else "rent_expectation"
            expected = {(entity, response["id"], "voided")}
        else:
            if response["id"] != receipt["target_id"]:
                raise ValueError("Review target differs from the committed command.")
            expected = {
                (event["entity_type"], event["entity_id"], event["action"]) for event in events
            }
            if len(expected) != 1 or next(iter(expected))[::2] != (
                "rent_expectation_timeliness_review",
                "recorded",
            ):
                raise ValueError("Timeliness review history is invalid.")
    actual = {(event["entity_type"], event["entity_id"], event["action"]) for event in events}
    if actual != expected or len(events) != len(expected):
        raise ValueError("Correlated financial business audit evidence is incomplete.")
    for event in events:
        after = loads(event["after_snapshot"])
        if after.get("id") != event["entity_id"]:
            raise ValueError("Financial audit record identity differs.")
        if event["entity_type"] in {"rent_expectation", "rent_receipt"}:
            if after.get("leaseId") != receipt["scope_id"]:
                raise ValueError("Financial audit belongs to another Lease.")
            view = (
                next(item for item in response["items"] if item["id"] == event["entity_id"])
                if action == "synchronize_expectations"
                else response
            )
            if any(view[field] != value for field, value in after.items() if field in view):
                raise ValueError("Original financial result differs from its business audit.")
            if event["action"] in {"created", "recorded"} and event["before_snapshot"] is not None:
                raise ValueError("Creation audit cannot have an existing before-state.")
            if event["action"] == "voided":
                before = loads(event["before_snapshot"])
                if (
                    before.get("id") != event["entity_id"]
                    or before.get("voidedAt") is not None
                    or after.get("voidReason")
                    != loads(receipt["request_json"])["payload"]["reason"]
                ):
                    raise ValueError("Void business audit transition is invalid.")
        elif event["entity_type"] == "rent_receipt_allocation":
            allocation = next(
                item for item in response["allocations"] if item["id"] == event["entity_id"]
            )
            if any(
                after.get(field) != allocation[field]
                for field in ("receiptId", "expectationId", "amountMinor", "createdAt")
            ):
                raise ValueError("Allocation result differs from its correlated audit.")
        elif (
            after.get("expectationId") != receipt["target_id"]
            or after.get("createdAt") != receipt["created_at"]
        ):
            raise ValueError("Review result differs from its correlated audit.")

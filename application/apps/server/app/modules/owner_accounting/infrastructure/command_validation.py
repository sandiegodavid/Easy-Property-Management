"""Reconstruct OWNER command revisions and immutable original-response history."""

from json import loads

from sqlalchemy import select, text

from app.modules.finance.application.commands import (
    canonical_json,
    canonical_uuid,
    fingerprint,
    validate_command_concurrency,
)
from app.modules.finance.domain.models import FinanceError
from app.modules.owner_accounting.domain.models import OwnerRentReport
from app.modules.owner_accounting.infrastructure.sqlalchemy_models import (
    OwnerRentReportModel,
    OwnerRentReportOperationModel,
)
from app.platform.migration_errors import MigrationSchemaError


def validate_owner_commands(connection):
    try:
        _validate(connection)
    except (FinanceError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise MigrationSchemaError("Owner report command history is invalid.") from error


def _validate(connection):
    reports = {
        row["id"]: OwnerRentReport(**row).to_dict()
        for row in connection.execute(select(OwnerRentReportModel.__table__)).mappings()
    }
    events = {}
    for row in connection.execute(
        text(
            "SELECT * FROM audit_events WHERE entity_type IN ('owner_rent_report', 'owner_rent_report_operation')"
        )
    ).mappings():
        events.setdefault((row["entity_type"], row["entity_id"], row["correlation_id"]), []).append(
            row
        )
    histories = {}
    rows = connection.execute(
        select(OwnerRentReportOperationModel.__table__).order_by(
            OwnerRentReportOperationModel.report_id,
            OwnerRentReportOperationModel.result_revision,
            OwnerRentReportOperationModel.effective.desc(),
            OwnerRentReportOperationModel.created_at,
            OwnerRentReportOperationModel.id,
        )
    ).mappings()
    for row in rows:
        for name in ("id", "report_id", "idempotency_key", "correlation_id"):
            canonical_uuid(row[name])
        request, response = loads(row["request_json"]), loads(row["response_json"])
        validate_command_concurrency(request["expectedRevision"], row["idempotency_key"])
        if (
            canonical_json(request) != row["request_json"]
            or canonical_json(response) != row["response_json"]
            or fingerprint(row["request_json"]) != row["request_fingerprint"]
            or fingerprint(row["response_json"]) != row["response_fingerprint"]
            or set(request) != {"action", "reportId", "expectedRevision", "payload"}
            or request["action"] != row["action"]
            or request["reportId"] != (None if row["action"] == "create" else row["report_id"])
            or request["expectedRevision"] != row["expected_revision"]
            or response["operationId"] != row["id"]
            or response["id"] != row["report_id"]
            or response["reportRevision"] != row["result_revision"]
        ):
            raise ValueError("Owner command request or result was rewritten.")
        previous = histories.get(row["report_id"])
        if (
            row["expected_revision"] != (0 if previous is None else previous["reportRevision"])
            or row["result_revision"] != row["expected_revision"] + row["effective"]
            or (previous is None) != (row["action"] == "create")
            or (previous is not None and previous["status"] != "pending")
        ):
            raise ValueError("Owner command revision or lifecycle chain is invalid.")
        report_events = events.pop(
            ("owner_rent_report", row["report_id"], row["correlation_id"]), []
        )
        operation_events = events.pop(
            ("owner_rent_report_operation", row["id"], row["correlation_id"]), []
        )
        if len(report_events) != 1 or len(operation_events) != 1:
            raise ValueError("Owner command audit cardinality differs.")
        event, operation_event = report_events[0], operation_events[0]
        before = None if event["before_snapshot"] is None else loads(event["before_snapshot"])
        after = loads(event["after_snapshot"])
        if (
            event["action"]
            != {
                "create": "created",
                "patch": "patched",
                "verify": "verified",
                "reject": "rejected",
            }[row["action"]]
            or before != previous
            or operation_event["action"] != "recorded"
            or operation_event["before_snapshot"] is not None
            or loads(operation_event["after_snapshot"]) != dict(row)
            or any(after[name] != response[name] for name in reports[row["report_id"]])
        ):
            raise ValueError("Owner original response and correlated audit differ.")
        after.pop("verificationEvidence", None)
        if (
            row["effective"]
            and after["updatedAt"] != row["created_at"]
            or not row["effective"]
            and canonical_json(after) != canonical_json(before)
        ):
            raise ValueError("Owner command effect or timestamp differs.")
        histories[row["report_id"]] = after
    if canonical_json(histories) != canonical_json(reports) or events:
        raise ValueError("Owner current state differs from immutable command history.")

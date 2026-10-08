"""Exact schema and retained command history for current-format Leasing."""

from datetime import UTC, datetime
from json import loads
from uuid import UUID

from sqlalchemy import inspect

from app.modules.leases.api.router import (
    LeaseMutationResponse,
    TerminationCaseMutationResponse,
    TimelineLeaseResponse,
)
from app.modules.leases.application.commands import (
    COMMAND_ACTIONS,
    TIMELINE_ACTIONS,
    canonical_json,
    fingerprint,
    receipt_audit,
)
from app.modules.leases.infrastructure.command_triggers import LEASE_COMMAND_TRIGGERS
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseCommandOperationModel
from app.platform.migration_errors import MigrationSchemaError
from app.modules.portfolio.application.source_timeline import SourceTimelineOperationReader

BUSINESS_AUDITS = {
    "create": (("lease", "created"), ("lease_term", "created"), ("lease_participant", "created")),
    "patch": (("lease", "updated"),),
    "replace_initial_term": (("lease_term", "replaced"),),
    "add_participant": (("lease_participant", "created"),),
    "update_participant": (("lease_participant", "updated"),),
    "remove_participant": (("lease_participant", "deleted"),),
    "add_renewal_option": (("lease_renewal_option", "created"),),
    "update_renewal_option": (("lease_renewal_option", "updated"),),
    "decide_renewal_option": (("lease_renewal_option", "status_changed"),),
    "create_termination_case": (("lease_termination_case", "created"),),
    "add_termination_proposal": (
        ("lease_termination_proposal", "created"),
        ("lease_termination_case", "status_changed"),
    ),
    "accept_termination_proposal": (
        ("lease_termination_proposal", "accepted"),
        ("lease_termination_case", "accepted"),
    ),
    "transition_termination_case": (("lease_termination_case", "status_changed"),),
    "execute": (("lease", "executed"), ("space_occupancy", "created")),
    "ended": (("lease", "ended"), ("space_occupancy", "ended"), ("space_occupancy", "created")),
    "terminated": (
        ("lease", "terminated"),
        ("lease_termination_case", "completed"),
        ("space_occupancy", "ended"),
        ("space_occupancy", "created"),
    ),
    "complete_termination_case": (
        ("lease", "terminated"),
        ("lease_termination_case", "completed"),
        ("space_occupancy", "ended"),
        ("space_occupancy", "created"),
    ),
    "void": (("lease", "voided"), ("space_occupancy", "cancelled")),
}


def validate_lease_commands(connection, source_operations: SourceTimelineOperationReader) -> None:
    try:
        _schema(connection)
        _history(connection, source_operations)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise MigrationSchemaError(
            "LEASE-001 command schema or retained history is invalid."
        ) from error


def _schema(connection):
    table = LeaseCommandOperationModel.__table__
    inspector = inspect(connection)
    if not inspector.has_table(table.name):
        raise ValueError("Lease command receipts are missing.")
    columns = inspector.get_columns(table.name)
    if {column["name"] for column in columns} != set(table.columns.keys()):
        raise ValueError("Lease command columns differ.")
    for column in columns:
        expected = table.columns[column["name"]]
        if (
            bool(column["nullable"]) != expected.nullable
            or bool(column["primary_key"]) != expected.primary_key
            or str(column["type"]).upper() != str(expected.type).upper()
        ):
            raise ValueError("Lease command column definition differs.")
    uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)}
    if uniques != {("idempotency_key",)}:
        raise ValueError("Lease command keys must be unique.")
    indexes = {
        (item["name"], tuple(item["column_names"]), bool(item["unique"]))
        for item in inspector.get_indexes(table.name)
    }
    if indexes != {("lease_commands_lease_revision", ("lease_id", "result_revision"), True)}:
        raise ValueError("Lease revision index differs.")
    index = inspector.get_indexes(table.name)[0]
    if (
        str(index.get("dialect_options", {}).get("sqlite_where", "")).replace(" ", "")
        != "effective=1"
    ):
        raise ValueError("Lease revision index must exclude no-ops.")
    foreign_keys = {
        (
            tuple(item["constrained_columns"]),
            item["referred_table"],
            tuple(item["referred_columns"]),
        )
        for item in inspector.get_foreign_keys(table.name)
    }
    if foreign_keys != {(("lease_id",), "leases", ("id",))}:
        raise ValueError("Lease command references differ.")
    from app.modules.leases.infrastructure.schema_validation import _normalise

    checks = {_normalise(item["sqltext"]) for item in inspector.get_check_constraints(table.name)}
    expected_checks = {
        _normalise(str(item.sqltext)) for item in table.constraints if hasattr(item, "sqltext")
    }
    if checks != expected_checks:
        raise ValueError("Lease command checks differ.")
    triggers = dict(
        connection.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='lease_command_operations'"
        ).all()
    )
    if {key: _normalise(value) for key, value in triggers.items()} != {
        key: _normalise(value) for key, value in LEASE_COMMAND_TRIGGERS.items()
    }:
        raise ValueError("Lease receipt immutability differs.")


def _uuid(value):
    if str(UUID(value)) != value:
        raise ValueError("Noncanonical Lease identity.")


def _utc(value):
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() != UTC.utcoffset(instant):
        raise ValueError("Lease command timestamp must be UTC.")
    return instant


def _history(connection, source_operations):
    leases = {
        row["id"]: dict(row)
        for row in connection.exec_driver_sql("SELECT * FROM leases").mappings()
    }
    cases = dict(
        connection.exec_driver_sql("SELECT id, lease_id FROM lease_termination_cases").all()
    )
    audits = {}
    operation_audits = {}
    effects_by_correlation = {}
    business_by_correlation = {}
    for event in connection.exec_driver_sql(
        "SELECT * FROM audit_events WHERE entity_type IN ('lease', 'lease_command_operation', 'lease_term', 'lease_participant', 'lease_renewal_option', 'lease_termination_case', 'lease_termination_proposal', 'space_occupancy')"
    ).mappings():
        audits.setdefault((event["entity_type"], event["entity_id"], event["action"]), []).append(
            event
        )
        if event["entity_type"] == "lease_command_operation":
            operation_audits.setdefault(event["entity_id"], []).append(event)
        elif event["action"] == "command_applied":
            effects_by_correlation.setdefault(
                (event["entity_id"], event["correlation_id"]), []
            ).append(event)
        else:
            business_by_correlation.setdefault(event["correlation_id"], set()).add(
                (event["entity_type"], event["action"])
            )
    revisions = {}
    recorded_ids = set()
    for row in connection.exec_driver_sql(
        "SELECT * FROM lease_command_operations ORDER BY lease_id, result_revision, effective DESC, created_at, id"
    ).mappings():
        receipt = dict(row)
        recorded_ids.add(receipt["id"])
        for field in ("id", "lease_id", "correlation_id"):
            _uuid(receipt[field])
        if not receipt["idempotency_key"].strip() or len(receipt["idempotency_key"]) > 200:
            raise ValueError("Invalid command key.")
        committed = _utc(receipt["created_at"])
        request = loads(receipt["request_json"])
        response = loads(receipt["response_json"])
        if (
            canonical_json(request) != receipt["request_json"]
            or fingerprint(receipt["request_json"]) != receipt["request_fingerprint"]
            or canonical_json(response) != receipt["response_json"]
            or fingerprint(receipt["response_json"]) != receipt["response_fingerprint"]
        ):
            raise ValueError("Command payload was rewritten.")
        action = receipt["action"]
        expected = receipt["expected_revision"]
        revision = receipt["result_revision"]
        effective = receipt["effective"]
        previous = revisions.get(receipt["lease_id"], 0)
        if (
            action not in COMMAND_ACTIONS
            or expected != previous
            or type(effective) is not int
            or effective not in {0, 1}
            or revision != previous + effective
            or (previous == 0) != (action == "create")
        ):
            raise ValueError("Lease revision history is incomplete.")
        if effective and not set(BUSINESS_AUDITS[action]).issubset(
            business_by_correlation.get(receipt["correlation_id"], set())
        ):
            raise ValueError("Correlated Lease workflow audit evidence is incomplete.")
        if (
            set(request) != {"action", "targetKind", "targetId", "expectedLeaseRevision", "payload"}
            or request["action"] != action
            or request["expectedLeaseRevision"] != expected
            or type(request["expectedLeaseRevision"]) is not int
            or not isinstance(request["payload"], dict)
        ):
            raise ValueError("Command identity differs from its request.")
        lease = leases[receipt["lease_id"]]
        target = request["targetId"]
        _uuid(target)
        if request["targetKind"] == "space":
            valid_target = action == "create" and target == lease["space_id"]
        elif request["targetKind"] == "lease":
            valid_target = target == lease["id"] and action != "create"
        elif request["targetKind"] == "termination_case":
            valid_target = cases.get(target) == lease["id"]
        else:
            valid_target = False
        if not valid_target:
            raise ValueError("Command target is invalid.")
        if (
            response.get("leaseRevision") != revision
            or type(response.get("leaseRevision")) is not int
            or response.get("operationId") != receipt["id"]
        ):
            raise ValueError("Response identity differs.")
        if action in TIMELINE_ACTIONS:
            TimelineLeaseResponse.model_validate(response)
            source = source_operations.source_timeline_operation(
                connection, receipt["idempotency_key"]
            )
            if source is None:
                raise ValueError("Portfolio source receipt is missing.")
            recorded = loads(source["result_snapshot"])
            if (
                source["id"] != receipt["id"]
                or source["space_id"] != lease["space_id"]
                or source["created_at"] != receipt["created_at"]
                or recorded.get("consumerResult") != response
                or recorded.get("sourceKind") != "lease"
                or recorded.get("sourceId") != lease["id"]
                or recorded.get("action")
                != ("terminated" if action == "complete_termination_case" else action)
                or recorded.get("correlationId") != receipt["correlation_id"]
                or source["result_revision"] != response["revision"]
                or response["revision"] != request["payload"]["expectedSpaceRevision"] + 1
            ):
                raise ValueError("Lease and Portfolio receipts disagree.")
        elif response.get("leaseId") is not None:
            TerminationCaseMutationResponse.model_validate(response)
            if cases.get(response["id"]) != lease["id"] or response["leaseId"] != lease["id"]:
                raise ValueError("Termination result belongs to another lease.")
        else:
            LeaseMutationResponse.model_validate(response)
        if response.get("leaseId", response["id"]) != lease["id"]:
            raise ValueError("Response belongs to another lease.")
        if _utc(response["updatedAt"]) > committed:
            raise ValueError("Response timestamp follows commit.")
        events = audits.get(("lease_command_operation", receipt["id"], "recorded"), [])
        operation_events = operation_audits.get(receipt["id"], [])
        if (
            len(events) != 1
            or len(operation_events) != 1
            or events[0]["correlation_id"] != receipt["correlation_id"]
            or events[0]["before_snapshot"] is not None
            or loads(events[0]["after_snapshot"]) != receipt_audit(receipt)
        ):
            raise ValueError("Correlated receipt evidence is incomplete.")
        effects = effects_by_correlation.pop((lease["id"], receipt["correlation_id"]), [])
        if len(effects) != 1:
            raise ValueError("Correlated Lease effect is missing.")
        after = loads(effects[0]["after_snapshot"])
        before = (
            None if effects[0]["before_snapshot"] is None else loads(effects[0]["before_snapshot"])
        )
        if (
            after.get("leaseRevision") != revision
            or (effective == 1 and after.get("updatedAt") != receipt["created_at"])
            or (effective == 0 and after != before)
            or (previous == 0 and before is not None)
            or (previous > 0 and (before is None or before.get("leaseRevision") != previous))
        ):
            raise ValueError("Lease effect revision differs.")
        if previous > 0 and before != revisions[(lease["id"], "snapshot")]:
            raise ValueError("Lease command chain is discontinuous.")
        revisions[lease["id"]] = revision
        revisions[(lease["id"], "snapshot")] = after
        if "terms" in response:
            revisions[(lease["id"], "children")] = response
    if set(operation_audits) != recorded_ids or effects_by_correlation:
        raise ValueError("Command audit history has unsupported events.")
    from app.modules.leases.domain.models import Lease

    for lease_id, lease in leases.items():
        if (
            revisions.get(lease_id) != lease["lease_revision"]
            or revisions.get((lease_id, "snapshot")) != Lease(**lease).to_dict()
        ):
            raise ValueError("Current Lease differs from its immutable command history.")
    _validate_children(connection, revisions)


def _validate_children(connection, revisions):
    from app.modules.leases.domain.models import LeaseTerm, LeaseParticipant, LeaseRenewalOption

    for table, domain, key in (
        ("lease_term_versions", LeaseTerm, "terms"),
        ("lease_participants", LeaseParticipant, "participants"),
        ("lease_renewal_options", LeaseRenewalOption, "renewalOptions"),
    ):
        grouped = {}
        for row in connection.exec_driver_sql(f"SELECT * FROM {table}").mappings():
            grouped.setdefault(row["lease_id"], []).append(domain(**row).to_dict())
        for identity, snapshot in revisions.items():
            if not isinstance(identity, tuple) or identity[1] != "children":
                continue
            expected = sorted(snapshot[key], key=lambda item: item["id"])
            actual = sorted(grouped.get(identity[0], []), key=lambda item: item["id"])
            if expected != actual:
                raise ValueError("Current Lease children differ from command history.")

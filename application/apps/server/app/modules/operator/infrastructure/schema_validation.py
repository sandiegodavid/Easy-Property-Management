"""Exact OPS schema and correlated portable mutation history."""

import json
from datetime import timedelta

from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, select, text

from app.modules.operator.application.recovery_schemas import validate_payload
from app.modules.operator.application.ports import RecoveryBinding
from app.modules.operator.application.command_forms import COMMAND_SCHEMAS
from app.modules.operator.application.recovery_results import receipt_projection
from collections.abc import Mapping
from app.modules.operator.domain.models import (
    Preferences,
    canonical,
    fingerprint,
    identifier,
    utc,
    MAX_ACTIVE_RECOVERY,
    audit_metadata,
)
from app.modules.operator.infrastructure.sqlalchemy_models import (
    MODELS,
    APPEND_ONLY,
    OperatorOperationModel,
    OperatorRecoveryModel,
    OperatorPreferenceModel,
    OperatorCoverageReviewModel,
    trigger_sql,
)
from app.platform.migration_errors import MigrationSchemaError


def normalized(value):
    return "".join(str(value).lower().split())


def validate_operator_schema(connection):
    inspector = inspect(connection)
    for model in MODELS:
        table = model.__table__
        columns = inspector.get_columns(table.name)
        if {c["name"] for c in columns} != set(table.c.keys()) or any(
            str(c["type"]) != str(table.c[c["name"]].type)
            or (not c["primary_key"] and c["nullable"] != table.c[c["name"]].nullable)
            for c in columns
        ):
            raise MigrationSchemaError("Operator columns are incompatible.")
        if inspector.get_pk_constraint(table.name)["constrained_columns"] != ["id"]:
            raise MigrationSchemaError("Operator primary key is incompatible.")
        checks = {normalized(c["sqltext"]) for c in inspector.get_check_constraints(table.name)}
        if checks != {
            normalized(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)
        }:
            raise MigrationSchemaError("Operator checks are incompatible.")
        uniques = {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table.name)}
        if uniques != {
            tuple(c.name for c in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }:
            raise MigrationSchemaError("Operator uniqueness is incompatible.")
        indexes = {
            (c["name"], tuple(c["column_names"]), bool(c["unique"]))
            for c in inspector.get_indexes(table.name)
        }
        if indexes != {
            (c.name, tuple(col.name for col in c.columns), bool(c.unique)) for c in table.indexes
        }:
            raise MigrationSchemaError("Operator indexes are incompatible.")
        foreign = {
            (tuple(c["constrained_columns"]), c["referred_table"], tuple(c["referred_columns"]))
            for c in inspector.get_foreign_keys(table.name)
        }
        if foreign != {
            ((fk.parent.name,), fk.column.table.name, (fk.column.name,))
            for fk in table.foreign_keys
        }:
            raise MigrationSchemaError("Operator references are incompatible.")
        triggers = dict(
            connection.execute(
                text("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=:name"),
                {"name": table.name},
            ).all()
        )
        expected = (
            {
                f"{table.name}_no_{action.lower()}": normalized(trigger_sql(table.name, action))
                for action in ("UPDATE", "DELETE")
            }
            if table.name in APPEND_ONLY
            else {}
        )
        if {name: normalized(sql) for name, sql in triggers.items()} != expected:
            raise MigrationSchemaError("Operator history immutability is incompatible.")
    validate_operator_data(connection)


def portable_json(value):
    parsed = json.loads(value)
    if not isinstance(parsed, dict) or canonical(parsed) != value:
        raise ValueError("Noncanonical operator record.")
    return parsed


def validate_command_recovery(connection, bindings: Mapping[str, RecoveryBinding]):
    """Historical evidence: never apply today's lifecycle/revision to an old attempt."""
    if set(bindings) != set(COMMAND_SCHEMAS):
        raise MigrationSchemaError("Operator recovery binding registry is incomplete.")
    try:
        rows = connection.execute(
            select(OperatorRecoveryModel.__table__).where(
                OperatorRecoveryModel.form_key.in_(tuple(bindings))
            )
        ).mappings()
        for row in rows:
            binding = bindings[row["form_key"]]
            payload = portable_json(row["payload_json"])
            if row["source_kind"] != binding.source_kind:
                raise ValueError("Recovery has the wrong source kind.")
            if binding.source_kind is None:
                if row["source_id"] is not None or row["base_source_revision"] is not None:
                    raise ValueError("Creation form cannot retain official source state.")
            elif (
                row["source_id"] is None
                or not isinstance(row["base_source_revision"], str)
                or not row["base_source_revision"].isdecimal()
                or str(int(row["base_source_revision"])) != row["base_source_revision"]
            ):
                raise ValueError("Recovery source revision is invalid.")
            if row["attempt_key"] is not None:
                calculated = binding.fingerprint(row["source_id"], payload, row["attempt_key"])
                if calculated != row["request_fingerprint"]:
                    raise ValueError("Recovery attempt no longer matches its saved command.")
            if row["receipt_json"] is not None:
                receipt = portable_json(row["receipt_json"])
                outcome = binding.reader.outcome(
                    connection, row["attempt_key"], family=binding.family
                )
                if (
                    outcome is None
                    or receipt
                    != receipt_projection(outcome, binding.source_kind, row["attempt_key"])
                    or outcome.action != binding.receipt_action
                    or outcome.request_fingerprint != row["request_fingerprint"]
                    or (binding.source_kind is not None and outcome.source_id != row["source_id"])
                ):
                    raise ValueError("Reconciled recovery lost its original owning receipt.")
    except (ValueError, TypeError, KeyError) as error:
        raise MigrationSchemaError("Retained command recovery evidence is invalid.") from error


def validate_coverage_targets(connection, portfolio):
    """Retained target existence through its source owner, never OPS foreign SQL."""
    from app.platform.coverage import CoverageSubject

    for row in connection.execute(select(OperatorCoverageReviewModel.__table__)).mappings():
        subject = CoverageSubject(row["subject_kind"], row["subject_id"])
        if portfolio.location(connection, subject, as_of=utc(row["created_at"])) is None:
            raise MigrationSchemaError("Retained coverage target is missing.")


RECOVERY_FIELDS = {
    "id": "id",
    "formKey": "form_key",
    "schemaVersion": "schema_version",
    "revision": "revision",
    "status": "status",
    "sourceKind": "source_kind",
    "sourceId": "source_id",
    "baseSourceRevision": "base_source_revision",
    "attemptKey": "attempt_key",
    "requestFingerprint": "request_fingerprint",
    "savedAt": "saved_at",
    "expiresAt": "expires_at",
}
RECOVERY_PRIVATE_FIELDS = {"payload", "receipt", "attemptKey", "requestFingerprint"}


def validate_operator_data(connection):
    try:
        preferences = connection.execute(select(OperatorPreferenceModel.__table__)).mappings().all()
        recovery = {
            row["id"]: row
            for row in connection.execute(select(OperatorRecoveryModel.__table__)).mappings()
        }
        for row in preferences:
            value = Preferences(
                appearance=row["appearance"],
                destination_order=json.loads(row["destination_order"]),
                hidden_destination_ids=json.loads(row["hidden_destination_ids"]),
                revision=row["revision"],
                updated_at=row["updated_at"],
            )
            if (
                value.revision < 1
                or canonical(value.destination_order) != row["destination_order"]
                or canonical(value.hidden_destination_ids) != row["hidden_destination_ids"]
            ):
                raise ValueError("Invalid preferences.")
        active = 0
        for row in recovery.values():
            identifier(row["id"])
            payload = portable_json(row["payload_json"])
            if validate_payload(row["form_key"], row["schema_version"], payload) != payload:
                raise ValueError("Recovery payload is not normalized.")
            if row["source_id"] is not None:
                identifier(row["source_id"])
            if row["attempt_key"] is not None:
                identifier(row["attempt_key"])
                if len(row["request_fingerprint"]) != 64 or any(
                    c not in "0123456789abcdef" for c in row["request_fingerprint"]
                ):
                    raise ValueError("Invalid owning fingerprint.")
            if row["receipt_json"] is not None:
                receipt = portable_json(row["receipt_json"])
                if receipt["attemptKey"] != row["attempt_key"]:
                    raise ValueError("Receipt does not match attempt.")
            if utc(row["expires_at"]) != utc(row["saved_at"]) + timedelta(days=30):
                raise ValueError("Invalid acknowledged expiry.")
            active += row["status"] in {"active", "outcome_unknown", "reconciled"}
        if active > MAX_ACTIVE_RECOVERY:
            raise ValueError("Recovery capacity exceeded.")
        _validate_operations(connection, preferences, recovery)
        _validate_coverage_reviews(connection)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise MigrationSchemaError("Retained Operator data is invalid.") from error


def _validate_coverage_reviews(connection):
    from app.modules.operator.application.coverage_models import (
        CoverageReview,
        review_audit_snapshot,
    )
    from app.modules.operator.application.coverage_models import CoverageResult
    from datetime import date
    from zoneinfo import ZoneInfo

    events = {
        row["entity_id"]: row
        for row in connection.execute(
            text(
                "SELECT * FROM audit_events WHERE entity_type='operator_coverage_review' ORDER BY rowid"
            )
        ).mappings()
    }
    count = connection.execute(
        text("SELECT count(*) FROM audit_events WHERE entity_type='operator_coverage_review'")
    ).scalar_one()
    if count != len(events):
        raise ValueError("Duplicate coverage audit.")
    for row in connection.execute(select(OperatorCoverageReviewModel.__table__)).mappings():
        for key in ("id", "subject_id", "idempotency_key", "correlation_id"):
            identifier(row[key])
        utc(row["created_at"])
        request = portable_json(row["request_json"])
        command = CoverageReview.model_validate(
            {**request, "idempotency_key": row["idempotency_key"]}
        )
        if (
            command.model_dump(mode="json", exclude={"idempotency_key"}) != request
            or fingerprint(request) != row["request_fingerprint"]
        ):
            raise ValueError("Coverage request was rewritten.")
        for stored, requested in (
            ("subject_kind", "subject_kind"),
            ("subject_id", "subject_id"),
            ("area", "area"),
            ("evidence_revision", "expected_evidence_revision"),
            ("basis", "basis"),
            ("next_review_on", "next_review_on"),
        ):
            if row[stored] != request[requested]:
                raise ValueError("Coverage decision differs from its command.")
        if row["reason"] != command.reason.strip():
            raise ValueError("Review reason differs from its command.")
        result = portable_json(row["result_json"])
        CoverageResult.model_validate(result)
        if (
            result["effectiveLocalDate"]
            != utc(row["created_at"]).astimezone(ZoneInfo(row["time_zone"])).date().isoformat()
        ):
            raise ValueError("Coverage result lost its property-local date.")
        if any(
            result[key] != row[stored]
            for key, stored in (
                ("operationId", "id"),
                ("subjectKind", "subject_kind"),
                ("subjectId", "subject_id"),
                ("area", "area"),
                ("evidenceRevision", "evidence_revision"),
                ("asOf", "created_at"),
                ("lastManualReviewAt", "created_at"),
            )
        ):
            raise ValueError("Coverage replay result differs from decision.")
        if command.basis == "not_applicable" and result["state"] != "not_applicable":
            raise ValueError("Invalid historical non-applicability.")
        if row["next_review_on"] and date.fromisoformat(
            row["next_review_on"]
        ) <= date.fromisoformat(result["effectiveLocalDate"]):
            raise ValueError("Invalid review date.")
        event = events.pop(row["id"], None)
        expected = review_audit_snapshot(row, result)
        if (
            event is None
            or event["action"] != "recorded"
            or event["actor_kind"] != "local_operator"
            or event["correlation_id"] != row["correlation_id"]
            or event["occurred_at"] != row["created_at"]
            or event["before_snapshot"] is not None
            or json.loads(event["after_snapshot"]) != expected
        ):
            raise ValueError("Coverage audit evidence is incomplete.")
    if events:
        raise ValueError("Coverage audit lost its decision.")


def _validate_operations(connection, preferences, recovery):
    operations = (
        connection.execute(
            select(OperatorOperationModel.__table__).order_by(
                OperatorOperationModel.created_at, OperatorOperationModel.id
            )
        )
        .mappings()
        .all()
    )
    audit_rows = (
        connection.execute(
            text(
                "SELECT * FROM audit_events WHERE entity_type IN ('operator_operation','operator_preferences','operator_recovery','operator_coverage_review') ORDER BY rowid"
            )
        )
        .mappings()
        .all()
    )
    audit_by_operation = {}
    mutations = {}
    for event in audit_rows:
        key = (event["entity_type"], event["entity_id"], event["correlation_id"], event["action"])
        if key in mutations:
            raise ValueError("Duplicate operator audit evidence.")
        mutations[key] = event
        if event["entity_type"] == "operator_operation":
            if event["entity_id"] in audit_by_operation:
                raise ValueError("Duplicate receipt audit.")
            audit_by_operation[event["entity_id"]] = event
    revisions = {}
    latest = {}
    recovery_history = {}
    for row in operations:
        for key in ("id", "idempotency_key", "correlation_id"):
            identifier(row[key])
        utc(row["created_at"])
        request, result = portable_json(row["request_json"]), portable_json(row["result_json"])
        _validate_request_result(row, request, result)
        if row["entity_type"] == "operator_recovery":
            if (
                row["entity_id"] not in recovery
                or row["recovery_id"] != row["entity_id"]
                or result["id"] != row["entity_id"]
            ):
                raise ValueError("Recovery receipt lost its record.")
        elif row["entity_type"] == "operator_preferences":
            if row["entity_id"] != "workspace" or not preferences or row["recovery_id"] is not None:
                raise ValueError("Preference receipt lost its record.")
        if (
            fingerprint(request) != row["request_fingerprint"]
            or result["operationId"] != row["id"]
            or result["revision"] != row["resulting_revision"]
        ):
            raise ValueError("Invalid operation replay evidence.")
        if request["expectedRevision"] != row["expected_revision"]:
            raise ValueError("Command revision differs from receipt.")
        entity = (row["entity_type"], row["entity_id"])
        # Creation-time ties are ordered by the revision, not random operation UUIDs.
        revisions.setdefault(entity, []).append(row["expected_revision"])
        if entity not in latest or latest[entity]["resulting_revision"] < row["resulting_revision"]:
            latest[entity] = row
        event = audit_by_operation.pop(row["id"], None)
        if (
            event is None
            or event["action"] != "recorded"
            or event["correlation_id"] != row["correlation_id"]
            or event["occurred_at"] != row["created_at"]
        ):
            raise ValueError("Missing correlated operation audit.")
        if json.loads(event["after_snapshot"]) != {
            "entityType": row["entity_type"],
            "entityId": row["entity_id"],
            "action": row["action"],
            "revision": row["resulting_revision"],
        }:
            raise ValueError("Receipt audit was rewritten.")
        change = mutations.get(
            (row["entity_type"], row["entity_id"], row["correlation_id"], row["action"])
        )
        if (
            change is None
            or change["occurred_at"] != row["created_at"]
            or change["actor_kind"] != "local_operator"
        ):
            raise ValueError("Missing correlated record mutation.")
        expected = audit_metadata(result)
        if json.loads(change["after_snapshot"]) != expected:
            raise ValueError("Mutation snapshot differs from recorded result.")
        if row["entity_type"] == "operator_recovery":
            recovery_history.setdefault(row["entity_id"], []).append((row, request, result, change))
    if audit_by_operation:
        raise ValueError("Operator audit lost its receipt.")
    for entity, values in revisions.items():
        if sorted(values) != list(range(len(values))):
            raise ValueError("Operator revision history is incomplete.")
    for history in recovery_history.values():
        _validate_recovery_history(history)
    for row in preferences:
        operation = latest.get(("operator_preferences", "workspace"))
        if operation is None or operation["resulting_revision"] != row["revision"]:
            raise ValueError("Preference history is incomplete.")
        result = json.loads(operation["result_json"])
        if (
            any(
                result[api] != row[stored]
                for api, stored in (
                    ("appearance", "appearance"),
                    ("revision", "revision"),
                    ("updatedAt", "updated_at"),
                )
            )
            or canonical(result["destinationOrder"]) != row["destination_order"]
            or canonical(result["hiddenDestinationIds"]) != row["hidden_destination_ids"]
        ):
            raise ValueError("Preferences differ from recorded state.")
    for row in recovery.values():
        operation = latest.get(("operator_recovery", row["id"]))
        if operation is None or operation["resulting_revision"] != row["revision"]:
            raise ValueError("Recovery history is incomplete.")
        result = json.loads(operation["result_json"])
        if (
            any(result[api] != row[stored] for api, stored in RECOVERY_FIELDS.items())
            or canonical(result["payload"]) != row["payload_json"]
            or (canonical(result["receipt"]) if result["receipt"] is not None else None)
            != row["receipt_json"]
        ):
            raise ValueError("Recovery state differs from recorded result.")


def _validate_recovery_history(history):
    previous = None
    for row, request, result, change in sorted(
        history, key=lambda item: item[0]["resulting_revision"]
    ):
        state = {key: result[key] for key in (*RECOVERY_FIELDS, "payload", "receipt")}
        before = json.loads(change["before_snapshot"]) if change["before_snapshot"] else None
        expected_before = (
            {key: value for key, value in previous.items() if key not in RECOVERY_PRIVATE_FIELDS}
            if previous is not None
            else None
        )
        if before != expected_before:
            raise ValueError("Recovery mutation does not follow its recorded predecessor.")
        if (
            validate_payload(state["formKey"], state["schemaVersion"], state["payload"])
            != state["payload"]
        ):
            raise ValueError("Invalid historical recovery payload.")
        if utc(state["expiresAt"]) != utc(state["savedAt"]) + timedelta(days=30):
            raise ValueError("Invalid historical recovery expiry.")
        kind = request["kind"]
        if kind == "recovery_save":
            if previous is not None and (
                previous["status"] != "active" or previous["formKey"] != state["formKey"]
            ):
                raise ValueError("Recovery save cannot overwrite this predecessor.")
            if any(
                state[key] is not None for key in ("attemptKey", "requestFingerprint", "receipt")
            ):
                raise ValueError("Recovery save contains unacknowledged attempt evidence.")
        else:
            if previous is None:
                raise ValueError("Recovery transition has no saved predecessor.")
            permitted = {
                "recovery_attempt": {"active"},
                "recovery_reconciled": {"outcome_unknown"},
                "recovery_discarded": {"active", "reconciled"},
                "recovery_expire": {"active", "reconciled"},
            }
            if previous["status"] not in permitted[kind]:
                raise ValueError("Illegal recovery lifecycle transition.")
            changed = {"revision", "status"}
            if kind == "recovery_attempt":
                changed.update(("attemptKey", "requestFingerprint"))
                identifier(state["attemptKey"])
                if (
                    utc(row["created_at"]) >= utc(previous["expiresAt"])
                    or len(state["requestFingerprint"]) != 64
                    or any(c not in "0123456789abcdef" for c in state["requestFingerprint"])
                ):
                    raise ValueError("Invalid historical owning attempt.")
            elif kind == "recovery_reconciled":
                changed.add("receipt")
                if (
                    not isinstance(state["receipt"], dict)
                    or state["receipt"].get("attemptKey") != previous["attemptKey"]
                ):
                    raise ValueError("Reconciliation receipt differs from its owning attempt.")
            elif kind == "recovery_expire" and utc(row["created_at"]) < utc(previous["expiresAt"]):
                raise ValueError("Recovery expired before its acknowledged deadline.")
            if any(state[key] != previous[key] for key in state.keys() - changed):
                raise ValueError("Recovery transition rewrote preserved evidence.")
        previous = state


def _validate_request_result(row, request, result):
    kinds = {
        "preferences": "updated",
        "recovery_save": "saved",
        "recovery_attempt": "saved",
        "recovery_discarded": "discarded",
        "recovery_reconciled": "reconciled",
        "recovery_expire": "expired",
    }
    if kinds.get(request.get("kind")) != row["action"]:
        raise ValueError("Operation action differs from its command.")
    if row["entity_type"] == "operator_preferences":
        if (
            set(request) != {"kind", "value", "expectedRevision"}
            or request["kind"] != "preferences"
        ):
            raise ValueError("Invalid preference command.")
        value = Preferences.model_validate(request["value"])
        if (
            result["appearance"] != value.appearance
            or result["destinationOrder"] != list(value.destination_order)
            or result["hiddenDestinationIds"] != list(value.hidden_destination_ids)
            or result["updatedAt"] != row["created_at"]
        ):
            raise ValueError("Preference result differs from its request.")
        return
    if request["id"] != row["entity_id"] or result["asOf"] != row["created_at"]:
        raise ValueError("Recovery result differs from its operation identity or instant.")
    if request["kind"] == "recovery_save":
        payload = validate_payload(request["formKey"], request["schemaVersion"], request["payload"])
        for key in ("formKey", "schemaVersion", "sourceKind", "sourceId", "baseSourceRevision"):
            if request[key] != result[key]:
                raise ValueError("Recovery result differs from its source command.")
        if (
            payload != result["payload"]
            or result["savedAt"] != row["created_at"]
            or result["status"] != "active"
        ):
            raise ValueError("Recovery save does not match its acknowledgment.")
    elif request["kind"] == "recovery_attempt":
        if (
            result["status"] != "outcome_unknown"
            or result["attemptKey"] != request["attemptKey"]
            or (
                request["requestFingerprint"] is not None
                and result["requestFingerprint"] != request["requestFingerprint"]
            )
            or (request["requestFingerprint"] is None and result["formKey"] not in COMMAND_SCHEMAS)
        ):
            raise ValueError("Recovery attempt differs from its receipt.")
    else:
        status = {"discarded": "discarded", "reconciled": "reconciled", "expired": "expired"}[
            row["action"]
        ]
        if result["status"] != status:
            raise ValueError("Recovery transition differs from its receipt.")

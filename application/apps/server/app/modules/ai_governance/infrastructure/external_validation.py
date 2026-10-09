"""Portable external intent/result history is not a device-readiness assertion."""

import json
from datetime import datetime

from sqlalchemy import select, text

from app.modules.ai_governance.application.commands import command_json
from app.modules.ai_governance.application.external_effects import (
    external_fingerprint,
    external_request,
    external_view,
)
from app.modules.ai_governance.domain.models import validate_uuid
from app.modules.ai_governance.infrastructure.sqlalchemy_models import AiExternalOperationModel
from app.platform.migration_errors import MigrationSchemaError


def _stamp(value):
    parsed = datetime.fromisoformat(value)
    if (
        parsed.tzinfo is None
        or parsed.utcoffset().total_seconds() != 0
        or parsed.isoformat() != value
    ):
        raise ValueError("Invalid UTC timestamp")
    return parsed


def validate_external_operations(connection):
    pending = set()
    streams = {}
    credential_audits = set()
    for row in connection.execute(select(AiExternalOperationModel.__table__)).mappings():
        try:
            for key in ("id", "idempotency_key", "connection_id", "correlation_id"):
                if validate_uuid(row[key], key) != row[key]:
                    raise ValueError("Noncanonical UUID")
            created = _stamp(row["created_at"])
            if row["request_json"] != external_request(
                row["action"], row["connection_id"], row["expected_revision"]
            ):
                raise ValueError("Invalid intent")
            if row["request_fingerprint"] != external_fingerprint(
                row["action"], row["connection_id"], row["expected_revision"]
            ):
                raise ValueError("Invalid fingerprint")
            revision = connection.execute(
                text("SELECT revision FROM ai_model_connections WHERE id=:id"),
                {"id": row["connection_id"]},
            ).scalar_one()
            if revision < row["revision"] or row["revision"] != row["expected_revision"] + 1:
                raise ValueError("Impossible connection revision")
            reserved = (
                connection.execute(
                    text(
                        "SELECT * FROM audit_events WHERE entity_type='ai_model_connection' AND action='external_reserved' AND id=:id"
                    ),
                    {"id": row["id"]},
                )
                .mappings()
                .one()
            )
            before = json.loads(reserved["before_snapshot"])
            after = json.loads(reserved["after_snapshot"])
            if (
                reserved["entity_id"] != row["connection_id"]
                or reserved["correlation_id"] != row["correlation_id"]
                or before["revision"] != row["expected_revision"]
                or after != {**before, "revision": row["revision"], "updated_at": row["created_at"]}
            ):
                raise ValueError("Invalid reservation revision audit")
            streams.setdefault(("ai_model_connection", row["connection_id"]), []).append(
                (reserved["occurred_at"], reserved["id"], before, after)
            )
            initial = {**row, "result_json": None, "completed_at": None}
            expected_events = [("intent_recorded", None, external_view(initial))]
            result = None if row["result_json"] is None else json.loads(row["result_json"])
            if result is None:
                if row["completed_at"] is not None or row["connection_id"] in pending:
                    raise ValueError("Invalid pending external operation")
                pending.add(row["connection_id"])
            else:
                if (
                    _stamp(row["completed_at"]) < created
                    or command_json(result) != row["result_json"]
                ):
                    raise ValueError("Invalid terminal time or canonical result")
                status = result.get("status")
                if status == "abandoned":
                    if result != {"status": "abandoned"}:
                        raise ValueError("Invalid abandoned result")
                elif status == "completed":
                    if row["action"] == "connection_probe":
                        if (
                            set(result) != {"status", "ready", "reason"}
                            or type(result["ready"]) is not bool
                        ):
                            raise ValueError("Invalid probe result")
                        if (result["ready"] and result["reason"] is not None) or (
                            not result["ready"]
                            and result["reason"]
                            not in {
                                "connection_disabled",
                                "credential_unavailable",
                                "provider_unavailable",
                            }
                        ):
                            raise ValueError("Invalid probe reason")
                    else:
                        if set(result) != {
                            "status",
                            "beforePresent",
                            "afterPresent",
                            "credentialAction",
                        } or any(
                            type(result[k]) is not bool for k in ("beforePresent", "afterPresent")
                        ):
                            raise ValueError("Invalid credential result")
                        action = (
                            "credential_deleted"
                            if row["action"] == "credential_delete"
                            else "credential_replaced"
                            if result["beforePresent"]
                            else "credential_set"
                        )
                        if result["credentialAction"] != action or result["afterPresent"] != (
                            row["action"] == "credential_set"
                        ):
                            raise ValueError("Invalid credential effect")
                        effects = (
                            connection.execute(
                                text(
                                    "SELECT * FROM audit_events WHERE entity_type='ai_model_connection' AND entity_id=:id AND correlation_id=:correlation AND action=:action"
                                ),
                                {
                                    "id": row["connection_id"],
                                    "correlation": row["correlation_id"],
                                    "action": action,
                                },
                            )
                            .mappings()
                            .all()
                        )
                        if (
                            len(effects) != 1
                            or json.loads(effects[0]["before_snapshot"])
                            != {
                                "id": row["connection_id"],
                                "credentialPresent": result["beforePresent"],
                            }
                            or json.loads(effects[0]["after_snapshot"])
                            != {
                                "id": row["connection_id"],
                                "credentialPresent": result["afterPresent"],
                            }
                        ):
                            raise ValueError("Missing credential audit")
                        credential_audits.add(effects[0]["id"])
                else:
                    raise ValueError("Invalid external status")
                expected_events.append((status, external_view(initial), external_view(row)))
            events = (
                connection.execute(
                    text(
                        "SELECT * FROM audit_events WHERE entity_type='ai_external_operation' AND entity_id=:id ORDER BY occurred_at,id"
                    ),
                    {"id": row["id"]},
                )
                .mappings()
                .all()
            )
            if len(events) != len(expected_events):
                raise ValueError("Incomplete external history")
            for event, (action, before, after) in zip(events, expected_events, strict=True):
                if (
                    event["action"] != action
                    or event["actor_kind"] != "local_operator"
                    or event["correlation_id"] != row["correlation_id"]
                    or (
                        None
                        if event["before_snapshot"] is None
                        else json.loads(event["before_snapshot"])
                    )
                    != before
                    or json.loads(event["after_snapshot"]) != after
                ):
                    raise ValueError("Invalid correlated external audit")
        except Exception as error:
            raise MigrationSchemaError("AI external operation history is invalid.") from error
    retained_ids = {event[1] for history in streams.values() for event in history}
    audited_ids = set(
        connection.execute(
            text(
                "SELECT id FROM audit_events WHERE entity_type='ai_model_connection' AND action='external_reserved'"
            )
        ).scalars()
    )
    if retained_ids != audited_ids:
        raise MigrationSchemaError("AI external reservation receipts are incomplete.")
    if credential_audits != set(
        connection.execute(
            text(
                "SELECT id FROM audit_events WHERE entity_type='ai_model_connection' AND action IN ('credential_set','credential_replaced','credential_deleted')"
            )
        ).scalars()
    ):
        raise MigrationSchemaError("AI credential audits lack completed external receipts.")
    return streams

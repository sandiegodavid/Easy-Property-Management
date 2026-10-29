"""Credential-free control-plane projection for the private encrypted host artifact.

This is not a business backup or an unencrypted output command. The private
archive adapter must encrypt this projection; usable authority is never exported.
"""

import json

from app.modules.hosted_admin.application.contracts import AdminError, CommandRequest
from app.modules.hosted_admin.application.operations import (
    OperationIntent,
    StepResult,
    canonical,
    fingerprint,
)
from app.modules.hosted_admin.application.qualification import QualificationPlan
from app.modules.hosted_admin.infrastructure.operations import STEPS

TABLES = (
    "operation_target",
    "operation",
    "operation_step",
    "reservation",
    "setup_draft",
    "operation_audit",
    "admission",
    "capacity",
    "qualification",
    "qualification_evidence",
    "qualification_receipt",
    "audit",
)
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


def validate_control(connection):
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise AdminError("admin_control_data_invalid", 503)
    for row in connection.execute("SELECT * FROM operation"):
        payload = json.loads(row["payload"])
        if canonical(payload) != row["payload"] or fingerprint(payload) != row["request_hash"]:
            raise AdminError("admin_control_data_invalid", 503)
        if row["kind"] == "source":
            cmd = CommandRequest.model_validate(
                {
                    key: value
                    for key, value in payload.items()
                    if key not in {"authority_reference", "source_reference"}
                }
            )
            if (
                cmd.operation_id != row["id"]
                or cmd.instance != row["target"]
                or not payload.get("authority_reference")
            ):
                raise AdminError("admin_control_data_invalid", 503)
            receipt = connection.execute(
                "SELECT result FROM admission WHERE id=?", (row["id"],)
            ).fetchone()
            if receipt is None or receipt[0] != row["result"]:
                raise AdminError("admin_control_data_invalid", 503)
        else:
            intent = OperationIntent.model_validate(
                {
                    key: value
                    for key, value in payload.items()
                    if key not in {"allocation_spec", "setup"}
                }
            )
            retained = connection.execute(
                "SELECT kind,identity,amount FROM reservation WHERE operation_id=? ORDER BY kind",
                (row["id"],),
            ).fetchall()
            if [dict(item) for item in retained] != payload.get("allocation_spec"):
                raise AdminError("admin_control_data_invalid", 503)
            if (intent.operation_id, intent.kind, intent.target) != (
                row["id"],
                row["kind"],
                row["target"],
            ):
                raise AdminError("admin_control_data_invalid", 503)
        steps = connection.execute(
            "SELECT * FROM operation_step WHERE operation_id=? ORDER BY sequence", (row["id"],)
        ).fetchall()
        if [step["kind"] for step in steps] != list(STEPS[row["kind"]]):
            raise AdminError("admin_control_data_invalid", 503)
        seen_pending = False
        for sequence, step in enumerate(steps):
            if step["sequence"] != sequence or step["spec_hash"] != fingerprint(
                {"request": row["request_hash"], "step": step["kind"]}
            ):
                raise AdminError("admin_control_data_invalid", 503)
            if step["state"] == "verified":
                StepResult.model_validate_json(step["result"] or "null")
                if seen_pending or step["checked"] is None or step["result"] is None:
                    raise AdminError("admin_control_data_invalid", 503)
            else:
                seen_pending = True
                if step["checked"] is not None or step["result"] is not None:
                    raise AdminError("admin_control_data_invalid", 503)
        if (row["state"] == "succeeded") != (not seen_pending) or (row["state"] == "succeeded") != (
            row["result"] is not None
        ):
            raise AdminError("admin_control_data_invalid", 503)
        events = connection.execute(
            "SELECT action FROM operation_audit WHERE operation_id=? ORDER BY sequence",
            (row["id"],),
        ).fetchall()
        if (
            not events
            or events[0][0] != "admitted"
            or (row["state"] == "succeeded" and events[-1][0] != "completed")
        ):
            raise AdminError("admin_control_data_invalid", 503)
    for row in connection.execute("SELECT * FROM qualification"):
        plan = QualificationPlan.model_validate_json(row["payload"])
        if not connection.execute(
            "SELECT 1 FROM audit WHERE action='qualification_planned' AND reference=?", (plan.id,)
        ).fetchone():
            raise AdminError("admin_control_data_invalid", 503)
        if (
            plan.id != row["id"]
            or plan.fingerprint() != row["request_hash"]
            or canonical(plan.model_dump()) != row["payload"]
        ):
            raise AdminError("admin_control_data_invalid", 503)

    from app.modules.hosted_admin.application.setup import SetupData, SetupPlan
    from uuid import UUID

    for row in connection.execute("SELECT * FROM setup_draft"):
        data = SetupData.model_validate_json(row["data"])
        if (
            str(UUID(row["id"])) != row["id"]
            or not row["identity"].strip()
            or row["saved"] < 0
            or canonical(data.model_dump()) != row["data"]
        ):
            raise AdminError("admin_control_data_invalid", 503)
        required_audit = (
            "setup_started"
            if row["state"] == "started"
            else "setup_discarded"
            if row["state"] == "discarded"
            else "setup_saved"
        )
        if not connection.execute(
            "SELECT 1 FROM audit WHERE reference=? AND action=?", (row["id"], required_audit)
        ).fetchone():
            raise AdminError("admin_control_data_invalid", 503)
        if row["state"] == "started":
            data.ready()
            plan = SetupPlan.model_validate_json(row["plan"])
            if canonical(plan.model_dump()) != row["plan"]:
                raise AdminError("admin_control_data_invalid", 503)
            operation = connection.execute(
                "SELECT payload FROM operation WHERE id=?", (row["operation_id"],)
            ).fetchone()
            setup = json.loads(operation[0]).get("setup", {}) if operation else {}
            if setup != {
                "draft_id": row["id"],
                "data": data.model_dump(),
                "plan": json.loads(row["plan"]),
            }:
                raise AdminError("admin_control_data_invalid", 503)


def snapshot_control(store):
    with store.transaction() as connection:
        validate_control(connection)
        identity = store._identity(connection)
        result = {
            "format": 1,
            "identity": identity["id"],
            "generation": identity["generation"],
            "tables": {
                name: [dict(row) for row in connection.execute(f"SELECT * FROM {name}")]
                for name in TABLES
            },
        }
    encoded = canonical(result).encode()
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise AdminError("admin_control_snapshot_too_large", 413)
    return encoded


def restore_control(store, encoded):
    """Import only into a new empty private authority store; leave identity disabled."""
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise AdminError("admin_control_snapshot_too_large", 413)
    value = json.loads(encoded)
    if (
        set(value) != {"format", "identity", "generation", "tables"}
        or value["format"] != 1
        or set(value["tables"]) != set(TABLES)
        or type(value["generation"]) is not int
        or value["generation"] < 1
    ):
        raise AdminError("admin_control_snapshot_invalid", 409)
    with store.transaction() as connection:
        current = store._identity(connection)
        if value["identity"] != current["id"] or any(
            connection.execute(f"SELECT 1 FROM {name} LIMIT 1").fetchone()
            for name in (*TABLES, "grant", "session", "authorization")
        ):
            raise AdminError("admin_control_restore_not_empty", 409)
        for name in TABLES:
            expected = {row[1] for row in connection.execute(f"PRAGMA table_info({name})")}
            for row in value["tables"][name]:
                if set(row) != expected:
                    raise AdminError("admin_control_snapshot_invalid", 409)
                columns = sorted(expected)
                placeholders = ",".join("?" for _ in columns)
                connection.execute(
                    f"INSERT INTO {name} ({','.join(columns)}) VALUES ({placeholders})",
                    tuple(row[key] for key in columns),
                )
        validate_control(connection)
        connection.execute(
            "UPDATE administrator SET generation=?,enabled=0", (value["generation"] + 1,)
        )
        connection.execute(
            "UPDATE operation SET state='paused',claim=NULL,claim_until=NULL,error='admin_restore_review_required',revision=revision+1 WHERE state NOT IN ('succeeded','cancelled')"
        )
        connection.execute(
            "UPDATE qualification SET state='aborted',revision=revision+1 WHERE state IN ('planned','running')"
        )
        connection.execute("UPDATE capacity SET ceiling=0,revision=revision+1")
        store._audit(connection, "control_restored_fenced", current["id"])

"""Validate retained batch plans, decisions, admitted children and outcomes."""

import json

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import canonical
from app.modules.hosted_admin.application.upgrade_batches import BatchCommand, child_identity
from app.modules.hosted_admin.application.upgrades import UpgradePlan
from app.modules.hosted_admin.infrastructure.batch_history import FIELDS


def validate_batches(connection):
    """Validate the retained graph independently of mutable runtime readiness."""
    for batch in connection.execute("SELECT * FROM upgrade_batch"):
        validate_events(connection, batch)
        validate_admissions(connection, batch)
        original = BatchCommand.model_validate_json(batch["request"])
        if (
            original.action != "check"
            or original.id != batch["id"]
            or canonical(original.model_dump()) != batch["request"]
        ):
            raise AdminError("admin_batch_history_invalid", 503)
        members = connection.execute(
            "SELECT * FROM upgrade_batch_member WHERE batch_id=? ORDER BY sequence", (batch["id"],)
        ).fetchall()
        if [(row["instance"], row["expected_revision"]) for row in members] != [
            (row.instance, row.expected_revision) for row in original.members
        ] or [row["sequence"] for row in members] != list(range(len(members))):
            raise AdminError("admin_batch_membership_invalid", 503)
        attempt = connection.execute(
            "SELECT request,batch_id FROM upgrade_batch_command WHERE id=?", (batch["attempt"],)
        ).fetchone()
        if (
            not attempt
            or attempt["batch_id"] != batch["id"]
            or BatchCommand.model_validate_json(attempt["request"]).action
            not in {"check", "recheck"}
        ):
            raise AdminError("admin_batch_readiness_invalid", 503)
        if batch["run_command"]:
            command = connection.execute(
                "SELECT request,batch_id FROM upgrade_batch_command WHERE id=?",
                (batch["run_command"],),
            ).fetchone()
            if not command or command["batch_id"] != batch["id"]:
                raise AdminError("admin_batch_authorization_invalid", 503)
            run = BatchCommand.model_validate_json(command["request"])
            if run.action not in {"start", "resume"} or [row.instance for row in run.sessions] != [
                row["instance"] for row in members
            ]:
                raise AdminError("admin_batch_authorization_invalid", 503)
        active = 0
        for row in members:
            if row["child_id"] is None:
                continue
            operation = connection.execute(
                "SELECT * FROM operation WHERE id=?", (row["child_id"],)
            ).fetchone()
            if not batch["run_command"] or not operation:
                raise AdminError("admin_batch_child_invalid", 503)
            if not connection.execute(
                "SELECT 1 FROM upgrade_batch_child WHERE child_id=? AND batch_id=? AND sequence=?",
                (row["child_id"], batch["id"], row["sequence"]),
            ).fetchone():
                raise AdminError("admin_batch_child_invalid", 503)
            execution = json.loads(operation["payload"])
            if (
                row["child_id"] != child_identity(batch["id"], row["instance"])
                or operation["kind"] != "upgrade"
                or operation["identity"] != batch["identity"]
                or execution["instance"] != row["instance"]
                or execution["plan"]["target"]["release"] != original.release
            ):
                raise AdminError("admin_batch_child_invalid", 503)
            if not connection.execute(
                "SELECT 1 FROM audit WHERE action='upgrade_batch_child_admitted' AND reference=?",
                (row["child_id"],),
            ).fetchone():
                raise AdminError("admin_batch_child_invalid", 503)
            active += int(
                operation["state"] not in {"succeeded", "cancelled"}
                and not operation["cancel_requested"]
            )
        if active > 1:
            raise AdminError("admin_batch_multiple_children", 503)
        if batch["state"] in {"completed", "mixed"} and (
            not batch["run_command"]
            or (batch["state"] == "mixed") != any(row["skipped"] for row in members)
            or any(
                not row["skipped"]
                and (
                    row["child_id"] is None
                    or connection.execute(
                        "SELECT state FROM operation WHERE id=?", (row["child_id"],)
                    ).fetchone()[0]
                    != "succeeded"
                )
                for row in members
            )
        ):
            raise AdminError("admin_batch_outcome_invalid", 503)
        for member in members:
            if not member["skipped"]:
                continue
            decisions = [
                BatchCommand.model_validate_json(row[0])
                for row in connection.execute(
                    "SELECT request FROM upgrade_batch_command WHERE batch_id=?", (batch["id"],)
                )
            ]
            if member["child_id"]:
                contained = connection.execute(
                    "SELECT 1 FROM upgrade_batch_skip WHERE child_id=? AND state='completed'",
                    (member["child_id"],),
                ).fetchone()
                rolled_back = connection.execute(
                    "SELECT 1 FROM operation WHERE kind='upgrade_rollback' AND json_extract(payload,'$.parent')=? AND state='succeeded'",
                    (member["child_id"],),
                ).fetchone()
                if not contained and not (
                    rolled_back
                    and any(
                        command.action == "skip" and command.instance == member["instance"]
                        for command in decisions
                    )
                ):
                    raise AdminError("admin_batch_skip_invalid", 503)
            elif not any(
                command.action == "cancel"
                or (command.action == "skip" and command.instance == member["instance"])
                for command in decisions
            ):
                raise AdminError("admin_batch_skip_invalid", 503)
        if batch["state"] == "completed" and (
            not batch["run_command"]
            or any(
                row["skipped"]
                or row["child_id"] is None
                or connection.execute(
                    "SELECT state FROM operation WHERE id=?", (row["child_id"],)
                ).fetchone()[0]
                != "succeeded"
                for row in members
            )
        ):
            raise AdminError("admin_batch_outcome_invalid", 503)
    for row in connection.execute("SELECT * FROM upgrade_batch_command"):
        command = BatchCommand.model_validate_json(row["request"])
        batch = connection.execute(
            "SELECT identity,revision FROM upgrade_batch WHERE id=?", (row["batch_id"],)
        ).fetchone()
        result = json.loads(row["result"])
        if (
            command.id != row["id"]
            or (command.id if command.action == "check" else command.batch) != row["batch_id"]
            or row["identity"] != batch["identity"]
            or canonical(command.model_dump()) != row["request"]
            or canonical(result) != row["result"]
            or set(result) != {"id", "state", "revision"}
            or result["id"] != row["batch_id"]
            or type(result["revision"]) is not int
            or not 1 <= result["revision"] <= batch["revision"]
        ):
            raise AdminError("admin_batch_receipt_invalid", 503)
        if not connection.execute(
            "SELECT 1 FROM audit WHERE action=? AND reference=?",
            ("upgrade_batch_" + command.action, command.id),
        ).fetchone():
            raise AdminError("admin_batch_audit_missing", 503)
    for row in connection.execute(
        "SELECT r.*,m.instance,m.expected_revision,b.request FROM upgrade_batch_readiness r JOIN upgrade_batch_member m ON m.batch_id=r.batch_id AND m.sequence=r.sequence JOIN upgrade_batch b ON b.id=r.batch_id"
    ):
        if row["observed"] < 0:
            raise AdminError("admin_batch_readiness_invalid", 503)
        if row["plan"]:
            plan = UpgradePlan.model_validate_json(row["plan"])
            if (
                canonical(plan.model_dump()) != row["plan"]
                or plan.instance.key != row["instance"]
                or plan.instance.revision != row["expected_revision"]
                or plan.target.release != BatchCommand.model_validate_json(row["request"]).release
                or not plan.target.eligible
            ):
                raise AdminError("admin_batch_readiness_invalid", 503)


TRANSITIONS = {
    "check": ({None}, {"checking"}),
    "recheck": ({"ready", "blocked", "paused"}, {"checking"}),
    "start": ({"ready"}, {"running"}),
    "resume": ({"ready"}, {"running"}),
    "pause": ({"checking", "ready", "blocked", "running", "paused"}, {"paused"}),
    "cancel": ({"checking", "ready", "blocked", "running", "paused"}, {"cancelled"}),
    "skip": (
        {"checking", "ready", "blocked", "running", "paused", "cancelled"},
        {"paused", "cancelled"},
    ),
    "blocked": ({"checking", "running"}, {"blocked"}),
    "readiness_finished": ({"checking"}, {"ready", "blocked"}),
    "child_admitted": ({"running"}, {"running"}),
    "finished": ({"running"}, {"completed", "mixed"}),
    "restore_fenced": ({"checking", "ready", "blocked", "running", "paused"}, {"paused"}),
}


def validate_events(connection, batch):
    prior = None
    events = connection.execute(
        "SELECT * FROM upgrade_batch_event WHERE batch_id=? ORDER BY revision", (batch["id"],)
    ).fetchall()
    for index, event in enumerate(events, 1):
        value = json.loads(event["payload"])
        action = event["action"]
        if (
            event["revision"] != index
            or set(value) != set(FIELDS)
            or value["revision"] != index
            or canonical(value) != event["payload"]
            or event["recorded"] < 0
        ):
            raise AdminError("admin_batch_events_invalid", 503)
        if action in {"skip_completed", "skip_failed"}:
            if prior is None or prior["state"] != value["state"]:
                raise AdminError("admin_batch_events_invalid", 503)
        else:
            before, after = TRANSITIONS.get(action, (set(), set()))
            if (prior["state"] if prior else None) not in before or value["state"] not in after:
                raise AdminError("admin_batch_transition_invalid", 503)
        if prior:
            if value["attempt"] != prior["attempt"] and action != "recheck":
                raise AdminError("admin_batch_events_invalid", 503)
            if value["run_command"] != prior["run_command"] and action not in {"start", "resume"}:
                raise AdminError("admin_batch_events_invalid", 503)
            if value["generation"] != prior["generation"] and action not in {
                "recheck",
                "start",
                "resume",
            }:
                raise AdminError("admin_batch_events_invalid", 503)
        if action in {"check", "recheck", "start", "resume", "pause", "cancel", "skip"}:
            row = connection.execute(
                "SELECT request,result FROM upgrade_batch_command WHERE id=? AND batch_id=?",
                (event["reference"], batch["id"]),
            ).fetchone()
            if row is None:
                raise AdminError("admin_batch_events_invalid", 503)
            command = BatchCommand.model_validate_json(row["request"])
            if (
                command.action != action
                or json.loads(row["result"])
                != {"id": batch["id"], "revision": index, "state": value["state"]}
                or (action != "check" and command.expected_revision != index - 1)
            ):
                raise AdminError("admin_batch_events_invalid", 503)
            if action in {"start", "resume"} and value["run_command"] != command.id:
                raise AdminError("admin_batch_events_invalid", 503)
            if action in {"check", "recheck"} and value["attempt"] != command.id:
                raise AdminError("admin_batch_events_invalid", 503)
        elif action == "restore_fenced":
            if not connection.execute(
                "SELECT 1 FROM audit WHERE action='control_restored_fenced' AND reference=?",
                (event["reference"],),
            ).fetchone():
                raise AdminError("admin_batch_events_invalid", 503)
        else:
            audit_action = {
                "blocked": "upgrade_batch_blocked",
                "readiness_finished": "upgrade_batch_readiness_finished",
                "finished": "upgrade_batch_finished",
                "child_admitted": "upgrade_batch_child_admitted",
                "skip_completed": "upgrade_batch_skip_completed",
                "skip_failed": "upgrade_batch_skip_failed",
            }[action]
            if not connection.execute(
                "SELECT 1 FROM audit WHERE action=? AND reference=?",
                (audit_action, event["reference"]),
            ).fetchone():
                raise AdminError("admin_batch_events_invalid", 503)
        prior = value
    if prior != {field: batch[field] for field in FIELDS}:
        raise AdminError("admin_batch_events_invalid", 503)


def validate_admissions(connection, batch):
    for row in connection.execute(
        "SELECT c.*,o.payload,o.identity FROM upgrade_batch_child c JOIN operation o ON o.id=c.child_id WHERE c.batch_id=?",
        (batch["id"],),
    ):
        member = connection.execute(
            "SELECT child_id,instance FROM upgrade_batch_member WHERE batch_id=? AND sequence=?",
            (batch["id"], row["sequence"]),
        ).fetchone()
        run = connection.execute(
            "SELECT request FROM upgrade_batch_command WHERE id=? AND batch_id=?",
            (row["run_command"], batch["id"]),
        ).fetchone()
        readiness = connection.execute(
            "SELECT plan FROM upgrade_batch_readiness WHERE batch_id=? AND attempt=? AND sequence=?",
            (batch["id"], row["attempt"], row["sequence"]),
        ).fetchone()
        if not member or not run or not readiness or not readiness[0]:
            raise AdminError("admin_batch_admission_invalid", 503)
        command = BatchCommand.model_validate_json(run[0])
        payload = json.loads(row["payload"])
        sessions = {item.instance: item.handling for item in command.sessions}
        if (
            command.action not in {"start", "resume"}
            or member["child_id"] != row["child_id"]
            or payload["plan"] != json.loads(readiness[0])
            or payload["session_handling"] != sessions.get(member["instance"])
            or not command.window_start <= row["admitted"] < command.window_end
        ):
            raise AdminError("admin_batch_admission_invalid", 503)
    for row in connection.execute(
        "SELECT s.*,c.request,m.child_id AS member_child,m.skipped,o.cancel_requested,o.state AS child_state FROM upgrade_batch_skip s JOIN upgrade_batch_command c ON c.id=s.command_id JOIN upgrade_batch_member m ON m.batch_id=s.batch_id AND m.sequence=s.sequence JOIN operation o ON o.id=s.child_id WHERE s.batch_id=?",
        (batch["id"],),
    ):
        command = BatchCommand.model_validate_json(row["request"])
        if (
            command.action != "skip"
            or row["member_child"] != row["child_id"]
            or not row["cancel_requested"]
            or row["child_state"] != "paused"
            or (row["state"] == "completed" and (not row["skipped"] or row["error"] is not None))
            or (row["state"] == "failed" and not row["error"])
        ):
            raise AdminError("admin_batch_containment_invalid", 503)
        if (
            row["state"] == "completed"
            and not connection.execute(
                "SELECT 1 FROM audit WHERE action='upgrade_batch_skip_completed' AND reference=?",
                (row["command_id"],),
            ).fetchone()
        ):
            raise AdminError("admin_batch_containment_invalid", 503)

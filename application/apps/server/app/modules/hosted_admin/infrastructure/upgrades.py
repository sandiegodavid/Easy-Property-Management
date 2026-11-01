"""Durable installed-release workflow over the shared checkpoint engine.

Long host work occurs in the private worker, never a request transaction. The
host port owns effects and their exact reconciliation, not browser assertions.
"""

from contextlib import nullcontext
import json
import sqlite3

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import Observation, canonical
from app.modules.hosted_admin.application.upgrades import (
    UpgradeCommand,
    UpgradePlan,
    UpgradeEvidence,
    UpgradeCheckPayload,
    UpgradeRunPayload,
)
from app.modules.hosted_admin.infrastructure.operations import OperationEngine, enqueue, audit
from app.modules.hosted_admin.infrastructure.upgrade_batches import UpgradeBatchService


class UpgradeService:
    def __init__(self, store, host):
        self.store, self.host = store, host
        self.engine = OperationEngine(store)
        self.batches = UpgradeBatchService(self)

    def lookup(self, identifier, identity):
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT operation_id FROM upgrade_command WHERE id=? AND identity=?",
                (identifier, identity["id"]),
            ).fetchone()
        return {"found": row is not None, "operation": self.view(row[0], identity) if row else None}

    def view(self, identifier, identity):
        try:
            operation = self.engine.get(identifier, identity["id"])
        except AdminError as error:
            if error.status != 404:
                raise
            with self.store.transaction() as connection:
                row = connection.execute(
                    "SELECT operation_id FROM upgrade_command WHERE id=? AND identity=?",
                    (identifier, identity["id"]),
                ).fetchone()
            if row is None:
                raise
            identifier = row[0]
            operation = self.engine.get(identifier, identity["id"])
        if not operation["kind"].startswith("upgrade"):
            raise AdminError("admin_operation_not_found", 404)
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM upgrade_plan WHERE operation_id=?", (identifier,)
            ).fetchone()
            events = connection.execute(
                "SELECT payload FROM upgrade_evidence WHERE operation_id=? ORDER BY rowid DESC LIMIT 3",
                (identifier,),
            ).fetchall()
            source = connection.execute(
                "SELECT o.payload,m.batch_id FROM operation o LEFT JOIN upgrade_batch_member m ON m.child_id=o.id OR m.child_id=json_extract(o.payload,'$.parent') WHERE o.id=?",
                (identifier,),
            ).fetchone()
        plan = UpgradePlan.model_validate_json(row[0]) if row else None
        payload = json.loads(source[0])
        from app.modules.hosted_admin.application.upgrades import UpgradeView, UpgradeEvidence

        return UpgradeView(
            operation=operation,
            original_release=plan.instance.release if plan else None,
            target=plan.target if plan else None,
            workspace_id=plan.instance.workspace_id if plan else None,
            session_handling=payload.get("session_handling"),
            evidence=[UpgradeEvidence.model_validate_json(row[0]) for row in events],
            batch=source["batch_id"],
        ).model_dump()

    def command(self, command, identity, credential=""):
        guard = (
            self.engine.worker_lock(command.operation)
            if command.action == "rollback"
            else nullcontext()
        )
        with guard, self.store.transaction() as connection:
            current = dict(self.store._identity(connection))
            if current != identity:
                raise AdminError("admin_authority_fenced", 409)
            prior = connection.execute(
                "SELECT * FROM upgrade_command WHERE id=?", (command.id,)
            ).fetchone()
            if prior:
                if prior["identity"] != identity["id"] or prior["request"] != canonical(
                    command.model_dump()
                ):
                    raise AdminError("admin_command_conflict", 409)
                return json.loads(prior["result"])
            if command.action != "check":
                self.store._consume(connection, credential, "action", command.fingerprint())
            if command.action == "check":
                payload = {
                    "operation_id": command.id,
                    "instance": command.instance,
                    "release": command.release,
                    "expected_revision": command.expected_revision,
                    "reason": command.reason,
                }
                operation = enqueue(
                    connection,
                    self.store,
                    identifier=command.id,
                    identity=identity,
                    kind="upgrade_check",
                    target=command.instance,
                    payload=payload,
                )
            else:
                parent = self.engine._get(connection, command.operation)
                self.engine._control(connection, parent, command.expected_revision, identity)
                if parent["target"] != command.instance:
                    raise AdminError("admin_upgrade_target_changed", 409)
                if command.action == "start":
                    operation = self._start(connection, command, parent, identity)
                elif command.action == "accept":
                    operation = self._accept(connection, command, parent)
                else:
                    operation = self._rollback(connection, command, parent, identity)
            result = self.engine.get_from_row(operation)
            connection.execute(
                "INSERT INTO upgrade_command VALUES (?,?,?,?,?)",
                (
                    command.id,
                    identity["id"],
                    canonical(command.model_dump()),
                    operation["id"],
                    canonical(result),
                ),
            )
            if command.action == "accept":
                connection.execute(
                    "INSERT INTO upgrade_decision VALUES (?,?,?)",
                    (operation["id"], command.id, int(command.restore_access)),
                )
            self.store._audit(connection, "upgrade_" + command.action, command.id)
            return result

    def _start(self, connection, command, parent, identity):
        if parent["kind"] != "upgrade_check" or parent["state"] != "succeeded":
            raise AdminError("admin_upgrade_readiness_required", 409)
        row = connection.execute(
            "SELECT * FROM upgrade_plan WHERE operation_id=?", (parent["id"],)
        ).fetchone()
        if not row or not 0 <= self.store.clock() - row["created"] < 300:
            raise AdminError("admin_upgrade_readiness_stale", 409)
        plan = UpgradePlan.model_validate_json(row["payload"]).model_dump()
        if not plan["target"]["eligible"] or (
            command.session_handling == "preserve" and not plan["target"]["preserve_sessions"]
        ):
            raise AdminError("admin_upgrade_session_handling_required", 409)
        payload = {
            "operation_id": command.id,
            "instance": command.instance,
            "plan": plan,
            "session_handling": command.session_handling,
            "gate_owner": command.id,
            "reason": command.reason,
        }
        try:
            operation = enqueue(
                connection,
                self.store,
                identifier=command.id,
                identity=identity,
                kind="upgrade",
                target=command.instance,
                payload=payload,
            )
        except sqlite3.IntegrityError as error:
            raise AdminError("admin_upgrade_already_running", 409) from error
        connection.execute(
            "INSERT INTO upgrade_plan VALUES (?,?,?)",
            (command.id, row["payload"], self.store.clock()),
        )
        return operation

    def _accept(self, connection, command, parent):
        if not self.engine._eligible(connection, parent):
            raise AdminError("admin_authority_fenced", 409)
        if parent["kind"] not in {"upgrade", "upgrade_rollback"} or parent["state"] not in {
            "waiting",
            "unknown",
            "failed",
        }:
            raise AdminError("admin_upgrade_verification_required", 409)
        pending = connection.execute(
            "SELECT kind FROM operation_step WHERE operation_id=? AND state!='verified' ORDER BY sequence LIMIT 1",
            (parent["id"],),
        ).fetchone()
        if not pending or pending[0] != "accept":
            raise AdminError("admin_upgrade_verification_required", 409)
        connection.execute(
            "UPDATE operation SET state='queued',revision=revision+1,error=NULL,updated=? WHERE id=?",
            (self.store.clock(), parent["id"]),
        )
        audit(connection, self.store, parent, "acceptance_requested")
        return self.engine._get(connection, parent["id"])

    def _rollback(self, connection, command, parent, identity):
        if (
            parent["kind"] != "upgrade"
            or parent["state"] in {"succeeded", "cancelled"}
            or parent["cancel_requested"]
        ):
            raise AdminError("admin_upgrade_rollback_unavailable", 409)
        paused = connection.execute(
            "SELECT 1 FROM operation_step WHERE operation_id=? AND kind='pause' AND state='verified'",
            (parent["id"],),
        ).fetchone()
        if not paused:
            raise AdminError("admin_upgrade_pause_unverified", 409)
        if parent["claim_until"] and parent["claim_until"] > self.store.clock():
            raise AdminError("admin_operation_busy", 409)
        connection.execute(
            "UPDATE operation SET state='paused',cancel_requested=1,revision=revision+1,error='admin_upgrade_rollback_requested',updated=? WHERE id=?",
            (self.store.clock(), parent["id"]),
        )
        audit(connection, self.store, parent, "rollback_requested")
        original = json.loads(parent["payload"])
        payload = original | {
            "operation_id": command.id,
            "parent": parent["id"],
            "reason": command.reason,
            "rollback": True,
        }
        operation = enqueue(
            connection,
            self.store,
            identifier=command.id,
            identity=identity,
            kind="upgrade_rollback",
            target=command.instance,
            payload=payload,
        )
        connection.execute(
            "INSERT INTO upgrade_plan SELECT ?,payload,? FROM upgrade_plan WHERE operation_id=?",
            (command.id, self.store.clock(), parent["id"]),
        )
        return operation

    def tick(self):
        self.batches.tick()
        with self.store.transaction() as connection:
            pending = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM operation WHERE kind IN ('upgrade_check','upgrade','upgrade_rollback') AND (state IN ('queued','running') OR (state='paused' AND cancel_requested=1)) AND NOT EXISTS (SELECT 1 FROM upgrade_batch_skip WHERE child_id=operation.id) ORDER BY created LIMIT 10"
                )
            ]
        for identifier in pending:
            try:
                operation = self.engine.get(identifier)
                if operation["cancel_requested"]:
                    self.engine.finish_cancel(identifier, UpgradeEffects(self))
                else:
                    self.engine.run(identifier, UpgradeEffects(self))
            except Exception:
                # Engine retained the exact checkpoint and safe error; polling
                # must not automatically resume a failed or uncertain operation.
                continue


class UpgradeEffects:
    def __init__(self, service):
        self.service = service

    def inspect(self, payload, step):
        if step == "readiness":
            with self.service.store.transaction() as connection:
                plan = connection.execute(
                    "SELECT payload FROM upgrade_plan WHERE operation_id=?",
                    (payload["operation_id"],),
                ).fetchone()
            return Observation("verified", {"verified": True}) if plan else Observation("absent")
        if step == "accept":
            with self.service.store.transaction() as connection:
                row = connection.execute(
                    "SELECT restore_access,command_id FROM upgrade_decision WHERE operation_id=? ORDER BY rowid DESC LIMIT 1",
                    (payload["operation_id"],),
                ).fetchone()
            if row is None:
                return Observation("waiting")
            payload = payload | {"restore_access": bool(row[0]), "acceptance_id": row[1]}
        return self.service.host.inspect(payload, step)

    def apply(self, payload, step):
        if step == "readiness":
            plan = UpgradePlan.model_validate(
                self.service.host.prepare(payload["instance"], payload["release"])
            ).model_dump()
            if (
                plan["instance"]["revision"] != payload["expected_revision"]
                or plan["instance"]["key"] != payload["instance"]
                or plan["target"]["release"] != payload["release"]
            ):
                raise AdminError("admin_upgrade_inventory_changed", 409)
            if not plan["target"]["eligible"]:
                raise AdminError("admin_upgrade_release_ineligible", 409)
            with self.service.store.transaction() as connection:
                connection.execute(
                    "INSERT INTO upgrade_plan VALUES (?,?,?)",
                    (payload["operation_id"], canonical(plan), self.service.store.clock()),
                )
            return
        if step == "accept":
            with self.service.store.transaction() as connection:
                row = connection.execute(
                    "SELECT restore_access,command_id FROM upgrade_decision WHERE operation_id=? ORDER BY rowid DESC LIMIT 1",
                    (payload["operation_id"],),
                ).fetchone()
            if row is None:
                raise AdminError("admin_upgrade_acceptance_required", 409)
            payload = payload | {"restore_access": bool(row[0]), "acceptance_id": row[1]}
        self.service.host.apply(payload, step)

    def contain(self, payload):
        return self.service.host.contain(payload)


def validate_upgrades(connection):
    for link in connection.execute(
        "SELECT l.*,r.payload AS report,c.request,o.payload AS execution FROM upgrade_onboarding l JOIN recovery_report r ON r.id=l.report_id JOIN upgrade_command c ON c.id=l.command_id JOIN operation o ON o.id=l.operation_id"
    ):
        report, command, execution = (
            json.loads(link["report"]),
            UpgradeCommand.model_validate_json(link["request"]),
            json.loads(link["execution"]),
        )
        expected = (
            execution["plan"]["instance"]["release"]
            if execution.get("rollback")
            else execution["plan"]["target"]["release"]
        )
        if (
            command.action != "accept"
            or command.operation != link["operation_id"]
            or report["handoff_id"] != link["handoff_id"]
            or report["binding"]["release"] != expected
            or report["binding"]["workspace_id"] != execution["plan"]["instance"]["workspace_id"]
            or report["state"] != "verified"
        ):
            raise AdminError("admin_upgrade_recovery_link_invalid", 503)
        if not connection.execute(
            "SELECT 1 FROM audit WHERE action='upgrade_recovery_linked' AND reference=?",
            (link["command_id"],),
        ).fetchone():
            raise AdminError("admin_upgrade_recovery_link_invalid", 503)
    for operation in connection.execute("SELECT * FROM operation WHERE kind LIKE 'upgrade%'"):
        raw = json.loads(operation["payload"])
        model = UpgradeCheckPayload if operation["kind"] == "upgrade_check" else UpgradeRunPayload
        payload = model.model_validate(raw)
        if (
            canonical(payload.model_dump(exclude_unset=True)) != operation["payload"]
            or payload.operation_id != operation["id"]
            or payload.instance != operation["target"]
        ):
            raise AdminError("admin_upgrade_history_invalid", 503)
        if operation["kind"] == "upgrade_rollback":
            parent = connection.execute(
                "SELECT payload,kind FROM operation WHERE id=?", (payload.parent,)
            ).fetchone()
            if (
                not parent
                or parent["kind"] != "upgrade"
                or json.loads(parent["payload"])["gate_owner"] != payload.gate_owner
                or json.loads(parent["payload"])["plan"] != raw["plan"]
            ):
                raise AdminError("admin_upgrade_history_invalid", 503)
    for row in connection.execute("SELECT * FROM upgrade_evidence"):
        proof = UpgradeEvidence.model_validate_json(row["payload"])
        if (
            proof.id != row["id"]
            or proof.operation != row["operation_id"]
            or proof.stage != row["stage"]
            or canonical(proof.model_dump()) != row["payload"]
        ):
            raise AdminError("admin_upgrade_evidence_invalid", 503)
        if not connection.execute(
            "SELECT 1 FROM audit WHERE action='upgrade_evidence_registered' AND reference=?",
            (proof.id,),
        ).fetchone():
            raise AdminError("admin_upgrade_evidence_invalid", 503)
    for row in connection.execute("SELECT * FROM upgrade_command"):
        command = UpgradeCommand.model_validate_json(row["request"])
        operation = connection.execute(
            "SELECT * FROM operation WHERE id=?", (row["operation_id"],)
        ).fetchone()
        if (
            command.id != row["id"]
            or canonical(command.model_dump()) != row["request"]
            or operation is None
            or operation["target"] != command.instance
            or operation["identity"] != row["identity"]
        ):
            raise AdminError("admin_upgrade_history_invalid", 503)
        result = json.loads(row["result"])
        expected_id = command.operation if command.action == "accept" else command.id
        if (
            result.get("id") != expected_id
            or row["operation_id"] != expected_id
            or result.get("state") != "queued"
            or type(result.get("revision")) is not int
            or not 1 <= result["revision"] <= operation["revision"]
        ):
            raise AdminError("admin_upgrade_history_invalid", 503)
        if not connection.execute(
            "SELECT 1 FROM audit WHERE action=? AND reference=?",
            ("upgrade_" + command.action, command.id),
        ).fetchone():
            raise AdminError("admin_upgrade_history_invalid", 503)
    for row in connection.execute("SELECT * FROM upgrade_plan"):
        plan = UpgradePlan.model_validate_json(row["payload"]).model_dump()
        operation = connection.execute(
            "SELECT payload,target,kind FROM operation WHERE id=?", (row["operation_id"],)
        ).fetchone()
        source = json.loads(operation["payload"])
        if (
            plan["instance"]["key"] != operation["target"]
            or (source.get("plan") is not None and source["plan"] != plan)
            or (
                operation["kind"] == "upgrade_check"
                and source["release"] != plan["target"]["release"]
            )
        ):
            raise AdminError("admin_upgrade_history_invalid", 503)
        if (
            canonical(plan) != row["payload"]
            or not isinstance(plan.get("instance"), dict)
            or not isinstance(plan.get("target"), dict)
            or row["created"] < 0
        ):
            raise AdminError("admin_upgrade_history_invalid", 503)
    for row in connection.execute(
        "SELECT d.*,c.request FROM upgrade_decision d JOIN upgrade_command c ON c.id=d.command_id"
    ):
        command = UpgradeCommand.model_validate_json(row["request"])
        if (
            command.action != "accept"
            or command.operation != row["operation_id"]
            or command.restore_access != bool(row["restore_access"])
        ):
            raise AdminError("admin_upgrade_history_invalid", 503)

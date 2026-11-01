"""Explicit skip retains the failed child and its gate while releasing execution."""

import json

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.infrastructure.operations import audit
from app.modules.hosted_admin.infrastructure.batch_history import record_event


class BatchContainment:
    def __init__(self, batches):
        self.batches, self.store = batches, batches.store

    def admit(self, connection, command, batch, member, identity, locks):
        child = member["child_id"]
        locks.enter_context(self.batches.upgrades.engine.worker_lock(child))
        prior = connection.execute(
            "SELECT state FROM upgrade_batch_skip WHERE child_id=? ORDER BY rowid DESC LIMIT 1",
            (child,),
        ).fetchone()
        if prior and prior[0] == "queued":
            raise AdminError("admin_batch_containment_pending", 409)
        operation = self.batches.upgrades.engine._get(connection, child)
        if operation["state"] == "succeeded":
            raise AdminError("admin_batch_already_accepted", 409)
        if operation["claim_until"] and operation["claim_until"] > self.store.clock():
            raise AdminError("admin_operation_busy", 409)
        if connection.execute(
            "SELECT 1 FROM operation WHERE kind='upgrade_rollback' AND json_extract(payload,'$.parent')=? AND state NOT IN ('succeeded','cancelled') LIMIT 1",
            (child,),
        ).fetchone():
            raise AdminError("admin_batch_recovery_required", 409)
        # Fencing commits before cleanup. No old worker/acceptance can run again.
        connection.execute(
            "UPDATE operation SET cancel_requested=1,state='paused',claim=NULL,claim_until=NULL,revision=revision+1,updated=? WHERE id=?",
            (self.store.clock(), child),
        )
        audit(connection, self.store, operation, "batch_skip_requested")
        connection.execute(
            "INSERT INTO upgrade_batch_skip VALUES (?,?,?,?,?,'queued',NULL,?)",
            (
                command.id,
                batch["id"],
                member["sequence"],
                child,
                identity["generation"],
                self.store.clock(),
            ),
        )

    def tick(self, identifier=None):
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT s.* FROM upgrade_batch_skip s WHERE s.state='queued' AND (? IS NULL OR s.batch_id=?) AND s.rowid=(SELECT max(rowid) FROM upgrade_batch_skip WHERE child_id=s.child_id) ORDER BY s.created,s.command_id LIMIT 1",
                (identifier, identifier),
            ).fetchone()
        if row is None:
            return
        try:
            with self.batches.upgrades.engine.worker_lock(row["child_id"]):
                with self.store.transaction() as connection:
                    if (
                        connection.execute(
                            "SELECT state FROM upgrade_batch_skip WHERE command_id=?",
                            (row["command_id"],),
                        ).fetchone()[0]
                        != "queued"
                    ):
                        return
                    self._authority(connection, row)
                    child = self.batches.upgrades.engine._get(connection, row["child_id"])
                    if not child["cancel_requested"] or child["state"] != "paused":
                        raise AdminError("admin_batch_containment_changed", 409)
                if not self.batches.upgrades.host.contain_for_skip(json.loads(child["payload"])):
                    raise AdminError("admin_batch_containment_unverified", 409)
                with self.store.transaction() as connection:
                    self._authority(connection, row)
                    connection.execute(
                        "UPDATE upgrade_batch_skip SET state='completed',error=NULL WHERE command_id=?",
                        (row["command_id"],),
                    )
                    connection.execute(
                        "UPDATE upgrade_batch_member SET skipped=1 WHERE batch_id=? AND sequence=? AND skipped=0",
                        (row["batch_id"], row["sequence"]),
                    )
                    connection.execute(
                        "UPDATE upgrade_batch SET revision=revision+1,updated=? WHERE id=?",
                        (self.store.clock(), row["batch_id"]),
                    )
                    self.store._audit(connection, "upgrade_batch_skip_completed", row["command_id"])
                    record_event(
                        connection, self.store, row["batch_id"], "skip_completed", row["command_id"]
                    )
        except AdminError as error:
            if error.code == "admin_operation_busy":
                return
            self._failed(row, error.code)
        except Exception:
            self._failed(row, "admin_batch_containment_unverified")

    def _authority(self, connection, row):
        identity = self.store._identity(connection)
        batch = self.batches._get(connection, row["batch_id"])
        if identity["id"] != batch["identity"] or identity["generation"] != row["generation"]:
            raise AdminError("admin_authority_fenced", 409)

    def _failed(self, row, code):
        with self.store.transaction() as connection:
            changed = connection.execute(
                "UPDATE upgrade_batch_skip SET state='failed',error=? WHERE command_id=? AND state='queued'",
                (code, row["command_id"]),
            )
            if changed.rowcount != 1:
                return
            connection.execute(
                "UPDATE upgrade_batch SET error=?,revision=revision+1,updated=? WHERE id=?",
                (code, self.store.clock(), row["batch_id"]),
            )
            self.store._audit(connection, "upgrade_batch_skip_failed", row["command_id"])
            record_event(connection, self.store, row["batch_id"], "skip_failed", row["command_id"])

"""Serial durable coordinator. No source effects or private host reads in status GETs."""

from contextlib import ExitStack, nullcontext
import json

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import canonical
from app.modules.hosted_admin.application.upgrade_batches import (
    BatchCommand,
    BatchView,
    BatchDirectory,
    child_identity,
)
from app.modules.hosted_admin.application.upgrades import UpgradePlan
from app.modules.hosted_admin.infrastructure.operations import enqueue
from app.modules.hosted_admin.infrastructure.batch_containment import BatchContainment
from app.modules.hosted_admin.infrastructure.batch_history import record_event
from app.modules.hosted_admin.infrastructure.batch_validation import (
    validate_batches as validate_batches,
)


READINESS_ERRORS = frozenset(
    {
        "admin_instance_operation_pending",
        "admin_instance_not_found",
        "admin_batch_readiness_changed",
        "admin_upgrade_access_changed",
        "admin_upgrade_capacity_unverified",
        "admin_upgrade_catalog_ambiguous",
        "admin_upgrade_inventory_changed",
        "admin_upgrade_qualification_changed",
        "admin_upgrade_recovery_space_required",
        "admin_upgrade_release_changed",
        "admin_upgrade_release_ineligible",
        "admin_upgrade_schema_unsupported",
    }
)


class UpgradeBatchService:
    def __init__(self, upgrades):
        self.upgrades, self.store = upgrades, upgrades.store
        self.containment = BatchContainment(self)

    def _get(self, connection, identifier, identity=None):
        row = connection.execute("SELECT * FROM upgrade_batch WHERE id=?", (identifier,)).fetchone()
        if row is None:
            row = connection.execute(
                "SELECT b.* FROM upgrade_batch b JOIN upgrade_batch_command c ON c.batch_id=b.id WHERE c.id=?",
                (identifier,),
            ).fetchone()
        if row is None or (identity is not None and row["identity"] != identity["id"]):
            raise AdminError("admin_batch_not_found", 404)
        return dict(row)

    def _members(self, connection, batch):
        return [
            dict(row)
            for row in connection.execute(
                "SELECT m.*,(SELECT json_extract(data,'$.name') FROM setup_draft WHERE state='started' AND json_extract(plan,'$.key')=m.instance LIMIT 1) AS display_name,r.plan,r.error AS readiness_error,r.observed,o.state AS child_state,o.revision AS child_revision,o.cancel_requested,o.error AS child_error,"
                "(SELECT kind FROM operation_step WHERE operation_id=o.id AND state!='verified' ORDER BY sequence LIMIT 1) AS pending_step,"
                "(SELECT restore_access FROM upgrade_decision WHERE operation_id=o.id ORDER BY rowid DESC LIMIT 1) AS restore_access,"
                "(SELECT state FROM upgrade_batch_skip WHERE child_id=o.id ORDER BY rowid DESC LIMIT 1) AS skip_state,"
                "(SELECT id FROM operation WHERE kind='upgrade_rollback' AND json_extract(payload,'$.parent')=o.id AND state='succeeded' LIMIT 1) AS accepted_rollback "
                "FROM upgrade_batch_member m LEFT JOIN upgrade_batch_readiness r ON r.batch_id=m.batch_id AND r.sequence=m.sequence AND r.attempt=? "
                "LEFT JOIN operation o ON o.id=m.child_id WHERE m.batch_id=? ORDER BY m.sequence",
                (batch["attempt"], batch["id"]),
            )
        ]

    @staticmethod
    def member_status(row):
        if row["skipped"]:
            return "skipped"
        if row["skip_state"] == "queued":
            return "containing"
        if row["accepted_rollback"]:
            return "rolled_back"
        if row["child_state"] == "succeeded":
            return "accepted_restored" if row["restore_access"] else "accepted_disabled"
        if row["child_state"] in {"unknown", "failed", "paused", "cancelled"}:
            return "failed"
        if row["child_state"] == "waiting" and row["pending_step"] == "accept":
            return "awaiting_acceptance"
        if row["child_id"]:
            return "upgrading"
        if row["readiness_error"]:
            return "blocked"
        return "queued" if row["plan"] else "checking_readiness"

    def view(self, identifier, identity, offset=0, limit=10):
        if (
            type(offset) is not int
            or type(limit) is not int
            or not 0 <= offset < 50
            or not 1 <= limit <= 50
        ):
            raise AdminError("admin_batch_page_invalid", 422)
        with self.store.transaction() as connection:
            batch = self._get(connection, identifier, identity)
            identifier = batch["id"]
            rows = self._members(
                connection, batch
            )  # Always bounded by the immutable 50-member plan.
            run = connection.execute(
                "SELECT request FROM upgrade_batch_command WHERE id=?", (batch["run_command"],)
            ).fetchone()
        request = BatchCommand.model_validate_json(batch["request"])
        execution = BatchCommand.model_validate_json(run[0]) if run else None
        sessions = (
            {item.instance: item.handling for item in execution.sessions} if execution else {}
        )
        counts = {}
        items = []
        for row in rows:
            status = self.member_status(row)
            counts[status] = counts.get(status, 0) + 1
            if not offset <= row["sequence"] < offset + limit:
                continue
            plan = UpgradePlan.model_validate_json(row["plan"]) if row["plan"] else None
            items.append(
                {
                    "sequence": row["sequence"],
                    "name": row["display_name"] or f"Operator {row['instance'].upper()}",
                    "instance": row["instance"],
                    "expected_revision": row["expected_revision"],
                    "status": status,
                    "operation": row["child_id"],
                    "rollback": row["accepted_rollback"],
                    "operation_revision": row["child_revision"],
                    "observed": row["observed"],
                    "original_release": plan.instance.release if plan else None,
                    "target_digest": plan.target.digest if plan else None,
                    "preserve_sessions": plan.target.preserve_sessions if plan else False,
                    "session_handling": sessions.get(row["instance"]),
                    "access_active": plan.active if plan else None,
                    "error": row["readiness_error"] or row["child_error"],
                    "can_skip": not row["skipped"]
                    and row["skip_state"] != "queued"
                    and (
                        not row["child_id"]
                        or bool(row["accepted_rollback"])
                        or row["child_state"] in {"failed", "unknown", "paused", "cancelled"}
                    ),
                }
            )
        return BatchView.model_validate(
            {
                "id": identifier,
                "state": batch["state"],
                "revision": batch["revision"],
                "release": request.release,
                "error": batch["error"],
                "total": len(rows),
                "counts": counts,
                "window_start": execution.window_start if execution else None,
                "window_end": execution.window_end if execution else None,
                "items": items,
                "offset": offset,
                "next_offset": offset + limit if offset + limit < len(rows) else None,
            }
        ).model_dump()

    def lookup(self, identifier, identity):
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT batch_id FROM upgrade_batch_command WHERE id=? AND identity=?",
                (identifier, identity["id"]),
            ).fetchone()
        return {"found": row is not None, "batch": self.view(row[0], identity) if row else None}

    def directory(self, identity, offset=0):
        if type(offset) is not int or not 0 <= offset <= 990 or offset % 10:
            raise AdminError("admin_batch_page_invalid", 422)
        with self.store.transaction() as connection:
            total = connection.execute(
                "SELECT count(*) FROM upgrade_batch WHERE identity=?", (identity["id"],)
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT b.id,b.state,b.revision,b.created,b.updated,json_extract(b.request,'$.release') AS release,count(m.sequence) AS total,sum(m.skipped) AS skipped,sum(CASE WHEN o.state='succeeded' THEN 1 ELSE 0 END) AS accepted FROM (SELECT * FROM upgrade_batch WHERE identity=? ORDER BY created DESC,id DESC LIMIT 10 OFFSET ?) b JOIN upgrade_batch_member m ON m.batch_id=b.id LEFT JOIN operation o ON o.id=m.child_id GROUP BY b.id ORDER BY b.created DESC,b.id DESC",
                (identity["id"], offset),
            ).fetchall()
        return BatchDirectory.model_validate(
            {
                "items": [dict(row) for row in rows],
                "total": total,
                "offset": offset,
                "next_offset": offset + 10 if offset + 10 < total else None,
            }
        ).model_dump()

    def command(self, command, identity, credential=""):
        guard = (
            self.upgrades.engine.worker_lock(command.batch)
            if command.action in {"start", "resume", "skip"}
            else nullcontext()
        )
        with ExitStack() as locks, guard, self.store.transaction() as connection:
            if dict(self.store._identity(connection)) != identity:
                raise AdminError("admin_authority_fenced", 409)
            prior = connection.execute(
                "SELECT * FROM upgrade_batch_command WHERE id=?", (command.id,)
            ).fetchone()
            if prior:
                if prior["identity"] != identity["id"] or prior["request"] != canonical(
                    command.model_dump()
                ):
                    raise AdminError("admin_command_conflict", 409)
                return json.loads(prior["result"])
            if command.action not in {"check", "recheck"}:
                self.store._consume(connection, credential, "action", command.fingerprint())
            now = self.store.clock()
            if command.action == "check":
                if connection.execute("SELECT count(*) FROM upgrade_batch").fetchone()[0] >= 1000:
                    raise AdminError("admin_batch_capacity", 409)
                connection.execute(
                    "INSERT INTO upgrade_batch(id,identity,generation,request,revision,state,attempt,run_command,error,created,updated) VALUES (?,?,?,?,1,'checking',?,NULL,NULL,?,?)",
                    (
                        command.id,
                        identity["id"],
                        identity["generation"],
                        canonical(command.model_dump()),
                        command.id,
                        now,
                        now,
                    ),
                )
                connection.executemany(
                    "INSERT INTO upgrade_batch_member(batch_id,sequence,instance,expected_revision) VALUES (?,?,?,?)",
                    [
                        (command.id, i, item.instance, item.expected_revision)
                        for i, item in enumerate(command.members)
                    ],
                )
                identifier = command.id
            else:
                batch = self._get(connection, command.batch, identity)
                if batch["revision"] != command.expected_revision:
                    raise AdminError("admin_batch_revision_conflict", 409)
                rows = self._members(connection, batch)
                if batch["state"] in {"completed", "mixed"} or (
                    batch["state"] == "cancelled" and command.action != "skip"
                ):
                    raise AdminError("admin_batch_finished", 409)
                identifier = batch["id"]
                if command.action == "recheck":
                    if batch["state"] not in {"ready", "blocked", "paused"}:
                        raise AdminError("admin_batch_pause_required", 409)
                    connection.execute(
                        "UPDATE upgrade_batch SET state='checking',attempt=?,generation=?,error=NULL WHERE id=?",
                        (command.id, identity["generation"], identifier),
                    )
                elif command.action in {"start", "resume"}:
                    self._start(connection, command, batch, rows, identity)
                elif command.action == "pause":
                    connection.execute(
                        "UPDATE upgrade_batch SET state='paused',error=NULL WHERE id=?",
                        (identifier,),
                    )
                elif command.action == "cancel":
                    connection.execute(
                        "UPDATE upgrade_batch_member SET skipped=1 WHERE batch_id=? AND child_id IS NULL AND skipped=0",
                        (identifier,),
                    )
                    connection.execute(
                        "UPDATE upgrade_batch SET state='cancelled',error=NULL WHERE id=?",
                        (identifier,),
                    )
                else:
                    member = next(
                        (row for row in rows if row["instance"] == command.instance), None
                    )
                    if member is None or member["skipped"] or member["child_state"] == "succeeded":
                        raise AdminError("admin_batch_recovery_required", 409)
                    if member["child_id"] and not member["accepted_rollback"]:
                        self.containment.admit(connection, command, batch, member, identity, locks)
                    else:
                        connection.execute(
                            "UPDATE upgrade_batch_member SET skipped=1 WHERE batch_id=? AND instance=?",
                            (identifier, command.instance),
                        )
                    connection.execute(
                        "UPDATE upgrade_batch SET state=CASE WHEN state='cancelled' THEN state ELSE 'paused' END,error=NULL WHERE id=?",
                        (identifier,),
                    )
                connection.execute(
                    "UPDATE upgrade_batch SET revision=revision+1,updated=? WHERE id=?",
                    (now, identifier),
                )
            batch = self._get(connection, identifier)
            result = {"id": identifier, "state": batch["state"], "revision": batch["revision"]}
            connection.execute(
                "INSERT INTO upgrade_batch_command VALUES (?,?,?,?,?,?)",
                (
                    command.id,
                    identifier,
                    identity["id"],
                    canonical(command.model_dump()),
                    canonical(result),
                    now,
                ),
            )
            self.store._audit(connection, "upgrade_batch_" + command.action, command.id)
            record_event(connection, self.store, identifier, command.action, command.id)
            return result

    def _start(self, connection, command, batch, rows, identity):
        if batch["state"] != "ready" or (command.action == "start") != (
            batch["run_command"] is None
        ):
            raise AdminError("admin_batch_readiness_required", 409)
        if command.window_end <= self.store.clock():
            raise AdminError("admin_batch_window_closed", 409)
        if [item.instance for item in command.sessions] != [row["instance"] for row in rows]:
            raise AdminError("admin_batch_membership_changed", 409)
        digests = {
            json.loads(row["plan"])["target"]["digest"]
            for row in rows
            if row["plan"] and not row["skipped"]
        }
        digests.update(
            row[0]
            for row in connection.execute(
                "SELECT json_extract(o.payload,'$.plan.target.digest') FROM upgrade_batch_child c JOIN operation o ON o.id=c.child_id WHERE c.batch_id=?",
                (batch["id"],),
            )
        )
        if len(digests) > 1:
            raise AdminError("admin_batch_target_changed", 409)
        for row, decision in zip(rows, command.sessions, strict=True):
            if row["skipped"] or row["child_state"] == "succeeded":
                continue
            if row["child_id"]:
                raise AdminError("admin_batch_recovery_required", 409)
            if not row["plan"] or not 0 <= self.store.clock() - row["observed"] < 300:
                raise AdminError("admin_batch_readiness_stale", 409)
            plan = UpgradePlan.model_validate_json(row["plan"])
            if decision.handling == "preserve" and not plan.target.preserve_sessions:
                raise AdminError("admin_upgrade_session_handling_required", 409)
        connection.execute(
            "UPDATE upgrade_batch SET state='running',generation=?,run_command=?,error=NULL WHERE id=?",
            (identity["generation"], command.id, batch["id"]),
        )

    def tick(self, identifier=None):
        self.containment.tick(identifier)
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT id FROM upgrade_batch WHERE state IN ('checking','running') AND (? IS NULL OR id=?) ORDER BY visits,created,id LIMIT 1",
                (identifier, identifier),
            ).fetchone()
            if row is not None:
                connection.execute("UPDATE upgrade_batch SET visits=visits+1 WHERE id=?", (row[0],))
        if row is None:
            return
        identifier = row[0]
        try:
            with self.upgrades.engine.worker_lock(identifier):
                self._advance(identifier)
        except AdminError as error:
            if error.code == "admin_operation_busy":
                return
            self._block(identifier, error.code)
        except Exception:
            self._block(identifier, "admin_batch_private_step_required")

    def _block(self, identifier, code):
        with self.store.transaction() as connection:
            row = self._get(connection, identifier)
            if row["state"] in {"checking", "running"}:
                connection.execute(
                    "UPDATE upgrade_batch SET state='blocked',error=?,revision=revision+1,updated=? WHERE id=?",
                    (code, self.store.clock(), identifier),
                )
                self.store._audit(connection, "upgrade_batch_blocked", identifier)
                record_event(connection, self.store, identifier, "blocked", identifier)

    def _current(self, connection, batch):
        current = dict(self.store._identity(connection))
        if current["id"] != batch["identity"] or current["generation"] != batch["generation"]:
            raise AdminError("admin_authority_fenced", 409)
        latest = self._get(connection, batch["id"])
        if latest["revision"] != batch["revision"] or latest["state"] != batch["state"]:
            raise AdminError("admin_batch_revision_conflict", 409)
        return current

    def _advance(self, identifier):
        with self.store.transaction() as connection:
            batch = self._get(connection, identifier)
            self._current(connection, batch)
            rows = self._members(connection, batch)
            run = connection.execute(
                "SELECT request FROM upgrade_batch_command WHERE id=?", (batch["run_command"],)
            ).fetchone()
        if batch["state"] == "checking":
            row = next(
                (
                    row
                    for row in rows
                    if not row["skipped"] and not row["child_id"] and row["observed"] is None
                ),
                None,
            )
            if row:
                self._prepare(batch, row)
                return
            unresolved = any(
                row["child_id"] and not row["skipped"] and row["child_state"] != "succeeded"
                for row in rows
            )
            state = (
                "blocked"
                if unresolved
                or any(
                    row["readiness_error"]
                    for row in rows
                    if not row["skipped"] and not row["child_id"]
                )
                else "ready"
            )
            with self.store.transaction() as connection:
                self._current(connection, batch)
                connection.execute(
                    "UPDATE upgrade_batch SET state=?,error=?,revision=revision+1,updated=? WHERE id=?",
                    (
                        state,
                        (
                            "admin_batch_child_recovery_required"
                            if unresolved
                            else "admin_batch_member_blocked"
                        )
                        if state == "blocked"
                        else None,
                        self.store.clock(),
                        identifier,
                    ),
                )
                self.store._audit(connection, "upgrade_batch_readiness_finished", identifier)
                record_event(connection, self.store, identifier, "readiness_finished", identifier)
            return
        if batch["state"] != "running":
            return
        row = next(
            (row for row in rows if not row["skipped"] and row["child_state"] != "succeeded"), None
        )
        if row is None:
            with self.store.transaction() as connection:
                self._current(connection, batch)
                connection.execute(
                    "UPDATE upgrade_batch SET state=?,revision=revision+1,updated=? WHERE id=?",
                    (
                        "mixed" if any(row["skipped"] for row in rows) else "completed",
                        self.store.clock(),
                        identifier,
                    ),
                )
                self.store._audit(connection, "upgrade_batch_finished", identifier)
                record_event(connection, self.store, identifier, "finished", identifier)
            return
        if row["child_id"]:
            if self.member_status(row) in {"failed", "rolled_back"}:
                self._block(identifier, "admin_batch_child_recovery_required")
            return
        command = BatchCommand.model_validate_json(run[0])
        if self.store.clock() < command.window_start:
            return
        if self.store.clock() >= command.window_end:
            raise AdminError("admin_batch_window_closed", 409)
        # Long host checks run with neither a host lock nor a SQLite transaction.
        plan = UpgradePlan.model_validate(
            self.upgrades.host.prepare(row["instance"], json.loads(batch["request"])["release"])
        ).model_dump()
        previous = json.loads(row["plan"])
        if plan != previous:
            raise AdminError("admin_batch_readiness_changed", 409)
        decision = next(item for item in command.sessions if item.instance == row["instance"])
        with self.store.transaction() as connection:
            identity = self._current(connection, batch)
            if not command.window_start <= self.store.clock() < command.window_end:
                raise AdminError("admin_batch_window_closed", 409)
            busy = connection.execute(
                "SELECT 1 FROM operation WHERE kind IN ('upgrade','upgrade_rollback') AND state NOT IN ('succeeded','cancelled') AND cancel_requested=0 LIMIT 1"
            ).fetchone()
            if busy:
                raise AdminError("admin_upgrade_already_running", 409)
            child = child_identity(identifier, row["instance"])
            payload = {
                "operation_id": child,
                "instance": row["instance"],
                "plan": plan,
                "session_handling": decision.handling,
                "gate_owner": child,
                "reason": command.reason,
            }
            enqueue(
                connection,
                self.store,
                identifier=child,
                identity=identity,
                kind="upgrade",
                target=row["instance"],
                payload=payload,
            )
            connection.execute(
                "INSERT INTO upgrade_plan VALUES (?,?,?)",
                (child, canonical(plan), self.store.clock()),
            )
            connection.execute(
                "UPDATE upgrade_batch_member SET child_id=? WHERE batch_id=? AND sequence=? AND child_id IS NULL",
                (child, identifier, row["sequence"]),
            )
            connection.execute(
                "INSERT INTO upgrade_batch_child VALUES (?,?,?,?,?,?)",
                (
                    child,
                    identifier,
                    row["sequence"],
                    batch["run_command"],
                    batch["attempt"],
                    self.store.clock(),
                ),
            )
            connection.execute(
                "UPDATE upgrade_batch SET revision=revision+1,updated=? WHERE id=?",
                (self.store.clock(), identifier),
            )
            self.store._audit(connection, "upgrade_batch_child_admitted", child)
            record_event(connection, self.store, identifier, "child_admitted", child)

    def _prepare(self, batch, row):
        plan, error = None, None
        try:
            with self.store.transaction() as connection:
                self._current(connection, batch)
                if connection.execute(
                    "SELECT 1 FROM operation WHERE target=? AND state NOT IN ('succeeded','cancelled') AND cancel_requested=0 LIMIT 1",
                    (row["instance"],),
                ).fetchone():
                    raise AdminError("admin_instance_operation_pending", 409)
            plan = UpgradePlan.model_validate(
                self.upgrades.host.prepare(row["instance"], json.loads(batch["request"])["release"])
            )
            if (
                plan.instance.key != row["instance"]
                or plan.instance.revision != row["expected_revision"]
                or plan.target.release != json.loads(batch["request"])["release"]
                or plan.target.release == plan.instance.release
                or not plan.target.eligible
            ):
                raise AdminError("admin_batch_readiness_changed", 409)
        except AdminError as failure:
            plan, error = (
                None,
                failure.code
                if failure.code in READINESS_ERRORS
                else "admin_batch_readiness_blocked",
            )
        except Exception:
            plan, error = None, "admin_batch_readiness_blocked"
        with self.store.transaction() as connection:
            self._current(connection, batch)
            connection.execute(
                "INSERT INTO upgrade_batch_readiness VALUES (?,?,?,?,?,?)",
                (
                    batch["id"],
                    batch["attempt"],
                    row["sequence"],
                    canonical(plan.model_dump()) if plan else None,
                    error,
                    self.store.clock(),
                ),
            )
            connection.execute(
                "UPDATE upgrade_batch SET updated=? WHERE id=?", (self.store.clock(), batch["id"])
            )
            self.store._audit(
                connection, "upgrade_batch_member_checked", f"{batch['id']}:{row['sequence']}"
            )

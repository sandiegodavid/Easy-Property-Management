"""Checkpointed saga runner. No SQLite transaction spans an external effect."""

from contextlib import contextmanager
import fcntl
import json
import os
import secrets
import sqlite3
import stat

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import StepResult, canonical, fingerprint

LEASE_SECONDS = 60
MAX_OPERATIONS = 10000
STEPS = {
    "source": ("source_command",),
    "provision": ("allocate", "workspace", "provider_setup", "readiness"),
    "qualification_test": ("allocate", "workspace", "provider_setup", "readiness"),
    "upgrade_check": ("readiness",),
    "upgrade": (
        "revalidate",
        "pause",
        "stop",
        "recovery",
        "validate",
        "switch",
        "start",
        "verify",
        "accept",
    ),
    "upgrade_rollback": (
        "stop",
        "validate_previous",
        "switch_previous",
        "start_previous",
        "verify_previous",
        "accept",
    ),
}
TERMINAL = {"succeeded", "cancelled"}


def audit(connection, store, operation, action):
    connection.execute(
        "INSERT INTO operation_audit(operation_id,action,identity,recorded) VALUES (?,?,?,?)",
        (operation["id"], action, operation["identity"], store.clock()),
    )


def enqueue(connection, store, *, identifier, identity, kind, target, payload):
    existing = connection.execute("SELECT * FROM operation WHERE id=?", (identifier,)).fetchone()
    encoded, desired = canonical(payload), fingerprint(payload)
    if existing:
        if existing["request_hash"] != desired or existing["identity"] != identity["id"]:
            raise AdminError("admin_command_conflict", 409)
        return dict(existing)
    if (
        kind in {"upgrade", "upgrade_rollback"}
        and connection.execute(
            "SELECT 1 FROM upgrade_batch_skip s WHERE s.rowid=(SELECT max(rowid) FROM upgrade_batch_skip WHERE child_id=s.child_id) AND s.state!='completed' LIMIT 1"
        ).fetchone()
    ):
        raise AdminError("admin_batch_containment_pending", 409)
    if connection.execute("SELECT count(*) FROM operation").fetchone()[0] >= MAX_OPERATIONS:
        raise AdminError("admin_operation_capacity", 409)
    connection.execute("INSERT OR IGNORE INTO operation_target VALUES (?,0,0)", (target,))
    control = connection.execute(
        "SELECT * FROM operation_target WHERE target=?", (target,)
    ).fetchone()
    urgent = kind == "source" and payload["action"] in {"disable", "revoke"}
    if urgent:
        # A priority fence is durable before the source command runs, even while
        # an old worker is blocked in a provider call. Reservations remain owned.
        prior_operations = connection.execute(
            "SELECT * FROM operation WHERE target=? AND state NOT IN ('succeeded','cancelled')",
            (target,),
        ).fetchall()
        for prior_operation in prior_operations:
            audit(connection, store, prior_operation, "priority_fenced")
        connection.execute("UPDATE operation_target SET fence=fence+1 WHERE target=?", (target,))
        connection.execute(
            "UPDATE operation SET cancel_requested=1,state='paused',error='admin_instance_fenced',revision=revision+1,updated=? WHERE target=? AND state NOT IN ('succeeded','cancelled')",
            (store.clock(), target),
        )
    fence = control["fence"] + int(urgent)
    try:
        connection.execute(
            "INSERT INTO operation VALUES (?,?,?,?,?,?,?,?,1,'queued',0,NULL,NULL,NULL,NULL,?,?)",
            (
                identifier,
                identity["id"],
                identity["generation"],
                kind,
                target,
                desired,
                encoded,
                fence,
                store.clock(),
                store.clock(),
            ),
        )
    except sqlite3.IntegrityError as error:
        raise AdminError("admin_instance_operation_pending", 409) from error
    for sequence, step in enumerate(STEPS[kind]):
        connection.execute(
            "INSERT INTO operation_step VALUES (?,?,?,?,'pending',NULL,NULL,NULL)",
            (identifier, sequence, step, fingerprint({"request": desired, "step": step})),
        )
    connection.execute("UPDATE operation_target SET revision=revision+1 WHERE target=?", (target,))
    operation = dict(
        connection.execute("SELECT * FROM operation WHERE id=?", (identifier,)).fetchone()
    )
    audit(connection, store, operation, "admitted")
    return operation


class OperationEngine:
    def __init__(self, store):
        self.store = store

    def get(self, identifier, identity=None):
        with self.store.transaction() as connection:
            operation = self._get(connection, identifier)
            if identity is not None and operation["identity"] != identity:
                raise AdminError("admin_operation_not_found", 404)
            steps = connection.execute(
                "SELECT sequence,kind,state,reference,checked FROM operation_step WHERE operation_id=? ORDER BY sequence",
                (identifier,),
            ).fetchall()
            return {
                key: operation[key]
                for key in (
                    "id",
                    "kind",
                    "target",
                    "revision",
                    "state",
                    "cancel_requested",
                    "error",
                    "created",
                    "updated",
                )
            } | {
                "steps": [dict(row) for row in steps],
                "result": json.loads(operation["result"]) if operation["result"] else None,
            }

    @staticmethod
    def _get(connection, identifier):
        row = connection.execute("SELECT * FROM operation WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise AdminError("admin_operation_not_found", 404)
        return dict(row)

    def reserve(self, intent, reservations, identity, *, admit_check):
        """Private composition only. Admission facts must include all retained inventory.

        admit_check is the trusted, connection-bound qualification/capacity adapter;
        the browser can supply neither reservations nor its own capacity facts.
        """
        if not 1 <= len(reservations) <= 16 or len({item.kind for item in reservations}) != len(
            reservations
        ):
            raise AdminError("admin_allocation_spec_invalid", 422)
        payload = intent.model_dump() | {
            "allocation_spec": [
                item.model_dump() for item in sorted(reservations, key=lambda value: value.kind)
            ]
        }
        with self.store.transaction() as connection:
            current = self.store._identity(connection)
            if dict(current) != identity:
                raise AdminError("admin_authority_fenced", 409)
            prior = connection.execute(
                "SELECT * FROM operation WHERE id=?", (intent.operation_id,)
            ).fetchone()
            if prior:
                if prior["request_hash"] != fingerprint(payload):
                    raise AdminError("admin_command_conflict", 409)
                return self.get_from_row(prior)
            control = connection.execute(
                "SELECT revision FROM operation_target WHERE target=?", (intent.target,)
            ).fetchone()
            if (control[0] if control else 0) != intent.expected_revision:
                raise AdminError("admin_operation_revision_conflict", 409)
            admit_check(connection, intent, reservations)
            operation = enqueue(
                connection,
                self.store,
                identifier=intent.operation_id,
                identity=identity,
                kind=intent.kind,
                target=intent.target,
                payload=payload,
            )
            try:
                for reservation in reservations:
                    connection.execute(
                        "INSERT INTO reservation VALUES (?,?,?,?,?)",
                        (
                            reservation.kind,
                            reservation.identity,
                            reservation.amount,
                            intent.operation_id,
                            intent.target,
                        ),
                    )
            except sqlite3.IntegrityError as error:
                raise AdminError("admin_allocation_conflict", 409) from error
            return self.get_from_row(operation)

    @staticmethod
    def get_from_row(row):
        return {key: row[key] for key in ("id", "state", "revision")}

    def recent(self, identity, limit=50):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise AdminError("admin_operation_limit_invalid", 422)
        with self.store.transaction() as connection:
            rows = connection.execute(
                "SELECT id,kind,target,state,revision,created,updated FROM operation WHERE identity=? ORDER BY created DESC,id DESC LIMIT ?",
                (identity, limit),
            ).fetchall()
            return {"items": [dict(row) for row in rows]}

    def cancel(self, identifier, expected_revision, identity):
        with self.store.transaction() as connection:
            operation = self._get(connection, identifier)
            self._control(connection, operation, expected_revision, identity)
            if (
                operation["kind"] in {"upgrade", "upgrade_rollback"}
                and connection.execute(
                    "SELECT 1 FROM operation_step WHERE operation_id=? AND kind='pause' AND state!='pending'",
                    (identifier,),
                ).fetchone()
            ):
                raise AdminError("admin_upgrade_recovery_required", 409)
            if operation["kind"] == "upgrade_rollback":
                raise AdminError("admin_upgrade_recovery_required", 409)
            if operation["state"] in TERMINAL or operation["cancel_requested"]:
                return self.get_from_row(operation)
            connection.execute(
                "UPDATE operation_target SET fence=fence+1 WHERE target=?", (operation["target"],)
            )
            connection.execute(
                "UPDATE operation SET cancel_requested=1,state='paused',revision=revision+1,updated=? WHERE id=?",
                (self.store.clock(), identifier),
            )
            audit(connection, self.store, operation, "stop_requested")
        return self.get(identifier, identity["id"])

    def resume(self, identifier, expected_revision, identity, credential=None):
        with self.store.transaction() as connection:
            operation = self._get(connection, identifier)
            self._control(connection, operation, expected_revision, identity)
            if operation["state"] in TERMINAL or operation["cancel_requested"]:
                raise AdminError("admin_operation_not_resumable", 409)
            control = connection.execute(
                "SELECT fence FROM operation_target WHERE target=?", (operation["target"],)
            ).fetchone()
            if control[0] != operation["target_fence"]:
                raise AdminError("admin_instance_fenced", 409)
            if operation["claim_until"] and operation["claim_until"] > self.store.clock():
                raise AdminError("admin_operation_busy", 409)
            payload = json.loads(operation["payload"])
            if operation["kind"] != "source" or payload["action"] not in {"disable", "revoke"}:
                # Fresh grant covers exact operation, reviewed operation revision,
                # and current identity generation, never a revoked old grant.
                self.store._consume(
                    connection, credential or "", "action", self.resume_hash(operation)
                )
            connection.execute(
                "UPDATE operation SET generation=?,state='queued',claim=NULL,claim_until=NULL,revision=revision+1,updated=? WHERE id=?",
                (identity["generation"], self.store.clock(), identifier),
            )
            audit(connection, self.store, operation, "resumed")
        return self.get(identifier, identity["id"])

    @staticmethod
    def resume_hash(operation):
        return fingerprint(
            {
                "resume": operation["id"],
                "revision": operation["revision"],
                "request_hash": operation["request_hash"],
            }
        )

    def _control(self, connection, operation, expected_revision, identity):
        current = self.store._identity(connection)
        if dict(current) != identity or operation["identity"] != identity["id"]:
            raise AdminError("admin_authority_fenced", 409)
        if operation["revision"] != expected_revision:
            raise AdminError("admin_operation_revision_conflict", 409)

    @contextmanager
    def worker_lock(self, identifier):
        # The lease bounds claims; flock additionally prevents a slow/crashed
        # worker's still-live process from executing alongside its replacement.
        directory = self.store.path.parent / "workers"
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise AdminError("admin_worker_lock_unsafe", 503)
        descriptor = os.open(
            directory / fingerprint(identifier),
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o077
            ):
                raise AdminError("admin_worker_lock_unsafe", 503)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise AdminError("admin_operation_busy", 409) from error
            yield
        finally:
            os.close(descriptor)

    def _eligible(self, connection, operation):
        identity = connection.execute("SELECT * FROM administrator").fetchone()
        control = connection.execute(
            "SELECT fence FROM operation_target WHERE target=?", (operation["target"],)
        ).fetchone()
        return (
            identity["enabled"]
            and identity["generation"] == operation["generation"]
            and control[0] == operation["target_fence"]
            and not operation["cancel_requested"]
        )

    def require_authority(self, identifier, *, phase=None):
        """Recheck a worker's authority after slow checks, before a new effect.

        This short read does not hold the control transaction across a source
        call. Source CAS checks and post-effect containment still apply.
        """
        with self.store.transaction() as connection:
            operation = self._get(connection, identifier)
            if operation["state"] != "running" or not self._eligible(connection, operation):
                raise AdminError("admin_authority_fenced", 409)
            if phase == "pause":
                run = connection.execute(
                    "SELECT c.request FROM upgrade_batch_child m JOIN upgrade_batch_command c ON c.id=m.run_command WHERE m.child_id=?",
                    (identifier,),
                ).fetchone()
                if run:
                    window = json.loads(run[0])
                    if not window["window_start"] <= self.store.clock() < window["window_end"]:
                        raise AdminError("admin_batch_window_closed", 409)

    def run(self, identifier, adapter):
        """Run at most one fixed step. Reconnect/lookup never dispatches this method."""
        with self.worker_lock(identifier):
            try:
                return self._run(identifier, adapter)
            except Exception:
                with self.store.transaction() as connection:
                    current = self._get(connection, identifier)
                    fenced = not self._eligible(connection, current)
                if fenced and current["state"] not in TERMINAL:
                    try:
                        contained = adapter.contain(json.loads(current["payload"]))
                    except Exception:
                        contained = False
                    self._pause(
                        identifier,
                        current["claim"],
                        "paused",
                        "admin_authority_fenced" if contained else "admin_containment_pending",
                    )
                raise

    def _run(self, identifier, adapter):
        claim = secrets.token_hex(16)
        with self.store.transaction() as connection:
            operation = self._get(connection, identifier)
            if operation["state"] == "cancelled":
                raise AdminError("admin_operation_cancelled", 409)
            if operation["state"] == "succeeded":
                return json.loads(operation["result"])
            if not self._eligible(connection, operation):
                raise AdminError("admin_authority_fenced", 409)
            if operation["state"] not in {"queued", "running"}:
                raise AdminError("admin_operation_resume_required", 409)
            if operation["claim_until"] and operation["claim_until"] > self.store.clock():
                raise AdminError("admin_operation_busy", 409)
            step = connection.execute(
                "SELECT * FROM operation_step WHERE operation_id=? AND state!='verified' ORDER BY sequence LIMIT 1",
                (identifier,),
            ).fetchone()
            connection.execute(
                "UPDATE operation SET state='running',claim=?,claim_until=?,updated=? WHERE id=?",
                (claim, self.store.clock() + LEASE_SECONDS, self.store.clock(), identifier),
            )
            connection.execute(
                "UPDATE operation_step SET state='intent' WHERE operation_id=? AND sequence=?",
                (identifier, step["sequence"]),
            )
            audit(connection, self.store, operation, "step_intent")
        payload = json.loads(operation["payload"])
        try:
            observed = adapter.inspect(payload, step["kind"])
            if observed.state == "absent":
                with self.store.transaction() as connection:
                    current = self._get(connection, identifier)
                    if not self._eligible(connection, current):
                        raise AdminError("admin_authority_fenced", 409)
                adapter.apply(payload, step["kind"])
                observed = adapter.inspect(payload, step["kind"])
        except Exception:
            self._pause(identifier, claim, "unknown", "admin_effect_outcome_unknown")
            raise
        with self.store.transaction() as connection:
            current = self._get(connection, identifier)
            fenced = not self._eligible(connection, current)
        if fenced:
            raise AdminError("admin_authority_fenced", 409)
        if observed.state != "verified":
            state = {"conflict": "failed", "waiting": "waiting"}.get(observed.state, "unknown")
            self._pause(
                identifier,
                claim,
                state,
                {"failed": "admin_effect_conflict", "waiting": "admin_external_setup_required"}.get(
                    state, "admin_effect_outcome_unknown"
                ),
            )
            raise AdminError("admin_effect_reconciliation_required", 409)
        if observed.reference is not None and (
            len(observed.reference) > 128
            or not all(
                character.isalnum() or character in "-_.:" for character in observed.reference
            )
        ):
            self._pause(identifier, claim, "failed", "admin_effect_reference_invalid")
            raise AdminError("admin_effect_reference_invalid", 503)
        try:
            safe_result = StepResult.model_validate(observed.result or {}).model_dump(
                exclude_none=True
            )
        except ValueError as error:
            self._pause(identifier, claim, "failed", "admin_effect_result_invalid")
            raise AdminError("admin_effect_result_invalid", 503) from error
        encoded = canonical(safe_result)
        if len(encoded.encode()) > 8192:
            self._pause(identifier, claim, "failed", "admin_effect_result_too_large")
            raise AdminError("admin_effect_result_too_large", 503)
        with self.store.transaction() as connection:
            current = self._get(connection, identifier)
            if current["claim"] != claim or not self._eligible(connection, current):
                raise AdminError("admin_authority_fenced", 409)
            connection.execute(
                "UPDATE operation_step SET state='verified',reference=?,result=?,checked=? WHERE operation_id=? AND sequence=?",
                (observed.reference, encoded, self.store.clock(), identifier, step["sequence"]),
            )
            pending = connection.execute(
                "SELECT 1 FROM operation_step WHERE operation_id=? AND state!='verified'",
                (identifier,),
            ).fetchone()
            state = "queued" if pending else "succeeded"
            connection.execute(
                "UPDATE operation SET state=?,claim=NULL,claim_until=NULL,error=NULL,result=?,revision=revision+1,updated=? WHERE id=?",
                (state, None if pending else encoded, self.store.clock(), identifier),
            )
            if not pending and operation["kind"] == "source":
                connection.execute(
                    "UPDATE admission SET result=? WHERE id=? AND result IS NULL",
                    (encoded, identifier),
                )
            audit(connection, self.store, operation, "step_verified" if pending else "completed")
        return safe_result

    def _pause(self, identifier, claim, state, error):
        with self.store.transaction() as connection:
            operation = self._get(connection, identifier)
            if operation["claim"] == claim:
                connection.execute(
                    "UPDATE operation SET state=?,claim=NULL,claim_until=NULL,error=?,revision=revision+1,updated=? WHERE id=?",
                    (state, error, self.store.clock(), identifier),
                )
                audit(connection, self.store, operation, state)

    def finish_cancel(self, identifier, adapter):
        with self.worker_lock(identifier):
            with self.store.transaction() as connection:
                operation = self._get(connection, identifier)
                if operation["state"] == "cancelled":
                    return
                if not operation["cancel_requested"]:
                    raise AdminError("admin_stop_not_requested", 409)
            # All effects and allocations stay in place; only access is contained.
            if not adapter.contain(json.loads(operation["payload"])):
                raise AdminError("admin_containment_pending", 503)
            with self.store.transaction() as connection:
                connection.execute(
                    "UPDATE operation SET state='cancelled',claim=NULL,claim_until=NULL,revision=revision+1,updated=? WHERE id=?",
                    (self.store.clock(), identifier),
                )
                audit(connection, self.store, operation, "cancelled_resources_retained")

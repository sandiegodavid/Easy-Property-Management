"""Private evidence-backed capacity promotion; no live resource mutation here."""

import json

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import canonical
from app.modules.hosted_admin.application.qualification import (
    QualificationEvidence,
    QualificationPlan,
    REQUIRED_EVIDENCE,
)

MAX_PLANS = 100
FRESH_SECONDS = 300
CLEANUP_EVIDENCE = frozenset({"retirement", "restoration"})


class QualificationService:
    def __init__(self, store, snapshot, evidence_reader):
        self.store, self.snapshot, self.evidence_reader = store, snapshot, evidence_reader

    def initialize_capacity(self, ceiling, snapshot):
        """Explicit protected installation input; does not infer qualification from inventory."""
        if type(ceiling) is not int or not 0 <= ceiling <= 2:
            raise AdminError("admin_initial_ceiling_invalid", 409)
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO capacity VALUES (1,1,?,?)", (ceiling, snapshot.environment_hash)
            )

    def _fresh(self, snapshot):
        if (
            not snapshot.inventory_clear
            or not 0 <= self.store.clock() - snapshot.observed < FRESH_SECONDS
        ):
            raise AdminError("admin_capacity_observation_unavailable", 409)

    def _room(self, connection, plan, snapshot, exclude=None):
        self._fresh(snapshot)
        if (snapshot.environment_hash, snapshot.release, snapshot.profile) != (
            plan.environment_hash,
            plan.release,
            plan.profile,
        ):
            raise AdminError("admin_qualification_environment_changed", 409)
        others = connection.execute(
            "SELECT payload FROM qualification WHERE state IN ('planned','running','aborted') AND id!=?",
            (exclude or plan.id,),
        ).fetchall()
        committed = [json.loads(row[0]) for row in others]
        memory = (
            snapshot.memory_committed
            + sum(item["memory_bytes"] for item in committed)
            + plan.memory_bytes
        )
        disk = (
            snapshot.disk_committed
            + sum(item["disk_bytes"] for item in committed)
            + plan.disk_bytes
        )
        if memory * 4 > snapshot.memory_total * 3:
            raise AdminError("admin_memory_reservation_blocked", 409)
        if snapshot.disk_free - disk < max(snapshot.disk_total // 5, snapshot.recovery_staging):
            raise AdminError("admin_disk_reservation_blocked", 409)

    def create(self, plan, identity):
        snapshot = self.snapshot()
        with self.store.transaction() as connection:
            self._identity(connection, identity)
            prior = connection.execute(
                "SELECT * FROM qualification WHERE id=?", (plan.id,)
            ).fetchone()
            if prior:
                if (
                    prior["request_hash"] != plan.fingerprint()
                    or prior["identity"] != identity["id"]
                ):
                    raise AdminError("admin_qualification_conflict", 409)
                return self._view(prior)
            if connection.execute("SELECT count(*) FROM qualification").fetchone()[0] >= MAX_PLANS:
                raise AdminError("admin_qualification_capacity", 409)
            if not self.store.clock() <= plan.starts < plan.expires:
                raise AdminError("admin_qualification_window_invalid", 409)
            self._room(connection, plan, snapshot)
            if {item.email.casefold() for item in plan.identities} & {
                value.casefold() for value in snapshot.retained_emails
            } or {item.hostname for item in plan.identities} & set(snapshot.retained_hostnames):
                raise AdminError("admin_qualification_identity_conflict", 409)
            # Retained normal identities/hosts are checked by the trusted snapshot
            # composition. Test reservations may not overlap another live plan.
            other_plans = connection.execute(
                "SELECT payload FROM qualification WHERE state!='retired' AND state!='promoted'"
            ).fetchall()
            for row in other_plans:
                other = QualificationPlan.model_validate_json(row[0])
                if {item.email.casefold() for item in plan.identities} & {
                    item.email.casefold() for item in other.identities
                } or {item.hostname for item in plan.identities} & {
                    item.hostname for item in other.identities
                }:
                    raise AdminError("admin_qualification_identity_conflict", 409)
            connection.execute(
                "INSERT INTO qualification VALUES (?,?,?,?,?,1,'planned',?)",
                (
                    plan.id,
                    plan.fingerprint(),
                    canonical(plan.model_dump()),
                    identity["id"],
                    identity["generation"],
                    self.store.clock(),
                ),
            )
            self.store._audit(connection, "qualification_planned", plan.id)
            return self._view(
                connection.execute("SELECT * FROM qualification WHERE id=?", (plan.id,)).fetchone()
            )

    def register(self, identifier, identity):
        # Only protected verifier output is read, never passed/failed JSON supplied
        # by a browser or a bare administrator declaration.
        evidence = self.evidence_reader(identifier)
        if not isinstance(evidence, QualificationEvidence) or evidence.id != identifier:
            raise AdminError("admin_qualification_evidence_invalid", 409)
        with self.store.transaction() as connection:
            self._identity(connection, identity)
            row, plan = self._plan(connection, evidence.qualification_id)
            if row["identity"] != identity["id"] or row["state"] not in {"running", "aborted"}:
                raise AdminError("admin_qualification_not_running", 409)
            if (
                evidence.environment_hash != plan.environment_hash
                or not plan.starts <= evidence.observed <= self.store.clock() < evidence.expires
                or (evidence.kind not in CLEANUP_EVIDENCE and evidence.expires > plan.expires)
            ):
                raise AdminError("admin_qualification_evidence_stale", 409)
            values = (
                evidence.id,
                plan.id,
                evidence.kind,
                evidence.artifact_digest,
                evidence.environment_hash,
                evidence.observed,
                evidence.expires,
                int(evidence.passed),
            )
            existing = connection.execute(
                "SELECT * FROM qualification_evidence WHERE id=? OR "
                "(qualification_id=? AND kind=? AND kind NOT IN ('retirement','restoration'))",
                (evidence.id, plan.id, evidence.kind),
            ).fetchone()
            if existing:
                if tuple(existing) != values:
                    raise AdminError("admin_qualification_evidence_conflict", 409)
                return {"id": identifier, "registered": True}
            connection.execute(
                "INSERT INTO qualification_evidence VALUES (?,?,?,?,?,?,?,?)", values
            )
            self.store._audit(connection, "qualification_evidence_registered", identifier)
        return {"id": identifier, "registered": True}

    def command(self, command, identity, credential=None):
        snapshot = self.snapshot()
        with self.store.transaction() as connection:
            self._identity(connection, identity)
            prior = connection.execute(
                "SELECT * FROM qualification_receipt WHERE id=?", (command.operation_id,)
            ).fetchone()
            if prior:
                if prior["request_hash"] != command.fingerprint():
                    raise AdminError("admin_qualification_conflict", 409)
                return json.loads(prior["result"])
            row, plan = self._plan(connection, command.qualification_id)
            capacity = connection.execute("SELECT * FROM capacity WHERE id=1").fetchone()
            if (
                not capacity
                or row["revision"] != command.expected_revision
                or capacity["revision"] != command.expected_capacity_revision
            ):
                raise AdminError("admin_qualification_revision_conflict", 409)
            if row["identity"] != identity["id"] or not command.reason.strip():
                raise AdminError("admin_qualification_authority_invalid", 403)
            state = self._transition(connection, command, identity, credential, row, plan, snapshot)
            connection.execute(
                "UPDATE qualification SET state=?,generation=?,revision=revision+1 WHERE id=?",
                (state, identity["generation"], plan.id),
            )
            result = {
                "id": plan.id,
                "state": state,
                "revision": row["revision"] + 1,
                "capacity_revision": capacity["revision"] + int(state == "promoted"),
                "ceiling": 3 if state == "promoted" else capacity["ceiling"],
            }
            connection.execute(
                "INSERT INTO qualification_receipt VALUES (?,?,?)",
                (command.operation_id, command.fingerprint(), canonical(result)),
            )
            self.store._audit(connection, "qualification_" + state, plan.id)
            return result

    def _transition(self, connection, command, identity, credential, row, plan, snapshot):
        action, state = command.action, row["state"]
        if action == "abort" and state in {"planned", "running"}:
            return "aborted"  # resources/reservations retained until verified retirement
        if (action == "start" and state == "planned") or (
            action == "resume" and state == "running"
        ):
            self._room(connection, plan, snapshot)
            if not plan.starts <= self.store.clock() < plan.expires:
                raise AdminError("admin_qualification_window_invalid", 409)
            if action == "resume" or row["generation"] != identity["generation"]:
                self.store._consume(connection, credential or "", "action", command.fingerprint())
            return "running"
        if action == "retire" and state in {"running", "aborted"}:
            self._fresh(snapshot)
            self._evidence(connection, plan, CLEANUP_EVIDENCE)
            if not snapshot.test_resources_retired or not snapshot.baseline_restored:
                raise AdminError("admin_qualification_restoration_pending", 409)
            return "retired"
        if action == "promote" and state == "retired":
            self._fresh(snapshot)
            self._evidence(connection, plan, REQUIRED_EVIDENCE)
            if (
                snapshot.environment_hash != plan.environment_hash
                or snapshot.release != plan.release
                or snapshot.profile != plan.profile
                or not snapshot.baseline_restored
                or not snapshot.test_resources_retired
            ):
                raise AdminError("admin_qualification_environment_changed", 409)
            if connection.execute(
                "SELECT 1 FROM qualification WHERE id!=? AND state IN ('planned','running','aborted')",
                (plan.id,),
            ).fetchone():
                raise AdminError("admin_qualification_reservations_pending", 409)
            if (
                snapshot.memory_committed * 4 > snapshot.memory_total * 3
                or snapshot.disk_free - snapshot.disk_committed
                < max(snapshot.disk_total // 5, snapshot.recovery_staging)
            ):
                raise AdminError("admin_physical_capacity_blocked", 409)
            self.store._consume(connection, credential or "", "action", command.fingerprint())
            connection.execute(
                "UPDATE capacity SET ceiling=3,revision=revision+1,environment_hash=? WHERE id=1",
                (plan.environment_hash,),
            )
            return "promoted"
        raise AdminError("admin_qualification_transition_invalid", 409)

    def _evidence(self, connection, plan, kinds):
        rows = connection.execute(
            "SELECT e.* FROM qualification_evidence e WHERE qualification_id=? "
            "AND NOT EXISTS (SELECT 1 FROM qualification_evidence newer "
            "WHERE newer.qualification_id=e.qualification_id AND newer.kind=e.kind "
            "AND (newer.observed>e.observed OR "
            "(newer.observed=e.observed AND newer.rowid>e.rowid)))",
            (plan.id,),
        ).fetchall()
        valid = set()
        for row in rows:
            if row["kind"] not in kinds:
                continue
            try:
                verified = self.evidence_reader(row["id"])
            except (OSError, ValueError, KeyError) as error:
                raise AdminError("admin_qualification_evidence_unavailable", 503) from error
            expected = (
                verified.id,
                verified.qualification_id,
                verified.kind,
                verified.artifact_digest,
                verified.environment_hash,
                verified.observed,
                verified.expires,
                int(verified.passed),
            )
            if tuple(row) != expected:
                raise AdminError("admin_qualification_evidence_changed", 409)
            if (
                row["passed"]
                and row["environment_hash"] == plan.environment_hash
                and row["expires"] > self.store.clock()
            ):
                valid.add(row["kind"])
        if not kinds <= valid:
            raise AdminError("admin_qualification_evidence_incomplete", 409)

    def admission_check(self, connection, intent, reservations):
        snapshot = self.snapshot()
        self._fresh(snapshot)
        required = {
            "hostname",
            "port",
            "user",
            "mount",
            "image",
            "workspace",
            "email",
            "disk",
            "memory",
        }
        if len(reservations) != len(required) or {item.kind for item in reservations} != required:
            raise AdminError("admin_allocation_spec_incomplete", 422)
        amounts = {item.kind: item.amount for item in reservations}
        port = next(item.identity for item in reservations if item.kind == "port")
        if (
            not port.isascii()
            or not port.isdigit()
            or not 1024 <= int(port) <= 65535
            or amounts["memory"] <= 0
            or amounts["disk"] <= 0
        ):
            raise AdminError("admin_allocation_spec_invalid", 422)
        capacity = connection.execute("SELECT * FROM capacity WHERE id=1").fetchone()
        if not capacity or capacity["environment_hash"] != snapshot.environment_hash:
            raise AdminError("admin_capacity_unqualified", 409)
        if intent.kind == "qualification_test":
            row, plan = self._plan(connection, intent.qualification_id)
            if (
                row["state"] != "running"
                or row["generation"] != self.store._identity(connection)["generation"]
                or not plan.starts <= self.store.clock() < plan.expires
            ):
                raise AdminError("admin_qualification_not_running", 409)
            emails = {item.identity for item in reservations if item.kind == "email"}
            hosts = {item.identity for item in reservations if item.kind == "hostname"}
            if (
                len(emails) != 1
                or len(hosts) != 1
                or not any(
                    item.email in emails and item.hostname in hosts for item in plan.identities
                )
            ):
                raise AdminError("admin_qualification_identity_conflict", 409)
            existing = connection.execute(
                "SELECT count(*) FROM operation WHERE kind='qualification_test' AND json_extract(payload,'$.qualification_id')=?",
                (plan.id,),
            ).fetchone()[0]
            if existing >= plan.target:
                raise AdminError("admin_qualification_test_limit", 409)
            prior_budgets = dict(
                connection.execute(
                    "SELECT r.kind,sum(r.amount) FROM reservation r JOIN operation o ON o.id=r.operation_id WHERE json_extract(o.payload,'$.qualification_id')=? GROUP BY r.kind",
                    (plan.id,),
                ).fetchall()
            )
            if (
                prior_budgets.get("memory", 0) + amounts["memory"] > plan.memory_bytes
                or prior_budgets.get("disk", 0) + amounts["disk"] > plan.disk_bytes
            ):
                raise AdminError("admin_qualification_budget_exceeded", 409)
        else:
            reserved = connection.execute(
                "SELECT count(*) FROM operation WHERE kind='provision' AND state!='cancelled'"
            ).fetchone()[0]
            if snapshot.active_count + reserved >= capacity["ceiling"]:
                raise AdminError("admin_capacity_unqualified", 409)
        # Per-operation physical limits include all retained reservations. A
        # qualification bypasses only the ordinary count ceiling, never capacity.
        totals = dict(
            connection.execute("SELECT kind,sum(amount) FROM reservation GROUP BY kind").fetchall()
        )
        memory = (
            snapshot.memory_committed
            + totals.get("memory", 0)
            + sum(item.amount for item in reservations if item.kind == "memory")
        )
        disk = (
            snapshot.disk_committed
            + totals.get("disk", 0)
            + sum(item.amount for item in reservations if item.kind == "disk")
        )
        if memory * 4 > snapshot.memory_total * 3 or snapshot.disk_free - disk < max(
            snapshot.disk_total // 5, snapshot.recovery_staging
        ):
            raise AdminError("admin_physical_capacity_blocked", 409)

    def status(self, identifier):
        with self.store.transaction() as connection:
            row, _ = self._plan(connection, identifier)
            evidence = connection.execute(
                "SELECT id,kind,observed,expires,passed FROM qualification_evidence WHERE qualification_id=? ORDER BY kind",
                (identifier,),
            ).fetchall()
            return self._view(row) | {"evidence": [dict(item) for item in evidence]}

    @staticmethod
    def _view(row):
        return {key: row[key] for key in ("id", "revision", "state", "created")}

    @staticmethod
    def _plan(connection, identifier):
        row = connection.execute("SELECT * FROM qualification WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise AdminError("admin_qualification_not_found", 404)
        return row, QualificationPlan.model_validate_json(row["payload"])

    def _identity(self, connection, identity):
        if dict(self.store._identity(connection)) != identity:
            raise AdminError("admin_authority_fenced", 409)

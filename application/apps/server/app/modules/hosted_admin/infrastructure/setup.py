"""Versioned acknowledged setup and atomic provisioning admission."""

from datetime import datetime
import json
import threading
from zoneinfo import ZoneInfo

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import canonical, fingerprint
from app.modules.hosted_admin.application.setup import SetupData, SetupHost, SetupPlan
from app.modules.hosted_admin.infrastructure.operations import OperationEngine, enqueue

MAX_DRAFTS = 100


class SetupService:
    def __init__(self, store, host: SetupHost):
        self.store, self.host = store, host
        self.engine = OperationEngine(store)

    def handle(self, request, identity):
        if request.method == "setup_options":
            return self.host.options()
        if request.method == "setup_list":
            with self.store.transaction() as connection:
                return {
                    "items": [
                        self.view(row)
                        for row in connection.execute(
                            "SELECT * FROM setup_draft WHERE identity=? AND state!='discarded' ORDER BY saved DESC,id DESC LIMIT 100",
                            (identity["id"],),
                        )
                    ]
                }
        if request.method == "setup_get":
            with self.store.transaction() as connection:
                return self.view(self.get(connection, request.draft_id, identity))
        if request.method == "setup_status":
            return self.status(request.draft_id, identity)
        command = request.setup
        if command.action == "create":
            return self.admit(request, identity)
        with self.store.transaction() as connection:
            current = dict(self.store.session(connection, request.token, request.csrf))
            if current != identity:
                raise AdminError("admin_authority_fenced", 409)
            if command.action == "save":
                return self.save(connection, command, identity)
            row = self.get(connection, command.draft_id, identity)
            if row["revision"] != command.expected_revision or row["state"] != "draft":
                raise AdminError("admin_setup_revision_conflict", 409)
            if command.action == "discard":
                connection.execute(
                    "UPDATE setup_draft SET state='discarded',revision=revision+1,saved=? WHERE id=?",
                    (self.store.clock(), row["id"]),
                )
                self.store._audit(connection, "setup_discarded", row["id"])
            return self.view(self.get(connection, row["id"], identity))

    def get(self, connection, identifier, identity):
        row = connection.execute(
            "SELECT * FROM setup_draft WHERE id=? AND identity=?", (identifier, identity["id"])
        ).fetchone()
        if row is None:
            raise AdminError("admin_setup_not_found", 404)
        return row

    def save(self, connection, command, identity):
        encoded = canonical(command.data.model_dump())
        row = connection.execute(
            "SELECT * FROM setup_draft WHERE id=?", (command.draft_id,)
        ).fetchone()
        if row:
            if row["identity"] != identity["id"]:
                raise AdminError("admin_setup_not_found", 404)
            if (
                row["state"] == "draft"
                and row["data"] == encoded
                and row["revision"] in {command.expected_revision, command.expected_revision + 1}
            ):
                return self.view(row)
            if row["state"] != "draft" or row["revision"] != command.expected_revision:
                raise AdminError("admin_setup_revision_conflict", 409)
            connection.execute(
                "UPDATE setup_draft SET data=?,revision=revision+1,saved=? WHERE id=?",
                (encoded, self.store.clock(), row["id"]),
            )
        else:
            if (
                command.expected_revision
                or connection.execute("SELECT count(*) FROM setup_draft").fetchone()[0]
                >= MAX_DRAFTS
            ):
                raise AdminError("admin_setup_capacity_or_revision", 409)
            connection.execute(
                "INSERT INTO setup_draft VALUES (?,?,1,'draft',?,NULL,NULL,?)",
                (command.draft_id, identity["id"], encoded, self.store.clock()),
            )
        self.store._audit(connection, "setup_saved", command.draft_id)
        return self.view(self.get(connection, command.draft_id, identity))

    def admit(self, request, identity):
        command = request.setup
        # Exact replay needs no provider availability and never allocates again.
        with self.store.transaction() as connection:
            row = dict(self.get(connection, command.draft_id, identity))
            if row["state"] == "started":
                if (
                    row["operation_id"] != command.operation_id
                    or row["revision"] != command.expected_revision + 1
                    or command.review_hash
                    != fingerprint(
                        {"data": json.loads(row["data"]), "plan": json.loads(row["plan"])}
                    )
                ):
                    raise AdminError("admin_command_conflict", 409)
                return self.view(row)
            if row["state"] != "draft" or row["revision"] != command.expected_revision:
                raise AdminError("admin_setup_revision_conflict", 409)
        data = SetupData.model_validate_json(row["data"])
        try:
            data.ready()
        except (ValueError, KeyError) as error:
            raise AdminError("admin_setup_incomplete", 422) from error
        if data.expires <= self.store.clock():
            raise AdminError("admin_setup_window_expired", 409)
        # Host lock spans observation and admission. All slow external reads
        # finish BEFORE taking the control-plane write transaction.
        with self.host.admission(row["id"], data) as prepared:
            if command.review_hash != fingerprint(
                {"data": data.model_dump(), "plan": prepared["plan"]}
            ):
                raise AdminError("admin_setup_revision_conflict", 409)
            with self.store.transaction() as connection:
                if dict(self.store.session(connection, request.token, request.csrf)) != identity:
                    raise AdminError("admin_authority_fenced", 409)
                current = self.get(connection, row["id"], identity)
                if current["revision"] != row["revision"] or current["state"] != "draft":
                    raise AdminError("admin_setup_revision_conflict", 409)
                self.host.check(connection, prepared["plan"], prepared)
                self.create(connection, row, command, identity, prepared["plan"])
                return self.view(self.get(connection, row["id"], identity))

    def create(self, connection, row, command, identity, plan):
        data = SetupData.model_validate_json(row["data"])
        plan = SetupPlan.model_validate(plan).model_dump()
        payload = {
            "operation_id": command.operation_id,
            "kind": "provision",
            "target": plan["key"],
            "expected_revision": 0,
            "qualification_id": None,
            "reason": "Create isolated synthetic demo",
            "allocation_spec": plan["reservations"],
            "setup": {"draft_id": row["id"], "data": data.model_dump(), "plan": plan},
        }
        enqueue(
            connection,
            self.store,
            identifier=command.operation_id,
            identity=identity,
            kind="provision",
            target=plan["key"],
            payload=payload,
        )
        import sqlite3

        try:
            for item in plan["reservations"]:
                connection.execute(
                    "INSERT INTO reservation VALUES (?,?,?,?,?)",
                    (
                        item["kind"],
                        item["identity"],
                        item["amount"],
                        command.operation_id,
                        plan["key"],
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise AdminError("admin_allocation_conflict", 409) from error
        connection.execute(
            "UPDATE setup_draft SET state='started',plan=?,operation_id=?,revision=revision+1,saved=? WHERE id=?",
            (canonical(plan), command.operation_id, self.store.clock(), row["id"]),
        )
        self.store._audit(connection, "setup_started", row["id"])

    @staticmethod
    def view(row):
        plan = json.loads(row["plan"]) if row["plan"] else None
        return {key: row[key] for key in ("id", "revision", "state", "saved", "operation_id")} | {
            "data": json.loads(row["data"]),
            "instance": plan["key"] if plan else None,
            "hostname": plan["hostname"] if plan else None,
        }

    def status(self, identifier, identity):
        with self.store.transaction() as connection:
            row = self.get(connection, identifier, identity)
            value = self.view(row)
        if row["state"] != "started":
            if row["state"] == "draft":
                try:
                    plan = self.host.plan(row["id"], SetupData.model_validate_json(row["data"]))
                    value.update(hostname=plan["hostname"], instance=plan["key"])
                    value["review_hash"] = fingerprint({"data": value["data"], "plan": plan})
                except OSError, ValueError:
                    pass  # Unconfigured hosts still support acknowledged drafts.
            return value
        operation = self.engine.get(row["operation_id"], identity["id"])
        value["operation"] = operation
        if operation["state"] != "succeeded":
            return value
        enrollment = self.host.enrollment(value["instance"])
        # This source read must never infer activation from a healthy process.
        value["enrollment"] = enrollment
        value["lifecycle"] = (
            "identity_approved_recovery_pending"
            if enrollment["approved"]
            else "scheduled"
            if self.store.clock() < value["data"]["starts"]
            else "awaiting_approval"
            if enrollment["status"].get("enrollments")
            else "waiting_for_sign_in"
        )
        if self.store.clock() >= value["data"]["expires"]:
            value["lifecycle"] = "expired"
        if value["lifecycle"] != "expired":
            value["invitation"] = invitation(value["data"], value["hostname"])
        # Slice 6 alone may issue ready-to-use instructions after verified
        # completion. Identity-only approval cannot produce those instructions.
        value["ready_instructions"] = None
        return value


def invitation(data, hostname):
    def stamp(instant):
        return (
            datetime.fromtimestamp(instant, ZoneInfo(data["timezone"])).strftime(
                "%b %d, %Y %H:%M %Z (UTC%z)"
            )
            + " · "
            + data["timezone"]
        )

    return (
        f"Your demo opens {stamp(data['starts'])} and expires {stamp(data['expires'])}. "
        f"Before it opens, the link may show that access has not started; return at the start time. "
        f"Then open https://{hostname}, sign in with {data['email']} using Cloudflare's email PIN, "
        "and select Continue to workspace to request approval. A pending-approval screen is expected on first use. "
        f"Contact {data['support']} if needed; do not repeatedly request new PINs to resolve pending approval. "
        "After the administrator confirms setup is complete and access is ready, return to the same link "
        "and select Continue to workspace again. Renew sign-in if prompted. Use synthetic data only."
    )


class SetupWorker:
    """One bounded background worker; committed jobs outlive HTTP connections."""

    def __init__(self, service):
        self.service, self.stopping = service, threading.Event()
        self.thread = threading.Thread(target=self.loop, name="admin-setup", daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=30)

    def tick(self):
        with self.service.store.transaction() as connection:
            rows = connection.execute(
                "SELECT o.id,o.cancel_requested FROM operation o JOIN setup_draft d ON d.operation_id=o.id WHERE o.state IN ('queued','running') OR (o.cancel_requested=1 AND o.state='paused') ORDER BY o.created LIMIT 10"
            ).fetchall()
        for row in rows:
            try:
                if row["cancel_requested"]:
                    self.service.engine.finish_cancel(row["id"], self.service.host)
                else:
                    self.service.engine.run(row["id"], self.service.host)
            except Exception:
                # The engine retains the safe failed/unknown checkpoint. Never
                # retry an unknown external outcome automatically.
                continue

    def loop(self):
        while not self.stopping.is_set():
            self.tick()
            self.stopping.wait(2)

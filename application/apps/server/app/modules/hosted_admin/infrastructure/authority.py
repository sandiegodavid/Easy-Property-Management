"""Private durable authority. Sessions expire; admitted work belongs to the identity generation."""

from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import time

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.infrastructure.operation_schema import SCHEMA as OPERATION_SCHEMA
from app.modules.hosted_admin.infrastructure.operations import OperationEngine, enqueue
from app.modules.hosted_admin.application.operations import Observation
from app.modules.hosted_admin.infrastructure.control_recovery import validate_control

GRANT_SECONDS = 300
IDLE_SECONDS = 1800
ABSOLUTE_SECONDS = 28800
MAX_ATTEMPTS = 10

SCHEMA = (
    """
CREATE TABLE administrator (id TEXT PRIMARY KEY, generation INTEGER NOT NULL CHECK(generation>0), enabled INTEGER NOT NULL CHECK(enabled IN (0,1)));
CREATE TABLE grant (hash TEXT PRIMARY KEY, purpose TEXT NOT NULL CHECK(purpose IN ('bootstrap','action')), request_hash TEXT,
 generation INTEGER NOT NULL, expires REAL NOT NULL CHECK(expires>=0), used INTEGER NOT NULL CHECK(used IN (0,1)));
CREATE TABLE session (hash TEXT PRIMARY KEY, csrf_hash TEXT NOT NULL, generation INTEGER NOT NULL,
 created REAL NOT NULL, touched REAL NOT NULL, revoked INTEGER NOT NULL CHECK(revoked IN (0,1)));
CREATE TABLE authorization (session_hash TEXT NOT NULL, request_hash TEXT NOT NULL,
 generation INTEGER NOT NULL, expires REAL NOT NULL, PRIMARY KEY(session_hash, request_hash));
CREATE TABLE admission (id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, generation INTEGER NOT NULL,
 payload TEXT NOT NULL, result TEXT, created REAL NOT NULL);
CREATE TRIGGER admission_intent_immutable BEFORE UPDATE OF id,request_hash,generation,payload,created ON admission
 BEGIN SELECT RAISE(ABORT,'immutable intent'); END;
CREATE TRIGGER admission_no_delete BEFORE DELETE ON admission BEGIN SELECT RAISE(ABORT,'immutable intent'); END;
CREATE TRIGGER admission_result_immutable BEFORE UPDATE OF result ON admission WHEN OLD.result IS NOT NULL
 BEGIN SELECT RAISE(ABORT,'immutable result'); END;
CREATE TABLE audit (sequence INTEGER PRIMARY KEY, action TEXT NOT NULL, reference TEXT NOT NULL, at REAL NOT NULL);
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TABLE attempts (id INTEGER PRIMARY KEY CHECK(id=1), since REAL NOT NULL, count INTEGER NOT NULL);
PRAGMA user_version=1;
"""
    + OPERATION_SCHEMA
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def private_path(path: Path, owner=None):
    owner = os.geteuid() if owner is None else owner
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_mode & 0o077:
        raise AdminError("admin_store_unsafe", 503)
    private_directory(path.parent, owner)


def private_directory(path, owner):
    parent = path.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != owner or parent.st_mode & 0o077:
        raise AdminError("admin_store_unsafe", 503)


class AuthorityStore:
    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        private_path(self.path)
        with self.transaction() as connection:
            if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise AdminError("admin_schema_invalid", 503)
            # Exact current-format schema, including immutability triggers.
            memory = sqlite3.connect(":memory:")
            try:
                memory.executescript(SCHEMA)
                query = "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
                if [tuple(row) for row in connection.execute(query)] != memory.execute(
                    query
                ).fetchall():
                    raise AdminError("admin_schema_invalid", 503)
            finally:
                memory.close()
            identities = connection.execute("SELECT * FROM administrator").fetchall()
            if len(identities) != 1:
                raise AdminError("admin_identity_invalid", 503)
            identity = identities[0]
            if (
                type(identity["generation"]) is not int
                or identity["generation"] <= 0
                or identity["enabled"] not in (0, 1)
                or not identity["id"].strip()
                or len(identity["id"]) > 96
            ):
                raise AdminError("admin_identity_invalid", 503)
            validate_control(connection)

    @classmethod
    def initialize(cls, path, identity):
        path = Path(path)
        if not identity.strip() or len(identity) > 96:
            raise AdminError("admin_identity_invalid")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        private_directory(path.parent, os.geteuid())
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with sqlite3.connect(path) as connection:
            connection.executescript(SCHEMA)
            connection.execute("INSERT INTO administrator VALUES (?,1,1)", (identity,))
        return cls(path)

    @contextmanager
    def transaction(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _identity(self, connection):
        identity = connection.execute("SELECT * FROM administrator").fetchone()
        if not identity["enabled"]:
            raise AdminError("admin_revoked")
        return identity

    def _audit(self, connection, action, reference):
        connection.execute(
            "INSERT INTO audit(action,reference,at) VALUES (?,?,?)",
            (action, reference, self.clock()),
        )

    def issue(self, request_hash=None):
        token = secrets.token_urlsafe(32)
        with self.transaction() as connection:
            identity = self._identity(connection)
            connection.execute("DELETE FROM grant WHERE expires <= ? OR used=1", (self.clock(),))
            connection.execute(
                "INSERT INTO grant VALUES (?,?,?,?,?,0)",
                (
                    digest(token),
                    "action" if request_hash else "bootstrap",
                    request_hash,
                    identity["generation"],
                    self.clock() + GRANT_SECONDS,
                ),
            )
            self._audit(connection, "grant_issued", identity["id"])
        return token

    def _consume(self, connection, credential, purpose, request_hash=None):
        identity = self._identity(connection)
        row = connection.execute(
            "SELECT * FROM grant WHERE hash=?", (digest(credential),)
        ).fetchone()
        if (
            row is None
            or row["used"]
            or row["expires"] <= self.clock()
            or row["generation"] != identity["generation"]
            or row["purpose"] != purpose
            or row["request_hash"] != request_hash
        ):
            raise AdminError("admin_grant_invalid", 401)
        connection.execute("UPDATE grant SET used=1 WHERE hash=?", (digest(credential),))
        return identity

    def _attempt(self):
        # Commit rate accounting separately, including unsuccessful exchanges.
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM attempts WHERE id=1").fetchone()
            if row is None or row["since"] + GRANT_SECONDS <= self.clock():
                connection.execute(
                    "INSERT OR REPLACE INTO attempts VALUES (1,?,1)", (self.clock(),)
                )
            elif row["count"] >= MAX_ATTEMPTS:
                raise AdminError("admin_attempt_limit", 429)
            else:
                connection.execute("UPDATE attempts SET count=count+1 WHERE id=1")

    def login(self, credential):
        self._attempt()
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.transaction() as connection:
            identity = self._consume(connection, credential, "bootstrap")
            connection.execute(
                "DELETE FROM session WHERE created+?<=? OR revoked=1",
                (ABSOLUTE_SECONDS, self.clock()),
            )
            connection.execute(
                "INSERT INTO session VALUES (?,?,?,?,?,0)",
                (digest(token), digest(csrf), identity["generation"], self.clock(), self.clock()),
            )
            self._audit(connection, "signed_in", identity["id"])
        return {"token": token, "csrf": csrf}

    def session(self, connection, token, csrf=None):
        identity = self._identity(connection)
        row = connection.execute("SELECT * FROM session WHERE hash=?", (digest(token),)).fetchone()
        if (
            row is None
            or row["revoked"]
            or row["generation"] != identity["generation"]
            or row["created"] + ABSOLUTE_SECONDS <= self.clock()
            or row["touched"] + IDLE_SECONDS <= self.clock()
        ):
            raise AdminError("admin_session_expired", 401)
        if csrf is not None and not hmac.compare_digest(row["csrf_hash"], digest(csrf)):
            raise AdminError("admin_csrf_invalid")
        connection.execute(
            "UPDATE session SET touched=? WHERE hash=?", (self.clock(), digest(token))
        )
        return identity

    def reauthenticate(self, request):
        self._attempt()
        if request.command is None:
            raise AdminError("admin_command_required", 400)
        fingerprint = request.command.fingerprint()
        with self.transaction() as connection:
            identity = self.session(connection, request.token, request.csrf)
            self._consume(connection, request.credential, "action", fingerprint)
            connection.execute(
                "INSERT OR REPLACE INTO authorization VALUES (?,?,?,?)",
                (
                    digest(request.token),
                    fingerprint,
                    identity["generation"],
                    self.clock() + GRANT_SECONDS,
                ),
            )
            self._audit(connection, "action_authorized", request.command.operation_id)
        return {"authorized": True}

    def admit(self, request, prepare=None):
        command = request.command
        if command is None:
            raise AdminError("admin_command_required", 400)
        fingerprint = command.fingerprint()
        with self.transaction() as connection:
            identity = self.session(connection, request.token, request.csrf)
            prior = connection.execute(
                "SELECT * FROM admission WHERE id=?", (command.operation_id,)
            ).fetchone()
            if prior:
                if prior["request_hash"] != fingerprint:
                    raise AdminError("admin_command_conflict", 409)
                if prior["generation"] != identity["generation"]:
                    raise AdminError("admin_authority_fenced", 409)
                return dict(prior)
            if command.action not in {"disable", "revoke"}:
                grant = connection.execute(
                    "SELECT * FROM authorization WHERE session_hash=? AND request_hash=?",
                    (digest(request.token), fingerprint),
                ).fetchone()
                if (
                    not grant
                    or grant["generation"] != identity["generation"]
                    or grant["expires"] <= self.clock()
                ):
                    raise AdminError("admin_reauthentication_required", 401)
                connection.execute(
                    "DELETE FROM authorization WHERE session_hash=? AND request_hash=?",
                    (digest(request.token), fingerprint),
                )
            source = prepare(command.instance) if prepare else None
            payload = command.model_dump() | {
                "authority_reference": f"{identity['id']}:{identity['generation']}"
            }
            if source is not None:
                payload["source_reference"] = source
            connection.execute(
                "INSERT INTO admission VALUES (?,?,?,?,NULL,?)",
                (
                    command.operation_id,
                    fingerprint,
                    identity["generation"],
                    json.dumps(payload),
                    self.clock(),
                ),
            )
            enqueue(
                connection,
                self,
                identifier=command.operation_id,
                identity=identity,
                kind="source",
                target=command.instance,
                payload=payload,
            )
            self._audit(connection, "command_admitted", command.operation_id)
            return dict(
                connection.execute(
                    "SELECT * FROM admission WHERE id=?", (command.operation_id,)
                ).fetchone()
            )

    def execute(self, admission, dispatch):
        # The source owns its immutable receipt. No authority-store write lock
        # spans a source process/provider call; a priority fence can always commit.
        return OperationEngine(self).run(admission["id"], SourceEffect(dispatch))

    def revoke_identity(self):
        with self.transaction() as connection:
            connection.execute("UPDATE administrator SET generation=generation+1,enabled=0")
            connection.execute("UPDATE session SET revoked=1")
            connection.execute("DELETE FROM authorization")
            self._audit(connection, "identity_revoked", "administrator")

    def restore_identity(self):
        """Explicit root recovery; old sessions, grants and admitted work stay fenced."""
        with self.transaction() as connection:
            connection.execute("UPDATE administrator SET generation=generation+1,enabled=1")
            connection.execute("UPDATE session SET revoked=1")
            connection.execute("DELETE FROM authorization")
            connection.execute("DELETE FROM grant")
            self._audit(connection, "identity_restored", "administrator")

    def handle(self, request, dispatch, console=None):
        if request.method == "login":
            return self.login(request.credential)
        if request.method == "reauthenticate":
            return self.reauthenticate(request)
        if request.method == "command":
            return self.execute(self.admit(request, getattr(dispatch, "prepare", None)), dispatch)
        if request.method.startswith("console_"):
            with self.transaction() as connection:
                identity = dict(self.session(connection, request.token, request.csrf))
            if console is None:
                raise AdminError("admin_console_unavailable", 503)
            return console.handle(request, identity)
        if request.method in {"operation", "operation_list", "resume", "cancel"}:
            with self.transaction() as connection:
                identity = dict(self.session(connection, request.token, request.csrf))
            engine = OperationEngine(self)
            if request.method == "operation_list":
                return engine.recent(identity["id"])
            if request.method == "operation":
                return engine.get(request.operation_id, identity["id"])
            if request.method == "cancel":
                return engine.cancel(request.operation_id, request.expected_revision, identity)
            return engine.resume(
                request.operation_id, request.expected_revision, identity, request.credential
            )
        if request.method == "source_status":
            with self.transaction() as connection:
                self.session(connection, request.token, request.csrf)
            return dispatch.status(request.instance)
        with self.transaction() as connection:
            identity = self.session(
                connection, request.token, None if request.method == "session" else request.csrf
            )
            if request.method == "logout":
                connection.execute(
                    "UPDATE session SET revoked=1 WHERE hash=?", (digest(request.token),)
                )
                self._audit(connection, "signed_out", identity["id"])
                return {"signed_out": True, "committed_work_continues": True}
            if request.method == "lookup":
                row = connection.execute(
                    "SELECT result FROM admission WHERE id=?", (request.operation_id,)
                ).fetchone()
                return {
                    "found": row is not None,
                    "result": json.loads(row["result"]) if row and row["result"] else None,
                }
            return {"identity": identity["id"]}


class SourceEffect:
    """Adapt the source-owned receipt lookup to the durable step protocol."""

    def __init__(self, dispatch):
        self.dispatch = dispatch
        self.result = None

    def inspect(self, payload, _step):
        if hasattr(self.dispatch, "reconcile"):
            result = self.dispatch.reconcile(payload)
        else:
            # In-process application adapters may return an already verified
            # receipt; production uses SourceRunner.reconcile on every retry.
            result = self.result
        return (
            Observation("verified", result, payload["operation_id"])
            if result is not None
            else Observation("absent")
        )

    def apply(self, payload, _step):
        self.result = self.dispatch(payload)

    def contain(self, payload):
        return bool(hasattr(self.dispatch, "contain") and self.dispatch.contain(payload))

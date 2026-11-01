"""Private host inventory primitives; never part of a portable workspace.

This store does not discover or approve instances. A trusted reconciliation
adapter must establish the observed facts before using ``register``.
"""

from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from uuid import UUID, uuid4

KEY = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
DIGEST = re.compile(r"[a-f0-9]{64}")
SCHEMA_VERSION = 1
MAX_PORT = 65535
MAX_HOSTNAME_LENGTH = 253
MAX_EMAIL_LENGTH = 254
MAX_INSTANCES = 1000
MAX_RECORD_BYTES = 256 * 1024
MAINTENANCE_ACTIONS = {
    "release": {
        "install",
        "deploy",
        "resume",
        "rollback",
        "reset-demo",
        "resume-reset",
        "rollback-reset",
        "backup",
    },
    "cleanup": {"cleanup"},
    "reconciliation": {"breakglass"},
}
RESERVED_KEYS = frozenset({"admin", "tunnel", "volumes", "recovery"})
IMMUTABLE_ALLOCATION_FIELDS = (
    "key",
    "instance_id",
    "allocation_id",
    "operator_id",
    "email",
    "hostname",
    "port",
    "user",
    "mount",
    "image",
    "local_config",
)


class InventoryError(ValueError):
    """Invalid, inconsistent, or inaccessible host inventory."""


class MaintenanceBusy(InventoryError):
    """A live holder owns the shared host maintenance lock."""


def valid_hostname(value):
    return (
        isinstance(value, str)
        and len(value) <= MAX_HOSTNAME_LENGTH
        and "." in value
        and any(character.isalpha() for character in value)
        and all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in value.split(".")
        )
    )


@dataclass(frozen=True)
class MaintenanceRequest:
    key: str | None = None
    release: str | None = None
    resume: str | None = None
    incident: str | None = None


@dataclass(frozen=True)
class Instance:
    key: str
    instance_id: str
    allocation_id: str
    operator_id: str
    workspace_id: str
    email: str
    hostname: str
    port: int
    user: str
    mount: str
    image: str
    release: str
    profile: str
    template: str
    config_digest: str
    baseline_digest: str
    local_config: str
    access_database: str
    workspace: str
    revision: int = 1
    lifecycle: str = "adopted"

    def validate(self):
        self._validate_identity()
        self._validate_paths()
        if self.mount == self.image or not all(
            KEY.fullmatch(value) for value in (self.release, self.profile, self.template)
        ):
            raise InventoryError("Invalid allocation or release identity.")
        if not DIGEST.fullmatch(self.config_digest) or not DIGEST.fullmatch(self.baseline_digest):
            raise InventoryError("Invalid configuration or baseline digest.")
        if type(self.revision) is not int or self.revision < 1 or self.lifecycle != "adopted":
            raise InventoryError("Invalid instance lifecycle or revision.")
        if Path(self.mount) not in Path(self.workspace).parents:
            raise InventoryError("Workspace must belong to the allocated mount.")
        if Path(self.mount) in Path(self.access_database).parents:
            raise InventoryError("Access authority cannot be on the business volume.")

    def _validate_identity(self):
        if (
            self.key in RESERVED_KEYS
            or not KEY.fullmatch(self.key)
            or self.user != f"epm-{self.key}"
        ):
            raise InventoryError("Invalid instance key or user.")
        try:
            for value in (
                self.instance_id,
                self.allocation_id,
                self.operator_id,
                self.workspace_id,
            ):
                if str(UUID(value)) != value:
                    raise ValueError
        except (ValueError, TypeError, AttributeError) as error:
            raise InventoryError("Invalid inventory identity.") from error
        if (
            not valid_hostname(self.hostname)
            or len(self.email) > MAX_EMAIL_LENGTH
            or not re.fullmatch(r"[^\s@<>]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", self.email)
            or type(self.port) is not int
            or not 1 <= self.port <= MAX_PORT
        ):
            raise InventoryError("Invalid instance address or port.")

    def _validate_paths(self):
        for value in (
            self.mount,
            self.image,
            self.local_config,
            self.access_database,
            self.workspace,
        ):
            path = Path(value)
            if (
                not path.is_absolute()
                or value != str(path)
                or any(character.isspace() or not character.isprintable() for character in value)
                or ".." in path.parts
                or path == Path("/")
            ):
                raise InventoryError("Invalid allocation path.")


SCHEMA = """
CREATE TABLE instances (
  key TEXT PRIMARY KEY, instance_id TEXT NOT NULL UNIQUE,
  allocation_id TEXT NOT NULL UNIQUE, operator_id TEXT NOT NULL UNIQUE,
  workspace_id TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE,
  hostname TEXT NOT NULL UNIQUE, port INTEGER NOT NULL UNIQUE,
  user TEXT NOT NULL UNIQUE, mount TEXT NOT NULL UNIQUE, image TEXT NOT NULL UNIQUE,
  release TEXT NOT NULL, profile TEXT NOT NULL, template TEXT NOT NULL,
  config_digest TEXT NOT NULL, baseline_digest TEXT NOT NULL,
  local_config TEXT NOT NULL UNIQUE, access_database TEXT NOT NULL UNIQUE,
  workspace TEXT NOT NULL UNIQUE, revision INTEGER NOT NULL CHECK (revision > 0),
  lifecycle TEXT NOT NULL CHECK (lifecycle = 'adopted'),
  registered_at TEXT NOT NULL
) STRICT;
CREATE TRIGGER instances_no_delete BEFORE DELETE ON instances
BEGIN SELECT RAISE(ABORT, 'Instance allocations must be retained'); END;
CREATE TABLE maintenance (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, action TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('running', 'needs_reconciliation', 'reconciled')),
  started_at TEXT NOT NULL, finished_at TEXT, exit_code INTEGER,
  before_digest TEXT NOT NULL, after_digest TEXT,
  incident_reference TEXT, intent_json TEXT NOT NULL,
  CHECK (
    (state = 'running' AND finished_at IS NULL AND exit_code IS NULL AND after_digest IS NULL)
    OR (state = 'needs_reconciliation' AND finished_at IS NOT NULL AND exit_code IS NOT NULL
        AND after_digest IS NULL)
    OR (state = 'reconciled' AND finished_at IS NOT NULL AND exit_code IS NOT NULL
        AND after_digest IS NOT NULL)
  )
) STRICT;
CREATE TRIGGER maintenance_intent_immutable
BEFORE UPDATE OF kind, action, before_digest, intent_json ON maintenance
BEGIN SELECT RAISE(ABORT, 'Maintenance intent is immutable'); END;
CREATE UNIQUE INDEX one_unfinished_maintenance ON maintenance ((1))
  WHERE state != 'reconciled';
CREATE TABLE inventory_audit (
  sequence INTEGER PRIMARY KEY, action TEXT NOT NULL, reference TEXT NOT NULL,
  digest TEXT NOT NULL, recorded_at TEXT NOT NULL
) STRICT;
CREATE TRIGGER inventory_audit_no_update BEFORE UPDATE ON inventory_audit
BEGIN SELECT RAISE(ABORT, 'Inventory audit is append only'); END;
CREATE TRIGGER inventory_audit_no_delete BEFORE DELETE ON inventory_audit
BEGIN SELECT RAISE(ABORT, 'Inventory audit is append only'); END;
CREATE TABLE inventory_metadata (version INTEGER NOT NULL) STRICT;
INSERT INTO inventory_metadata VALUES (1);
"""


class HostInventory:
    """Root-private durable allocation registry, isolated from business data."""

    def __init__(self, path: Path, *, owner_uid: int = 0):
        self.path = path
        self.owner_uid = owner_uid

    def _check_directory(self):
        if not self.path.is_absolute() or self.path.parent.resolve() != self.path.parent:
            raise InventoryError("Inventory path must be absolute without symlinks.")
        info = self.path.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner_uid or info.st_mode & 0o077:
            raise InventoryError("Inventory directory must be owner-private and a real directory.")
        for parent in self.path.parent.parents:
            metadata = parent.lstat()
            sticky_root = metadata.st_uid == 0 and metadata.st_mode & stat.S_ISVTX
            if (
                stat.S_ISLNK(metadata.st_mode)
                or metadata.st_uid not in {0, self.owner_uid}
                or (metadata.st_mode & 0o022 and not sticky_root)
            ):
                raise InventoryError("Inventory ancestors must be protected directories.")

    def _check_file(self):
        self._check_directory()
        info = self.path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid or info.st_mode & 0o077:
            raise InventoryError("Inventory must be an owner-private regular file.")

    def initialize(self):
        self._check_directory()
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        os.close(descriptor)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript(SCHEMA)

    def _connect(self, *, writable=False):
        self._check_file()
        mode = "rw" if writable else "ro"
        connection = sqlite3.connect(f"{self.path.as_uri()}?mode={mode}", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            version = connection.execute("SELECT version FROM inventory_metadata").fetchall()
            if len(version) != 1 or version[0][0] != SCHEMA_VERSION:
                raise InventoryError("Unsupported or invalid inventory schema.")
            with closing(sqlite3.connect(":memory:")) as expected:
                expected.executescript(SCHEMA)
                query = "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
                if [tuple(row) for row in connection.execute(query)] != expected.execute(
                    query
                ).fetchall():
                    raise InventoryError("Inventory schema differs from the current format.")
        except (sqlite3.Error, InventoryError) as error:
            connection.close()
            raise InventoryError("Inventory is invalid or unreadable.") from error
        return connection

    @contextmanager
    def connection(self, *, writable=False):
        connection = self._connect(writable=writable)
        try:
            with connection:
                if writable:
                    connection.execute("BEGIN IMMEDIATE")
                yield connection
        finally:
            connection.close()

    def list(self):
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM instances ORDER BY key LIMIT ?", (MAX_INSTANCES + 1,)
            ).fetchall()
        if len(rows) > MAX_INSTANCES:
            raise InventoryError("Inventory exceeds its instance bound.")
        result = []
        for row in rows:
            data = dict(row)
            registered = data.pop("registered_at")
            try:
                timestamp = datetime.fromisoformat(registered)
                if timestamp.utcoffset() != UTC.utcoffset(timestamp):
                    raise ValueError
                instance = Instance(**data)
                instance.validate()
            except (ValueError, TypeError, KeyError) as error:
                raise InventoryError("Invalid retained inventory record.") from error
            result.append(instance)
        return result

    def register(self, instance: Instance):
        """Record already independently verified facts; never overwrite an allocation."""
        instance.validate()
        values = {**vars(instance), "registered_at": datetime.now(UTC).isoformat()}
        try:
            with self.connection(writable=True) as connection:
                if (
                    connection.execute("SELECT count(*) FROM instances").fetchone()[0]
                    >= MAX_INSTANCES
                ):
                    raise InventoryError("Inventory exceeds its instance bound.")
                collision = connection.execute(
                    "SELECT 1 FROM instances WHERE mount = ? OR image = ? LIMIT 1",
                    (instance.image, instance.mount),
                ).fetchone()
                if collision:
                    raise InventoryError("Instance or allocation is already registered.")
                columns = ", ".join(values)
                placeholders = ", ".join("?" for _ in values)
                connection.execute(
                    f"INSERT INTO instances ({columns}) VALUES ({placeholders})",
                    tuple(values.values()),
                )
                self._audit(
                    connection, "instance_adopted", instance.instance_id, instance.baseline_digest
                )
        except sqlite3.IntegrityError as error:
            raise InventoryError("Instance or allocation is already registered.") from error

    def get(self, key):
        matches = [item for item in self.list() if item.key == key]
        if len(matches) != 1:
            raise InventoryError("Instance is not registered.")
        return matches[0]

    def record_access_cutover(self, before, after, operation_id):
        """Source-owned inventory update after an exact fenced access receipt.

        Allocation identities stay fixed; only this explicit workflow may
        replace the assigned email. The operation retains both configurations.
        """
        before.validate()
        after.validate()
        allowed = {"email", "config_digest", "baseline_digest", "revision"}
        if after.revision != before.revision + 1 or any(
            getattr(before, field) != getattr(after, field)
            for field in vars(before)
            if field not in allowed
        ):
            raise InventoryError("Access cutover cannot change an allocation.")
        with self.connection(writable=True) as connection:
            current = connection.execute(
                "SELECT * FROM instances WHERE key=?", (before.key,)
            ).fetchone()
            if current is None:
                raise InventoryError("Instance is not registered.")
            actual = {field: current[field] for field in vars(before)}
            prior = connection.execute(
                "SELECT digest FROM inventory_audit WHERE action='access_cutover' AND reference=?",
                (operation_id,),
            ).fetchone()
            desired = digest_json(asdict(after))
            if prior:
                if prior[0] != desired or actual != asdict(after):
                    raise InventoryError("Access cutover identity changed.")
                return
            if actual != asdict(before):
                raise InventoryError("Inventory changed during access cutover.")
            connection.execute(
                "UPDATE instances SET email=?,config_digest=?,baseline_digest=?,revision=? "
                "WHERE key=?",
                (
                    after.email,
                    after.config_digest,
                    after.baseline_digest,
                    after.revision,
                    after.key,
                ),
            )
            self._audit(connection, "access_cutover", operation_id, desired)

    @staticmethod
    def _audit(connection, action, reference, digest):
        connection.execute(
            "INSERT INTO inventory_audit (action, reference, digest, recorded_at) "
            "VALUES (?, ?, ?, ?)",
            (action, reference, digest, datetime.now(UTC).isoformat()),
        )

    def begin_maintenance(self, kind, action, before_digest, request=None):
        request = request or MaintenanceRequest()
        key, release, resume, incident = (
            request.key,
            request.release,
            request.resume,
            request.incident,
        )
        if action not in MAINTENANCE_ACTIONS.get(kind, set()):
            raise InventoryError("Unknown maintenance action.")
        if (kind == "reconciliation") != (incident is not None):
            raise InventoryError("Root reconciliation requires a private incident reference.")
        with self.connection(writable=True) as connection:
            unfinished = connection.execute(
                "SELECT * FROM maintenance WHERE state != 'reconciled'"
            ).fetchone()
            if unfinished:
                resumable = {
                    "deploy": {"deploy", "resume", "rollback"},
                    "reset-demo": {"reset-demo", "resume-reset", "rollback-reset"},
                }.get(unfinished["action"], {unfinished["action"]})
                if (
                    resume != unfinished["id"]
                    or kind != unfinished["kind"]
                    or action not in resumable
                ):
                    raise InventoryError(
                        "Unfinished maintenance requires explicit resume or reconciliation."
                    )
                intent = json.loads(unfinished["intent_json"])
                if (key is not None and key != intent["key"]) or (
                    release is not None and release != intent["release"]
                ):
                    raise InventoryError("Resume must retain the original instance and release.")
                self._check_sources(connection, intent)
                connection.execute(
                    "UPDATE maintenance SET state = 'running', finished_at = NULL, "
                    "exit_code = NULL WHERE id = ?",
                    (resume,),
                )
                self._audit(connection, "maintenance_resumed", resume, before_digest)
                return resume
            if resume:
                raise InventoryError("Maintenance operation cannot be resumed.")
            if action in {"resume", "rollback", "resume-reset", "rollback-reset"}:
                raise InventoryError("This action requires the original maintenance ID.")
            identifier = str(uuid4())
            intent = self._new_intent(connection, kind, action, identifier, request)
            connection.execute(
                "INSERT INTO maintenance "
                "(id, kind, action, state, started_at, before_digest, "
                "incident_reference, intent_json) "
                "VALUES (?, ?, ?, 'running', ?, ?, ?, ?)",
                (
                    identifier,
                    kind,
                    action,
                    datetime.now(UTC).isoformat(),
                    before_digest,
                    incident,
                    json.dumps(intent, sort_keys=True, separators=(",", ":")),
                ),
            )
            self._audit(connection, "maintenance_started", identifier, before_digest)
            return identifier

    def reserve_upgrade(self, identifier, before, release):
        """Own private maintenance durably before pausing access.

        The caller holds the brief shared host lock. The database transaction
        makes replay/admission atomic; no lock is held over deployment work.
        This is not a generic wizard action and cannot be resumed by its CLI.
        """
        before.validate()
        if str(UUID(identifier)) != identifier:
            raise InventoryError("Invalid upgrade operation identity.")
        request = MaintenanceRequest(key=before.key, release=release)
        desired = digest_json(asdict(before))
        with self.connection(writable=True) as connection:
            prior = connection.execute(
                "SELECT * FROM maintenance WHERE id=?", (identifier,)
            ).fetchone()
            if prior:
                intent = json.loads(prior["intent_json"])
                retained = intent.get("sources", {}).get(before.key, {})
                if (
                    prior["kind"] != "release"
                    or prior["action"] != "admin-upgrade"
                    or prior["before_digest"] != desired
                    or intent.get("release") != release
                    or intent.get("key") != before.key
                    or {field: retained.get(field) for field in asdict(before)} != asdict(before)
                ):
                    raise InventoryError("Upgrade reservation identity changed.")
                return identifier
            if connection.execute("SELECT 1 FROM maintenance WHERE state!='reconciled'").fetchone():
                raise InventoryError("Unfinished maintenance blocks this upgrade.")
            intent = self._new_intent(connection, "release", "admin-upgrade", identifier, request)
            retained = intent["sources"][before.key]
            if {field: retained[field] for field in asdict(before)} != asdict(before):
                raise InventoryError("Inventory changed before upgrade reservation.")
            connection.execute(
                "INSERT INTO maintenance "
                "(id,kind,action,state,started_at,before_digest,intent_json) "
                "VALUES (?, 'release','admin-upgrade','running',?,?,?)",
                (
                    identifier,
                    datetime.now(UTC).isoformat(),
                    desired,
                    json.dumps(intent, sort_keys=True, separators=(",", ":")),
                ),
            )
            self._audit(connection, "upgrade_reserved", identifier, desired)
        return identifier

    def upgrade_releases(self):
        """Protect both installed artifacts, including after a crash or rollback.

        Completed upgrade history is retained until an explicit retention policy
        can retire its recovery chain; ordinary cleanup cannot infer that proof.
        """
        with self.connection() as connection:
            releases = set()
            for row in connection.execute(
                "SELECT intent_json FROM maintenance WHERE action='admin-upgrade'"
            ):
                intent = json.loads(row[0])
                original = intent["sources"][intent["key"]]["release"]
                for release in (original, intent["release"]):
                    if not isinstance(release, str) or not re.fullmatch(
                        r"release-[0-9]{8}-[0-9]{2,}", release
                    ):
                        raise InventoryError("Retained upgrade release identity is invalid.")
                    releases.add(release)
            return sorted(releases)

    @staticmethod
    def _new_intent(connection, kind, action, identifier, request):
        key, release = request.key, request.release
        if (kind == "release" and not key) or (
            kind != "reconciliation" and action != "backup" and not release
        ):
            raise InventoryError("Select the instance and intended release before maintenance.")
        sources = {
            row["key"]: dict(row)
            for row in connection.execute("SELECT * FROM instances ORDER BY key")
        }
        if key is not None and key not in sources:
            raise InventoryError("Instance is not registered.")
        if release is not None and not re.fullmatch(r"release-[0-9]{8}-[0-9]{2,}", release):
            raise InventoryError("Invalid intended release.")
        if action == "backup" and key is not None:
            if release is not None and release != sources[key]["release"]:
                raise InventoryError("Backup must use the registered source release.")
            release = sources[key]["release"]
        scope = "host" if kind != "release" or action == "install" else "instance"
        return {
            "scope": scope,
            "key": key,
            "release": release,
            "sources": sources,
            "checkpoint": (
                f"/opt/epm/releases/{release}/wizard-state/{key}.{UUID(identifier).hex}"
                if key is not None and release is not None
                else None
            ),
        }

    @staticmethod
    def _check_sources(connection, intent):
        current = {
            row["key"]: dict(row)
            for row in connection.execute("SELECT * FROM instances ORDER BY key")
        }
        if current != intent["sources"]:
            raise InventoryError("Registered source revisions changed during maintenance.")

    def maintenance_intent(self, identifier):
        return json.loads(self.maintenance(identifier)["intent_json"])

    def finish_maintenance(self, identifier, exit_code):
        with self.connection(writable=True) as connection:
            changed = connection.execute(
                "UPDATE maintenance SET state = 'needs_reconciliation', exit_code = ?, "
                "finished_at = ? WHERE id = ? AND state = 'running'",
                (exit_code, datetime.now(UTC).isoformat(), identifier),
            ).rowcount
            if changed != 1:
                raise InventoryError("Maintenance operation is not running.")
            self._audit(
                connection,
                "maintenance_observed_exit",
                identifier,
                digest_json({"exit_code": exit_code}),
            )

    def maintenance(self, identifier):
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM maintenance WHERE id = ?", (identifier,)
            ).fetchone()
        if row is None:
            raise InventoryError("Maintenance operation was not found.")
        return dict(row)

    def maintenance_history(self):
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM maintenance ORDER BY started_at DESC, id DESC LIMIT 20"
            ).fetchall()
        return [dict(row) for row in rows]

    def reconcile(self, identifier, replacements, observed_digest):
        for old, new in replacements:
            old.validate()
            new.validate()
            if (
                any(
                    getattr(old, field) != getattr(new, field)
                    for field in IMMUTABLE_ALLOCATION_FIELDS
                )
                or new.revision != old.revision + 1
            ):
                raise InventoryError("Reconciliation cannot replace allocation identities.")
        with self.connection(writable=True) as connection:
            operation = connection.execute(
                "SELECT * FROM maintenance WHERE id = ?", (identifier,)
            ).fetchone()
            if operation is None or operation["state"] != "needs_reconciliation":
                raise InventoryError("Maintenance must finish before reconciliation.")
            intent = json.loads(operation["intent_json"])
            self._check_sources(connection, intent)
            for old, new in replacements:
                source = intent["sources"].get(old.key, {})
                if any(source.get(field) != value for field, value in asdict(old).items()):
                    raise InventoryError("Inventory changed during reconciliation.")
                if operation["kind"] != "reconciliation":
                    if (
                        operation["action"] not in {"deploy", "reset-demo", "admin-upgrade"}
                        or old.key != intent["key"]
                    ):
                        raise InventoryError("Changes are outside the maintenance target.")
                    if new.release not in {old.release, intent["release"]}:
                        raise InventoryError("Observed release differs from maintenance intent.")
                fields = asdict(new)
                assignments = ", ".join(f"{name} = ?" for name in fields)
                changed = connection.execute(
                    f"UPDATE instances SET {assignments} "
                    "WHERE key = ? AND revision = ? AND config_digest = ?",
                    (*fields.values(), old.key, old.revision, old.config_digest),
                ).rowcount
                if changed != 1:
                    raise InventoryError("Inventory changed during reconciliation.")
            connection.execute(
                "UPDATE maintenance SET state = 'reconciled', after_digest = ? WHERE id = ?",
                (observed_digest, identifier),
            )
            self._audit(connection, "maintenance_reconciled", identifier, observed_digest)


def digest_json(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def new_identity():
    """Issue opaque, independent instance and allocation IDs."""
    return str(uuid4()), str(uuid4())


def discrepancies(registered: Instance, observed: Instance):
    """Return exact changed fields without silently adopting an observed change."""
    registered.validate()
    observed.validate()
    return tuple(key for key, value in vars(registered).items() if value != vars(observed)[key])

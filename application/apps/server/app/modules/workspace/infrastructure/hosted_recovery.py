"""Internal workspace backup runner, change detection, retention, and alerting (H05.3)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import threading
from typing import Literal
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import Engine, text

from app.modules.hosted_access.application.source_contracts import (
    Drain,
    MaintenanceFence,
    SourceCommand,
    VerifyRestoreBinding,
)
from app.modules.hosted_admin.infrastructure.recovery_status_ingest import (
    WorkspaceProtectionSummary,
    sign_protection_summary,
)
from app.modules.hosted_recovery.domain.models import (
    EnvelopeContext,
    HostedRecoveryError,
    RecoveryIntegrityError,
    canonical_json_bytes,
    validate_kms_key_ref,
    validate_relative_file_path,
)
from app.modules.hosted_recovery.infrastructure.alerting import (
    DeduplicatingAlertEmitter,
    RecoveryAlert,
)
from app.modules.hosted_recovery.infrastructure.engine import (
    ChunkedAeadBackupEngine,
    DatabaseInput,
    RetainedFileInput,
)
from app.modules.workspace.application.recovery_contracts import (
    Capture,
    ConfirmRestore,
    PreviewRestore,
    ReconcileCheckpoint,
    ReconstructCatalog,
    WorkspaceRecoveryCommand,
    WorkspaceRecoveryObservation,
    WorkspaceRecoveryResult,
    require_invocation,
)
from app.platform.hosted_contracts.authority import (
    LocalRestoreAuthority,
    ObservationPage,
    ObservationQuery,
    OperatorAuthority,
    OperatorRestoreAuthority,
    ServiceAuthority,
)
from app.platform.hosted_contracts.operations import (
    CommandIntent,
    OperationOutcome,
    OperationReference,
    OperationState,
    SemanticConflict,
)
from app.platform.hosted_contracts.reads import Freshness, FreshnessState
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.ui_states import Protection, Section
from app.platform.hosted_contracts.values import WorkspaceScope
from app.platform.sqlite_engine import immediate_transaction

logger = logging.getLogger("epm.workspace.hosted_recovery")

OVERDUE_THRESHOLD_MS = 28 * 60 * 60 * 1000  # 28 hours (D10)
DEFAULT_RETENTION_POINTS = 7
DEFAULT_RETENTION_WINDOW_MS = 7 * 24 * 60 * 60 * 1000
SUMMARY_TTL_MS = 5 * 60 * 1000
PREVIEW_TTL_MS = 10 * 60 * 1000  # 10 minutes (D4)
STEP_UP_TTL_MS = 10 * 60 * 1000  # 10 minutes (D4)
EXECUTION_AUTH_TTL_MS = 5 * 60 * 1000  # 5 minutes (D4)


class WorkspaceStateUnreadable(HostedRecoveryError):
    code = "business_state_unreadable"


class RestoreDeniedError(HostedRecoveryError):
    code = "restore_denied"


class RestoreNotFoundError(HostedRecoveryError):
    code = "restore_point_not_found"


class BackupConflictError(SemanticConflict):
    """Raised when a concurrent backup or recovery operation is already running."""


def kms_ref_to_db_ref(kms_key_ref: str) -> str:
    """Convert a Cloud KMS resource path ('/') into a hosted_ddl REF-safe token (':')."""
    validated = validate_kms_key_ref(kms_key_ref)
    return "kms:" + validated.replace("/", ":")


def db_ref_to_kms_ref(db_ref: str) -> str:
    """Convert a hosted_ddl REF token ('kms:...') back to a Cloud KMS resource path."""
    if not db_ref.startswith("kms:"):
        raise ValueError("Database encryption_key_ref must start with 'kms:'.")
    return validate_kms_key_ref(db_ref[4:].replace(":", "/"))


def manifest_ref_for_point(point_id: str) -> str:
    return f"manifest:{point_id}"


def object_key_for_manifest_ref(manifest_ref: str) -> str:
    if not manifest_ref.startswith("manifest:"):
        raise ValueError("Invalid manifest_ref format.")
    point_id = manifest_ref[len("manifest:") :]
    return f"manifests/{point_id}.json.enc"


@dataclass(frozen=True)
class LiveWorkspaceFingerprint:
    business_revision: str
    files_generation: str
    file_entries: tuple[tuple[str, str, int], ...]  # (local_relative_path, content_sha256, size)


@dataclass(frozen=True)
class ProtectionSnapshot:
    protection_state: Literal["healthy", "unchanged", "overdue", "unavailable", "unknown"]
    last_point_id: str | None
    last_captured_at: int | None
    last_verified_at: int | None
    last_checked_at: int | None
    dirty_since: int | None
    consecutive_failures: int
    last_error_code: str | None
    revision: int


@dataclass(frozen=True)
class StartupMode:
    mode: Literal["normal", "recovery"]
    reason: str | None
    active_business_ref: str
    interrupted_restore_id: str | None = None
    pending_acceptance_id: str | None = None


@dataclass(frozen=True)
class RestorePreview:
    preview_id: str
    point_id: str
    workspace_id: str
    source_epoch: int
    source_generation: int
    current_business_revision: str | None
    selected_captured_at: int
    selected_verified_at: int
    exact_request_hash: str
    created_at: int
    expires_at: int
    recovery_mode: bool


@dataclass(frozen=True)
class RestoreStatusDetail:
    operation_id: str
    point_id: str
    preview_id: str
    phase: str
    state: str
    prior_business_ref: str
    prior_tree_kind: str
    target_business_ref: str
    new_source_generation: int
    new_access_epoch: int | None
    started_at: int
    updated_at: int
    accepted_at: int | None
    error_code: str | None


@dataclass(frozen=True)
class ReconstructResult:
    scanned_manifests: int
    imported_points: list[str]
    skipped_points: list[str]


def compute_restore_request_hash(
    *,
    workspace_id: str,
    point_id: str,
    source_epoch: int,
    preview_id: str,
) -> str:
    """Deterministic SHA-256 request_hash binding exact restore preview parameters (D4)."""
    raw = canonical_json_bytes(
        {
            "action": "confirm_restore",
            "workspace_id": workspace_id,
            "point_id": point_id,
            "source_epoch": source_epoch,
            "preview_id": preview_id,
        }
    )
    return hashlib.sha256(raw).hexdigest()


def _open_readonly_sqlite(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file() or db_path.is_symlink():
        raise WorkspaceStateUnreadable("Business database file is missing or unsafe.")
    try:
        conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=5.0)
        conn.execute("PRAGMA query_only=ON")
        check = conn.execute("PRAGMA quick_check(1)").fetchone()
        if not check or check[0] != "ok":
            conn.close()
            raise WorkspaceStateUnreadable("Business database failed quick_check.")
        return conn
    except WorkspaceStateUnreadable:
        raise
    except sqlite3.Error as error:
        raise WorkspaceStateUnreadable("Business database cannot be opened.") from error


def _fingerprint_database(conn: sqlite3.Connection) -> str:
    """Compute a persistent, backup-invariant content fingerprint of the SQLite database."""
    hasher = hashlib.sha256()
    user_version = conn.execute("PRAGMA main.user_version").fetchone()[0]
    hasher.update(f"user_version={user_version}\n".encode("ascii"))
    for obj_type, name, ddl in conn.execute(
        "SELECT type, name, COALESCE(sql, '') FROM main.sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall():
        hasher.update(f"DDL:{obj_type}:{name}:{ddl}\n".encode("utf-8"))
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM main.sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        columns = [col[1] for col in conn.execute(f"PRAGMA main.table_info({quoted})").fetchall()]
        order_cols = ", ".join('"' + c.replace('"', '""') + '"' for c in columns)
        hasher.update(f"TABLE:{table}\n".encode("utf-8"))
        for row in conn.execute(f"SELECT {order_cols} FROM main.{quoted} ORDER BY {order_cols}"):
            hasher.update(
                json.dumps(list(row), separators=(",", ":"), default=str).encode("utf-8") + b"\n"
            )
    return f"biz:{hasher.hexdigest()[:48]}"


def _read_retained_files(
    conn: sqlite3.Connection,
    workspace_dir: Path,
) -> tuple[str, tuple[tuple[str, str, int], ...]]:
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM main.sqlite_master "
            "WHERE type='table' AND name IN ('file_records', 'file_content_locations')"
        ).fetchall()
    }
    if tables != {"file_records", "file_content_locations"}:
        empty_hash = hashlib.sha256(b"no-files").hexdigest()[:48]
        return f"files:{empty_hash}", ()

    rows = conn.execute(
        "SELECT fcl.local_relative_path, fr.content_sha256, fr.size_bytes "
        "FROM main.file_records fr "
        "JOIN main.file_content_locations fcl ON fcl.file_id = fr.id "
        "WHERE fcl.storage_provider = 'local' AND fcl.storage_state = 'available' "
        "ORDER BY fcl.local_relative_path, fr.content_sha256"
    ).fetchall()

    resolved_root = workspace_dir.resolve()
    hasher = hashlib.sha256()
    seen_paths: dict[str, tuple[str, int]] = {}
    for rel_path, content_sha, size_bytes in rows:
        if not isinstance(rel_path, str):
            raise WorkspaceStateUnreadable("Invalid retained file path in database.")
        validated = validate_relative_file_path(rel_path)
        full_path = (resolved_root / validated).resolve()
        try:
            full_path.relative_to(resolved_root)
        except ValueError as error:
            raise WorkspaceStateUnreadable("Retained file path escapes workspace.") from error
        if full_path.is_symlink() or not full_path.is_file():
            raise WorkspaceStateUnreadable("Retained file is missing on disk.")
        stat_info = full_path.stat()
        if stat_info.st_size != int(size_bytes):
            raise WorkspaceStateUnreadable("Retained file size does not match database metadata.")
        actual_sha = hashlib.sha256(full_path.read_bytes()).hexdigest()
        if actual_sha != content_sha:
            raise WorkspaceStateUnreadable("Retained file content does not match database digest.")
        seen_paths[validated] = (actual_sha, stat_info.st_size)
        hasher.update(f"{validated}:{actual_sha}:{stat_info.st_size}\n".encode("utf-8"))

    entries = tuple((path, sha, sz) for path, (sha, sz) in sorted(seen_paths.items()))
    return f"files:{hasher.hexdigest()[:48]}", entries


def probe_live_workspace_state(
    business_db_path: Path,
    workspace_dir: Path,
) -> LiveWorkspaceFingerprint:
    """Read consistent business_revision and files_generation from the active workspace."""
    conn = _open_readonly_sqlite(business_db_path)
    try:
        conn.execute("BEGIN DEFERRED")
        business_rev = _fingerprint_database(conn)
        files_gen, entries = _read_retained_files(conn, workspace_dir)
        return LiveWorkspaceFingerprint(
            business_revision=business_rev,
            files_generation=files_gen,
            file_entries=entries,
        )
    except WorkspaceStateUnreadable:
        raise
    except (sqlite3.Error, OSError, ValueError) as error:
        raise WorkspaceStateUnreadable("Failed to inspect live workspace state.") from error
    finally:
        conn.close()


def stage_consistent_snapshot(
    *,
    business_db_path: Path,
    workspace_dir: Path,
    staging_dir: Path,
) -> tuple[DatabaseInput, list[RetainedFileInput], LiveWorkspaceFingerprint]:
    """Use SQLite Online Backup API + consistent file staging without holding locks during upload."""
    staging_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    staged_db = staging_dir / "property-management.sqlite"
    src_conn = _open_readonly_sqlite(business_db_path)
    try:
        dst_conn = sqlite3.connect(staged_db)
        try:
            src_conn.backup(dst_conn)
            dst_conn.commit()
        finally:
            dst_conn.close()
    finally:
        src_conn.close()

    # Compute exact fingerprint and file list from the staged consistent snapshot.
    snap_conn = _open_readonly_sqlite(staged_db)
    try:
        business_rev = _fingerprint_database(snap_conn)
        files_gen, entries = _read_retained_files(snap_conn, workspace_dir)
    finally:
        snap_conn.close()

    staged_files: list[RetainedFileInput] = []
    files_stage_root = staging_dir / "files"
    resolved_workspace = workspace_dir.resolve()
    for rel_path, _, _ in entries:
        src_file = (resolved_workspace / rel_path).resolve()
        dst_file = files_stage_root / rel_path
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_file, dst_file)
        staged_files.append(RetainedFileInput(relative_path=rel_path, path=dst_file))

    fingerprint = LiveWorkspaceFingerprint(
        business_revision=business_rev,
        files_generation=files_gen,
        file_entries=entries,
    )
    return DatabaseInput("property-management.sqlite", staged_db), staged_files, fingerprint


class HostedWorkspaceRecoveryService:
    """Internal per-operator workspace backup runner implementing WorkspaceRecoveryPort (H05.3)."""

    def __init__(
        self,
        *,
        recovery_engine: Engine,
        access_engine: Engine,
        backup_engine: ChunkedAeadBackupEngine,
        operator_id: str,
        workspace_id: str,
        deployment_id: str,
        workspace_root: Path,
        scratch_root: Path,
        release_ref: str,
        business_schema_revision: str,
        access_schema_revision: str,
        clock: Callable[[], int],
        alert_emitter: DeduplicatingAlertEmitter | None = None,
        summary_signer_key: Ed25519PrivateKey | None = None,
        summary_key_id: str = "op-summary-v1",
        summary_publisher: Callable[[str], None] | None = None,
        retention_points: int = DEFAULT_RETENTION_POINTS,
        retention_window_ms: int = DEFAULT_RETENTION_WINDOW_MS,
        overdue_threshold_ms: int = OVERDUE_THRESHOLD_MS,
        source_lifecycle=None,
        close_business_connections: Callable[[], None] | None = None,
    ):
        self.recovery_engine = recovery_engine
        self.access_engine = access_engine
        self.backup_engine = backup_engine
        self.operator_id = operator_id
        self.workspace_id = workspace_id
        self.deployment_id = deployment_id
        self.workspace_root = workspace_root
        self.scratch_root = scratch_root
        self.release_ref = release_ref
        self.business_schema_revision = business_schema_revision
        self.access_schema_revision = access_schema_revision
        self.clock = clock
        self.alert_emitter = alert_emitter
        self.summary_signer_key = summary_signer_key
        self.summary_key_id = summary_key_id
        self.summary_publisher = summary_publisher
        self.retention_points = max(1, retention_points)
        self.retention_window_ms = retention_window_ms
        self.overdue_threshold_ms = overdue_threshold_ms
        self.source_lifecycle = source_lifecycle
        self.close_business_connections = close_business_connections
        self._op_lock = threading.Lock()
        self._last_wrapped_dek_b64: str | None = None
        self._last_wrapped_key_ref: str | None = None
        self._previews: dict[str, RestorePreview] = {}
        self._consumed_previews: set[str] = set()

    def _active_business_paths(self, conn) -> tuple[Path, Path, int, str]:
        meta = (
            conn.execute(
                text(
                    "SELECT active_business_ref, source_generation, encryption_key_ref "
                    "FROM recovery_meta WHERE id = 1"
                )
            )
            .mappings()
            .one()
        )
        active_ref = str(meta["active_business_ref"])
        incarnation_dir = (self.workspace_root / active_ref).resolve()
        try:
            incarnation_dir.relative_to(self.workspace_root.resolve())
        except ValueError as error:
            raise WorkspaceStateUnreadable("active_business_ref escapes workspace root.") from error
        db_path = incarnation_dir / "property-management.sqlite"
        kms_key_ref = db_ref_to_kms_ref(str(meta["encryption_key_ref"]))
        return incarnation_dir, db_path, int(meta["source_generation"]), kms_key_ref

    def _current_access_epoch(self) -> int:
        with self.access_engine.connect() as conn:
            row = (
                conn.execute(text("SELECT access_epoch FROM access_meta WHERE id = 1"))
                .mappings()
                .one()
            )
            return int(row["access_epoch"])

    def _record_audit(
        self,
        conn,
        *,
        operation_id: str | None,
        actor_ref: str,
        action: str,
        now: int,
        facts: dict[str, object],
    ) -> None:
        conn.execute(
            text(
                "INSERT INTO recovery_audit "
                "(audit_id, operation_id, actor_ref, action, recorded_at, safe_facts_json) "
                "VALUES (:audit_id, :operation_id, :actor_ref, :action, :recorded_at, :facts)"
            ),
            {
                "audit_id": str(uuid4()),
                "operation_id": operation_id,
                "actor_ref": actor_ref,
                "action": action,
                "recorded_at": now,
                "facts": json.dumps(facts, sort_keys=True, separators=(",", ":")),
            },
        )

    def read_protection_status(self) -> ProtectionSnapshot:
        """Read current protection state directly from recovery.sqlite (zero Admin dependency)."""
        with self.recovery_engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT bs.protection_state, bs.last_point_id, bs.last_checked_at, "
                        "bs.dirty_since, bs.consecutive_failures, bs.last_error_code, bs.revision, "
                        "rp.captured_at, rp.verified_at "
                        "FROM backup_state bs "
                        "LEFT JOIN recovery_points rp ON rp.point_id = bs.last_point_id "
                        "WHERE bs.id = 1"
                    )
                )
                .mappings()
                .one()
            )
        return ProtectionSnapshot(
            protection_state=row["protection_state"],
            last_point_id=row["last_point_id"],
            last_captured_at=row["captured_at"],
            last_verified_at=row["verified_at"],
            last_checked_at=row["last_checked_at"],
            dirty_since=row["dirty_since"],
            consecutive_failures=int(row["consecutive_failures"]),
            last_error_code=row["last_error_code"],
            revision=int(row["revision"]),
        )

    def build_signed_summary(self) -> str | None:
        """Build an Ed25519-signed WorkspaceProtectionSummary from recovery.sqlite + access_meta."""
        if self.summary_signer_key is None:
            return None
        now = self.clock()
        snap = self.read_protection_status()
        source_epoch = self._current_access_epoch()
        checked_at = snap.last_checked_at if snap.last_checked_at is not None else now
        latest_point_ref = (
            manifest_ref_for_point(snap.last_point_id) if snap.last_point_id is not None else None
        )
        summary = WorkspaceProtectionSummary(
            operator_id=self.operator_id,
            workspace_id=self.workspace_id,
            source_epoch=source_epoch,
            source_revision=snap.revision,
            latest_point_ref=latest_point_ref,
            captured_at=snap.last_captured_at,
            verified_at=snap.last_verified_at,
            checked_at=checked_at,
            dirty_since=snap.dirty_since,
            protection_state=snap.protection_state,
            active_operation_ref=None,
            key_id=self.summary_key_id,
            issued_at=now,
            expires_at=now + SUMMARY_TTL_MS,
        )
        return sign_protection_summary(summary, private_key=self.summary_signer_key)

    def _publish_summary_best_effort(self) -> None:
        if self.summary_publisher is None or self.summary_signer_key is None:
            return
        try:
            token = self.build_signed_summary()
            if token is not None:
                self.summary_publisher(token)
        except Exception:
            logger.warning(
                "Async workspace protection summary push failed (Admin outage tolerant)."
            )

    def _emit_incident(
        self,
        *,
        alert_kind: Literal["backup_failed", "backup_overdue", "backup_unknown"],
        snap: ProtectionSnapshot,
        now: int,
    ) -> None:
        if self.alert_emitter is None:
            return
        self.alert_emitter.notify_incident(
            RecoveryAlert(
                deployment_id=self.deployment_id,
                operator_id=self.operator_id,
                workspace_id=self.workspace_id,
                alert_kind=alert_kind,
                protection_state=snap.protection_state,
                recorded_at=now,
                consecutive_failures=snap.consecutive_failures,
                last_error_code=snap.last_error_code,
                last_verified_at=snap.last_verified_at,
                dirty_since=snap.dirty_since,
            )
        )

    def _emit_recovered(self, *, snap: ProtectionSnapshot, now: int) -> None:
        if self.alert_emitter is None:
            return
        if snap.protection_state in {"healthy", "unchanged"}:
            self.alert_emitter.notify_recovered(
                deployment_id=self.deployment_id,
                operator_id=self.operator_id,
                workspace_id=self.workspace_id,
                protection_state=snap.protection_state,
                recorded_at=now,
                last_verified_at=snap.last_verified_at,
            )

    def evaluate_freshness(self) -> ProtectionSnapshot:
        """Check whether dirty unprotected data has crossed the 28-hour overdue threshold."""
        now = self.clock()
        transitioned_overdue = False
        with immediate_transaction(self.recovery_engine) as conn:
            bs = conn.execute(text("SELECT * FROM backup_state WHERE id = 1")).mappings().one()
            dirty_since = bs["dirty_since"]
            state = bs["protection_state"]
            if (
                dirty_since is not None
                and now - int(dirty_since) >= self.overdue_threshold_ms
                and state != "overdue"
            ):
                conn.execute(
                    text(
                        "UPDATE backup_state SET "
                        "protection_state = 'overdue', last_checked_at = :now, "
                        "revision = revision + 1 WHERE id = 1"
                    ),
                    {"now": now},
                )
                self._record_audit(
                    conn,
                    operation_id=None,
                    actor_ref="service:operator_backup",
                    action="backup_overdue",
                    now=now,
                    facts={
                        "dirty_since": int(dirty_since),
                        "threshold_ms": self.overdue_threshold_ms,
                    },
                )
                transitioned_overdue = True
        snap = self.read_protection_status()
        if transitioned_overdue:
            self._emit_incident(alert_kind="backup_overdue", snap=snap, now=now)
            self._publish_summary_best_effort()
        return snap

    def _release_maintenance_fence(self, op_id: str) -> None:
        """Clear access_meta.maintenance_operation_id when still held by op_id (#11)."""
        with immediate_transaction(self.access_engine) as conn:
            conn.execute(
                text(
                    "UPDATE access_meta SET maintenance_operation_id = NULL, "
                    "revision = revision + 1 "
                    "WHERE id = 1 AND maintenance_operation_id = :op_id"
                ),
                {"op_id": op_id},
            )

    def reconcile_startup(self) -> ProtectionSnapshot:
        """Reconcile interrupted backup operations, stale fences, and post-crash drift."""
        now = self.clock()
        alert_kind: Literal["backup_overdue", "backup_unknown"] | None = None

        # Probe live workspace state and check stale fences OUTSIDE any write lock (#11, #15).
        with self.recovery_engine.connect() as conn:
            incarnation_dir, db_path, source_gen, _ = self._active_business_paths(conn)
            stale_restore_ops = set(
                conn.execute(
                    text(
                        "SELECT operation_id FROM restore_operations "
                        "WHERE phase = 'needs_attention'"
                    )
                )
                .scalars()
                .all()
            )
        with self.access_engine.connect() as aconn:
            held_op = aconn.execute(
                text("SELECT maintenance_operation_id FROM access_meta WHERE id = 1")
            ).scalar_one_or_none()
        if held_op is not None and str(held_op) in stale_restore_ops:
            self._release_maintenance_fence(str(held_op))

        live = None
        try:
            live = probe_live_workspace_state(db_path, incarnation_dir)
        except WorkspaceStateUnreadable:
            live = None

        with immediate_transaction(self.recovery_engine) as conn:
            # 1. Reconcile any interrupted backup operations left in pending/running.
            interrupted = (
                conn.execute(
                    text(
                        "SELECT operation_id FROM recovery_operations "
                        "WHERE kind = 'backup' AND state IN ('pending', 'running')"
                    )
                )
                .scalars()
                .all()
            )
            for op_id in interrupted:
                point_row = (
                    conn.execute(
                        text("SELECT point_id FROM recovery_points WHERE operation_id = :op_id"),
                        {"op_id": op_id},
                    )
                    .mappings()
                    .first()
                )
                if point_row is not None:
                    result_obj = WorkspaceRecoveryResult(
                        point_id=point_row["point_id"],
                        phase="captured",
                        receipt_ref=f"op:{op_id}",
                    )
                    conn.execute(
                        text(
                            "UPDATE recovery_operations SET state = 'succeeded', "
                            "result_json = :res, error_code = NULL, updated_at = :now, "
                            "revision = revision + 1 WHERE operation_id = :op_id"
                        ),
                        {"res": result_obj.model_dump_json(), "now": now, "op_id": op_id},
                    )
                else:
                    conn.execute(
                        text(
                            "UPDATE recovery_operations SET state = 'unknown', "
                            "error_code = 'interrupted_on_crash', updated_at = :now, "
                            "revision = revision + 1 WHERE operation_id = :op_id"
                        ),
                        {"now": now, "op_id": op_id},
                    )

            # 2. Compare live business state against backup_state protected tuple.
            bs = conn.execute(text("SELECT * FROM backup_state WHERE id = 1")).mappings().one()
            if live is None:
                conn.execute(
                    text(
                        "UPDATE backup_state SET protection_state = 'unknown', "
                        "dirty_since = COALESCE(dirty_since, :now), last_checked_at = :now, "
                        "last_error_code = 'business_state_unreadable', revision = revision + 1 "
                        "WHERE id = 1"
                    ),
                    {"now": now},
                )
                self._record_audit(
                    conn,
                    operation_id=None,
                    actor_ref="service:operator_backup",
                    action="startup_reconcile_unknown",
                    now=now,
                    facts={"reason": "business_state_unreadable"},
                )
                alert_kind = "backup_unknown"
            else:
                matches_protected = (
                    bs["last_point_id"] is not None
                    and bs["protected_business_revision"] == live.business_revision
                    and bs["protected_files_generation"] == live.files_generation
                    and bs["protected_source_generation"] == source_gen
                )
                if not matches_protected:
                    # Committed changes exist that are not yet verified off-host.
                    new_state = "overdue" if bs["last_point_id"] is not None else "unavailable"
                    conn.execute(
                        text(
                            "UPDATE backup_state SET protection_state = :state, "
                            "dirty_since = COALESCE(dirty_since, :now), last_checked_at = :now, "
                            "last_error_code = 'unprotected_changes_after_restart', "
                            "revision = revision + 1 WHERE id = 1"
                        ),
                        {"state": new_state, "now": now},
                    )
                    self._record_audit(
                        conn,
                        operation_id=None,
                        actor_ref="service:operator_backup",
                        action="startup_reconcile_dirty",
                        now=now,
                        facts={
                            "business_revision": live.business_revision,
                            "files_generation": live.files_generation,
                            "protection_state": new_state,
                        },
                    )
                    if new_state == "overdue":
                        alert_kind = "backup_overdue"

        snap = self.read_protection_status()
        if alert_kind is not None:
            self._emit_incident(alert_kind=alert_kind, snap=snap, now=now)
        self._publish_summary_best_effort()
        return snap

    def execute(
        self,
        actor: OperatorAuthority | LocalRestoreAuthority | ServiceAuthority,
        command: WorkspaceRecoveryCommand,
    ) -> OperationOutcome[WorkspaceRecoveryResult]:
        require_invocation(actor, command)
        scope = command.intent.scope
        if (
            not isinstance(scope, WorkspaceScope)
            or scope.workspace_id != self.workspace_id
            or scope.operator_id != self.operator_id
        ):
            raise HostedRecoveryError("Command workspace scope does not match service workspace.")
        payload = command.intent.payload
        if isinstance(payload, Capture):
            return self._execute_capture(actor, command)
        if isinstance(payload, ReconcileCheckpoint):
            return self._execute_reconcile_checkpoint(actor, command)
        if isinstance(payload, PreviewRestore):
            preview = self.preview_restore(actor, point_id=payload.point_id)
            return OperationOutcome[WorkspaceRecoveryResult](
                operation=command.reference(),
                state=OperationState.SUCCEEDED,
                revision=1,
                observed_at=preview.created_at,
                result=WorkspaceRecoveryResult(
                    point_id=preview.point_id,
                    phase="preview",
                    receipt_ref=f"preview:{preview.preview_id}",
                ),
            )
        if isinstance(payload, ConfirmRestore):
            if not isinstance(actor, (OperatorRestoreAuthority, LocalRestoreAuthority)):
                raise RestoreDeniedError("ConfirmRestore requires strong step-up authority.")
            subject = (
                actor.identity_proof_ref
                if isinstance(actor, OperatorRestoreAuthority)
                else actor.os_owner_proof_ref
            )
            return self.confirm_restore(
                actor,
                point_id=payload.point_id,
                preview_id=payload.preview_id,
                idempotency_key=command.idempotency_key,
                authorized_subject=subject,
                operation_id=command.operation_id,
                command=command,
            )
        if isinstance(payload, ReconstructCatalog):
            reconstructed = self.reconstruct_catalog(actor)
            now = self.clock()
            point_id = (
                reconstructed.imported_points[0]
                if reconstructed.imported_points
                else (self.read_protection_status().last_point_id or str(uuid4()))
            )
            return OperationOutcome[WorkspaceRecoveryResult](
                operation=command.reference(),
                state=OperationState.SUCCEEDED,
                revision=1,
                observed_at=now,
                result=WorkspaceRecoveryResult(
                    point_id=point_id,
                    phase="reconciled",
                    receipt_ref=f"op:{command.operation_id}",
                ),
            )
        raise RestoreDeniedError("Unsupported recovery action.")

    def _outcome_from_row(self, row) -> OperationOutcome[WorkspaceRecoveryResult]:
        stored_cmd = WorkspaceRecoveryCommand.model_validate_json(row["request_json"])
        op_ref = OperationReference(
            deployment_id=stored_cmd.intent.deployment_id,
            scope=stored_cmd.intent.scope,
            kind=stored_cmd.intent.kind,
            operation_id=row["operation_id"],
            idempotency_key=stored_cmd.idempotency_key,
            request_hash=row["request_hash"],
        )
        state = OperationState(row["state"])
        result = (
            WorkspaceRecoveryResult.model_validate_json(row["result_json"])
            if row["result_json"] is not None
            else None
        )
        action_required = (
            "check_original_result"
            if state in {OperationState.UNKNOWN, OperationState.NEEDS_ATTENTION}
            else None
        )
        return OperationOutcome[WorkspaceRecoveryResult](
            operation=op_ref,
            state=state,
            revision=int(row["revision"]),
            observed_at=int(row["updated_at"]),
            result=result,
            error_code=row["error_code"],
            action_required=action_required,
        )

    def _lookup_idempotent(
        self, conn, *, kind: str, idempotency_key: str, request_hash: str
    ) -> OperationOutcome[WorkspaceRecoveryResult] | None:
        row = (
            conn.execute(
                text(
                    "SELECT operation_id, request_hash, request_json, state, result_json, "
                    "error_code, updated_at, revision "
                    "FROM recovery_operations "
                    "WHERE kind = :kind AND idempotency_key = :key"
                ),
                {"kind": kind, "key": idempotency_key},
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise SemanticConflict()
        return self._outcome_from_row(row)

    def _execute_reconcile_checkpoint(
        self,
        actor: ServiceAuthority,
        command: WorkspaceRecoveryCommand,
    ) -> OperationOutcome[WorkspaceRecoveryResult]:
        now = self.clock()
        self.reconcile_startup()
        with immediate_transaction(self.recovery_engine) as conn:
            existing = self._lookup_idempotent(
                conn,
                kind="backup",
                idempotency_key=command.idempotency_key,
                request_hash=command.request_hash,
            )
            if existing is not None:
                return existing
            op_id = command.operation_id
            bs = (
                conn.execute(text("SELECT last_point_id FROM backup_state WHERE id = 1"))
                .mappings()
                .one()
            )
            source_gen = int(
                conn.execute(
                    text("SELECT source_generation FROM recovery_meta WHERE id = 1")
                ).scalar_one()
            )
            point_id = bs["last_point_id"] or str(uuid4())
            result = WorkspaceRecoveryResult(
                point_id=point_id,
                phase="reconciled",
                receipt_ref=f"op:{op_id}",
            )
            conn.execute(
                text(
                    "INSERT INTO recovery_operations ("
                    "operation_id, kind, idempotency_key, request_hash, request_json, "
                    "actor_kind, actor_ref, state, source_generation, result_json, error_code, "
                    "created_at, updated_at, revision"
                    ") VALUES ("
                    ":op_id, 'backup', :key, :hash, :req_json, 'system', :actor_ref, 'succeeded', "
                    ":src_gen, :res_json, NULL, :now, :now, 1"
                    ")"
                ),
                {
                    "op_id": op_id,
                    "key": command.idempotency_key,
                    "hash": command.request_hash,
                    "req_json": command.model_dump_json(),
                    "actor_ref": f"service:{actor.service}",
                    "src_gen": source_gen,
                    "res_json": result.model_dump_json(),
                    "now": now,
                },
            )
            return OperationOutcome[WorkspaceRecoveryResult](
                operation=command.reference(),
                state=OperationState.SUCCEEDED,
                revision=1,
                observed_at=now,
                result=result,
            )

    def _execute_capture(
        self,
        actor: ServiceAuthority,
        command: WorkspaceRecoveryCommand,
    ) -> OperationOutcome[WorkspaceRecoveryResult]:
        if not self._op_lock.acquire(blocking=False):
            raise BackupConflictError()
        try:
            return self._run_capture_locked(actor, command)
        finally:
            self._op_lock.release()

    def _run_capture_locked(
        self,
        actor: ServiceAuthority,
        command: WorkspaceRecoveryCommand,
    ) -> OperationOutcome[WorkspaceRecoveryResult]:
        now = self.clock()
        # Phase 1: Idempotency check & admit running operation in recovery.sqlite.
        with immediate_transaction(self.recovery_engine) as conn:
            existing = self._lookup_idempotent(
                conn,
                kind="backup",
                idempotency_key=command.idempotency_key,
                request_hash=command.request_hash,
            )
            if existing is not None:
                return existing
            incarnation_dir, db_path, source_gen, kms_key_ref = self._active_business_paths(conn)
            bs = conn.execute(text("SELECT * FROM backup_state WHERE id = 1")).mappings().one()
            op_id = command.operation_id
            conn.execute(
                text(
                    "INSERT INTO recovery_operations ("
                    "operation_id, kind, idempotency_key, request_hash, request_json, "
                    "actor_kind, actor_ref, state, source_generation, result_json, error_code, "
                    "created_at, updated_at, revision"
                    ") VALUES ("
                    ":op_id, 'backup', :key, :hash, :req_json, 'system', :actor_ref, 'running', "
                    ":src_gen, NULL, NULL, :now, :now, 1"
                    ")"
                ),
                {
                    "op_id": op_id,
                    "key": command.idempotency_key,
                    "hash": command.request_hash,
                    "req_json": command.model_dump_json(),
                    "actor_ref": f"service:{actor.service}",
                    "src_gen": source_gen,
                    "now": now,
                },
            )
            last_point_id = bs["last_point_id"]
            protected_biz = bs["protected_business_revision"]
            protected_files = bs["protected_files_generation"]
            protected_src = bs["protected_source_generation"]
            last_point_verified = False
            if last_point_id is not None:
                pt_state = conn.execute(
                    text("SELECT state FROM recovery_points WHERE point_id = :pid"),
                    {"pid": last_point_id},
                ).scalar_one_or_none()
                last_point_verified = pt_state == "verified"

        # Phase 2: Probe live state outside recovery.sqlite transaction.
        try:
            live = probe_live_workspace_state(db_path, incarnation_dir)
        except WorkspaceStateUnreadable as error:
            return self._fail_capture(
                command=command,
                op_id=op_id,
                actor_ref=f"service:{actor.service}",
                error_code=error.code,
                new_protection_state="unknown",
                alert_kind="backup_unknown",
            )

        # Phase 3: Unchanged fast-path (never overwrite captured_at / verified_at).
        if (
            last_point_id is not None
            and last_point_verified
            and protected_biz == live.business_revision
            and protected_files == live.files_generation
            and protected_src == source_gen
        ):
            checked_now = self.clock()
            result = WorkspaceRecoveryResult(
                point_id=last_point_id,
                phase="reconciled",
                receipt_ref=f"op:{op_id}",
            )
            with immediate_transaction(self.recovery_engine) as conn:
                conn.execute(
                    text(
                        "UPDATE recovery_points SET last_checked_at = :now, "
                        "revision = revision + 1 WHERE point_id = :pid"
                    ),
                    {"now": checked_now, "pid": last_point_id},
                )
                conn.execute(
                    text(
                        "UPDATE backup_state SET protection_state = 'unchanged', "
                        "dirty_since = NULL, last_checked_at = :now, "
                        "last_backup_attempt_at = :now, consecutive_failures = 0, "
                        "last_error_code = NULL, revision = revision + 1 WHERE id = 1"
                    ),
                    {"now": checked_now},
                )
                conn.execute(
                    text(
                        "UPDATE recovery_operations SET state = 'succeeded', "
                        "result_json = :res, error_code = NULL, updated_at = :now, "
                        "revision = revision + 1 WHERE operation_id = :op_id"
                    ),
                    {"res": result.model_dump_json(), "now": checked_now, "op_id": op_id},
                )
                self._record_audit(
                    conn,
                    operation_id=op_id,
                    actor_ref=f"service:{actor.service}",
                    action="backup_unchanged",
                    now=checked_now,
                    facts={"point_id": last_point_id},
                )
            snap = self.read_protection_status()
            self._emit_recovered(snap=snap, now=checked_now)
            self._publish_summary_best_effort()
            return OperationOutcome[WorkspaceRecoveryResult](
                operation=command.reference(),
                state=OperationState.SUCCEEDED,
                revision=2,
                observed_at=checked_now,
                result=result,
            )

        # Phase 4: Consistent SQLite + file staging in scratch/ and off-host encrypted upload + readback.
        point_id = str(uuid4())
        stage_dir = self.scratch_root / f"capture-{op_id}"
        try:
            db_input, file_inputs, snapshot_fp = stage_consistent_snapshot(
                business_db_path=db_path,
                workspace_dir=incarnation_dir,
                staging_dir=stage_dir,
            )
            captured_at = self.clock()
            context = EnvelopeContext(
                deployment_id=self.deployment_id,
                scope_kind="operator",
                operator_id=self.operator_id,
                workspace_id=self.workspace_id,
                point_id=point_id,
                schema_revisions={
                    "business": self.business_schema_revision,
                    "access": self.access_schema_revision,
                },
                key_ref=kms_key_ref,
            )
            if self._last_wrapped_dek_b64 is None and last_point_id is not None:
                with self.recovery_engine.connect() as conn:
                    prev_mref = conn.execute(
                        text("SELECT manifest_ref FROM recovery_points WHERE point_id = :pid"),
                        {"pid": last_point_id},
                    ).scalar_one_or_none()
                if prev_mref is not None:
                    loaded_dek = self.backup_engine.read_wrapped_dek(
                        manifest_ref=object_key_for_manifest_ref(str(prev_mref)),
                        expected_key_ref=kms_key_ref,
                    )
                    if loaded_dek is not None:
                        self._last_wrapped_dek_b64 = loaded_dek
                        self._last_wrapped_key_ref = kms_key_ref
            backup_result = self.backup_engine.create_point(
                context=context,
                captured_at=captured_at,
                business_revision=snapshot_fp.business_revision,
                files_generation=snapshot_fp.files_generation,
                source_generation=source_gen,
                release_ref=self.release_ref,
                databases=[db_input],
                files=file_inputs,
                existing_wrapped_dek_b64=self._last_wrapped_dek_b64,
                existing_key_ref=self._last_wrapped_key_ref,
            )
            self._last_wrapped_dek_b64 = backup_result.wrapped_dek_b64
            self._last_wrapped_key_ref = backup_result.key_ref
        except HostedRecoveryError as error:
            failed_state: Literal["overdue", "unavailable"] = (
                "overdue" if last_point_id is not None else "unavailable"
            )
            return self._fail_capture(
                command=command,
                op_id=op_id,
                actor_ref=f"service:{actor.service}",
                error_code=error.code,
                new_protection_state=failed_state,
                alert_kind="backup_failed",
            )
        except Exception:
            failed_state = "overdue" if last_point_id is not None else "unavailable"
            return self._fail_capture(
                command=command,
                op_id=op_id,
                actor_ref=f"service:{actor.service}",
                error_code="backup_capture_failed",
                new_protection_state=failed_state,
                alert_kind="backup_failed",
            )
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)

        # Phase 5: Commit verified point and healthy backup_state atomically.
        verified_at = max(captured_at, self.clock())
        retain_until = captured_at + self.retention_window_ms
        result = WorkspaceRecoveryResult(
            point_id=point_id,
            phase="captured",
            receipt_ref=f"op:{op_id}",
        )
        with immediate_transaction(self.recovery_engine) as conn:
            conn.execute(
                text(
                    "INSERT INTO recovery_points ("
                    "point_id, workspace_id, operation_id, manifest_ref, manifest_sha256, "
                    "manifest_format, business_revision, files_generation, source_generation, "
                    "release_ref, schema_revision, access_schema_revision, captured_at, "
                    "verified_at, retain_until, key_ref, stored_bytes, state, last_checked_at, "
                    "revision"
                    ") VALUES ("
                    ":point_id, :workspace_id, :op_id, :manifest_ref, :manifest_sha256, "
                    ":manifest_format, :business_revision, :files_generation, :source_generation, "
                    ":release_ref, :schema_revision, :access_schema_revision, :captured_at, "
                    ":verified_at, :retain_until, :key_ref, :stored_bytes, 'verified', "
                    ":verified_at, 1"
                    ")"
                ),
                {
                    "point_id": point_id,
                    "workspace_id": self.workspace_id,
                    "op_id": op_id,
                    "manifest_ref": manifest_ref_for_point(point_id),
                    "manifest_sha256": backup_result.manifest_sha256,
                    "manifest_format": backup_result.manifest_format,
                    "business_revision": snapshot_fp.business_revision,
                    "files_generation": snapshot_fp.files_generation,
                    "source_generation": source_gen,
                    "release_ref": self.release_ref,
                    "schema_revision": self.business_schema_revision,
                    "access_schema_revision": self.access_schema_revision,
                    "captured_at": captured_at,
                    "verified_at": verified_at,
                    "retain_until": retain_until,
                    "key_ref": kms_ref_to_db_ref(kms_key_ref),
                    "stored_bytes": backup_result.stored_bytes,
                },
            )
            conn.execute(
                text(
                    "UPDATE backup_state SET "
                    "last_point_id = :point_id, "
                    "protected_business_revision = :biz_rev, "
                    "protected_files_generation = :files_gen, "
                    "protected_source_generation = :src_gen, "
                    "protection_state = 'healthy', "
                    "dirty_since = NULL, "
                    "last_checked_at = :verified_at, "
                    "last_backup_attempt_at = :verified_at, "
                    "consecutive_failures = 0, "
                    "last_error_code = NULL, "
                    "revision = revision + 1 "
                    "WHERE id = 1"
                ),
                {
                    "point_id": point_id,
                    "biz_rev": snapshot_fp.business_revision,
                    "files_gen": snapshot_fp.files_generation,
                    "src_gen": source_gen,
                    "verified_at": verified_at,
                },
            )
            conn.execute(
                text(
                    "UPDATE recovery_operations SET state = 'succeeded', "
                    "result_json = :res, error_code = NULL, updated_at = :now, "
                    "revision = revision + 1 WHERE operation_id = :op_id"
                ),
                {"res": result.model_dump_json(), "now": verified_at, "op_id": op_id},
            )
            self._record_audit(
                conn,
                operation_id=op_id,
                actor_ref=f"service:{actor.service}",
                action="backup_verified",
                now=verified_at,
                facts={
                    "point_id": point_id,
                    "uploaded_chunks": backup_result.uploaded_chunks,
                    "deduplicated_chunks": backup_result.deduplicated_chunks,
                    "stored_bytes": backup_result.stored_bytes,
                },
            )

        # Phase 6: 7-point reference-safe retention (never pruning sole usable point).
        self._enforce_retention(actor_ref=f"service:{actor.service}")

        snap = self.read_protection_status()
        self._emit_recovered(snap=snap, now=verified_at)
        self._publish_summary_best_effort()
        return OperationOutcome[WorkspaceRecoveryResult](
            operation=command.reference(),
            state=OperationState.SUCCEEDED,
            revision=2,
            observed_at=verified_at,
            result=result,
        )

    def _fail_capture(
        self,
        *,
        command: WorkspaceRecoveryCommand,
        op_id: str,
        actor_ref: str,
        error_code: str,
        new_protection_state: Literal["overdue", "unavailable", "unknown"],
        alert_kind: Literal["backup_failed", "backup_unknown"],
    ) -> OperationOutcome[WorkspaceRecoveryResult]:
        now = self.clock()
        with immediate_transaction(self.recovery_engine) as conn:
            conn.execute(
                text(
                    "UPDATE backup_state SET "
                    "protection_state = :state, "
                    "dirty_since = COALESCE(dirty_since, :now), "
                    "last_checked_at = :now, "
                    "last_backup_attempt_at = :now, "
                    "consecutive_failures = consecutive_failures + 1, "
                    "last_error_code = :err, "
                    "revision = revision + 1 "
                    "WHERE id = 1"
                ),
                {"state": new_protection_state, "now": now, "err": error_code},
            )
            conn.execute(
                text(
                    "UPDATE recovery_operations SET state = 'failed', "
                    "error_code = :err, updated_at = :now, revision = revision + 1 "
                    "WHERE operation_id = :op_id"
                ),
                {"err": error_code, "now": now, "op_id": op_id},
            )
            self._record_audit(
                conn,
                operation_id=op_id,
                actor_ref=actor_ref,
                action="backup_failed",
                now=now,
                facts={"error_code": error_code, "protection_state": new_protection_state},
            )
        snap = self.read_protection_status()
        self._emit_incident(alert_kind=alert_kind, snap=snap, now=now)
        self._publish_summary_best_effort()
        return OperationOutcome[WorkspaceRecoveryResult](
            operation=command.reference(),
            state=OperationState.FAILED,
            revision=2,
            observed_at=now,
            result=None,
            error_code=error_code,
        )

    def _enforce_retention(self, *, actor_ref: str) -> None:
        with immediate_transaction(self.recovery_engine) as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT point_id, manifest_ref FROM recovery_points "
                        "WHERE state = 'verified' "
                        "ORDER BY captured_at DESC, point_id DESC"
                    )
                )
                .mappings()
                .all()
            )
            previously_expired = (
                conn.execute(
                    text(
                        "SELECT point_id, manifest_ref FROM recovery_points "
                        "WHERE state = 'expired' "
                        "ORDER BY captured_at ASC, point_id ASC"
                    )
                )
                .mappings()
                .all()
            )
            retained = rows[: self.retention_points]
            newly_expired = rows[self.retention_points :]
            to_prune = [*previously_expired, *newly_expired]
            if not to_prune or not retained:
                return
            now = self.clock()
            for item in newly_expired:
                conn.execute(
                    text(
                        "UPDATE recovery_points SET state = 'expired', "
                        "last_checked_at = :now, revision = revision + 1 "
                        "WHERE point_id = :pid"
                    ),
                    {"now": now, "pid": item["point_id"]},
                )

        retained_object_keys = [object_key_for_manifest_ref(r["manifest_ref"]) for r in retained]
        try:
            self.backup_engine.prune_unreferenced_chunks(
                retained_manifest_refs=retained_object_keys,
                expected_deployment_id=self.deployment_id,
                expected_scope_kind="operator",
                expected_operator_id=self.operator_id,
                expected_workspace_id=self.workspace_id,
            )
            for item in to_prune:
                self.backup_engine.transport.delete_object(
                    object_key_for_manifest_ref(item["manifest_ref"])
                )
        except Exception:
            logger.warning("Reference-safe retention pruning deferred after storage error.")
            return

        pruned_at = self.clock()
        with immediate_transaction(self.recovery_engine) as conn:
            for item in to_prune:
                conn.execute(
                    text(
                        "UPDATE recovery_points SET state = 'pruned', "
                        "last_checked_at = :now, revision = revision + 1 "
                        "WHERE point_id = :pid"
                    ),
                    {"now": pruned_at, "pid": item["point_id"]},
                )
            self._record_audit(
                conn,
                operation_id=None,
                actor_ref=actor_ref,
                action="retention_pruned",
                now=pruned_at,
                facts={"pruned_points": [item["point_id"] for item in to_prune]},
            )

    def observe(
        self,
        actor: OperatorAuthority | LocalRestoreAuthority,
        query: ObservationQuery,
    ) -> ObservationPage[WorkspaceRecoveryObservation]:
        """Return bounded verified own-workspace recovery points from recovery.sqlite."""
        scope = query.scope
        if (
            not isinstance(scope, WorkspaceScope)
            or scope.workspace_id != self.workspace_id
            or scope.operator_id != self.operator_id
        ):
            raise HostedRecoveryError("Observation scope does not match workspace.")
        limit = min(query.limit, 50)
        with self.recovery_engine.connect() as conn:
            total = int(
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM recovery_points "
                        "WHERE workspace_id = :ws AND state = 'verified'"
                    ),
                    {"ws": self.workspace_id},
                ).scalar_one()
            )
            bs_rev = int(
                conn.execute(text("SELECT revision FROM backup_state WHERE id = 1")).scalar_one()
            )
            rows = (
                conn.execute(
                    text(
                        "SELECT point_id, revision, captured_at, verified_at, "
                        "manifest_sha256, schema_revision, access_schema_revision, state "
                        "FROM recovery_points "
                        "WHERE workspace_id = :ws AND state = 'verified' "
                        "ORDER BY captured_at DESC, point_id DESC LIMIT :limit"
                    ),
                    {"ws": self.workspace_id, "limit": limit},
                )
                .mappings()
                .all()
            )
        now = self.clock()
        items = tuple(
            WorkspaceRecoveryObservation(
                resource_id=row["point_id"],
                revision=int(row["revision"]),
                freshness=Freshness(
                    state=FreshnessState.KNOWN,
                    as_of=int(row["verified_at"]),
                    source_revision=f"recovery:{row['revision']}",
                ),
                captured_at=int(row["captured_at"]),
                verified_at=int(row["verified_at"]),
                manifest_sha256=row["manifest_sha256"],
                eligible=(
                    row["schema_revision"] == self.business_schema_revision
                    and row["access_schema_revision"] == self.access_schema_revision
                ),
            )
            for row in rows
        )
        return ObservationPage[WorkspaceRecoveryObservation](
            items=items,
            matching_total=total,
            freshness=Freshness(
                state=FreshnessState.KNOWN,
                as_of=now,
                source_revision=f"backup_state:{bs_rev}",
            ),
            continuation=None,
        )

    def original(
        self,
        actor: OperatorAuthority | LocalRestoreAuthority | ServiceAuthority,
        reference: OperationReference,
    ) -> OperationOutcome[WorkspaceRecoveryResult] | None:
        with self.recovery_engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT operation_id, request_hash, request_json, state, result_json, "
                        "error_code, updated_at, revision "
                        "FROM recovery_operations WHERE operation_id = :op_id"
                    ),
                    {"op_id": reference.operation_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return self._outcome_from_row(row)

    def active_business_directory(self) -> Path:
        """Resolve the current active business incarnation directory from recovery_meta."""
        with self.recovery_engine.connect() as conn:
            incarnation_dir, _, _, _ = self._active_business_paths(conn)
        return incarnation_dir

    def detect_runtime_mode(self, *, force_recovery_mode: bool = False) -> StartupMode:
        """O(1) per-request mode/readiness check without full-DB dump or retained-file hashing."""
        with self.recovery_engine.connect() as conn:
            meta = (
                conn.execute(text("SELECT active_business_ref FROM recovery_meta WHERE id = 1"))
                .mappings()
                .one()
            )
            active_ref = str(meta["active_business_ref"])
            interrupted = (
                conn.execute(
                    text(
                        "SELECT operation_id FROM restore_operations "
                        "WHERE phase IN ('prepared', 'fenced', 'restored', 'validated', 'needs_attention') "
                        "ORDER BY started_at DESC LIMIT 1"
                    )
                )
                .scalars()
                .first()
            )
            pending_accept = (
                conn.execute(
                    text(
                        "SELECT operation_id FROM restore_operations "
                        "WHERE phase = 'switched' ORDER BY started_at DESC LIMIT 1"
                    )
                )
                .scalars()
                .first()
            )
        if interrupted is not None:
            return StartupMode(
                mode="recovery",
                reason="interrupted_restore_present",
                active_business_ref=active_ref,
                interrupted_restore_id=str(interrupted),
                pending_acceptance_id=str(pending_accept) if pending_accept else None,
            )
        incarnation_dir = (self.workspace_root / active_ref).resolve()
        try:
            incarnation_dir.relative_to(self.workspace_root.resolve())
            db_path = incarnation_dir / "property-management.sqlite"
            if not db_path.is_file() or db_path.is_symlink():
                raise WorkspaceStateUnreadable("Business database missing.")
            with db_path.open("rb") as handle:
                if handle.read(16) != b"SQLite format 3\x00":
                    raise WorkspaceStateUnreadable("Business database header invalid.")
        except OSError, ValueError, WorkspaceStateUnreadable:
            return StartupMode(
                mode="recovery",
                reason="business_database_unreadable",
                active_business_ref=active_ref,
                pending_acceptance_id=str(pending_accept) if pending_accept else None,
            )
        if force_recovery_mode:
            return StartupMode(
                mode="recovery",
                reason="recovery_mode_required",
                active_business_ref=active_ref,
                pending_acceptance_id=str(pending_accept) if pending_accept else None,
            )
        return StartupMode(
            mode="normal",
            reason=None,
            active_business_ref=active_ref,
            pending_acceptance_id=str(pending_accept) if pending_accept else None,
        )

    def detect_startup_mode(self, *, force_recovery_mode: bool = False) -> StartupMode:
        """Inspect active_business_ref and unfinished restores before business composition."""
        with self.recovery_engine.connect() as conn:
            meta = (
                conn.execute(text("SELECT active_business_ref FROM recovery_meta WHERE id = 1"))
                .mappings()
                .one()
            )
            active_ref = str(meta["active_business_ref"])
            interrupted = (
                conn.execute(
                    text(
                        "SELECT operation_id FROM restore_operations "
                        "WHERE phase IN ('prepared', 'fenced', 'restored', 'validated', 'needs_attention') "
                        "ORDER BY started_at DESC LIMIT 1"
                    )
                )
                .scalars()
                .first()
            )
            pending_accept = (
                conn.execute(
                    text(
                        "SELECT operation_id FROM restore_operations "
                        "WHERE phase = 'switched' ORDER BY started_at DESC LIMIT 1"
                    )
                )
                .scalars()
                .first()
            )
        if interrupted is not None:
            return StartupMode(
                mode="recovery",
                reason="interrupted_restore_present",
                active_business_ref=active_ref,
                interrupted_restore_id=str(interrupted),
                pending_acceptance_id=str(pending_accept) if pending_accept else None,
            )
        incarnation_dir = (self.workspace_root / active_ref).resolve()
        try:
            incarnation_dir.relative_to(self.workspace_root.resolve())
            db_path = incarnation_dir / "property-management.sqlite"
            probe_live_workspace_state(db_path, incarnation_dir)
        except ValueError, WorkspaceStateUnreadable:
            return StartupMode(
                mode="recovery",
                reason="business_database_unreadable",
                active_business_ref=active_ref,
                pending_acceptance_id=str(pending_accept) if pending_accept else None,
            )
        if force_recovery_mode:
            return StartupMode(
                mode="recovery",
                reason="recovery_mode_required",
                active_business_ref=active_ref,
                pending_acceptance_id=str(pending_accept) if pending_accept else None,
            )
        return StartupMode(
            mode="normal",
            reason=None,
            active_business_ref=active_ref,
            pending_acceptance_id=str(pending_accept) if pending_accept else None,
        )

    def protection_section(self) -> Section[Protection]:
        """Build a live Section[Protection] directly from recovery.sqlite (D12)."""
        snap = self.read_protection_status()
        now = self.clock()
        proof_ref = f"point:{snap.last_point_id}" if snap.last_point_id else None
        if (
            snap.protection_state in {"healthy", "unchanged"}
            and snap.last_verified_at is not None
            and proof_ref is not None
        ):
            return Section[Protection](
                state="ready",
                data=Protection(
                    status="protected",
                    state=snap.protection_state,
                    last_verified_at=snap.last_verified_at,
                    point_age_ms=max(0, now - snap.last_verified_at),
                    proof_ref=proof_ref,
                ),
                freshness=Freshness(
                    state=FreshnessState.KNOWN,
                    as_of=snap.last_checked_at or snap.last_verified_at,
                    source_revision=f"backup_state:{snap.revision}",
                ),
            )
        if snap.protection_state == "overdue":
            return Section[Protection](
                state="ready",
                data=Protection(
                    status="degraded",
                    state="overdue",
                    last_verified_at=snap.last_verified_at,
                    point_age_ms=(
                        max(0, now - snap.last_verified_at)
                        if snap.last_verified_at is not None
                        else None
                    ),
                    proof_ref=proof_ref,
                ),
                freshness=Freshness(
                    state=FreshnessState.STALE,
                    as_of=snap.last_checked_at or snap.last_verified_at or now,
                    source_revision=f"backup_state:{snap.revision}",
                    error_code=snap.last_error_code or "backup_overdue",
                ),
            )
        return Section[Protection](
            state="unavailable",
            freshness=Freshness(
                state=FreshnessState.UNAVAILABLE,
                error_code=snap.last_error_code or "backup_protection_unavailable",
            ),
        )

    def _require_operator_scope(self, actor: OperatorAuthority | LocalRestoreAuthority) -> None:
        if not isinstance(
            actor, (OperatorAuthority, OperatorRestoreAuthority, LocalRestoreAuthority)
        ):
            raise RestoreDeniedError("Operator authority is required for workspace recovery.")
        scope = actor.scope
        if (
            actor.deployment_id != self.deployment_id
            or not isinstance(scope, WorkspaceScope)
            or scope.workspace_id != self.workspace_id
            or scope.operator_id != self.operator_id
        ):
            raise RestoreDeniedError("Restore authority scope does not match owning workspace.")

    def _prune_expired_previews(self, now: int) -> None:
        expired = [pid for pid, item in self._previews.items() if item.expires_at <= now]
        for pid in expired:
            self._previews.pop(pid, None)

    def get_preview(self, preview_id: str) -> RestorePreview | None:
        now = self.clock()
        self._prune_expired_previews(now)
        return self._previews.get(preview_id)

    def preview_restore(
        self,
        actor: OperatorAuthority | LocalRestoreAuthority,
        *,
        point_id: str,
    ) -> RestorePreview:
        """Create a short-lived restore preview bound to (workspace, point, source_epoch, preview)."""
        self._require_operator_scope(actor)
        now = self.clock()
        self._prune_expired_previews(now)
        with self.recovery_engine.connect() as conn:
            point = (
                conn.execute(
                    text(
                        "SELECT point_id, workspace_id, state, captured_at, verified_at, "
                        "schema_revision, access_schema_revision "
                        "FROM recovery_points WHERE point_id = :pid"
                    ),
                    {"pid": point_id},
                )
                .mappings()
                .first()
            )
            if point is None or point["workspace_id"] != self.workspace_id:
                raise RestoreNotFoundError("Recovery point not found for this workspace.")
            if point["state"] != "verified":
                raise RestoreDeniedError("Only verified recovery points can be restored.")
            if (
                point["schema_revision"] != self.business_schema_revision
                or point["access_schema_revision"] != self.access_schema_revision
            ):
                raise RestoreDeniedError("Recovery point schema revision is incompatible.")
            incarnation_dir, db_path, source_gen, _ = self._active_business_paths(conn)

        source_epoch = self._current_access_epoch()
        recovery_mode = False
        current_biz_rev: str | None = None
        try:
            current_biz_rev = probe_live_workspace_state(db_path, incarnation_dir).business_revision
        except WorkspaceStateUnreadable:
            recovery_mode = True

        preview_id = str(uuid4())
        exact_hash = compute_restore_request_hash(
            workspace_id=self.workspace_id,
            point_id=point_id,
            source_epoch=source_epoch,
            preview_id=preview_id,
        )
        preview = RestorePreview(
            preview_id=preview_id,
            point_id=point_id,
            workspace_id=self.workspace_id,
            source_epoch=source_epoch,
            source_generation=source_gen,
            current_business_revision=current_biz_rev,
            selected_captured_at=int(point["captured_at"]),
            selected_verified_at=int(point["verified_at"]),
            exact_request_hash=exact_hash,
            created_at=now,
            expires_at=now + PREVIEW_TTL_MS,
            recovery_mode=recovery_mode,
        )
        self._previews[preview_id] = preview
        with immediate_transaction(self.recovery_engine) as conn:
            self._record_audit(
                conn,
                operation_id=None,
                actor_ref="operator:preview",
                action="restore_previewed",
                now=now,
                facts={
                    "preview_id": preview_id,
                    "point_id": point_id,
                    "source_epoch": source_epoch,
                },
            )
        return preview

    def _run_source_fence(self, *, kind: Literal["maintenance_fence", "drain"], op_id: str) -> None:
        if self.source_lifecycle is None:
            return
        with self.access_engine.connect() as conn:
            meta = (
                conn.execute(text("SELECT revision, access_epoch FROM access_meta WHERE id = 1"))
                .mappings()
                .one()
            )
            rev = int(meta["revision"])
            epoch = int(meta["access_epoch"])
        scope = WorkspaceScope(operator_id=self.operator_id, workspace_id=self.workspace_id)
        actor = ServiceAuthority(
            deployment_id=self.deployment_id,
            scope=scope,
            service="source",
            authenticated_channel_ref="internal:operator_recovery",
        )
        payload = (
            MaintenanceFence(maintenance_id=op_id)
            if kind == "maintenance_fence"
            else Drain(maintenance_id=op_id)
        )
        intent = CommandIntent(
            deployment_id=self.deployment_id,
            scope=scope,
            kind=kind,
            expected_revision=rev,
            access_epoch=epoch,
            payload=payload,
        )
        cmd = SourceCommand(
            operation_id=str(uuid4()),
            idempotency_key=f"restore-{kind}-{op_id}",
            intent=intent,
            request_hash=semantic_hash(intent),
        )
        self.source_lifecycle.execute(actor, cmd)

    def _run_verify_restore_binding(self, *, point_id: str, op_id: str) -> int:
        if self.source_lifecycle is None:
            with immediate_transaction(self.access_engine) as conn:
                now = self.clock()
                conn.execute(
                    text(
                        "UPDATE access_meta SET access_epoch = access_epoch + 1, "
                        "restore_generation = restore_generation + 1, "
                        "maintenance_operation_id = NULL, revision = revision + 1 WHERE id = 1"
                    )
                )
                conn.execute(
                    text("UPDATE access_sessions SET revoked_at = :now WHERE revoked_at IS NULL"),
                    {"now": now},
                )
                return int(
                    conn.execute(
                        text("SELECT access_epoch FROM access_meta WHERE id = 1")
                    ).scalar_one()
                )
        with self.access_engine.connect() as conn:
            meta = (
                conn.execute(text("SELECT revision, access_epoch FROM access_meta WHERE id = 1"))
                .mappings()
                .one()
            )
            rev = int(meta["revision"])
            epoch = int(meta["access_epoch"])
        scope = WorkspaceScope(operator_id=self.operator_id, workspace_id=self.workspace_id)
        actor = ServiceAuthority(
            deployment_id=self.deployment_id,
            scope=scope,
            service="operator_recovery",
            authenticated_channel_ref="internal:operator_recovery",
        )
        intent = CommandIntent(
            deployment_id=self.deployment_id,
            scope=scope,
            kind="verify_restore_binding",
            expected_revision=rev,
            access_epoch=epoch + 1,
            payload=VerifyRestoreBinding(point_id=point_id, restore_operation_id=op_id),
        )
        cmd = SourceCommand(
            operation_id=str(uuid4()),
            idempotency_key=f"restore-verify-binding-{op_id}",
            intent=intent,
            request_hash=semantic_hash(intent),
        )
        self.source_lifecycle.execute(actor, cmd)
        return self._current_access_epoch()

    def lookup_idempotent_restore(
        self,
        *,
        idempotency_key: str,
        point_id: str,
        preview_id: str,
    ) -> OperationOutcome[WorkspaceRecoveryResult] | None:
        """Return original restore outcome on exact replay without requiring an active preview."""
        with self.recovery_engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT * FROM recovery_operations "
                        "WHERE kind = 'restore' AND idempotency_key = :key"
                    ),
                    {"key": idempotency_key},
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        stored_cmd = WorkspaceRecoveryCommand.model_validate_json(row["request_json"])
        payload = stored_cmd.intent.payload
        if (
            not isinstance(payload, ConfirmRestore)
            or payload.point_id != point_id
            or payload.preview_id != preview_id
        ):
            raise SemanticConflict()
        return self._outcome_from_row(row)

    def confirm_restore(
        self,
        actor: OperatorRestoreAuthority | LocalRestoreAuthority,
        *,
        point_id: str,
        preview_id: str,
        idempotency_key: str,
        authorized_subject: str,
        operation_id: str | None = None,
        command: WorkspaceRecoveryCommand | None = None,
        before_switch_hook: Callable[[Path], None] | None = None,
    ) -> OperationOutcome[WorkspaceRecoveryResult]:
        """Execute crash-safe operator-authorized restore with atomic locator switch (D4, D6)."""
        self._require_operator_scope(actor)
        now = self.clock()
        self._prune_expired_previews(now)

        # Idempotent replay check before consuming preview or recomputing epoch (#13a).
        existing = self.lookup_idempotent_restore(
            idempotency_key=idempotency_key,
            point_id=point_id,
            preview_id=preview_id,
        )
        if existing is not None:
            return existing

        preview = self._previews.get(preview_id)
        if preview is None or preview_id in self._consumed_previews:
            raise RestoreDeniedError("Restore preview is missing, expired, or already used.")
        if preview.point_id != point_id or preview.workspace_id != self.workspace_id:
            raise RestoreDeniedError("Restore confirmation does not match previewed point.")
        if now > preview.expires_at:
            self._previews.pop(preview_id, None)
            raise RestoreDeniedError("Restore preview has expired.")

        scope = WorkspaceScope(operator_id=self.operator_id, workspace_id=self.workspace_id)
        op_id = operation_id or str(uuid4())
        if command is None:
            intent = CommandIntent(
                deployment_id=self.deployment_id,
                scope=scope,
                kind="confirm_restore",
                expected_revision=1,
                access_epoch=preview.source_epoch,
                payload=ConfirmRestore(
                    point_id=point_id,
                    preview_id=preview_id,
                    confirmation_id=preview_id,
                ),
            )
            command = WorkspaceRecoveryCommand(
                operation_id=op_id,
                idempotency_key=idempotency_key,
                intent=intent,
                request_hash=semantic_hash(intent),
            )

        if isinstance(actor, OperatorRestoreAuthority):
            if now - actor.step_up_at > STEP_UP_TTL_MS or actor.step_up_at > now:
                raise RestoreDeniedError("Recent strong step-up authentication has expired.")
            if actor.confirmed_request_hash not in {
                preview.exact_request_hash,
                command.request_hash,
            }:
                raise RestoreDeniedError("Step-up confirmation hash does not match preview.")
        elif actor.confirmed_request_hash not in {preview.exact_request_hash, command.request_hash}:
            raise RestoreDeniedError("Local restore confirmation hash does not match preview.")

        current_epoch = self._current_access_epoch()
        if current_epoch != preview.source_epoch:
            raise RestoreDeniedError("Workspace access_epoch changed since preview; preview again.")

        # Probe existing tree OUTSIDE any SQLite write transaction (#15).
        with self.recovery_engine.connect() as conn:
            prior_ref_probe = str(
                conn.execute(
                    text("SELECT active_business_ref FROM recovery_meta WHERE id = 1")
                ).scalar_one()
            )
        prior_dir = (self.workspace_root / prior_ref_probe).resolve()
        prior_db = prior_dir / "property-management.sqlite"
        prior_tree_kind: Literal["healthy_pre_state", "forensic_damaged"] = "healthy_pre_state"
        try:
            probe_live_workspace_state(prior_db, prior_dir)
        except WorkspaceStateUnreadable:
            prior_tree_kind = "forensic_damaged"

        if not self._op_lock.acquire(blocking=False):
            raise BackupConflictError()

        target_dir: Path | None = None
        switched = False
        auth_expires_at = now + EXECUTION_AUTH_TTL_MS
        try:
            # Consume preview single-use now that we own the exclusive lock.
            self._consumed_previews.add(preview_id)
            self._previews.pop(preview_id, None)

            with immediate_transaction(self.recovery_engine) as conn:
                existing = self._lookup_idempotent(
                    conn,
                    kind="restore",
                    idempotency_key=idempotency_key,
                    request_hash=command.request_hash,
                )
                if existing is not None:
                    return existing
                point = (
                    conn.execute(
                        text(
                            "SELECT point_id, workspace_id, manifest_ref, manifest_sha256, "
                            "state, schema_revision, access_schema_revision "
                            "FROM recovery_points WHERE point_id = :pid"
                        ),
                        {"pid": point_id},
                    )
                    .mappings()
                    .first()
                )
                if (
                    point is None
                    or point["workspace_id"] != self.workspace_id
                    or point["state"] != "verified"
                ):
                    raise RestoreDeniedError(
                        "Selected recovery point is unavailable or unverified."
                    )
                if (
                    point["schema_revision"] != self.business_schema_revision
                    or point["access_schema_revision"] != self.access_schema_revision
                ):
                    raise RestoreDeniedError("Selected recovery point schema is incompatible.")

                meta = (
                    conn.execute(
                        text(
                            "SELECT active_business_ref, source_generation "
                            "FROM recovery_meta WHERE id = 1"
                        )
                    )
                    .mappings()
                    .one()
                )
                prior_ref = str(meta["active_business_ref"])
                source_gen = int(meta["source_generation"])
                new_gen = source_gen + 1
                target_ref = f"incarnation-{new_gen}"
                manifest_ref = str(point["manifest_ref"])
                manifest_sha256 = str(point["manifest_sha256"])

                auth_ref = (
                    actor.step_up_ref
                    if isinstance(actor, OperatorRestoreAuthority)
                    else actor.os_owner_proof_ref
                )
                conn.execute(
                    text(
                        "INSERT INTO recovery_operations ("
                        "operation_id, kind, idempotency_key, request_hash, request_json, "
                        "actor_kind, actor_ref, state, source_generation, result_json, error_code, "
                        "created_at, updated_at, revision"
                        ") VALUES ("
                        ":op_id, 'restore', :key, :hash, :req_json, 'operator', :actor_ref, 'running', "
                        ":src_gen, NULL, NULL, :now, :now, 1"
                        ")"
                    ),
                    {
                        "op_id": op_id,
                        "key": idempotency_key,
                        "hash": command.request_hash,
                        "req_json": command.model_dump_json(),
                        "actor_ref": auth_ref,
                        "src_gen": source_gen,
                        "now": now,
                    },
                )
                conn.execute(
                    text(
                        "INSERT INTO restore_operations ("
                        "operation_id, point_id, preview_id, prior_business_ref, prior_tree_kind, "
                        "target_business_ref, new_source_generation, new_access_epoch, "
                        "authorized_subject, authorization_ref, authorized_at, "
                        "execution_authorization_expires_at, preview_source_revision, "
                        "executor_ref, phase, validation_ref, started_at, updated_at, accepted_at"
                        ") VALUES ("
                        ":op_id, :pid, :preview_id, :prior_ref, :prior_kind, :target_ref, "
                        ":new_gen, NULL, :subject, :auth_ref, :now, :auth_exp, :prev_rev, "
                        "'service:operator_recovery', 'prepared', NULL, :now, :now, NULL"
                        ")"
                    ),
                    {
                        "op_id": op_id,
                        "pid": point_id,
                        "preview_id": preview_id,
                        "prior_ref": prior_ref,
                        "prior_kind": prior_tree_kind,
                        "target_ref": target_ref,
                        "new_gen": new_gen,
                        "subject": authorized_subject,
                        "auth_ref": auth_ref,
                        "now": now,
                        "auth_exp": auth_expires_at,
                        "prev_rev": preview.current_business_revision,
                    },
                )
                self._record_audit(
                    conn,
                    operation_id=op_id,
                    actor_ref=auth_ref,
                    action="restore_prepared",
                    now=now,
                    facts={
                        "point_id": point_id,
                        "prior_ref": prior_ref,
                        "prior_tree_kind": prior_tree_kind,
                        "target_ref": target_ref,
                    },
                )

            # Enforce D4 execution authorization TTL before fencing (#16).
            if self.clock() > auth_expires_at:
                raise RestoreDeniedError("Restore execution authorization expired before fencing.")

            # Phase: fenced (maintenance_fence + drain + close live business DB connections).
            self._run_source_fence(kind="maintenance_fence", op_id=op_id)
            self._run_source_fence(kind="drain", op_id=op_id)
            if self.close_business_connections is not None:
                self.close_business_connections()
            fenced_at = self.clock()
            with immediate_transaction(self.recovery_engine) as conn:
                conn.execute(
                    text(
                        "UPDATE restore_operations SET phase = 'fenced', updated_at = :now "
                        "WHERE operation_id = :op_id"
                    ),
                    {"now": fenced_at, "op_id": op_id},
                )

            # Phase: restored -> download, verify AEAD + digests into fresh sibling directory.
            target_dir = (self.workspace_root / target_ref).resolve()
            try:
                target_dir.relative_to(self.workspace_root.resolve())
            except ValueError as error:
                raise RecoveryIntegrityError("Restore target escapes workspace root.") from error
            if target_dir.exists():
                raise RecoveryIntegrityError("Target incarnation directory already exists.")
            target_dir.mkdir(mode=0o700, parents=False)

            self.backup_engine.restore_point(
                manifest_ref=object_key_for_manifest_ref(manifest_ref),
                expected_deployment_id=self.deployment_id,
                expected_scope_kind="operator",
                expected_operator_id=self.operator_id,
                expected_workspace_id=self.workspace_id,
                expected_point_id=point_id,
                expected_manifest_sha256=manifest_sha256,
                destination_dir=target_dir,
            )
            # Materialize restored files into incarnation root matching local_relative_path layout.
            restored_files_wrapper = target_dir / "files"
            if restored_files_wrapper.is_dir():
                for child in list(restored_files_wrapper.iterdir()):
                    dest = target_dir / child.name
                    if child.name == "files" and child.is_dir():
                        for nested in list(child.iterdir()):
                            shutil.move(str(nested), str(restored_files_wrapper / nested.name))
                        child.rmdir()
                    elif not dest.exists():
                        shutil.move(str(child), str(dest))

            restored_at = self.clock()
            with immediate_transaction(self.recovery_engine) as conn:
                conn.execute(
                    text(
                        "UPDATE restore_operations SET phase = 'restored', updated_at = :now "
                        "WHERE operation_id = :op_id"
                    ),
                    {"now": restored_at, "op_id": op_id},
                )

            # Phase: validated -> SQLite PRAGMA integrity_check + file completeness/digest check.
            restored_db = target_dir / "property-management.sqlite"
            val_conn = sqlite3.connect(restored_db.as_uri() + "?mode=ro", uri=True)
            try:
                integrity = val_conn.execute("PRAGMA integrity_check").fetchone()
                if not integrity or integrity[0] != "ok":
                    raise RecoveryIntegrityError("Restored SQLite database failed integrity_check.")
            finally:
                val_conn.close()
            probe_live_workspace_state(restored_db, target_dir)

            if before_switch_hook is not None:
                before_switch_hook(target_dir)

            # Enforce D4 execution authorization TTL before switching active_business_ref (#16).
            if self.clock() > auth_expires_at:
                raise RestoreDeniedError("Restore execution authorization expired before switch.")

            validated_at = self.clock()
            with immediate_transaction(self.recovery_engine) as conn:
                conn.execute(
                    text(
                        "UPDATE restore_operations SET phase = 'validated', "
                        "validation_ref = :vref, updated_at = :now WHERE operation_id = :op_id"
                    ),
                    {"vref": f"integrity:{op_id}", "now": validated_at, "op_id": op_id},
                )

            # Phase: switched -> commit active_business_ref in recovery.sqlite FIRST while
            # maintenance_operation_id still fences traffic (#12), THEN run verify_restore_binding.
            switched_at = self.clock()
            result = WorkspaceRecoveryResult(
                point_id=point_id,
                phase="restored",
                receipt_ref=f"op:{op_id}",
            )
            with immediate_transaction(self.recovery_engine) as conn:
                conn.execute(
                    text(
                        "UPDATE recovery_meta SET active_business_ref = :target_ref, "
                        "source_generation = :new_gen, restore_generation = restore_generation + 1, "
                        "revision = revision + 1 WHERE id = 1"
                    ),
                    {"target_ref": target_ref, "new_gen": new_gen},
                )
                conn.execute(
                    text(
                        "UPDATE restore_operations SET phase = 'switched', updated_at = :now "
                        "WHERE operation_id = :op_id"
                    ),
                    {"now": switched_at, "op_id": op_id},
                )
                conn.execute(
                    text(
                        "UPDATE recovery_operations SET state = 'succeeded', "
                        "result_json = :res, error_code = NULL, updated_at = :now, "
                        "revision = revision + 1 WHERE operation_id = :op_id"
                    ),
                    {"res": result.model_dump_json(), "now": switched_at, "op_id": op_id},
                )
            switched = True

            new_epoch = self._run_verify_restore_binding(point_id=point_id, op_id=op_id)
            with immediate_transaction(self.recovery_engine) as conn:
                conn.execute(
                    text(
                        "UPDATE restore_operations SET new_access_epoch = :new_epoch, "
                        "updated_at = :now WHERE operation_id = :op_id"
                    ),
                    {"new_epoch": new_epoch, "now": self.clock(), "op_id": op_id},
                )
                self._record_audit(
                    conn,
                    operation_id=op_id,
                    actor_ref="service:operator_recovery",
                    action="restore_switched",
                    now=switched_at,
                    facts={
                        "point_id": point_id,
                        "target_ref": target_ref,
                        "prior_ref": prior_ref,
                        "new_access_epoch": new_epoch,
                    },
                )

            self._publish_summary_best_effort()
            return OperationOutcome[WorkspaceRecoveryResult](
                operation=command.reference(),
                state=OperationState.SUCCEEDED,
                revision=2,
                observed_at=switched_at,
                result=result,
            )
        except Exception as error:
            # Clean up unvalidated staging tree ONLY if active_business_ref has NOT switched (#12).
            if not switched and target_dir is not None and target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            # Release maintenance_operation_id fence on pre-switch failure (#11) so workspace is not wedged.
            if not switched:
                try:
                    self._release_maintenance_fence(op_id)
                except Exception:
                    logger.warning("Failed to release maintenance fence after restore rollback.")
            err_code = error.code if isinstance(error, HostedRecoveryError) else "restore_failed"
            failed_at = self.clock()
            with immediate_transaction(self.recovery_engine) as conn:
                conn.execute(
                    text(
                        "UPDATE restore_operations SET phase = 'needs_attention', "
                        "updated_at = :now WHERE operation_id = :op_id AND phase != 'switched'"
                    ),
                    {"now": failed_at, "op_id": op_id},
                )
                conn.execute(
                    text(
                        "UPDATE recovery_operations SET state = 'failed', "
                        "error_code = :err, updated_at = :now, revision = revision + 1 "
                        "WHERE operation_id = :op_id AND state NOT IN ('succeeded', 'failed')"
                    ),
                    {"err": err_code, "now": failed_at, "op_id": op_id},
                )
                self._record_audit(
                    conn,
                    operation_id=op_id,
                    actor_ref="service:operator_recovery",
                    action="restore_failed",
                    now=failed_at,
                    facts={"point_id": point_id, "error_code": err_code},
                )
            return OperationOutcome[WorkspaceRecoveryResult](
                operation=command.reference(),
                state=OperationState.FAILED,
                revision=2,
                observed_at=failed_at,
                result=None,
                error_code=err_code,
            )
        finally:
            self._op_lock.release()

    def accept_restore(
        self,
        actor: OperatorAuthority | LocalRestoreAuthority,
        *,
        operation_id: str,
    ) -> RestoreStatusDetail:
        """Accept a switched restore after fresh post-restore operator sign-in."""
        self._require_operator_scope(actor)
        now = self.clock()
        with immediate_transaction(self.recovery_engine) as conn:
            row = (
                conn.execute(
                    text("SELECT * FROM restore_operations WHERE operation_id = :op_id"),
                    {"op_id": operation_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise RestoreNotFoundError("Restore operation not found.")
            if row["phase"] == "accepted":
                detail = self.restore_operation_detail(operation_id)
                assert detail is not None
                return detail
            if row["phase"] != "switched":
                raise RestoreDeniedError("Only a switched restore can be accepted.")
            conn.execute(
                text(
                    "UPDATE restore_operations SET phase = 'accepted', "
                    "accepted_at = :now, updated_at = :now WHERE operation_id = :op_id"
                ),
                {"now": now, "op_id": operation_id},
            )
            self._record_audit(
                conn,
                operation_id=operation_id,
                actor_ref="operator:accept",
                action="restore_accepted",
                now=now,
                facts={"point_id": row["point_id"], "prior_ref": row["prior_business_ref"]},
            )
        detail = self.restore_operation_detail(operation_id)
        assert detail is not None
        return detail

    def restore_operation_detail(self, operation_id: str) -> RestoreStatusDetail | None:
        with self.recovery_engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT ro.*, op.state AS op_state, op.error_code AS op_error_code "
                        "FROM restore_operations ro "
                        "JOIN recovery_operations op ON op.operation_id = ro.operation_id "
                        "WHERE ro.operation_id = :op_id"
                    ),
                    {"op_id": operation_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return RestoreStatusDetail(
            operation_id=row["operation_id"],
            point_id=row["point_id"],
            preview_id=row["preview_id"],
            phase=row["phase"],
            state=row["op_state"],
            prior_business_ref=row["prior_business_ref"],
            prior_tree_kind=row["prior_tree_kind"],
            target_business_ref=row["target_business_ref"],
            new_source_generation=int(row["new_source_generation"]),
            new_access_epoch=(
                int(row["new_access_epoch"]) if row["new_access_epoch"] is not None else None
            ),
            started_at=int(row["started_at"]),
            updated_at=int(row["updated_at"]),
            accepted_at=int(row["accepted_at"]) if row["accepted_at"] is not None else None,
            error_code=row["op_error_code"],
        )

    def reconstruct_catalog(
        self,
        actor: OperatorAuthority | LocalRestoreAuthority,
    ) -> ReconstructResult:
        """Reconstruct missing verified recovery_points rows from own-workspace off-host manifests."""
        self._require_operator_scope(actor)
        manifest_keys = self.backup_engine.transport.list_objects("manifests/")
        imported: list[str] = []
        skipped: list[str] = []
        now = self.clock()

        for key in manifest_keys:
            try:
                manifest, _, _, manifest_sha256 = self.backup_engine.load_manifest(
                    manifest_ref=key,
                    expected_deployment_id=self.deployment_id,
                    expected_scope_kind="operator",
                    expected_operator_id=self.operator_id,
                    expected_workspace_id=self.workspace_id,
                )
            except HostedRecoveryError:
                skipped.append(key)
                continue

            with immediate_transaction(self.recovery_engine) as conn:
                exists = conn.execute(
                    text("SELECT 1 FROM recovery_points WHERE point_id = :pid"),
                    {"pid": manifest.point_id},
                ).scalar_one_or_none()
                if exists is not None:
                    skipped.append(manifest.point_id)
                    continue
                op_id = str(uuid4())
                result = WorkspaceRecoveryResult(
                    point_id=manifest.point_id,
                    phase="reconciled",
                    receipt_ref=f"reconstruct:{op_id}",
                )
                conn.execute(
                    text(
                        "INSERT INTO recovery_operations ("
                        "operation_id, kind, idempotency_key, request_hash, request_json, "
                        "actor_kind, actor_ref, state, source_generation, result_json, error_code, "
                        "created_at, updated_at, revision"
                        ") VALUES ("
                        ":op_id, 'backup', :key, :hash, '{}', 'system', 'service:operator_recovery', "
                        "'succeeded', :src_gen, :res_json, NULL, :now, :now, 1"
                        ")"
                    ),
                    {
                        "op_id": op_id,
                        "key": f"reconstruct-{manifest.point_id}",
                        "hash": manifest_sha256,
                        "src_gen": manifest.source_generation,
                        "res_json": result.model_dump_json(),
                        "now": now,
                    },
                )
                stored_bytes = sum(
                    c.ciphertext_size
                    for g in (*manifest.databases, *manifest.files)
                    for c in g.chunks
                )
                verified_at = max(now, manifest.captured_at)
                conn.execute(
                    text(
                        "INSERT INTO recovery_points ("
                        "point_id, workspace_id, operation_id, manifest_ref, manifest_sha256, "
                        "manifest_format, business_revision, files_generation, source_generation, "
                        "release_ref, schema_revision, access_schema_revision, captured_at, "
                        "verified_at, retain_until, key_ref, stored_bytes, state, last_checked_at, "
                        "revision"
                        ") VALUES ("
                        ":point_id, :ws, :op_id, :mref, :msha, :mfmt, :biz_rev, :fgen, :sgen, "
                        ":rel, :bschema, :aschema, :cap, :ver, :ret, :kref, :sbytes, 'verified', "
                        ":ver, 1"
                        ")"
                    ),
                    {
                        "point_id": manifest.point_id,
                        "ws": self.workspace_id,
                        "op_id": op_id,
                        "mref": manifest_ref_for_point(manifest.point_id),
                        "msha": manifest_sha256,
                        "mfmt": manifest.format_version,
                        "biz_rev": manifest.business_revision,
                        "fgen": manifest.files_generation,
                        "sgen": manifest.source_generation,
                        "rel": manifest.release_ref,
                        "bschema": manifest.schema_revisions.get(
                            "business", self.business_schema_revision
                        ),
                        "aschema": manifest.schema_revisions.get(
                            "access", self.access_schema_revision
                        ),
                        "cap": manifest.captured_at,
                        "ver": verified_at,
                        "ret": manifest.captured_at + self.retention_window_ms,
                        "kref": kms_ref_to_db_ref(manifest.key_ref),
                        "sbytes": stored_bytes,
                    },
                )
                self._record_audit(
                    conn,
                    operation_id=op_id,
                    actor_ref="service:operator_recovery",
                    action="catalog_reconstructed",
                    now=now,
                    facts={"point_id": manifest.point_id, "manifest_sha256": manifest_sha256},
                )
                imported.append(manifest.point_id)

        return ReconstructResult(
            scanned_manifests=len(manifest_keys),
            imported_points=imported,
            skipped_points=skipped,
        )

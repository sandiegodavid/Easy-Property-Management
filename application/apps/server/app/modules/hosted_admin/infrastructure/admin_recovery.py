"""Admin control-plane backup, independent recovery mode & host-loss recovery (H05.6 / D5)."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import stat
import threading
from typing import Literal
from uuid import uuid4

from pydantic import Field
from sqlalchemy import Engine, text

from app.modules.hosted_admin.application.recovery_contracts import (
    AdminRecoveryCommand,
    AdminRecoveryObservation,
    AdminRecoveryResult,
    CaptureControl,
    ConfirmControlRestore,
    PreviewControlRestore,
    ReconcileCheckpoint,
    require_invocation,
)
from app.modules.hosted_recovery.domain.models import (
    EnvelopeContext,
    HostedRecoveryError,
    RecoveryIntegrityError,
    canonical_json_bytes,
    validate_kms_key_ref,
)
from app.modules.hosted_recovery.infrastructure.engine import (
    ChunkedAeadBackupEngine,
    DatabaseInput,
)
from app.modules.workspace.infrastructure.hosted_recovery import (
    DEFAULT_RETENTION_POINTS,
    DEFAULT_RETENTION_WINDOW_MS,
    EXECUTION_AUTH_TTL_MS,
    PREVIEW_TTL_MS,
    STEP_UP_TTL_MS,
    WorkspaceStateUnreadable,
    _fingerprint_database,
    _open_readonly_sqlite,
    db_ref_to_kms_ref,
    kms_ref_to_db_ref,
    manifest_ref_for_point,
    object_key_for_manifest_ref,
)
from app.platform.hosted_contracts.authority import (
    AdminRecoveryAuthority,
    ObservationPage,
    ObservationQuery,
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
from app.platform.hosted_contracts.values import CanonicalId, Contract, DeploymentScope, Reference
from app.platform.hosted_schema import HostedSchemaError, initialize_store, validate_schema
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction


class AdminRecoveryDenied(HostedRecoveryError):
    code = "admin_recovery_denied"


class AdminRecoveryNotFound(HostedRecoveryError):
    code = "admin_recovery_not_found"


class BootstrapRecoveryPrincipal(Contract):
    """Approved Admin recovery principal pinned outside admin.sqlite (D5)."""

    issuer: Reference
    subject: str = Field(min_length=1, max_length=256)
    principal_ref: Reference
    mfa_required: Literal[True] = True


class BootstrapRecoveryAuthority(Contract):
    """Protected root-owned /run/epm/admin-recovery-authority.json policy (D5)."""

    version: Literal[1] = 1
    deployment_id: CanonicalId
    principals: tuple[BootstrapRecoveryPrincipal, ...] = Field(min_length=1)

    def require_principal(self, principal_ref: str) -> BootstrapRecoveryPrincipal:
        for item in self.principals:
            if item.principal_ref == principal_ref:
                return item
        raise AdminRecoveryDenied("Caller is not an approved bootstrap Admin recovery principal.")

    def verify_identity(
        self, *, issuer: str, subject: str, mfa_verified_at: int | None
    ) -> BootstrapRecoveryPrincipal:
        if mfa_verified_at is None:
            raise AdminRecoveryDenied("Admin recovery requires verified TOTP/MFA.")
        for item in self.principals:
            if item.issuer == issuer and item.subject == subject:
                return item
        raise AdminRecoveryDenied("Identity does not match protected bootstrap recovery authority.")


def load_bootstrap_authority(
    path: Path,
    *,
    expected_authority_ref: str | None = None,
) -> tuple[BootstrapRecoveryAuthority, str]:
    """Load and pin-verify the protected bootstrap recovery authority file (D5)."""
    if not path.is_absolute() or path.resolve() != path or path.is_symlink():
        raise AdminRecoveryDenied(
            "Bootstrap recovery authority path must be canonical and non-symlink."
        )
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
        raise AdminRecoveryDenied(
            "Bootstrap recovery authority file must be private (no group/world access)."
        )
    raw = path.read_bytes()
    authority_ref = "sha256:" + hashlib.sha256(raw).hexdigest()
    if expected_authority_ref is not None and authority_ref != expected_authority_ref:
        raise AdminRecoveryDenied("Bootstrap recovery authority digest does not match pinned ref.")
    try:
        authority = BootstrapRecoveryAuthority.model_validate_json(raw)
    except Exception as error:
        raise AdminRecoveryDenied("Bootstrap recovery authority file is malformed.") from error
    return authority, authority_ref


@dataclass(frozen=True)
class AdminStartupMode:
    mode: Literal["normal", "recovery"]
    reason: str | None
    active_admin_resource_ref: str


@dataclass(frozen=True)
class ControlRestorePreview:
    preview_id: str
    point_id: str
    deployment_id: str
    source_generation: int
    selected_captured_at: int
    selected_verified_at: int
    exact_request_hash: str
    created_at: int
    expires_at: int


@dataclass(frozen=True)
class ControlReconstructResult:
    scanned_manifests: int
    imported_points: list[str]
    skipped_points: list[str]


def compute_control_restore_hash(
    *,
    deployment_id: str,
    point_id: str,
    source_generation: int,
    preview_id: str,
) -> str:
    raw = canonical_json_bytes(
        {
            "action": "confirm_control_restore",
            "deployment_id": deployment_id,
            "point_id": point_id,
            "source_generation": source_generation,
            "preview_id": preview_id,
        }
    )
    return hashlib.sha256(raw).hexdigest()


def _backup_sqlite(src_path: Path, dst_path: Path) -> str:
    src = _open_readonly_sqlite(src_path)
    try:
        dst = sqlite3.connect(dst_path)
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()
    snap = _open_readonly_sqlite(dst_path)
    try:
        return _fingerprint_database(snap)
    finally:
        snap.close()


class AdminControlRecoveryService:
    """Separate Admin control-plane backup and independent recovery mode service (H05.6)."""

    def __init__(
        self,
        *,
        admin_recovery_engine: Engine,
        backup_engine: ChunkedAeadBackupEngine,
        bootstrap_authority_path: Path,
        control_root: Path,
        scratch_root: Path,
        deployment_id: str,
        release_ref: str,
        admin_schema_revision: str,
        inventory_schema_revision: str,
        application_directory: Path,
        clock: Callable[[], int],
        retention_points: int = DEFAULT_RETENTION_POINTS,
        retention_window_ms: int = DEFAULT_RETENTION_WINDOW_MS,
    ):
        self.admin_recovery_engine = admin_recovery_engine
        self.backup_engine = backup_engine
        self.bootstrap_authority_path = bootstrap_authority_path
        self.control_root = control_root
        self.scratch_root = scratch_root
        self.deployment_id = deployment_id
        self.release_ref = release_ref
        self.admin_schema_revision = admin_schema_revision
        self.inventory_schema_revision = inventory_schema_revision
        self.application_directory = application_directory
        self.clock = clock
        self.retention_points = max(1, retention_points)
        self.retention_window_ms = retention_window_ms
        self._op_lock = threading.Lock()
        self._last_wrapped_dek_b64: str | None = None
        self._last_wrapped_key_ref: str | None = None
        self._previews: dict[str, ControlRestorePreview] = {}
        self._consumed_previews: set[str] = set()

    def _load_pinned_authority(self, conn) -> BootstrapRecoveryAuthority:
        meta = (
            conn.execute(
                text(
                    "SELECT deployment_id, recovery_authority_ref FROM admin_recovery_meta WHERE id = 1"
                )
            )
            .mappings()
            .one()
        )
        if meta["deployment_id"] != self.deployment_id:
            raise AdminRecoveryDenied("admin_recovery_meta deployment_id mismatch.")
        authority, _ = load_bootstrap_authority(
            self.bootstrap_authority_path,
            expected_authority_ref=str(meta["recovery_authority_ref"]),
        )
        if authority.deployment_id != self.deployment_id:
            raise AdminRecoveryDenied("Bootstrap recovery authority deployment_id mismatch.")
        return authority

    def _verify_recovery_actor(self, conn, actor: AdminRecoveryAuthority) -> None:
        if actor.deployment_id != self.deployment_id:
            raise AdminRecoveryDenied("AdminRecoveryAuthority deployment_id mismatch.")
        now = self.clock()
        if now - actor.step_up_at > STEP_UP_TTL_MS or actor.step_up_at > now:
            raise AdminRecoveryDenied("Admin recovery MFA step-up has expired.")
        authority = self._load_pinned_authority(conn)
        authority.require_principal(actor.bootstrap_principal_ref)

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
                "INSERT INTO control_recovery_audit "
                "(audit_id, operation_id, actor_ref, action, recorded_at, safe_facts_json) "
                "VALUES (:aid, :op_id, :actor, :action, :now, :facts)"
            ),
            {
                "aid": str(uuid4()),
                "op_id": operation_id,
                "actor": actor_ref,
                "action": action,
                "now": now,
                "facts": json.dumps(facts, sort_keys=True, separators=(",", ":")),
            },
        )

    def _active_control_paths(self, conn) -> tuple[Path, Path, Path, int, str]:
        meta = (
            conn.execute(
                text(
                    "SELECT active_admin_resource_ref, source_generation, encryption_key_ref "
                    "FROM admin_recovery_meta WHERE id = 1"
                )
            )
            .mappings()
            .one()
        )
        active_ref = str(meta["active_admin_resource_ref"])
        incarnation_dir = (self.control_root / active_ref).resolve()
        try:
            incarnation_dir.relative_to(self.control_root.resolve())
        except ValueError as error:
            raise AdminRecoveryDenied("active_admin_resource_ref escapes control_root.") from error
        admin_db = incarnation_dir / "admin.sqlite"
        inv_db = incarnation_dir / "host_inventory.sqlite"
        kms_key = db_ref_to_kms_ref(str(meta["encryption_key_ref"]))
        return incarnation_dir, admin_db, inv_db, int(meta["source_generation"]), kms_key

    def detect_admin_mode(self) -> AdminStartupMode:
        """Detect whether main admin.sqlite is healthy without requiring it to start recovery."""
        with self.admin_recovery_engine.connect() as conn:
            meta = (
                conn.execute(
                    text("SELECT active_admin_resource_ref FROM admin_recovery_meta WHERE id = 1")
                )
                .mappings()
                .one()
            )
            active_ref = str(meta["active_admin_resource_ref"])
        incarnation_dir = (self.control_root / active_ref).resolve()
        admin_db = incarnation_dir / "admin.sqlite"
        try:
            incarnation_dir.relative_to(self.control_root.resolve())
            raw_conn = _open_readonly_sqlite(admin_db)
            raw_conn.close()
            eng = create_sqlite_engine(admin_db)
            try:
                with eng.connect() as c:
                    validate_schema(
                        c, HostedStore.ADMIN, application_directory=self.application_directory
                    )
            finally:
                eng.dispose()
        except ValueError, WorkspaceStateUnreadable, HostedSchemaError, Exception:
            return AdminStartupMode(
                mode="recovery",
                reason="admin_database_unreadable",
                active_admin_resource_ref=active_ref,
            )
        return AdminStartupMode(
            mode="normal",
            reason=None,
            active_admin_resource_ref=active_ref,
        )

    def _outcome_from_row(self, row) -> OperationOutcome[AdminRecoveryResult]:
        stored_cmd = AdminRecoveryCommand.model_validate_json(row["request_json"])
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
            AdminRecoveryResult.model_validate_json(row["result_json"])
            if row["result_json"] is not None
            else None
        )
        action_required = (
            "check_original_result"
            if state in {OperationState.UNKNOWN, OperationState.NEEDS_ATTENTION}
            else None
        )
        return OperationOutcome[AdminRecoveryResult](
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
    ) -> OperationOutcome[AdminRecoveryResult] | None:
        row = (
            conn.execute(
                text(
                    "SELECT operation_id, request_hash, request_json, state, result_json, "
                    "error_code, updated_at, revision "
                    "FROM control_recovery_operations "
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

    def execute(
        self,
        actor: AdminRecoveryAuthority | ServiceAuthority,
        command: AdminRecoveryCommand,
    ) -> OperationOutcome[AdminRecoveryResult]:
        require_invocation(actor, command)
        payload = command.intent.payload
        if isinstance(payload, CaptureControl):
            return self._execute_capture_control(actor, command)
        if isinstance(payload, PreviewControlRestore):
            assert isinstance(actor, AdminRecoveryAuthority)
            preview = self.preview_control_restore(actor, point_id=payload.point_id)
            return OperationOutcome[AdminRecoveryResult](
                operation=command.reference(),
                state=OperationState.SUCCEEDED,
                revision=1,
                observed_at=preview.created_at,
                result=AdminRecoveryResult(
                    point_id=preview.point_id,
                    phase="preview",
                    receipt_ref=f"preview:{preview.preview_id}",
                ),
            )
        if isinstance(payload, ConfirmControlRestore):
            assert isinstance(actor, AdminRecoveryAuthority)
            return self.confirm_control_restore(
                actor,
                point_id=payload.point_id,
                preview_id=payload.preview_id,
                idempotency_key=command.idempotency_key,
                operation_id=command.operation_id,
                command=command,
            )
        if isinstance(payload, ReconcileCheckpoint):
            return OperationOutcome[AdminRecoveryResult](
                operation=command.reference(),
                state=OperationState.SUCCEEDED,
                revision=1,
                observed_at=self.clock(),
                result=AdminRecoveryResult(
                    point_id=payload.capture_operation_id,
                    phase="reconciled",
                    receipt_ref=f"op:{command.operation_id}",
                ),
            )
        raise AdminRecoveryDenied("Unsupported control recovery action.")

    def _execute_capture_control(
        self,
        actor: ServiceAuthority,
        command: AdminRecoveryCommand,
    ) -> OperationOutcome[AdminRecoveryResult]:
        if not self._op_lock.acquire(blocking=False):
            raise SemanticConflict()
        try:
            now = self.clock()
            with immediate_transaction(self.admin_recovery_engine) as conn:
                existing = self._lookup_idempotent(
                    conn,
                    kind="backup",
                    idempotency_key=command.idempotency_key,
                    request_hash=command.request_hash,
                )
                if existing is not None:
                    return existing
                _, admin_db, inv_db, source_gen, kms_key = self._active_control_paths(conn)
                op_id = command.operation_id
                conn.execute(
                    text(
                        "INSERT INTO control_recovery_operations ("
                        "operation_id, kind, idempotency_key, request_hash, request_json, "
                        "actor_kind, actor_ref, authorization_ref, authorized_at, "
                        "authorization_expires_at, source_generation, state, result_json, "
                        "error_code, created_at, updated_at, revision"
                        ") VALUES ("
                        ":op_id, 'backup', :key, :hash, :req_json, 'system', :actor, "
                        "NULL, NULL, NULL, :src_gen, 'running', NULL, NULL, :now, :now, 1)"
                    ),
                    {
                        "op_id": op_id,
                        "key": command.idempotency_key,
                        "hash": command.request_hash,
                        "req_json": command.model_dump_json(),
                        "actor": f"service:{actor.service}",
                        "src_gen": source_gen,
                        "now": now,
                    },
                )

            point_id = str(uuid4())
            stage_dir = self.scratch_root / f"control-capture-{op_id}"
            stage_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                staged_admin = stage_dir / "admin.sqlite"
                staged_inv = stage_dir / "host_inventory.sqlite"
                admin_fp = _backup_sqlite(admin_db, staged_admin)
                inv_fp = _backup_sqlite(inv_db, staged_inv)
                captured_at = self.clock()
                context = EnvelopeContext(
                    deployment_id=self.deployment_id,
                    scope_kind="control",
                    operator_id=None,
                    workspace_id=None,
                    point_id=point_id,
                    schema_revisions={
                        "admin": self.admin_schema_revision,
                        "host_inventory": self.inventory_schema_revision,
                    },
                    key_ref=kms_key,
                )
                backup_result = self.backup_engine.create_point(
                    context=context,
                    captured_at=captured_at,
                    business_revision=admin_fp,
                    files_generation=inv_fp,
                    source_generation=source_gen,
                    release_ref=self.release_ref,
                    databases=[
                        DatabaseInput("admin.sqlite", staged_admin),
                        DatabaseInput("host_inventory.sqlite", staged_inv),
                    ],
                    existing_wrapped_dek_b64=self._last_wrapped_dek_b64,
                    existing_key_ref=self._last_wrapped_key_ref,
                    full_readback=True,
                )
                self._last_wrapped_dek_b64 = backup_result.wrapped_dek_b64
                self._last_wrapped_key_ref = backup_result.key_ref
            except Exception as error:
                err_code = (
                    error.code
                    if isinstance(error, HostedRecoveryError)
                    else "control_backup_failed"
                )
                failed_at = self.clock()
                with immediate_transaction(self.admin_recovery_engine) as conn:
                    conn.execute(
                        text(
                            "UPDATE control_backup_state SET protection_state = 'unavailable', "
                            "dirty_since = COALESCE(dirty_since, :now), last_checked_at = :now, "
                            "last_attempt_at = :now, consecutive_failures = consecutive_failures + 1, "
                            "last_error_code = :err, revision = revision + 1 WHERE id = 1"
                        ),
                        {"now": failed_at, "err": err_code},
                    )
                    conn.execute(
                        text(
                            "UPDATE control_recovery_operations SET state = 'failed', "
                            "error_code = :err, updated_at = :now, revision = revision + 1 "
                            "WHERE operation_id = :op_id"
                        ),
                        {"err": err_code, "now": failed_at, "op_id": op_id},
                    )
                return OperationOutcome[AdminRecoveryResult](
                    operation=command.reference(),
                    state=OperationState.FAILED,
                    revision=2,
                    observed_at=failed_at,
                    result=None,
                    error_code=err_code,
                )
            finally:
                shutil.rmtree(stage_dir, ignore_errors=True)

            verified_at = max(captured_at, self.clock())
            result = AdminRecoveryResult(
                point_id=point_id, phase="captured", receipt_ref=f"op:{op_id}"
            )
            with immediate_transaction(self.admin_recovery_engine) as conn:
                conn.execute(
                    text(
                        "INSERT INTO control_recovery_points ("
                        "point_id, operation_id, manifest_ref, manifest_sha256, manifest_format, "
                        "captured_at, verified_at, retain_until, key_ref, stored_bytes, state, "
                        "last_checked_at, revision"
                        ") VALUES ("
                        ":pid, :op_id, :mref, :msha, :mfmt, :cap, :ver, :ret, :kref, :sbytes, "
                        "'verified', :ver, 1)"
                    ),
                    {
                        "pid": point_id,
                        "op_id": op_id,
                        "mref": manifest_ref_for_point(point_id),
                        "msha": backup_result.manifest_sha256,
                        "mfmt": backup_result.manifest_format,
                        "cap": captured_at,
                        "ver": verified_at,
                        "ret": captured_at + self.retention_window_ms,
                        "kref": kms_ref_to_db_ref(kms_key),
                        "sbytes": backup_result.stored_bytes,
                    },
                )
                conn.execute(
                    text(
                        "UPDATE control_backup_state SET "
                        "last_point_id = :pid, "
                        "protected_admin_snapshot_ref = :afp, "
                        "protected_inventory_manifest_ref = :ifp, "
                        "protected_config_revision = :crev, "
                        "protected_source_generation = :sgen, "
                        "protection_state = 'healthy', "
                        "last_checked_at = :ver, "
                        "last_attempt_at = :ver, "
                        "dirty_since = NULL, "
                        "consecutive_failures = 0, "
                        "last_error_code = NULL, "
                        "revision = revision + 1 WHERE id = 1"
                    ),
                    {
                        "pid": point_id,
                        "afp": admin_fp,
                        "ifp": inv_fp,
                        "crev": f"rel:{self.release_ref}",
                        "sgen": source_gen,
                        "ver": verified_at,
                    },
                )
                conn.execute(
                    text(
                        "UPDATE control_recovery_operations SET state = 'succeeded', "
                        "result_json = :res, error_code = NULL, updated_at = :now, "
                        "revision = revision + 1 WHERE operation_id = :op_id"
                    ),
                    {"res": result.model_dump_json(), "now": verified_at, "op_id": op_id},
                )
                self._record_audit(
                    conn,
                    operation_id=op_id,
                    actor_ref=f"service:{actor.service}",
                    action="control_backup_verified",
                    now=verified_at,
                    facts={"point_id": point_id, "stored_bytes": backup_result.stored_bytes},
                )
            return OperationOutcome[AdminRecoveryResult](
                operation=command.reference(),
                state=OperationState.SUCCEEDED,
                revision=2,
                observed_at=verified_at,
                result=result,
            )
        finally:
            self._op_lock.release()

    def preview_control_restore(
        self,
        actor: AdminRecoveryAuthority,
        *,
        point_id: str,
    ) -> ControlRestorePreview:
        now = self.clock()
        with self.admin_recovery_engine.connect() as conn:
            self._verify_recovery_actor(conn, actor)
            point = (
                conn.execute(
                    text(
                        "SELECT point_id, state, captured_at, verified_at "
                        "FROM control_recovery_points WHERE point_id = :pid"
                    ),
                    {"pid": point_id},
                )
                .mappings()
                .first()
            )
            if point is None:
                raise AdminRecoveryNotFound("Control recovery point not found.")
            if point["state"] != "verified":
                raise AdminRecoveryDenied("Only verified control recovery points can be restored.")
            source_gen = int(
                conn.execute(
                    text("SELECT source_generation FROM admin_recovery_meta WHERE id = 1")
                ).scalar_one()
            )
        preview_id = str(uuid4())
        exact_hash = compute_control_restore_hash(
            deployment_id=self.deployment_id,
            point_id=point_id,
            source_generation=source_gen,
            preview_id=preview_id,
        )
        preview = ControlRestorePreview(
            preview_id=preview_id,
            point_id=point_id,
            deployment_id=self.deployment_id,
            source_generation=source_gen,
            selected_captured_at=int(point["captured_at"]),
            selected_verified_at=int(point["verified_at"]),
            exact_request_hash=exact_hash,
            created_at=now,
            expires_at=now + PREVIEW_TTL_MS,
        )
        self._previews[preview_id] = preview
        return preview

    def get_preview(self, preview_id: str) -> ControlRestorePreview | None:
        now = self.clock()
        preview = self._previews.get(preview_id)
        if preview is not None and preview.expires_at <= now:
            self._previews.pop(preview_id, None)
            return None
        return preview

    def confirm_control_restore(
        self,
        actor: AdminRecoveryAuthority,
        *,
        point_id: str,
        preview_id: str,
        idempotency_key: str,
        operation_id: str | None = None,
        command: AdminRecoveryCommand | None = None,
    ) -> OperationOutcome[AdminRecoveryResult]:
        """Restore main admin.sqlite + host_inventory.sqlite into a separate incarnation."""
        now = self.clock()
        op_id = operation_id or str(uuid4())
        if command is None:
            intent = CommandIntent(
                deployment_id=self.deployment_id,
                scope=DeploymentScope(),
                kind="confirm_control_restore",
                expected_revision=1,
                access_epoch=1,
                payload=ConfirmControlRestore(
                    point_id=point_id,
                    preview_id=preview_id,
                    confirmation_id=preview_id,
                ),
            )
            command = AdminRecoveryCommand(
                operation_id=op_id,
                idempotency_key=idempotency_key,
                intent=intent,
                request_hash=semantic_hash(intent),
            )

        with self.admin_recovery_engine.connect() as conn:
            self._verify_recovery_actor(conn, actor)
            existing = self._lookup_idempotent(
                conn,
                kind="restore",
                idempotency_key=idempotency_key,
                request_hash=command.request_hash,
            )
            if existing is not None:
                return existing

        preview = self.get_preview(preview_id)
        if preview is None or preview_id in self._consumed_previews:
            raise AdminRecoveryDenied(
                "Control restore preview is missing, expired, or already used."
            )
        if preview.point_id != point_id:
            raise AdminRecoveryDenied("Control restore point_id does not match preview.")
        if actor.confirmed_request_hash not in {preview.exact_request_hash, command.request_hash}:
            raise AdminRecoveryDenied("Admin recovery confirmation hash mismatch.")

        if not self._op_lock.acquire(blocking=False):
            raise SemanticConflict()
        target_dir: Path | None = None
        try:
            self._consumed_previews.add(preview_id)
            self._previews.pop(preview_id, None)
            with immediate_transaction(self.admin_recovery_engine) as conn:
                self._verify_recovery_actor(conn, actor)
                point = (
                    conn.execute(
                        text(
                            "SELECT point_id, manifest_ref, manifest_sha256, state "
                            "FROM control_recovery_points WHERE point_id = :pid"
                        ),
                        {"pid": point_id},
                    )
                    .mappings()
                    .first()
                )
                if point is None or point["state"] != "verified":
                    raise AdminRecoveryDenied("Selected control recovery point is unavailable.")
                meta = (
                    conn.execute(
                        text(
                            "SELECT active_admin_resource_ref, source_generation "
                            "FROM admin_recovery_meta WHERE id = 1"
                        )
                    )
                    .mappings()
                    .one()
                )
                prior_ref = str(meta["active_admin_resource_ref"])
                source_gen = int(meta["source_generation"])
                new_gen = source_gen + 1
                target_ref = f"admin-incarnation-{new_gen}"
                manifest_ref = str(point["manifest_ref"])
                manifest_sha = str(point["manifest_sha256"])

                conn.execute(
                    text(
                        "INSERT INTO control_recovery_operations ("
                        "operation_id, kind, idempotency_key, request_hash, request_json, "
                        "actor_kind, actor_ref, authorization_ref, authorized_at, "
                        "authorization_expires_at, source_generation, state, result_json, "
                        "error_code, created_at, updated_at, revision"
                        ") VALUES ("
                        ":op_id, 'restore', :key, :hash, :req_json, 'admin', :actor, "
                        ":auth_ref, :now, :auth_exp, :src_gen, 'running', NULL, NULL, :now, :now, 1)"
                    ),
                    {
                        "op_id": op_id,
                        "key": idempotency_key,
                        "hash": command.request_hash,
                        "req_json": command.model_dump_json(),
                        "actor": actor.bootstrap_principal_ref,
                        "auth_ref": actor.current_mfa_proof_ref,
                        "now": now,
                        "auth_exp": now + EXECUTION_AUTH_TTL_MS,
                        "src_gen": source_gen,
                    },
                )
                conn.execute(
                    text(
                        "INSERT INTO control_restore_operations ("
                        "operation_id, point_id, target_resource_ref, prior_resource_ref, "
                        "new_registry_generation, phase, validation_ref, started_at, updated_at"
                        ") VALUES ("
                        ":op_id, :pid, :target, :prior, :new_gen, 'prepared', NULL, :now, :now)"
                    ),
                    {
                        "op_id": op_id,
                        "pid": point_id,
                        "target": target_ref,
                        "prior": prior_ref,
                        "new_gen": new_gen,
                        "now": now,
                    },
                )

            target_dir = (self.control_root / target_ref).resolve()
            target_dir.relative_to(self.control_root.resolve())
            if target_dir.exists():
                raise RecoveryIntegrityError("Control restore target directory already exists.")
            target_dir.mkdir(mode=0o700, parents=False)

            self.backup_engine.restore_point(
                manifest_ref=object_key_for_manifest_ref(manifest_ref),
                expected_deployment_id=self.deployment_id,
                expected_scope_kind="control",
                expected_point_id=point_id,
                expected_manifest_sha256=manifest_sha,
                destination_dir=target_dir,
            )

            restored_admin_db = target_dir / "admin.sqlite"
            restored_inv_db = target_dir / "host_inventory.sqlite"
            # Validate schemas + integrity, advance control fences, revoke historical sessions,
            # and render historical pending/running operations inert (never replay old jobs!).
            for db_file, store in (
                (restored_admin_db, HostedStore.ADMIN),
                (restored_inv_db, HostedStore.HOST_INVENTORY),
            ):
                chk = sqlite3.connect(db_file.as_uri() + "?mode=ro", uri=True)
                try:
                    if chk.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RecoveryIntegrityError(
                            f"Restored {db_file.name} failed integrity_check."
                        )
                finally:
                    chk.close()
                eng = create_sqlite_engine(db_file)
                try:
                    with eng.connect() as c:
                        validate_schema(c, store, application_directory=self.application_directory)
                finally:
                    eng.dispose()

            reconcile_now = self.clock()
            restored_admin_engine = create_sqlite_engine(restored_admin_db)
            try:
                with immediate_transaction(restored_admin_engine) as aconn:
                    aconn.execute(
                        text(
                            "UPDATE main.control_meta SET "
                            "registry_generation = registry_generation + 1 WHERE id = 1"
                        )
                    )
                    aconn.execute(
                        text(
                            "UPDATE main.admin_sessions SET revoked_at = :now "
                            "WHERE revoked_at IS NULL"
                        ),
                        {"now": reconcile_now},
                    )
                    aconn.execute(
                        text(
                            "UPDATE main.managed_identity_sessions SET revoked_at = :now, "
                            "revision = revision + 1 WHERE revoked_at IS NULL"
                        ),
                        {"now": reconcile_now},
                    )
                    aconn.execute(
                        text(
                            "UPDATE main.operations SET state = 'unknown', "
                            "error_code = 'historical_after_control_restore', "
                            "updated_at = :now, revision = revision + 1 "
                            "WHERE state IN ('pending', 'running')"
                        ),
                        {"now": reconcile_now},
                    )
                    new_reg_gen = int(
                        aconn.execute(
                            text("SELECT registry_generation FROM main.control_meta WHERE id = 1")
                        ).scalar_one()
                    )
            finally:
                restored_admin_engine.dispose()

            switched_at = self.clock()
            result = AdminRecoveryResult(
                point_id=point_id, phase="restored", receipt_ref=f"op:{op_id}"
            )
            with immediate_transaction(self.admin_recovery_engine) as conn:
                conn.execute(
                    text(
                        "UPDATE admin_recovery_meta SET "
                        "active_admin_resource_ref = :target, "
                        "source_generation = :new_gen, revision = revision + 1 WHERE id = 1"
                    ),
                    {"target": target_ref, "new_gen": new_gen},
                )
                conn.execute(
                    text(
                        "UPDATE control_restore_operations SET phase = 'switched', "
                        "new_registry_generation = :rgen, validation_ref = :vref, "
                        "updated_at = :now WHERE operation_id = :op_id"
                    ),
                    {
                        "rgen": new_reg_gen,
                        "vref": f"integrity:{op_id}",
                        "now": switched_at,
                        "op_id": op_id,
                    },
                )
                conn.execute(
                    text(
                        "UPDATE control_recovery_operations SET state = 'succeeded', "
                        "result_json = :res, error_code = NULL, updated_at = :now, "
                        "revision = revision + 1 WHERE operation_id = :op_id"
                    ),
                    {"res": result.model_dump_json(), "now": switched_at, "op_id": op_id},
                )
                self._record_audit(
                    conn,
                    operation_id=op_id,
                    actor_ref=actor.bootstrap_principal_ref,
                    action="control_restore_switched",
                    now=switched_at,
                    facts={
                        "point_id": point_id,
                        "target_ref": target_ref,
                        "prior_ref": prior_ref,
                        "new_registry_generation": new_reg_gen,
                    },
                )
            return OperationOutcome[AdminRecoveryResult](
                operation=command.reference(),
                state=OperationState.SUCCEEDED,
                revision=2,
                observed_at=switched_at,
                result=result,
            )
        except Exception as error:
            if target_dir is not None and target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            err_code = (
                error.code if isinstance(error, HostedRecoveryError) else "control_restore_failed"
            )
            failed_at = self.clock()
            with immediate_transaction(self.admin_recovery_engine) as conn:
                conn.execute(
                    text(
                        "UPDATE control_restore_operations SET phase = 'needs_attention', "
                        "updated_at = :now WHERE operation_id = :op_id AND phase != 'switched'"
                    ),
                    {"now": failed_at, "op_id": op_id},
                )
                conn.execute(
                    text(
                        "UPDATE control_recovery_operations SET state = 'failed', "
                        "error_code = :err, updated_at = :now, revision = revision + 1 "
                        "WHERE operation_id = :op_id AND state NOT IN ('succeeded', 'failed')"
                    ),
                    {"err": err_code, "now": failed_at, "op_id": op_id},
                )
            return OperationOutcome[AdminRecoveryResult](
                operation=command.reference(),
                state=OperationState.FAILED,
                revision=2,
                observed_at=failed_at,
                result=None,
                error_code=err_code,
            )
        finally:
            self._op_lock.release()

    def accept_control_restore(
        self, actor: AdminRecoveryAuthority, *, operation_id: str
    ) -> dict[str, object]:
        now = self.clock()
        with immediate_transaction(self.admin_recovery_engine) as conn:
            self._verify_recovery_actor(conn, actor)
            row = (
                conn.execute(
                    text("SELECT * FROM control_restore_operations WHERE operation_id = :op_id"),
                    {"op_id": operation_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise AdminRecoveryNotFound("Control restore operation not found.")
            if row["phase"] not in {"switched", "accepted"}:
                raise AdminRecoveryDenied("Only a switched control restore can be accepted.")
            if row["phase"] != "accepted":
                conn.execute(
                    text(
                        "UPDATE control_restore_operations SET phase = 'accepted', "
                        "updated_at = :now WHERE operation_id = :op_id"
                    ),
                    {"now": now, "op_id": operation_id},
                )
                self._record_audit(
                    conn,
                    operation_id=operation_id,
                    actor_ref=actor.bootstrap_principal_ref,
                    action="control_restore_accepted",
                    now=now,
                    facts={"point_id": row["point_id"]},
                )
            return {"operationId": operation_id, "phase": "accepted", "updatedAt": now}

    def reconstruct_catalog(self) -> ControlReconstructResult:
        """Reconstruct verified control_recovery_points from off-host manifests (no runnable ops)."""
        manifest_keys = self.backup_engine.transport.list_objects("manifests/")
        imported: list[str] = []
        skipped: list[str] = []
        now = self.clock()
        for key in manifest_keys:
            try:
                manifest, _, _, manifest_sha = self.backup_engine.load_manifest(
                    manifest_ref=key,
                    expected_deployment_id=self.deployment_id,
                    expected_scope_kind="control",
                )
            except HostedRecoveryError:
                skipped.append(key)
                continue

            with immediate_transaction(self.admin_recovery_engine) as conn:
                exists = conn.execute(
                    text("SELECT 1 FROM control_recovery_points WHERE point_id = :pid"),
                    {"pid": manifest.point_id},
                ).scalar_one_or_none()
                if exists is not None:
                    skipped.append(manifest.point_id)
                    continue
                op_id = str(uuid4())
                result = AdminRecoveryResult(
                    point_id=manifest.point_id,
                    phase="reconciled",
                    receipt_ref=f"reconstruct:{op_id}",
                )
                conn.execute(
                    text(
                        "INSERT INTO control_recovery_operations ("
                        "operation_id, kind, idempotency_key, request_hash, request_json, "
                        "actor_kind, actor_ref, authorization_ref, authorized_at, "
                        "authorization_expires_at, source_generation, state, result_json, "
                        "error_code, created_at, updated_at, revision"
                        ") VALUES ("
                        ":op_id, 'backup', :key, :hash, '{}', 'system', 'service:admin_recovery', "
                        "NULL, NULL, NULL, :sgen, 'succeeded', :res, NULL, :now, :now, 1)"
                    ),
                    {
                        "op_id": op_id,
                        "key": f"reconstruct-{manifest.point_id}",
                        "hash": manifest_sha,
                        "sgen": manifest.source_generation,
                        "res": result.model_dump_json(),
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
                        "INSERT INTO control_recovery_points ("
                        "point_id, operation_id, manifest_ref, manifest_sha256, manifest_format, "
                        "captured_at, verified_at, retain_until, key_ref, stored_bytes, state, "
                        "last_checked_at, revision"
                        ") VALUES ("
                        ":pid, :op_id, :mref, :msha, :mfmt, :cap, :ver, :ret, :kref, :sbytes, "
                        "'verified', :ver, 1)"
                    ),
                    {
                        "pid": manifest.point_id,
                        "op_id": op_id,
                        "mref": manifest_ref_for_point(manifest.point_id),
                        "msha": manifest_sha,
                        "mfmt": manifest.format_version,
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
                    actor_ref="service:admin_recovery",
                    action="control_catalog_reconstructed",
                    now=now,
                    facts={"point_id": manifest.point_id, "manifest_sha256": manifest_sha},
                )
                imported.append(manifest.point_id)
        return ControlReconstructResult(
            scanned_manifests=len(manifest_keys),
            imported_points=imported,
            skipped_points=skipped,
        )

    def observe(
        self, actor: AdminRecoveryAuthority, query: ObservationQuery
    ) -> ObservationPage[AdminRecoveryObservation]:
        if query.scope.kind != "deployment" or query.deployment_id != self.deployment_id:
            raise AdminRecoveryDenied("Admin recovery observation requires deployment scope.")
        limit = min(query.limit, 50)
        with self.admin_recovery_engine.connect() as conn:
            self._verify_recovery_actor(conn, actor)
            total = int(
                conn.execute(
                    text("SELECT COUNT(*) FROM control_recovery_points WHERE state = 'verified'")
                ).scalar_one()
            )
            bs_rev = int(
                conn.execute(
                    text("SELECT revision FROM control_backup_state WHERE id = 1")
                ).scalar_one()
            )
            rows = (
                conn.execute(
                    text(
                        "SELECT point_id, revision, captured_at, verified_at, manifest_sha256 "
                        "FROM control_recovery_points WHERE state = 'verified' "
                        "ORDER BY captured_at DESC, point_id DESC LIMIT :limit"
                    ),
                    {"limit": limit},
                )
                .mappings()
                .all()
            )
        items = tuple(
            AdminRecoveryObservation(
                resource_id=row["point_id"],
                revision=int(row["revision"]),
                freshness=Freshness(
                    state=FreshnessState.KNOWN,
                    as_of=int(row["verified_at"]),
                    source_revision=f"control_recovery:{row['revision']}",
                ),
                captured_at=int(row["captured_at"]),
                verified_at=int(row["verified_at"]),
                manifest_sha256=row["manifest_sha256"],
                eligible=True,
            )
            for row in rows
        )
        return ObservationPage[AdminRecoveryObservation](
            items=items,
            matching_total=total,
            freshness=Freshness(
                state=FreshnessState.KNOWN,
                as_of=self.clock(),
                source_revision=f"control_backup_state:{bs_rev}",
            ),
            continuation=None,
        )

    def original(
        self,
        actor: AdminRecoveryAuthority | ServiceAuthority,
        reference: OperationReference,
    ) -> OperationOutcome[AdminRecoveryResult] | None:
        with self.admin_recovery_engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT operation_id, request_hash, request_json, state, result_json, "
                        "error_code, updated_at, revision "
                        "FROM control_recovery_operations WHERE operation_id = :op_id"
                    ),
                    {"op_id": reference.operation_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return self._outcome_from_row(row)


def reconstruct_on_clean_host(
    *,
    admin_recovery_db_path: Path,
    bootstrap_authority_path: Path,
    control_root: Path,
    scratch_root: Path,
    backup_engine: ChunkedAeadBackupEngine,
    kms_key_ref: str,
    release_ref: str,
    admin_schema_revision: str,
    inventory_schema_revision: str,
    application_directory: Path,
    clock: Callable[[], int],
) -> tuple[AdminControlRecoveryService, ControlReconstructResult, str]:
    """Initialize a fresh admin-recovery.sqlite incarnation and reconstruct verified points (whole-host loss)."""
    authority, authority_ref = load_bootstrap_authority(bootstrap_authority_path)
    validate_kms_key_ref(kms_key_ref)
    admin_recovery_db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    initialize_store(
        HostedStore.ADMIN_RECOVERY,
        admin_recovery_db_path,
        application_directory=application_directory,
    )
    engine = create_sqlite_engine(admin_recovery_db_path)
    incarnation_id = str(uuid4())
    now = clock()
    with immediate_transaction(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO admin_recovery_meta ("
                "id, deployment_id, incarnation_id, recovery_authority_ref, source_generation, "
                "active_admin_resource_ref, encryption_key_ref, namespace_prefix, created_at, revision"
                ") VALUES ("
                "1, :dep, :inc, :aref, 1, 'admin-incarnation-1', :kref, :prefix, :now, 1)"
            ),
            {
                "dep": authority.deployment_id,
                "inc": incarnation_id,
                "aref": authority_ref,
                "kref": kms_ref_to_db_ref(kms_key_ref),
                "prefix": f"deployments/{authority.deployment_id}/control/",
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO control_backup_state ("
                "id, last_point_id, protected_admin_snapshot_ref, "
                "protected_inventory_manifest_ref, protected_config_revision, "
                "protected_source_generation, protection_state, last_checked_at, "
                "last_attempt_at, dirty_since, consecutive_failures, last_error_code, revision"
                ") VALUES (1, NULL, NULL, NULL, NULL, NULL, 'unknown', :now, NULL, NULL, 0, NULL, 1)"
            ),
            {"now": now},
        )

    service = AdminControlRecoveryService(
        admin_recovery_engine=engine,
        backup_engine=backup_engine,
        bootstrap_authority_path=bootstrap_authority_path,
        control_root=control_root,
        scratch_root=scratch_root,
        deployment_id=authority.deployment_id,
        release_ref=release_ref,
        admin_schema_revision=admin_schema_revision,
        inventory_schema_revision=inventory_schema_revision,
        application_directory=application_directory,
        clock=clock,
    )
    reconstructed = service.reconstruct_catalog()
    return service, reconstructed, incarnation_id


def build_host_loss_cli_parser() -> argparse.ArgumentParser:
    """Restricted platform control-plane host-loss recovery CLI (never customer workspace restore)."""
    parser = argparse.ArgumentParser(
        description="Restricted Admin control-plane host-loss reconstruction CLI (H05.6)."
    )
    parser.add_argument("--admin-recovery-db", type=Path, required=True)
    parser.add_argument("--bootstrap-authority", type=Path, required=True)
    parser.add_argument("--control-root", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--backup-proxy-socket", type=Path, required=True)
    parser.add_argument("--backup-proxy-uid", type=int, required=True)
    parser.add_argument("--kms-key-ref", required=True)
    parser.add_argument("--release-ref", default="rel-hosted-mvp")
    parser.add_argument("--admin-schema-revision", default="admin_0001_initial")
    parser.add_argument("--inventory-schema-revision", default="host_inventory_0001_initial")
    return parser

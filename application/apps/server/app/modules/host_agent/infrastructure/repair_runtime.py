"""Host Agent clean-runtime repair orchestrator (H05.5 / D1).

Replaces ONLY the failed Operator container from a qualified compatible release image
while retaining operator/workspace IDs, business trees, access/recovery stores, and
key references. Never initializes an empty business DB or runs synthetic seeding;
revokes all prior sessions and boots the replacement runtime in minimal recovery mode.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
import json
import os
from pathlib import Path

from sqlalchemy import Engine, text

from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.hosted_admin.application.pilot_contracts import AdminResult
from app.modules.hosted_admin.infrastructure.provisioning_admission import _append_event
from app.modules.workspace.infrastructure.hosted_recovery import (
    WorkspaceStateUnreadable,
    probe_live_workspace_state,
)
from app.platform.hosted_schema import HostedSchemaError, validate_schema
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction


@dataclass(frozen=True)
class RepairPaths:
    workspace_root: Path
    control_root: Path
    scratch_root: Path


@dataclass(frozen=True)
class RepairRuntimeIntent:
    operation_id: str
    operation_state: str
    operator_id: str
    workspace_id: str
    deployment_id: str
    binding_id: str
    release_id: str
    artifact_digest: str
    expected_resource_generation: int
    access_epoch: int
    operator_revision: int


@dataclass(frozen=True)
class RepairRuntimeResult:
    operation_id: str
    operator_id: str
    workspace_id: str
    binding_id: str
    release_id: str
    state: str
    recovery_mode_required: bool
    business_db_healthy: bool | None = None
    prior_sessions_revoked: int = 0
    container_ref: str | None = None
    error_code: str | None = None


StopContainerHook = Callable[[RepairRuntimeIntent, RepairPaths], None]
ReplaceContainerHook = Callable[[RepairRuntimeIntent, RepairPaths, bool], str]


class CleanRuntimeRepairError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class CleanRuntimeRepairer:
    """Executes admitted Admin repair_runtime operations safely without touching customer data."""

    def __init__(
        self,
        *,
        admin_engine: Engine,
        paths_for: Callable[[RepairRuntimeIntent], RepairPaths],
        stop_container: StopContainerHook,
        replace_container: ReplaceContainerHook,
        application_directory: Path,
        clock: Callable[[], int],
        inventory=None,
    ):
        self.admin_engine = admin_engine
        self.paths_for = paths_for
        self.stop_container = stop_container
        self.replace_container = replace_container
        self.application_directory = application_directory
        self.clock = clock
        self.inventory = inventory

    def load_intent(self, operation_id: str) -> RepairRuntimeIntent:
        with self.admin_engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT o.operation_id, o.kind, o.state, o.operator_id, o.request_json, "
                        "o.access_epoch, op.workspace_id, op.revision AS op_revision, "
                        "op.setup_state, op.access_epoch AS op_access_epoch, cm.deployment_id "
                        "FROM main.operations o "
                        "JOIN main.operators op ON op.operator_id = o.operator_id "
                        "JOIN main.control_meta cm ON cm.id = 1 "
                        "WHERE o.operation_id = :op_id"
                    ),
                    {"op_id": operation_id},
                )
                .mappings()
                .one_or_none()
            )
            if (
                row is None
                or row["kind"] != "repair_runtime"
                or row["setup_state"] == "retired"
                or int(row["access_epoch"]) != int(row["op_access_epoch"])
            ):
                raise HostAgentDenied()
            req = json.loads(row["request_json"])
            payload = req.get("payload") or {}
            release_id = payload.get("release_id")
            binding_id = payload.get("binding_id")
            expected_gen = payload.get("expected_resource_generation")
            if not release_id or not binding_id or not isinstance(expected_gen, int):
                raise HostAgentDenied()
            rel = (
                conn.execute(
                    text(
                        "SELECT artifact_digest FROM main.qualified_releases "
                        "WHERE release_id = :rel_id AND component = 'operator' "
                        "AND state = 'qualified'"
                    ),
                    {"rel_id": release_id},
                )
                .mappings()
                .one_or_none()
            )
            if rel is None:
                raise HostAgentDenied()
            return RepairRuntimeIntent(
                operation_id=row["operation_id"],
                operation_state=row["state"],
                operator_id=row["operator_id"],
                workspace_id=row["workspace_id"],
                deployment_id=row["deployment_id"],
                binding_id=binding_id,
                release_id=release_id,
                artifact_digest=rel["artifact_digest"],
                expected_resource_generation=expected_gen,
                access_epoch=int(row["access_epoch"]),
                operator_revision=int(row["op_revision"]),
            )

    def _mark_running(self, operation_id: str) -> None:
        now = self.clock()
        with immediate_transaction(self.admin_engine) as conn:
            row = (
                conn.execute(
                    text("SELECT kind, state FROM main.operations WHERE operation_id = :op_id"),
                    {"op_id": operation_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["kind"] != "repair_runtime":
                raise HostAgentDenied()
            if row["state"] not in {"pending", "running", "needs_attention", "unknown"}:
                raise HostAgentDenied()
            conn.execute(
                text(
                    "UPDATE main.operations SET state = 'running', error_code = NULL, "
                    "updated_at = :now, revision = revision + 1 WHERE operation_id = :op_id"
                ),
                {"now": now, "op_id": operation_id},
            )
            _append_event(
                conn,
                operation_id=operation_id,
                event_code="repair_runtime_started",
                safe_summary="Host Agent started clean runtime replacement.",
                recorded_at=now,
            )

    def _mark_succeeded(self, intent: RepairRuntimeIntent, *, container_ref: str) -> None:
        now = self.clock()
        result = AdminResult(
            resource_id=intent.operator_id,
            revision=intent.operator_revision,
            state="ready",
        )
        with immediate_transaction(self.admin_engine) as conn:
            conn.execute(
                text(
                    "UPDATE main.operations SET state = 'succeeded', "
                    "effect_reference = :cref, result_json = :res, error_code = NULL, "
                    "updated_at = :now, revision = revision + 1 "
                    "WHERE operation_id = :op_id AND kind = 'repair_runtime'"
                ),
                {
                    "cref": container_ref,
                    "res": result.model_dump_json(),
                    "now": now,
                    "op_id": intent.operation_id,
                },
            )
            _append_event(
                conn,
                operation_id=intent.operation_id,
                event_code="repair_runtime_succeeded",
                safe_summary=(
                    "Replaced operator container in minimal recovery mode; IDs, data, "
                    "and stores preserved, prior sessions revoked."
                ),
                recorded_at=now,
            )

    def _mark_needs_attention(self, operation_id: str, *, error_code: str) -> None:
        now = self.clock()
        with immediate_transaction(self.admin_engine) as conn:
            conn.execute(
                text(
                    "UPDATE main.operations SET state = 'needs_attention', "
                    "error_code = :err, updated_at = :now, revision = revision + 1 "
                    "WHERE operation_id = :op_id AND kind = 'repair_runtime' "
                    "AND state NOT IN ('succeeded', 'failed')"
                ),
                {"err": error_code, "now": now, "op_id": operation_id},
            )
            _append_event(
                conn,
                operation_id=operation_id,
                event_code="repair_runtime_needs_attention",
                safe_summary=f"Clean runtime repair stopped safely: {error_code}.",
                recorded_at=now,
            )

    def _validate_retained_stores_and_revoke_sessions(
        self, intent: RepairRuntimeIntent, paths: RepairPaths
    ) -> tuple[str, int]:
        access_path = paths.control_root / "access.sqlite"
        recovery_path = paths.control_root / "recovery.sqlite"
        if not access_path.is_file() or access_path.is_symlink():
            raise CleanRuntimeRepairError("access_store_invalid", "Retained access.sqlite missing.")
        if not recovery_path.is_file() or recovery_path.is_symlink():
            raise CleanRuntimeRepairError(
                "recovery_store_invalid", "Retained recovery.sqlite missing."
            )

        rec_engine = create_sqlite_engine(recovery_path)
        try:
            with rec_engine.connect() as conn:
                try:
                    validate_schema(
                        conn,
                        HostedStore.RECOVERY,
                        application_directory=self.application_directory,
                    )
                except HostedSchemaError as error:
                    raise CleanRuntimeRepairError(
                        "recovery_store_invalid", "Retained recovery.sqlite schema invalid."
                    ) from error
                rec_meta = (
                    conn.execute(
                        text(
                            "SELECT workspace_id, active_business_ref, encryption_key_ref "
                            "FROM recovery_meta WHERE id = 1"
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if rec_meta is None or rec_meta["workspace_id"] != intent.workspace_id:
                    raise CleanRuntimeRepairError(
                        "recovery_store_mismatch", "Retained recovery_meta workspace mismatch."
                    )
                active_business_ref = str(rec_meta["active_business_ref"])
        finally:
            rec_engine.dispose()

        access_stat = access_path.stat()
        acc_engine = create_sqlite_engine(access_path)
        try:
            with immediate_transaction(acc_engine) as conn:
                try:
                    validate_schema(
                        conn,
                        HostedStore.HOSTED_ACCESS,
                        application_directory=self.application_directory,
                    )
                except HostedSchemaError as error:
                    raise CleanRuntimeRepairError(
                        "access_store_invalid", "Retained access.sqlite schema invalid."
                    ) from error
                acc_meta = (
                    conn.execute(
                        text(
                            "SELECT deployment_id, operator_id, workspace_id, binding_id, "
                            "resource_generation, access_epoch, not_before "
                            "FROM access_meta WHERE id = 1"
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    acc_meta is None
                    or acc_meta["deployment_id"] != intent.deployment_id
                    or acc_meta["operator_id"] != intent.operator_id
                    or acc_meta["workspace_id"] != intent.workspace_id
                    or acc_meta["binding_id"] != intent.binding_id
                    or int(acc_meta["resource_generation"]) != intent.expected_resource_generation
                    or int(acc_meta["access_epoch"]) != intent.access_epoch
                ):
                    raise CleanRuntimeRepairError(
                        "access_store_mismatch", "Retained access_meta identity mismatch."
                    )
                now = self.clock()
                revoked = conn.execute(
                    text("UPDATE access_sessions SET revoked_at = :now WHERE revoked_at IS NULL"),
                    {"now": now},
                ).rowcount
                conn.execute(
                    text(
                        "UPDATE access_meta SET "
                        "session_generation = session_generation + 1, "
                        "not_before = MAX(not_before, :nb), "
                        "revision = revision + 1 "
                        "WHERE id = 1"
                    ),
                    {"nb": now + 1},
                )
            with acc_engine.connect() as conn:
                conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        finally:
            acc_engine.dispose()
        if os.geteuid() == 0:
            for suffix in ("", "-wal", "-shm", "-journal"):
                candidate = Path(f"{access_path}{suffix}")
                if candidate.exists():
                    os.chown(candidate, access_stat.st_uid, access_stat.st_gid)

        return active_business_ref, int(revoked or 0)

    def _update_inventory_binding(self, intent: RepairRuntimeIntent, *, container_ref: str) -> None:
        if self.inventory is None:
            return
        with self.inventory.transaction(write=True) as conn:
            conn.execute(
                text(
                    "UPDATE resource_bindings SET container_ref = :cref, "
                    "state = 'stopped', updated_at = :now, revision = revision + 1 "
                    "WHERE binding_id = :bid AND resource_generation = :gen"
                ),
                {
                    "cref": container_ref,
                    "now": self.clock(),
                    "bid": intent.binding_id,
                    "gen": intent.expected_resource_generation,
                },
            )

    def execute(self, operation_id: str) -> RepairRuntimeResult:
        """Execute an admitted repair_runtime operation idempotently and fail-closed."""
        lock_ctx = self.inventory.exclusive() if self.inventory is not None else nullcontext()
        with lock_ctx:
            intent = self.load_intent(operation_id)
            if intent.operation_state == "succeeded":
                return RepairRuntimeResult(
                    operation_id=intent.operation_id,
                    operator_id=intent.operator_id,
                    workspace_id=intent.workspace_id,
                    binding_id=intent.binding_id,
                    release_id=intent.release_id,
                    state="succeeded",
                    recovery_mode_required=True,
                )

            self._mark_running(operation_id)
            paths = self.paths_for(intent)
            try:
                # 1. Stop and fence the former runtime before touching any state.
                self.stop_container(intent, paths)

                # 2. Validate retained access/recovery stores and revoke all old sessions.
                active_business_ref, revoked_count = (
                    self._validate_retained_stores_and_revoke_sessions(intent, paths)
                )

                # 3. Inspect business DB read-only (NEVER initialize or seed an empty DB).
                incarnation_dir = (paths.workspace_root / active_business_ref).resolve()
                business_db_healthy = True
                try:
                    incarnation_dir.relative_to(paths.workspace_root.resolve())
                    probe_live_workspace_state(
                        incarnation_dir / "property-management.sqlite", incarnation_dir
                    )
                except ValueError, WorkspaceStateUnreadable:
                    business_db_healthy = False

                # 4. Always start replacement container in minimal recovery mode (recovery.md:137).
                container_ref = self.replace_container(intent, paths, True)
                self._update_inventory_binding(intent, container_ref=container_ref)
                self._mark_succeeded(intent, container_ref=container_ref)
                return RepairRuntimeResult(
                    operation_id=intent.operation_id,
                    operator_id=intent.operator_id,
                    workspace_id=intent.workspace_id,
                    binding_id=intent.binding_id,
                    release_id=intent.release_id,
                    state="succeeded",
                    recovery_mode_required=True,
                    business_db_healthy=business_db_healthy,
                    prior_sessions_revoked=revoked_count,
                    container_ref=container_ref,
                )
            except CleanRuntimeRepairError as error:
                self._mark_needs_attention(operation_id, error_code=error.code)
                return RepairRuntimeResult(
                    operation_id=intent.operation_id,
                    operator_id=intent.operator_id,
                    workspace_id=intent.workspace_id,
                    binding_id=intent.binding_id,
                    release_id=intent.release_id,
                    state="needs_attention",
                    recovery_mode_required=True,
                    error_code=error.code,
                )
            except Exception:
                self._mark_needs_attention(operation_id, error_code="repair_runtime_failed")
                return RepairRuntimeResult(
                    operation_id=intent.operation_id,
                    operator_id=intent.operator_id,
                    workspace_id=intent.workspace_id,
                    binding_id=intent.binding_id,
                    release_id=intent.release_id,
                    state="needs_attention",
                    recovery_mode_required=True,
                    error_code="repair_runtime_failed",
                )

"""Internal jittered nightly backup schedulers & hourly overdue watchdogs (H06.3 / D6).

Runs as an in-process asyncio background task inside Operator (`operator_entry.py`) and
Admin (`shared_identity_entry.py`), keeping backups 100% single-writer and Admin-outage
independent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import hashlib
import logging
from uuid import uuid4

from sqlalchemy import text

from app.modules.hosted_admin.application.recovery_contracts import (
    AdminRecoveryCommand,
    CaptureControl,
)
from app.modules.workspace.application.recovery_contracts import (
    Capture,
    WorkspaceRecoveryCommand,
)
from app.platform.hosted_contracts.authority import ServiceAuthority
from app.platform.hosted_contracts.operations import CommandIntent
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import DeploymentScope, WorkspaceScope

logger = logging.getLogger("epm.hosted_recovery.scheduler")

NIGHTLY_INTERVAL_MS = 24 * 60 * 60 * 1000
WATCHDOG_INTERVAL_SECONDS = 3600
DEFAULT_JITTER_WINDOW_SECONDS = 3600


def deterministic_nightly_jitter_seconds(
    scope_id: str, *, window_seconds: int = DEFAULT_JITTER_WINDOW_SECONDS
) -> int:
    """Deterministic per-workspace/deployment jitter in [0, window_seconds)."""
    if window_seconds <= 0:
        return 0
    digest = hashlib.sha256(scope_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % window_seconds


def _is_nightly_slot_due(
    *, now: int, last_protected_at: int | None, interval_ms: int, jitter_ms: int
) -> bool:
    """Anchor nightly capture to a deterministic UTC slot (day_start + jitter) with zero drift."""
    if last_protected_at is None:
        return True
    day_start_ms = (now // interval_ms) * interval_ms
    slot_ms = day_start_ms + jitter_ms
    if now >= slot_ms:
        return last_protected_at < slot_ms
    prev_slot_ms = slot_ms - interval_ms
    return last_protected_at < prev_slot_ms


async def _run_tick_shielded(fn: Callable[[], bool], error_message: str) -> None:
    """Run a blocking scheduler tick in a thread and shield it from cancellation until done."""
    task = asyncio.create_task(asyncio.to_thread(fn))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            logger.warning(error_message)
        raise
    except Exception:
        logger.warning(error_message)


class WorkspaceBackupScheduler:
    """In-process nightly capture + hourly overdue/dirty watchdog for one Operator workspace."""

    def __init__(
        self,
        recovery_service,
        *,
        deployment_id: str,
        operator_id: str,
        workspace_id: str,
        clock: Callable[[], int],
        nightly_interval_ms: int = NIGHTLY_INTERVAL_MS,
        watchdog_interval_seconds: float = WATCHDOG_INTERVAL_SECONDS,
        jitter_window_seconds: int = DEFAULT_JITTER_WINDOW_SECONDS,
    ):
        self.recovery_service = recovery_service
        self.deployment_id = deployment_id
        self.operator_id = operator_id
        self.workspace_id = workspace_id
        self.clock = clock
        self.nightly_interval_ms = nightly_interval_ms
        self.watchdog_interval_seconds = watchdog_interval_seconds
        self.jitter_ms = (
            deterministic_nightly_jitter_seconds(workspace_id, window_seconds=jitter_window_seconds)
            * 1000
        )

    def run_once(self) -> bool:
        """Evaluate freshness/watchdog and run nightly capture if due. Returns True if captured."""
        if hasattr(self.recovery_service, "mark_dirty_if_diverged"):
            self.recovery_service.mark_dirty_if_diverged()
        snap = self.recovery_service.evaluate_freshness()
        now = self.clock()
        last_protected_at = snap.last_verified_at
        if (
            getattr(snap, "protection_state", None) == "unchanged"
            and last_protected_at is not None
            and getattr(snap, "last_checked_at", None) is not None
        ):
            last_protected_at = max(last_protected_at, int(snap.last_checked_at))
        due = _is_nightly_slot_due(
            now=now,
            last_protected_at=last_protected_at,
            interval_ms=self.nightly_interval_ms,
            jitter_ms=self.jitter_ms,
        )
        if not due:
            return False
        day_bucket = now // NIGHTLY_INTERVAL_MS
        rev = max(1, snap.revision)
        scope = WorkspaceScope(operator_id=self.operator_id, workspace_id=self.workspace_id)
        actor = ServiceAuthority(
            deployment_id=self.deployment_id,
            scope=scope,
            service="operator_backup",
            authenticated_channel_ref="internal:nightly-scheduler",
        )
        intent = CommandIntent(
            deployment_id=self.deployment_id,
            scope=scope,
            kind="capture",
            expected_revision=rev,
            access_epoch=1,
            payload=Capture(
                capture_policy_ref="free-nightly-v1",
                expected_checkpoint_revision=rev,
            ),
        )
        command = WorkspaceRecoveryCommand(
            operation_id=str(uuid4()),
            idempotency_key=f"nightly:{self.operator_id}:{day_bucket}:r{rev}",
            intent=intent,
            request_hash=semantic_hash(intent),
        )
        self.recovery_service.execute(actor, command)
        return True

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            await _run_tick_shielded(
                self.run_once, "Workspace nightly backup scheduler tick failed."
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.watchdog_interval_seconds)
            except TimeoutError:
                continue


class AdminControlBackupScheduler:
    """In-process nightly control-plane capture scheduler for Admin."""

    def __init__(
        self,
        admin_recovery,
        *,
        deployment_id: str,
        clock: Callable[[], int],
        nightly_interval_ms: int = NIGHTLY_INTERVAL_MS,
        watchdog_interval_seconds: float = WATCHDOG_INTERVAL_SECONDS,
        jitter_window_seconds: int = DEFAULT_JITTER_WINDOW_SECONDS,
    ):
        self.admin_recovery = admin_recovery
        self.deployment_id = deployment_id
        self.clock = clock
        self.nightly_interval_ms = nightly_interval_ms
        self.watchdog_interval_seconds = watchdog_interval_seconds
        self.jitter_ms = (
            deterministic_nightly_jitter_seconds(
                deployment_id, window_seconds=jitter_window_seconds
            )
            * 1000
        )

    def _read_last_verified_and_revision(self) -> tuple[int | None, int]:
        with self.admin_recovery.admin_recovery_engine.connect() as conn:
            bs = (
                conn.execute(text("SELECT revision FROM control_backup_state WHERE id = 1"))
                .mappings()
                .one_or_none()
            )
            last_verified = conn.execute(
                text(
                    "SELECT MAX(verified_at) FROM control_recovery_points WHERE state = 'verified'"
                )
            ).scalar_one_or_none()
        rev = int(bs["revision"]) if bs is not None else 1
        return (int(last_verified) if last_verified is not None else None), rev

    def run_once(self) -> bool:
        """Run nightly control-plane capture if due. Returns True if captured."""
        last_verified, revision = self._read_last_verified_and_revision()
        now = self.clock()
        due = _is_nightly_slot_due(
            now=now,
            last_protected_at=last_verified,
            interval_ms=self.nightly_interval_ms,
            jitter_ms=self.jitter_ms,
        )
        if not due:
            return False
        day_bucket = now // NIGHTLY_INTERVAL_MS
        rev = max(1, revision)
        scope = DeploymentScope()
        actor = ServiceAuthority(
            deployment_id=self.deployment_id,
            scope=scope,
            service="admin_backup",
            authenticated_channel_ref="internal:admin-nightly-scheduler",
        )
        intent = CommandIntent(
            deployment_id=self.deployment_id,
            scope=scope,
            kind="capture_control",
            expected_revision=rev,
            access_epoch=1,
            payload=CaptureControl(
                capture_policy_ref="admin-nightly-v1",
                expected_checkpoint_revision=rev,
            ),
        )
        command = AdminRecoveryCommand(
            operation_id=str(uuid4()),
            idempotency_key=f"admin-nightly:{self.deployment_id}:{day_bucket}:r{rev}",
            intent=intent,
            request_hash=semantic_hash(intent),
        )
        self.admin_recovery.execute(actor, command)
        return True

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            await _run_tick_shielded(
                self.run_once, "Admin nightly control backup scheduler tick failed."
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.watchdog_interval_seconds)
            except TimeoutError:
                continue

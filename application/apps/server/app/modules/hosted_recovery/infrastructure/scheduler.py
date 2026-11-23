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
        snap = self.recovery_service.evaluate_freshness()
        now = self.clock()
        due = (
            snap.last_verified_at is None
            or (now - snap.last_verified_at) >= self.nightly_interval_ms + self.jitter_ms
        )
        if not due:
            return False
        day_bucket = now // NIGHTLY_INTERVAL_MS
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
            expected_revision=max(1, snap.revision),
            access_epoch=1,
            payload=Capture(
                capture_policy_ref="free-nightly-v1",
                expected_checkpoint_revision=max(1, snap.revision),
            ),
        )
        command = WorkspaceRecoveryCommand(
            operation_id=str(uuid4()),
            idempotency_key=f"nightly:{self.operator_id}:{day_bucket}",
            intent=intent,
            request_hash=semantic_hash(intent),
        )
        self.recovery_service.execute(actor, command)
        return True

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.to_thread(self.run_once)
            except Exception:
                logger.warning("Workspace nightly backup scheduler tick failed.")
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
        due = (
            last_verified is None
            or (now - last_verified) >= self.nightly_interval_ms + self.jitter_ms
        )
        if not due:
            return False
        day_bucket = now // NIGHTLY_INTERVAL_MS
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
            expected_revision=max(1, revision),
            access_epoch=1,
            payload=CaptureControl(
                capture_policy_ref="admin-nightly-v1",
                expected_checkpoint_revision=max(1, revision),
            ),
        )
        command = AdminRecoveryCommand(
            operation_id=str(uuid4()),
            idempotency_key=f"admin-nightly:{self.deployment_id}:{day_bucket}",
            intent=intent,
            request_hash=semantic_hash(intent),
        )
        self.admin_recovery.execute(actor, command)
        return True

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.to_thread(self.run_once)
            except Exception:
                logger.warning("Admin nightly control backup scheduler tick failed.")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.watchdog_interval_seconds)
            except TimeoutError:
                continue

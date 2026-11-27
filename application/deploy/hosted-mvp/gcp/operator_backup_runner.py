"""Host-side scheduled Pilot 0 Operator backup runner (per-HOST_UID R2 + Cloud KMS).

Pilot 0 Operator web containers run as shared UID 65532:65532 without mounting
/run/epm-backup-proxy, while epm-backup-proxy.service authenticates callers by
SO_PEERCRED against per-operator HOST_UIDs in inventory.sqlite.

This runner iterates active registered Pilot 0 operators and, for any operator
whose recovery.sqlite shows uncommitted changes (dirty_since), degraded/overdue
protection state, or a prior backup error (or when --force is passed):
  1. Stops epm-op-<slug> briefly.
  2. Temporarily chowns the operator directories to HOST_UID:HOST_UID.
  3. Runs a short-lived --network none container on the operator's current
     pinned image with /run/epm-backup-proxy mounted to capture and verify an
     R2 + Cloud KMS recovery point.
  4. Always restores 65532:65532 ownership and restarts epm-op-<slug> in a
     finally block, then waits for Docker health so the container's
     UnixSummaryPublisher relays the healthy state to Admin.

Unchanged, healthy workspaces are skipped with zero container downtime.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

REGISTRY_PATH = Path("/etc/epm/pilot0-operators/registry.json")
INVENTORY_DB = Path("/srv/epm/data/host/backup-proxy/inventory.sqlite")
LOCK_PATH = Path("/run/epm/operator-backup.lock")
CENTRAL_UID = 65532
HEALTH_TIMEOUT_SECONDS = 90.0

IN_CONTAINER_BACKUP_CODE = """
import time
from pathlib import Path
from app.modules.host_agent.infrastructure.backup_proxy import UnixBackupProxyClient
from app.modules.hosted_access.infrastructure.operator_entry import OperatorDeployment
from app.modules.hosted_access.infrastructure.shared_identity_entry import read_private
from app.modules.hosted_recovery.infrastructure.engine import ChunkedAeadBackupEngine
from app.modules.hosted_recovery.infrastructure.scheduler import WorkspaceBackupScheduler
from app.modules.workspace.infrastructure.hosted_recovery import HostedWorkspaceRecoveryService
from app.platform.sqlite_engine import create_sqlite_engine

cfg = OperatorDeployment.model_validate_json(read_private(Path("/control/deployment.json")))
b = cfg.binding
clock = lambda: time.time_ns() // 1_000_000
svc = HostedWorkspaceRecoveryService(
    recovery_engine=create_sqlite_engine(cfg.recovery_database),
    access_engine=create_sqlite_engine(cfg.access_database),
    backup_engine=ChunkedAeadBackupEngine(
        UnixBackupProxyClient(cfg.backup_proxy_socket, expected_proxy_uid=cfg.backup_proxy_uid)
    ),
    operator_id=b.scope.operator_id,
    workspace_id=b.scope.workspace_id,
    deployment_id=b.deployment_id,
    workspace_root=Path("/data/workspace"),
    scratch_root=cfg.scratch_directory,
    release_ref=cfg.release_ref,
    business_schema_revision=cfg.business_schema_revision,
    access_schema_revision=cfg.access_schema_revision,
    clock=clock,
)
sched = WorkspaceBackupScheduler(
    svc,
    deployment_id=b.deployment_id,
    operator_id=b.scope.operator_id,
    workspace_id=b.scope.workspace_id,
    clock=clock,
    nightly_interval_ms=1000,
    jitter_window_seconds=0,
)
ran = sched.run_once()
status = svc.read_protection_status()
print("RUN_ONCE:", ran, status)
if not ran:
    raise SystemExit("WorkspaceBackupScheduler.run_once() returned False.")
"""


@dataclass(frozen=True)
class OperatorTarget:
    operator_id: str
    workspace_slug: str
    host_uid: int

    @property
    def container_name(self) -> str:
        return f"epm-op-{self.workspace_slug}"

    def host_directories(self) -> list[str]:
        return [
            f"/srv/epm/data/workspace/{self.operator_id}",
            f"/srv/epm/data/control/{self.operator_id}",
            f"/srv/epm/data/scratch/{self.operator_id}",
            f"/etc/epm/pilot0-operators/{self.operator_id}",
        ]


def log_event(event: str, **fields: object) -> None:
    record = {
        "component": "epm_operator_backup",
        "event": event,
        "timestamp_ms": time.time_ns() // 1_000_000,
        **fields,
    }
    print(json.dumps(record, sort_keys=True), flush=True)


def load_targets(
    registry_path: Path = REGISTRY_PATH,
    inventory_db: Path = INVENTORY_DB,
    *,
    operator_filter: str | None = None,
    slug_filter: str | None = None,
) -> list[OperatorTarget]:
    reg = json.loads(registry_path.read_text(encoding="utf-8"))
    conn = sqlite3.connect(str(inventory_db))
    try:
        principals = {
            row[0]: int(row[1])
            for row in conn.execute(
                "SELECT operator_id, host_uid FROM operator_principals WHERE retired_at IS NULL"
            ).fetchall()
        }
    finally:
        conn.close()

    targets: list[OperatorTarget] = []
    for op_id, op in sorted(
        reg.get("operators", {}).items(), key=lambda kv: kv[1]["workspace_slug"]
    ):
        slug = op["workspace_slug"]
        if operator_filter and op_id != operator_filter:
            continue
        if slug_filter and slug != slug_filter:
            continue
        if op_id not in principals:
            log_event("operator_missing_host_uid", operator_id=op_id, workspace_slug=slug)
            continue
        targets.append(
            OperatorTarget(operator_id=op_id, workspace_slug=slug, host_uid=principals[op_id])
        )
    return targets


def needs_backup(recovery_db: Path, *, force: bool = False) -> tuple[bool, str]:
    if force:
        return True, "forced"
    if not recovery_db.is_file():
        return False, "recovery_db_missing"
    conn = sqlite3.connect(str(recovery_db))
    try:
        row = conn.execute(
            "SELECT protection_state, dirty_since, last_error_code, consecutive_failures "
            "FROM backup_state WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return True, "backup_state_missing"
    protection_state, dirty_since, last_error_code, consecutive_failures = row
    reason = f"clean:{protection_state}"
    due = False
    if protection_state not in {"healthy", "unchanged"}:
        due, reason = True, f"protection_state={protection_state}"
    elif dirty_since is not None:
        due, reason = True, "workspace_dirty"
    elif last_error_code is not None or (consecutive_failures or 0) > 0:
        due, reason = True, f"prior_error={last_error_code}"
    return due, reason


def _wait_for_healthy(container_name: str, *, timeout: float = HEALTH_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        proc = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}",
                container_name,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip() == "running|healthy":
            return
        time.sleep(3)
    raise RuntimeError(f"{container_name} did not report running|healthy within {timeout:.0f}s.")


def run_operator_backup(target: OperatorTarget) -> None:
    ctr = target.container_name
    image_ref = subprocess.check_output(
        ["docker", "inspect", "--format", "{{.Image}}", ctr], text=True
    ).strip()
    if not image_ref:
        raise RuntimeError(f"Could not resolve current Docker image ID for {ctr}.")

    dirs = target.host_directories()
    log_event(
        "operator_backup_started",
        operator_id=target.operator_id,
        workspace_slug=target.workspace_slug,
        host_uid=target.host_uid,
        image_ref=image_ref,
    )
    subprocess.run(["docker", "stop", ctr], check=True)
    try:
        subprocess.run(["chown", "-R", f"{target.host_uid}:{target.host_uid}", *dirs], check=True)
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--user",
                f"{target.host_uid}:{target.host_uid}",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,noexec,size=32m",
                "--mount",
                f"type=bind,source=/etc/epm/pilot0-operators/{target.operator_id},"
                "target=/control,readonly",
                "--mount",
                f"type=bind,source=/srv/epm/data/workspace/{target.operator_id},"
                "target=/data/workspace",
                "--mount",
                f"type=bind,source=/srv/epm/data/control/{target.operator_id},target=/data/control",
                "--mount",
                f"type=bind,source=/srv/epm/data/scratch/{target.operator_id},target=/data/scratch",
                "--mount",
                "type=bind,source=/run/epm-backup-proxy,target=/run/epm-backup-proxy",
                "--pull",
                "never",
                "--entrypoint",
                "/opt/epm/venv/bin/python",
                image_ref,
                "-B",
                "-c",
                IN_CONTAINER_BACKUP_CODE,
            ],
            check=True,
        )
    finally:
        subprocess.run(["chown", "-R", f"{CENTRAL_UID}:{CENTRAL_UID}", *dirs], check=True)
        subprocess.run(["docker", "start", ctr], check=True)

    _wait_for_healthy(ctr)
    log_event(
        "operator_backup_succeeded",
        operator_id=target.operator_id,
        workspace_slug=target.workspace_slug,
    )


def systemd_units() -> dict[str, str]:
    """Return the host systemd service and 6-hour timer unit contents."""
    return {
        "epm-operator-backup.service": (
            "[Unit]\n"
            "Description=EPM Pilot 0 Host-Side Operator Verified Backup Runner\n"
            "After=docker.service epm-backup-proxy.service epm-h03-identity.service\n"
            "Requires=docker.service epm-backup-proxy.service\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            "ExecStart=/opt/epm/python/bin/python3 -B /opt/epm/pilot0/operator_backup_runner.py\n"
        ),
        "epm-operator-backup.timer": (
            "[Unit]\n"
            "Description=Run EPM Pilot 0 Operator verified backup check every 6 hours\n\n"
            "[Timer]\n"
            "OnCalendar=*-*-* 02,08,14,20:00:00 UTC\n"
            "RandomizedDelaySec=10m\n"
            "Persistent=true\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator", dest="operator_id", default=None)
    parser.add_argument("--slug", dest="slug", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log_event("operator_backup_locked_skip")
            return 0

        targets = load_targets(operator_filter=args.operator_id, slug_filter=args.slug)
        failures = 0
        for target in targets:
            recovery_db = Path(f"/srv/epm/data/control/{target.operator_id}/recovery.sqlite")
            due, reason = needs_backup(recovery_db, force=args.force)
            if not due:
                log_event(
                    "operator_backup_skipped",
                    operator_id=target.operator_id,
                    workspace_slug=target.workspace_slug,
                    reason=reason,
                )
                continue
            if args.dry_run:
                log_event(
                    "operator_backup_dry_run",
                    operator_id=target.operator_id,
                    workspace_slug=target.workspace_slug,
                    reason=reason,
                )
                continue
            try:
                run_operator_backup(target)
            except Exception as exc:
                failures += 1
                log_event(
                    "operator_backup_failed",
                    operator_id=target.operator_id,
                    workspace_slug=target.workspace_slug,
                    error=str(exc),
                )
        return 1 if failures else 0
    finally:
        os.close(lock_fd)


if __name__ == "__main__":
    sys.exit(main())

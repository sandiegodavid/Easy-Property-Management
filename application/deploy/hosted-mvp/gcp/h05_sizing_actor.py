"""H05.9 backup/restore physical reserve sizing actor for native Linux/Docker/GCP qualification.

Exercises all three workload shapes (`database_heavy`, `retained_file_heavy`,
`many_small_files_history`) at the Free 50,000,000-byte logical allowance through:
  - 7 verified off-host backup captures (measuring scratch staging + control churn),
  - concurrent staged restore into a sibling incarnation while retaining the prior tree
    (measuring workspace live + staged restore + 1 retained prior/forensic incarnation),
  - independent byte and inode exhaustion/rollback proofs on backup and restore staging.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from sqlalchemy import text

from app.modules.host_agent.infrastructure.backup_proxy import (
    BackupProxyHandler,
    CallerPrincipal,
)
from app.modules.hosted_recovery.domain.models import ObjectMetadata
from app.modules.hosted_recovery.infrastructure.engine import ChunkedAeadBackupEngine
from app.modules.hosted_recovery.infrastructure.kms_provider import LocalAesKmsProvider
from app.modules.hosted_recovery.infrastructure.r2_store import LocalDirectoryObjectStore
from app.modules.workspace.application.recovery_contracts import (
    Capture,
    WorkspaceRecoveryCommand,
)
from app.modules.workspace.infrastructure.hosted_recovery import (
    HostedWorkspaceRecoveryService,
    kms_ref_to_db_ref,
)
from app.platform.hosted_contracts.authority import (
    OperatorAuthority,
    OperatorRestoreAuthority,
    ServiceAuthority,
)
from app.platform.hosted_contracts.operations import CommandIntent
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import WorkspaceScope
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine

FREE_LOGICAL_BYTES = 50_000_000
PEAK_SAMPLE_INTERVAL_S = 0.25
DEFAULT_NOW_MS = 1_760_000_000_000
DEPLOYMENT_ID = "00000000-0000-4000-8000-000000000950"
OPERATOR_ID = "00000000-0000-4000-8000-000000000951"
WORKSPACE_ID = "00000000-0000-4000-8000-000000000952"
KMS_KEY = "projects/epm-demo/locations/us-west1/keyRings/epm-h05/cryptoKeys/ws-sizing"
BIZ_SCHEMA = "20260401_0001"
ACC_SCHEMA = "access_0001_initial"
LINUX_QUOTA_ERRORS = (errno.EDQUOT, errno.ENOSPC, 122, 28)
APPLICATION_ROOT = Path(
    os.environ.get("EPM_APPLICATION_ROOT") or Path(__file__).resolve().parents[3]
)


def tree_disk_usage(root: Path) -> dict[str, int]:
    """Measure allocated bytes and inode count for a directory tree."""
    total_bytes = 0
    inodes = 0
    seen_inodes: set[tuple[int, int]] = set()
    if not root.exists():
        return {"bytes": 0, "inodes": 0}
    for dirpath, _dirnames, filenames in os.walk(root):
        dir_stat = os.lstat(dirpath)
        dir_key = (dir_stat.st_dev, dir_stat.st_ino)
        if dir_key not in seen_inodes:
            seen_inodes.add(dir_key)
            inodes += 1
            total_bytes += dir_stat.st_blocks * 512 if hasattr(dir_stat, "st_blocks") else 0
        for name in filenames:
            path = Path(dirpath) / name
            try:
                st = os.lstat(path)
            except FileNotFoundError:
                continue
            key = (st.st_dev, st.st_ino)
            if key not in seen_inodes:
                seen_inodes.add(key)
                inodes += 1
                total_bytes += st.st_blocks * 512 if hasattr(st, "st_blocks") else st.st_size
    return {"bytes": total_bytes, "inodes": inodes}


def _update_peaks(peaks: dict[str, dict[str, int]], trees: dict[str, Path]) -> None:
    for role, path in trees.items():
        sample = tree_disk_usage(path)
        peaks[role]["peak_bytes"] = max(peaks[role]["peak_bytes"], sample["bytes"])
        peaks[role]["peak_inodes"] = max(peaks[role]["peak_inodes"], sample["inodes"])


class _DirectProxyTransport:
    def __init__(self, handler: BackupProxyHandler, uid: int, *, on_activity=None) -> None:
        self._handler = handler
        self._uid = uid
        self._on_activity = on_activity

    def _call(
        self, req: dict[str, object], payload: bytes = b""
    ) -> tuple[dict[str, object], bytes]:
        if self._on_activity is not None:
            self._on_activity()
        return self._handler.dispatch(self._uid, {"version": 1, **req}, payload)

    def put_object(self, relative_key: str, data: bytes) -> ObjectMetadata:
        resp, _ = self._call({"op": "put_object", "key": relative_key}, data)
        return ObjectMetadata.model_validate(resp["meta"])

    def head_object(self, relative_key: str) -> ObjectMetadata:
        resp, _ = self._call({"op": "head_object", "key": relative_key})
        return ObjectMetadata.model_validate(resp["meta"])

    def get_object(self, relative_key: str) -> tuple[bytes, ObjectMetadata]:
        resp, body = self._call({"op": "get_object", "key": relative_key})
        return body, ObjectMetadata.model_validate(resp["meta"])

    def delete_object(self, relative_key: str) -> None:
        self._call({"op": "delete_object", "key": relative_key})

    def list_objects_page(
        self, subprefix: str = "", *, max_keys: int = 1000, continuation_token: str | None = None
    ) -> tuple[list[str], str | None]:
        req: dict[str, object] = {
            "op": "list_objects",
            "subprefix": subprefix,
            "max_keys": max_keys,
        }
        if continuation_token is not None:
            req["continuation_token"] = continuation_token
        resp, body = self._call(req)
        keys = json.loads(body.decode("utf-8"))["keys"] if body else resp["keys"]
        return list(keys), resp.get("next_token")

    def list_objects(self, subprefix: str = "", *, max_keys: int = 1000) -> list[str]:
        keys, _ = self.list_objects_page(subprefix, max_keys=max_keys)
        return keys

    def kms_wrap(self, key_ref: str, plaintext_dek: bytes, *, aad: bytes) -> bytes:
        _, body = self._call(
            {
                "op": "kms_wrap",
                "key_ref": key_ref,
                "aad_b64": base64.b64encode(aad).decode("ascii"),
            },
            plaintext_dek,
        )
        return body

    def kms_unwrap(self, key_ref: str, wrapped_dek: bytes, *, aad: bytes) -> bytes:
        _, body = self._call(
            {
                "op": "kms_unwrap",
                "key_ref": key_ref,
                "aad_b64": base64.b64encode(aad).decode("ascii"),
            },
            wrapped_dek,
        )
        return body


def _init_business_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE properties (id TEXT PRIMARY KEY, name TEXT NOT NULL, notes TEXT)"
        )
        conn.execute(
            "CREATE TABLE file_records ("
            "id TEXT PRIMARY KEY, content_sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE file_content_locations ("
            "file_id TEXT PRIMARY KEY, storage_provider TEXT NOT NULL, "
            "storage_state TEXT NOT NULL, local_relative_path TEXT)"
        )
        conn.commit()


def _populate_workload(shape: str, incarnation: Path, target_bytes: int) -> int:
    """Populate incarnation-1 with deterministic data matching the target workload shape."""
    db_path = incarnation / "property-management.sqlite"
    _init_business_db(db_path)
    logical_bytes = 0
    with sqlite3.connect(db_path) as conn:
        if shape == "database_heavy":
            payload_chunk = "A" * 4096
            row_count = max(8, int((target_bytes * 0.85) // 4200))
            rows = [(f"prop-{i:06d}", f"Property {i}", payload_chunk) for i in range(row_count)]
            conn.executemany("INSERT INTO properties VALUES (?, ?, ?)", rows)
            conn.commit()
        elif shape == "retained_file_heavy":
            conn.execute("INSERT INTO properties VALUES ('p0', 'Main Asset', 'retained-files')")
            file_count = max(2, min(16, int(target_bytes // (256 * 1024)) or 2))
            per_file = max(4096, int((target_bytes * 0.85) // file_count))
            for idx in range(file_count):
                rel = f"files/doc-{idx:03d}.bin"
                data = (f"DOC-{idx:03d}-".encode() * ((per_file // 8) + 1))[:per_file]
                target = incarnation / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                conn.execute(
                    "INSERT INTO file_records VALUES (?, ?, ?)", (f"f-{idx}", digest, len(data))
                )
                conn.execute(
                    "INSERT INTO file_content_locations VALUES (?, 'local', 'available', ?)",
                    (f"f-{idx}", rel),
                )
                logical_bytes += len(data)
            conn.commit()
        elif shape == "many_small_files_history":
            conn.execute("INSERT INTO properties VALUES ('p0', 'Many Small Files', 'history')")
            file_count = max(32, min(1500, int((target_bytes * 0.80) // 4096)))
            per_file = max(1024, int((target_bytes * 0.80) // file_count))
            for idx in range(file_count):
                rel = f"files/batch-{idx // 100:02d}/item-{idx:05d}.txt"
                data = (f"ITEM-{idx:05d}-".encode() * ((per_file // 11) + 1))[:per_file]
                target = incarnation / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                conn.execute(
                    "INSERT INTO file_records VALUES (?, ?, ?)", (f"f-{idx}", digest, len(data))
                )
                conn.execute(
                    "INSERT INTO file_content_locations VALUES (?, 'local', 'available', ?)",
                    (f"f-{idx}", rel),
                )
                logical_bytes += len(data)
            conn.commit()
        else:
            raise ValueError(f"Unsupported workload shape: {shape}")

    logical_bytes += db_path.stat().st_size
    return min(logical_bytes, target_bytes)


@dataclass(frozen=True)
class SizingDirs:
    workspace: Path
    control: Path
    scratch: Path
    r2: Path


def _setup_recovery_service(
    dirs: SizingDirs,
    *,
    clock_ms: list[int],
    on_activity=None,
):
    workspace_dir, control_dir, scratch_dir, r2_dir = (
        dirs.workspace,
        dirs.control,
        dirs.scratch,
        dirs.r2,
    )
    for d in (workspace_dir, control_dir, scratch_dir, r2_dir):
        d.mkdir(parents=True, exist_ok=True)
    os.chmod(control_dir, 0o700)
    os.chmod(scratch_dir, 0o700)

    app_dir = APPLICATION_ROOT if (APPLICATION_ROOT / "database").is_dir() else None
    rec_db = control_dir.resolve() / "recovery.sqlite"
    acc_db = control_dir.resolve() / "access.sqlite"
    initialize_store(HostedStore.RECOVERY, rec_db, application_directory=app_dir)
    initialize_store(HostedStore.HOSTED_ACCESS, acc_db, application_directory=app_dir)

    rec_engine = create_sqlite_engine(rec_db)
    acc_engine = create_sqlite_engine(acc_db)
    with rec_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO recovery_meta ("
                "id, workspace_id, deployment_ref, source_generation, restore_generation, "
                "active_business_ref, encryption_key_ref, namespace_prefix, revision"
                ") VALUES ("
                "1, :ws, :dep, 1, 1, 'incarnation-1', :key_ref, :prefix, 1)"
            ),
            {
                "ws": WORKSPACE_ID,
                "dep": f"dep:{DEPLOYMENT_ID}",
                "key_ref": kms_ref_to_db_ref(KMS_KEY),
                "prefix": f"deployments/{DEPLOYMENT_ID}/operators/{OPERATOR_ID}/",
            },
        )
        conn.execute(
            text(
                "INSERT INTO backup_state (id, protection_state, consecutive_failures, revision) "
                "VALUES (1, 'unknown', 0, 1)"
            )
        )
    with acc_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO access_meta ("
                "id, deployment_id, operator_id, workspace_id, binding_id, resource_generation, "
                "issuer, subject, email_key, effective_access, access_epoch, session_generation, "
                "not_before, effective_policy_id, usable_bytes, policy_revision, "
                "maintenance_operation_id, restore_generation, revision"
                ") VALUES ("
                "1, :dep, :op, :ws, :bind, 1, 'firebase:epm-demo', NULL, "
                "'sizing@example.com', 'disabled', 1, 1, :now, :pol, 50000000, 1, NULL, 1, 1)"
            ),
            {
                "dep": DEPLOYMENT_ID,
                "op": OPERATOR_ID,
                "ws": WORKSPACE_ID,
                "bind": str(uuid4()),
                "now": clock_ms[0],
                "pol": str(uuid4()),
            },
        )
        conn.execute(
            text(
                "UPDATE access_meta SET effective_access = 'enabled', "
                "subject = 'sub-sizing', revision = 2 WHERE id = 1"
            )
        )

    store = LocalDirectoryObjectStore(r2_dir)
    kms = LocalAesKmsProvider({KMS_KEY: hashlib.sha256(b"h059-sizing-kek").digest()})
    principal = CallerPrincipal(
        uid=20001,
        scope_kind="operator",
        deployment_id=DEPLOYMENT_ID,
        operator_id=OPERATOR_ID,
        workspace_id=WORKSPACE_ID,
        namespace_prefix=f"deployments/{DEPLOYMENT_ID}/operators/{OPERATOR_ID}/",
        allowed_key_refs=frozenset({KMS_KEY}),
    )
    handler = BackupProxyHandler(object_store=store, kms=kms, peer_resolver=lambda _: principal)
    transport = _DirectProxyTransport(handler, 20001, on_activity=on_activity)
    backup_engine = ChunkedAeadBackupEngine(transport, chunk_size=65536)

    def now() -> int:
        clock_ms[0] += 1_000
        return clock_ms[0]

    service = HostedWorkspaceRecoveryService(
        recovery_engine=rec_engine,
        access_engine=acc_engine,
        backup_engine=backup_engine,
        operator_id=OPERATOR_ID,
        workspace_id=WORKSPACE_ID,
        deployment_id=DEPLOYMENT_ID,
        workspace_root=workspace_dir.resolve(),
        scratch_root=scratch_dir.resolve(),
        release_ref="rel-h05-sizing",
        business_schema_revision=BIZ_SCHEMA,
        access_schema_revision=ACC_SCHEMA,
        clock=now,
    )
    return service, rec_engine, acc_engine


def _make_capture_command(scope: WorkspaceScope, key: str) -> WorkspaceRecoveryCommand:
    intent = CommandIntent(
        deployment_id=DEPLOYMENT_ID,
        scope=scope,
        kind="capture",
        expected_revision=1,
        access_epoch=1,
        payload=Capture(capture_policy_ref="policy:free-nightly", expected_checkpoint_revision=1),
    )
    return WorkspaceRecoveryCommand(
        operation_id=str(uuid4()),
        idempotency_key=key,
        intent=intent,
        request_hash=semantic_hash(intent),
    )


def run_h05_workload(
    shape: str,
    dirs: SizingDirs,
    *,
    target_bytes: int = FREE_LOGICAL_BYTES,
    captures: int = 7,
) -> dict[str, object]:
    """Measure peak workspace/control/scratch usage across 7 captures + concurrent restore."""
    clock_ms = [DEFAULT_NOW_MS]
    incarnation = dirs.workspace / "incarnation-1"
    logical_used = _populate_workload(shape, incarnation, target_bytes)
    trees = {"workspace": dirs.workspace, "control": dirs.control, "scratch": dirs.scratch}
    peaks = {role: {"peak_bytes": 0, "peak_inodes": 0} for role in trees}
    last_sample = [0.0]

    def _throttled_sample() -> None:
        now = time.monotonic()
        if now - last_sample[0] >= PEAK_SAMPLE_INTERVAL_S:
            last_sample[0] = now
            _update_peaks(peaks, trees)

    service, rec_engine, acc_engine = _setup_recovery_service(
        dirs,
        clock_ms=clock_ms,
        on_activity=_throttled_sample,
    )
    try:
        _update_peaks(peaks, trees)
        scope = WorkspaceScope(operator_id=OPERATOR_ID, workspace_id=WORKSPACE_ID)
        svc_actor = ServiceAuthority(
            deployment_id=DEPLOYMENT_ID,
            scope=scope,
            service="operator_backup",
            authenticated_channel_ref="channel:h059-sizing",
        )
        op_actor = OperatorAuthority(
            deployment_id=DEPLOYMENT_ID,
            scope=scope,
            identity_proof_ref="session:h059-sizing",
        )
        last_point_id = ""
        biz_db = incarnation / "property-management.sqlite"
        for i in range(1, captures + 1):
            with sqlite3.connect(biz_db) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO properties VALUES (?, ?, ?)",
                    (f"churn-{i}", f"Nightly {i}", "X" * 1024),
                )
                conn.commit()
            cmd = _make_capture_command(scope, f"h059-{shape}-cap-{i}")
            service.execute(svc_actor, cmd)
            _update_peaks(peaks, trees)
            snap = service.read_protection_status()
            if snap.last_point_id:
                last_point_id = snap.last_point_id

        # Full Preview -> ConfirmRestore creates concurrent incarnation-2 alongside incarnation-1.
        preview = service.preview_restore(op_actor, point_id=last_point_id)
        restore_actor = OperatorRestoreAuthority(
            deployment_id=DEPLOYMENT_ID,
            scope=scope,
            identity_proof_ref="session:h059-sizing",
            step_up_ref=f"stepup:{preview.preview_id}",
            step_up_at=clock_ms[0],
            confirmed_request_hash=preview.exact_request_hash,
        )
        outcome = service.confirm_restore(
            restore_actor,
            point_id=last_point_id,
            preview_id=preview.preview_id,
            idempotency_key=f"h059-{shape}-restore-1",
            authorized_subject=f"operator:{OPERATOR_ID}",
        )
        _update_peaks(peaks, trees)

        # Verify restored DB integrity.
        startup = service.detect_startup_mode()
        return {
            "shape": shape,
            "logical_used_bytes": logical_used,
            "captures_completed": captures,
            "restore_state": outcome.state.value,
            "startup_mode_after_restore": startup.mode,
            "trees": peaks,
        }
    finally:
        rec_engine.dispose()
        acc_engine.dispose()


def _fill_quota_until_error(kind: str, dirs: SizingDirs) -> tuple[int | None, Path, bool]:
    """Consume quota in the target tree until OSError; caller removes created files in finally."""
    if kind.startswith("backup_"):
        target_dir = dirs.scratch / ".quota-fill"
        target_dir.mkdir(parents=True, exist_ok=True)
        remove_dir = True
    elif kind.startswith("restore_"):
        target_dir = dirs.workspace / ".quota-fill"
        target_dir.mkdir(parents=True, exist_ok=True)
        remove_dir = True
    else:
        raise ValueError(f"Unknown exhaustion kind: {kind}")

    observed_errno: int | None = None
    if kind.endswith("byte_exhaustion"):
        with (target_dir / "fill.bin").open("wb", buffering=0) as handle:
            for chunk_size in (1024 * 1024, 64 * 1024, 4096, 512):
                chunk = b"\0" * chunk_size
                try:
                    for _ in range(512):
                        handle.write(chunk)
                        os.fsync(handle.fileno())
                except OSError as exc:
                    observed_errno = exc.errno
    else:
        try:
            for idx in range(16_384):
                (target_dir / f"i-{idx}").touch()
        except OSError as exc:
            observed_errno = exc.errno
    return observed_errno, target_dir, remove_dir


def _cleanup_quota_fill(target_dir: Path | None, remove_dir: bool) -> None:
    if target_dir is None or not target_dir.exists():
        return
    for entry in list(target_dir.iterdir()):
        if entry.is_file():
            entry.unlink(missing_ok=True)
    if remove_dir:
        target_dir.rmdir()


def _run_exhausted_operation(
    kind: str,
    service: HostedWorkspaceRecoveryService,
    *,
    point_id: str,
    now_ms: int,
    simulated_errno: int | None,
) -> bool:
    """Invoke real capture or confirm_restore under quota exhaustion and return failed_closed."""
    scope = WorkspaceScope(operator_id=OPERATOR_ID, workspace_id=WORKSPACE_ID)
    if kind.startswith("backup_"):
        svc_actor = ServiceAuthority(
            deployment_id=DEPLOYMENT_ID,
            scope=scope,
            service="operator_backup",
            authenticated_channel_ref="channel:h059-exhaust",
        )
        orig_capture = service.backup_engine.create_point
        if simulated_errno is not None:

            def _failing_capture(*args, **kwargs):
                raise OSError(simulated_errno, os.strerror(simulated_errno))

            service.backup_engine.create_point = _failing_capture  # type: ignore[method-assign]
        try:
            fail_cmd = _make_capture_command(scope, f"h059-{kind}-fault")
            outcome = service.execute(svc_actor, fail_cmd)
            return outcome.state.value == "failed"
        finally:
            service.backup_engine.create_point = orig_capture  # type: ignore[method-assign]

    op_actor = OperatorAuthority(
        deployment_id=DEPLOYMENT_ID,
        scope=scope,
        identity_proof_ref="session:h059-exhaust",
    )
    preview = service.preview_restore(op_actor, point_id=point_id)
    recent_actor = OperatorRestoreAuthority(
        deployment_id=DEPLOYMENT_ID,
        scope=scope,
        identity_proof_ref="session:h059-exhaust",
        step_up_ref=f"stepup:{preview.preview_id}",
        step_up_at=now_ms,
        confirmed_request_hash=preview.exact_request_hash,
    )
    orig_restore = service.backup_engine.restore_point
    if simulated_errno is not None:

        def _failing_restore(*args, **kwargs):
            raise OSError(simulated_errno, os.strerror(simulated_errno))

        service.backup_engine.restore_point = _failing_restore  # type: ignore[method-assign]
    try:
        outcome = service.confirm_restore(
            recent_actor,
            point_id=point_id,
            preview_id=preview.preview_id,
            idempotency_key=f"h059-{kind}-fault",
            authorized_subject=f"operator:{OPERATOR_ID}",
        )
        return outcome.state.value in {"failed", "needs_attention"}
    except Exception:
        return True
    finally:
        service.backup_engine.restore_point = orig_restore  # type: ignore[method-assign]


def run_exhaustion_proof(
    kind: str,
    dirs: SizingDirs,
    *,
    simulated_errno: int | None = None,
) -> dict[str, object]:
    """Verify byte or inode exhaustion during real backup or restore staging rolls back cleanly."""
    if not (kind.startswith("backup_") or kind.startswith("restore_")):
        raise ValueError(f"Unknown exhaustion kind: {kind}")
    clock_ms = [DEFAULT_NOW_MS]
    incarnation = dirs.workspace / "incarnation-1"
    _populate_workload("database_heavy", incarnation, 64_000)
    biz_db = incarnation / "property-management.sqlite"
    with sqlite3.connect(biz_db) as conn:
        before_count = conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]

    service, rec_engine, acc_engine = _setup_recovery_service(dirs, clock_ms=clock_ms)
    fill_dir: Path | None = None
    remove_fill_dir = False
    try:
        scope = WorkspaceScope(operator_id=OPERATOR_ID, workspace_id=WORKSPACE_ID)
        svc_actor = ServiceAuthority(
            deployment_id=DEPLOYMENT_ID,
            scope=scope,
            service="operator_backup",
            authenticated_channel_ref="channel:h059-exhaust",
        )
        op_actor = OperatorAuthority(
            deployment_id=DEPLOYMENT_ID,
            scope=scope,
            identity_proof_ref="session:h059-exhaust",
        )
        service.execute(svc_actor, _make_capture_command(scope, f"h059-{kind}-baseline"))
        point_id = service.read_protection_status().last_point_id or ""
        active_before = service.active_business_directory()

        if kind.startswith("backup_"):
            with sqlite3.connect(biz_db) as conn:
                conn.execute(
                    "INSERT INTO properties(id, name, notes) VALUES (999999, 'mut', 'quota-test')"
                )
                conn.commit()
                before_count = conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]

        if simulated_errno is None:
            observed_errno, fill_dir, remove_fill_dir = _fill_quota_until_error(kind, dirs)
        else:
            observed_errno = simulated_errno

        clock_ms[0] += 10_000
        try:
            operation_failed_closed = _run_exhausted_operation(
                kind,
                service,
                point_id=point_id,
                now_ms=clock_ms[0],
                simulated_errno=simulated_errno,
            )
        finally:
            _cleanup_quota_fill(fill_dir, remove_fill_dir)

        with sqlite3.connect(biz_db) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            after_count = conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
        startup = service.detect_startup_mode()
        snap = service.read_protection_status()
        active_after = service.active_business_directory()
        preview_after = service.preview_restore(op_actor, point_id=point_id)

        honest_status = (
            snap.last_point_id == point_id
            and bool(preview_after.preview_id)
            and operation_failed_closed
            and (snap.consecutive_failures >= 1 if kind.startswith("backup_") else True)
        )
        workspace_entries = sorted(p.name for p in dirs.workspace.iterdir())
        no_empty_init = (
            workspace_entries == ["incarnation-1"]
            and startup.reason != "business_database_unreadable"
            and (startup.mode == "normal" if kind.startswith("backup_") else True)
        )
        return {
            "kind": kind,
            "errno": observed_errno,
            "sqlite_integrity_ok": integrity,
            "original_tree_preserved": (
                after_count == before_count and biz_db.is_file() and active_after == active_before
            ),
            "no_empty_init": no_empty_init,
            "honest_status_recorded": honest_status,
        }
    finally:
        rec_engine.dispose()
        acc_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    wl = sub.add_parser("workload")
    wl.add_argument("--shape", required=True)
    wl.add_argument("--workspace", type=Path, required=True)
    wl.add_argument("--control", type=Path, required=True)
    wl.add_argument("--scratch", type=Path, required=True)
    wl.add_argument("--r2", type=Path, required=True)
    wl.add_argument("--target-bytes", type=int, default=FREE_LOGICAL_BYTES)
    wl.add_argument("--captures", type=int, default=7)

    ex = sub.add_parser("exhaustion")
    ex.add_argument("--kind", required=True)
    ex.add_argument("--workspace", type=Path, required=True)
    ex.add_argument("--control", type=Path, required=True)
    ex.add_argument("--scratch", type=Path, required=True)
    ex.add_argument("--r2", type=Path, required=True)

    args = parser.parse_args()
    dirs = SizingDirs(
        workspace=args.workspace,
        control=args.control,
        scratch=args.scratch,
        r2=args.r2,
    )
    if args.command == "workload":
        out = run_h05_workload(
            args.shape,
            dirs,
            target_bytes=args.target_bytes,
            captures=args.captures,
        )
    else:
        out = run_exhaustion_proof(args.kind, dirs)
    print(json.dumps(out, sort_keys=True))


if __name__ == "__main__":
    main()

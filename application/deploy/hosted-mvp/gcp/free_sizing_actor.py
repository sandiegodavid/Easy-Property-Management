"""H04.9 Free-pilot (50 MB) physical sizing actor for native Linux/Docker/GCP qualification.

Exercises the three required workload shapes against the real workspace schema,
content-addressed local file store, and H04 UsageAccountingStore / FreeStorageAdmission,
plus independent physical byte and inode exhaustion/rollback tests.
"""

from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from sqlalchemy import Engine, text

from app.modules.hosted_access.application.identity_evidence import IdentityBinding
from app.modules.hosted_access.application.source_contracts import (
    AdmittedFreePolicy,
    InitializeDisabled,
    SourceCommand,
)
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.free_storage_admission import (
    FreeStorageAdmission,
)
from app.modules.hosted_access.infrastructure.source_lifecycle import (
    FREE_V1_USABLE_BYTES,
    SourceLifecycle,
)
from app.modules.hosted_access.infrastructure.usage_accounting import (
    UsageAccountingStore,
    measure_logical_usage,
)
from app.modules.workspace.application.service import WorkspacePaths, WorkspaceService
from app.platform.hosted_contracts.authority import ServiceAuthority
from app.platform.hosted_contracts.operations import CommandIntent
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import WorkspaceScope
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

LINUX_QUOTA_ERRORS = (errno.EDQUOT, errno.ENOSPC, 122, 28)
HTTP_INSUFFICIENT_STORAGE = 507
MIB = 1024 * 1024
DEFAULT_NOW_MS = 2_000_000_000
MAX_EXHAUSTION_MIB = 512
MAX_EXHAUSTION_FILES = 16_384
FULL_TARGET_THRESHOLD = 10_000_000
APPLICATION_ROOT = Path(
    os.environ.get("EPM_APPLICATION_ROOT") or Path(__file__).resolve().parents[3]
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def tree_disk_usage(root: Path) -> dict[str, int]:
    """Measure allocated bytes and inode count for a directory tree."""
    total_bytes = 0
    inodes = 0
    seen_inodes: set[tuple[int, int]] = set()
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


def _init_access_store(
    control_dir: Path,
    business_engine: Engine,
    usable_bytes: int,
) -> tuple[Engine, UsageAccountingStore, FreeStorageAdmission]:
    private_dir = control_dir.resolve()
    private_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(private_dir, 0o700)
    access_db = private_dir / "access.sqlite"
    app_dir = APPLICATION_ROOT if (APPLICATION_ROOT / "database").is_dir() else None
    initialize_store(HostedStore.HOSTED_ACCESS, access_db, application_directory=app_dir)
    access_engine = create_sqlite_engine(access_db)
    clock = [DEFAULT_NOW_MS]

    def next_ms() -> int:
        clock[0] += 10
        return clock[0]

    scope = WorkspaceScope(
        operator_id="00000000-0000-4000-8000-000000000901",
        workspace_id="00000000-0000-4000-8000-000000000902",
    )
    binding = IdentityBinding(
        deployment_id="00000000-0000-4000-8000-000000000900",
        scope=scope,
        binding_id="00000000-0000-4000-8000-000000000903",
        resource_generation=1,
        assignment_revision=1,
        access_epoch=1,
        registered_origin_id="00000000-0000-4000-8000-000000000904",
        issuer="firebase:h04-sizing",
        subject="h04-sizing-subject",
        target_origin="https://sizing.epmdemo.xyz",
    )

    @contextmanager
    def mutation():
        with immediate_transaction(access_engine) as conn:
            yield conn

    lifecycle = SourceLifecycle(
        access_engine,
        mutation=mutation,
        binding=lambda: binding,
        clock=next_ms,
    )
    admin = ServiceAuthority(
        deployment_id=binding.deployment_id,
        scope=scope,
        service="admin",
        authenticated_channel_ref="local-sizing",
    )
    payload = InitializeDisabled(
        binding_id=binding.binding_id,
        policy=AdmittedFreePolicy(
            policy_id="00000000-0000-4000-8000-000000000905",
            policy_revision=1,
            usable_bytes=FREE_V1_USABLE_BYTES,
            admission_hash=sha256(b"h04-sizing-free-v1").hexdigest(),
        ),
        assignment_id="00000000-0000-4000-8000-000000000907",
    )
    intent = CommandIntent[InitializeDisabled](
        deployment_id=binding.deployment_id,
        scope=scope,
        kind="initialize_disabled",
        expected_revision=1,
        access_epoch=1,
        payload=payload,
    )
    command = SourceCommand(
        operation_id="00000000-0000-4000-8000-000000000906",
        idempotency_key="init-sizing-1",
        intent=intent,
        request_hash=semantic_hash(intent),
    )
    lifecycle.execute(admin, command, email_key="firebase:h04-sizing:sizing@example.invalid")
    if usable_bytes != FREE_V1_USABLE_BYTES:
        with immediate_transaction(access_engine) as conn:
            conn.execute(
                text("UPDATE main.access_meta SET usable_bytes = :limit"),
                {"limit": usable_bytes},
            )
    usage = UsageAccountingStore(access_engine, business_engine, clock=next_ms)
    usage.refresh_usage_state()
    admission = FreeStorageAdmission(usage)
    return access_engine, usage, admission


def _init_workspace(workspace_dir: Path, scratch_dir: Path) -> tuple[WorkspacePaths, Engine]:
    current = workspace_dir / "current"
    locator = scratch_dir / "locator.json"
    locator.write_text(json.dumps({"localWorkspacePath": str(current)}), encoding="utf-8")
    WorkspaceService.from_local_config(locator).initialize()
    paths = WorkspacePaths(root=current)
    business_engine = create_sqlite_engine(paths.database)
    return paths, business_engine


def _insert_retained_file(
    business_engine: Engine,
    paths: WorkspacePaths,
    scratch_dir: Path,
    payload: bytes,
    filename: str,
) -> int:
    digest = sha256(payload).hexdigest()
    stage = scratch_dir / f"stage-{uuid4().hex}.tmp"
    stage.write_bytes(payload)
    blob_dir = paths.root / "files" / "blobs" / digest[:2]
    blob_dir.mkdir(parents=True, exist_ok=True)
    final_path = blob_dir / digest
    # ext4 prjquota forbids cross-project rename() (EXDEV); stage in scratch, copy into
    # workspace temp file, atomically replace within workspace, then remove scratch stage.
    ws_tmp = blob_dir / f".{uuid4().hex}.tmp"
    try:
        shutil.copyfile(stage, ws_tmp)
        os.replace(ws_tmp, final_path)
    finally:
        ws_tmp.unlink(missing_ok=True)
        stage.unlink(missing_ok=True)
    rel_path = str(final_path.relative_to(paths.root))
    file_id = str(uuid4())
    now = _utc_now()
    with immediate_transaction(business_engine) as conn:
        conn.execute(
            text(
                "INSERT INTO file_records "
                "(id, original_name, media_type, size_bytes, content_sha256, created_at) "
                "VALUES (:id, :name, 'application/octet-stream', :size, :sha, :now)"
            ),
            {
                "id": file_id,
                "name": filename,
                "size": len(payload),
                "sha": digest,
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO file_content_locations "
                "(file_id, storage_provider, storage_state, local_relative_path, verified_at) "
                "VALUES (:id, 'local', 'available', :rel, :now)"
            ),
            {"id": file_id, "rel": rel_path, "now": now},
        )
    return len(payload)


def _probe_logical_507(admission: FreeStorageAdmission, growth_bytes: int, purpose: str) -> bool:
    try:
        with admission.reserve_request(
            growth_bytes, write=True, source_epoch=1, purpose=purpose
        ) as outcome:
            outcome.status_code = 400
    except HostedAccessError as exc:
        return exc.status == HTTP_INSUFFICIENT_STORAGE
    return False


@dataclass
class _WorkloadContext:
    business_engine: Engine
    paths: WorkspacePaths
    scratch_dir: Path
    usage: UsageAccountingStore
    admission: FreeStorageAdmission
    target_bytes: int
    peaks: dict[str, dict[str, int]]
    trees: dict[str, Path]


def _run_database_heavy(ctx: _WorkloadContext) -> tuple[int, bool]:
    with immediate_transaction(ctx.business_engine) as conn:
        conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS _h04_sizing_records ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "category TEXT NOT NULL, "
            "payload TEXT NOT NULL)"
        )
    chunk_text = "P" * 4000
    batch_rows = 32
    items_written = 0
    while True:
        snap = ctx.usage.refresh_usage_state()
        reserve_estimate = batch_rows * 4600
        if snap.used_bytes + reserve_estimate > ctx.target_bytes:
            break
        with ctx.admission.reserve_request(
            reserve_estimate, write=True, source_epoch=1, purpose="db_sizing_batch"
        ) as outcome:
            with immediate_transaction(ctx.business_engine) as conn:
                conn.execute(
                    text(
                        "INSERT INTO _h04_sizing_records (category, payload) "
                        "VALUES (:cat, :payload)"
                    ),
                    [
                        {"cat": f"unit-ledger-{items_written + i}", "payload": chunk_text}
                        for i in range(batch_rows)
                    ],
                )
            items_written += batch_rows
            outcome.status_code = 200
        _update_peaks(ctx.peaks, ctx.trees)

    triggered_507 = _probe_logical_507(
        ctx.admission, max(100_000, ctx.target_bytes // 4), "db_over_limit"
    )
    with closing(sqlite3.connect(ctx.paths.database)) as raw:
        raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        _update_peaks(ctx.peaks, ctx.trees)
        raw.execute("VACUUM")
        _update_peaks(ctx.peaks, ctx.trees)
    return items_written, triggered_507


def _run_retained_file_heavy(ctx: _WorkloadContext) -> tuple[int, bool]:
    chunk_size = min(2 * MIB, max(16_384, ctx.target_bytes // 10))
    items_written = 0
    while True:
        snap = ctx.usage.refresh_usage_state()
        if snap.used_bytes + chunk_size + 16_384 > ctx.target_bytes:
            break
        with ctx.admission.reserve_request(
            chunk_size + 8192, write=True, source_epoch=1, purpose="file_upload"
        ) as outcome:
            header = f"blob-{items_written:08d}-".encode()
            payload = (header * ((chunk_size // len(header)) + 1))[:chunk_size]
            _insert_retained_file(
                ctx.business_engine,
                ctx.paths,
                ctx.scratch_dir,
                payload,
                f"attachment-{items_written}.bin",
            )
            items_written += 1
            outcome.status_code = 200
        _update_peaks(ctx.peaks, ctx.trees)

    triggered_507 = _probe_logical_507(ctx.admission, chunk_size + 16_384, "file_over_limit")
    return items_written, triggered_507


def _run_many_small_files_history(ctx: _WorkloadContext) -> tuple[int, bool]:
    small_size = 16_384 if ctx.target_bytes >= FULL_TARGET_THRESHOLD else 2048
    max_files = min(3000, max(40, ctx.target_bytes // (small_size + 1024)))
    items_written = 0
    while items_written < max_files:
        snap = ctx.usage.refresh_usage_state()
        if snap.used_bytes + small_size + 8192 > ctx.target_bytes:
            break
        with ctx.admission.reserve_request(
            small_size + 4096, write=True, source_epoch=1, purpose="small_receipt"
        ) as outcome:
            header = f"rcpt-{items_written:08d}-".encode()
            payload = (header * ((small_size // len(header)) + 1))[:small_size]
            _insert_retained_file(
                ctx.business_engine,
                ctx.paths,
                ctx.scratch_dir,
                payload,
                f"receipt-{items_written}.pdf",
            )
            items_written += 1
            outcome.status_code = 200
        if items_written % 25 == 0:
            _update_peaks(ctx.peaks, ctx.trees)

    remaining = max(0, ctx.target_bytes - ctx.usage.refresh_usage_state().used_bytes)
    triggered_507 = _probe_logical_507(ctx.admission, remaining + 8192, "small_over_limit")
    return items_written, triggered_507


def run_workload(
    shape: str,
    *,
    workspace_dir: Path,
    control_dir: Path,
    scratch_dir: Path,
    target_bytes: int = FREE_V1_USABLE_BYTES,
) -> dict[str, object]:
    """Execute one H04.9 sizing workload shape and return measured high-water marks."""
    for directory in (workspace_dir, control_dir, scratch_dir):
        directory.mkdir(parents=True, exist_ok=True)
    trees = {"workspace": workspace_dir, "control": control_dir, "scratch": scratch_dir}
    peaks = {role: {"peak_bytes": 0, "peak_inodes": 0} for role in trees}

    paths, business_engine = _init_workspace(workspace_dir, scratch_dir)
    access_engine, usage, admission = _init_access_store(
        control_dir, business_engine, usable_bytes=target_bytes
    )
    _update_peaks(peaks, trees)
    ctx = _WorkloadContext(
        business_engine=business_engine,
        paths=paths,
        scratch_dir=scratch_dir,
        usage=usage,
        admission=admission,
        target_bytes=target_bytes,
        peaks=peaks,
        trees=trees,
    )

    try:
        if shape == "database_heavy":
            items_written, logical_507 = _run_database_heavy(ctx)
        elif shape == "retained_file_heavy":
            items_written, logical_507 = _run_retained_file_heavy(ctx)
        elif shape == "many_small_files_history":
            items_written, logical_507 = _run_many_small_files_history(ctx)
        else:
            raise ValueError(f"Unknown workload shape: {shape}")

        final_usage = measure_logical_usage(business_engine)
        usage.refresh_usage_state()
        _update_peaks(peaks, trees)
        return {
            "shape": shape,
            "target_bytes": target_bytes,
            "items_written": items_written,
            "committed_db_bytes": final_usage.committed_db_bytes,
            "retained_file_bytes": final_usage.retained_file_bytes,
            "logical_used_bytes": final_usage.used_bytes,
            "logical_507_triggered": logical_507,
            "trees": peaks,
        }
    finally:
        business_engine.dispose()
        access_engine.dispose()


def _exhaust_bytes(workspace_dir: Path) -> int | None:
    filler = workspace_dir / "byte_exhaustion.bin"
    chunk = b"Q" * MIB
    try:
        with filler.open("wb") as handle:
            for _ in range(MAX_EXHAUSTION_MIB):
                handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
    except OSError as exc:
        return exc.errno
    finally:
        filler.unlink(missing_ok=True)
    return None


def _exhaust_inodes(workspace_dir: Path) -> int | None:
    inode_dir = workspace_dir / "inode_exhaustion"
    inode_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        for index in range(MAX_EXHAUSTION_FILES):
            item = inode_dir / f"f{index}"
            item.write_bytes(b"")
            created.append(item)
    except OSError as exc:
        return exc.errno
    finally:
        for item in created:
            item.unlink(missing_ok=True)
        inode_dir.rmdir()
    return None


def run_exhaustion_fault(
    kind: str,
    *,
    workspace_dir: Path,
    control_dir: Path,
    scratch_dir: Path,
) -> dict[str, object]:
    """Run independent physical byte or inode exhaustion + rollback/reconciliation proof."""
    paths, business_engine = _init_workspace(workspace_dir, scratch_dir)
    access_engine, usage, admission = _init_access_store(
        control_dir, business_engine, usable_bytes=FREE_V1_USABLE_BYTES
    )
    try:
        with immediate_transaction(business_engine) as conn:
            conn.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS _h04_ack (id INTEGER PRIMARY KEY, label TEXT NOT NULL)"
            )
            conn.execute(text("INSERT INTO _h04_ack (id, label) VALUES (1, 'acknowledged')"))

        res = usage.reserve(
            str(uuid4()),
            sha256(f"fault-{kind}".encode()).hexdigest(),
            reserved_bytes=MIB,
            purpose=f"fault_{kind}",
            source_epoch=1,
        )
        if kind == "byte_exhaustion":
            observed_errno = _exhaust_bytes(workspace_dir)
        elif kind == "inode_exhaustion":
            observed_errno = _exhaust_inodes(workspace_dir)
        else:
            raise ValueError(f"Unknown exhaustion kind: {kind}")

        usage.mark_unknown(res.reservation_id)
        _, reconciled_count = usage.reconcile_unknown(include_held=True)
        with closing(sqlite3.connect(paths.database)) as raw:
            integrity = raw.execute("PRAGMA integrity_check").fetchone()[0]
            ack_label = raw.execute("SELECT label FROM _h04_ack WHERE id = 1").fetchone()[0]

        http_507_observed = _probe_logical_507(
            admission, FREE_V1_USABLE_BYTES + 1, f"post_fault_507_{kind}"
        )
        return {
            "kind": kind,
            "errno": observed_errno,
            "sqlite_integrity_ok": integrity == "ok",
            "acknowledged_rows_preserved": ack_label == "acknowledged",
            "reservations_reconciled": reconciled_count >= 1,
            "http_507_observed": http_507_observed,
        }
    finally:
        business_engine.dispose()
        access_engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="H04.9 Free sizing qualification actor")
    parser.add_argument(
        "mode",
        choices=(
            "database_heavy",
            "retained_file_heavy",
            "many_small_files_history",
            "byte_exhaustion",
            "inode_exhaustion",
        ),
    )
    parser.add_argument("--workspace", type=Path, default=Path("/workspace"))
    parser.add_argument("--control", type=Path, default=Path("/control"))
    parser.add_argument("--scratch", type=Path, default=Path("/scratch"))
    parser.add_argument("--target-bytes", type=int, default=FREE_V1_USABLE_BYTES)
    args = parser.parse_args(argv)

    if args.mode in ("byte_exhaustion", "inode_exhaustion"):
        result = run_exhaustion_fault(
            args.mode,
            workspace_dir=args.workspace,
            control_dir=args.control,
            scratch_dir=args.scratch,
        )
    else:
        result = run_workload(
            args.mode,
            workspace_dir=args.workspace,
            control_dir=args.control,
            scratch_dir=args.scratch,
            target_bytes=args.target_bytes,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Live GCP R2 + Cloud KMS + epm-backup-proxy end-to-end recovery proof (H06.6).

Runs on epm-h02-host with real Cloudflare R2 credentials (from GCP Secret Manager)
and real GCP Cloud KMS keys (`admin-control-kek` and `operator-workspace-kek`).
Uses a disposable UUID deployment prefix and deletes all created R2 objects in
`finally:`. Never prints or writes any secret material.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

from app.modules.host_agent.infrastructure.backup_proxy import (
    BackupProxyHandler,
    BackupProxyServer,
    InventoryPeerResolver,
    UnixBackupProxyClient,
    backup_proxy_listener,
    load_r2_credentials,
)
from app.modules.hosted_recovery.domain.models import (
    BackupProxyDenied,
    EnvelopeContext,
    HostedRecoveryError,
    RecoveryCryptoError,
    RecoveryIntegrityError,
)
from app.modules.hosted_recovery.infrastructure.engine import (
    ChunkedAeadBackupEngine,
    DatabaseInput,
    RetainedFileInput,
)
from app.modules.hosted_recovery.infrastructure.kms_provider import CloudKmsEnvelopeProvider
from app.modules.hosted_recovery.infrastructure.r2_store import R2ObjectStore
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore

REPO_ROOT = Path(__file__).resolve().parents[4]
APPLICATION_ROOT = REPO_ROOT / "application"


@dataclass(frozen=True)
class LiveProofContext:
    tmp: Path
    inventory_path: Path
    deployment_id: str
    operator_id: str
    workspace_id: str
    admin_key_ref: str
    operator_key_ref: str
    object_store: R2ObjectStore
    kms: CloudKmsEnvelopeProvider


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _create_sample_sqlite(path: Path, marker: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE proof_items (id INTEGER PRIMARY KEY, label TEXT NOT NULL)")
        conn.execute("INSERT INTO proof_items (label) VALUES (?)", (marker,))
        conn.commit()


def _seed_host_inventory(ctx: LiveProofContext, *, host_uid: int, host_gid: int) -> None:
    initialize_store(
        HostedStore.HOST_INVENTORY,
        ctx.inventory_path,
        application_directory=APPLICATION_ROOT,
    )
    now_ms = int(time.time() * 1000)
    with sqlite3.connect(ctx.inventory_path) as conn:
        conn.execute(
            "INSERT INTO host_identity "
            "(id, host_id, deployment_id, filesystem_identity, agent_contract_version, created_at) "
            "VALUES (1, ?, ?, ?, ?, ?)",
            (str(uuid4()), ctx.deployment_id, "ext4:prjquota", "h06.6", now_ms),
        )
        conn.execute(
            "INSERT INTO operator_principals "
            "(operator_id, workspace_id, host_uid, host_gid, assigned_at, revision) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            (ctx.operator_id, ctx.workspace_id, host_uid, host_gid, now_ms),
        )
        conn.commit()


def _verify_admin_negative_controls(
    ctx: LiveProofContext,
    client: UnixBackupProxyClient,
    engine: ChunkedAeadBackupEngine,
    *,
    point_id: str,
    backup_result,
) -> dict[str, bool]:
    cross_key_denied = False
    try:
        client.kms_wrap(ctx.operator_key_ref, os.urandom(32), aad=b"cross-key")
    except BackupProxyDenied:
        cross_key_denied = True
    if not cross_key_denied:
        raise RuntimeError("Admin UID was not denied operator KMS key.")

    traversal_denied = False
    try:
        client._request(
            {
                "op": "put_object",
                "key": "../escape.bin",
                "sha256": sha256(b"nope").hexdigest(),
            },
            b"nope",
        )
    except BackupProxyDenied:
        traversal_denied = True
    if not traversal_denied:
        raise RuntimeError("Path traversal key was not denied by backup proxy.")

    prefix = f"deployments/{ctx.deployment_id}/control/"
    chunk_keys = [k for k in ctx.object_store.list_objects(prefix) if "/chunks/" in k]
    if not chunk_keys:
        raise RuntimeError("Expected at least one chunk object in R2 for tamper test.")
    tampered_bytes = b"corrupted-ciphertext-payload"
    ctx.object_store.put_object(
        chunk_keys[0],
        tampered_bytes,
        sha256_hex=sha256(tampered_bytes).hexdigest(),
    )
    tamper_dir = ctx.tmp / "admin-tamper"
    tamper_dir.mkdir()
    tamper_rejected = False
    try:
        engine.restore_point(
            manifest_ref=backup_result.manifest_ref,
            expected_deployment_id=ctx.deployment_id,
            expected_scope_kind="control",
            destination_dir=tamper_dir,
            expected_point_id=point_id,
            expected_manifest_sha256=backup_result.manifest_sha256,
        )
    except HostedRecoveryError as error:
        tamper_rejected = isinstance(error, (RecoveryIntegrityError, RecoveryCryptoError))
    if not tamper_rejected:
        raise RuntimeError("Tampered R2 chunk was not rejected during restore.")

    return {
        "cross_key_denied": cross_key_denied,
        "path_traversal_denied": traversal_denied,
        "tampered_chunk_rejected": tamper_rejected,
    }


def _run_admin_proof(ctx: LiveProofContext) -> dict[str, object]:
    resolver = InventoryPeerResolver(
        ctx.inventory_path,
        application_directory=APPLICATION_ROOT,
        expected_deployment_id=ctx.deployment_id,
        admin_uid=os.getuid(),
        operator_key_refs={ctx.operator_key_ref},
        control_key_refs={ctx.admin_key_ref},
    )
    handler = BackupProxyHandler(
        object_store=ctx.object_store,
        kms=ctx.kms,
        peer_resolver=resolver.resolve,
    )
    sock_path = ctx.tmp / "admin-proxy.sock"
    with backup_proxy_listener(sock_path) as listener:
        server = BackupProxyServer(listener, handler)
        server.start()
        try:
            client = UnixBackupProxyClient(sock_path, expected_proxy_uid=os.getuid())
            engine = ChunkedAeadBackupEngine(client)

            src_dir = ctx.tmp / "admin-src"
            src_dir.mkdir()
            admin_db = src_dir / "admin.sqlite"
            _create_sample_sqlite(admin_db, "h066-admin-live-proof")
            expected_sha = _sha256_file(admin_db)

            point_id = str(uuid4())
            envelope_ctx = EnvelopeContext(
                deployment_id=ctx.deployment_id,
                scope_kind="control",
                operator_id=None,
                workspace_id=None,
                point_id=point_id,
                key_ref=ctx.admin_key_ref,
                schema_revisions={"admin": "admin_0001_initial"},
            )
            t0 = time.monotonic()
            result = engine.create_point(
                context=envelope_ctx,
                captured_at=int(time.time() * 1000),
                business_revision="rev-1",
                files_generation="gen-1",
                source_generation=1,
                release_ref="pilot0-h06.6",
                databases=[DatabaseInput(filename="admin.sqlite", path=admin_db)],
                full_readback=True,
            )
            capture_ms = int((time.monotonic() - t0) * 1000)

            restore_dir = ctx.tmp / "admin-restore"
            restore_dir.mkdir()
            t1 = time.monotonic()
            restored = engine.restore_point(
                manifest_ref=result.manifest_ref,
                expected_deployment_id=ctx.deployment_id,
                expected_scope_kind="control",
                destination_dir=restore_dir,
                expected_point_id=point_id,
                expected_manifest_sha256=result.manifest_sha256,
            )
            restore_ms = int((time.monotonic() - t1) * 1000)
            restored_sha = _sha256_file(restore_dir / "admin.sqlite")
            if restored_sha != expected_sha:
                raise RuntimeError("Admin restored SQLite digest mismatch.")
            with sqlite3.connect(restore_dir / "admin.sqlite") as conn:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Admin restored SQLite failed integrity_check.")

            negatives = _verify_admin_negative_controls(
                ctx,
                client,
                engine,
                point_id=point_id,
                backup_result=result,
            )
            return {
                "status": "passed",
                "point_id": point_id,
                "capture_ms": capture_ms,
                "restore_ms": restore_ms,
                "uploaded_chunks": result.uploaded_chunks,
                "verified_chunks": restored.verified_chunks,
                "restored_sha256": restored_sha,
                **negatives,
            }
        finally:
            server.stop()


def _run_operator_proof(ctx: LiveProofContext) -> dict[str, object]:
    resolver = InventoryPeerResolver(
        ctx.inventory_path,
        application_directory=APPLICATION_ROOT,
        expected_deployment_id=ctx.deployment_id,
        admin_uid=999999999,
        operator_key_refs={ctx.operator_key_ref},
        control_key_refs={ctx.admin_key_ref},
    )
    handler = BackupProxyHandler(
        object_store=ctx.object_store,
        kms=ctx.kms,
        peer_resolver=resolver.resolve,
    )
    sock_path = ctx.tmp / "operator-proxy.sock"
    with backup_proxy_listener(sock_path) as listener:
        server = BackupProxyServer(listener, handler)
        server.start()
        try:
            client = UnixBackupProxyClient(sock_path, expected_proxy_uid=os.getuid())
            engine = ChunkedAeadBackupEngine(client)

            src_dir = ctx.tmp / "op-src"
            src_dir.mkdir()
            biz_db = src_dir / "business.sqlite"
            _create_sample_sqlite(biz_db, "h066-operator-live-proof")
            retained = src_dir / "lease-doc.txt"
            retained.write_text(
                "Pilot 0 live encrypted R2+KMS attachment proof.\n", encoding="utf-8"
            )
            expected_db_sha = _sha256_file(biz_db)
            expected_file_sha = _sha256_file(retained)

            point_id = str(uuid4())
            envelope_ctx = EnvelopeContext(
                deployment_id=ctx.deployment_id,
                scope_kind="operator",
                operator_id=ctx.operator_id,
                workspace_id=ctx.workspace_id,
                point_id=point_id,
                key_ref=ctx.operator_key_ref,
                schema_revisions={"business": "20260401_0001"},
            )
            t0 = time.monotonic()
            result = engine.create_point(
                context=envelope_ctx,
                captured_at=int(time.time() * 1000),
                business_revision="rev-op-1",
                files_generation="gen-op-1",
                source_generation=1,
                release_ref="pilot0-h06.6",
                databases=[DatabaseInput(filename="business.sqlite", path=biz_db)],
                files=[RetainedFileInput(relative_path="docs/lease-doc.txt", path=retained)],
                full_readback=True,
            )
            capture_ms = int((time.monotonic() - t0) * 1000)

            restore_dir = ctx.tmp / "op-restore"
            restore_dir.mkdir()
            t1 = time.monotonic()
            restored = engine.restore_point(
                manifest_ref=result.manifest_ref,
                expected_deployment_id=ctx.deployment_id,
                expected_scope_kind="operator",
                expected_operator_id=ctx.operator_id,
                expected_workspace_id=ctx.workspace_id,
                destination_dir=restore_dir,
                expected_point_id=point_id,
                expected_manifest_sha256=result.manifest_sha256,
            )
            restore_ms = int((time.monotonic() - t1) * 1000)
            restored_db_sha = _sha256_file(restore_dir / "business.sqlite")
            restored_file_sha = _sha256_file(restore_dir / "files" / "docs" / "lease-doc.txt")
            if restored_db_sha != expected_db_sha or restored_file_sha != expected_file_sha:
                raise RuntimeError("Operator restored files digest mismatch.")

            cross_key_denied = False
            try:
                client.kms_wrap(ctx.admin_key_ref, os.urandom(32), aad=b"cross-key")
            except BackupProxyDenied:
                cross_key_denied = True
            if not cross_key_denied:
                raise RuntimeError("Operator UID was not denied admin KMS key.")

            return {
                "status": "passed",
                "point_id": point_id,
                "capture_ms": capture_ms,
                "restore_ms": restore_ms,
                "uploaded_chunks": result.uploaded_chunks,
                "verified_chunks": restored.verified_chunks,
                "restored_db_sha256": restored_db_sha,
                "restored_file_sha256": restored_file_sha,
                "cross_key_denied": cross_key_denied,
            }
        finally:
            server.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Live GCP R2 + Cloud KMS + backup-proxy proof.")
    parser.add_argument("--credentials-file", type=Path, required=True)
    parser.add_argument("--admin-key-ref", required=True)
    parser.add_argument("--operator-key-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    creds = load_r2_credentials(args.credentials_file)
    object_store = R2ObjectStore(
        endpoint_url=creds["endpoint_url"],
        bucket=creds["bucket"],
        access_key_id=creds["access_key_id"],
        secret_access_key=creds["secret_access_key"],
    )
    kms = CloudKmsEnvelopeProvider()

    deployment_id = str(uuid4())
    operator_id = str(uuid4())
    workspace_id = str(uuid4())
    prefix = f"deployments/{deployment_id}/"

    cleanup_deleted = 0
    cleanup_remaining = -1
    try:
        with TemporaryDirectory(prefix="h066-live-r2-kms-") as td:
            tmp = Path(td).resolve()
            tmp.chmod(0o700)
            ctx = LiveProofContext(
                tmp=tmp,
                inventory_path=tmp / "host_inventory.sqlite",
                deployment_id=deployment_id,
                operator_id=operator_id,
                workspace_id=workspace_id,
                admin_key_ref=args.admin_key_ref,
                operator_key_ref=args.operator_key_ref,
                object_store=object_store,
                kms=kms,
            )
            _seed_host_inventory(ctx, host_uid=os.getuid(), host_gid=os.getgid())
            admin_result = _run_admin_proof(ctx)
            operator_result = _run_operator_proof(ctx)
    finally:
        keys = object_store.list_objects(prefix)
        for key in keys:
            object_store.delete_object(key)
            cleanup_deleted += 1
        cleanup_remaining = len(object_store.list_objects(prefix))

    if cleanup_remaining != 0:
        raise RuntimeError(f"Disposable R2 prefix cleanup left {cleanup_remaining} objects.")

    report = {
        "version": 1,
        "proof": "live_r2_kms_backup_proxy_recovery",
        "owner": "H06.6",
        "status": "passed",
        "recorded_at_ms": int(time.time() * 1000),
        "environment": {
            "host": os.uname().nodename,
            "kernel": os.uname().release,
            "r2_bucket": creds["bucket"],
            "admin_key_ref": args.admin_key_ref,
            "operator_key_ref": args.operator_key_ref,
            "disposable_deployment_id": deployment_id,
        },
        "cases": {
            "admin_control_recovery": admin_result,
            "operator_workspace_recovery": operator_result,
            "disposable_r2_cleanup": {
                "status": "passed",
                "deleted_objects": cleanup_deleted,
                "remaining_objects": cleanup_remaining,
            },
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

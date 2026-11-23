"""H05.3 tests: internal workspace backup runner, retention, crash reconciliation, alerting & D12."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from sqlalchemy import text

from app.modules.host_agent.infrastructure.backup_proxy import (
    BackupProxyHandler,
    CallerPrincipal,
)
from app.modules.hosted_admin.infrastructure.recovery_status_ingest import (
    RecoveryStatusIngestService,
    RecoverySummaryDenied,
    WorkspaceProtectionSummary,
    sign_protection_summary,
)
from app.modules.hosted_recovery.domain.models import BackupProxyUnavailable, ObjectMetadata
from app.modules.hosted_recovery.infrastructure.alerting import (
    DeduplicatingAlertEmitter,
    RecoveryAlert,
)
from app.modules.hosted_recovery.infrastructure.engine import ChunkedAeadBackupEngine
from app.modules.hosted_recovery.infrastructure.kms_provider import LocalAesKmsProvider
from app.modules.hosted_recovery.infrastructure.r2_store import LocalDirectoryObjectStore
from app.modules.workspace.application.recovery_contracts import (
    Capture,
    WorkspaceRecoveryCommand,
)
from app.modules.workspace.infrastructure.hosted_recovery import (
    HostedWorkspaceRecoveryService,
    OVERDUE_THRESHOLD_MS,
    kms_ref_to_db_ref,
    object_key_for_manifest_ref,
)
from app.platform.hosted_contracts.authority import (
    ObservationQuery,
    OperatorAuthority,
    ServiceAuthority,
)
from app.platform.hosted_contracts.operations import (
    CommandIntent,
    OperationState,
    SemanticConflict,
)
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import WorkspaceScope
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine

APP_DIR = Path(__file__).resolve().parents[6]
DEPLOYMENT_ID = "00000000-0000-4000-8000-000000000002"
OP_ID = "00000000-0000-4000-8000-000000000011"
WS_ID = "00000000-0000-4000-8000-000000000012"
KMS_KEY = (
    "projects/epm-demo/locations/us-west1/keyRings/epm-hosted/"
    "cryptoKeys/operator-backup/cryptoKeyVersions/1"
)
BIZ_SCHEMA = "20260401_0001"
ACC_SCHEMA = "access_0001_initial"


class _FakeClock:
    def __init__(self, start_ms: int = 1_700_000_000_000):
        self.now = start_ms

    def __call__(self) -> int:
        return self.now

    def advance(self, delta_ms: int) -> int:
        self.now += delta_ms
        return self.now


class _MemoryAlertSink:
    def __init__(self):
        self.alerts: list[RecoveryAlert] = []

    def emit(self, alert: RecoveryAlert) -> None:
        self.alerts.append(alert)


class _DirectTransport:
    def __init__(self, handler: BackupProxyHandler, uid: int):
        self._handler = handler
        self._uid = uid
        self.fail_uploads = False

    def _call(self, header: dict[str, object], body: bytes = b""):
        return self._handler.dispatch(self._uid, {"version": 1, **header}, body)

    def put_object(self, relative_key: str, data: bytes) -> ObjectMetadata:
        if self.fail_uploads:
            raise BackupProxyUnavailable("Simulated R2 outage.")
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

    def list_objects(self, subprefix: str = "", *, max_keys: int = 1000) -> list[str]:
        resp, _ = self._call({"op": "list_objects", "subprefix": subprefix, "max_keys": max_keys})
        return list(resp["keys"])

    def kms_wrap(self, key_ref: str, plaintext_dek: bytes, *, aad: bytes) -> bytes:
        import base64

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
        import base64

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
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE properties (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
        conn.execute(
            "CREATE TABLE file_records ("
            "id TEXT PRIMARY KEY, content_sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE file_content_locations ("
            "file_id TEXT PRIMARY KEY, storage_provider TEXT NOT NULL, "
            "storage_state TEXT NOT NULL, local_relative_path TEXT)"
        )
        conn.execute("INSERT INTO properties VALUES ('p1', 'Maple Street')")
        conn.commit()
    finally:
        conn.close()


def _add_retained_file(
    db_path: Path, workspace_incarnation: Path, file_id: str, rel_path: str, content: bytes
) -> None:
    target = workspace_incarnation / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO file_records VALUES (?, ?, ?)",
            (file_id, digest, len(content)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO file_content_locations VALUES (?, 'local', 'available', ?)",
            (file_id, rel_path),
        )
        conn.commit()
    finally:
        conn.close()


def _setup_workspace_fixture(tmp_path: Path, *, summary_publisher=None):
    clock = _FakeClock()
    control_dir = tmp_path / "control"
    control_dir.mkdir(mode=0o700)
    rec_db = control_dir / "recovery.sqlite"
    acc_db = control_dir / "access.sqlite"
    initialize_store(HostedStore.RECOVERY, rec_db, application_directory=APP_DIR)
    initialize_store(HostedStore.HOSTED_ACCESS, acc_db, application_directory=APP_DIR)

    ws_root = tmp_path / "workspace"
    incarnation = ws_root / "incarnation-1"
    biz_db = incarnation / "property-management.sqlite"
    _init_business_db(biz_db)
    _add_retained_file(biz_db, incarnation, "f1", "files/lease-a.pdf", b"LEASE-ALPHA-" * 200)

    rec_engine = create_sqlite_engine(rec_db)
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
                "ws": WS_ID,
                "dep": f"dep:{DEPLOYMENT_ID}",
                "key_ref": kms_ref_to_db_ref(KMS_KEY),
                "prefix": f"deployments/{DEPLOYMENT_ID}/operators/{OP_ID}/",
            },
        )
        conn.execute(
            text(
                "INSERT INTO backup_state ("
                "id, last_point_id, protected_business_revision, protected_files_generation, "
                "protected_source_generation, protection_state, dirty_since, last_checked_at, "
                "last_backup_attempt_at, consecutive_failures, last_error_code, revision"
                ") VALUES (1, NULL, NULL, NULL, NULL, 'unknown', NULL, NULL, NULL, 0, NULL, 1)"
            )
        )

    acc_engine = create_sqlite_engine(acc_db)
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
                "'alpha@example.com', 'disabled', 1, 1, :now, :pol, 50000000, 1, NULL, 1, 1)"
            ),
            {
                "dep": DEPLOYMENT_ID,
                "op": OP_ID,
                "ws": WS_ID,
                "bind": str(uuid4()),
                "now": clock.now,
                "pol": str(uuid4()),
            },
        )

    store = LocalDirectoryObjectStore(tmp_path / "r2")
    kms = LocalAesKmsProvider({KMS_KEY: hashlib.sha256(b"kek-h053").digest()})
    principal = CallerPrincipal(
        uid=20001,
        scope_kind="operator",
        deployment_id=DEPLOYMENT_ID,
        operator_id=OP_ID,
        workspace_id=WS_ID,
        namespace_prefix=f"deployments/{DEPLOYMENT_ID}/operators/{OP_ID}/",
        allowed_key_refs=frozenset({KMS_KEY}),
    )
    handler = BackupProxyHandler(object_store=store, kms=kms, peer_resolver=lambda _: principal)
    transport = _DirectTransport(handler, 20001)
    backup_engine = ChunkedAeadBackupEngine(transport, chunk_size=4096)

    sink = _MemoryAlertSink()
    emitter = DeduplicatingAlertEmitter([sink])
    signer = Ed25519PrivateKey.generate()
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)

    service = HostedWorkspaceRecoveryService(
        recovery_engine=rec_engine,
        access_engine=acc_engine,
        backup_engine=backup_engine,
        operator_id=OP_ID,
        workspace_id=WS_ID,
        deployment_id=DEPLOYMENT_ID,
        workspace_root=ws_root,
        scratch_root=scratch,
        release_ref="rel-2026-11-22",
        business_schema_revision=BIZ_SCHEMA,
        access_schema_revision=ACC_SCHEMA,
        clock=clock,
        alert_emitter=emitter,
        summary_signer_key=signer,
        summary_key_id="op-key-1",
        summary_publisher=summary_publisher,
    )
    return {
        "service": service,
        "clock": clock,
        "rec_engine": rec_engine,
        "acc_engine": acc_engine,
        "biz_db": biz_db,
        "incarnation": incarnation,
        "scratch": scratch,
        "store": store,
        "transport": transport,
        "backup_engine": backup_engine,
        "sink": sink,
        "signer": signer,
    }


def _capture_cmd(
    key: str, *, policy_ref: str = "policy:free-nightly"
) -> tuple[ServiceAuthority, WorkspaceRecoveryCommand]:
    scope = WorkspaceScope(operator_id=OP_ID, workspace_id=WS_ID)
    actor = ServiceAuthority(
        deployment_id=DEPLOYMENT_ID,
        scope=scope,
        service="operator_backup",
        authenticated_channel_ref="channel:local-runner",
    )
    intent = CommandIntent(
        deployment_id=DEPLOYMENT_ID,
        scope=scope,
        kind="capture",
        expected_revision=1,
        access_epoch=1,
        payload=Capture(capture_policy_ref=policy_ref, expected_checkpoint_revision=1),
    )
    cmd = WorkspaceRecoveryCommand(
        operation_id=str(uuid4()),
        idempotency_key=key,
        intent=intent,
        request_hash=semantic_hash(intent),
    )
    return actor, cmd


def test_consistent_scheduled_capture_and_idempotency(tmp_path: Path):
    env = _setup_workspace_fixture(tmp_path)
    service: HostedWorkspaceRecoveryService = env["service"]

    actor, cmd = _capture_cmd("cap-1")
    out1 = service.execute(actor, cmd)
    assert out1.state == OperationState.SUCCEEDED
    assert out1.result is not None
    assert out1.result.phase == "captured"

    snap = service.read_protection_status()
    assert snap.protection_state == "healthy"
    assert snap.last_point_id == out1.result.point_id
    assert snap.dirty_since is None
    assert not list(env["scratch"].iterdir())

    # Exact replay returns original outcome without creating a second point.
    out_replay = service.execute(actor, cmd)
    assert out_replay.operation.operation_id == out1.operation.operation_id
    assert out_replay.result == out1.result

    # Reusing idempotency key with changed semantics -> SemanticConflict.
    _, conflict_cmd = _capture_cmd("cap-1", policy_ref="policy:different")
    with pytest.raises(SemanticConflict):
        service.execute(actor, conflict_cmd)

    # Original operation lookup works.
    looked_up = service.original(actor, out1.operation)
    assert looked_up is not None and looked_up.operation.operation_id == out1.operation.operation_id


def test_unchanged_file_only_checkpoints_and_unreadable_never_unchanged(tmp_path: Path):
    env = _setup_workspace_fixture(tmp_path)
    service: HostedWorkspaceRecoveryService = env["service"]
    clock: _FakeClock = env["clock"]

    actor, cmd1 = _capture_cmd("cap-initial")
    out1 = service.execute(actor, cmd1)
    assert out1.result is not None
    snap1 = service.read_protection_status()

    # Second capture with no changes -> unchanged, timestamps preserved, no new point.
    clock.advance(3_600_000)
    _, cmd2 = _capture_cmd("cap-unchanged")
    out2 = service.execute(actor, cmd2)
    assert out2.state == "succeeded"
    assert out2.result is not None and out2.result.point_id == out1.result.point_id
    snap2 = service.read_protection_status()
    assert snap2.protection_state == "unchanged"
    assert snap2.last_captured_at == snap1.last_captured_at
    assert snap2.last_verified_at == snap1.last_verified_at
    assert snap2.last_checked_at > snap1.last_checked_at

    # File-only change -> detected and produces a fresh verified point.
    clock.advance(3_600_000)
    _add_retained_file(
        env["biz_db"], env["incarnation"], "f2", "files/receipt-b.pdf", b"RECEIPT-BETA-" * 150
    )
    _, cmd3 = _capture_cmd("cap-file-only")
    out3 = service.execute(actor, cmd3)
    assert out3.state == "succeeded"
    assert out3.result is not None and out3.result.point_id != out1.result.point_id
    assert service.read_protection_status().protection_state == "healthy"

    # Unreadable/corrupt business DB -> unknown + alert, NEVER unchanged.
    clock.advance(3_600_000)
    env["biz_db"].write_bytes(b"corrupted-not-sqlite")
    _, cmd4 = _capture_cmd("cap-corrupt")
    out4 = service.execute(actor, cmd4)
    assert out4.state == "failed"
    assert service.read_protection_status().protection_state == "unknown"
    assert any(a.alert_kind == "backup_unknown" for a in env["sink"].alerts)


def test_source_commit_crash_startup_reconciliation_and_catchup(tmp_path: Path):
    env = _setup_workspace_fixture(tmp_path)
    service: HostedWorkspaceRecoveryService = env["service"]
    clock: _FakeClock = env["clock"]

    actor, cmd1 = _capture_cmd("cap-before-crash")
    service.execute(actor, cmd1)
    assert service.read_protection_status().protection_state == "healthy"

    # Simulate crash: interrupted running operation + committed DB write after last verified point.
    clock.advance(60_000)
    interrupted_op = str(uuid4())
    with env["rec_engine"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO recovery_operations ("
                "operation_id, kind, idempotency_key, request_hash, request_json, "
                "actor_kind, actor_ref, state, source_generation, result_json, error_code, "
                "created_at, updated_at, revision"
                ") VALUES ("
                ":op, 'backup', 'crashed-key', :hash, '{}', 'system', 'service:operator_backup', "
                "'running', 1, NULL, NULL, :now, :now, 1)"
            ),
            {"op": interrupted_op, "hash": "a" * 64, "now": clock.now},
        )
    conn = sqlite3.connect(env["biz_db"])
    try:
        conn.execute("INSERT INTO properties VALUES ('p2', 'Oak Avenue')")
        conn.commit()
    finally:
        conn.close()

    # Startup reconciliation marks interrupted op unknown and flags degraded protection.
    reconciled = service.reconcile_startup()
    assert reconciled.protection_state == "overdue"
    assert reconciled.dirty_since is not None
    with env["rec_engine"].connect() as rec_conn:
        state = rec_conn.execute(
            text("SELECT state FROM recovery_operations WHERE operation_id = :op"),
            {"op": interrupted_op},
        ).scalar_one()
        assert state == "unknown"
    assert any(a.alert_kind == "backup_overdue" for a in env["sink"].alerts)

    # Catch-up capture verifies the new changes and emits backup_recovered.
    clock.advance(60_000)
    _, cmd2 = _capture_cmd("cap-catchup")
    out2 = service.execute(actor, cmd2)
    assert out2.state == "succeeded"
    assert service.read_protection_status().protection_state == "healthy"
    assert any(a.alert_kind == "backup_recovered" for a in env["sink"].alerts)


def test_seven_points_incremental_retention_preserves_shared_chunks(tmp_path: Path):
    env = _setup_workspace_fixture(tmp_path)
    service: HostedWorkspaceRecoveryService = env["service"]
    clock: _FakeClock = env["clock"]

    point_ids: list[str] = []
    for idx in range(1, 10):
        clock.advance(86_400_000)
        conn = sqlite3.connect(env["biz_db"])
        try:
            conn.execute("INSERT INTO properties VALUES (?, ?)", (f"prop-{idx}", f"Unit {idx}"))
            conn.commit()
        finally:
            conn.close()
        actor, cmd = _capture_cmd(f"nightly-{idx}")
        out = service.execute(actor, cmd)
        assert out.state == "succeeded" and out.result is not None
        point_ids.append(out.result.point_id)

    op_scope = WorkspaceScope(operator_id=OP_ID, workspace_id=WS_ID)
    op_actor = OperatorAuthority(
        deployment_id=DEPLOYMENT_ID,
        scope=op_scope,
        identity_proof_ref="proof:op-session-1",
    )
    page = service.observe(
        op_actor,
        ObservationQuery(deployment_id=DEPLOYMENT_ID, scope=op_scope, limit=20),
    )
    assert len(page.items) == 7
    retained_ids = [item.resource_id for item in page.items]
    assert retained_ids == list(reversed(point_ids[2:]))

    with env["rec_engine"].connect() as rec_conn:
        pruned_states = {
            row["point_id"]: row["state"]
            for row in rec_conn.execute(
                text("SELECT point_id, state FROM recovery_points")
            ).mappings()
        }
    assert pruned_states[point_ids[0]] == "pruned"
    assert pruned_states[point_ids[1]] == "pruned"

    # Oldest retained point (point_ids[2]) still restores cleanly with shared lease-a.pdf intact!
    restore_dir = tmp_path / "restore-oldest-retained"
    restore_dir.mkdir(mode=0o700)
    restored = env["backup_engine"].restore_point(
        manifest_ref=object_key_for_manifest_ref(f"manifest:{point_ids[2]}"),
        expected_deployment_id=DEPLOYMENT_ID,
        expected_scope_kind="operator",
        expected_operator_id=OP_ID,
        expected_workspace_id=WS_ID,
        destination_dir=restore_dir,
    )
    assert restored.restored_files == ["files/lease-a.pdf"]
    assert (restore_dir / "files/files/lease-a.pdf").read_bytes() == b"LEASE-ALPHA-" * 200


def test_overdue_alerting_admin_outage_independence_and_signed_ingest(tmp_path: Path):
    # Initialize real admin.sqlite for D12 ingest verification.
    admin_dir = tmp_path / "admin"
    admin_dir.mkdir(mode=0o700)
    admin_db = admin_dir / "admin.sqlite"
    initialize_store(HostedStore.ADMIN, admin_db, application_directory=APP_DIR)
    admin_engine = create_sqlite_engine(admin_db)

    published_tokens: list[str] = []
    admin_down = {"flag": False}

    def _publisher(token: str) -> None:
        if admin_down["flag"]:
            raise RuntimeError("Admin service unreachable")
        published_tokens.append(token)

    env = _setup_workspace_fixture(tmp_path, summary_publisher=_publisher)
    service: HostedWorkspaceRecoveryService = env["service"]
    clock: _FakeClock = env["clock"]
    signer: Ed25519PrivateKey = env["signer"]

    # Seed storage_policies + operator row in admin.sqlite.
    pol_id = str(uuid4())
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO storage_policies ("
                "policy_id, plan_code, policy_version, usable_bytes, backup_interval_seconds, "
                "retained_nightly_points, keep_warm, created_at"
                ") VALUES (:pol, 'free', 1, 50000000, 86400, 7, 1, :now)"
            ),
            {"pol": pol_id, "now": clock.now},
        )
        conn.execute(
            text(
                "INSERT INTO operators ("
                "operator_id, workspace_id, display_name, invited_email, email_key, "
                "workspace_slug, issuer, subject, desired_policy_id, desired_access, "
                "setup_state, support_contact, access_epoch, revision, created_at, updated_at, "
                "retired_at"
                ") VALUES ("
                ":op, :ws, 'Alpha Operator', 'alpha@example.com', 'alpha@example.com', "
                "'alpha', 'firebase:epm-demo', 'sub-alpha', :pol, 'enabled', 'active', "
                "'support@epmdemo.xyz', 1, 1, :now, :now, NULL)"
            ),
            {"op": OP_ID, "ws": WS_ID, "pol": pol_id, "now": clock.now},
        )

    ingest = RecoveryStatusIngestService(
        admin_engine,
        resolve_public_key=lambda op, ws, kid: (
            signer.public_key() if (op, ws, kid) == (OP_ID, WS_ID, "op-key-1") else None
        ),
        clock=clock,
    )

    # 1. Capture succeeds even when Admin is completely down!
    admin_down["flag"] = True
    actor, cmd1 = _capture_cmd("cap-admin-down")
    out1 = service.execute(actor, cmd1)
    assert out1.state == "succeeded"
    assert service.read_protection_status().protection_state == "healthy"
    assert published_tokens == []

    # 2. When Admin is up, signed summary ingests cleanly; stale revisions are ignored.
    admin_down["flag"] = False
    token_healthy = service.build_signed_summary()
    assert token_healthy is not None
    res1 = ingest.ingest_signed(token_healthy)
    assert res1.applied is True and res1.reason == "inserted"
    res_dup = ingest.ingest_signed(token_healthy)
    assert res_dup.applied is False and res_dup.reason == "stale_revision"

    # 3. Forged signature / wrong key is rejected.
    rogue_key = Ed25519PrivateKey.generate()
    forged = sign_protection_summary(
        WorkspaceProtectionSummary(
            operator_id=OP_ID,
            workspace_id=WS_ID,
            source_epoch=1,
            source_revision=99,
            checked_at=clock.now,
            protection_state="healthy",
            key_id="op-key-1",
            issued_at=clock.now,
            expires_at=clock.now + 60_000,
        ),
        private_key=rogue_key,
    )
    with pytest.raises(RecoverySummaryDenied):
        ingest.ingest_signed(forged)

    # 4. Simulated R2 outage fails capture, deduplicates alerts, and updates Admin summary.
    conn = sqlite3.connect(env["biz_db"])
    try:
        conn.execute("INSERT INTO properties VALUES ('p-dirty', 'Dirty Lane')")
        conn.commit()
    finally:
        conn.close()
    env["transport"].fail_uploads = True
    clock.advance(60_000)
    out_fail1 = service.execute(*_capture_cmd("cap-fail-1"))
    assert out_fail1.state == "failed"
    assert service.read_protection_status().protection_state == "overdue"
    clock.advance(60_000)
    out_fail2 = service.execute(*_capture_cmd("cap-fail-2"))
    assert out_fail2.state == "failed"
    # Deduplicated: only ONE backup_failed alert emitted across 2 consecutive failures.
    failed_alerts = [a for a in env["sink"].alerts if a.alert_kind == "backup_failed"]
    assert len(failed_alerts) == 1

    # Latest published token updates Admin workspace_recovery_status to overdue.
    res_overdue = ingest.ingest_signed(published_tokens[-1])
    assert res_overdue.applied is True and res_overdue.reason == "updated"

    # 5. evaluate_freshness triggers backup_overdue when dirty_since crosses 28 hours.
    with env["rec_engine"].begin() as rec_conn:
        rec_conn.execute(
            text(
                "UPDATE backup_state SET protection_state = 'healthy', "
                "dirty_since = :dirty, revision = revision + 1 WHERE id = 1"
            ),
            {"dirty": clock.now},
        )
    clock.advance(OVERDUE_THRESHOLD_MS + 1000)
    fresh_snap = service.evaluate_freshness()
    assert fresh_snap.protection_state == "overdue"
    assert any(a.alert_kind == "backup_overdue" for a in env["sink"].alerts)

    # 6. Recovery clears alerts and emits backup_recovered.
    env["transport"].fail_uploads = False
    out_rec = service.execute(*_capture_cmd("cap-recover"))
    assert out_rec.state == "succeeded"
    assert service.read_protection_status().protection_state == "healthy"
    assert any(a.alert_kind == "backup_recovered" for a in env["sink"].alerts)

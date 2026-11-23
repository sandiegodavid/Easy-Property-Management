"""H05.6 tests: Admin control-plane backup, independent recovery mode & whole-host loss."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from app.modules.host_agent.infrastructure.backup_proxy import (
    BackupProxyHandler,
    CallerPrincipal,
)
from app.modules.hosted_admin.api.recovery_router import build_admin_recovery_router
from app.modules.hosted_admin.application.recovery_contracts import (
    AdminRecoveryCommand,
    CaptureControl,
)
from app.modules.hosted_admin.infrastructure.admin_recovery import (
    AdminControlRecoveryService,
    AdminRecoveryDenied,
    BootstrapRecoveryAuthority,
    BootstrapRecoveryPrincipal,
    build_host_loss_cli_parser,
    load_bootstrap_authority,
    reconstruct_on_clean_host,
)
from app.modules.hosted_recovery.infrastructure.engine import ChunkedAeadBackupEngine
from app.modules.hosted_recovery.infrastructure.kms_provider import LocalAesKmsProvider
from app.modules.hosted_recovery.infrastructure.r2_store import LocalDirectoryObjectStore
from app.modules.hosted_recovery.tests.test_h05_backup_runner_and_alerting import (
    APP_DIR,
    DEPLOYMENT_ID,
    _DirectTransport,
    _FakeClock,
)
from app.modules.hosted_recovery.tests.test_h05_clean_runtime_repair import (
    PRINCIPAL_ID,
    _seed_admin_db,
)
from app.modules.workspace.infrastructure.hosted_recovery import kms_ref_to_db_ref
from app.platform.hosted_contracts.authority import AdminRecoveryAuthority, ServiceAuthority
from app.platform.hosted_contracts.operations import CommandIntent, OperationState
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import DeploymentScope
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine

CTRL_KMS_KEY = (
    "projects/epm-demo/locations/us-west1/keyRings/epm-hosted/"
    "cryptoKeys/control-backup/cryptoKeyVersions/1"
)
HOST_ID = "00000000-0000-4000-8000-000000000201"


def _write_bootstrap_authority(path: Path) -> tuple[BootstrapRecoveryAuthority, str]:
    authority = BootstrapRecoveryAuthority(
        deployment_id=DEPLOYMENT_ID,
        principals=(
            BootstrapRecoveryPrincipal(
                issuer="firebase:epm-demo",
                subject="admin-sub",
                principal_ref=f"bootstrap:{PRINCIPAL_ID}",
            ),
        ),
    )
    path.write_text(authority.model_dump_json(), encoding="utf-8")
    os.chmod(path, 0o600)
    return load_bootstrap_authority(path)


def _setup_control_fixture(tmp_path: Path):
    clock = _FakeClock()
    control_root = tmp_path / "control-data"
    incarnation = control_root / "admin-incarnation-1"
    incarnation.mkdir(mode=0o700, parents=True)

    # Seed main admin.sqlite inside admin-incarnation-1.
    seed_stage = tmp_path / "seed-stage"
    seed_stage.mkdir(mode=0o700)
    seeded_admin_engine = _seed_admin_db(seed_stage, now_ms=clock.now)
    seeded_admin_engine.dispose()
    admin_db = incarnation / "admin.sqlite"
    admin_db.write_bytes((tmp_path / "seed-stage/admin/admin.sqlite").read_bytes())
    os.chmod(admin_db, 0o600)

    # Add an active admin_sessions row and an active pending operation to verify post-restore fencing.
    admin_engine = create_sqlite_engine(admin_db)
    msid = str(uuid4())
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO main.managed_identity_sessions ("
                "managed_session_id, cookie_hash, purpose, operator_id, issuer, subject, "
                "email_key, method, authenticated_at, mfa_verified_at, provider_valid_until, "
                "remembered_until, revocation_checked_at, revocation_valid_until, issued_at, "
                "revoked_at, revision"
                ") VALUES ("
                ":msid, :chash, 'admin', NULL, 'firebase:epm-demo', 'admin-sub', "
                "'admin@epmdemo.xyz', 'google_totp', :now, :now, :exp, :exp, :now, :rv, :now, "
                "NULL, 1)"
            ),
            {
                "msid": msid,
                "chash": "4" * 64,
                "now": clock.now,
                "exp": clock.now + 3_600_000,
                "rv": clock.now + 240_000,
            },
        )
        conn.execute(
            text(
                "INSERT INTO main.admin_sessions ("
                "session_hash, principal_id, csrf_hash, generation, authenticated_at, "
                "mfa_verified_at, expires_at, last_seen_at, revoked_at, managed_session_id, "
                "managed_valid_until, revocation_valid_until"
                ") VALUES ("
                ":sh, :pid, :ch, 1, :now, :now, :exp, :now, NULL, :msid, :exp, :rv)"
            ),
            {
                "sh": "1" * 64,
                "pid": PRINCIPAL_ID,
                "ch": "2" * 64,
                "now": clock.now,
                "exp": clock.now + 3_600_000,
                "msid": msid,
                "rv": clock.now + 240_000,
            },
        )
        conn.execute(
            text(
                "INSERT INTO main.operations ("
                "operation_id, operator_id, component_deployment_id, kind, idempotency_key, "
                "request_hash, request_json, actor_principal_id, system_actor, "
                "expected_revision, access_epoch, state, effect_reference, result_json, "
                "error_code, created_at, updated_at, revision"
                ") VALUES ("
                ":op_id, :operator_id, NULL, 'repair_runtime', 'old-job-1', :rh, '{}', :pid, NULL, "
                "1, 1, 'pending', NULL, NULL, NULL, :now, :now, 1)"
            ),
            {
                "op_id": str(uuid4()),
                "operator_id": "00000000-0000-4000-8000-000000000011",
                "rh": "3" * 64,
                "pid": PRINCIPAL_ID,
                "now": clock.now,
            },
        )
    admin_engine.dispose()

    # Seed host_inventory.sqlite inside admin-incarnation-1.
    inv_db = incarnation / "host_inventory.sqlite"
    initialize_store(HostedStore.HOST_INVENTORY, inv_db, application_directory=APP_DIR)
    inv_conn = sqlite3.connect(inv_db)
    try:
        inv_conn.execute(
            "INSERT INTO host_identity "
            "(id, host_id, deployment_id, filesystem_identity, agent_contract_version, created_at) "
            "VALUES (1, ?, ?, 'ext4:dev1', 'v1', ?)",
            (HOST_ID, DEPLOYMENT_ID, clock.now),
        )
        inv_conn.commit()
    finally:
        inv_conn.close()

    # Separate private admin-recovery.sqlite outside admin-incarnation-1.
    rec_dir = tmp_path / "admin-recovery-store"
    rec_dir.mkdir(mode=0o700)
    auth_path = rec_dir / "admin-recovery-authority.json"
    _, authority_ref = _write_bootstrap_authority(auth_path)
    admin_rec_db = rec_dir / "admin-recovery.sqlite"
    initialize_store(HostedStore.ADMIN_RECOVERY, admin_rec_db, application_directory=APP_DIR)
    admin_rec_engine = create_sqlite_engine(admin_rec_db)
    with admin_rec_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO admin_recovery_meta ("
                "id, deployment_id, incarnation_id, recovery_authority_ref, source_generation, "
                "active_admin_resource_ref, encryption_key_ref, namespace_prefix, created_at, revision"
                ") VALUES ("
                "1, :dep, :inc, :aref, 1, 'admin-incarnation-1', :kref, :prefix, :now, 1)"
            ),
            {
                "dep": DEPLOYMENT_ID,
                "inc": str(uuid4()),
                "aref": authority_ref,
                "kref": kms_ref_to_db_ref(CTRL_KMS_KEY),
                "prefix": f"deployments/{DEPLOYMENT_ID}/control/",
                "now": clock.now,
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
            {"now": clock.now},
        )

    store = LocalDirectoryObjectStore(tmp_path / "r2")
    kms = LocalAesKmsProvider({CTRL_KMS_KEY: hashlib.sha256(b"ctrl-kek-h056").digest()})
    ctrl_principal = CallerPrincipal(
        uid=10001,
        scope_kind="control",
        deployment_id=DEPLOYMENT_ID,
        operator_id=None,
        workspace_id=None,
        namespace_prefix=f"deployments/{DEPLOYMENT_ID}/control/",
        allowed_key_refs=frozenset({CTRL_KMS_KEY}),
    )
    handler = BackupProxyHandler(
        object_store=store, kms=kms, peer_resolver=lambda _: ctrl_principal
    )
    transport = _DirectTransport(handler, 10001)
    backup_engine = ChunkedAeadBackupEngine(transport, chunk_size=4096)

    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    service = AdminControlRecoveryService(
        admin_recovery_engine=admin_rec_engine,
        backup_engine=backup_engine,
        bootstrap_authority_path=auth_path,
        control_root=control_root,
        scratch_root=scratch,
        deployment_id=DEPLOYMENT_ID,
        release_ref="rel-2026-11-23",
        admin_schema_revision="admin_0001_initial",
        inventory_schema_revision="host_inventory_0001_initial",
        application_directory=APP_DIR,
        clock=clock,
    )
    return {
        "service": service,
        "clock": clock,
        "admin_db": admin_db,
        "admin_rec_db": admin_rec_db,
        "admin_rec_engine": admin_rec_engine,
        "auth_path": auth_path,
        "control_root": control_root,
        "scratch": scratch,
        "backup_engine": backup_engine,
    }


def _capture_control_cmd(key: str) -> tuple[ServiceAuthority, AdminRecoveryCommand]:
    actor = ServiceAuthority(
        deployment_id=DEPLOYMENT_ID,
        scope=DeploymentScope(),
        service="admin_backup",
        authenticated_channel_ref="internal:admin-backup",
    )
    intent = CommandIntent(
        deployment_id=DEPLOYMENT_ID,
        scope=DeploymentScope(),
        kind="capture_control",
        expected_revision=1,
        access_epoch=1,
        payload=CaptureControl(
            capture_policy_ref="policy:control-nightly", expected_checkpoint_revision=1
        ),
    )
    cmd = AdminRecoveryCommand(
        operation_id=str(uuid4()),
        idempotency_key=key,
        intent=intent,
        request_hash=semantic_hash(intent),
    )
    return actor, cmd


def test_separate_admin_recovery_loss_damaged_main_admin_db(tmp_path: Path):
    env = _setup_control_fixture(tmp_path)
    service: AdminControlRecoveryService = env["service"]
    clock: _FakeClock = env["clock"]

    # 1. Capture verified control-plane backup.
    cap_out = service.execute(*_capture_control_cmd("ctrl-cap-1"))
    assert cap_out.state == OperationState.SUCCEEDED and cap_out.result is not None
    point_id = cap_out.result.point_id

    # 2. Corrupt main admin.sqlite -> Admin recovery mode detected without touching admin.sqlite!
    env["admin_db"].write_bytes(b"CORRUPTED-ADMIN-DB")
    assert service.detect_admin_mode().mode == "recovery"

    # 3. Bootstrap authority rejects non-bootstrap principal and missing MFA.
    authority, _ = load_bootstrap_authority(env["auth_path"])
    with pytest.raises(AdminRecoveryDenied):
        authority.verify_identity(
            issuer="firebase:epm-demo", subject="operator-sub", mfa_verified_at=clock.now
        )
    with pytest.raises(AdminRecoveryDenied):
        authority.verify_identity(
            issuer="firebase:epm-demo", subject="admin-sub", mfa_verified_at=None
        )

    # 4. Exercise /api/admin/recovery/* HTTP router completely independently of admin.sqlite.
    app = FastAPI()

    def _auth(_request, _write: bool, req_hash: str | None) -> AdminRecoveryAuthority:
        return AdminRecoveryAuthority(
            deployment_id=DEPLOYMENT_ID,
            bootstrap_principal_ref=f"bootstrap:{PRINCIPAL_ID}",
            current_mfa_proof_ref="mfa:google-totp-1",
            step_up_at=clock.now,
            confirmed_request_hash=req_hash or ("0" * 64),
        )

    async def _read_body(request):
        return await request.json()

    app.include_router(
        build_admin_recovery_router(service, authenticate_recovery=_auth, read_body=_read_body)
    )
    client = TestClient(app)

    status_resp = client.get("/api/admin/recovery/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["mode"] == "recovery"
    assert status_resp.json()["catalog"]["items"][0]["resource_id"] == point_id

    prev_resp = client.post("/api/admin/recovery/preview", json={"point_id": point_id})
    assert prev_resp.status_code == 200
    preview_id = prev_resp.json()["previewId"]
    exact_hash = prev_resp.json()["exactRequestHash"]

    confirm_resp = client.post(
        "/api/admin/recovery/confirm",
        json={
            "point_id": point_id,
            "preview_id": preview_id,
            "idempotency_key": "ctrl-restore-1",
            "confirmed_request_hash": exact_hash,
        },
    )
    assert confirm_resp.status_code == 200
    op_id = confirm_resp.json()["operation"]["operation_id"]

    # Damaged prior admin.sqlite is preserved intact; new admin-incarnation-2 is active and healthy!
    assert env["admin_db"].read_bytes() == b"CORRUPTED-ADMIN-DB"
    assert service.detect_admin_mode().mode == "normal"
    assert service.detect_admin_mode().active_admin_resource_ref == "admin-incarnation-2"

    # Restored admin.sqlite advanced registry_generation, revoked historical sessions,
    # and marked historical pending operations unknown (never replayed!).
    restored_engine = create_sqlite_engine(env["control_root"] / "admin-incarnation-2/admin.sqlite")
    try:
        with restored_engine.connect() as conn:
            reg_gen = int(
                conn.execute(
                    text("SELECT registry_generation FROM main.control_meta WHERE id=1")
                ).scalar_one()
            )
            assert reg_gen == 2
            revoked = (
                conn.execute(text("SELECT revoked_at FROM main.admin_sessions")).scalars().all()
            )
            assert all(ts is not None for ts in revoked)
            op_states = conn.execute(text("SELECT state, error_code FROM main.operations")).all()
            assert op_states == [("unknown", "historical_after_control_restore")]
    finally:
        restored_engine.dispose()

    accept_resp = client.post("/api/admin/recovery/accept", json={"operation_id": op_id})
    assert accept_resp.status_code == 200
    assert accept_resp.json()["phase"] == "accepted"


def test_damaged_admin_recovery_db_and_whole_host_control_loss(tmp_path: Path):
    env = _setup_control_fixture(tmp_path)
    service: AdminControlRecoveryService = env["service"]
    clock: _FakeClock = env["clock"]

    # 1. Capture verified control-plane backup on old host.
    cap_out = service.execute(*_capture_control_cmd("ctrl-cap-before-host-loss"))
    assert cap_out.state == OperationState.SUCCEEDED and cap_out.result is not None
    point_id = cap_out.result.point_id

    # 2. Simulate whole-host loss (fresh host directory with zero local SQLite files).
    clean_host = tmp_path / "clean-host"
    clean_host.mkdir(mode=0o700)
    clean_control_root = clean_host / "control-data"
    clean_control_root.mkdir(mode=0o700)
    clean_scratch = clean_host / "scratch"
    clean_scratch.mkdir(mode=0o700)
    clean_auth = clean_host / "admin-recovery-authority.json"
    _write_bootstrap_authority(clean_auth)
    clean_rec_db = clean_host / "admin-recovery.sqlite"

    clean_service, reconstructed, new_incarnation = reconstruct_on_clean_host(
        admin_recovery_db_path=clean_rec_db,
        bootstrap_authority_path=clean_auth,
        control_root=clean_control_root,
        scratch_root=clean_scratch,
        backup_engine=env["backup_engine"],
        kms_key_ref=CTRL_KMS_KEY,
        release_ref="rel-2026-11-23",
        admin_schema_revision="admin_0001_initial",
        inventory_schema_revision="host_inventory_0001_initial",
        application_directory=APP_DIR,
        clock=clock,
    )
    assert new_incarnation
    assert reconstructed.scanned_manifests == 1
    assert reconstructed.imported_points == [point_id]

    # 3. Authenticated AdminRecoveryAuthority previews and confirms restore onto clean host.
    base_actor = AdminRecoveryAuthority(
        deployment_id=DEPLOYMENT_ID,
        bootstrap_principal_ref=f"bootstrap:{PRINCIPAL_ID}",
        current_mfa_proof_ref="mfa:google-totp-host-loss",
        step_up_at=clock.now,
        confirmed_request_hash="0" * 64,
    )
    preview = clean_service.preview_control_restore(base_actor, point_id=point_id)
    confirm_actor = AdminRecoveryAuthority(
        deployment_id=DEPLOYMENT_ID,
        bootstrap_principal_ref=f"bootstrap:{PRINCIPAL_ID}",
        current_mfa_proof_ref="mfa:google-totp-host-loss",
        step_up_at=clock.now,
        confirmed_request_hash=preview.exact_request_hash,
    )
    out = clean_service.confirm_control_restore(
        confirm_actor,
        point_id=point_id,
        preview_id=preview.preview_id,
        idempotency_key="clean-host-restore-1",
    )
    assert out.state == OperationState.SUCCEEDED
    assert clean_service.detect_admin_mode().mode == "normal"
    assert (clean_control_root / "admin-incarnation-2/admin.sqlite").is_file()
    assert (clean_control_root / "admin-incarnation-2/host_inventory.sqlite").is_file()

    # 4. Host-loss CLI parser is scoped strictly to control-plane recovery (no workspace args).
    parser = build_host_loss_cli_parser()
    option_names = {opt for action in parser._actions for opt in action.option_strings}
    assert "--admin-recovery-db" in option_names
    assert "--bootstrap-authority" in option_names
    assert not any("workspace" in opt for opt in option_names)

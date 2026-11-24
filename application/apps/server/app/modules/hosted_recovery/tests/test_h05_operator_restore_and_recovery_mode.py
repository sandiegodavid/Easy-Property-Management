"""H05.4 tests: operator-authorized restore, step-up confirmation, minimal recovery mode & fences."""

from __future__ import annotations

from pathlib import Path
import socket
import sqlite3
import tempfile
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from app.__main__ import _build_parser
from app.modules.host_agent.application.auth_routes import IdentityCookiePolicy
from app.modules.hosted_access.application.identity_evidence import (
    IdentityBinding,
    ManagedObservation,
    RecentAuthGrant,
)
from app.modules.hosted_access.infrastructure.handoff_signing import IdentitySigner
from app.modules.hosted_access.infrastructure.operator_identity_runtime import (
    OperatorIdentityInputs,
    create_minimal_recovery_app,
)
from app.modules.hosted_access.infrastructure.source_sessions import digest
from app.modules.hosted_recovery.tests.test_h05_backup_runner_and_alerting import (
    BIZ_SCHEMA,
    DEPLOYMENT_ID,
    OP_ID,
    WS_ID,
    _capture_cmd,
    _setup_workspace_fixture,
)
from app.modules.workspace.infrastructure.hosted_recovery import (
    HostedWorkspaceRecoveryService,
    RestoreDeniedError,
    RestoreNotFoundError,
)
from app.platform.hosted_contracts.authority import OperatorAuthority, OperatorRestoreAuthority
from app.platform.hosted_contracts.operations import OperationState
from app.platform.hosted_contracts.values import WorkspaceScope

SOURCE_ORIGIN = "https://alpha.epmdemo.xyz"
CENTRAL_ORIGIN = "https://auth.epmdemo.xyz"


def _enable_access_and_create_session(
    acc_engine,
    *,
    clock_ms: int,
    cookie_value: str,
    csrf_value: str,
    managed_session_id: str | None = None,
    epoch: int = 1,
) -> tuple[str, str]:
    session_id = str(uuid4())
    managed_id = managed_session_id or str(uuid4())
    with acc_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE access_meta SET subject = 'sub-alpha', effective_access = 'enabled', "
                "access_epoch = :epoch, revision = revision + 1 WHERE id = 1"
            ),
            {"epoch": epoch},
        )
        gen = int(
            conn.execute(
                text("SELECT session_generation FROM access_meta WHERE id = 1")
            ).scalar_one()
        )
        conn.execute(
            text(
                "INSERT INTO access_sessions ("
                "session_hash, csrf_hash, actor_subject, handoff_id, generation, access_epoch, "
                "issued_at, expires_at, managed_valid_until, last_seen_at, revoked_at, "
                "session_id, managed_session_id, managed_observation_revision, "
                "revocation_valid_until, remembered_until, remembered, display_label, "
                "renewed_from_session_id"
                ") VALUES ("
                ":shash, :chash, 'sub-alpha', :hid, :gen, :epoch, :now, :exp, :exp, :now, NULL, "
                ":sid, :msid, 1, :exp, :exp, 0, 'Test Device', NULL)"
            ),
            {
                "shash": digest(cookie_value),
                "chash": digest(csrf_value),
                "hid": str(uuid4()),
                "gen": gen,
                "epoch": epoch,
                "now": clock_ms,
                "exp": clock_ms + 3_600_000,
                "sid": session_id,
                "msid": managed_id,
            },
        )
    return session_id, managed_id


def _make_binding(acc_engine) -> IdentityBinding:
    with acc_engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT binding_id, resource_generation, access_epoch, revision "
                    "FROM access_meta WHERE id = 1"
                )
            )
            .mappings()
            .one()
        )
    return IdentityBinding(
        deployment_id=DEPLOYMENT_ID,
        scope=WorkspaceScope(operator_id=OP_ID, workspace_id=WS_ID),
        binding_id=row["binding_id"],
        resource_generation=int(row["resource_generation"]),
        access_epoch=int(row["access_epoch"]),
        assignment_revision=int(row["revision"]),
        registered_origin_id="00000000-0000-4000-8000-000000000099",
        target_origin=SOURCE_ORIGIN,
        issuer="firebase:epm-demo",
        subject="sub-alpha",
    )


def _build_recovery_test_client(env, *, recovery_mode: bool = True):
    acc_engine = env["acc_engine"]
    binding = _make_binding(acc_engine)
    source_key = Ed25519PrivateKey.generate()
    central_key = Ed25519PrivateKey.generate()
    source_signer = IdentitySigner("src-key-1", source_key)
    central_signer = IdentitySigner("central-key-1", central_key)

    # Bind a private AF_UNIX listener in /tmp (short path for macOS).
    sock_tmp = tempfile.TemporaryDirectory(dir="/tmp", prefix="epm-rec-")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(Path(sock_tmp.name) / "id.sock"))

    class _NoopCentral:
        pass

    inputs = OperatorIdentityInputs(
        engine=acc_engine,
        binding=lambda: _make_binding(acc_engine),
        signer=source_signer,
        central_key=lambda b, issuer, kid: (
            central_key.public_key()
            if (b, issuer, kid) == (_make_binding(acc_engine), "central_identity", "central-key-1")
            else None
        ),
        central=_NoopCentral(),
        clock=env["clock"],
        listener=listener,
        relay_uid=0,
        source_origin=SOURCE_ORIGIN,
        central_origin=CENTRAL_ORIGIN,
        support_contact="support@epmdemo.xyz",
        usage_reader=lambda: None,
        protection_reader=env["service"].protection_section,
        recovery_service=env["service"],
        recovery_mode=recovery_mode,
    )
    app = create_minimal_recovery_app(inputs)

    def _cleanup():
        listener.close()
        sock_tmp.cleanup()

    return app, binding, central_signer, _cleanup


def _issue_recent_grant(
    *,
    central_signer: IdentitySigner,
    binding: IdentityBinding,
    session_id: str,
    challenge_id: str,
    request_hash: str,
    now_ms: int,
) -> str:
    grant = RecentAuthGrant(
        binding=binding,
        issuer_service="central_identity",
        key_id="central-key-1",
        issued_at=now_ms,
        expires_at=now_ms + 240_000,
        operation_id=challenge_id,
        session_id=session_id,
        request_hash=request_hash,
        nonce_hash=digest(challenge_id),
        managed=ManagedObservation(
            managed_session_id=str(uuid4()),
            revision=1,
            issuer=binding.issuer,
            subject=binding.subject,
            method="google",
            purpose="operator",
            operator_id=OP_ID,
            email_verified=True,
            authenticated_at=now_ms,
            mfa_verified_at=None,
            issued_at=now_ms,
            provider_valid_until=now_ms + 300_000,
            remembered_until=now_ms + 3_600_000,
            checked_at=now_ms,
            valid_until=now_ms + 240_000,
            revoked=False,
        ),
    )
    return central_signer.sign(grant).get_secret_value()


def test_corrupt_business_recovery_mode_and_operator_step_up_exact_confirmation(tmp_path: Path):
    env = _setup_workspace_fixture(tmp_path)
    service: HostedWorkspaceRecoveryService = env["service"]
    clock = env["clock"]

    # 1. Capture a verified backup of the healthy workspace.
    out1 = service.execute(*_capture_cmd("cap-before-corrupt"))
    assert out1.state == OperationState.SUCCEEDED and out1.result is not None
    point_id = out1.result.point_id

    # 2. Corrupt the business DB -> startup detects minimal recovery mode, never creates empty DB.
    env["biz_db"].write_bytes(b"CORRUPTED-SQLITE-HEADER")
    startup = service.detect_startup_mode()
    assert startup.mode == "recovery"
    assert startup.reason == "business_database_unreadable"

    app, _binding, central_signer, cleanup = _build_recovery_test_client(env, recovery_mode=True)
    try:
        cookie_name = IdentityCookiePolicy().operator
        cookie_val = "A" * 43
        csrf_val = "C" * 43
        session_id, _ = _enable_access_and_create_session(
            env["acc_engine"], clock_ms=clock.now, cookie_value=cookie_val, csrf_value=csrf_val
        )
        client = TestClient(app, base_url=SOURCE_ORIGIN)
        headers_get = {"cookie": f"{cookie_name}={cookie_val}"}
        headers_post = {
            "cookie": f"{cookie_name}={cookie_val}",
            "origin": SOURCE_ORIGIN,
            "x-epm-csrf": csrf_val,
        }

        # Business API returns 503 recovery_mode_active while recovery API works.
        biz_resp = client.get("/api/properties", headers=headers_get)
        assert biz_resp.status_code == 503
        assert biz_resp.json()["code"] == "recovery_mode_active"

        # Status & points endpoints work in recovery mode.
        status_resp = client.get("/api/hosted/recovery/status", headers=headers_get)
        assert status_resp.status_code == 200
        assert status_resp.json()["mode"] == "recovery"
        assert status_resp.json()["startup"]["reason"] == "business_database_unreadable"

        points_resp = client.get("/api/hosted/recovery/points", headers=headers_get)
        assert points_resp.status_code == 200
        assert points_resp.json()["items"][0]["resource_id"] == point_id

        # Preview generates exactRequestHash + stepUpChallengeId.
        prev_resp = client.post(
            "/api/hosted/recovery/preview",
            json={"point_id": point_id},
            headers=headers_post,
        )
        assert prev_resp.status_code == 200
        preview_data = prev_resp.json()
        preview_id = preview_data["previewId"]
        exact_hash = preview_data["exactRequestHash"]
        challenge_id = preview_data["stepUpChallengeId"]

        # Confirm with wrong/forged step-up grant -> rejected (401).
        bad_confirm = client.post(
            "/api/hosted/recovery/confirm",
            json={
                "point_id": point_id,
                "preview_id": preview_id,
                "idempotency_key": "restore-bad-1",
                "recent_auth_grant": "forged.grant.token.value.00000000",
            },
            headers=headers_post,
        )
        assert bad_confirm.status_code == 401

        # Confirm with valid RecentAuthGrant bound to exactRequestHash -> succeeds!
        grant_token = _issue_recent_grant(
            central_signer=central_signer,
            binding=_make_binding(env["acc_engine"]),
            session_id=session_id,
            challenge_id=challenge_id,
            request_hash=exact_hash,
            now_ms=clock.now,
        )
        confirm_resp = client.post(
            "/api/hosted/recovery/confirm",
            json={
                "point_id": point_id,
                "preview_id": preview_id,
                "idempotency_key": "restore-ok-1",
                "recent_auth_grant": grant_token,
            },
            headers=headers_post,
        )
        assert confirm_resp.status_code == 200
        op_id = confirm_resp.json()["operation"]["operation_id"]
        assert confirm_resp.json()["state"] == "succeeded"

        # Old session was revoked by verify_restore_binding (access_epoch advanced to 2).
        revoked_resp = client.get("/api/hosted/recovery/status", headers=headers_get)
        assert revoked_resp.status_code == 401

        # Damaged incarnation-1 is preserved intact as forensic_damaged; incarnation-2 is now active!
        assert env["biz_db"].read_bytes() == b"CORRUPTED-SQLITE-HEADER"
        new_startup = service.detect_startup_mode()
        assert new_startup.mode == "normal"
        assert new_startup.active_business_ref == "incarnation-2"
        assert new_startup.pending_acceptance_id == op_id

        # Replaying the consumed preview/grant fails.
        clock.advance(1000)
        cookie_val_2 = "B" * 43
        csrf_val_2 = "D" * 43
        _enable_access_and_create_session(
            env["acc_engine"],
            clock_ms=clock.now,
            cookie_value=cookie_val_2,
            csrf_value=csrf_val_2,
            epoch=2,
        )
        headers_post_2 = {
            "cookie": f"{cookie_name}={cookie_val_2}",
            "origin": SOURCE_ORIGIN,
            "x-epm-csrf": csrf_val_2,
        }
        replay_resp = client.post(
            "/api/hosted/recovery/confirm",
            json={
                "point_id": point_id,
                "preview_id": preview_id,
                "idempotency_key": "restore-replay-2",
                "recent_auth_grant": grant_token,
            },
            headers=headers_post_2,
        )
        assert replay_resp.status_code == 403

        # Fresh post-restore session inspects operation & accepts restore.
        op_resp = client.get(
            f"/api/hosted/recovery/operations/{op_id}",
            headers={"cookie": f"{cookie_name}={cookie_val_2}"},
        )
        assert op_resp.status_code == 200
        assert op_resp.json()["phase"] == "switched"
        assert op_resp.json()["priorTreeKind"] == "forensic_damaged"

        accept_resp = client.post(
            "/api/hosted/recovery/accept",
            json={"operation_id": op_id},
            headers=headers_post_2,
        )
        assert accept_resp.status_code == 200
        assert accept_resp.json()["phase"] == "accepted"
    finally:
        cleanup()


def test_cross_workspace_replay_path_key_denial(tmp_path: Path):
    env = _setup_workspace_fixture(tmp_path)
    service: HostedWorkspaceRecoveryService = env["service"]
    out = service.execute(*_capture_cmd("cap-1"))
    assert out.result is not None
    point_id = out.result.point_id

    # Foreign workspace actor is denied preview.
    foreign_actor = OperatorAuthority(
        deployment_id=DEPLOYMENT_ID,
        scope=WorkspaceScope(operator_id=str(uuid4()), workspace_id=str(uuid4())),
        identity_proof_ref="session:foreign",
    )
    with pytest.raises(RestoreDeniedError):
        service.preview_restore(foreign_actor, point_id=point_id)

    # Unknown / foreign point_id raises RestoreNotFoundError.
    own_actor = OperatorAuthority(
        deployment_id=DEPLOYMENT_ID,
        scope=WorkspaceScope(operator_id=OP_ID, workspace_id=WS_ID),
        identity_proof_ref=f"session:{OP_ID}",
    )
    with pytest.raises(RestoreNotFoundError):
        service.preview_restore(own_actor, point_id=str(uuid4()))

    # Extra caller-supplied path/key fields are rejected by strict HTTP contract (400).
    app, _, _, cleanup = _build_recovery_test_client(env, recovery_mode=False)
    try:
        cookie_name = IdentityCookiePolicy().operator
        cookie_val = "k" * 43
        csrf_val = "s" * 43
        _enable_access_and_create_session(
            env["acc_engine"],
            clock_ms=env["clock"].now,
            cookie_value=cookie_val,
            csrf_value=csrf_val,
        )
        client = TestClient(app, base_url=SOURCE_ORIGIN)
        resp = client.post(
            "/api/hosted/recovery/preview",
            json={"point_id": point_id, "destination_path": "/etc/passwd"},
            headers={
                "cookie": f"{cookie_name}={cookie_val}",
                "origin": SOURCE_ORIGIN,
                "x-epm-csrf": csrf_val,
            },
        )
        assert resp.status_code == 400
    finally:
        cleanup()


def test_crash_safe_locator_switch_rollback_and_healthy_prior_tree(tmp_path: Path):
    env = _setup_workspace_fixture(tmp_path)
    service: HostedWorkspaceRecoveryService = env["service"]
    clock = env["clock"]

    out1 = service.execute(*_capture_cmd("cap-v1"))
    assert out1.result is not None
    point_v1 = out1.result.point_id

    # Mutate business DB after point_v1 so we can verify rollback + healthy pre-state preservation.
    conn = sqlite3.connect(env["biz_db"])
    try:
        conn.execute("INSERT INTO properties VALUES ('p-after', 'Post-Backup Villa')")
        conn.commit()
    finally:
        conn.close()

    own_scope = WorkspaceScope(operator_id=OP_ID, workspace_id=WS_ID)
    own_actor = OperatorAuthority(
        deployment_id=DEPLOYMENT_ID, scope=own_scope, identity_proof_ref=f"session:{OP_ID}"
    )

    # 1. Crash before atomic switch -> staging removed, active_business_ref untouched, needs_attention.
    prev_fail = service.preview_restore(own_actor, point_id=point_v1)
    restore_actor_fail = OperatorRestoreAuthority(
        deployment_id=DEPLOYMENT_ID,
        scope=own_scope,
        identity_proof_ref=f"session:{OP_ID}",
        step_up_ref="stepup:fail-test",
        step_up_at=clock.now,
        confirmed_request_hash=prev_fail.exact_request_hash,
    )

    def _simulate_crash(_target: Path) -> None:
        raise RuntimeError("Simulated power loss before switchover")

    failed_out = service.confirm_restore(
        restore_actor_fail,
        point_id=point_v1,
        preview_id=prev_fail.preview_id,
        idempotency_key="restore-crash-1",
        authorized_subject="op-alpha",
        before_switch_hook=_simulate_crash,
    )
    assert failed_out.state == OperationState.FAILED
    assert not (tmp_path / "workspace/incarnation-2").exists()
    detail_fail = service.restore_operation_detail(failed_out.operation.operation_id)
    assert detail_fail is not None and detail_fail.phase == "needs_attention"
    with env["rec_engine"].connect() as rec_conn:
        active_ref = rec_conn.execute(
            text("SELECT active_business_ref FROM recovery_meta WHERE id = 1")
        ).scalar_one()
    assert active_ref == "incarnation-1"

    # 2. Clean restore over healthy workspace -> incarnation-1 retained as healthy_pre_state!
    prev_ok = service.preview_restore(own_actor, point_id=point_v1)
    restore_actor_ok = OperatorRestoreAuthority(
        deployment_id=DEPLOYMENT_ID,
        scope=own_scope,
        identity_proof_ref=f"session:{OP_ID}",
        step_up_ref="stepup:ok-test",
        step_up_at=clock.now,
        confirmed_request_hash=prev_ok.exact_request_hash,
    )
    ok_out = service.confirm_restore(
        restore_actor_ok,
        point_id=point_v1,
        preview_id=prev_ok.preview_id,
        idempotency_key="restore-clean-2",
        authorized_subject="op-alpha",
    )
    assert ok_out.state == OperationState.SUCCEEDED
    detail_ok = service.restore_operation_detail(ok_out.operation.operation_id)
    assert detail_ok is not None
    assert detail_ok.phase == "switched"
    assert detail_ok.prior_tree_kind == "healthy_pre_state"
    # Prior healthy DB still has 'p-after'; restored incarnation-2 has only 'p1' in database/!
    assert (tmp_path / "workspace/incarnation-2/workspace.json").is_file()
    c_old = sqlite3.connect(tmp_path / "workspace/incarnation-1/property-management.sqlite")
    c_new = sqlite3.connect(
        tmp_path / "workspace/incarnation-2/database/property-management.sqlite"
    )
    try:
        assert {r[0] for r in c_old.execute("SELECT id FROM properties")} == {"p1", "p-after"}
        assert {r[0] for r in c_new.execute("SELECT id FROM properties")} == {"p1"}
    finally:
        c_old.close()
        c_new.close()


def test_admin_outage_independence_and_reconstruct_catalog(tmp_path: Path):
    env = _setup_workspace_fixture(tmp_path)
    service: HostedWorkspaceRecoveryService = env["service"]

    out1 = service.execute(*_capture_cmd("cap-recon-1"))
    assert out1.result is not None
    point_id = out1.result.point_id

    # Simulate catalog loss in a fresh recovery.sqlite (zero Admin DB involved).
    fresh_rec_dir = tmp_path / "fresh-control"
    fresh_rec_dir.mkdir(mode=0o700)
    fresh_rec_db = fresh_rec_dir / "recovery.sqlite"
    from app.platform.hosted_schema import initialize_store
    from app.platform.schema_resources import HostedStore
    from app.platform.sqlite_engine import create_sqlite_engine
    from app.modules.workspace.infrastructure.hosted_recovery import kms_ref_to_db_ref
    from app.modules.hosted_recovery.tests.test_h05_backup_runner_and_alerting import (
        ACC_SCHEMA,
        APP_DIR,
        KMS_KEY,
    )

    initialize_store(HostedStore.RECOVERY, fresh_rec_db, application_directory=APP_DIR)
    fresh_rec_engine = create_sqlite_engine(fresh_rec_db)
    with fresh_rec_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO recovery_meta ("
                "id, workspace_id, deployment_ref, source_generation, restore_generation, "
                "active_business_ref, encryption_key_ref, namespace_prefix, revision"
                ") VALUES (1, :ws, :dep, 1, 1, 'incarnation-1', :kref, :pref, 1)"
            ),
            {
                "ws": WS_ID,
                "dep": f"dep:{DEPLOYMENT_ID}",
                "kref": kms_ref_to_db_ref(KMS_KEY),
                "pref": f"deployments/{DEPLOYMENT_ID}/operators/{OP_ID}/",
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

    fresh_service = HostedWorkspaceRecoveryService(
        recovery_engine=fresh_rec_engine,
        access_engine=env["acc_engine"],
        backup_engine=env["backup_engine"],
        operator_id=OP_ID,
        workspace_id=WS_ID,
        deployment_id=DEPLOYMENT_ID,
        workspace_root=tmp_path / "workspace",
        scratch_root=env["scratch"],
        release_ref="rel-2026-11-22",
        business_schema_revision=BIZ_SCHEMA,
        access_schema_revision=ACC_SCHEMA,
        clock=env["clock"],
    )
    own_actor = OperatorAuthority(
        deployment_id=DEPLOYMENT_ID,
        scope=WorkspaceScope(operator_id=OP_ID, workspace_id=WS_ID),
        identity_proof_ref=f"session:{OP_ID}",
    )
    reconstructed = fresh_service.reconstruct_catalog(own_actor)
    assert reconstructed.scanned_manifests == 1
    assert reconstructed.imported_points == [point_id]


def test_no_offline_workspace_bypass():
    """Verify CLI exposes zero offline hosted workspace restore/decrypt/export bypass commands."""
    parser = _build_parser()
    subparsers = next(
        a for a in parser._actions if hasattr(a, "choices") and isinstance(a.choices, dict)
    )
    commands = set(subparsers.choices.keys())
    forbidden = {
        "hosted-restore",
        "hosted-decrypt",
        "hosted-export",
        "hosted-publish-backup",
        "hosted-recovery-bundle",
        "hosted-unpack-recovery-bundle",
        "hosted-recovery-status",
    }
    assert commands.isdisjoint(forbidden)

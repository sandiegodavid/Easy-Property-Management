"""H05.5 tests: Admin repair_runtime admission and Host Agent clean-runtime repair."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from app.modules.host_agent.infrastructure.repair_runtime import (
    CleanRuntimeRepairer,
    RepairPaths,
)
from app.modules.hosted_admin.api.router import build_admin_lite_router
from app.modules.hosted_admin.application.errors import AdminConflictError
from app.modules.hosted_admin.application.pilot_contracts import AdminCommand, RepairRuntime
from app.modules.hosted_admin.infrastructure.admin_control import AdminControlService
from app.modules.hosted_admin.infrastructure.policy_bootstrap import bootstrap_free_v1_policy
from app.modules.hosted_admin.infrastructure.schema_store import DeploymentMetadata, bind_deployment
from app.modules.hosted_recovery.tests.test_h05_backup_runner_and_alerting import (
    APP_DIR,
    DEPLOYMENT_ID,
    KMS_KEY,
    OP_ID,
    WS_ID,
    _setup_workspace_fixture,
)
from app.modules.hosted_recovery.tests.test_h05_operator_restore_and_recovery_mode import (
    _enable_access_and_create_session,
)
from app.modules.workspace.infrastructure.hosted_recovery import kms_ref_to_db_ref
from app.platform.hosted_contracts.authority import AdminAuthority
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

PRINCIPAL_ID = "00000000-0000-4000-8000-000000000102"
RELEASE_ID = "00000000-0000-4000-8000-000000000103"
BINDING_ID = "00000000-0000-4000-8000-000000000104"
ARTIFACT_DIGEST = "b" * 64


def _seed_admin_db(tmp_path: Path, *, now_ms: int):
    admin_dir = tmp_path / "admin"
    admin_dir.mkdir(mode=0o700)
    admin_db = admin_dir / "admin.sqlite"
    initialize_store(HostedStore.ADMIN, admin_db, application_directory=APP_DIR)
    engine = create_sqlite_engine(admin_db)
    with engine.begin() as conn:
        bind_deployment(
            conn,
            DeploymentMetadata(
                deployment_id=DEPLOYMENT_ID,
                public_base_domain="epmdemo.xyz",
                login_origin="https://auth.epmdemo.xyz",
                registry_generation=1,
                created_at=now_ms,
            ),
            application_directory=APP_DIR,
        )
        policy, _ = bootstrap_free_v1_policy(conn, created_at=now_ms, application_directory=APP_DIR)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO main.admin_principals ("
                "principal_id, issuer, subject, enabled, session_generation, revision, created_at"
                ") VALUES ("
                ":pid, 'firebase:epm-demo', 'admin-sub', 1, 1, 1, :now)"
            ),
            {"pid": PRINCIPAL_ID, "now": now_ms},
        )
        conn.execute(
            text(
                "INSERT INTO main.qualified_releases ("
                "release_id, component, artifact_kind, artifact_digest, artifact_ref, "
                "compatibility_manifest_ref, compatibility_manifest_sha256, "
                "business_schema_revision, access_schema_revision, admin_schema_revision, "
                "admin_recovery_schema_revision, inventory_schema_revision, "
                "recovery_schema_revision, qualification_ref, qualified_at, state, revision"
                ") VALUES ("
                ":rel, 'operator', 'oci_image', :digest, 'oci:epm-operator:h05', "
                "'manifest:h05', :msha, '20260401_0001', 'access_0001_initial', "
                "NULL, NULL, NULL, 'recovery_0001_initial', "
                "'qual:h05', :now, 'qualified', 1)"
            ),
            {"rel": RELEASE_ID, "digest": ARTIFACT_DIGEST, "msha": "c" * 64, "now": now_ms},
        )
        conn.execute(
            text(
                "INSERT INTO main.operators ("
                "operator_id, workspace_id, display_name, invited_email, email_key, "
                "workspace_slug, issuer, subject, desired_policy_id, desired_access, "
                "setup_state, support_contact, access_epoch, revision, created_at, updated_at, "
                "retired_at"
                ") VALUES ("
                ":op, :ws, 'Alpha Operator', 'alpha@example.com', 'alpha@example.com', "
                "'alpha', 'firebase:epm-demo', 'sub-alpha', :pol, 'enabled', 'active', "
                "'support@epmdemo.xyz', 1, 1, :now, :now, NULL)"
            ),
            {"op": OP_ID, "ws": WS_ID, "pol": policy.policy_id, "now": now_ms},
        )
    return engine


def _admin_actor(now_ms: int) -> AdminAuthority:
    return AdminAuthority(
        deployment_id=DEPLOYMENT_ID,
        principal_id=PRINCIPAL_ID,
        identity_proof_ref="admin:session-1",
        mfa_verified_at=now_ms,
    )


def _repair_cmd(
    *,
    key: str,
    expected_revision: int = 1,
    release_id: str = RELEASE_ID,
) -> AdminCommand:
    intent = CommandIntent[RepairRuntime](
        deployment_id=DEPLOYMENT_ID,
        scope=WorkspaceScope(operator_id=OP_ID, workspace_id=WS_ID),
        kind="repair_runtime",
        expected_revision=expected_revision,
        access_epoch=1,
        payload=RepairRuntime(
            binding_id=BINDING_ID,
            release_id=release_id,
            expected_resource_generation=1,
        ),
    )
    return AdminCommand(
        operation_id=str(uuid4()),
        idempotency_key=key,
        intent=intent,
        request_hash=semantic_hash(intent),
    )


def test_clean_runtime_repair_preserves_ids_data_revokes_sessions_and_boots_recovery_mode(
    tmp_path: Path,
):
    env = _setup_workspace_fixture(tmp_path)
    clock = env["clock"]
    admin_engine = _seed_admin_db(tmp_path, now_ms=clock.now)
    control = AdminControlService(
        admin_engine, clock=clock, issuer="firebase:epm-demo", application_directory=APP_DIR
    )

    # Create an active session in access.sqlite and corrupt the business DB.
    _enable_access_and_create_session(
        env["acc_engine"], clock_ms=clock.now, cookie_value="A" * 43, csrf_value="C" * 43
    )
    env["biz_db"].write_bytes(b"CORRUPT-BIZ-BYTES")

    # 1. Admit repair_runtime via AdminControlService (idempotent + conflict-checked).
    actor = _admin_actor(clock.now)
    cmd = _repair_cmd(key="repair-1")
    out1 = control.execute(actor, cmd)
    assert out1.state == OperationState.PENDING
    op_id = out1.operation.operation_id

    # Exact replay returns original outcome.
    out_replay = control.execute(actor, cmd)
    assert out_replay.operation.operation_id == op_id

    # Same key with changed semantics -> SemanticConflict.
    with pytest.raises(SemanticConflict):
        control.execute(actor, _repair_cmd(key="repair-1", expected_revision=2))

    # Concurrent repair while pending -> AdminConflictError.
    with pytest.raises(AdminConflictError):
        control.execute(actor, _repair_cmd(key="repair-2", expected_revision=2))

    # 2. Execute Host Agent CleanRuntimeRepairer.
    events: list[tuple[str, object]] = []

    def _stop(intent, _paths):
        events.append(("stop", intent.operator_id))

    def _replace(intent, _paths, recovery_mode_required: bool) -> str:
        events.append(("replace", intent.artifact_digest, recovery_mode_required))
        return "container:epm-op-alpha-repaired"

    repairer = CleanRuntimeRepairer(
        admin_engine=admin_engine,
        paths_for=lambda _intent: RepairPaths(
            workspace_root=tmp_path / "workspace",
            control_root=tmp_path / "control",
            scratch_root=tmp_path / "scratch",
        ),
        stop_container=_stop,
        replace_container=_replace,
        application_directory=APP_DIR,
        clock=clock,
    )
    result = repairer.execute(op_id)
    assert result.state == "succeeded"
    assert result.recovery_mode_required is True
    assert result.business_db_healthy is False
    assert result.prior_sessions_revoked == 1
    assert events == [
        ("stop", OP_ID),
        ("replace", ARTIFACT_DIGEST, True),
    ]

    # Business DB was NOT silently initialized or overwritten!
    assert env["biz_db"].read_bytes() == b"CORRUPT-BIZ-BYTES"

    # Prior sessions were revoked & session_generation incremented (zero session carry-over).
    with env["acc_engine"].connect() as acc_conn:
        revoked_rows = (
            acc_conn.execute(text("SELECT revoked_at FROM access_sessions")).scalars().all()
        )
        assert all(ts is not None for ts in revoked_rows)
        meta = (
            acc_conn.execute(
                text(
                    "SELECT operator_id, workspace_id, session_generation FROM access_meta WHERE id=1"
                )
            )
            .mappings()
            .one()
        )
        assert meta["operator_id"] == OP_ID
        assert meta["workspace_id"] == WS_ID
        assert int(meta["session_generation"]) == 2

    # recovery.sqlite IDs and key_ref are 100% preserved.
    with env["rec_engine"].connect() as rec_conn:
        rmeta = (
            rec_conn.execute(
                text("SELECT workspace_id, encryption_key_ref FROM recovery_meta WHERE id=1")
            )
            .mappings()
            .one()
        )
        assert rmeta["workspace_id"] == WS_ID
        assert rmeta["encryption_key_ref"] == kms_ref_to_db_ref(KMS_KEY)

    # Idempotent re-execution of succeeded operation does not re-stop/re-replace.
    events.clear()
    again = repairer.execute(op_id)
    assert again.state == "succeeded"
    assert events == []


def test_clean_runtime_repair_fails_closed_on_missing_recovery_store(tmp_path: Path):
    env = _setup_workspace_fixture(tmp_path)
    clock = env["clock"]
    admin_engine = _seed_admin_db(tmp_path, now_ms=clock.now)
    control = AdminControlService(
        admin_engine, clock=clock, issuer="firebase:epm-demo", application_directory=APP_DIR
    )

    out = control.execute(_admin_actor(clock.now), _repair_cmd(key="repair-missing-rec"))
    op_id = out.operation.operation_id

    # Delete recovery.sqlite -> repairer must fail closed to needs_attention, never recreate it.
    (tmp_path / "control/recovery.sqlite").unlink()
    replaced = {"called": False}

    def _replace(_intent, _paths, _rec_mode):
        replaced["called"] = True
        return "container:should-not-start"

    repairer = CleanRuntimeRepairer(
        admin_engine=admin_engine,
        paths_for=lambda _intent: RepairPaths(
            workspace_root=tmp_path / "workspace",
            control_root=tmp_path / "control",
            scratch_root=tmp_path / "scratch",
        ),
        stop_container=lambda _i, _p: None,
        replace_container=_replace,
        application_directory=APP_DIR,
        clock=clock,
    )
    res = repairer.execute(op_id)
    assert res.state == "needs_attention"
    assert res.error_code == "recovery_store_invalid"
    assert replaced["called"] is False
    assert not (tmp_path / "control/recovery.sqlite").exists()


def test_admin_router_repair_runtime_and_operation_lookup(tmp_path: Path):
    env = _setup_workspace_fixture(tmp_path)
    clock = env["clock"]
    admin_engine = _seed_admin_db(tmp_path, now_ms=clock.now)
    control = AdminControlService(
        admin_engine, clock=clock, issuer="firebase:epm-demo", application_directory=APP_DIR
    )

    class _FakeSession:
        principal_id = PRINCIPAL_ID
        managed_session_id = "00000000-0000-4000-8000-000000000199"
        mfa_verified_at = clock.now

    class _FakeAdminSessions:
        def authenticate(self, _cookie, *, sensitive=False):
            return _FakeSession()

        def csrf_token(self, _cookie):
            return "csrf-token-1"

    app = FastAPI()

    async def _read_body(request):
        return await request.json()

    router = build_admin_lite_router(
        control,
        _FakeAdminSessions(),
        read_cookie=lambda _req, _name: "cookie",
        read_body=_read_body,
    )
    app.include_router(router)
    client = TestClient(app)

    # Admin exposes zero customer-workspace restore/decrypt routes.
    route_paths = {route.path for route in router.routes}
    assert not any("workspace-restore" in p or "decrypt" in p for p in route_paths)

    resp = client.post(
        f"/api/admin/operators/{OP_ID}/repair-runtime",
        json={
            "idempotencyKey": "http-repair-1",
            "expectedRevision": 1,
            "bindingId": BINDING_ID,
            "releaseId": RELEASE_ID,
            "expectedResourceGeneration": 1,
        },
        headers={"x-csrf-token": "csrf-token-1"},
    )
    assert resp.status_code == 202
    op_id = resp.json()["operation"]["operation_id"]
    assert resp.json()["state"] == "pending"

    # Original operation lookup via GET /api/admin/operations/{operation_id}.
    get_resp = client.get(f"/api/admin/operations/{op_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["operation"]["operation_id"] == op_id
    assert get_resp.json()["state"] == "pending"

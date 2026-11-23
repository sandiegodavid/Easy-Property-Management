"""H05.1 SourceLifecycle maintenance/drain/restore_binding fences and D8 protection projection."""

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.modules.hosted_access.application.identity_evidence import IdentityBinding
from app.modules.hosted_access.application.managed_provider import ProviderDenied
from app.modules.hosted_access.application.source_contracts import (
    Drain,
    MaintenanceFence,
    SourceCommand,
    VerifyRestoreBinding,
)
from app.modules.hosted_access.infrastructure.source_lifecycle import SourceLifecycle
from app.modules.hosted_admin.infrastructure.admin_control import AdminControlService
from app.platform.hosted_contracts.authority import ServiceAuthority
from app.platform.hosted_contracts.operations import CommandIntent, SemanticConflict
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import WorkspaceScope
from app.platform.hosted_schema import create_schema, validate_schema
from app.platform.schema_resources import HostedStore

APPLICATION = Path(__file__).resolve().parents[6]
DEPLOYMENT_ID = "00000000-0000-4000-8000-000000000001"
OPERATOR_ID = "00000000-0000-4000-8000-000000000002"
WORKSPACE_ID = "00000000-0000-4000-8000-000000000003"
BINDING_ID = "00000000-0000-4000-8000-000000000004"
ORIGIN_ID = "00000000-0000-4000-8000-000000000005"
POLICY_ID = "00000000-0000-4000-8000-000000000006"
MAINTENANCE_ID = "00000000-0000-4000-8000-000000000010"
POINT_ID = "00000000-0000-4000-8000-000000000011"
SESSION_ID = "00000000-0000-4000-8000-000000000012"
HANDOFF_ID = "00000000-0000-4000-8000-000000000013"
MANAGED_ID = "00000000-0000-4000-8000-000000000014"


def _scope():
    return WorkspaceScope(operator_id=OPERATOR_ID, workspace_id=WORKSPACE_ID)


def _binding(*, access_epoch=1):
    return IdentityBinding(
        deployment_id=DEPLOYMENT_ID,
        scope=_scope(),
        binding_id=BINDING_ID,
        resource_generation=1,
        access_epoch=access_epoch,
        assignment_revision=1,
        registered_origin_id=ORIGIN_ID,
        target_origin="https://op.example.test",
        issuer="firebase-google",
        subject="sub-operator-1",
    )


@pytest.fixture
def lifecycle_env(tmp_path):
    db_path = tmp_path / "access.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", poolclass=NullPool)
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        create_schema(conn, HostedStore.HOSTED_ACCESS, application_directory=APPLICATION)
        conn.execute(
            text("""
            INSERT INTO access_meta (
                id, deployment_id, operator_id, workspace_id, binding_id,
                resource_generation, issuer, subject, email_key, effective_access,
                access_epoch, session_generation, not_before, effective_policy_id,
                usable_bytes, policy_revision, maintenance_operation_id,
                restore_generation, revision
            ) VALUES (
                1, :dep, :op, :ws, :bind,
                1, 'firebase-google', NULL, 'firebase-google:op@example.test', 'disabled',
                1, 1, 1000, :pol,
                50000000, 1, NULL,
                1, 1
            )
        """),
            {
                "dep": DEPLOYMENT_ID,
                "op": OPERATOR_ID,
                "ws": WORKSPACE_ID,
                "bind": BINDING_ID,
                "pol": POLICY_ID,
            },
        )
        conn.execute(
            text("""
            UPDATE access_meta SET subject='sub-operator-1', effective_access='enabled' WHERE id=1
        """)
        )
        conn.execute(
            text("""
            INSERT INTO access_sessions (
                session_hash, csrf_hash, actor_subject, handoff_id, generation, access_epoch,
                issued_at, expires_at, managed_valid_until, last_seen_at, revoked_at,
                session_id, managed_session_id, managed_observation_revision,
                revocation_valid_until, remembered_until, remembered, display_label,
                renewed_from_session_id
            ) VALUES (
                :sh, :ch, 'sub-operator-1', :hid, 1, 1,
                1000, 900000, 900000, 1000, NULL,
                :sid, :mid, 1,
                900000, 900000, 0, 'Chrome', NULL
            )
        """),
            {
                "sh": "a" * 64,
                "ch": "b" * 64,
                "hid": HANDOFF_ID,
                "sid": SESSION_ID,
                "mid": MANAGED_ID,
            },
        )
        conn.commit()

    clock_val = [2000]
    current_binding = [_binding(access_epoch=1)]

    @contextmanager
    def mutation():
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    svc = SourceLifecycle(
        engine,
        mutation=mutation,
        binding=lambda: current_binding[0],
        clock=lambda: clock_val[0],
    )
    yield svc, engine, clock_val, current_binding
    engine.dispose()


def _command(kind, payload, *, expected_revision, access_epoch=1, key="idem-1", op_id=None):
    intent = CommandIntent(
        deployment_id=DEPLOYMENT_ID,
        scope=_scope(),
        kind=kind,
        expected_revision=expected_revision,
        access_epoch=access_epoch,
        payload=payload,
    )
    return SourceCommand(
        operation_id=op_id or str(uuid4()),
        idempotency_key=key,
        request_hash=semantic_hash(intent),
        intent=intent,
    )


def test_maintenance_fence_drain_and_verify_restore_binding_flow(lifecycle_env):
    svc, engine, clock_val, _binding_ref = lifecycle_env
    source_actor = ServiceAuthority(
        service="source",
        deployment_id=DEPLOYMENT_ID,
        scope=_scope(),
        authenticated_channel_ref="channel:source",
    )
    recovery_actor = ServiceAuthority(
        service="operator_recovery",
        deployment_id=DEPLOYMENT_ID,
        scope=_scope(),
        authenticated_channel_ref="channel:recovery",
    )

    # 1. Maintenance fence succeeds and is idempotent.
    fence_cmd = _command(
        "maintenance_fence",
        MaintenanceFence(maintenance_id=MAINTENANCE_ID),
        expected_revision=1,
        key="fence-1",
    )
    fence_out = svc.execute(source_actor, fence_cmd)
    assert fence_out.revision == 2
    assert svc.execute(source_actor, fence_cmd) == fence_out

    # Conflicting semantic replay raises SemanticConflict.
    conflict_cmd = _command(
        "maintenance_fence",
        MaintenanceFence(maintenance_id=str(uuid4())),
        expected_revision=1,
        key="fence-1",
    )
    with pytest.raises(SemanticConflict):
        svc.execute(source_actor, conflict_cmd)

    # Second concurrent fence is denied while already fenced.
    with pytest.raises(ProviderDenied):
        svc.execute(
            source_actor,
            _command(
                "maintenance_fence",
                MaintenanceFence(maintenance_id=str(uuid4())),
                expected_revision=2,
                key="fence-2",
            ),
        )

    # 2. Drain revokes active sessions and records 'drain' receipt.
    drain_cmd = _command(
        "drain",
        Drain(maintenance_id=MAINTENANCE_ID),
        expected_revision=2,
        key="drain-1",
    )
    drain_out = svc.execute(source_actor, drain_cmd)
    assert drain_out.revision == 3
    assert drain_out.result.revocation is not None
    assert drain_out.result.revocation.not_before == 2001

    # 3. VerifyRestoreBinding advances access_epoch & restore_generation even while
    #    binding.access_epoch is still 1 (Admin-outage independence).
    clock_val[0] = 3000
    restore_cmd = _command(
        "verify_restore_binding",
        VerifyRestoreBinding(point_id=POINT_ID, restore_operation_id=MAINTENANCE_ID),
        expected_revision=3,
        access_epoch=2,
        key="restore-binding-1",
    )
    restore_out = svc.execute(recovery_actor, restore_cmd)
    assert restore_out.revision == 4
    assert restore_out.result.access_epoch == 2
    assert restore_out.result.effective_enabled is True
    assert restore_out.result.revocation is not None
    assert restore_out.result.revocation.not_before == 3001
    # Replay returns exact original outcome.
    assert svc.execute(recovery_actor, restore_cmd) == restore_out

    # Verify DB state and full schema validation (including 'drain' and 'restore_binding' receipts).
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("BEGIN")
        validate_schema(conn, HostedStore.HOSTED_ACCESS, application_directory=APPLICATION)
        meta = conn.execute(text("SELECT * FROM access_meta WHERE id=1")).mappings().one()
        assert meta["access_epoch"] == 2
        assert meta["restore_generation"] == 2
        assert meta["maintenance_operation_id"] is None
        sess = conn.execute(text("SELECT revoked_at FROM access_sessions")).scalar_one()
        assert sess == 2000
        kinds = {row[0] for row in conn.execute(text("SELECT kind FROM access_receipts")).all()}
        assert kinds == {"maintenance_fence", "drain", "restore_binding"}


def test_verify_restore_binding_rejects_wrong_caller_and_non_increasing_epoch(lifecycle_env):
    svc, _engine, _clock, _binding_ref = lifecycle_env
    source_actor = ServiceAuthority(
        service="source",
        deployment_id=DEPLOYMENT_ID,
        scope=_scope(),
        authenticated_channel_ref="channel:source",
    )
    admin_actor = ServiceAuthority(
        service="admin",
        deployment_id=DEPLOYMENT_ID,
        scope=_scope(),
        authenticated_channel_ref="channel:admin",
    )
    recovery_actor = ServiceAuthority(
        service="operator_recovery",
        deployment_id=DEPLOYMENT_ID,
        scope=_scope(),
        authenticated_channel_ref="channel:recovery",
    )

    svc.execute(
        source_actor,
        _command(
            "maintenance_fence",
            MaintenanceFence(maintenance_id=MAINTENANCE_ID),
            expected_revision=1,
            key="fence-neg",
        ),
    )

    # Admin cannot invoke verify_restore_binding.
    with pytest.raises(ValueError, match="wrong calling service"):
        svc.execute(
            admin_actor,
            _command(
                "verify_restore_binding",
                VerifyRestoreBinding(point_id=POINT_ID, restore_operation_id=MAINTENANCE_ID),
                expected_revision=2,
                access_epoch=2,
                key="restore-bad-actor",
            ),
        )

    # Same access_epoch (not increasing) is denied.
    with pytest.raises(ProviderDenied):
        svc.execute(
            recovery_actor,
            _command(
                "verify_restore_binding",
                VerifyRestoreBinding(point_id=POINT_ID, restore_operation_id=MAINTENANCE_ID),
                expected_revision=2,
                access_epoch=1,
                key="restore-same-epoch",
            ),
        )

    # Mismatched restore_operation_id is denied.
    with pytest.raises(ProviderDenied):
        svc.execute(
            recovery_actor,
            _command(
                "verify_restore_binding",
                VerifyRestoreBinding(point_id=POINT_ID, restore_operation_id=str(uuid4())),
                expected_revision=2,
                access_epoch=2,
                key="restore-wrong-id",
            ),
        )


def test_admin_projection_treats_unchanged_as_protected_and_overdue_as_degraded():
    base_row = {
        "operator_id": OPERATOR_ID,
        "workspace_id": WORKSPACE_ID,
        "display_name": "Test Op",
        "invited_email": "op@example.test",
        "workspace_slug": "test-op",
        "subject": "sub-1",
        "desired_access": "enabled",
        "setup_state": "active",
        "deployment_state": "applied",
        "observation_ref": "obs:1",
        "desired_release_id": POLICY_ID,
        "obs_freshness": "known",
        "obs_enabled": 1,
        "obs_epoch": 1,
        "obs_usage": 1000,
        "obs_at": 5000,
        "obs_src_rev": 2,
        "rec_state": "unchanged",
        "rec_verified_at": 4000,
        "rec_point_ref": "point:1",
        "rec_obs_at": 5000,
        "rec_src_rev": 3,
        "op_id": None,
        "op_kind": None,
        "op_key": None,
        "op_hash": None,
        "op_state": None,
        "op_rev": None,
        "op_updated": None,
        "op_error": None,
        "op_scope": None,
    }

    summary = AdminControlService._summary_from_row(
        object(), base_row, deployment_id=DEPLOYMENT_ID, now=6000
    )
    assert summary.protection.state == "ready"
    assert summary.protection.data is not None
    assert summary.protection.data.status == "protected"
    readiness = AdminControlService._readiness_from_row(base_row)
    prot_gate = next(g for g in readiness.checks if g.name == "protection")
    assert prot_gate.state == "passed"
    assert readiness.state == "ready"

    overdue_row = base_row | {"rec_state": "overdue"}
    overdue_summary = AdminControlService._summary_from_row(
        object(), overdue_row, deployment_id=DEPLOYMENT_ID, now=6000
    )
    assert overdue_summary.protection.state == "ready"
    assert overdue_summary.protection.data is not None
    assert overdue_summary.protection.data.status == "degraded"
    overdue_readiness = AdminControlService._readiness_from_row(overdue_row)
    assert (
        next(g for g in overdue_readiness.checks if g.name == "protection").state == "unavailable"
    )

    unknown_row = base_row | {"rec_state": "unknown"}
    unknown_summary = AdminControlService._summary_from_row(
        object(), unknown_row, deployment_id=DEPLOYMENT_ID, now=6000
    )
    assert unknown_summary.protection.state == "unavailable"

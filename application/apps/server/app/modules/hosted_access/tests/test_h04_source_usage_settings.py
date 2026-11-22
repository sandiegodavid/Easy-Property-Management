"""H04.4 source lifecycle (initialize_binding/apply_policy), logical usage, and Settings API."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from app.modules.host_agent.application.auth_routes import IdentityCookiePolicy
from app.modules.hosted_access.api.operator_settings import (
    SETTINGS_ROUTE,
    OperatorSettingsInputs,
    operator_settings_router,
)
from app.modules.hosted_access.application.identity_evidence import IdentityBinding
from app.modules.hosted_access.application.managed_provider import ProviderDenied
from app.modules.hosted_access.application.source_contracts import (
    AdmittedFreePolicy,
    ApplyPolicy,
    InitializeDisabled,
    SourceCommand,
)
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.source_lifecycle import (
    FREE_V1_USABLE_BYTES,
    SourceLifecycle,
)
from app.modules.hosted_access.infrastructure.source_sessions import SessionExpired
from app.modules.hosted_access.infrastructure.usage_accounting import (
    UsageAccountingStore,
    measure_logical_usage,
)
from app.platform.hosted_contracts.authority import ServiceAuthority
from app.platform.hosted_contracts.operations import (
    CommandIntent,
    OperationState,
    SemanticConflict,
)
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import WorkspaceScope
from app.platform.hosted_schema import InitializationResult, initialize_store
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

APPLICATION = Path(__file__).resolve().parents[6]
DEPLOYMENT_ID = "00000000-0000-4000-8000-000000000301"
OPERATOR_ID = "00000000-0000-4000-8000-000000000302"
WORKSPACE_ID = "00000000-0000-4000-8000-000000000303"
BINDING_ID = "00000000-0000-4000-8000-000000000304"
ASSIGNMENT_ID = "00000000-0000-4000-8000-000000000305"
POLICY_V1_ID = "00000000-0000-4000-8000-000000000306"
POLICY_V2_ID = "00000000-0000-4000-8000-000000000307"
ORIGIN_ID = "00000000-0000-4000-8000-000000000308"
ISSUER = "firebase:pilot0"
EMAIL_KEY = f"{ISSUER}:owner@example.invalid"
ORIGIN = "https://oak.epmdemo.xyz"
NOW = 2_000_000
HASH_A = "a" * 64
HASH_B = "b" * 64
BLOB_1_BYTES = 10_000
BLOB_2_BYTES = 25_000
EXPECTED_DEDUP_FILE_BYTES = BLOB_1_BYTES + BLOB_2_BYTES
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_INSUFFICIENT_STORAGE = 507
POLICY_REV_2 = 2


def _scope() -> WorkspaceScope:
    return WorkspaceScope(operator_id=OPERATOR_ID, workspace_id=WORKSPACE_ID)


def _binding() -> IdentityBinding:
    return IdentityBinding(
        deployment_id=DEPLOYMENT_ID,
        scope=_scope(),
        binding_id=BINDING_ID,
        resource_generation=1,
        assignment_revision=1,
        access_epoch=1,
        registered_origin_id=ORIGIN_ID,
        issuer=ISSUER,
        subject="pending-subject",
        target_origin=ORIGIN,
    )


def _admin_actor() -> ServiceAuthority:
    return ServiceAuthority(
        deployment_id=DEPLOYMENT_ID,
        scope=_scope(),
        service="admin",
        authenticated_channel_ref="relay:admin-1",
    )


@pytest.fixture
def stores(tmp_path):
    private = tmp_path.resolve() / "private"
    private.mkdir(mode=0o700)
    access_path = private / "access.sqlite"
    business_path = private / "business.sqlite"
    assert (
        initialize_store(HostedStore.HOSTED_ACCESS, access_path, application_directory=APPLICATION)
        == InitializationResult.INITIALIZED
    )
    access_engine = create_sqlite_engine(access_path)
    business_engine = create_sqlite_engine(business_path)
    with immediate_transaction(business_engine) as conn:
        conn.exec_driver_sql(
            "CREATE TABLE file_records ("
            "id TEXT PRIMARY KEY, size_bytes INTEGER NOT NULL, content_sha256 TEXT NOT NULL)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE file_content_locations ("
            "file_id TEXT PRIMARY KEY, storage_provider TEXT NOT NULL, storage_state TEXT NOT NULL)"
        )
    clock = [NOW]

    @contextmanager
    def mutation():
        with immediate_transaction(access_engine) as conn:
            yield conn

    lifecycle = SourceLifecycle(
        access_engine,
        mutation=mutation,
        binding=_binding,
        clock=lambda: clock[0],
    )
    usage = UsageAccountingStore(access_engine, business_engine, clock=lambda: clock[0])
    try:
        yield {
            "access_engine": access_engine,
            "business_engine": business_engine,
            "lifecycle": lifecycle,
            "usage": usage,
            "clock": clock,
        }
    finally:
        access_engine.dispose()
        business_engine.dispose()


def _init_command(*, key: str = "init-1", policy_id: str = POLICY_V1_ID) -> SourceCommand:
    payload = InitializeDisabled(
        binding_id=BINDING_ID,
        policy=AdmittedFreePolicy(
            policy_id=policy_id,
            policy_revision=1,
            usable_bytes=FREE_V1_USABLE_BYTES,
            admission_hash=HASH_A,
        ),
        assignment_id=ASSIGNMENT_ID,
    )
    intent = CommandIntent[InitializeDisabled](
        deployment_id=DEPLOYMENT_ID,
        scope=_scope(),
        kind="initialize_disabled",
        expected_revision=1,
        access_epoch=1,
        payload=payload,
    )
    return SourceCommand(
        operation_id=str(uuid4()),
        idempotency_key=key,
        intent=intent,
        request_hash=semantic_hash(intent),
    )


def _apply_policy_command(
    *,
    expected_revision: int,
    policy_revision: int,
    policy_id: str = POLICY_V2_ID,
    key: str = "policy-2",
    access_epoch: int = 1,
) -> SourceCommand:
    payload = ApplyPolicy(
        policy_id=policy_id,
        policy_revision=policy_revision,
        admission_hash=HASH_B,
    )
    intent = CommandIntent[ApplyPolicy](
        deployment_id=DEPLOYMENT_ID,
        scope=_scope(),
        kind="apply_policy",
        expected_revision=expected_revision,
        access_epoch=access_epoch,
        payload=payload,
    )
    return SourceCommand(
        operation_id=str(uuid4()),
        idempotency_key=key,
        intent=intent,
        request_hash=semantic_hash(intent),
    )


def test_initialize_binding_and_apply_policy_fencing_and_idempotency(stores):
    lifecycle: SourceLifecycle = stores["lifecycle"]
    init_cmd = _init_command()

    # Missing or invalid email_key fails closed.
    with pytest.raises(ProviderDenied):
        lifecycle.execute(_admin_actor(), init_cmd, email_key="wrong-issuer:a@b.invalid")

    # Initial disabled binding succeeds and seeds access_meta + usage_state.
    outcome = lifecycle.execute(_admin_actor(), init_cmd, email_key=EMAIL_KEY)
    assert outcome.state == OperationState.SUCCEEDED
    assert outcome.result is not None
    assert outcome.result.effective_enabled is False

    # Replay returns original outcome; changed semantics conflicts; fresh key on existing fails.
    assert lifecycle.execute(_admin_actor(), init_cmd, email_key=EMAIL_KEY) == outcome
    with pytest.raises(SemanticConflict):
        lifecycle.execute(
            _admin_actor(), _init_command(key="init-1", policy_id=POLICY_V2_ID), email_key=EMAIL_KEY
        )
    with pytest.raises(ProviderDenied):
        lifecycle.execute(_admin_actor(), _init_command(key="init-2"), email_key=EMAIL_KEY)

    # apply_policy rejects stale/equal policy_revision and wrong expected_revision.
    with pytest.raises(ProviderDenied):
        lifecycle.execute(
            _admin_actor(),
            _apply_policy_command(expected_revision=1, policy_revision=1, key="bad-pol-1"),
        )
    with pytest.raises(ProviderDenied):
        lifecycle.execute(
            _admin_actor(),
            _apply_policy_command(expected_revision=99, policy_revision=2, key="bad-pol-2"),
        )

    # Valid apply_policy advances policy_revision and replays idempotently.
    pol_cmd = _apply_policy_command(expected_revision=1, policy_revision=POLICY_REV_2)
    pol_out = lifecycle.execute(_admin_actor(), pol_cmd)
    assert pol_out.state == OperationState.SUCCEEDED
    assert pol_out.revision == POLICY_REV_2
    assert lifecycle.execute(_admin_actor(), pol_cmd) == pol_out

    with stores["access_engine"].connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT effective_policy_id, policy_revision, usable_bytes "
                    "FROM main.access_meta"
                )
            )
            .mappings()
            .one()
        )
        assert row["effective_policy_id"] == POLICY_V2_ID
        assert row["policy_revision"] == POLICY_REV_2
        assert row["usable_bytes"] == FREE_V1_USABLE_BYTES


def test_logical_usage_deduplication_reservations_507_and_reconciliation(stores):
    lifecycle: SourceLifecycle = stores["lifecycle"]
    usage: UsageAccountingStore = stores["usage"]
    lifecycle.execute(_admin_actor(), _init_command(), email_key=EMAIL_KEY)

    # Insert deduplicated local blobs + one missing blob into business DB.
    with immediate_transaction(stores["business_engine"]) as conn:
        conn.execute(
            text(
                "INSERT INTO file_records VALUES "
                "('f1', :b1, 'sha1'), ('f2', :b1, 'sha1'), "
                "('f3', :b2, 'sha2'), ('f4', 99999, 'sha3')"
            ),
            {"b1": BLOB_1_BYTES, "b2": BLOB_2_BYTES},
        )
        conn.execute(
            text(
                "INSERT INTO file_content_locations VALUES "
                "('f1', 'local', 'available'), ('f2', 'local', 'available'), "
                "('f3', 'local', 'available'), ('f4', 'local', 'missing')"
            )
        )

    measured = measure_logical_usage(stores["business_engine"])
    assert measured.committed_db_bytes > 0
    assert measured.retained_file_bytes == EXPECTED_DEDUP_FILE_BYTES

    snap = usage.refresh_usage_state()
    assert snap.retained_file_bytes == EXPECTED_DEDUP_FILE_BYTES
    assert snap.usable_bytes == FREE_V1_USABLE_BYTES

    # Reserve within 50 MB succeeds and replays idempotently; changed hash conflicts.
    op1 = str(uuid4())
    res1 = usage.reserve(op1, HASH_A, reserved_bytes=40_000_000, purpose="upload", source_epoch=1)
    assert (
        usage.reserve(op1, HASH_A, reserved_bytes=40_000_000, purpose="upload", source_epoch=1)
        == res1
    )
    with pytest.raises(SemanticConflict):
        usage.reserve(op1, HASH_B, reserved_bytes=40_000_000, purpose="upload", source_epoch=1)

    # Second concurrent reservation exceeding 50,000,000 bytes fails with HTTP 507.
    with pytest.raises(HostedAccessError) as exc:
        usage.reserve(
            str(uuid4()), HASH_B, reserved_bytes=15_000_000, purpose="upload", source_epoch=1
        )
    assert exc.value.status == HTTP_INSUFFICIENT_STORAGE
    assert exc.value.code == "hosted_storage_quota_exceeded"

    # Release frees headroom; unknown retains headroom until reconciled.
    usage.release(res1.reservation_id)
    res2 = usage.reserve(
        str(uuid4()), HASH_B, reserved_bytes=45_000_000, purpose="upload", source_epoch=1
    )
    usage.mark_unknown(res2.reservation_id)
    with pytest.raises(HostedAccessError) as exc2:
        usage.reserve(
            str(uuid4()), HASH_A, reserved_bytes=10_000_000, purpose="upload", source_epoch=1
        )
    assert exc2.value.status == HTTP_INSUFFICIENT_STORAGE

    reconciled_snap, count = usage.reconcile_unknown()
    assert count == 1
    assert reconciled_snap.reserved_bytes == 0

    # Settle commit records post-commit usage and marks reservation committed.
    res3 = usage.reserve(
        str(uuid4()), HASH_A, reserved_bytes=1000, purpose="record_write", source_epoch=1
    )
    settled = usage.settle_commit(res3.reservation_id)
    assert settled.reserved_bytes == 0
    assert settled.retained_file_bytes == EXPECTED_DEDUP_FILE_BYTES


def test_operator_settings_endpoint_auth_usage_and_honest_protection(stores):
    lifecycle: SourceLifecycle = stores["lifecycle"]
    usage: UsageAccountingStore = stores["usage"]
    lifecycle.execute(_admin_actor(), _init_command(), email_key=EMAIL_KEY)
    usage.refresh_usage_state()

    auth_mode = {"state": "ok"}

    class FakeSessions:
        destination = SimpleNamespace(binding=_binding)

        def authorize_with_restore(self, cookie, *, csrf, write):
            assert csrf is None and write is False
            if auth_mode["state"] == "expired":
                raise SessionExpired()
            if cookie != "valid-session":
                raise ProviderDenied()
            return SimpleNamespace(session_id=str(uuid4())), 1

    app = FastAPI()
    app.include_router(
        operator_settings_router(
            FakeSessions(),
            OperatorSettingsInputs(
                origin=ORIGIN,
                usage_reader=usage.read_usage,
                support_contact="support@epmdemo.xyz",
            ),
        )
    )
    client = TestClient(app, base_url=ORIGIN)
    cookie_name = IdentityCookiePolicy().operator

    assert client.get(SETTINGS_ROUTE).status_code == HTTP_UNAUTHORIZED
    assert (
        client.get(
            SETTINGS_ROUTE,
            headers={"Cookie": f"{cookie_name}=valid-session", "Host": "evil.invalid"},
        ).status_code
        == HTTP_FORBIDDEN
    )

    response = client.get(SETTINGS_ROUTE, headers={"Cookie": f"{cookie_name}=valid-session"})
    assert response.status_code == HTTP_OK
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["surface"] == "operator_settings"
    assert body["delivery_owner"] == "H04"
    assert body["usage"]["state"] == "ready"
    assert body["usage"]["data"]["plan"] == "free"
    assert body["usage"]["data"]["usable_bytes"] == FREE_V1_USABLE_BYTES
    assert body["usageBreakdown"]["remainingBytes"] <= FREE_V1_USABLE_BYTES
    assert body["protection"]["state"] == "unavailable"
    assert body["protection"]["data"] is None
    assert body["support_contact"] == "support@epmdemo.xyz"
    assert [a["action"] for a in body["actions"]] == ["operator_read_settings"]

    auth_mode["state"] = "expired"
    expired = client.get(SETTINGS_ROUTE, headers={"Cookie": f"{cookie_name}=valid-session"})
    assert expired.status_code == HTTP_UNAUTHORIZED
    assert expired.json()["state"] == "renewal_required"

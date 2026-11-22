"""H04.5 hosted business composition: FreeStorageAdmission, Settings, and 2-device workflows."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import socket
import tempfile
from types import SimpleNamespace
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from app.bootstrap.api import create_app
from app.modules.host_agent.application.auth_routes import IdentityCookiePolicy
from app.modules.hosted_access.api.managed_business import ManagedBusinessInputs
from app.modules.hosted_access.api.operator_settings import SETTINGS_ROUTE
from app.modules.hosted_access.application.identity_evidence import IdentityBinding
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.free_storage_admission import (
    FreeStorageAdmission,
    PhysicalQuotaHeadroom,
)
from app.modules.hosted_access.infrastructure.handoff_signing import IdentitySigner
from app.modules.hosted_access.infrastructure.operator_identity_runtime import (
    OperatorIdentityInputs,
)
from app.modules.hosted_access.infrastructure.source_lifecycle import FREE_V1_USABLE_BYTES
from app.modules.hosted_access.infrastructure.usage_accounting import UsageAccountingStore
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig
from app.platform.hosted_contracts.values import WorkspaceScope
from app.platform.hosted_schema import InitializationResult, initialize_store
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

APPLICATION = Path(__file__).resolve().parents[6]
DEPLOYMENT_ID = "00000000-0000-4000-8000-000000000401"
OPERATOR_ID = "00000000-0000-4000-8000-000000000402"
WORKSPACE_ID = "00000000-0000-4000-8000-000000000403"
BINDING_ID = "00000000-0000-4000-8000-000000000404"
ORIGIN_ID = "00000000-0000-4000-8000-000000000405"
POLICY_ID = "00000000-0000-4000-8000-000000000406"
ISSUER = "firebase:pilot0"
SUBJECT = "operator-uid-1"
EMAIL_KEY = f"{ISSUER}:pilot@example.invalid"
ORIGIN = "https://oak.epmdemo.xyz"
CENTRAL_ORIGIN = "https://login.epmdemo.xyz"
NOW = 3_000_000
MIB = 1024 * 1024
HTTP_OK = 200
HTTP_CREATED = 201
HTTP_FORBIDDEN = 403
HTTP_CONFLICT = 409
HTTP_SERVICE_UNAVAILABLE = 503
HTTP_INSUFFICIENT_STORAGE = 507
CRASH_RESERVE_BYTES = 100_000
COOKIE_A = "A" * 43
CSRF_A = "a" * 43
COOKIE_B = "B" * 43
CSRF_B = "b" * 43


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _healthy_headroom() -> PhysicalQuotaHeadroom:
    return PhysicalQuotaHeadroom(
        workspace_available_bytes=64 * MIB,
        workspace_available_inodes=2048,
        control_available_bytes=8 * MIB,
        control_available_inodes=512,
        scratch_available_bytes=32 * MIB,
        scratch_available_inodes=512,
    )


def _insert_session(conn, *, cookie: str, csrf: str, label: str) -> str:
    session_id = str(uuid4())
    conn.execute(
        text(
            "INSERT INTO main.access_sessions ("
            "session_hash, csrf_hash, actor_subject, handoff_id, generation, access_epoch, "
            "issued_at, expires_at, managed_valid_until, last_seen_at, revoked_at, "
            "session_id, managed_session_id, managed_observation_revision, "
            "revocation_valid_until, remembered_until, remembered, display_label, "
            "renewed_from_session_id"
            ") VALUES ("
            ":sh, :ch, :sub, :hid, 1, 1, "
            ":now, :exp, :exp, :now, NULL, "
            ":sid, :msid, 1, :exp, :exp, 0, :label, NULL"
            ")"
        ),
        {
            "sh": _digest(cookie),
            "ch": _digest(csrf),
            "sub": SUBJECT,
            "hid": str(uuid4()),
            "now": NOW - 1000,
            "exp": NOW + 3_600_000,
            "sid": session_id,
            "msid": str(uuid4()),
            "label": label,
        },
    )
    return session_id


@pytest.fixture
def hosted_app(tmp_path):
    root = tmp_path.resolve()
    workspace_dir = root / "workspace"
    control_dir = root / "control"
    socket_dir = Path(tempfile.mkdtemp(dir="/tmp", prefix="epm"))
    for directory in (workspace_dir, control_dir):
        directory.mkdir(mode=0o700)

    config_path = control_dir / "workspace.json"
    config_path.write_text(json.dumps({"localWorkspacePath": str(workspace_dir)}), encoding="utf-8")
    ws_service = WorkspaceService(
        LocalConfig(config_path=config_path, workspace_path=workspace_dir)
    )
    initialized = ws_service.initialize()
    workspace_id = initialized.workspace_id

    access_path = control_dir / "access.sqlite"
    assert (
        initialize_store(HostedStore.HOSTED_ACCESS, access_path, application_directory=APPLICATION)
        == InitializationResult.INITIALIZED
    )
    access_engine = create_sqlite_engine(access_path)
    business_engine = create_sqlite_engine(ws_service.paths.database)

    with immediate_transaction(access_engine) as conn:
        conn.execute(
            text(
                "INSERT INTO main.access_meta ("
                "id, deployment_id, operator_id, workspace_id, binding_id, "
                "resource_generation, issuer, subject, email_key, effective_access, "
                "access_epoch, session_generation, not_before, effective_policy_id, "
                "usable_bytes, policy_revision, maintenance_operation_id, "
                "restore_generation, revision"
                ") VALUES ("
                "1, :dep, :op, :ws, :bind, 1, :issuer, NULL, :email, 'disabled', "
                "1, 1, :now, :policy, :usable, 1, NULL, 1, 1"
                ")"
            ),
            {
                "dep": DEPLOYMENT_ID,
                "op": OPERATOR_ID,
                "ws": workspace_id,
                "bind": BINDING_ID,
                "issuer": ISSUER,
                "email": EMAIL_KEY,
                "now": NOW - 10_000,
                "policy": POLICY_ID,
                "usable": FREE_V1_USABLE_BYTES,
            },
        )
        conn.execute(
            text(
                "UPDATE main.access_meta SET subject = :sub, effective_access = 'enabled', "
                "revision = 2 WHERE id = 1"
            ),
            {"sub": SUBJECT},
        )
        conn.execute(
            text(
                "INSERT INTO main.usage_state ("
                "id, business_revision, committed_db_bytes, retained_file_bytes, "
                "observed_at, measurement_version, revision"
                ") VALUES (1, 'initial', 0, 0, :now, 'logical-v1', 1)"
            ),
            {"now": NOW - 5_000},
        )
        _insert_session(conn, cookie=COOKIE_A, csrf=CSRF_A, label="Laptop A")
        _insert_session(conn, cookie=COOKIE_B, csrf=CSRF_B, label="Tablet B")

    clock = [NOW]
    state = {"ready": True, "headroom": _healthy_headroom()}
    usage_store = UsageAccountingStore(access_engine, business_engine, clock=lambda: clock[0])
    usage_store.refresh_usage_state()
    admission = FreeStorageAdmission(usage_store, physical_headroom=lambda: state["headroom"])

    binding = IdentityBinding(
        deployment_id=DEPLOYMENT_ID,
        scope=WorkspaceScope(operator_id=OPERATOR_ID, workspace_id=workspace_id),
        binding_id=BINDING_ID,
        resource_generation=1,
        assignment_revision=1,
        access_epoch=1,
        registered_origin_id=ORIGIN_ID,
        issuer=ISSUER,
        subject=SUBJECT,
        target_origin=ORIGIN,
    )
    key = Ed25519PrivateKey.generate()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_dir / "source.sock"))
    app = create_app(
        config_path,
        operator_identity_inputs=OperatorIdentityInputs(
            engine=access_engine,
            binding=lambda: binding,
            signer=IdentitySigner("source-key-1", key),
            central_key=lambda *_args: None,
            central=SimpleNamespace(),
            clock=lambda: clock[0],
            listener=listener,
            relay_uid=1000,
            source_origin=ORIGIN,
            central_origin=CENTRAL_ORIGIN,
            support_contact="support@epmdemo.xyz",
            business=ManagedBusinessInputs(
                readiness=lambda: state["ready"],
                storage=admission,
                files=True,
            ),
            usage_reader=usage_store.read_usage,
        ),
    )
    try:
        yield {
            "app": app,
            "state": state,
            "usage": usage_store,
            "admission": admission,
            "access_engine": access_engine,
            "business_engine": business_engine,
        }
    finally:
        listener.close()
        shutil.rmtree(socket_dir, ignore_errors=True)
        access_engine.dispose()
        business_engine.dispose()


def _headers(cookie: str, csrf: str) -> dict[str, str]:
    name = IdentityCookiePolicy().operator
    return {"Cookie": f"{name}={cookie}", "Origin": ORIGIN, "X-EPM-CSRF": csrf}


def test_two_device_portfolio_settings_and_forbidden_routes(hosted_app):
    with TestClient(hosted_app["app"], base_url=ORIGIN) as client:
        dev_a = _headers(COOKIE_A, CSRF_A)
        dev_b = _headers(COOKIE_B, CSRF_B)

        # Device A creates a party record; Device B reads it and portfolio summary.
        created = client.post(
            "/api/parties",
            json={
                "idempotencyKey": str(uuid4()),
                "expectedRevision": 0,
                "confirmedNewParty": True,
                "partyKind": "individual",
                "displayName": "Oak Owner",
                "contacts": [{"methodKind": "email", "value": "oak@example.invalid"}],
            },
            headers=dev_a,
        )
        assert created.status_code == HTTP_CREATED, created.text
        party_id = created.json()["id"]

        fetched = client.get(f"/api/parties/{party_id}", headers=dev_b)
        assert fetched.status_code == HTTP_OK
        assert fetched.json()["displayName"] == "Oak Owner"
        assert client.get("/api/portfolio/status-summary", headers=dev_b).status_code == HTTP_OK

        # Operator Settings shows Free pilot, settled usage, and honest unavailable H05 protection.
        settings = client.get(SETTINGS_ROUTE, headers=dev_b)
        assert settings.status_code == HTTP_OK
        body = settings.json()
        assert body["usage"]["state"] == "ready"
        assert body["usage"]["data"]["usable_bytes"] == FREE_V1_USABLE_BYTES
        assert body["usage"]["data"]["used_bytes"] > 0
        assert body["usageBreakdown"]["reservedBytes"] == 0
        assert body["protection"]["state"] == "unavailable"

        # Two-device unfinished-form draft lease: Device A holds lease, Device B conflicts (409).
        draft_id = str(uuid4())
        lease_a = client.post(
            f"/api/hosted/drafts/{draft_id}/lease",
            json={"token": "L" * 43, "expectedRevision": 0},
            headers=dev_a,
        )
        assert lease_a.status_code == HTTP_OK
        lease_b = client.post(
            f"/api/hosted/drafts/{draft_id}/lease",
            json={"token": "M" * 43, "expectedRevision": 0},
            headers=dev_b,
        )
        assert lease_b.status_code == HTTP_CONFLICT

        # Forbidden local-only prefixes stay blocked (403).
        assert client.get("/api/workspace/status", headers=dev_a).status_code == HTTP_FORBIDDEN


def test_507_physical_and_logical_exhaustion_preserves_state_and_closed_readiness(hosted_app):
    with TestClient(hosted_app["app"], base_url=ORIGIN) as client:
        dev_a = _headers(COOKIE_A, CSRF_A)
        payload = {
            "idempotencyKey": "prop-quota-1",
            "expectedRevision": 0,
            "displayName": "Blocked Property",
            "propertyType": "single_family",
            "addressLine1": "200 Pine St",
            "city": "Portland",
            "stateProvince": "OR",
            "postalCode": "97201",
            "countryCode": "US",
            "timeZone": "America/Los_Angeles",
        }

        # Physical inode exhaustion fails with 507 and zero DB writes.
        hosted_app["state"]["headroom"] = PhysicalQuotaHeadroom(
            workspace_available_bytes=64 * MIB,
            workspace_available_inodes=10,
            control_available_bytes=8 * MIB,
            control_available_inodes=512,
            scratch_available_bytes=32 * MIB,
            scratch_available_inodes=512,
        )
        inode_resp = client.post("/api/properties", json=payload, headers=dev_a)
        assert inode_resp.status_code == HTTP_INSUFFICIENT_STORAGE
        assert inode_resp.json()["detail"]["code"] == "hosted_storage_quota_exceeded"

        # Physical byte exhaustion fails with 507.
        hosted_app["state"]["headroom"] = PhysicalQuotaHeadroom(
            workspace_available_bytes=1024,
            workspace_available_inodes=2048,
            control_available_bytes=8 * MIB,
            control_available_inodes=512,
            scratch_available_bytes=32 * MIB,
            scratch_available_inodes=512,
        )
        byte_resp = client.post("/api/properties", json=payload, headers=dev_a)
        assert byte_resp.status_code == HTTP_INSUFFICIENT_STORAGE

        # Restore healthy physical headroom; exhaust logical 50 MB allowance -> 507.
        hosted_app["state"]["headroom"] = _healthy_headroom()
        with immediate_transaction(hosted_app["access_engine"]) as conn:
            conn.execute(
                text("UPDATE main.usage_state SET committed_db_bytes = :used WHERE id = 1"),
                {"used": FREE_V1_USABLE_BYTES - 1024},
            )
        logical_resp = client.post("/api/properties", json=payload, headers=dev_a)
        assert logical_resp.status_code == HTTP_INSUFFICIENT_STORAGE
        assert logical_resp.json()["detail"]["code"] == "hosted_storage_quota_exceeded"

        # Zero properties committed after all three 507 rejections.
        with hosted_app["business_engine"].connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM properties")).scalar_one() == 0

        # When readiness is False (missing H05 protection), business routes return 503.
        hosted_app["state"]["ready"] = False
        assert client.get("/api/properties", headers=dev_a).status_code == HTTP_SERVICE_UNAVAILABLE
        # Settings endpoint remains available to authenticated session.
        assert client.get(SETTINGS_ROUTE, headers=dev_a).status_code == HTTP_OK


def test_free_storage_admission_releases_on_error_and_marks_unknown_on_crash(hosted_app):
    admission: FreeStorageAdmission = hosted_app["admission"]
    usage: UsageAccountingStore = hosted_app["usage"]

    with pytest.raises(HostedAccessError):
        with admission.reserve_request(CRASH_RESERVE_BYTES, write=True, source_epoch=1):
            raise HostedAccessError("bad_request", "Rejected", 400)
    assert usage.read_usage().reserved_bytes == 0

    with pytest.raises(RuntimeError):
        with admission.reserve_request(CRASH_RESERVE_BYTES, write=True, source_epoch=1):
            raise RuntimeError("simulated crash")
    assert usage.read_usage().reserved_bytes == CRASH_RESERVE_BYTES

    reconciled, count = usage.reconcile_unknown()
    assert count == 1
    assert reconciled.reserved_bytes == 0

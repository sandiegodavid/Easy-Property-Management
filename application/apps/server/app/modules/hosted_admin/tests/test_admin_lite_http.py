"""H04.3 Admin-lite HTTP API and SharedIdentityManifest v2 gateway allowlist tests."""

from __future__ import annotations

from pathlib import Path
import re
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import text

from app.modules.host_agent.application.auth_routes import (
    ADMIN_IDENTITY_ROUTES,
    ADMIN_LITE_ROUTES,
    SharedIdentityManifest,
)
from app.modules.host_agent.application.capacity import CapacitySnapshot
from app.modules.host_agent.application.ingress import IngressProjection
from app.modules.host_agent.infrastructure.auth_projection import (
    VerifiedAuthEndpoint,
    _uri_pattern,
    auth_config,
)
from app.modules.host_agent.infrastructure.gateway import GatewaySettings
from app.modules.hosted_access.api.admin_identity import build_admin_identity_app
from app.modules.hosted_access.tests.test_identity_contracts import setup
from app.modules.hosted_admin.infrastructure.admin_control import (
    AdminControlService,
    SourceObservationReading,
)
from app.modules.hosted_admin.infrastructure.capacity_store import (
    record_capacity_snapshot,
    register_capacity_profile,
)
from app.modules.hosted_admin.infrastructure.policy_bootstrap import (
    FREE_V1_USABLE_BYTES,
    bootstrap_free_v1_policy,
)
from app.modules.hosted_admin.infrastructure.schema_store import DeploymentMetadata, bind_deployment
from app.modules.hosted_admin.tests.test_admin_control import (
    RELEASE_ID,
    capacity_profile,
    free_budget,
    host_resources,
)
from app.platform.sqlite_engine import immediate_transaction

pytest_plugins = ("app.modules.hosted_access.tests.test_admin_sessions",)

APPLICATION = Path(__file__).resolve().parents[6]
DEPLOYMENT_ID = "00000000-0000-4000-8000-000000000201"
MANIFEST_ID = "00000000-0000-4000-8000-000000000202"
ENDPOINT_ID = "00000000-0000-4000-8000-000000000203"
HASH_A = "a" * 64
HTTP_OK = 200
HTTP_CREATED = 201
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_CONFLICT = 409
EXPECTED_V2_ADMIN_ROUTES = 11
EXPECTED_USAGE_BYTES = 12_345


def _seed_admin_control(service, tick) -> tuple[AdminControlService, str]:
    now = tick[0]
    with immediate_transaction(service.engine) as connection:
        bind_deployment(
            connection,
            DeploymentMetadata(
                deployment_id=DEPLOYMENT_ID,
                public_base_domain="epmdemo.xyz",
                login_origin="https://login.epmdemo.xyz",
                registry_generation=1,
                created_at=100,
            ),
            application_directory=APPLICATION,
        )
        policy, _ = bootstrap_free_v1_policy(
            connection, created_at=100, application_directory=APPLICATION
        )
        connection.execute(
            text(
                "INSERT INTO main.qualified_releases ("
                "release_id, component, artifact_kind, artifact_digest, artifact_ref, "
                "compatibility_manifest_ref, compatibility_manifest_sha256, "
                "business_schema_revision, access_schema_revision, recovery_schema_revision, "
                "qualification_ref, state, qualified_at, revision"
                ") VALUES ("
                ":id, 'operator', 'oci_image', :digest, 'operator-image:v1', "
                "'manifest-v1', :mhash, 'biz_1', 'access_0001_initial', 'rec_1', "
                "'qual-v1', 'qualified', 100, 1"
                ")"
            ),
            {"id": RELEASE_ID, "digest": "d" * 64, "mhash": "f" * 64},
        )
        profile = capacity_profile()
        budget = free_budget()
        register_capacity_profile(connection, profile, budget, created_at=100)
        total, available, shared_observed = host_resources(operator_slots=4)
        record_capacity_snapshot(
            connection,
            CapacitySnapshot(
                revision=1,
                observed_at=now - 10_000,
                complete=True,
                profile_ref=profile.reference,
                profile_revision=profile.revision,
                total=total,
                available=available,
                shared_observed=shared_observed,
            ),
        )
    control = AdminControlService(
        service.engine,
        clock=lambda: tick[0],
        issuer=service.provider.setup.realm.alias,
        application_directory=APPLICATION,
        source_inspector=lambda _op, _ws, _ep: SourceObservationReading(
            effective_enabled=False,
            usage_bytes=EXPECTED_USAGE_BYTES,
            usable_bytes=FREE_V1_USABLE_BYTES,
            source_revision=2,
            observed_at=tick[0] - 100,
        ),
    )
    return control, policy.policy_id


def _sign_in(browser: TestClient, token, tick) -> str:
    now = tick[0]
    tick[0] -= 20_000
    start = browser.get("/auth/start")
    tick[0] = now
    assert start.status_code == HTTP_OK
    complete = browser.post(
        "/auth/complete",
        json={"attemptId": start.json()["attemptId"], "token": token.get_secret_value()},
        headers={"Origin": setup().origins.admin},
    )
    assert complete.status_code == HTTP_OK
    return complete.json()["csrfToken"]


def _create_payload(boot_data: dict, *, operator_id: str, slug: str, key: str) -> dict:
    return {
        "idempotencyKey": key,
        "expectedRevision": boot_data["registryGeneration"],
        "operatorId": operator_id,
        "displayName": "Redwood Properties",
        "email": f"{slug}@example.invalid",
        "slug": slug,
        "supportContact": "support@epmdemo.xyz",
        "releaseId": RELEASE_ID,
        "policyId": boot_data["freePolicy"]["policy_id"],
        "admissionCommitment": boot_data["admissionCommitment"],
        "initialData": "empty",
    }


def test_admin_lite_http_create_list_detail_and_refresh(composition):
    service, token, tick, _, _ = composition
    service.provider.setup.origins = setup().origins
    control, _ = _seed_admin_control(service, tick)
    browser = TestClient(
        build_admin_identity_app(service, admin_control=control),
        base_url=setup().origins.admin,
    )

    assert browser.get("/api/admin/bootstrap").status_code == HTTP_UNAUTHORIZED
    assert browser.get("/api/admin/operators").status_code == HTTP_UNAUTHORIZED

    csrf = _sign_in(browser, token, tick)
    admin_headers = {"Origin": setup().origins.admin, "X-CSRF-Token": csrf}

    boot = browser.get("/api/admin/bootstrap")
    assert boot.status_code == HTTP_OK
    assert boot.headers["cache-control"] == "no-store"
    boot_data = boot.json()
    assert boot_data["deploymentId"] == DEPLOYMENT_ID
    assert boot_data["freePolicy"]["usable_bytes"] == FREE_V1_USABLE_BYTES
    assert len(boot_data["qualifiedOperatorReleases"]) == 1

    operator_id = str(uuid4())
    create_body = _create_payload(
        boot_data, operator_id=operator_id, slug="redwood", key="http-create-1"
    )
    assert (
        browser.post(
            "/api/admin/operators", json=create_body, headers={"Origin": setup().origins.admin}
        ).status_code
        == HTTP_UNAUTHORIZED
    )
    assert (
        browser.post(
            "/api/admin/operators",
            json=create_body,
            headers={"Origin": "https://evil.invalid", "X-CSRF-Token": csrf},
        ).status_code
        == HTTP_UNAUTHORIZED
    )

    created = browser.post("/api/admin/operators", json=create_body, headers=admin_headers)
    assert created.status_code == HTTP_CREATED
    replayed = browser.post("/api/admin/operators", json=create_body, headers=admin_headers)
    assert replayed.status_code == HTTP_CREATED
    assert replayed.json() == created.json()

    conflict = browser.post(
        "/api/admin/operators",
        json={**create_body, "slug": "redwood-other"},
        headers=admin_headers,
    )
    assert conflict.status_code == HTTP_CONFLICT

    listed = browser.get("/api/admin/operators?limit=10")
    assert listed.status_code == HTTP_OK
    assert listed.json()["directory"]["data"]["matching_total"] == 1
    assert browser.get("/api/admin/operators/not-a-uuid").status_code == HTTP_BAD_REQUEST

    detail = browser.get(f"/api/admin/operators/{operator_id}")
    assert detail.status_code == HTTP_OK
    assert detail.json()["operator"]["slug"] == "redwood"

    refreshed = browser.post(
        f"/api/admin/operators/{operator_id}/refresh",
        json={"idempotencyKey": "refresh-1", "expectedRevision": 1},
        headers=admin_headers,
    )
    assert refreshed.status_code == HTTP_OK
    assert refreshed.json()["state"] == "succeeded"
    detail_after = browser.get(f"/api/admin/operators/{operator_id}").json()
    assert detail_after["operator"]["usage"]["data"]["used_bytes"] == EXPECTED_USAGE_BYTES


def test_admin_lite_http_invitations_and_delivery(composition):
    service, token, tick, _, _ = composition
    service.provider.setup.origins = setup().origins
    control, _ = _seed_admin_control(service, tick)
    browser = TestClient(
        build_admin_identity_app(service, admin_control=control),
        base_url=setup().origins.admin,
    )
    csrf = _sign_in(browser, token, tick)
    admin_headers = {"Origin": setup().origins.admin, "X-CSRF-Token": csrf}

    boot_data = browser.get("/api/admin/bootstrap").json()
    operator_id = str(uuid4())
    create_body = _create_payload(
        boot_data, operator_id=operator_id, slug="sequoia", key="http-create-seq"
    )
    assert (
        browser.post("/api/admin/operators", json=create_body, headers=admin_headers).status_code
        == HTTP_CREATED
    )

    invite_req = {"idempotencyKey": "invite-1", "expectedRevision": 1}
    assert (
        browser.post(
            f"/api/admin/operators/{operator_id}/invitations",
            json=invite_req,
            headers=admin_headers,
        ).status_code
        == HTTP_CONFLICT
    )
    with immediate_transaction(service.engine) as conn:
        conn.execute(
            text(
                "UPDATE main.component_deployments SET state='applied', "
                "observed_release_id=:rel, observation_ref='host:1', observed_at=:now "
                "WHERE operator_id=:op"
            ),
            {"rel": RELEASE_ID, "now": tick[0], "op": operator_id},
        )
        conn.execute(
            text("UPDATE main.operators SET setup_state='ready_for_claim' WHERE operator_id=:op"),
            {"op": operator_id},
        )
    issued = browser.post(
        f"/api/admin/operators/{operator_id}/invitations",
        json=invite_req,
        headers=admin_headers,
    )
    assert issued.status_code == HTTP_CREATED
    inv_id = issued.json()["invitationId"]
    assert issued.json()["token"] is not None
    replayed_inv = browser.post(
        f"/api/admin/operators/{operator_id}/invitations",
        json=invite_req,
        headers=admin_headers,
    )
    assert replayed_inv.status_code == HTTP_OK
    assert replayed_inv.json()["token"] is None

    delivered = browser.post(
        f"/api/admin/operators/{operator_id}/invitations/{inv_id}/delivered",
        json={"expectedRevision": 1},
        headers=admin_headers,
    )
    assert delivered.status_code == HTTP_OK
    assert delivered.json()["state"] == "sent"


def test_shared_identity_manifest_v2_and_gateway_uuid_patterns():
    base = dict(
        component_id=MANIFEST_ID,
        artifact_sha256=HASH_A,
        private_endpoint_id=ENDPOINT_ID,
        central_origin="https://login.epmdemo.xyz",
        admin_origin="https://admin.epmdemo.xyz",
        owning_login_origin="https://login.epmdemo.xyz",
    )
    with pytest.raises(ValidationError):
        SharedIdentityManifest(
            **base,
            route_policy="separate_exact_host_method_allowlists_v1",
            admin_routes=ADMIN_LITE_ROUTES,
        )
    with pytest.raises(ValidationError):
        SharedIdentityManifest(
            **base,
            route_policy="separate_exact_host_method_allowlists_v2",
            admin_routes=ADMIN_IDENTITY_ROUTES,
        )

    manifest_v2 = SharedIdentityManifest(
        **base,
        route_policy="separate_exact_host_method_allowlists_v2",
        admin_routes=ADMIN_LITE_ROUTES,
    )
    assert len(manifest_v2.admin_routes) == EXPECTED_V2_ADMIN_ROUTES

    endpoint = VerifiedAuthEndpoint(
        manifest=manifest_v2,
        address="172.18.0.10",
        port=8443,
        tls_name="admin.internal",
        admin_assets=("/assets/admin.js",),
    )
    config = auth_config(
        IngressProjection(records=()),
        GatewaySettings(admin_socket=Path("/run/epm/caddy.sock"), gateway_uid=900),
        shared=endpoint,
        login_origin="https://login.epmdemo.xyz",
    )
    routes = config["apps"]["http"]["servers"]["gateway"]["routes"]
    admin_routes = [
        route
        for route in routes
        if route.get("match", [{}])[0].get("host") == ["admin.epmdemo.xyz"]
    ]
    assert len(admin_routes) == EXPECTED_V2_ADMIN_ROUTES + 2

    detail_re = re.compile(_uri_pattern("/api/admin/operators/{operator_id}"))
    assert detail_re.fullmatch(f"/api/admin/operators/{DEPLOYMENT_ID}")
    assert detail_re.fullmatch(f"/api/admin/operators/{DEPLOYMENT_ID}?foo=1")
    assert not detail_re.fullmatch("/api/admin/operators/ABCDEF00-0000-4000-8000-000000000201")
    assert not detail_re.fullmatch("/api/admin/operators/../session")
    assert not detail_re.fullmatch("/api/admin/operators/not-a-uuid")
    assert not detail_re.fullmatch(f"/api/admin/operators/{DEPLOYMENT_ID}/extra")

    delivered_re = re.compile(
        _uri_pattern("/api/admin/operators/{operator_id}/invitations/{invitation_id}/delivered")
    )
    assert delivered_re.fullmatch(
        f"/api/admin/operators/{DEPLOYMENT_ID}/invitations/{MANIFEST_ID}/delivered"
    )
    assert not delivered_re.fullmatch(
        f"/api/admin/operators/{DEPLOYMENT_ID}/invitations/bad/delivered"
    )

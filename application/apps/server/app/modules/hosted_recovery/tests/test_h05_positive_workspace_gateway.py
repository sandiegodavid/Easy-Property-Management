"""Focused H05.7 tests: positive workspace gateway routing (D9) and live readiness gate."""

from __future__ import annotations

import json
from pathlib import Path
import re
from types import SimpleNamespace

from pydantic import ValidationError
import pytest
from sqlalchemy import text

from app.modules.host_agent.application.auth_routes import (
    ADMIN_H05_ROUTES,
    SharedIdentityManifest,
    WORKSPACE_FORBIDDEN_PREFIXES,
    WorkspaceRouteManifest,
    WorkspaceRouteObservation,
)
from app.modules.host_agent.application.dispatch import (
    HostAgentDenied,
    HostAgentUnavailable,
    IngressPolicy,
)
from app.modules.host_agent.application.ingress import (
    IngressProjection,
    IngressRecord,
)
from app.modules.host_agent.application.service import HostAgent
from app.modules.host_agent.infrastructure.auth_projection import (
    VerifiedAuthEndpoint,
    auth_config,
)
from app.modules.host_agent.infrastructure.gateway import Gateway, GatewaySettings
from app.modules.host_agent.tests.test_agent import (
    BINDING,
    follow,
    ready,
    setup as setup,
)
from app.modules.hosted_access.infrastructure.operator_entry import _live_business_readiness
from app.modules.hosted_recovery.tests.test_h05_backup_runner_and_alerting import (
    _capture_cmd,
    _setup_workspace_fixture,
)
from app.platform.hosted_contracts.semantic import semantic_hash

APP_DIR = Path(__file__).resolve().parents[6]
DEPLOYMENT = "01960000-0000-7000-8000-000000000700"
OPERATOR = "01960000-0000-7000-8000-000000000705"
WORKSPACE = "01960000-0000-7000-8000-000000000706"
COMPONENT_ID = "01960000-0000-7000-8000-000000000701"
ENDPOINT_ID = "01960000-0000-7000-8000-000000000702"
POINT_ID = "01960000-0000-7000-8000-000000000703"
OP_ID = "01960000-0000-7000-8000-000000000704"
ARTIFACT_SHA = "a" * 64


def _make_workspace_manifest() -> WorkspaceRouteManifest:
    return WorkspaceRouteManifest(
        component_id=COMPONENT_ID,
        artifact_sha256=ARTIFACT_SHA,
        private_endpoint_id=ENDPOINT_ID,
        recovery_proof_ref=f"manifest:{POINT_ID}",
    )


def _make_projection(desired_state: str = "eligible") -> IngressProjection:
    return IngressProjection(
        records=(
            IngressRecord(
                binding_id=BINDING,
                operator_id=OPERATOR,
                workspace_id=WORKSPACE,
                resource_generation=1,
                public_origin="https://ws-alpha.example.invalid",
                desired_state=desired_state,
                access_epoch=1,
                operation_id=OP_ID,
            ),
        )
    )


def test_workspace_route_manifest_and_admin_h05_routes():
    shared = SharedIdentityManifest(
        component_id=COMPONENT_ID,
        artifact_sha256=ARTIFACT_SHA,
        private_endpoint_id=ENDPOINT_ID,
        central_origin="https://login.example.invalid",
        admin_origin="https://admin.example.invalid",
        owning_login_origin="https://login.example.invalid",
        route_policy="separate_exact_host_method_allowlists_v3",
        admin_routes=ADMIN_H05_ROUTES,
    )
    assert ("POST", "/api/admin/operators/{operator_id}/repair-runtime") in shared.admin_routes
    assert ("GET", "/api/admin/operations/{operation_id}") in shared.admin_routes
    assert ("POST", "/api/admin/recovery/confirm") in shared.admin_routes

    manifest = _make_workspace_manifest()
    assert manifest.websocket_allowed is False
    assert manifest.forbidden_prefixes == WORKSPACE_FORBIDDEN_PREFIXES

    with pytest.raises(ValidationError):
        WorkspaceRouteManifest(
            component_id=COMPONENT_ID,
            artifact_sha256=ARTIFACT_SHA,
            private_endpoint_id=ENDPOINT_ID,
            recovery_proof_ref=f"manifest:{POINT_ID}",
            forbidden_prefixes=("/admin",),
        )


def test_auth_config_rejects_unverified_eligible_and_projects_verified_workspace_routes(tmp_path):
    settings = GatewaySettings(admin_socket=tmp_path / "caddy.sock", gateway_uid=1000)
    projection = _make_projection("eligible")

    # Eligible record without verified WorkspaceRouteObservation fails closed.
    with pytest.raises(HostAgentUnavailable):
        auth_config(projection, settings)

    manifest = _make_workspace_manifest()
    endpoint = VerifiedAuthEndpoint(
        manifest=manifest,
        address="10.20.0.10",
        port=8443,
        tls_name="ws-alpha.internal.invalid",
    )

    # Tampered manifest hash or closed route state fails closed.
    bad_obs = WorkspaceRouteObservation(
        binding_id=BINDING,
        resource_generation=1,
        access_epoch=1,
        workspace_route_state="ready",
        workspace_manifest_sha256="b" * 64,
        source_identity_proof_ref="id-proof:1",
        resource_readiness_proof_ref=f"manifest:{POINT_ID}",
        verified_recovery_point_id=POINT_ID,
        observed_at=1_760_000_000_000,
    )
    with pytest.raises(HostAgentDenied):
        auth_config(projection, settings, eligible=((bad_obs, endpoint),))

    closed_obs = bad_obs.model_copy(
        update={
            "workspace_manifest_sha256": semantic_hash(manifest),
            "workspace_route_state": "closed",
        }
    )
    with pytest.raises(HostAgentDenied):
        auth_config(projection, settings, eligible=((closed_obs, endpoint),))

    # Verified observation + manifest emits deny-first + exact-host proxy routes.
    valid_obs = closed_obs.model_copy(update={"workspace_route_state": "ready"})
    config = auth_config(projection, settings, eligible=((valid_obs, endpoint),))
    routes = config["apps"]["http"]["servers"]["gateway"]["routes"]
    deny_route, proxy_route = routes[0], routes[1]

    # Route 0: terminal 403 for WebSockets (Upgrade), forbidden prefixes, and traversal.
    assert deny_route["terminal"] is True
    assert deny_route["handle"][0]["status_code"] == 403
    match_blocks = deny_route["match"]
    assert {"host": ["ws-alpha.example.invalid"], "header": {"Upgrade": ["*"]}} in match_blocks
    # Normalized Caddy path matcher covers all forbidden prefixes.
    normalized_paths = match_blocks[1]["path"]
    for prefix in WORKSPACE_FORBIDDEN_PREFIXES:
        assert prefix in normalized_paths
        assert f"{prefix}/*" in normalized_paths
    # Raw orig_uri case-insensitive matcher catches pre-normalization paths.
    forbidden_expr = match_blocks[2]["expression"]
    forbidden_regex = json.loads(
        forbidden_expr.removeprefix("{http.request.orig_uri}.matches(").removesuffix(")")
    )
    for prefix in WORKSPACE_FORBIDDEN_PREFIXES:
        assert re.search(forbidden_regex, prefix) is not None
        assert re.search(forbidden_regex, prefix.upper()) is not None
        assert re.search(forbidden_regex, f"{prefix}/nested?x=1") is not None
    assert re.search(forbidden_regex, "/api/properties") is None
    # Traversal / double-slash / encoded-delimiter matcher catches evasion.
    traversal_expr = match_blocks[3]["expression"]
    traversal_regex = json.loads(
        traversal_expr.removeprefix("{http.request.orig_uri}.matches(").removesuffix(")")
    )
    for evade in ("//admin", "/api/../admin", "/%2e%2e/admin", "/admin%2finfo", "/admin%5cinfo"):
        assert re.search(traversal_regex, evade) is not None
    assert re.search(traversal_regex, "/api/properties") is None

    # Route 1: terminal reverse_proxy enforcing exact hostport, HTTPS, Cf-Connecting-Ip, and header stripping.
    assert proxy_route["terminal"] is True
    assert proxy_route["handle"][0]["handler"] == "reverse_proxy"
    assert proxy_route["handle"][0]["upstreams"] == [{"dial": "10.20.0.10:8443"}]
    proxy_match = proxy_route["match"][0]
    assert proxy_match["host"] == ["ws-alpha.example.invalid"]
    assert '{http.request.hostport} == "ws-alpha.example.invalid"' in proxy_match["expression"]
    not_headers = {next(iter(item["header"])) for item in proxy_match["not"]}
    assert {
        "Forwarded",
        "X-Forwarded-Host",
        "X-Forwarded-Port",
        "X-Original-URL",
        "X-Rewrite-URL",
        "Upgrade",
    }.issubset(not_headers)
    deleted = set(proxy_route["handle"][0]["headers"]["request"]["delete"])
    assert {
        "Forwarded",
        "X-Forwarded-Host",
        "X-Forwarded-For",
        "Cf-Connecting-Ip",
        "Upgrade",
    }.issubset(deleted)


def test_host_agent_eligible_gate_requires_verified_h05_proof(setup):
    ready(setup)

    cmd = follow(
        setup,
        IngressPolicy(
            desired_state="eligible",
            expected_ingress_revision=1,
            source_identity_proof_ref="id-proof:verified-1",
            resource_readiness_proof_ref=f"manifest:{POINT_ID}",
        ),
    )
    # Default agent without verifier rejects eligible.
    with pytest.raises(HostAgentUnavailable):
        setup.agent.execute(cmd)

    # Agent with verifier that rejects still raises HostAgentUnavailable.
    agent_reject = HostAgent(
        setup.inventory,
        setup.admission,
        setup.driver,
        clock=setup.agent.clock,
        eligible_proof_verifier=lambda _c: False,
    )
    with pytest.raises(HostAgentUnavailable):
        agent_reject.execute(cmd)

    # Agent with verifier that validates H05 proof admits eligible!
    verified_calls = []

    def verifier(command):
        verified_calls.append(
            (
                command.payload.source_identity_proof_ref,
                command.payload.resource_readiness_proof_ref,
            )
        )
        return (
            command.payload.source_identity_proof_ref == "id-proof:verified-1"
            and command.payload.resource_readiness_proof_ref == f"manifest:{POINT_ID}"
        )

    agent_open = HostAgent(
        setup.inventory,
        setup.admission,
        setup.driver,
        clock=setup.agent.clock,
        eligible_proof_verifier=verifier,
    )
    receipt = agent_open.execute(cmd)
    assert receipt.state == "applied"
    assert verified_calls == [("id-proof:verified-1", f"manifest:{POINT_ID}")]


def test_gateway_apply_eligible_without_containment(setup, tmp_path):
    """Gateway.apply(desired_state='eligible') loads verified config without stopping the container."""
    ready(setup)
    cmd = follow(
        setup,
        IngressPolicy(
            desired_state="eligible",
            expected_ingress_revision=1,
            source_identity_proof_ref="id-proof:verified-1",
            resource_readiness_proof_ref=f"manifest:{POINT_ID}",
        ),
    )
    scope = cmd.effect.parent.scope
    settings = GatewaySettings(admin_socket=tmp_path / "caddy.sock", gateway_uid=1000)
    manifest = _make_workspace_manifest()
    endpoint = VerifiedAuthEndpoint(
        manifest=manifest,
        address="10.20.0.10",
        port=8443,
        tls_name="ws-alpha.internal.invalid",
    )
    obs = WorkspaceRouteObservation(
        binding_id=cmd.effect.binding_id,
        resource_generation=cmd.effect.resource_generation,
        access_epoch=cmd.access_epoch,
        workspace_route_state="ready",
        workspace_manifest_sha256=semantic_hash(manifest),
        source_identity_proof_ref="id-proof:verified-1",
        resource_readiness_proof_ref=f"manifest:{POINT_ID}",
        verified_recovery_point_id=POINT_ID,
        observed_at=1_760_000_000_000,
    )
    projection = IngressProjection(
        records=(
            IngressRecord(
                binding_id=cmd.effect.binding_id,
                operator_id=scope.operator_id,
                workspace_id=scope.workspace_id,
                resource_generation=cmd.effect.resource_generation,
                public_origin="https://ws-alpha.example.invalid",
                desired_state="eligible",
                access_epoch=cmd.access_epoch,
                operation_id=cmd.effect.child_id(),
            ),
        )
    )

    class FakeInventory:
        def ingress_projection(self):
            return projection

        def auth_ready(self):
            return ()

        def eligible_ready(self):
            return (obs,)

    class FakeAdmin:
        def __init__(self):
            self.loaded = None

        def load(self, config):
            self.loaded = config

        def inspect(self):
            return self.loaded

    class FakeEndpoints:
        def resolve_held(self, _row):
            raise AssertionError("not used")

        def resolve_eligible(self, _row):
            return endpoint

        def resolve_shared(self):
            return None, None

    contain_calls = []
    admin = FakeAdmin()
    gw = Gateway(
        FakeInventory(),
        admin,
        settings,
        contain=lambda c, a: contain_calls.append((c, a)),
        auth_endpoints=FakeEndpoints(),
        eligible_proof_verifier=lambda _c: True,
    )
    allocation = SimpleNamespace(
        binding_id=cmd.effect.binding_id,
        resource_generation=cmd.effect.resource_generation,
        ingress_projection_revision=2,
    )

    result = gw.apply(cmd, allocation)
    assert result.status == "applied"
    assert result.ingress_state == "eligible"
    assert result.evidence_ref.startswith("gateway-eligible-v1:")
    assert admin.loaded is not None
    assert contain_calls == []  # Enabling workspace must NOT stop/contain the container!

    # Inspect confirms the same state without stopping the container.
    inspected = gw.inspect(cmd, allocation)
    assert inspected.ingress_state == "eligible"
    assert contain_calls == []


def test_live_business_readiness_enforces_all_three_h05_conditions(tmp_path):
    """Section 6: readiness is True iff access enabled & unfenced, DB healthy, and verified point healthy/unchanged."""
    fx = _setup_workspace_fixture(tmp_path)
    access_engine = fx["acc_engine"]
    recovery_engine = fx["rec_engine"]
    service = fx["service"]
    clock = fx["clock"]
    biz_db = fx["biz_db"]

    try:
        # 0. Missing recovery_service fails closed.
        assert _live_business_readiness(access_engine, None) is False

        # Enable access in access_meta (fixture seeds 'disabled' with NULL subject).
        with access_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE access_meta SET effective_access = 'enabled', "
                    "subject = 'sub-alpha-1' WHERE id = 1"
                )
            )

        # 1. Before any verified recovery point -> False.
        assert _live_business_readiness(access_engine, service) is False

        # 2. Capture first verified backup -> healthy -> True!
        actor, cmd1 = _capture_cmd("cap-h057-1")
        service.execute(actor, cmd1)
        assert _live_business_readiness(access_engine, service) is True

        # 3. Second capture with no changes -> unchanged -> still True!
        clock.advance(60_000)
        actor, cmd2 = _capture_cmd("cap-h057-2")
        service.execute(actor, cmd2)
        assert service.read_protection_status().protection_state == "unchanged"
        assert _live_business_readiness(access_engine, service) is True

        # 4. Access disabled -> False.
        with access_engine.begin() as conn:
            conn.execute(text("UPDATE access_meta SET effective_access = 'disabled' WHERE id = 1"))
        assert _live_business_readiness(access_engine, service) is False
        with access_engine.begin() as conn:
            conn.execute(text("UPDATE access_meta SET effective_access = 'enabled' WHERE id = 1"))
        assert _live_business_readiness(access_engine, service) is True

        # 5. Maintenance fence active -> False.
        with access_engine.begin() as conn:
            conn.execute(
                text("UPDATE access_meta SET maintenance_operation_id = :op WHERE id = 1"),
                {"op": OP_ID},
            )
        assert _live_business_readiness(access_engine, service) is False
        with access_engine.begin() as conn:
            conn.execute(
                text("UPDATE access_meta SET maintenance_operation_id = NULL WHERE id = 1")
            )
        assert _live_business_readiness(access_engine, service) is True

        # 6. Protection state degraded (overdue) -> False.
        with recovery_engine.begin() as conn:
            conn.execute(text("UPDATE backup_state SET protection_state = 'overdue' WHERE id = 1"))
        assert _live_business_readiness(access_engine, service) is False
        with recovery_engine.begin() as conn:
            conn.execute(text("UPDATE backup_state SET protection_state = 'healthy' WHERE id = 1"))
        assert _live_business_readiness(access_engine, service) is True

        # 7. Corrupt business DB -> startup mode switches to recovery -> False.
        biz_db.write_bytes(b"corrupted-not-sqlite")
        assert _live_business_readiness(access_engine, service) is False
    finally:
        access_engine.dispose()
        recovery_engine.dispose()

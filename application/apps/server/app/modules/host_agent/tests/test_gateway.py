"""Closed ingress projection, immutable deny receipts and fail-closed gateway effects."""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, event

from app.modules.host_agent.application.ingress import IngressRecord, IngressProjection
from app.modules.host_agent.application.dispatch import (
    HostAgentUnavailable,
    IngressPolicy,
)
from app.modules.host_agent.infrastructure.gateway import (
    Gateway,
    GatewaySettings,
    HostEffects,
    closed_config,
)
from app.modules.host_agent.tests.test_runtime_effects import runtime as runtime
from app.modules.host_agent.tests.test_agent import (
    setup as setup,
    ready,
    rows,
    follow,
)


@pytest.fixture
def gateway(setup):
    active = {}
    calls = []
    failures = set()
    settings = GatewaySettings(Path("/run/epm-caddy/admin.sock"), 1001)

    def load(config):
        calls.append("load")
        if "load" in failures:
            raise OSError("reload failed; old config remains")
        active.clear()
        active.update(deepcopy(config))

    def inspect():
        if "inspect" in failures:
            raise OSError("admin unavailable")
        return deepcopy(active)

    def contain(command, allocation):
        calls.append("contain")
        if "contain" in failures:
            raise OSError("cannot verify containment")

    value = Gateway(setup.inventory, SimpleNamespace(load=load, inspect=inspect), settings, contain)
    setup.agent.driver = HostEffects(setup.driver, value)
    return SimpleNamespace(value=value, active=active, calls=calls, failures=failures, setup=setup)


def test_new_binding_is_held_and_config_is_exact_closed_projection(gateway):
    ready(gateway.setup)
    config = gateway.active
    assert config["admin"]["listen"] == "unix//run/epm-caddy/admin.sock"
    assert config["admin"]["config"]["persist"] is False
    server = config["apps"]["http"]["servers"]["gateway"]
    assert server["listen"] == ["127.0.0.1:8080"]
    assert len(server["routes"]) == 2
    denied = server["routes"][0]
    assert denied["handle"][0]["status_code"] == 503
    assert denied["handle"][0]["headers"]["Cache-Control"] == ["no-store"]
    assert server["routes"][-1]["handle"][0]["status_code"] == 403
    assert "reverse_proxy" not in str(config)
    assert "Forwarded" in str(denied["match"])
    assert gateway.setup.inventory.ingress_projection().records[0].desired_state == "held"


def test_deny_is_committed_before_load_and_retained_after_provider_failure(gateway):
    ready(gateway.setup)
    command = follow(
        gateway.setup, IngressPolicy(desired_state="blocked", expected_ingress_revision=1), epoch=2
    )
    gateway.failures.add("load")
    assert gateway.setup.agent.execute(command).state == "unknown"
    row = rows(gateway.setup, "ingress_bindings")[0]
    assert row["desired_state"] == "blocked" and row["access_epoch"] == 2
    assert gateway.calls[-2:] == ["load", "contain"]
    assert row["verified_state"] == "unknown"


def test_exact_retry_only_inspects_and_cannot_replay_failed_load(gateway):
    ready(gateway.setup)
    command = follow(
        gateway.setup, IngressPolicy(desired_state="blocked", expected_ingress_revision=1), epoch=2
    )
    gateway.failures.add("load")
    assert gateway.setup.agent.execute(command).state == "unknown"
    gateway.failures.clear()
    loads = gateway.calls.count("load")
    assert gateway.setup.agent.execute(command).state == "unknown"
    assert gateway.calls.count("load") == loads
    # A protected restart/reconciliation may load current desired inventory state;
    # it does not rerun an old historical effect or derive it from labels.
    gateway.value.reload_closed()
    assert gateway.setup.agent.execute(command).state == "applied"
    assert gateway.calls.count("load") == loads + 1
    row = rows(gateway.setup, "ingress_bindings")[0]
    assert row["verified_state"] == "blocked" and row["verified_revision"] == row["revision"]


def test_normal_deny_verifies_config_and_long_lived_containment_before_receipt(gateway):
    ready(gateway.setup)
    command = follow(
        gateway.setup, IngressPolicy(desired_state="blocked", expected_ingress_revision=1), epoch=2
    )
    result = gateway.setup.agent.execute(command)
    assert result.state == "applied"
    assert gateway.calls.count("contain") == 2
    before = list(gateway.calls)
    assert gateway.setup.agent.execute(command) == result
    assert gateway.calls == before


@pytest.mark.parametrize("failure", ["inspect", "contain"])
def test_uncertain_deny_never_claims_verified(gateway, failure):
    ready(gateway.setup)
    gateway.failures.add(failure)
    command = follow(
        gateway.setup, IngressPolicy(desired_state="blocked", expected_ingress_revision=1), epoch=2
    )
    assert gateway.setup.agent.execute(command).state == "unknown"
    assert rows(gateway.setup, "ingress_bindings")[0]["verified_state"] == "unknown"


def test_local_flags_or_unknown_eligibility_never_create_positive_routes(gateway):
    ready(gateway.setup)
    snapshot = gateway.setup.inventory.ingress_projection()
    row = snapshot.records[0].model_copy(update={"desired_state": "eligible"})
    with pytest.raises(HostAgentUnavailable):
        closed_config(IngressProjection(records=(row,)), gateway.value.settings)
    with pytest.raises(ValidationError):
        IngressProjection(records=(snapshot.records[0], snapshot.records[0]))


@pytest.mark.parametrize(
    "origin",
    [
        "http://a.example.invalid",
        "https://a.example.invalid:443",
        "https://admin.example.invalid",
        "https://a.example.invalid/path",
        "https://a.example.invalid.",
        "https://A.example.invalid",
        "https://a.example.invalid@evil.invalid",
        "https://a..invalid",
    ],
)
def test_malformed_registered_origin_rejects(gateway, origin):
    ready(gateway.setup)
    row = gateway.setup.inventory.ingress_projection().records[0]
    with pytest.raises(ValidationError):
        IngressRecord(**(row.model_dump() | {"public_origin": origin}))


def test_deny_projection_read_budget_is_bounded(setup):
    from app.modules.host_agent.tests.test_agent import prepare, OTHER, uid

    ready(setup)
    statements = []

    def trace(connection, cursor, statement, *args):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", trace)
    try:
        assert len(setup.inventory.ingress_projection().records) == 1
        first = list(statements)
        setup.agent.execute(setup.admission.add(prepare(operator=OTHER, binding=uid("second"))))
        statements.clear()
        assert len(setup.inventory.ingress_projection().records) == 2
        assert len(statements) == len(first)
        selects = [
            sql
            for sql in statements
            if sql.lstrip().upper().startswith("SELECT") and "FROM ingress_bindings" in sql
        ]
        assert len(selects) == 1 and "LIMIT" in selects[0]
    finally:
        event.remove(Engine, "before_cursor_execute", trace)


def test_failed_load_and_containment_preserve_both_errors(gateway):
    ready(gateway.setup)
    gateway.failures.update({"load", "contain"})
    command = follow(
        gateway.setup, IngressPolicy(desired_state="blocked", expected_ingress_revision=1), epoch=2
    )
    from app.modules.host_agent.application.dispatch import AdmittedEffect

    admitted = gateway.setup.agent.admission.resolve(command)
    assert isinstance(admitted, AdmittedEffect)
    with gateway.setup.inventory.exclusive():
        _, allocation, _ = gateway.setup.inventory.reserve(admitted, gateway.setup.agent.clock())
        with pytest.raises(ExceptionGroup) as caught:
            gateway.value.apply(command, allocation)
    assert len(caught.value.exceptions) == 2
    assert "reload failed" in str(caught.value.exceptions[0])
    assert "cannot verify containment" in str(caught.value.exceptions[1])


def test_caddy_load_refuses_default_tcp_admin_before_io():
    from app.modules.host_agent.application.dispatch import HostAgentDenied
    from app.modules.host_agent.infrastructure.gateway import CaddyAdmin

    admin = CaddyAdmin(GatewaySettings(Path("/run/epm-caddy/admin.sock"), 1001))
    with pytest.raises(HostAgentDenied):
        admin.load({"apps": {}})


def test_start_projection_contains_uncommitted_runtime_under_gate(runtime):
    from app.modules.host_agent.infrastructure.gateway import IngressContainment

    gates = []

    @contextmanager
    def lock(name, *, wait):
        assert name == "gate.lock" and wait
        gates.append("locked")
        try:
            yield
        finally:
            gates.append("unlocked")

    registry = runtime.driver.stops
    registry.lock = lock
    original = registry.contain

    def contain(engine, target):
        assert gates == ["locked"]
        original(engine, target)

    registry.contain = contain
    runtime.actual["State"]["Running"] = True
    allocation = runtime.allocation.model_copy(update={"container_ref": None})
    IngressContainment(registry, runtime.driver.engine)(runtime.command, allocation)
    assert runtime.actual["State"]["Running"] is False
    assert runtime.events == ["stop"] and gates == ["locked", "unlocked"]


def test_retained_container_is_stopped_even_without_start_projection(runtime):
    from contextlib import nullcontext
    from app.modules.host_agent.infrastructure.gateway import IngressContainment

    registry = SimpleNamespace(lock=lambda *a, **k: nullcontext(), targets=lambda: ())
    runtime.actual["State"]["Running"] = True
    IngressContainment(registry, runtime.driver.engine)(runtime.command, runtime.allocation)
    assert runtime.events == ["stop"] and runtime.actual["State"]["Running"] is False


def test_corrupt_stop_projection_never_proves_absence(runtime):
    from contextlib import nullcontext
    from app.modules.host_agent.infrastructure.gateway import IngressContainment

    def unavailable():
        raise HostAgentUnavailable()

    registry = SimpleNamespace(lock=lambda *a, **k: nullcontext(), targets=unavailable)
    with pytest.raises(HostAgentUnavailable):
        IngressContainment(registry, runtime.driver.engine)(
            runtime.command, runtime.allocation.model_copy(update={"container_ref": None})
        )


@pytest.mark.parametrize("retry", [False, True])
def test_projection_failure_still_contains_runtime(gateway, monkeypatch, retry):
    ready(gateway.setup)
    command = follow(
        gateway.setup, IngressPolicy(desired_state="blocked", expected_ingress_revision=1), epoch=2
    )
    if retry:
        gateway.failures.add("load")
        assert gateway.setup.agent.execute(command).state == "unknown"
        gateway.failures.clear()

    def corrupted():
        raise HostAgentUnavailable()

    monkeypatch.setattr(gateway.setup.inventory, "ingress_projection", corrupted)
    before = gateway.calls.count("contain")
    assert gateway.setup.agent.execute(command).state == "unknown"
    assert gateway.calls.count("contain") == before + 1


def test_corrupt_projection_does_not_prevent_other_exact_target_containment(runtime):
    from contextlib import nullcontext
    from app.modules.host_agent.infrastructure.gateway import IngressContainment

    target = runtime.driver.stops.target("original")

    def read(name):
        if name == "corrupt":
            raise HostAgentUnavailable()
        return target

    registry = SimpleNamespace(
        lock=lambda *a, **k: nullcontext(),
        targets=lambda: ("corrupt", "valid"),
        target=read,
        contain=lambda engine, target: engine.stop(target.container_id),
    )
    runtime.actual["State"]["Running"] = True
    with pytest.raises(ExceptionGroup) as caught:
        IngressContainment(registry, runtime.driver.engine)(runtime.command, runtime.allocation)
    assert len(caught.value.exceptions) == 1
    assert runtime.actual["State"]["Running"] is False


def test_lost_stop_reply_is_verified_without_repeating_a_stopped_effect(runtime):
    from contextlib import nullcontext
    from app.modules.host_agent.infrastructure.gateway import IngressContainment

    registry = SimpleNamespace(lock=lambda *a, **k: nullcontext(), targets=lambda: ())
    original = runtime.driver.engine.stop

    def lost(identity):
        original(identity)
        raise OSError("reply lost")

    runtime.driver.engine.stop = lost
    runtime.actual["State"]["Running"] = True
    contain = IngressContainment(registry, runtime.driver.engine)
    contain(runtime.command, runtime.allocation)
    contain(runtime.command, runtime.allocation)
    assert runtime.events == ["stop"]


def auth_command(gateway):
    from app.modules.host_agent.application.auth_routes import ApplyAuthRoutes, AuthRouteManifest
    from app.modules.host_agent.application.dispatch import HostEffect
    from app.modules.host_agent.application.contracts import StartContainer
    from app.modules.host_agent.infrastructure.auth_projection import VerifiedAuthEndpoint
    from app.modules.host_agent.tests.test_agent import BINDING, ID, prepare
    from app.platform.hosted_contracts.semantic import semantic_hash

    setup = gateway.setup
    ready(setup)
    setup.agent.execute(follow(setup, StartContainer(binding_id=BINDING)))
    binding = rows(setup, "resource_bindings")[0]
    assert binding["state"] == "running"
    manifest = AuthRouteManifest(component_id=ID, artifact_sha256="a" * 64, private_endpoint_id=ID)
    effect = prepare().effect.model_copy(
        update={"kind": "apply_auth_routes", "slot": "auth_routes"}
    )
    command = setup.admission.add(
        HostEffect(
            effect=effect,
            access_epoch=1,
            expected_revision=binding["revision"],
            payload=ApplyAuthRoutes(
                effect=effect,
                access_epoch=1,
                expected_ingress_revision=1,
                manifest_ref="auth-manifest",
                manifest_sha256=semantic_hash(manifest),
            ),
        )
    )
    gateway.value.auth_endpoints = SimpleNamespace(
        resolve_held=lambda evidence: VerifiedAuthEndpoint(
            manifest, "10.3.0.2", 8443, "source.local"
        ),
        resolve_shared=lambda: (None, None),
    )
    return command


def test_auth_projection_readiness_reboot_and_newer_deny(gateway):
    command = auth_command(gateway)
    agent = gateway.setup.agent
    assert agent.execute(command).state == "applied"
    (evidence,) = gateway.setup.inventory.auth_ready()
    assert evidence.auth_access_epoch == 1
    assert evidence.auth_operation_id == command.effect.child_id()
    active = deepcopy(gateway.active)
    routes = active["apps"]["http"]["servers"]["gateway"]["routes"]
    assert [route["match"][0]["method"] for route in routes[:3]] == [["GET"], ["POST"], ["GET"]]
    assert "/auth/start" in routes[0]["match"][0]["expression"]
    assert not any("/api" in str(route) for route in routes)
    gateway.active.clear()
    gateway.value.reload_closed()
    assert gateway.active == active
    block = follow(
        gateway.setup,
        IngressPolicy(
            desired_state="blocked",
            expected_ingress_revision=evidence.ingress_revision,
        ),
        epoch=2,
    )
    assert agent.execute(block).state == "applied"
    assert gateway.setup.inventory.auth_ready() == ()
    assert "reverse_proxy" not in str(gateway.active)
    assert agent.execute(command).state == "applied"  # historical receipt only
    assert "reverse_proxy" not in str(gateway.active)


def test_unknown_apply_auth_cannot_publish_ready(gateway):
    command = auth_command(gateway)
    gateway.failures.add("inspect")
    assert gateway.setup.agent.execute(command).state == "unknown"
    assert gateway.setup.inventory.auth_ready() == ()
    assert "reverse_proxy" not in str(gateway.active)
    assert "contain" in gateway.calls


def test_shared_auth_routes_require_owning_login_origin_and_exact_assets():
    from app.modules.host_agent.application.auth_routes import SharedIdentityManifest
    from app.modules.host_agent.application.dispatch import HostAgentDenied
    from app.modules.host_agent.infrastructure.auth_projection import (
        VerifiedAuthEndpoint,
        auth_config,
    )
    from app.modules.host_agent.tests.test_agent import ID

    manifest = SharedIdentityManifest(
        component_id=ID,
        artifact_sha256="a" * 64,
        private_endpoint_id=ID,
        central_origin="https://login.example.invalid",
        admin_origin="https://admin.example.invalid",
        owning_login_origin="https://login.example.invalid",
    )
    endpoint = VerifiedAuthEndpoint(
        manifest,
        "fd00::a",
        8443,
        "identity.local",
        admin_assets=("/assets/admin-test.js",),
        central_assets=("/assets/login-test.js",),
    )
    projection = IngressProjection(records=())
    settings = GatewaySettings(Path("/run/epm-caddy/admin.sock"), 1001)
    with pytest.raises(HostAgentDenied):
        auth_config(
            projection, settings, shared=endpoint, login_origin="https://other.example.invalid"
        )
    config = auth_config(
        projection, settings, shared=endpoint, login_origin=manifest.central_origin
    )
    routes = config["apps"]["http"]["servers"]["gateway"]["routes"]
    proxies = routes[:-1]
    assert all(r["handle"][0]["upstreams"] == [{"dial": "[fd00::a]:8443"}] for r in proxies)
    assert any(
        r["match"][0]["host"] == ["login.example.invalid"]
        and "/__/auth/handler" in r["match"][0]["expression"]
        for r in proxies
    )
    assert not any(
        r["match"][0]["host"] == ["admin.example.invalid"]
        and "/__/auth/handler" in r["match"][0]["expression"]
        for r in proxies
    )
    assert len(proxies) == len(manifest.central_routes) + len(manifest.admin_routes) + 3


def test_shared_endpoint_owner_requires_pinned_manifest_before_native_inspection():
    from unittest.mock import Mock

    from app.modules.host_agent.application.auth_routes import SharedIdentityManifest
    from app.modules.host_agent.application.dispatch import HostAgentDenied
    from app.modules.host_agent.infrastructure.auth_endpoints import (
        AuthEndpoints,
        SharedAuthSelection,
    )
    from app.modules.host_agent.infrastructure.auth_projection import VerifiedAuthEndpoint
    from app.modules.host_agent.tests.test_agent import ID
    from app.platform.hosted_contracts.semantic import semantic_hash

    manifest = SharedIdentityManifest(
        component_id=ID,
        artifact_sha256="a" * 64,
        private_endpoint_id=ID,
        central_origin="https://login.example.invalid",
        admin_origin="https://admin.example.invalid",
        owning_login_origin="https://login.example.invalid",
    )
    manifests = Mock()
    manifests.shared.return_value = manifest
    manifests.login_origin.return_value = manifest.central_origin
    native = Mock()
    with pytest.raises(HostAgentDenied):
        AuthEndpoints(
            manifests, native, shared=SharedAuthSelection("shared", "0" * 64)
        ).resolve_shared()
    native.shared.assert_not_called()
    endpoint = VerifiedAuthEndpoint(manifest, "10.3.0.2", 8443, "identity.local")
    native.shared.return_value = endpoint
    resolved = AuthEndpoints(
        manifests, native, shared=SharedAuthSelection("shared", semantic_hash(manifest))
    )
    assert resolved.resolve_shared() == (endpoint, manifest.central_origin)
    native.shared.assert_called_once_with(manifest)


def test_runtime_projects_verified_shared_hosts_to_gateway_and_tunnel(monkeypatch, tmp_path):
    import json
    import re
    from types import SimpleNamespace

    from app.modules.host_agent.application.auth_routes import SharedIdentityManifest
    from app.modules.host_agent.application.ingress import IngressProjection
    from app.modules.host_agent.infrastructure.auth_projection import VerifiedAuthEndpoint
    from app.modules.host_agent.infrastructure.host_services import TunnelSettings
    from app.modules.host_agent.infrastructure.service_runtime import ServiceRuntime
    from app.modules.host_agent.tests.test_agent import ID

    manifest = SharedIdentityManifest(
        component_id=ID,
        artifact_sha256="a" * 64,
        private_endpoint_id=ID,
        central_origin="https://login.example.invalid",
        admin_origin="https://admin.example.invalid",
        owning_login_origin="https://login.example.invalid",
    )
    stops = tmp_path.resolve() / "stops"
    stops.mkdir(mode=0o700)
    runtime = ServiceRuntime(
        SimpleNamespace(
            layout=SimpleNamespace(stops=str(stops)),
            network=None,
            tunnel=TunnelSettings(tunnel_id=ID),
        )
    )
    endpoint = VerifiedAuthEndpoint(manifest, "10.3.0.2", 8000, "identity.local")
    monkeypatch.setattr(
        runtime,
        "registered_sources",
        lambda _: SimpleNamespace(resolve_shared=lambda: (endpoint, manifest.central_origin)),
    )
    gateway, tunnel = runtime.ingress_projection(
        SimpleNamespace(auth_ready=lambda: ()),
        IngressProjection(records=()),
        GatewaySettings(Path("/run/epm-caddy/admin.sock"), 1001),
    )
    routes = gateway["apps"]["http"]["servers"]["gateway"]["routes"][:-1]
    central = [
        row["match"][0] for row in routes if row["match"][0]["host"] == ["login.example.invalid"]
    ]
    for method, path in manifest.central_routes:
        pattern = json.dumps("^" + re.escape(path) + r"(?:[?].*)?$")
        assert any(row["method"] == [method] and pattern in row["expression"] for row in central)
    assert [item.get("hostname") for item in tunnel["ingress"]] == [
        "login.example.invalid",
        "admin.example.invalid",
        None,
    ]


def test_registered_source_rejects_stale_epoch_before_live_host_inspection():
    from unittest.mock import Mock

    from app.modules.host_agent.application.auth_routes import AuthRouteManifest
    from app.modules.host_agent.application.dispatch import HostAgentDenied
    from app.modules.host_agent.infrastructure.auth_registration import (
        AuthRegistration,
        RegisteredSources,
        SourceRegistration,
    )
    from app.modules.host_agent.tests.test_agent import ID, BINDING

    manifest = AuthRouteManifest(component_id=ID, artifact_sha256="a" * 64, private_endpoint_id=ID)
    registration = SourceRegistration(
        manifest_ref="pinned",
        manifest=manifest,
        binding_id=BINDING,
        resource_generation=1,
        socket_name=ID,
        tls_name="source.local",
    )
    inventory = Mock()
    inventory.identity.deployment_id = ID
    inventory.auth_target.return_value = {
        "binding_id": BINDING,
        "resource_generation": 1,
        "access_epoch": 2,
        "workspace_id": ID,
    }
    engine = Mock()
    sources = RegisteredSources(
        inventory,
        engine,
        Mock(),
        Mock(),
        AuthRegistration(sources=(registration,)),
        Path("/run/epm-source-identity"),
    )
    with pytest.raises(HostAgentDenied):
        sources.resolve_identity_source(ID, SimpleNamespace(operator_id=ID, workspace_id=ID), 1)
    engine.inspect.assert_not_called()


def test_auth_route_allows_matching_cloudflare_xff_and_strips_client_network():
    import json
    import re

    from app.modules.host_agent.application.auth_routes import SharedIdentityManifest
    from app.modules.host_agent.infrastructure.auth_projection import (
        VerifiedAuthEndpoint,
        auth_config,
    )
    from app.modules.host_agent.tests.test_agent import ID

    manifest = SharedIdentityManifest(
        component_id=ID,
        artifact_sha256="a" * 64,
        private_endpoint_id=ID,
        central_origin="https://login.example.invalid",
        admin_origin="https://admin.example.invalid",
        owning_login_origin="https://login.example.invalid",
    )
    endpoint = VerifiedAuthEndpoint(manifest, "10.3.0.2", 8000, "identity.local")
    config = auth_config(
        IngressProjection(records=()),
        GatewaySettings(Path("/run/epm-caddy/admin.sock"), 1001),
        shared=endpoint,
        login_origin=manifest.central_origin,
    )
    routes = config["apps"]["http"]["servers"]["gateway"]["routes"][:-1]
    for route in routes:
        denied_headers = {
            next(iter(item["header"])) for item in route["match"][0]["not"] if "header" in item
        }
        assert "X-Forwarded-For" not in denied_headers
        expr = route["match"][0]["expression"]
        assert "{http.request.header.Cf-Connecting-Ip}" in expr
        assert (
            "{http.request.header.X-Forwarded-For} == {http.request.header.Cf-Connecting-Ip}"
            in expr
        )
        req_headers = route["handle"][0]["headers"]["request"]
        assert "X-Forwarded-For" in req_headers["delete"]
        assert "Cf-Connecting-Ip" in req_headers["delete"]
        if (
            route["match"][0]["method"] == ["POST"]
            and json.dumps("^" + re.escape("/auth/email-link") + r"(?:[?].*)?$")
            in route["match"][0]["expression"]
        ):
            assert req_headers["set"]["X-Epm-Client-Network"] == [
                "{http.request.header.Cf-Connecting-Ip}"
            ]
            assert "X-Epm-Client-Network" not in req_headers["delete"]
        else:
            assert "X-Epm-Client-Network" in req_headers["delete"]


def test_auth_effect_inspect_only_does_not_contain_and_apply_failure_rolls_back_snapshot(gateway):
    from unittest.mock import Mock

    from app.modules.host_agent.application.auth_routes import SharedIdentityManifest
    from app.modules.host_agent.infrastructure.auth_projection import (
        VerifiedAuthEndpoint,
        auth_config,
    )
    from app.modules.host_agent.tests.test_agent import ID

    service = gateway.value
    manifest = SharedIdentityManifest(
        component_id=ID,
        artifact_sha256="a" * 64,
        private_endpoint_id=ID,
        central_origin="https://login.example.invalid",
        admin_origin="https://admin.example.invalid",
        owning_login_origin="https://login.example.invalid",
    )
    shared = VerifiedAuthEndpoint(manifest, "10.3.0.2", 8000, "identity.local")
    service.auth_endpoints = SimpleNamespace(
        resolve_held=Mock(side_effect=HostAgentUnavailable()),
        resolve_shared=lambda: (shared, manifest.central_origin),
    )
    _, expected_previous = service._snapshot()
    command = SimpleNamespace(
        payload=SimpleNamespace(
            expected_ingress_revision=1, manifest_ref="pinned", manifest_sha256="a" * 64
        ),
        effect=SimpleNamespace(binding_id=ID, resource_generation=1, child_id=lambda: ID),
        access_epoch=1,
    )
    allocation = SimpleNamespace(
        ingress_projection_revision=3, binding_id=ID, resource_generation=1, access_epoch=1
    )
    gateway.calls.clear()
    with pytest.raises(HostAgentUnavailable):
        service.auth_effect(command, allocation, inspect_only=True)
    assert gateway.calls == []

    with pytest.raises(HostAgentUnavailable):
        service.auth_effect(command, allocation, inspect_only=False)
    assert "contain" in gateway.calls
    assert gateway.active == expected_previous
    assert gateway.active == auth_config(
        service.inventory.ingress_projection(),
        service.settings,
        shared=shared,
        login_origin=manifest.central_origin,
    )

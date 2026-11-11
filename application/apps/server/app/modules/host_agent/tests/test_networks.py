"""Inventory-derived network checks; mocks are not native isolation qualification."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.host_agent.application.dispatch import HostAgentDenied, HostAgentUnavailable
from app.modules.host_agent.application.network import NetworkProjection, NetworkRecord
from app.modules.host_agent.infrastructure.network_policy import NetworkSettings, bridge
from app.modules.host_agent.infrastructure.network_firewall import (
    firewall_document,
    expected,
    normalized,
)
from app.modules.host_agent.infrastructure.operator_networks import OperatorNetworks
from app.modules.host_agent.infrastructure.container_policy import container_spec
from app.modules.host_agent.tests.test_agent import setup as setup, ready, prepare, OTHER, uid
from app.modules.host_agent.tests.test_runtime_effects import runtime as runtime


def settings(**updates):
    return NetworkSettings(
        **(
            dict(
                ipv4_pool="10.240.0.0/16",
                ipv6_pool="fd47:6570:6d00::/48",
                first_project=1,
                gateway_uid=800,
                tunnel_uid=801,
                proxy_uid=802,
            )
            | updates
        )
    )


def test_inventory_slots_are_exclusive_and_stable(setup):
    ready(setup)
    first = setup.inventory.network_projection().records[0]
    setup.agent.execute(setup.admission.add(prepare(operator=OTHER, binding=uid("second"))))
    rows = setup.inventory.network_projection().records
    assert first in rows and len(rows) == 2
    targets = [bridge(row, settings()) for row in rows]
    assert len({v.ipv4 for v in targets}) == len({v.ipv6 for v in targets}) == 2
    assert bridge(first, settings()) in targets
    with pytest.raises(ValidationError):
        NetworkProjection(records=(first, first))


@pytest.mark.parametrize(
    "updates",
    [
        {"gateway_uid": 0},
        {"proxy_uid": 800},
        {"ipv4_pool": "169.254.0.0/16"},
        {"ipv6_pool": "2001:db8::/48"},
        {"first_project": 0},
        {"proxy_port": 8080},
    ],
)
def test_unsafe_protected_settings_reject(updates):
    with pytest.raises(HostAgentDenied):
        settings(**updates)


def test_out_of_pool_slot_never_wraps(setup):
    ready(setup)
    row = setup.inventory.network_projection().records[0]
    with pytest.raises(HostAgentDenied):
        bridge(row.model_copy(update={"workspace_project": 65537}), settings())


@pytest.fixture
def networks(setup):
    ready(setup)
    events, state = [], {}

    def create(target):
        events.append("create")
        state[target.name] = target.spec() | {"Containers": {}}

    engine = SimpleNamespace(
        inspect_network=lambda name: deepcopy(state.get(name)), create_network=create
    )
    firewall = SimpleNamespace(
        apply=lambda targets: events.append("apply"),
        verify=lambda targets: events.append("verify"),
    )
    command = prepare()
    with setup.inventory.transaction(write=False) as connection:
        allocation = setup.inventory.allocation(connection, command)
    return SimpleNamespace(
        service=OperatorNetworks(
            setup.inventory,
            engine,
            firewall,
            settings(),
            prerequisites=SimpleNamespace(verify=lambda targets: None),
        ),
        command=command,
        allocation=allocation,
        state=state,
        events=events,
    )


def test_prepare_denies_before_create_and_retry_only_verifies_existing(networks):
    target = networks.service.prepare(networks.command, networks.allocation)
    assert networks.events == ["apply", "create", "verify"]
    networks.service.prepare(networks.command, networks.allocation)
    assert networks.events.count("create") == 1
    networks.state[target.name]["Internal"] = False
    with pytest.raises(HostAgentDenied):
        networks.service.prepare(networks.command, networks.allocation)
    assert networks.events.count("create") == 1


def test_changed_scope_or_project_cannot_select_another_bridge(networks):
    for update in ({"workspace_project": 999}, {"resource_generation": 2}):
        with pytest.raises(HostAgentDenied):
            networks.service.prepare(
                networks.command, networks.allocation.model_copy(update=update)
            )
    assert networks.events == []


def test_unknown_firewall_never_creates_bridge(networks):
    def down(*args):
        raise HostAgentUnavailable()

    networks.service.firewall.apply = down
    with pytest.raises(HostAgentUnavailable):
        networks.service.prepare(networks.command, networks.allocation)
    assert networks.events == []


def test_unexpected_peer_or_second_network_is_not_adopted(networks):
    target = networks.service.prepare(networks.command, networks.allocation)
    networks.state[target.name]["Containers"] = {
        "foreign": {
            "IPv4Address": "10.240.0.3/30",
            "IPv6Address": target.address6 + "/64",
        }
    }
    with pytest.raises(HostAgentDenied):
        networks.service.verify(networks.command, networks.allocation)
    with pytest.raises(HostAgentDenied):
        networks.service.verify_container(target, {"NetworkSettings": {"Networks": {"other": {}}}})


def test_networked_spec_preserves_sandbox_and_unpublished_ports(runtime):
    row = NetworkRecord(
        binding_id=runtime.command.effect.binding_id,
        operator_id=runtime.command.effect.parent.scope.operator_id,
        workspace_id=runtime.command.effect.parent.scope.workspace_id,
        resource_generation=1,
        workspace_project=101,
    )
    target = bridge(row, settings())
    spec = container_spec(
        runtime.command,
        runtime.allocation,
        runtime.driver.storage.targets,
        runtime.profile,
        network=target,
    )
    assert spec["HostConfig"]["NetworkMode"] == target.name
    assert spec["HostConfig"]["PortBindings"] == {} and not spec["HostConfig"]["PublishAllPorts"]
    assert spec["HostConfig"]["Dns"] == ["127.0.0.1"]
    assert spec["HostConfig"]["ReadonlyRootfs"] and spec["HostConfig"]["CapDrop"] == ["ALL"]
    assert spec["NetworkingConfig"]["EndpointsConfig"] == target.endpoint()
    assert "HTTP_PROXY" not in str(spec)
    assert f"HTTPS_PROXY=http://{target.gateway4}:{target.proxy_port}" in spec["Env"]


def test_dual_stack_firewall_covers_docker_forwarding():
    document = firewall_document((), settings())
    objects = expected(document)
    assert normalized({"nftables": objects}) == objects
    chains = [entry["chain"] for entry in objects if "chain" in entry]
    assert {chain["hook"] for chain in chains} == {"input", "output", "forward"}
    assert all(chain["prio"] < 0 for chain in chains)
    text = str(document)
    assert "10.240.0.0" in text and "fd47:6570:6d00::" in text
    assert "epm-*" in text and "skuid" in text
    assert "169.254.0.0" in text and "fe80::" in text
    forwards = [
        entry["rule"]
        for entry in objects
        if "rule" in entry and entry["rule"]["chain"] == "forward"
    ]
    assert len(forwards) == 2 and all(row["expr"][-1] == {"drop": None} for row in forwards)


def test_runtime_rechecks_network_on_start_and_supervisor_contains_drift(runtime):
    from app.modules.host_agent.tests.test_runtime_effects import action

    events = []

    def drift(*args):
        events.append("network")
        raise HostAgentUnavailable()

    runtime.driver.networks = SimpleNamespace(verify=drift, qualification_hash=lambda value: value)
    with pytest.raises(HostAgentUnavailable):
        runtime.driver.apply(action(runtime, "start_container"), runtime.allocation)
    assert "start" not in runtime.events and events == ["network"]
    runtime.actual["State"]["Running"] = True
    assert runtime.driver.supervise(runtime.command, runtime.allocation) == "needs_attention"
    assert runtime.actual["State"]["Running"] is False


def test_firewall_inspection_rejects_removed_rule_or_changed_uid(monkeypatch):
    from app.modules.host_agent.infrastructure.network_firewall import NetworkFirewall

    value = NetworkFirewall(settings())
    monkeypatch.setattr(value, "prerequisites", lambda: None)
    clean = {"nftables": expected(firewall_document((), settings()))}
    monkeypatch.setattr(value, "_run", lambda *args: deepcopy(clean))
    value.verify(())
    damaged = deepcopy(clean)
    damaged["nftables"].pop()
    monkeypatch.setattr(value, "_run", lambda *args: damaged)
    with pytest.raises(HostAgentUnavailable):
        value.verify(())
    damaged = deepcopy(clean)
    for item in damaged["nftables"]:
        for expression in item.get("rule", {}).get("expr", []):
            if expression.get("match", {}).get("left") == {"meta": {"key": "skuid"}}:
                expression["match"]["right"] = 0
    with pytest.raises(HostAgentUnavailable):
        value.verify(())


def test_firewall_comparison_preserves_extra_predicates_and_rule_order():
    from app.modules.host_agent.infrastructure.network_firewall import normalized_expr, meta

    values = [meta("skuid", 800), meta("nfproto", "ipv6"), {"drop": None}]
    assert normalized_expr(values) == values
    assert normalized(
        {
            "nftables": [
                {"chain": {"name": "forward"}},
                {"rule": {"chain": "forward", "expr": [{"drop": None}]}},
                {"rule": {"chain": "forward", "expr": [{"accept": None}]}},
            ]
        }
    ) != normalized(
        {
            "nftables": [
                {"chain": {"name": "forward"}},
                {"rule": {"chain": "forward", "expr": [{"accept": None}]}},
                {"rule": {"chain": "forward", "expr": [{"drop": None}]}},
            ]
        }
    )


@pytest.mark.parametrize(
    "route",
    [
        {"dst": "10.240.0.0/16", "dev": "other"},
        {"dst": "fd47:6570:6d00::/48", "dev": "eth0"},
    ],
)
def test_conflicting_host_routes_fail_before_creation(route, monkeypatch):
    from app.modules.host_agent.infrastructure.network_prerequisites import HostNetworkPrerequisites

    value = HostNetworkPrerequisites(SimpleNamespace(networks=lambda: []), settings())
    monkeypatch.setattr(value, "routes", lambda: [route])
    with pytest.raises(HostAgentDenied):
        value.verify(())


def test_conflicting_docker_pool_cannot_be_adopted(monkeypatch):
    from app.modules.host_agent.infrastructure.network_prerequisites import HostNetworkPrerequisites

    actual = {"Name": "foreign", "IPAM": {"Config": [{"Subnet": "10.240.0.0/24"}]}}
    value = HostNetworkPrerequisites(SimpleNamespace(networks=lambda: [actual]), settings())
    monkeypatch.setattr(value, "routes", lambda: [])
    with pytest.raises(HostAgentDenied):
        value.verify(())


def test_static_addresses_are_verified_before_start_and_dynamic_drift_rejects(networks):
    target = networks.service.prepare(networks.command, networks.allocation)
    actual = {
        "State": {"Running": False},
        "NetworkSettings": {
            "Networks": {
                target.name: {
                    "IPAMConfig": target.endpoint()[target.name]["IPAMConfig"],
                    "IPAddress": "",
                    "GlobalIPv6Address": "",
                },
            }
        },
    }
    networks.service.verify_container(target, actual)
    actual["State"]["Running"] = True
    with pytest.raises(HostAgentUnavailable):
        networks.service.verify_container(target, actual)
    peer = actual["NetworkSettings"]["Networks"][target.name]
    peer.update(IPAddress=target.address4, GlobalIPv6Address=target.address6)
    networks.service.verify_container(target, actual)
    peer["IPAMConfig"]["IPv4Address"] = "10.0.0.1"
    with pytest.raises(HostAgentDenied):
        networks.service.verify_container(target, actual)


def test_connected_policy_requires_a_new_native_qualification_hash(networks, runtime):
    original = runtime.driver._policy_hash()
    runtime.driver.networks = networks.service
    assert runtime.driver._policy_hash() != original
    assert runtime.driver._policy_hash() == networks.service.qualification_hash(original)


def test_docker_omitted_empty_iprange_is_equivalent_but_changed_ranges_reject(setup):
    ready(setup)
    target = bridge(setup.inventory.network_projection().records[0], settings())
    actual = target.spec()
    for row in actual["IPAM"]["Config"]:
        row.pop("IPRange")
    target.verify(actual)
    actual["IPAM"]["Config"][0]["IPRange"] = "10.240.0.2/32"
    with pytest.raises(HostAgentDenied):
        target.verify(actual)
    actual["IPAM"]["Config"][0].pop("IPRange")
    actual["Options"]["com.docker.network.bridge.enable_icc"] = "true"
    with pytest.raises(HostAgentDenied):
        target.verify(actual)

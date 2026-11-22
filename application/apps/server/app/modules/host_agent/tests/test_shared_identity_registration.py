"""Protected shared endpoint registration and negative native observations."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID
import pytest

from app.modules.host_agent.application.auth_routes import SharedIdentityManifest
from app.modules.host_agent.application.dispatch import HostAgentDenied, HostAgentUnavailable
from app.modules.host_agent.application.ingress import IngressProjection
from app.modules.host_agent.infrastructure import shared_identity_registration as registration
from app.modules.host_agent.infrastructure.auth_registration import (
    AuthRegistration,
    RegisteredSources,
)
from app.modules.host_agent.infrastructure.gateway import GatewaySettings
from app.modules.host_agent.infrastructure.host_services import TunnelSettings
from app.modules.host_agent.infrastructure.network_policy import (
    NetworkSettings,
    SharedIdentityNetwork,
)
from app.modules.host_agent.infrastructure.service_runtime import ServiceRuntime
from app.platform.hosted_contracts.semantic import semantic_hash

ID = "00000000-0000-4000-8000-000000000001"
LOGIN = "https://login.example.invalid"
ADMIN = "https://admin.example.invalid"
CONTAINER = "c" * 64


@pytest.fixture
def shared(tmp_path, monkeypatch):
    import os

    key = Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "identity.example.invalid")])
    now = datetime.now(UTC)
    tls = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(minutes=1))
        .sign(key, None)
    )
    manifest = SharedIdentityManifest(
        component_id=ID,
        artifact_sha256="a" * 64,
        private_endpoint_id=ID,
        central_origin=LOGIN,
        admin_origin=ADMIN,
        owning_login_origin=LOGIN,
    )
    database = tmp_path / "retained.sqlite"
    connection = sqlite3.connect(database)
    with connection:
        connection.execute("CREATE TABLE control_meta (id, deployment_id, login_origin)")
        connection.execute("INSERT INTO control_meta VALUES (1, ?, ?)", (ID, LOGIN))
    connection.close()
    database.chmod(0o600)
    uid = os.geteuid()
    if uid == 0:
        uid = 65532
        os.chown(database, uid, uid)

    selected = registration.SharedRegistration(
        manifest=manifest,
        manifest_sha256=semantic_hash(manifest),
        container_id=CONTAINER,
        image_config_sha256="d" * 64,
        runtime_uid=uid,
        runtime_gid=uid,
        admin_database=database,
        firebase_project="synthetic-project",
        tls_name="identity.example.invalid",
        trust_pem=tls.public_bytes(Encoding.PEM).decode(),
        admin_index_sha256="e" * 64,
        admin_assets=(registration.IdentityAsset(path="/assets/admin.js", sha256="f" * 64),),
        central_assets=(registration.IdentityAsset(path="/assets/login.js", sha256="b" * 64),),
    )
    settings = NetworkSettings(
        "10.240.0.0/16",
        "fd47:6570:6d00::/48",
        1,
        800,
        801,
        802,
        shared_identity=SharedIdentityNetwork(
            endpoint_id=ID,
            ipv4="10.241.0.0/30",
            ipv6="fd42:1::/64",
            proxy_uid=803,
            proxy_port=1081,
        ),
    )
    bridge = settings.shared_identity.bridge()
    network = bridge.spec() | {
        "Containers": {
            CONTAINER: {
                "IPv4Address": bridge.address4 + "/30",
                "IPv6Address": bridge.address6 + "/64",
            },
        }
    }
    engine = Mock()
    engine.inspect_network.return_value = network
    engine.networks.return_value = [network]
    engine.inspect.return_value = {
        "Id": CONTAINER,
        "Image": "sha256:" + selected.image_config_sha256,
        "Config": {
            "Image": "registry.example.invalid/image@sha256:" + manifest.artifact_sha256,
            "User": f"{uid}:{uid}",
        },
        "State": {"Running": True},
        "HostConfig": {
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
        },
        "NetworkSettings": {
            "Networks": {
                bridge.name: {
                    "IPAMConfig": bridge.endpoint()[bridge.name]["IPAMConfig"],
                    "IPAddress": bridge.address4,
                    "GlobalIPv6Address": bridge.address6,
                }
            }
        },
    }
    monkeypatch.setattr(registration.HostNetworkPrerequisites, "routes", staticmethod(lambda: []))
    probe = Mock()
    monkeypatch.setattr(registration, "probe_as_gateway", probe)
    inventory = SimpleNamespace(
        identity=SimpleNamespace(deployment_id=ID),
        network_projection=lambda: SimpleNamespace(records=()),
        auth_ready=lambda: (),
    )
    firewall = Mock()
    sources = RegisteredSources(
        inventory,
        engine,
        firewall,
        settings,
        AuthRegistration(sources=(), shared=selected),
        Path("/run/epm"),
        central_principal=(uid, uid),
    )
    return SimpleNamespace(
        sources=sources,
        inventory=inventory,
        settings=settings,
        engine=engine,
        firewall=firewall,
        registration=selected,
        probe=probe,
        bridge=bridge,
    )


def test_shared_registration_projects_only_native_verified_routes(shared, monkeypatch, tmp_path):
    runtime = ServiceRuntime(
        SimpleNamespace(
            layout=SimpleNamespace(stops=str(tmp_path)),
            network=shared.settings,
            tunnel=TunnelSettings(tunnel_id=ID),
        )
    )
    monkeypatch.setattr(runtime, "registered_sources", lambda _: shared.sources)
    projection = IngressProjection(records=())
    settings = GatewaySettings(tmp_path / "admin.sock", 800)
    config, tunnel = runtime.ingress_projection(shared.inventory, projection, settings)
    routes = config["apps"]["http"]["servers"]["gateway"]["routes"]
    assert {route["match"][0]["host"][0] for route in routes if route.get("match")} == {
        "admin.example.invalid",
        "login.example.invalid",
    }
    assert (
        "/assets/admin" in str(routes)
        or r"/assets/admin\." in str(routes)
        or "admin.js" in str(routes)
    )
    assert "root_ca_pool" in str(config)
    assert len(tunnel["ingress"]) == 3
    shared.firewall.verify.assert_called_once_with(())
    shared.probe.assert_called_once()
    assert shared.probe.call_args.args[2] == 800

    shared.firewall.verify.side_effect = HostAgentUnavailable()
    closed, tunnel = runtime.ingress_projection(shared.inventory, projection, settings)
    assert "reverse_proxy" not in str(closed)
    assert tunnel["ingress"] == [{"service": "http_status:403"}]
    assert shared.probe.call_count == 1


@pytest.mark.parametrize(
    "failure", ["image", "manifest", "privileged", "mount", "bridge", "origin", "tls"]
)
def test_shared_registration_refuses_stale_host_evidence(shared, failure):
    inspected = deepcopy(shared.engine.inspect.return_value)
    if failure == "image":
        inspected["Image"] = "sha256:" + "b" * 64
    elif failure == "manifest":
        inspected["Config"]["Image"] = "candidate:latest"
    elif failure == "privileged":
        inspected["HostConfig"]["Privileged"] = True
    elif failure == "mount":
        inspected["Mounts"] = [{"Type": "bind", "Destination": "/opt/epm/venv"}]
    elif failure == "bridge":
        shared.engine.inspect_network.return_value["Containers"] = {}
    elif failure == "origin":
        with sqlite3.connect(shared.registration.admin_database) as connection:
            connection.execute(
                "UPDATE control_meta SET login_origin='https://other.example.invalid'"
            )
    else:
        shared.probe.side_effect = HostAgentDenied()
    shared.engine.inspect.return_value = inspected
    with pytest.raises(HostAgentDenied):
        shared.sources.resolve_shared()


def test_probe_as_gateway_drops_both_uid_and_gid(shared, monkeypatch):
    from importlib import reload

    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=b"verified\n"))
    real_probe = reload(registration).probe_as_gateway
    monkeypatch.setattr(registration.subprocess, "run", run)
    real_probe(shared.registration, shared.bridge, 800, 801)
    assert run.call_args.kwargs["user"] == 800
    assert run.call_args.kwargs["group"] == 801
    assert run.call_args.kwargs["extra_groups"] == []

"""Two-phase native identity projection test on an isolated disposable Linux guest."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from threading import Event
from types import SimpleNamespace

from qualify_shared_identity import (
    ADMIN,
    ID,
    UID_CADDY,
    UID_PROXY,
    UID_SHARED,
    UID_TUNNEL,
    check_routes,
    create_fixture,
    execute,
    fixture_firewall,
    launch_peer,
    peer_is_listening,
    pin,
    probe_gate,
    register_peer,
    remove_firewall,
    stop_gateway,
    wait_ready,
)

from app.modules.host_agent.application.ingress import IngressProjection
from app.modules.host_agent.infrastructure.docker_engine import DockerEngine
from app.modules.host_agent.infrastructure.gateway import GatewaySettings
from app.modules.host_agent.infrastructure.host_services import TunnelSettings
from app.modules.host_agent.infrastructure.identity_relay import open_relay_socket, serve_identity
from app.modules.host_agent.infrastructure.ingress_bootstrap import (
    IngressBootstrap,
    ProjectionPublisher,
)
from app.modules.host_agent.infrastructure.service_runtime import ServiceRuntime
from app.modules.hosted_access.application.handoff_channel import ContinuationTarget

BOOT = Path("/proc/sys/kernel/random/boot_id")
RUN = Path("/run/epm-h0312-fixture")
STATE = Path("/var/tmp/epm-h0312-fixture")

RELAY_CLIENT = """
import json
import socket
import struct
import sys
from pathlib import Path
from app.modules.host_agent.application.dispatch import HostAgentDenied, HostAgentUnavailable
from app.modules.host_agent.infrastructure.identity_relay import invoke_identity
from app.modules.hosted_access.application.handoff_channel import ReadContinuation
if sys.argv[3] == "check-rejection":
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(sys.argv[1])
        with connection.makefile("rb") as stream:
            length = struct.unpack("!I", stream.read(4))[0]
            assert json.loads(stream.read(length)) == {"error": "denied"}
    sys.exit(0)

try:
    request = ReadContinuation.model_validate_json(sys.stdin.buffer.read())
    result = invoke_identity(Path(sys.argv[1]), request, expected_uid=int(sys.argv[2]))
    print(result.return_path)
except HostAgentDenied:
    print("peer-denied")
except HostAgentUnavailable:
    print("socket-unavailable")
"""


def check_socket():
    shared = RUN / "relay"
    shared.mkdir()
    os.chown(shared, 0, UID_SHARED)
    shared.chmod(0o750)
    call = {
        "method": "read_continuation",
        "continuation_id": ID,
        "binding": {
            "deployment_id": ID,
            "scope": {"operator_id": ID, "workspace_id": ID},
            "binding_id": ID,
            "resource_generation": 1,
            "access_epoch": 1,
            "assignment_revision": 1,
            "registered_origin_id": ID,
            "target_origin": "https://operator.fixture.invalid",
            "issuer": "fixture",
            "subject": "synthetic",
        },
    }

    attempts = []

    def dispatch(request, *, deadline):
        attempts.append(request)
        return ContinuationTarget(
            binding=request.binding, return_path="/home", remembered=False, expires_at=1000000
        )

    def invoke(uid, gid, expected=0, *, check_rejection=False):
        return execute(
            sys.executable,
            "-B",
            "-c",
            RELAY_CLIENT,
            str(shared / "relay.sock"),
            str(expected),
            "check-rejection" if check_rejection else "request",
            user=uid,
            group=gid,
            extra_groups=[],
            input=json.dumps(call),
        )

    stop = Event()
    with open_relay_socket(shared, central_gid=UID_SHARED) as listener:
        info = (shared / "relay.sock").stat()
        assert (info.st_uid, info.st_gid, info.st_mode & 0o777) == (0, UID_SHARED, 0o660)
        with ThreadPoolExecutor(max_workers=1) as pool:
            job = pool.submit(
                serve_identity, listener, dispatch, allowed_uid=UID_SHARED, stopping=stop
            )
            try:
                assert invoke(UID_SHARED, UID_SHARED) == "/home"
                invoke(UID_PROXY, UID_SHARED, check_rejection=True)
                assert invoke(UID_PROXY, UID_PROXY) == "socket-unavailable"
                assert invoke(UID_SHARED, UID_SHARED, UID_PROXY) == "peer-denied"
                assert len(attempts) == 1
            finally:
                stop.set()
                job.result(timeout=5)
    assert not (shared / "relay.sock").exists()


def publishers(firewall):
    RUN.mkdir(mode=0o755)
    runtime_dir = RUN / "gateway"
    runtime_dir.mkdir(mode=0o700)
    os.chown(runtime_dir, UID_CADDY, UID_CADDY)
    gateway = GatewaySettings(runtime_dir / "admin.sock", UID_CADDY, firewall.settings.gateway_port)
    tunnel = TunnelSettings(tunnel_id=ID, gateway_port=firewall.settings.gateway_port)
    outputs = []
    for component, reader in (("caddy", UID_CADDY), ("tunnel", UID_TUNNEL)):
        directory = RUN / component
        directory.mkdir()
        os.chown(directory, 0, reader)
        directory.chmod(0o750)
        outputs.append(ProjectionPublisher(directory, reader_gid=reader))
    return gateway, tunnel, outputs


def qualify(caddy, firewall):
    gateway, tunnel, outputs = publishers(firewall)
    settings = firewall.settings
    runtime = ServiceRuntime(
        SimpleNamespace(
            layout=SimpleNamespace(stops=str(STATE / "stops")),
            network=settings,
            tunnel=tunnel,
            auth_registration=str(STATE / "registered/auth.json"),
            identity_socket_root="/run/epm-h0312-fixture/source",
            identity_relay=SimpleNamespace(central_uid=UID_SHARED, central_gid=UID_SHARED),
        )
    )
    inventory = SimpleNamespace(
        identity=SimpleNamespace(deployment_id=ID),
        auth_ready=tuple,
        network_projection=lambda: SimpleNamespace(records=()),
        ingress_projection=lambda: IngressProjection(records=()),
        exclusive=nullcontext,
    )
    bootstrap = IngressBootstrap(
        inventory,
        gateway,
        tunnel,
        *outputs,
        contain_all=lambda: None,
        project_ingress=lambda snapshot: runtime.ingress_projection(inventory, snapshot, gateway),
    )
    bootstrap.refresh()
    config_path, tunnel_path = (output.directory / "config.json" for output in outputs)
    result = {
        "gateway_sha256": pin(config_path.read_bytes()),
        "tunnel_sha256": pin(tunnel_path.read_bytes()),
    }
    check_gateway(caddy, config_path)
    check_socket()
    return result, bootstrap, config_path, tunnel_path


def check_gateway(caddy, config):
    process = subprocess.Popen(
        [str(caddy), "run", "--config", str(config)],
        user=UID_CADDY,
        group=UID_CADDY,
        extra_groups=[],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        check_routes()
        for header in ("Forwarded", "X-Forwarded-Host", "X-Original-URL"):
            assert (
                probe_gate(ADMIN.removeprefix("https://"), "/", headers={header: "fixture.invalid"})
                == "403"
            )
        assert probe_gate("unknown.fixture.invalid", "/") == "403"
        assert (
            probe_gate("admin.fixture.invalid", "/", headers={"X-Forwarded-Proto": "http"}) == "403"
        )
    finally:
        stop_gateway(process)


def before(image, caddy, firewall, engine):
    target = firewall.settings.shared_identity.bridge()
    if engine.inspect_network(target.name) is not None:
        raise RuntimeError("The synthetic identity bridge already exists.")
    STATE.mkdir(mode=0o755)
    create_fixture(STATE)
    (STATE / "stops").mkdir(mode=0o700)
    firewall.apply(())
    engine.create_network(target)
    container = launch_peer(STATE, target, image)
    register_peer(STATE, engine, firewall, container, image)
    wait_ready(lambda: peer_is_listening(target.address4))
    pins, *_ = qualify(caddy, firewall)
    (STATE / "before.json").write_text(
        json.dumps({"boot_id": BOOT.read_text().strip(), "container": container, **pins})
    )
    print(json.dumps({"phase": "awaiting_reboot", **pins}))


def after(caddy, firewall, engine):
    retained = json.loads((STATE / "before.json").read_text())
    boot = BOOT.read_text().strip()
    assert boot != retained["boot_id"]
    assert not RUN.exists()
    target = firewall.settings.shared_identity.bridge()
    container = retained["container"]
    assert engine.inspect_network(target.name)
    assert engine.inspect(container)["State"]["Running"] is False
    firewall.apply(())
    try:
        engine.start(container)
        wait_ready(lambda: peer_is_listening(target.address4))
        pins, bootstrap, caddy_path, tunnel_path = qualify(caddy, firewall)
        assert all(retained[name] == value for name, value in pins.items())
        with sqlite3.connect(STATE / "admin.sqlite") as connection:
            connection.execute(
                "UPDATE control_meta SET login_origin='https://stale.fixture.invalid'"
            )
        bootstrap.refresh()
        assert "reverse_proxy" not in caddy_path.read_text()
        assert json.loads(tunnel_path.read_bytes())["ingress"] == [{"service": "http_status:403"}]
        print(
            json.dumps(
                {
                    "actual_reboot": True,
                    "ephemeral_projection_absent_after_boot": True,
                    "retained_container_reused": True,
                    "stale_shared_projection_closed": True,
                    "gateway_and_tunnel_rebuilt": True,
                    "exact_ingress_and_peer_uid_denials": True,
                    **pins,
                }
            )
        )
    finally:
        execute("/usr/bin/docker", "rm", "-f", container)
        engine.remove_empty_network(target.name)
        remove_firewall()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("before", "after"))
    parser.add_argument("--caddy", type=Path, required=True)
    parser.add_argument("--image")
    args = parser.parse_args()
    assert os.geteuid() == 0
    assert "table inet epm_h02" not in execute("/usr/sbin/nft", "list", "tables").splitlines()
    if args.phase == "before":
        before(args.image, args.caddy, fixture_firewall(), DockerEngine())
    else:
        after(args.caddy, fixture_firewall(), DockerEngine())

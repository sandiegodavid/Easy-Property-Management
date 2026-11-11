"""Disposable root-Linux network proof; never run on a live host."""

import argparse
from hashlib import sha256
import json
import importlib
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import time
from uuid import uuid4

from app.modules.host_agent.application.network import NetworkRecord
from qualify_stream import verify as verify_stream
from app.modules.host_agent.infrastructure.docker_engine import DockerEngine
from app.modules.host_agent.infrastructure.network_policy import NetworkSettings, bridge
from app.modules.host_agent.infrastructure.network_firewall import NetworkFirewall
from app.modules.host_agent.infrastructure.operator_networks import OperatorNetworks
from app.modules.host_agent.infrastructure.network_prerequisites import HostNetworkPrerequisites


SERVER = """
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import socket, time
class Server(ThreadingHTTPServer):
    address_family = socket.AF_INET6
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        if self.path == '/stream':
            while True:
                self.wfile.write(b'tick\\n')
                self.wfile.flush()
                time.sleep(0.1)
        else:
            self.wfile.write(b'fixture')
Server(('::',8000), Handler).serve_forever()
"""


def call(*args):
    return subprocess.run(
        [str(v) for v in args], capture_output=True, text=True, check=True, timeout=30
    ).stdout


def setup(root):
    subprocess.run(["/usr/sbin/modprobe", "br_netfilter"], check=True)
    for name in ("bridge-nf-call-iptables", "bridge-nf-call-ip6tables"):
        if Path("/proc/sys/net/bridge", name).read_text().strip() != "1":
            raise RuntimeError("Bridge netfilter is not enabled; no implicit sysctl mutation.")
    settings = NetworkSettings(
        ipv4_pool="10.249.0.0/16",
        ipv6_pool="fd47:6570:6e00::/48",
        first_project=1,
        gateway_uid=42011,
        tunnel_uid=42012,
        proxy_uid=42013,
        gateway_port=18080,
        proxy_port=21080,
    )
    rows = [
        NetworkRecord(
            binding_id=str(uuid4()),
            operator_id=str(uuid4()),
            workspace_id=str(uuid4()),
            resource_generation=1,
            workspace_project=slot,
        )
        for slot in (1, 2)
    ]
    targets = [bridge(row, settings) for row in rows]
    HostNetworkPrerequisites(DockerEngine(), settings).verify(targets)
    firewall = NetworkFirewall(settings)
    firewall.apply(targets)
    (root / "firewall.json").write_text(
        json.dumps(firewall._run(["list", "table", "inet", "epm_h02"]), indent=2)
    )
    return settings, targets, firewall


def create(target, image):
    engine = DockerEngine()
    engine.create_network(target)
    identity = call(
        "/usr/bin/docker",
        "create",
        "--network",
        target.name,
        "--ip",
        target.address4,
        "--ip6",
        target.address6,
        "--user",
        "42001:42001",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--memory=64m",
        "--memory-swap=64m",
        "--cpus=0.25",
        "--pids-limit=16",
        "--dns=127.0.0.1",
        "--log-driver=local",
        "--log-opt=max-size=1m",
        "--log-opt=max-file=2",
        "sha256:" + image,
        "python",
        "-u",
        "-c",
        SERVER,
    ).strip()
    OperatorNetworks.verify_container(target, engine.inspect(identity))
    engine.start(identity)
    OperatorNetworks.verify_container(target, engine.inspect(identity))
    target.verify(engine.inspect_network(target.name))
    return identity


def host_probe(uid, address, *, allowed):
    # Numeric subprocess credentials avoid setpriv's name-service lookup, which
    # consults GCE OS Login metadata even for an unregistered numeric lab UID.
    code = (
        "import socket,sys; s=socket.create_connection((sys.argv[1],8000),timeout=1); "
        "s.sendall(b'GET / HTTP/1.0\\r\\n\\r\\n'); print(s.recv(256).decode())"
    )
    result = subprocess.run(
        [
            "/usr/bin/python3",
            "-c",
            code,
            address,
        ],
        user=uid,
        group=uid,
        extra_groups=[],
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert (result.returncode == 0) == allowed, result.stderr.decode()


def container_probe(identity, address, port):
    code = (
        "import socket,sys; s=socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=1); "
        "s.close()"
    )
    result = subprocess.run(
        ["/usr/bin/docker", "exec", identity, "python", "-c", code, address, str(port)],
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode != 0, (address, port)


def proxy_probe(identity, gateway, proxy_port):
    request = b"CONNECT 169.254.169.254:443 HTTP/1.1\r\nHost: 169.254.169.254:443\r\n\r\n"
    code = (
        "import socket,sys; s=socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=1); "
        f"s.sendall({request!r}); "
        "assert s.recv(4096).startswith(b'HTTP/1.1 403 Forbidden')"
    )
    call("/usr/bin/docker", "exec", identity, "python", "-c", code, gateway, proxy_port)


def verify(settings, targets, identities, firewall):
    # Retry only this read-only readiness probe while the synthetic HTTP server starts.
    for _ in range(30):
        try:
            host_probe(settings.gateway_uid, targets[0].address4, allowed=True)
            break
        except AssertionError:
            time.sleep(0.1)
    else:
        raise AssertionError("Synthetic server did not become reachable by gateway UID")
    for identity, target in zip(identities, targets, strict=True):
        proxy_probe(identity, target.gateway4, settings.proxy_port)
        for address in (target.address4, target.address6):
            host_probe(settings.gateway_uid, address, allowed=True)
            host_probe(0, address, allowed=False)
            host_probe(settings.tunnel_uid, address, allowed=False)
    for identity, own, sibling in (
        (identities[0], targets[0], targets[1]),
        (identities[1], targets[1], targets[0]),
    ):
        for address, port in (
            (sibling.address4, 8000),
            (sibling.address6, 8000),
            (own.gateway4, 22),
            (own.gateway6, 22),
            ("169.254.169.254", 80),
            ("metadata.google.internal", 80),
            ("8.8.8.8", 443),
            ("2606:4700:4700::1111", 443),
        ):
            container_probe(identity, address, port)
    for uid in settings.uids:
        code = "import socket; socket.create_connection(('169.254.169.254',80),timeout=1)"
        probe = subprocess.run(
            [
                "/usr/bin/python3",
                "-c",
                code,
            ],
            user=uid,
            group=uid,
            extra_groups=[],
            capture_output=True,
            check=False,
            timeout=3,
        )
        assert probe.returncode != 0
    observed = firewall._run(["list", "table", "inet", "epm_h02"])
    metadata_packets = sum(
        part["counter"]["packets"]
        for entry in observed["nftables"]
        if entry.get("rule", {}).get("chain") == "output" and "169.254.0.0" in json.dumps(entry)
        for part in entry["rule"]["expr"]
        if "counter" in part
    )
    assert metadata_packets >= len(settings.uids)
    firewall.verify(targets)


def run(image, caddy=None):
    if os.geteuid() != 0 or os.environ.get("EPM_RUN_GATEWAY_QUALIFICATION") != "1":
        raise RuntimeError("Explicit disposable root Linux opt-in required")
    root = Path(tempfile.mkdtemp(prefix="epm-network-qualification-", dir="/var/lib"))
    results = {"status": "failed", "root": str(root), "image": image}
    identities, targets = [], []
    proxy = None
    print(root, flush=True)
    try:
        settings, targets, firewall = setup(root)
        code = (
            "from app.modules.host_agent.infrastructure.egress_proxy import ProxyServer; "
            "from app.modules.host_agent.infrastructure.endpoint_policy import EndpointPolicy; "
            f"ProxyServer(('0.0.0.0',{settings.proxy_port}),EndpointPolicy()).serve_forever()"
        )
        proxy = subprocess.Popen(
            [
                sys.executable,
                "-c",
                code,
            ],
            user=settings.proxy_uid,
            group=settings.proxy_uid,
            extra_groups=[],
            stdout=subprocess.DEVNULL,
            stderr=(root / "proxy.log").open("wb"),
        )
        for target in targets:
            identities.append(create(target, image))
        # Force routes through the bridge to exercise forwarding denial even though
        # internal networks deliberately have no default route.
        for identity, target in zip(identities, targets, strict=True):
            pid = DockerEngine().inspect(identity)["State"]["Pid"]
            call(
                "/usr/bin/nsenter",
                "-t",
                pid,
                "-n",
                "/usr/sbin/ip",
                "route",
                "add",
                "169.254.169.254/32",
                "via",
                target.gateway4,
            )
            call(
                "/usr/bin/nsenter",
                "-t",
                pid,
                "-n",
                "/usr/sbin/ip",
                "route",
                "add",
                "8.8.8.8/32",
                "via",
                target.gateway4,
            )
            call(
                "/usr/bin/nsenter",
                "-t",
                pid,
                "-n",
                "/usr/sbin/ip",
                "-6",
                "route",
                "add",
                "2606:4700:4700::1111/128",
                "via",
                target.gateway6,
            )
        verify(settings, targets, identities, firewall)
        observed = firewall._run(["list", "table", "inet", "epm_h02"])
        (root / "observed.json").write_text(json.dumps(observed, indent=2))
        forward_packets = sum(
            part["counter"]["packets"]
            for entry in observed["nftables"]
            if entry.get("rule", {}).get("chain") == "forward"
            for part in entry["rule"]["expr"]
            if "counter" in part
        )
        assert forward_packets > 0, "No packet exercised the forwarding-deny chain"
        results["forward_drop_packets"] = forward_packets
        results.update(
            cases=[
                "gateway UID reaches dual-stack unpublished application ports",
                "root and tunnel UID cannot reach application ports",
                "sibling, host-control, metadata and direct public egress denied",
                "complete firewall projection reinspected",
                "real controlled proxy reachable and metadata CONNECT rejected",
                "forced metadata/public routes hit forwarding drop counters",
                "static endpoint checked before and after start",
            ],
        )
        if caddy is not None:
            results["stream_containment"] = verify_stream(
                root, settings, targets[0], identities[0], caddy
            )
        results["source_sha256"] = sha256(Path(__file__).read_bytes()).hexdigest()
        results["library_sha256"] = {
            name: sha256(
                Path(
                    importlib.import_module(
                        "app.modules.host_agent.infrastructure." + name
                    ).__file__
                ).read_bytes()
            ).hexdigest()
            for name in (
                "network_policy",
                "network_firewall",
                "operator_networks",
                "network_prerequisites",
                "docker_engine",
                "egress_proxy",
                "endpoint_policy",
            )
        }
        results["status"] = "scoped_network_pass"
    finally:
        if proxy is not None:
            proxy.terminate()
            proxy.wait(timeout=5)
        for identity in identities:
            call("/usr/bin/docker", "rm", "--force", identity)
        engine = DockerEngine()
        for target in targets:
            if engine.inspect_network(target.name) is not None:
                engine.remove_empty_network(target.name)
        (root / "result.json").write_text(json.dumps(results, indent=2) + "\n")
    print(root / "result.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--caddy", type=Path)
    args = parser.parse_args()
    run(args.image, args.caddy)

"""Exercise native shared identity routing with a disposable, synthetic HTTPS peer."""

from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID

from app.modules.host_agent.application.auth_routes import SharedIdentityManifest
from app.modules.host_agent.application.ingress import IngressProjection
from app.modules.host_agent.infrastructure.auth_projection import auth_config
from app.modules.host_agent.infrastructure.auth_registration import RegisteredSources
from app.modules.host_agent.infrastructure.docker_engine import DockerEngine
from app.modules.host_agent.infrastructure.gateway import GatewaySettings
from app.modules.host_agent.infrastructure.network_firewall import NetworkFirewall
from app.modules.host_agent.infrastructure.network_policy import (
    NetworkSettings,
    SharedIdentityNetwork,
)
from app.modules.host_agent.infrastructure.shared_identity_registration import IdentityAsset
from app.platform.hosted_contracts.semantic import semantic_hash

ID = "074c0282-dd50-4444-a025-32dc78b94aa1"
ADMIN = "https://admin.fixture.invalid"
LOGIN = "https://login.fixture.invalid"
TLS_NAME = "private.fixture.invalid"
PROBE_PROJECT = "fixture-project"
UID_CADDY, UID_TUNNEL, UID_PROXY, UID_EGRESS, UID_SHARED = 24801, 24802, 24803, 24804, 24805
ADMIN_INDEX = b"<!doctype html><title>Admin fixture</title>"
ADMIN_JS = b"export const admin = 1;"
CENTRAL_JS = b"export const central = 1;"
PEER = """
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import ssl
import sys

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        host = self.headers["Host"]
        path = self.path
        if self.headers.get_all("X-Forwarded-Proto") != ["https"]:
            return self.reply(421)
        forwarded = ("Forwarded", "X-Forwarded-Host", "X-Forwarded-For")
        if any(self.headers.get_all(name) for name in forwarded):
            return self.reply(421)
        routes = {
            ("admin.fixture.invalid", "/"): (
                b"<!doctype html><title>Admin fixture</title>", "text/html"
            ),
            ("admin.fixture.invalid", "/assets/admin.js"): (
                b"export const admin = 1;", "text/javascript"
            ),
            ("login.fixture.invalid", "/assets/central.js"): (
                b"export const central = 1;", "text/javascript"
            ),
            ("login.fixture.invalid", "/__/auth/handler"): (
                b"<!doctype html><title>Helper</title>", "text/html"
            ),
            ("login.fixture.invalid", "/__/firebase/init.json"): (
                json.dumps({
                    "authDomain": "login.fixture.invalid", "projectId": "fixture-project",
                }).encode(),
                "application/json",
            ),
        }
        if (host, path) not in routes:
            return self.reply(404)
        data, kind = routes[(host, path)]
        self.reply(200, data, kind)

    def reply(self, status, data=b"", kind="text/plain"):
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

server = ThreadingHTTPServer((sys.argv[1], 8000), Handler)
tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
tls.load_cert_chain("/control/cert.pem", "/control/key.pem")
server.socket = tls.wrap_socket(server.socket, server_side=True)
server.serve_forever()
"""


def pin(data):
    return sha256(data).hexdigest()


def certs(root):
    key = Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, TLS_NAME)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(minutes=10))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(TLS_NAME)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, None)
    )
    pem = cert.public_bytes(Encoding.PEM)
    (root / "cert.pem").write_bytes(pem)
    private = root / "key.pem"
    private.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    os.chown(private, UID_SHARED, UID_SHARED)
    private.chmod(0o600)


def execute(*args, **options):
    return subprocess.run(
        args, check=True, text=True, capture_output=True, timeout=15, **options
    ).stdout.strip()


def wait_ready(predicate):
    end = monotonic() + 10
    while monotonic() < end:
        if predicate():
            return
        sleep(0.2)
    raise RuntimeError("Fixture startup timed out.")


def probe_gate(host, path, *, uid=UID_TUNNEL, method="GET", headers=None):
    code = """
import http.client, json, sys
connection = http.client.HTTPConnection("127.0.0.1", 18880, timeout=2)
try:
    connection.request(sys.argv[3], sys.argv[2], headers={
      "Host":sys.argv[1], "X-Forwarded-Proto":"https", **json.loads(sys.argv[4])
    })
    print(connection.getresponse().status)
except OSError:
    print("denied")
finally:
    connection.close()
"""
    return execute(
        sys.executable,
        "-B",
        "-c",
        code,
        host,
        path,
        method,
        json.dumps(headers or {}),
        user=uid,
        extra_groups=[],
    )


def fixture_firewall():
    return NetworkFirewall(
        NetworkSettings(
            ipv4_pool="10.240.0.0/16",
            ipv6_pool="fd47:6570:6d00::/48",
            first_project=1,
            gateway_uid=UID_CADDY,
            tunnel_uid=UID_TUNNEL,
            proxy_uid=UID_PROXY,
            gateway_port=18880,
            shared_identity=SharedIdentityNetwork(
                endpoint_id=ID,
                ipv4="10.241.231.0/30",
                ipv6="fd53:148::/64",
                proxy_uid=UID_EGRESS,
                proxy_port=18881,
            ),
        )
    )


def run(image, caddy, root):
    if os.geteuid() != 0:
        raise RuntimeError("Run only as root on a disposable native Linux qualification guest.")
    firewall = fixture_firewall()
    settings = firewall.settings
    target = settings.shared_identity.bridge()
    engine = DockerEngine()
    # Never replace a preexisting policy or reuse another fixture's network.
    table_names = execute("/usr/sbin/nft", "list", "tables").splitlines()
    if "table inet epm_h02" in table_names or engine.inspect_network(target.name) is not None:
        raise RuntimeError("Use a guest without a running EPM firewall or shared fixture network.")
    with ExitStack() as cleanup:
        create_fixture(root)
        cleanup.callback(remove_firewall)
        firewall.apply(())
        engine.create_network(target)
        cleanup.callback(engine.remove_empty_network, target.name)
        container = launch_peer(root, target, image)
        cleanup.callback(execute, "/usr/bin/docker", "rm", "-f", container)
        registered = register_peer(root, engine, firewall, container, image)
        wait_ready(lambda: peer_is_listening(target.address4))
        endpoint, login_origin = registered.resolve_shared()
        process = launch_gateway(root, settings, endpoint, login_origin, caddy)
        cleanup.callback(stop_gateway, process)
        check_routes()
        proxy = launch_egress(root, target)
        cleanup.callback(stop_gateway, proxy)
        check_egress(container, target)
    print(
        json.dumps(
            {
                "native_firewall_verified": True,
                "registered_tls_and_asset_pins_verified": True,
                "shared_bridge_verified": True,
                "exact_gateway_routes_verified": True,
                "non_tunnel_uid_denied": True,
                "private_central_proxy_boundary_verified": True,
                "public_deployed": False,
            }
        )
    )


def remove_firewall():
    if "table inet epm_h02" in execute("/usr/sbin/nft", "list", "tables").splitlines():
        execute("/usr/sbin/nft", "delete", "table", "inet", "epm_h02")


def create_fixture(root):
    root.chmod(0o755)
    certs(root)
    (root / "peer.py").write_text(PEER)
    database = root / "admin.sqlite"
    connection = sqlite3.connect(database)
    with connection:
        connection.executescript("CREATE TABLE control_meta (id, deployment_id, login_origin);")
        connection.execute("INSERT INTO control_meta VALUES (1, ?, ?)", (ID, LOGIN))
    connection.close()
    os.chown(database, UID_SHARED, UID_SHARED)
    database.chmod(0o600)


def launch_peer(root, target, image):
    return execute(
        "/usr/bin/docker",
        "run",
        "-d",
        "--pull",
        "never",
        "--user",
        f"{UID_SHARED}:{UID_SHARED}",
        "--network",
        target.name,
        "--ip",
        target.address4,
        "--ip6",
        target.address6,
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--mount",
        f"type=bind,source={root},dst=/control,readonly",
        "sha256:" + image,
        "python",
        "-B",
        "/control/peer.py",
        target.address4,
    )


def register_peer(root, engine, firewall, container, image):
    database = root / "admin.sqlite"
    pem = (root / "cert.pem").read_text()
    # The synthetic peer uses the locally pinned image ID. Real launch
    # registration pins both the OCI manifest and the image config digest.
    manifest = SharedIdentityManifest(
        component_id=ID,
        artifact_sha256=image,
        private_endpoint_id=ID,
        central_origin=LOGIN,
        owning_login_origin=LOGIN,
        admin_origin=ADMIN,
    )
    payload = {
        "sources": [],
        "shared": {
            "manifest": manifest.model_dump(mode="json"),
            "manifest_sha256": semantic_hash(manifest),
            "container_id": container,
            "image_config_sha256": image,
            "runtime_uid": UID_SHARED,
            "runtime_gid": UID_SHARED,
            "admin_database": str(database),
            "tls_name": TLS_NAME,
            "trust_pem": pem,
            "firebase_project": PROBE_PROJECT,
            "admin_index_sha256": pin(ADMIN_INDEX),
            "admin_assets": [
                IdentityAsset(path="/assets/admin.js", sha256=pin(ADMIN_JS)).model_dump()
            ],
            "central_assets": [
                IdentityAsset(path="/assets/central.js", sha256=pin(CENTRAL_JS)).model_dump()
            ],
        },
    }
    register = root / "registered"
    register.mkdir(mode=0o700)
    path = register / "auth.json"
    path.write_text(json.dumps(payload))
    path.chmod(0o600)
    inventory = SimpleNamespace(
        identity=SimpleNamespace(deployment_id=ID),
        network_projection=lambda: SimpleNamespace(records=()),
    )
    return RegisteredSources.load(
        inventory,
        engine,
        firewall,
        firewall.settings,
        path,
        Path("/run/epm-synthetic"),
        central_principal=(UID_SHARED, UID_SHARED),
    )


def peer_is_listening(address):
    code = "import socket,sys; socket.create_connection((sys.argv[1], 8000), 1).close()"
    probe = subprocess.run(
        [sys.executable, "-B", "-c", code, address],
        user=UID_CADDY,
        extra_groups=[],
        capture_output=True,
        timeout=2,
        check=False,
    )
    return probe.returncode == 0


def launch_gateway(root, settings, endpoint, login_origin, caddy):
    run_dir = root / "gateway"
    run_dir.mkdir(mode=0o700)
    os.chown(run_dir, UID_CADDY, UID_CADDY)
    gateway = GatewaySettings(run_dir / "admin.sock", UID_CADDY, settings.gateway_port)
    config = auth_config(
        IngressProjection(records=()), gateway, shared=endpoint, login_origin=login_origin
    )
    config_file = run_dir / "caddy.json"
    config_file.write_text(json.dumps(config))
    return subprocess.Popen(
        [str(caddy), "run", "--config", str(config_file)],
        user=UID_CADDY,
        extra_groups=[],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def stop_gateway(process):
    if process.poll() is None:
        process.terminate()
    _, error = process.communicate(timeout=5)
    if process.returncode not in (0, -15):
        print(error.decode(), file=sys.stderr)


def check_routes():
    wait_ready(lambda: probe_gate("admin.fixture.invalid", "/") == "200")
    assert probe_gate("login.fixture.invalid", "/assets/central.js") == "200"
    assert probe_gate("login.fixture.invalid", "/__/auth/handler") == "200"
    assert probe_gate("admin.fixture.invalid", "/assets/central.js") == "403"
    assert probe_gate("login.fixture.invalid", "/api/admin/session") == "403"
    assert probe_gate("admin.fixture.invalid", "/", uid=UID_EGRESS) == "denied"
    assert probe_gate("login.fixture.invalid", "/__/auth/handler", method="POST") == "403"


def launch_egress(root, target):
    private = root / "egress"
    private.mkdir(mode=0o700)
    path = private / "proxy.json"
    path.write_text(
        json.dumps(
            {
                "address": target.gateway4,
                "central_address": target.address4,
                "port": target.proxy_port,
                "firebase_project": PROBE_PROJECT,
            }
        )
    )
    path.chmod(0o600)
    os.chown(path, UID_EGRESS, UID_EGRESS)
    os.chown(private, UID_EGRESS, UID_EGRESS)
    return subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-m",
            "app.modules.host_agent.infrastructure.identity_egress",
            "--configuration",
            str(path),
        ],
        user=UID_EGRESS,
        extra_groups=[],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def check_egress(container, target):
    probe = r"""
import socket, sys
try:
    with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=1) as client:
        name = b"unregistered.fixture.invalid:443"
        client.sendall(b"CONNECT " + name + b" HTTP/1.1\r\nHost: " + name + b"\r\n\r\n")
        print(client.recv(64).split()[1].decode())
except OSError:
    print("denied")
"""
    wait_ready(
        lambda: (
            execute(
                "/usr/bin/docker",
                "exec",
                container,
                "python",
                "-B",
                "-c",
                probe,
                target.gateway4,
                str(target.proxy_port),
            )
            == "403"
        )
    )
    assert (
        execute(
            sys.executable,
            "-B",
            "-c",
            probe,
            target.gateway4,
            str(target.proxy_port),
            user=UID_TUNNEL,
            extra_groups=[],
        )
        == "denied"
    )


if __name__ == "__main__":
    with TemporaryDirectory(prefix="epm-shared-identity-") as directory:
        run(sys.argv[1], Path(sys.argv[2]), Path(directory))

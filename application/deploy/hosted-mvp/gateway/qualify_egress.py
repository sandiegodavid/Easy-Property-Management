"""No-network-escape TLS/redirect/DNS qualification inside private mount+network namespaces."""

import argparse
from hashlib import sha256
from http import HTTPStatus
from http.client import HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
from threading import Thread
import time
from urllib.parse import urlsplit

from app.modules.host_agent.infrastructure.endpoint_policy import EndpointPolicy
from app.modules.host_agent.infrastructure.egress_proxy import ProxyServer
from app.modules.host_agent.infrastructure.bounded_dns import resolve
from app.modules.host_agent.application.dispatch import HostAgentUnavailable


def call(*arguments):
    return subprocess.run([str(v) for v in arguments], check=True, capture_output=True, timeout=10)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(302 if self.path == "/redirect" else 200)
        if self.path == "/redirect":
            self.send_header("Location", "https://blocked.epm.test/secret")
        self.end_headers()
        self.wfile.write(b"synthetic evidence")


def fetch(host, context, path="/"):
    connection = HTTPSConnection("127.0.0.1", 21080, timeout=3, context=context)
    connection.set_tunnel(host, 443)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.getheader("Location"), response.read()
    finally:
        connection.close()


DNS_DEADLINE = 3.5
MAX_CONNECT_RESPONSE = 512


def setup(root):
    call("/usr/bin/mount", "--make-rprivate", "/")
    hosts = root / "hosts"
    hosts.write_text(
        "127.0.0.1 localhost\n8.8.4.4 approved.epm.test blocked.epm.test rebound.epm.test\n"
    )
    call("/usr/bin/mount", "--bind", hosts, "/etc/hosts")
    resolver = root / "resolv.conf"
    resolver.write_text("nameserver 8.8.4.4\noptions attempts:5 timeout:5\n")
    call("/usr/bin/mount", "--bind", resolver, "/etc/resolv.conf")
    call("/usr/sbin/ip", "link", "set", "lo", "up")
    call("/usr/sbin/ip", "addr", "add", "8.8.4.4/32", "dev", "lo")
    call("/usr/sbin/ip", "addr", "add", "169.254.169.254/32", "dev", "lo")
    # The endpoint appears globally routed to the production IP policy but is wholly
    # inside this namespace, which has no external interface or default route.
    assert len(json.loads(call("/usr/sbin/ip", "-j", "link").stdout)) == 1
    cert, key = root / "cert.pem", root / "key.pem"
    call(
        "/usr/bin/openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "1",
        "-keyout",
        key,
        "-out",
        cert,
        "-subj",
        "/CN=approved.epm.test",
        "-addext",
        "subjectAltName=DNS:approved.epm.test,DNS:rebound.epm.test",
    )
    upstream = ThreadingHTTPServer(("8.8.4.4", 443), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    upstream.socket = tls.wrap_socket(upstream.socket, server_side=True)
    proxy = ProxyServer(
        ("127.0.0.1", 21080), EndpointPolicy(("approved.epm.test", "rebound.epm.test"))
    )
    return hosts, cert, upstream, proxy


def verify_sni():
    with socket.create_connection(("127.0.0.1", 21080), timeout=3) as raw:
        raw.sendall(
            b"CONNECT approved.epm.test:443 HTTP/1.1\r\nHost: approved.epm.test:443\r\n\r\n"
        )
        headers = bytearray()
        while not headers.endswith(b"\r\n\r\n"):
            part = raw.recv(1)
            if not part or len(headers) >= MAX_CONNECT_RESPONSE:
                raise AssertionError("CONNECT did not yield a bounded response")
            headers.extend(part)
        negative = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        negative.check_hostname = False
        negative.verify_mode = ssl.CERT_NONE
        try:
            negative.wrap_socket(raw, server_hostname="blocked.epm.test")
        except OSError:
            return True
        else:
            raise AssertionError("Different TLS SNI escaped CONNECT authority")


def inside(root):
    hosts, cert, upstream, proxy = setup(root)
    threads = [Thread(target=upstream.serve_forever), Thread(target=proxy.serve_forever)]
    for thread in threads:
        thread.start()
    cases = {}
    try:
        context = ssl.create_default_context(cafile=str(cert))
        status, _, body = fetch("approved.epm.test", context)
        assert status == HTTPStatus.OK and body == b"synthetic evidence"
        cases["approved_numeric_destination_and_verified_tls"] = True
        cases["tls_sni_must_match_connect_endpoint"] = verify_sni()
        status, redirect, _ = fetch("approved.epm.test", context, "/redirect")
        assert status == HTTPStatus.FOUND
        try:
            fetch(urlsplit(redirect).hostname, context)
        except OSError:
            cases["redirect_to_unregistered_endpoint_denied"] = True
        else:
            raise AssertionError("Unregistered redirect escaped endpoint policy")
        assert fetch("rebound.epm.test", context)[0] == HTTPStatus.OK
        hosts.write_text(
            "127.0.0.1 localhost\n8.8.4.4 approved.epm.test\n169.254.169.254 rebound.epm.test\n"
        )
        try:
            fetch("rebound.epm.test", context)
        except OSError:
            cases["fresh_dns_rebinding_to_metadata_denied"] = True
        else:
            raise AssertionError("Rebound private address escaped policy")
        # A reachable DNS listener deliberately never replies. The resolver must be
        # killed/reaped by the production two-second subprocess deadline.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as dns:
            dns.bind(("8.8.4.4", 53))
            began = time.monotonic()
            try:
                resolve("stall.epm.test", 443)
            except HostAgentUnavailable:
                elapsed = time.monotonic() - began
                assert elapsed < DNS_DEADLINE
                cases["dns_deadline_seconds"] = elapsed
            else:
                raise AssertionError("Stalled DNS unexpectedly resolved")
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        for thread in threads:
            thread.join(timeout=3)
            assert not thread.is_alive()
    return cases


def run():
    if os.geteuid() != 0 or os.environ.get("EPM_RUN_GATEWAY_QUALIFICATION") != "1":
        raise RuntimeError("Explicit disposable root Linux opt-in required")
    root = Path(tempfile.mkdtemp(prefix="epm-egress-qualification-", dir="/var/lib"))
    result = {"status": "failed", "root": str(root)}
    command = [
        "/usr/bin/unshare",
        "--mount",
        "--net",
        sys.executable,
        "-B",
        __file__,
        "--inside",
        str(root),
    ]
    completed = subprocess.run(command, capture_output=True, timeout=30, check=False)
    (root / "diagnostic.log").write_bytes(completed.stderr)
    if completed.returncode == 0:
        result.update(
            status="scoped_egress_pass",
            cases=json.loads(completed.stdout),
            source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        )
    (root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(root / "result.json", flush=True)
    if completed.returncode:
        raise RuntimeError("Native egress proof failed; inspect private diagnostic")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inside", type=Path)
    args = parser.parse_args()
    if args.inside:
        print(json.dumps(inside(args.inside)))
    else:
        run()

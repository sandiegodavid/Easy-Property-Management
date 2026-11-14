"""Bounded, credential-free probes of the exact shared identity hosts and files."""

from hashlib import sha256
from http.client import HTTPConnection
from ipaddress import IPv4Address
import json
import socket
import ssl
import sys

from app.modules.host_agent.infrastructure.shared_identity_registration import SharedRegistration

MAX_BODY = 2 * 1024 * 1024


class CandidateConnection(HTTPConnection):
    def __init__(self, address, registration):
        super().__init__(address, port=8000, timeout=3)
        self.context = ssl.create_default_context(cadata=registration.trust_pem)
        self.tls_name = registration.tls_name

    def connect(self):
        with socket.create_connection((self.host, self.port), self.timeout) as transport:
            self.sock = self.context.wrap_socket(transport, server_hostname=self.tls_name)


def read(address, registration, origin, path, media_types, *, expected=200):
    connection = CandidateConnection(address, registration)
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Host": origin.removeprefix("https://"),
                "X-Forwarded-Proto": "https",
            },
        )
        response = connection.getresponse()
        if response.status != expected:
            raise ValueError("Unexpected endpoint status.")
        if expected != 200:
            return b""
        if (
            response.headers.get_content_type() not in media_types
            or "no-store" not in response.headers.get("Cache-Control", "")
        ):
            raise ValueError("Unexpected endpoint response.")
        body = response.read(MAX_BODY + 1)
        if not body or len(body) > MAX_BODY:
            raise ValueError("Invalid endpoint body size.")
        return body
    finally:
        connection.close()


def verify(address, registration):
    manifest = registration.manifest
    index = read(address, registration, manifest.admin_origin, "/", {"text/html"})
    if sha256(index).hexdigest() != registration.admin_index_sha256:
        raise ValueError("Admin index pin mismatch.")
    for origin, assets in (
        (manifest.admin_origin, registration.admin_assets),
        (manifest.central_origin, registration.central_assets),
    ):
        for asset in assets:
            media = (
                {"text/css"}
                if asset.path.endswith(".css")
                else {"text/javascript", "application/javascript"}
            )
            body = read(address, registration, origin, asset.path, media)
            if sha256(body).hexdigest() != asset.sha256:
                raise ValueError("Identity asset pin mismatch.")
    read(address, registration, manifest.central_origin, "/api/admin/session", set(), expected=404)
    config = json.loads(
        read(
            address,
            registration,
            manifest.central_origin,
            "/__/firebase/init.json",
            {"application/json"},
        )
    )
    if (
        config.get("authDomain") != manifest.central_origin.removeprefix("https://")
        or config.get("projectId") != registration.firebase_project
    ):
        raise ValueError("Firebase helper origin mismatch.")
    read(address, registration, manifest.central_origin, "/__/auth/handler", {"text/html"})


def main():
    try:
        raw = sys.stdin.buffer.read(131073)
        if len(raw) > 131072:
            raise ValueError()
        registration, address = raw.rsplit(b"\n", 1)
        verify(
            str(IPv4Address(address.decode("ascii"))),
            SharedRegistration.model_validate_json(registration),
        )
    except Exception:
        raise SystemExit(3) from None
    print("verified")


if __name__ == "__main__":
    main()

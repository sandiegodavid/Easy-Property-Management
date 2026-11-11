"""Fixed fresh hosted launch; never import local or legacy hosted bootstrap."""

import argparse
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import platform

from app.hosted_candidates.binding import load_binding
from app.hosted_candidates.startup import validate_startup
from app.hosted_candidates.status_page import CSS, page
from app.platform.browser_transport import MAX_PORT
from app.platform.config import application_root
from app.platform.hosted_artifacts import (
    ArtifactInvalid,
    ArtifactUnavailable,
    load_manifest,
    verify_candidate,
)


def inspect(component):
    root = application_root()
    package = Path(__file__).resolve().parents[1]
    manifest = load_manifest(root / "hosted-candidate.json")
    architecture = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
    if architecture != manifest.architecture:
        raise ArtifactInvalid()
    return verify_candidate(manifest, package, root, component=component)


class HostedStatusHandler(BaseHTTPRequestHandler):
    server_version = "EPM"
    sys_version = ""
    timeout = 5

    def do_GET(self):
        if self.path == "/health/live":
            self.respond(200, "application/json", b'{"status":"alive"}')
        elif self.server.binding is not None and self.headers.get_all("Host") != [
            self.server.binding.origin[8:]
        ]:
            self.respond(421, "application/json", b'{"status":"unavailable"}')
        elif self.path == "/status.css":
            self.respond(200, "text/css; charset=utf-8", CSS.encode())
        elif self.path in {"/", "/status"} or (
            "text/html" in self.headers.get("Accept", "")
            and not self.path.startswith(("/api/", "/health/"))
        ):
            self.respond(503, "text/html; charset=utf-8", page())
        else:
            self.unavailable()

    def unavailable(self):
        # A transport response is not an observation of access, data or writes.
        body = {
            "status": "unavailable",
            "ready": False,
            "checkedAt": datetime.now(UTC).isoformat(),
            "retryAfterSeconds": 30,
        }
        self.respond(503, "application/json", json.dumps(body).encode())

    def do_POST(self):
        self.close_connection = True
        self.unavailable()

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST
    do_OPTIONS = do_POST
    do_HEAD = do_POST

    def respond(self, status, content_type, body):
        # External self-only CSS; no script, credentials or automatic retries.
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'none'",
        )
        if status == HTTPStatus.SERVICE_UNAVAILABLE:
            self.send_header("Retry-After", "30")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def launch(component):
    parser = argparse.ArgumentParser(description="Inspect an unqualified component candidate.")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--health-only", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--binding", type=Path, help="Read-only root-owned fresh launch binding.")
    args = parser.parse_args()
    try:
        report = inspect(component)
        if args.verify:
            print(json.dumps(report, sort_keys=True))
            return
        if not 1 <= args.port <= MAX_PORT or component == "host_agent":
            raise ArtifactUnavailable()
        if args.health_only and args.binding is not None:
            raise ArtifactInvalid()
        binding = None
        if not args.health_only:
            if args.binding is None:
                raise ArtifactInvalid()
            binding = load_binding(args.binding, component)
            try:
                validate_startup(binding, application_root())
            except Exception:
                # Do not expose validation errors or fall back to local/old hosted.
                # Even future structural success cannot enable routes here.
                pass
        with HTTPServer(("0.0.0.0", args.port), HostedStatusHandler) as server:
            server.binding = binding
            server.serve_forever()
    except Exception:
        parser.exit(3, "Candidate runtime unavailable; no hosted application was started.\n")

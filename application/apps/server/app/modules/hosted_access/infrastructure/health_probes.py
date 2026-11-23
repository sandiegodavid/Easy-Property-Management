"""Loopback-only internal /health/live and /health/ready probes (H06.6 / D8).

Strictly bound to 127.0.0.1 (never exposed on public Caddy routes). O(1) checks with
zero secrets, zero full-DB scans, and bounded timeouts.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading


class _LoopbackHealthServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _make_handler(readiness_check: Callable[[], bool]) -> type[BaseHTTPRequestHandler]:
    class _HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health/live":
                self._send_json(200, {"status": "alive"})
                return
            if self.path == "/health/ready":
                try:
                    ready = bool(readiness_check())
                except Exception:
                    ready = False
                if ready:
                    self._send_json(200, {"status": "ready"})
                else:
                    self._send_json(503, {"status": "not_ready"})
                return
            self._send_json(404, {"status": "not_found"})

        def _send_json(self, status_code: int, payload: dict[str, str]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    return _HealthHandler


@contextmanager
def internal_health_server(
    readiness_check: Callable[[], bool],
    *,
    port: int = 8081,
    host: str = "127.0.0.1",
):
    """Run a loopback-only internal /health/live + /health/ready HTTP server."""
    if host != "127.0.0.1":
        raise ValueError("Internal health server must bind strictly to 127.0.0.1.")
    server = _LoopbackHealthServer((host, port), _make_handler(readiness_check))
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="internal-health")
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3.0)

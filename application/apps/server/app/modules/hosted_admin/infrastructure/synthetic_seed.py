"""Pinned offline synthetic portfolio seeding for Free pilot provisioning (D10)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import time
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app.bootstrap.api import create_app
from app.platform.browser_transport import LOCAL_CLIENT_HEADER, LOCAL_CLIENT_VALUE

SEED_BUNDLE_PREFIX = "synthetic-demo-v1:"
TIMEZONE = "America/Los_Angeles"


class SeedBundleError(RuntimeError):
    """Raised when a synthetic seed bundle pin or execution fails."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _AsgiResponse:
    status_code: int
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.body.decode("utf-8"))


class _OfflineAsgiClient:
    """Zero-httpx in-process ASGI client for offline synthetic workspace seeding."""

    def __init__(self, app) -> None:
        self._app = app
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lifespan_cm = None

    def __enter__(self) -> _OfflineAsgiClient:
        self._loop = asyncio.new_event_loop()
        self._lifespan_cm = self._app.router.lifespan_context(self._app)
        try:
            self._loop.run_until_complete(self._lifespan_cm.__aenter__())
        except BaseException:
            self._loop.close()
            self._loop = None
            self._lifespan_cm = None
            raise
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._loop is not None:
            try:
                if self._lifespan_cm is not None:
                    self._loop.run_until_complete(self._lifespan_cm.__aexit__(exc_type, exc, tb))
            finally:
                self._loop.close()
                self._loop = None
                self._lifespan_cm = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: object | None = None,
    ) -> _AsgiResponse:
        if self._loop is None:
            raise RuntimeError("Offline ASGI client must be used as a context manager.")
        query_string = urlencode(params or {}, doseq=True).encode("ascii")
        payload = b"" if json_body is None else json.dumps(json_body).encode("utf-8")
        headers = [
            (b"host", b"127.0.0.1:8000"),
            (LOCAL_CLIENT_HEADER.lower().encode("ascii"), LOCAL_CLIENT_VALUE.encode("ascii")),
        ]
        if json_body is not None:
            headers.append((b"content-type", b"application/json"))
            headers.append((b"content-length", str(len(payload)).encode("ascii")))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method.upper(),
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": query_string,
            "headers": headers,
            "server": ("127.0.0.1", 8000),
            "client": ("127.0.0.1", 0),
        }
        status_code = 0
        chunks: list[bytes] = []
        sent_body = False

        async def receive():
            nonlocal sent_body
            if sent_body:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent_body = True
            return {"type": "http.request", "body": payload, "more_body": False}

        async def send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        self._loop.run_until_complete(self._app(scope, receive, send))
        return _AsgiResponse(status_code=status_code, body=b"".join(chunks))

    def get(self, path: str, *, params: dict | None = None) -> _AsgiResponse:
        return self._request("GET", path, params=params)

    def post(self, path: str, *, json: object | None = None) -> _AsgiResponse:
        return self._request("POST", path, json_body=json)

    def patch(self, path: str, *, json: object | None = None) -> _AsgiResponse:
        return self._request("PATCH", path, json_body=json)

    def put(self, path: str, *, json: object | None = None) -> _AsgiResponse:
        return self._request("PUT", path, json_body=json)

    def delete(self, path: str, *, json: object | None = None) -> _AsgiResponse:
        return self._request("DELETE", path, json_body=json)


def canonical_seed_bundle_ref(dataset_path: Path) -> str:
    """Compute the canonical D10 seed bundle reference from dataset.json bytes."""
    if not dataset_path.is_file():
        raise SeedBundleError("seed_bundle_missing", "Synthetic dataset file is missing.")
    digest = sha256(dataset_path.read_bytes()).hexdigest()
    return f"{SEED_BUNDLE_PREFIX}{digest}"


def verify_seed_bundle_ref(seed_bundle: str | None, dataset_path: Path) -> str:
    """Fail closed unless seed_bundle matches the pinned dataset.json SHA-256."""
    expected = canonical_seed_bundle_ref(dataset_path)
    if seed_bundle != expected:
        raise SeedBundleError(
            "seed_bundle_mismatch",
            "Requested synthetic seed bundle does not match the pinned dataset.",
        )
    return expected


def _load_demo_seeder(demo_seed_path: Path):
    spec = importlib.util.spec_from_file_location("epm_demo_seed", demo_seed_path)
    if spec is None or spec.loader is None:
        raise SeedBundleError("seed_runner_unavailable", "Demo seeder module could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed_synthetic_workspace(
    workspace_root: Path,
    *,
    scratch_dir: Path,
    seed_bundle: str | None,
    dataset_path: Path,
    seeder_runner: Callable[[Path, Path, Path], None] | None = None,
) -> str:
    """Verify pinned seed_bundle and populate workspace offline using scratch for journals."""
    verified_ref = verify_seed_bundle_ref(seed_bundle, dataset_path)
    scratch_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_path = scratch_dir / "seed-config.json"
    journal_path = scratch_dir / "seed-journal.json"
    config_path.write_text(
        json.dumps({"localWorkspacePath": str(workspace_root)}, indent=2) + "\n",
        encoding="utf-8",
    )
    if seeder_runner is not None:
        seeder_runner(workspace_root, config_path, journal_path)
        return verified_ref

    demo_module = _load_demo_seeder(dataset_path.parent / "seed.py")
    plan = json.loads(dataset_path.read_text(encoding="utf-8"))
    previous_tz = os.environ.get("TZ")
    os.environ["TZ"] = TIMEZONE
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        as_of = datetime.now(ZoneInfo(TIMEZONE)).date()
        with _OfflineAsgiClient(create_app(config_path)) as client:
            seeder = demo_module.Seeder(client, journal_path, as_of)
            seeder.owners(plan)
            seeder.providers(plan)
            for item in plan["properties"]:
                seeder.property(item)
            seeder.expenses()
            for item in plan["issues"]:
                seeder.issue(item)
            seeder.communications(plan)
            seeder.inspection()
            seeder.rent_follow_up()
    finally:
        if previous_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous_tz
        if hasattr(time, "tzset"):
            time.tzset()
    return verified_ref

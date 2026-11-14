"""Authorization precedes routing, business work, files and original-result lookup."""

import asyncio
import errno
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest
from starlette.responses import JSONResponse

from app.modules.hosted_access.api.middleware import HostedTransportMiddleware
from app.modules.hosted_access.api.router import SESSION_COOKIE, build_session_router
from app.modules.hosted_access.api.request_body import bounded_body
from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.application.service import HostedAccessService
from app.modules.hosted_access.domain.models import HostedAccessError, VerifiedIdentity


@pytest.fixture
def transport(deployment_values):
    deployment = HostedDeployment.model_validate(deployment_values)
    now = datetime.now(UTC) + timedelta(seconds=1)

    class UnavailableStore:
        def begin_session(self, _values):
            raise HostedAccessError(
                "hosted_access_unavailable", "Hosted sign-in is unavailable.", 503
            )

        def session(self, _token_hash):
            raise HostedAccessError(
                "hosted_access_unavailable", "Hosted sign-in is unavailable.", 503
            )

    store = UnavailableStore()
    service = HostedAccessService(deployment, store, now=lambda: now)
    proof = VerifiedIdentity(
        deployment.identity_issuer,
        "subject",
        deployment.allowed_email,
        now - timedelta(seconds=1),
        now + timedelta(hours=1),
        sha256(b"proof").hexdigest(),
    )

    class Verifier:
        def verify(self, assertion):
            if assertion != "verified-proof":
                raise HostedAccessError("hosted_identity_rejected", "Identity rejected.")
            return proof

    calls = []
    ready = [True]
    app = FastAPI()

    @app.exception_handler(HostedAccessError)
    async def access_error(_request, error):
        return JSONResponse({"detail": {"code": error.code}}, status_code=error.status)

    @app.get("/api/tasks")
    @app.post("/api/tasks")
    def business(request: Request):
        calls.append(request.state.hosted_actor)
        failure = getattr(app.state, "business_failure", None)
        if failure is not None:
            raise failure
        return {"ok": True}

    @app.get("/api/files/{file_id}/content")
    def download(file_id: str):
        calls.append(file_id)
        return {"content": "private"}

    @app.get("/api/workspace")
    def forbidden():
        calls.append("forbidden")
        return {}

    app.include_router(build_session_router(service))
    app.add_middleware(
        HostedTransportMiddleware,
        service=service,
        verifier=Verifier(),
        routes=app.openapi()["paths"],
        workspace_ready=lambda: ready[0],
    )
    with TestClient(app, base_url=deployment.public_origin, client=("127.0.0.1", 123)) as client:
        client.headers.update({"cf-access-jwt-assertion": "verified-proof"})
        yield client, store, calls, ready


@pytest.mark.parametrize(
    "path",
    [
        "/api/workspace",
        "/api/ai/settings",
        "/api/files/verify",
        "/api/files/integrity-attention",
        "/api/new-domain",
        "/openapi.json",
        "/docs",
        "/assets/unhashed.js",
    ],
)
def test_unknown_and_administration_routes_are_denied_without_sign_in(transport, path):
    client, _store, calls, _ready = transport
    assert client.get(path).status_code == 403
    assert calls == []


@pytest.mark.parametrize(
    "headers",
    [
        {"host": "attacker.example"},
        {"origin": "https://attacker.example"},
        {"sec-fetch-site": "cross-site"},
        {"cf-access-jwt-assertion": "spoofed"},
    ],
)
def test_untrusted_transport_proof_cannot_reach_business_work(transport, headers):
    client, _store, calls, _ready = transport
    assert client.get("/api/tasks", headers=headers).status_code in {401, 403}
    assert calls == []


def test_duplicate_security_headers_and_session_cookies_are_rejected(transport):
    client, _store, calls, _ready = transport
    assert client.get("/api/tasks", headers=[("host", "a"), ("host", "b")]).status_code == 403
    assert (
        client.get(
            "/api/tasks",
            headers={
                "cookie": f"{SESSION_COOKIE}=a; {SESSION_COOKIE}=b",
            },
        ).status_code
        == 403
    )
    assert calls == []


def test_forwarded_headers_do_not_make_an_external_peer_trusted(transport):
    client, _store, calls, _ready = transport
    with TestClient(
        client.app, base_url=str(client.base_url), client=("203.0.113.10", 123)
    ) as external:
        response = external.get(
            "/api/tasks",
            headers={
                "x-forwarded-for": "127.0.0.1",
                "x-forwarded-host": "demo-a.example.com",
                "cf-access-jwt-assertion": "verified-proof",
                "X-EPM-Local-Client": "1",
            },
        )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "hosted_host_rejected"
    assert calls == []


def test_unsafe_requests_require_origin_before_session_lookup(transport):
    client, _store, calls, _ready = transport
    client.headers["cookie"] = f"{SESSION_COOKIE}={'a' * 43}"
    client.headers["x-epm-csrf"] = "untrusted-csrf"
    response = client.post("/api/tasks")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "hosted_origin_rejected"
    assert calls == []


def test_cross_site_top_level_navigation_can_reach_public_sign_in(transport):
    client, _store, calls, _ready = transport
    response = client.get(
        "/sign-in",
        headers={
            "accept": "text/html",
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document",
        },
    )
    # This minimal app has no shell route; reaching its 404 proves dispatch was allowed.
    assert response.status_code == 404
    assert calls == []


def test_access_logout_return_redirects_without_identity_or_session_admission(transport):
    client, _store, calls, _ready = transport
    del client.headers["cf-access-jwt-assertion"]
    response = client.get(
        "/?__cf_access_message=logged_out",
        headers={
            "accept": "text/html",
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/sign-in"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["vary"] == "Sec-Fetch-Dest, Sec-Fetch-Mode, Sec-Fetch-Site"
    assert "set-cookie" not in response.headers
    assert calls == []
    # Following the fixed redirect can reach only the public sign-in route.
    assert (
        client.get(
            response.headers["location"],
            headers={
                "accept": "text/html",
                "sec-fetch-site": "cross-site",
                "sec-fetch-mode": "navigate",
                "sec-fetch-dest": "document",
            },
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    ("path", "method", "headers"),
    [
        ("/", "GET", {}),
        ("/?__cf_access_message=other", "GET", {}),
        ("/?__cf_access_message=logged_out&next=https://attacker.example", "GET", {}),
        ("/api/tasks?__cf_access_message=logged_out", "GET", {}),
        ("/api/hosted/session?__cf_access_message=logged_out", "POST", {}),
        ("/?__cf_access_message=logged_out", "POST", {}),
        ("/?__cf_access_message=logged_out", "GET", {"origin": "https://attacker.example"}),
        ("/?__cf_access_message=logged_out", "GET", {"origin": "null"}),
        ("/?__cf_access_message=logged_out", "GET", {"host": "attacker.example"}),
        ("/?__cf_access_message=logged_out", "GET", {"sec-fetch-mode": "cors"}),
        ("/?__cf_access_message=logged_out", "GET", {"sec-fetch-dest": "iframe"}),
        ("/?__cf_access_message=logged_out", "GET", {"accept": "application/json"}),
    ],
)
def test_access_logout_return_exception_is_narrow(transport, path, method, headers):
    client, _store, calls, _ready = transport
    response = client.request(
        method,
        path,
        headers={
            "accept": "text/html",
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document",
            **headers,
        },
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert "location" not in response.headers
    assert calls == []


@pytest.mark.parametrize(
    ("path", "method", "headers"),
    [
        ("/api/tasks", "GET", {}),
        ("/api/files/id/content", "GET", {}),
        ("/api/hosted/session", "POST", {}),
        ("/sign-in", "POST", {}),
        ("/sign-in", "GET", {"origin": "https://attacker.example"}),
        ("/sign-in", "GET", {"sec-fetch-mode": "cors"}),
        ("/sign-in", "GET", {"sec-fetch-dest": "iframe"}),
        ("/sign-in", "GET", {"accept": "application/json"}),
    ],
)
def test_cross_site_sign_in_navigation_exception_is_narrow(transport, path, method, headers):
    client, _store, calls, _ready = transport
    response = client.request(
        method,
        path,
        headers={
            "accept": "text/html",
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document",
            **headers,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "hosted_origin_rejected"
    assert calls == []


def test_rate_limit_is_bounded_before_business_work(transport, monkeypatch):
    client, _store, calls, _ready = transport
    monkeypatch.setattr("app.modules.hosted_access.api.middleware.MAX_REQUESTS_PER_MINUTE", 1)
    assert client.get("/api/tasks").status_code == 401
    assert client.get("/api/tasks").status_code == 429
    assert calls == []


def test_late_storage_error_does_not_start_a_second_response():
    middleware = HostedTransportMiddleware.__new__(HostedTransportMiddleware)
    messages = []

    async def dispatch(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise HostedAccessError("hosted_storage_quota_exceeded", "Interrupted stream", 507)

    async def send(message):
        messages.append(message)

    middleware._dispatch = dispatch
    with pytest.raises(HostedAccessError):
        asyncio.run(middleware({"type": "http"}, None, send))
    assert len(messages) == 1


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
def test_retired_session_routes_cannot_issue_or_accept_authority(transport, method):
    client, _store, calls, _ready = transport
    client.headers.update(
        {
            "origin": str(client.base_url).rstrip("/"),
            "cookie": f"{SESSION_COOKIE}={'a' * 43}",
            "x-epm-csrf": "untrusted-csrf",
        }
    )
    response = client.request(method, "/api/hosted/session")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "hosted_access_unavailable"
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    assert calls == []


def test_no_local_marker_bypass_and_declared_body_limit(transport):
    client, _store, calls, _ready = transport
    assert client.get("/api/tasks", headers={"X-EPM-Local-Client": "1"}).status_code == 401
    response = client.post(
        "/api/tasks",
        headers={
            "origin": str(client.base_url).rstrip("/"),
            "content-length": str(51 * 1024 * 1024),
        },
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "request_payload_too_large"
    assert calls == []


def test_chunked_body_is_bounded_before_any_handler_work():
    chunks = iter(
        [
            {"type": "http.request", "body": b"a" * 100, "more_body": True},
            {"type": "http.request", "body": b"b" * 100, "more_body": False},
        ]
    )
    calls = []

    async def receive():
        return next(chunks)

    async def dispatch():
        async with bounded_body(receive, max_bytes=128):
            calls.append("handler")

    with pytest.raises(HostedAccessError) as caught:
        asyncio.run(dispatch())
    assert caught.value.status == 413
    assert caught.value.code == "request_payload_too_large"
    assert calls == []


def test_wrapped_handler_full_error_is_typed_even_after_owning_cleanup():
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def dispatch():
        async with bounded_body(receive):
            error = RuntimeError("opaque provider failure")
            error.__cause__ = OSError(errno.ENOSPC, "private storage location")
            raise error

    with pytest.raises(HostedAccessError) as caught:
        asyncio.run(dispatch())
    assert caught.value.status == 507
    assert caught.value.code == "hosted_storage_quota_exceeded"
    assert "original operation key" in str(caught.value)
    assert "private storage" not in str(caught.value)

"""Shared constants and local-only ASGI browser bridge for containerized hosting tests.

This module is strictly for local development and testing without Caddy, Cloudflare Tunnel,
Firebase, backup-proxy, egress-proxy, or host-guardian. Production entrypoints remain untouched.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from time import time_ns
from urllib.parse import urlsplit

from starlette.responses import JSONResponse, RedirectResponse

DEPLOYMENT_ID = "00000000-0000-4000-8000-000000009001"
OPERATOR_ID = "00000000-0000-4000-8000-000000009002"
WORKSPACE_ID = "00000000-0000-4000-8000-000000009003"
BINDING_ID = "00000000-0000-4000-8000-000000009004"
RELEASE_ID = "00000000-0000-4000-8000-000000009005"

REALM_ALIAS = "identity-local-v1"
PROJECT_ID = "epm-local-test"
ADMIN_SUBJECT = "local-admin-subject"
ADMIN_EMAIL = "local-admin@epmdemo.xyz"
OPERATOR_SUBJECT = "local-operator-subject"
OPERATOR_EMAIL = "demo-operator@epmdemo.xyz"
OPERATOR_SLUG = "demo"
SUPPORT_CONTACT = "dctech92130@gmail.com"

BASE_DOMAIN = "epm.local"
ADMIN_ORIGIN = f"https://admin.{BASE_DOMAIN}"
CENTRAL_ORIGIN = f"https://login.{BASE_DOMAIN}"
OPERATOR_ORIGIN = f"https://{OPERATOR_SLUG}.{BASE_DOMAIN}"

MIB = 1024 * 1024
SESSION_COOKIE_LENGTH = 43


def now_ms() -> int:
    return time_ns() // 1_000_000


def _strip_secure_attribute(raw_cookie: bytes) -> bytes:
    decoded = raw_cookie.decode("latin1")
    # Modern browsers require Secure on __Host- cookies and accept Secure on http://localhost.
    if decoded.lstrip().startswith("__Host-"):
        return raw_cookie
    parts = [part.strip() for part in decoded.split(";")]
    filtered = [part for part in parts if part.lower() != "secure"]
    return "; ".join(filtered).encode("latin1")


def _extract_cookie(headers: list[tuple[bytes, bytes]], cookie_name: str) -> str | None:
    for key, value in headers:
        if key.lower() != b"cookie":
            continue
        for item in value.decode("latin1").split(";"):
            name, sep, cookie_val = item.strip().partition("=")
            if sep and name == cookie_name and cookie_val:
                return cookie_val
    return None


@dataclass(frozen=True)
class LocalSessionHooks:
    component: str
    canonical_origin: str
    cookie_name: str
    mint_session: Callable[[], tuple[str, int]]
    revoke_current: Callable[[str], None] | None = None
    extra_status: Callable[[], dict[str, object]] | None = None


class LocalBrowserBridge:
    """Translate local HTTP localhost traffic into canonical HTTPS origin requests."""

    def __init__(self, inner_app, hooks: LocalSessionHooks) -> None:
        self.inner_app = inner_app
        self.hooks = hooks
        parsed = urlsplit(hooks.canonical_origin)
        self.canonical_host = (parsed.hostname or "").encode("ascii")
        self.canonical_origin = hooks.canonical_origin.encode("ascii")
        self.auto_login = os.environ.get("EPM_LOCAL_AUTO_LOGIN", "1") == "1"

    def _mint_redirect(self) -> RedirectResponse:
        token, max_age = self.hooks.mint_session()
        is_host_cookie = self.hooks.cookie_name.startswith("__Host-")
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            self.hooks.cookie_name,
            token,
            max_age=max_age,
            secure=is_host_cookie,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return response

    def _status_response(self, headers: list[tuple[bytes, bytes]]) -> JSONResponse:
        payload: dict[str, object] = {
            "mode": "local_container_test",
            "component": self.hooks.component,
            "canonicalOrigin": self.hooks.canonical_origin,
            "signedIn": _extract_cookie(headers, self.hooks.cookie_name) is not None,
            "autoLogin": self.auto_login,
            "endpoints": {
                "signIn": "/__local__/sign-in",
                "signOut": "/__local__/sign-out",
                "healthLive": "/health/live",
                "healthReady": "/health/ready",
            },
        }
        if self.hooks.extra_status is not None:
            payload.update(self.hooks.extra_status())
        return JSONResponse(payload)

    def _sign_out_response(self, headers: list[tuple[bytes, bytes]]) -> RedirectResponse:
        cookie_val = _extract_cookie(headers, self.hooks.cookie_name)
        if cookie_val is not None and self.hooks.revoke_current is not None:
            self.hooks.revoke_current(cookie_val)
        is_host_cookie = self.hooks.cookie_name.startswith("__Host-")
        response = RedirectResponse(url="/?signed_out=1", status_code=302)
        response.delete_cookie(
            self.hooks.cookie_name,
            secure=is_host_cookie,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return response

    def _local_response(self, scope, headers: list[tuple[bytes, bytes]]):
        path = scope.get("path", "")
        routes = {
            "/health/live": lambda: JSONResponse(
                {"status": "live", "component": self.hooks.component}
            ),
            "/health/ready": lambda: JSONResponse(
                {"status": "ready", "component": self.hooks.component}
            ),
            "/__local__/status": lambda: self._status_response(headers),
            "/__local__/sign-in": self._mint_redirect,
            "/__local__/sign-out": lambda: self._sign_out_response(headers),
        }
        handler = routes.get(path)
        if handler is not None:
            return handler()
        if self._should_auto_login(scope, headers):
            return self._mint_redirect()
        return None

    def _should_auto_login(self, scope, headers: list[tuple[bytes, bytes]]) -> bool:
        return (
            self.auto_login
            and scope.get("method", "GET").upper() == "GET"
            and scope.get("path", "") == "/"
            and b"signed_out=1" not in scope.get("query_string", b"")
            and _extract_cookie(headers, self.hooks.cookie_name) is None
        )

    def _rewrite_request_headers(
        self, headers: list[tuple[bytes, bytes]]
    ) -> list[tuple[bytes, bytes]]:
        rewritten: list[tuple[bytes, bytes]] = []
        has_host = False
        for key, value in headers:
            lower = key.lower()
            if lower == b"host":
                rewritten.append((b"host", self.canonical_host))
                has_host = True
            elif lower == b"origin":
                rewritten.append((b"origin", self.canonical_origin))
            elif lower in {b"forwarded", b"x-forwarded-host", b"x-forwarded-for"}:
                continue
            elif lower == b"x-forwarded-proto":
                rewritten.append((b"x-forwarded-proto", b"https"))
            else:
                rewritten.append((key, value))
        if not has_host:
            rewritten.append((b"host", self.canonical_host))
        return rewritten

    @staticmethod
    def _rewrite_response_headers(
        headers: list[tuple[bytes, bytes]],
    ) -> list[tuple[bytes, bytes]]:
        out: list[tuple[bytes, bytes]] = []
        for key, value in headers:
            lower = key.lower()
            if lower == b"strict-transport-security":
                continue
            if lower == b"set-cookie":
                out.append((key, _strip_secure_attribute(value)))
            else:
                out.append((key, value))
        return out

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.inner_app(scope, receive, send)
            return

        headers = list(scope.get("headers", ()))
        direct = self._local_response(scope, headers)
        if direct is not None:
            await direct(scope, receive, send)
            return

        proxied_scope = {
            **scope,
            "scheme": "https",
            "headers": self._rewrite_request_headers(headers),
            "raw_path": scope.get("path", "").encode("ascii"),
        }

        async def rewritten_send(message):
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": self._rewrite_response_headers(list(message.get("headers", ()))),
                }
            await send(message)

        await self.inner_app(proxied_scope, receive, rewritten_send)


def read_json_if_exists(path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))

"""Device-local browser boundary, independent of workspace readiness or domain state."""

from dataclasses import dataclass
from urllib.parse import urlsplit
from unicodedata import category
from typing import Literal

from pydantic import BaseModel, ConfigDict

from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

LOCAL_CLIENT_HEADER = "x-epm-local-client"
LOCAL_CLIENT_VALUE = "1"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
METHODS = SAFE_METHODS | {"POST", "PUT", "PATCH", "DELETE"}
PREFLIGHT_HEADERS = frozenset({"content-type", "idempotency-key", "x-correlation-id"})
MAX_PORT = 65535

TransportErrorCode = Literal[
    "transport_host_rejected",
    "transport_origin_rejected",
    "transport_origin_required",
    "transport_preflight_rejected",
]


class TransportProblem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: TransportErrorCode
    message: str


class TransportErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detail: TransportProblem


def local_origin(value: str) -> str:
    """Canonical exact loopback origin; never accept wildcards, paths or credentials."""
    parsed = urlsplit(value)
    if (
        value != value.strip()
        or any(character.isspace() or category(character) == "Cc" for character in value)
        or parsed.netloc.endswith(":")
        or parsed.scheme not in {"http", "https"}
        or parsed.hostname not in LOOPBACK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("An exact HTTP(S) loopback origin is required.")
    port = parsed.port
    if port is not None and not 1 <= port <= MAX_PORT:
        raise ValueError("Invalid loopback port.")
    host = f"[{parsed.hostname}]" if parsed.hostname == "::1" else parsed.hostname
    suffix = "" if port in {None, 80 if parsed.scheme == "http" else 443} else f":{port}"
    return f"{parsed.scheme}://{host}{suffix}"


@dataclass(frozen=True)
class BrowserTransportPolicy:
    development_origins: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(
            self,
            "development_origins",
            tuple(dict.fromkeys(local_origin(value) for value in self.development_origins)),
        )


class BrowserTransportMiddleware:
    def __init__(self, app: ASGIApp, *, policy: BrowserTransportPolicy):
        self.app, self.policy = app, policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            headers = request_headers(scope)
            current = local_origin(f"{scope['scheme']}://{headers['host']}")
        except ValueError, KeyError, UnicodeError:
            await problem("transport_host_rejected")(scope, receive, send)
            return
        origin = headers.get("origin")
        if origin is not None:
            try:
                origin = local_origin(origin)
            except ValueError:
                origin = "invalid"
            if origin not in {current, *self.policy.development_origins}:
                await problem("transport_origin_rejected")(scope, receive, send)
                return
        elif not absent_origin_allowed(scope["method"], headers):
            await problem("transport_origin_required")(scope, receive, send)
            return
        if "access-control-request-method" in headers:
            response = preflight(scope["method"], origin, headers)
            await response(scope, receive, send)
            return

        async def cors_send(message):
            if (
                message["type"] == "http.response.start"
                and origin in self.policy.development_origins
            ):
                response_headers = list(message.get("headers", []))
                response_headers.extend(
                    [
                        (b"access-control-allow-origin", origin.encode("ascii")),
                        (b"vary", b"Origin"),
                    ]
                )
                message = {**message, "headers": response_headers}
            await send(message)

        await self.app(scope, receive, cors_send)


def request_headers(scope):
    result = {}
    for key, value in scope["headers"]:
        name = key.decode("ascii").lower()
        if name in result and (
            name in {"host", "origin", "referer", LOCAL_CLIENT_HEADER}
            or name.startswith(("sec-fetch-", "access-control-request-"))
        ):
            raise ValueError("Duplicate request header.")
        result[name] = value.decode("latin-1")
    return result


def absent_origin_allowed(method, headers):
    browser = any(key.startswith("sec-fetch-") for key in headers) or "referer" in headers
    if method in SAFE_METHODS:
        return headers.get("sec-fetch-site") in {None, "none", "same-origin"} and (
            "referer" not in headers or headers.get("sec-fetch-site") == "same-origin"
        )
    return not browser and headers.get(LOCAL_CLIENT_HEADER) == LOCAL_CLIENT_VALUE


def preflight(method, origin, headers):
    requested = headers["access-control-request-method"]
    names = {
        item.strip().lower()
        for item in headers.get("access-control-request-headers", "").split(",")
        if item.strip()
    }
    if (
        method != "OPTIONS"
        or origin is None
        or requested not in METHODS
        or not names <= PREFLIGHT_HEADERS
    ):
        return problem("transport_preflight_rejected")
    return Response(
        status_code=204,
        headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": requested,
            "Access-Control-Allow-Headers": ", ".join(sorted(names)),
            "Access-Control-Max-Age": "600",
            "Vary": "Origin, Access-Control-Request-Method, Access-Control-Request-Headers",
        },
    )


def problem(code: TransportErrorCode):
    return JSONResponse(
        status_code=403,
        content={
            "detail": {
                "code": code,
                "message": "Request rejected by local transport policy.",
            }
        },
    )

"""Authorize before the packaged app, bootstrap, files, domains or original-result lookup."""

from collections import deque
from contextlib import nullcontext
import ipaddress
import re
from urllib.parse import quote
from time import monotonic

from collections.abc import Mapping
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import compile_path

from app.modules.hosted_access.api.router import SESSION_COOKIE
from app.modules.hosted_access.api.request_body import MAX_BODY_BYTES, bounded_body
from app.modules.hosted_access.application.ports import IdentityVerifier
from app.modules.hosted_access.application.service import HostedAccessService
from app.modules.hosted_access.domain.models import HostedAccessError
from app.platform.web_delivery import accepts_html, browser_route
from app.platform.actor_context import OperatorActor, operator_actor_scope

SAFE_METHODS = {"GET", "HEAD"}
MAX_REQUESTS_PER_MINUTE = 600
BUSINESS_ROOTS = frozenset(
    {
        "audit",
        "communications",
        "condition-checklist-templates",
        "condition-observations",
        "condition-reports",
        "expense-categories",
        "expense-refunds",
        "expenses",
        "file-links",
        "files",
        "finance",
        "inspection-commands",
        "intake",
        "leases",
        "maintenance-appointments",
        "maintenance-assignments",
        "maintenance-command-receipts",
        "maintenance-cost-contexts",
        "maintenance-expense-links",
        "maintenance-issues",
        "maintenance-quotes",
        "maintenance-work-journal",
        "money",
        "operator",
        "owner-concerns",
        "owner-rent-report-operations",
        "owner-rent-reports",
        "parties",
        "portfolio",
        "prepaid-checks",
        "properties",
        "provider-categories",
        "providers",
        "rent-expectations",
        "rent-receipts",
        "security-deposit-credits",
        "security-deposit-deduction-sources",
        "security-deposit-deductions",
        "security-deposit-receipts",
        "security-deposit-refunds",
        "security-deposit-settlements",
        "security-deposits",
        "spaces",
        "tasks",
        "tenants",
        "termination-cases",
    }
)
FORBIDDEN_PREFIXES = (
    "/api/workspace",
    "/api/ai",
    "/api/operator/recovery/expire",
    "/api/files/storage",
    "/api/files/verify",
    "/api/files/integrity",
    "/api/files/integrity-attention",
    "/api/files/reconciliation",
)
SENSITIVE_HEADERS = {
    "host",
    "origin",
    "cookie",
    "cf-access-jwt-assertion",
    "x-epm-csrf",
    "x-epm-draft-lease",
    "content-length",
}


class HostedTransportMiddleware:
    def __init__(
        self,
        app,
        *,
        service: HostedAccessService,
        verifier: IdentityVerifier,
        routes: Mapping[str, dict],
        workspace_ready,
        storage=None,
    ):
        self.app = app
        self.service = service
        self.verifier = verifier
        self.workspace_ready = workspace_ready
        self.storage = storage
        self.routes = [
            (method.upper(), compile_path(path)[0])
            for path, operations in routes.items()
            for method in operations
            if method in {"get", "post", "put", "patch", "delete", "head"}
        ]
        self.admissions = deque()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return
        response_started = False

        async def tracked_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._dispatch(scope, receive, tracked_send)
        except HostedAccessError as error:
            if response_started:
                # A streaming response cannot change its status or start a second
                # response. Let the transport close it rather than fabricate success.
                raise
            if (
                scope["method"] == "GET"
                and browser_route(scope["path"])
                and accepts_html(scope["headers"])
                and (error.status == 401 or error.code == "hosted_demo_expired")
            ):
                response = RedirectResponse(
                    "/sign-in?next="
                    + quote(
                        scope["path"]
                        + (
                            "?" + scope["query_string"].decode("utf-8", errors="replace")
                            if scope.get("query_string")
                            else ""
                        ),
                        safe="",
                    ),
                    status_code=303,
                    headers={"Cache-Control": "no-store"},
                )
                await response(scope, receive, send)
                return
            response = JSONResponse(
                {"detail": {"code": error.code, "message": str(error)}},
                status_code=error.status,
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )
            await response(scope, receive, send)

    def _headers(self, scope) -> dict[str, str]:
        result = {}
        for raw_name, raw_value in scope["headers"]:
            try:
                name, value = raw_name.decode("ascii").lower(), raw_value.decode("latin-1")
            except UnicodeDecodeError as error:
                raise HostedAccessError(
                    "hosted_headers_rejected", "Invalid request headers.", 403
                ) from error
            if name in SENSITIVE_HEADERS and name in result:
                raise HostedAccessError(
                    "hosted_headers_rejected", "Ambiguous request headers.", 403
                )
            result[name] = value
        cookies = result.get("cookie", "").split(";")
        if sum(cookie.strip().split("=", 1)[0] == SESSION_COOKIE for cookie in cookies) > 1:
            raise HostedAccessError("hosted_headers_rejected", "Ambiguous session cookies.", 403)
        return result

    def _route_allowed(self, path: str, method: str) -> bool:
        if any(path == prefix or path.startswith(prefix + "/") for prefix in FORBIDDEN_PREFIXES):
            return False
        if path in {"/api/hosted/session", "/api/hosted/session/all"}:
            return method in (
                {"GET", "POST", "DELETE"} if path.endswith("/session") else {"DELETE"}
            )
        if re.fullmatch(r"/api/hosted/drafts/[0-9a-f-]{36}/lease", path):
            return method == "POST"
        parts = path.split("/")
        if len(parts) < 3 or parts[1] != "api" or parts[2] not in BUSINESS_ROOTS:
            return method in SAFE_METHODS and browser_route(path)
        return any(method == verb and pattern.fullmatch(path) for verb, pattern in self.routes)

    async def _dispatch(self, scope, receive, send):
        headers = self._headers(scope)
        path, method = scope["path"], scope["method"]
        try:
            private_peer = ipaddress.ip_address(scope["client"][0]).is_loopback
        except ValueError, TypeError, KeyError:
            private_peer = False
        expected = self.service.deployment.public_origin.removeprefix("https://")
        if not private_peer or headers.get("host") != expected:
            raise HostedAccessError("hosted_host_rejected", "Request host is not authorized.", 403)
        origin = headers.get("origin")
        sign_in_navigation = (
            path == "/sign-in"
            and method == "GET"
            and origin is None
            and headers.get("sec-fetch-mode") == "navigate"
            and headers.get("sec-fetch-dest") == "document"
            and accepts_html(scope["headers"])
        )
        if (
            origin is not None
            and origin != self.service.deployment.public_origin
            or method not in SAFE_METHODS
            and origin != self.service.deployment.public_origin
            or headers.get("sec-fetch-site") == "cross-site"
            and not sign_in_navigation
        ):
            raise HostedAccessError(
                "hosted_origin_rejected", "Request origin is not authorized.", 403
            )
        tick = monotonic()
        while self.admissions and self.admissions[0] <= tick - 60:
            self.admissions.popleft()
        if len(self.admissions) >= MAX_REQUESTS_PER_MINUTE:
            raise HostedAccessError("hosted_rate_limited", "Request limit reached; try later.", 429)
        self.admissions.append(tick)
        try:
            size = int(headers.get("content-length", "0"))
        except ValueError as error:
            raise HostedAccessError(
                "hosted_body_rejected", "Invalid request length.", 400
            ) from error
        if size < 0 or size > MAX_BODY_BYTES:
            raise HostedAccessError("request_payload_too_large", "Request exceeds its limit.", 413)
        public_asset = (
            bool(
                re.fullmatch(
                    r"/assets/[A-Za-z0-9_.-]+-[A-Za-z0-9_-]{8,64}\.(?:js|css|svg|png|jpg|webp|ico|woff2)",
                    path,
                )
            )
            and method in SAFE_METHODS
        )
        public_sign_in = path == "/sign-in" and method in SAFE_METHODS
        if not public_asset and not public_sign_in:
            if not self._route_allowed(path, method):
                raise HostedAccessError("hosted_route_forbidden", "Route is unavailable.", 403)
            identity = await run_in_threadpool(
                self.verifier.verify, headers.get("cf-access-jwt-assertion", "")
            )
            scope.setdefault("state", {})["hosted_identity"] = identity
            if not (path == "/api/hosted/session" and method == "POST"):
                request = Request(scope)
                token = request.cookies.get(SESSION_COOKIE, "")
                actor = await run_in_threadpool(
                    self.service.authenticate,
                    identity,
                    token,
                    csrf=headers.get("x-epm-csrf", "") if method not in SAFE_METHODS else None,
                )
                scope["state"]["hosted_actor"] = actor
                self._capability(path, method)
                if (
                    headers.get("content-type", "").startswith("multipart/")
                    and "files.write" not in self.service.deployment.capabilities
                ):
                    raise HostedAccessError(
                        "hosted_capability_forbidden", "File action unavailable.", 403
                    )
                if not path.startswith("/api/hosted/") and not self.workspace_ready():
                    raise HostedAccessError(
                        "hosted_workspace_unavailable", "Workspace unavailable.", 503
                    )

        replaced_failure = False

        async def private_send(message):
            nonlocal replaced_failure
            if replaced_failure:
                return
            if (
                message["type"] == "http.response.start"
                and message["status"] >= 500
                and self.storage is not None
                and self.storage.exhausted()
            ):
                replaced_failure = True
                # A source may have committed before a response failed. Keep the
                # original receipt/retry contract; never claim this proves rollback.
                response = JSONResponse(
                    {
                        "detail": {
                            "code": "hosted_storage_quota_exceeded",
                            "message": "Storage is exhausted. Keep the original operation key, check its result, and contact the administrator.",
                        }
                    },
                    status_code=507,
                    headers={"Cache-Control": "no-store"},
                )
                await response(scope, receive, send)
                return
            if message["type"] == "http.response.start" and not public_asset:
                values = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"cache-control"
                ]
                message = {**message, "headers": [*values, (b"cache-control", b"no-store")]}
            await send(message)

        actor = scope.get("state", {}).get("hosted_actor")
        # The authenticated HTML shell must still render a truthful storage error
        # and explicit retry. Only API dispatch can touch workspace data/audit.
        protected_business = (
            actor is not None and path.startswith("/api/") and not path.startswith("/api/hosted/")
        )
        # Unknown-length bodies reserve the entire allowed body before any spool.
        # Public/session requests cannot carry uploads; reject their bodies early.
        reserved_body = (
            size
            if "content-length" in headers
            else (
                MAX_BODY_BYTES
                if (protected_business and method not in SAFE_METHODS)
                or "transfer-encoding" in headers
                else 0
            )
        )
        if not protected_business and reserved_body > 16 * 1024:
            raise HostedAccessError(
                "hosted_body_rejected", "This route does not accept a body.", 400
            )
        reservation = (
            self.storage.reserve(reserved_body, write=method not in SAFE_METHODS)
            if self.storage is not None and protected_business
            else nullcontext()
        )
        with reservation:
            async with bounded_body(receive, max_bytes=reserved_body) as replay:
                if actor is None:
                    await self.app(scope, replay, private_send)
                else:
                    with operator_actor_scope(
                        OperatorActor(
                            actor.operator_id,
                            actor.workspace_id,
                            actor.session_reference,
                            headers.get("x-epm-draft-lease"),
                        )
                    ):
                        await self.app(scope, replay, private_send)

    def _capability(self, path: str, method: str) -> None:
        if path.startswith("/api/hosted/"):
            return
        needed = "records.read" if method in SAFE_METHODS else "records.write"
        capabilities = self.service.deployment.capabilities
        if needed not in capabilities:
            raise HostedAccessError("hosted_capability_forbidden", "Action is unavailable.", 403)
        if path.startswith(("/api/files", "/api/file-links")):
            needed = "files.read" if method in SAFE_METHODS else "files.write"
            if needed not in capabilities:
                raise HostedAccessError(
                    "hosted_capability_forbidden", "File action unavailable.", 403
                )

"""Explicit Admin-only ASGI composition for protected identity deployment."""

import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from pathlib import Path
from pydantic import SecretStr, ValidationError

from app.modules.host_agent.application.auth_routes import IdentityCookiePolicy
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.api.start_rate import StartRateLimiter
from app.modules.hosted_access.infrastructure.admin_sessions import AdminSessions

MAX_BODY = 20000


def build_admin_identity_app(
    sessions: AdminSessions,
    *,
    web_config=None,
    ui_directory: Path | None = None,
    start_limiter: StartRateLimiter | None = None,
) -> FastAPI:
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.router.redirect_slashes = False
    origin = sessions.provider.setup.origins.admin
    cookies = IdentityCookiePolicy()
    limiter = start_limiter or StartRateLimiter()

    def cookie(request, name):
        raw = request.headers.get("cookie", "")
        values = [part.strip().split("=", 1) for part in raw.split(";") if "=" in part]
        matching = [value for key, value in values if key == name]
        if len(matching) != 1:
            raise ProviderDenied()
        return matching[0]

    def set_cookie(response, name, value, seconds):
        response.set_cookie(
            name, value, max_age=seconds, secure=True, httponly=True, samesite="lax", path="/"
        )

    @app.middleware("http")
    async def boundary(request, call_next):
        try:
            for key in (
                "host",
                "origin",
                "cookie",
                "content-type",
                "content-length",
                "x-csrf-token",
            ):
                if len(request.headers.getlist(key)) > 1:
                    raise ProviderDenied()
            if str(request.base_url).rstrip("/") != origin:
                raise ProviderDenied()
            if request.method == "POST" and request.headers.get("origin") != origin:
                raise ProviderDenied()
            response = await call_next(request)
        except ProviderDenied:
            response = JSONResponse({"message": "Start Admin sign-in again."}, status_code=401)
        except ProviderUnavailable:
            response = JSONResponse(
                {"message": "Sign-in is temporarily unavailable."}, status_code=503
            )
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'self' https://apis.google.com; "
                    "style-src 'self'; connect-src 'self' https://identitytoolkit.googleapis.com "
                    "https://securetoken.googleapis.com; frame-src "
                    + sessions.provider.setup.origins.central
                    + "; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
                ),
                "Cross-Origin-Opener-Policy": "same-origin-allow-popups",
            }
        )
        return response

    async def body(request):
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise ProviderDenied()
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BODY:
                raise ProviderDenied()

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ProviderDenied()
                result[key] = value
            return result

        try:
            value = json.loads(raw, object_pairs_hook=unique)
        except ValueError, RecursionError:
            raise ProviderDenied() from None
        if not isinstance(value, dict):
            raise ProviderDenied()
        return value

    @app.get("/auth/start")
    def start(request: Request):
        limiter.check(request)
        attempt, challenge = sessions.begin()
        response = JSONResponse({"attemptId": attempt, **(web_config or {})})
        set_cookie(response, cookies.central_challenge, challenge, 900)
        return response

    @app.post("/auth/complete")
    async def complete(request: Request):
        value = await body(request)
        if set(value) not in ({"attemptId", "token"}, {"attemptId", "token", "phase"}) or not all(
            isinstance(v, str) for v in value.values()
        ):
            raise ProviderDenied()
        # Provider transport is blocking and bounded. Keep it outside the ASGI event loop.
        from starlette.concurrency import run_in_threadpool

        if "phase" in value:
            if value["phase"] != "enroll":
                raise ProviderDenied()
            await run_in_threadpool(
                sessions.enrollment_allowed,
                SecretStr(value["token"]),
                value["attemptId"],
                cookie(request, cookies.central_challenge),
            )
            return JSONResponse({"message": "Continue authenticator setup."})
        try:
            credentials = await run_in_threadpool(
                sessions.sign_in,
                SecretStr(value["token"]),
                attempt_id=value["attemptId"],
                browser=cookie(request, cookies.central_challenge),
            )
        except ValidationError:
            raise ProviderDenied() from None
        response = JSONResponse(
            {"csrfToken": credentials.csrf, "expiresAt": credentials.expires_at}
        )
        set_cookie(
            response,
            cookies.admin,
            credentials.session,
            max(0, (credentials.expires_at - sessions.clock()) // 1000),
        )
        response.delete_cookie(
            cookies.central_challenge, secure=True, httponly=True, samesite="lax"
        )
        return response

    @app.get("/api/admin/session")
    def status(request: Request):
        session = sessions.authenticate(cookie(request, cookies.admin))
        return {
            "expiresAt": session.expires_at,
            "csrfToken": sessions.csrf_token(cookie(request, cookies.admin)),
            "recentAuthRequired": sessions.clock() >= session.mfa_verified_at + 900000,
        }

    @app.post("/auth/logout")
    async def logout(request: Request):
        from starlette.concurrency import run_in_threadpool

        await run_in_threadpool(
            sessions.logout, cookie(request, cookies.admin), request.headers.get("x-csrf-token")
        )
        response = JSONResponse({"message": "Signed out."})
        response.delete_cookie(cookies.admin, secure=True, httponly=True, samesite="lax")
        return response

    if ui_directory is not None:

        @app.get("/")
        def index():
            return FileResponse(ui_directory / "index.html")

        @app.get("/assets/{name}")
        def asset(name: str):
            path = ui_directory / "assets" / name
            if path.suffix not in {".js", ".css"} or path.name != name or not path.is_file():
                raise ProviderDenied()
            return FileResponse(path)

    return app

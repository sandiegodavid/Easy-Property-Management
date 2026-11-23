"""Central-only identity routes composed with authenticated source and readiness owners."""

import asyncio
import json
from pathlib import Path
from secrets import token_urlsafe
from uuid import UUID
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError
from starlette.concurrency import run_in_threadpool

from app.modules.host_agent.application.auth_routes import IdentityCookiePolicy
from app.modules.hosted_access.api.handoff_forms import read_form, transfer_form
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.infrastructure.central_login import CentralCompletion
from app.platform.hosted_security_headers import HSTS_HEADER_VALUE, PERMISSIONS_POLICY_VALUE


class Completion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    attemptId: str
    token: SecretStr | None = None
    email: str | None = None
    code: SecretStr | None = None
    remembered: bool = False


def build_central_identity_app(
    service, *, ui_directory: Path, web_config, network_source, pairing=None, handoffs=None
):
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.router.redirect_slashes = False
    origin = service.attempts.setup.origins.central
    cookies = IdentityCookiePolicy()

    def identifier(value):
        try:
            if str(UUID(value)) != value:
                raise ValueError()
        except ValueError, TypeError, AttributeError:
            raise ProviderDenied() from None
        return value

    def observed_cookie(request, name=cookies.central_challenge):
        values = [
            entry.strip().split("=", 1)
            for entry in request.headers.get("cookie", "").split(";")
            if "=" in entry
        ]
        matching = [value for cookie_name, value in values if cookie_name == name]
        if len(matching) != 1 or len(matching[0]) != 43:
            raise ProviderDenied()
        return matching[0]

    def set_cookie(response, name, value, seconds):
        response.set_cookie(
            name, value, secure=True, httponly=True, samesite="lax", path="/", max_age=seconds
        )

    @app.middleware("http")
    async def boundary(request, call_next):
        nonce = token_urlsafe(24)
        request.state.nonce = nonce
        try:
            for header in ("host", "origin", "cookie", "content-type", "content-length"):
                if len(request.headers.getlist(header)) > 1:
                    raise ProviderDenied()
            if str(request.base_url).rstrip("/") != origin:
                raise ProviderDenied()
            form_return = (
                pairing is not None
                and request.url.path == "/auth/email/continue"
                and request.headers.get("content-type", "").split(";", 1)[0]
                == "application/x-www-form-urlencoded"
            )
            if (
                request.method == "POST"
                and request.headers.get("origin") != origin
                and not form_return
            ):
                raise ProviderDenied()
            response = await call_next(request)
        except ProviderDenied, ValidationError:
            response = JSONResponse(
                {"message": "Start a new sign-in from your workspace."}, status_code=401
            )
        except ProviderUnavailable, TimeoutError:
            response = JSONResponse(
                {"message": "Sign-in is temporarily unavailable."}, status_code=503
            )
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "Strict-Transport-Security": HSTS_HEADER_VALUE,
                "Permissions-Policy": PERMISSIONS_POLICY_VALUE,
                "Cross-Origin-Opener-Policy": "same-origin-allow-popups",
                "Content-Security-Policy": f"default-src 'none'; script-src 'self' 'nonce-{nonce}' https://apis.google.com; "
                "style-src 'self'; connect-src 'self' https://identitytoolkit.googleapis.com "
                "https://securetoken.googleapis.com; frame-src 'self'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'",
            }
        )
        if hasattr(request.state, "handoff_origin"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action "
                + request.state.handoff_origin
            )
        return response

    async def bounded_bytes(request):
        raw = bytearray()
        async with asyncio.timeout(10):
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 20000:
                    raise ProviderDenied()

        return raw

    async def body(request):
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise ProviderDenied()
        raw = await bounded_bytes(request)

        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ProviderDenied()
                value[key] = item
            return value

        try:
            value = json.loads(raw, object_pairs_hook=unique)
        except ValueError, RecursionError:
            raise ProviderDenied() from None
        if not isinstance(value, dict):
            raise ProviderDenied()
        return value

    def html(request, *, email=False):
        content = (ui_directory / "index.html").read_text()
        # This script executes before any application or third-party resources load.
        scrub = (
            "const p=new URLSearchParams(location.search);"
            "let a=p.get('attempt');"
            "try{const u=new URL(p.get('continueUrl'));"
            "if(u.origin===location.origin&&u.pathname==='/auth/email/continue')"
            "a=u.searchParams.get('attempt');}catch{}"
            "window.epmEmailCompletion={code:p.get('oobCode'),attempt:a};"
            "history.replaceState(null,'',location.pathname);"
        )
        script = f'<script nonce="{request.state.nonce}">{scrub}</script>' if email else ""
        content = content.replace("<head>", "<head>" + script, 1)
        response = HTMLResponse(content)
        if email:
            set_cookie(response, cookies.central_challenge, token_urlsafe(32), 900)
        return response

    @app.get("/auth/start")
    async def start(request: Request):
        if "application/json" not in request.headers.get("accept", ""):
            return html(request)
        if "attempt" in request.query_params:
            attempt_id = identifier(request.query_params["attempt"])

            def inspect():
                with service.engine.connect() as connection:
                    row = service.attempts.attempt(connection, attempt_id, observed_cookie(request))
                    return {"state": row["state"]}

            return await run_in_threadpool(inspect)
        flow = identifier(request.query_params.get("flow"))
        method = request.query_params.get("method", "google")
        if method != "google":
            raise ProviderDenied()
        source = request.query_params.get("source")
        attempt, challenge = await run_in_threadpool(
            service.attempts.start,
            flow,
            method=method,
            origin_id=identifier(source) if source is not None else None,
        )
        response = JSONResponse({"attemptId": attempt, **web_config})
        set_cookie(response, cookies.central_challenge, challenge, 900)
        return response

    @app.post("/auth/email-link")
    async def email_link(request: Request):
        value = await body(request)
        if set(value) - {"flowId", "email", "source"} or not isinstance(value.get("email"), str):
            raise ProviderDenied()
        network = network_source(request)
        if not network:
            raise ProviderUnavailable()
        attempt, challenge = await run_in_threadpool(
            service.attempts.start,
            identifier(value.get("flowId")),
            method="email_link",
            email=value["email"],
            origin_id=identifier(value["source"]) if "source" in value else None,
        )
        await run_in_threadpool(service.send_email, attempt, challenge, network=network)
        response = JSONResponse({"state": "sent", "attemptId": attempt})
        set_cookie(response, cookies.central_challenge, challenge, 900)
        return response

    def completion_response(result, remembered):
        if isinstance(result, CentralCompletion):
            response = JSONResponse(result.result)
            set_cookie(
                response,
                cookies.central,
                result.cookie.get_secret_value(),
                30 * 86400 if remembered else 8 * 3600,
            )
            return response
        return JSONResponse(result)

    @app.post("/auth/complete")
    async def complete(request: Request):
        if (
            request.headers.get("content-type", "").split(";", 1)[0]
            == "application/x-www-form-urlencoded"
        ):
            if handoffs is None:
                raise ProviderDenied()
            form = await read_form(request, {"attemptId"})
            handoff = await run_in_threadpool(
                handoffs.issue_google,
                identifier(form["attemptId"]),
                observed_cookie(request),
                SecretStr(observed_cookie(request, cookies.central)),
            )
            return destination_form(request, handoff)
        value = Completion.model_validate(await body(request))
        if value.token is None or value.code is not None or value.email is not None:
            raise ProviderDenied()
        browser = observed_cookie(request)
        result = await run_in_threadpool(
            service.complete_google,
            identifier(value.attemptId),
            browser,
            value.token,
            remembered=value.remembered,
        )
        if handoffs is not None and isinstance(result, CentralCompletion):
            claim = result.result.get("claim")
            claim_ready = claim is None or "state" not in claim
            if (
                claim_ready
                and result.operator_id is not None
                and await run_in_threadpool(handoffs.google_ready, result.operator_id)
            ):
                result = CentralCompletion(
                    {"state": "verified", "handoffAttempt": value.attemptId},
                    result.cookie,
                    operator_id=result.operator_id,
                )
        return completion_response(result, value.remembered)

    def destination_form(request, handoff):
        if handoff is None:
            return HTMLResponse(
                '<!doctype html><html lang="en"><meta charset="utf-8">'
                "<title>Workspace sign-in</title><main><h1>Identity verified</h1>"
                "<p>Your workspace is not ready for access yet.</p></main></html>"
            )
        request.state.handoff_origin = handoff.target_origin
        return transfer_form(
            handoff.target_origin,
            "/auth/complete",
            {"handoff": handoff.token.get_secret_value()},
            heading="Identity verified",
            button="Continue to your workspace",
        )

    @app.get("/auth/email/continue")
    def continue_email(request: Request):
        return html(request, email=True)

    @app.post("/auth/email/continue")
    async def finish_email(request: Request):
        if (
            request.headers.get("content-type", "").split(";", 1)[0]
            == "application/x-www-form-urlencoded"
        ):
            if pairing is None or request.headers.get("origin") in {None, origin}:
                raise ProviderDenied()
            try:
                fields = parse_qsl(
                    (await bounded_bytes(request)).decode("ascii"),
                    strict_parsing=True,
                    max_num_fields=2,
                    errors="strict",
                )
            except UnicodeError, ValueError:
                raise ProviderDenied() from None
            if len(fields) != 2 or set(dict(fields)) != {"continuationId", "assertion"}:
                raise ProviderDenied()
            form = dict(fields)
            if not 1 <= len(form["assertion"]) <= 16384:
                raise ProviderDenied()
            browser = observed_cookie(request)
            cookie = observed_cookie(request, cookies.central)
            continuation = identifier(form["continuationId"])
            await run_in_threadpool(
                pairing.pair,
                continuation,
                SecretStr(form["assertion"]),
                origin=request.headers["origin"],
                browser=browser,
                cookie=cookie,
            )
            handoff = (
                await run_in_threadpool(
                    handoffs.issue_paired, continuation, browser, SecretStr(cookie)
                )
                if handoffs is not None
                else None
            )
            return destination_form(request, handoff)
        value = Completion.model_validate(await body(request))
        if value.token is not None or value.email is None or value.code is None:
            raise ProviderDenied()
        result = await run_in_threadpool(
            service.complete_email,
            identifier(value.attemptId),
            observed_cookie(request),
            value.email,
            value.code,
            remembered=value.remembered,
        )
        return completion_response(result, value.remembered)

    @app.get("/assets/{name}")
    def asset(name: str):
        path = ui_directory / "assets" / name
        if path.name != name or path.suffix not in {".js", ".css"} or not path.is_file():
            raise ProviderDenied()
        return FileResponse(path)

    return app

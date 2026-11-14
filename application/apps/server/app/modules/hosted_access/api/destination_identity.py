"""Destination auth routes for the owning Operator process."""

from datetime import UTC, datetime
from html import escape
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import SecretStr
from starlette.concurrency import run_in_threadpool

from app.modules.host_agent.application.auth_routes import IdentityCookiePolicy
from app.modules.hosted_access.api.handoff_forms import read_form, transfer_form
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)

from app.modules.hosted_access.infrastructure.source_sessions import SessionLimitReached


def _identifier(raw):
    try:
        if str(UUID(raw)) == raw:
            return raw
    except ValueError, TypeError, AttributeError:
        pass
    raise ProviderDenied()


def _device_label(agent):
    for marker, label in (
        ("Edg/", "Microsoft Edge"),
        ("Firefox/", "Firefox"),
        ("Chrome/", "Chrome"),
        ("Safari/", "Safari"),
    ):
        if marker in agent:
            return label
    return "Browser"


def destination_router(owner, central, *, source_origin, central_origin):
    router = APIRouter(include_in_schema=False)
    cookies = IdentityCookiePolicy()

    def boundary(request):
        if (
            str(request.base_url).rstrip("/") != source_origin
            or request.scope.get("raw_path") != request.url.path.encode("ascii")
            or any(
                len(request.headers.getlist(name)) > 1
                for name in ("host", "origin", "cookie", "content-type", "content-length")
            )
        ):
            raise ProviderDenied()

    def cookie(request, name, *, optional=False):
        pairs = (
            value.strip().split("=", 1)
            for value in request.headers.get("cookie", "").split(";")
            if "=" in value
        )
        matches = [value for key, value in pairs if key == name]
        if not matches and optional:
            return None
        if len(matches) != 1 or len(matches[0]) != 43:
            raise ProviderDenied()
        return matches[0]

    def challenge(request):
        return cookie(request, cookies.source_challenge)

    def denied(error):
        capped = isinstance(error, SessionLimitReached)
        unavailable = isinstance(error, (ProviderUnavailable, TimeoutError))
        return JSONResponse(
            {
                **({"code": error.code} if capped else {}),
                "message": "Sign-in is temporarily unavailable."
                if unavailable
                else "Sign out another device before continuing."
                if capped
                else "Start a new sign-in from your workspace.",
            },
            status_code=503 if unavailable else 409 if capped else 401,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    @router.get("/auth/start")
    async def start(request: Request):
        try:
            boundary(request)
            query = dict(request.query_params)
            if len(query) != len(request.query_params.multi_items()):
                raise ProviderDenied()
            if set(query) == {"continuation"}:
                continuation = _identifier(query["continuation"])
                context = await run_in_threadpool(central.continuation_target, continuation)
                if context.binding.target_origin != source_origin:
                    raise ProviderDenied()
                result = await run_in_threadpool(
                    owner.begin,
                    context.return_path,
                    remembered=context.remembered,
                    continuation_id=continuation,
                    continuation_expires=context.expires_at,
                    expected_binding=context.binding,
                    renewal_cookie=cookie(request, cookies.operator)
                    if context.renewal is not None
                    else None,
                    expected_renewal=context.renewal,
                )
                response = transfer_form(
                    central_origin,
                    "/auth/email/continue",
                    {
                        "continuationId": continuation,
                        "assertion": result.assertion.get_secret_value(),
                    },
                    heading="Continue signing in",
                    button="Continue to secure sign-in",
                )
            elif query.keys() <= {"returnTo", "renew"} and query.get("renew") in {None, "1"}:
                result = await run_in_threadpool(
                    owner.begin,
                    query.get("returnTo", "/home"),
                    renewal_cookie=cookie(request, cookies.operator)
                    if query.get("renew")
                    else None,
                )
                response = RedirectResponse(
                    central_origin
                    + "/auth/start?flow="
                    + result.attempt.attempt_id
                    + "&source="
                    + result.origin_id,
                    status_code=303,
                )
            else:
                raise ProviderDenied()
            response.set_cookie(
                cookies.source_challenge,
                result.challenge.get_secret_value(),
                secure=True,
                httponly=True,
                path="/",
                samesite="lax",
                max_age=max(0, (result.attempt.expires_at - owner.clock()) // 1000),
            )
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response
        except (ProviderDenied, ProviderUnavailable, TimeoutError, ValueError) as error:
            return denied(error)

    def cap_form(token, devices):
        options = "".join(
            f'<option value="{escape(row["session_id"], quote=True)}">'
            f"{escape(row['display_label'])} · Last seen "
            f"{datetime.fromtimestamp(row['last_seen_at'] / 1000, UTC):%b %d, %Y at %H:%M UTC}</option>"
            for row in devices
        )
        return HTMLResponse(
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="color-scheme" content="light dark">'
            "<title>Choose a device to sign out</title><main><h1>Choose a device to sign out</h1>"
            "<p>Your workspace has reached its signed-in device limit.</p>"
            '<form method="post" action="/auth/complete">'
            f'<input type="hidden" name="handoff" value="{escape(token.get_secret_value(), quote=True)}">'
            '<label for="device">Device to sign out</label> '
            f'<select id="device" name="device" required><option value="">Choose a device</option>{options}</select> '
            '<button type="submit">Sign out selected device and continue</button></form>'
            '<p><a href="/sign-in">Cancel</a></p></main></html>',
            status_code=409,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.post("/auth/complete")
    async def complete(request: Request):
        try:
            boundary(request)
            if request.url.query:
                raise ProviderDenied()
            origin = request.headers.get("origin")
            if origin not in {source_origin, central_origin}:
                raise ProviderDenied()
            replacing = origin == source_origin
            browser = challenge(request)
            form = await read_form(request, {"handoff", "device"} if replacing else {"handoff"})
            token = SecretStr(form["handoff"])
            prior = cookie(request, cookies.operator, optional=True)
            device = _identifier(form["device"]) if replacing else None
            try:
                result = await run_in_threadpool(
                    owner.redeem,
                    token,
                    browser,
                    central,
                    renewal_cookie=prior,
                    replace_device=device,
                    device_label=_device_label(request.headers.get("user-agent", "")),
                )
            except SessionLimitReached:
                if "text/html" not in request.headers.get("accept", ""):
                    raise
                devices = await run_in_threadpool(
                    owner.cap_devices, token, browser, renewal_cookie=prior
                )
                return cap_form(token, devices)
            response = RedirectResponse(result.return_path, status_code=303)
            response.set_cookie(
                cookies.operator,
                result.session.get_secret_value(),
                secure=True,
                httponly=True,
                path="/",
                samesite="lax",
                max_age=max(0, (result.remembered_until - owner.clock()) // 1000)
                if result.remembered
                else None,
            )
            response.delete_cookie(
                cookies.source_challenge, secure=True, httponly=True, path="/", samesite="lax"
            )
            response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
            return response
        except (ProviderDenied, ProviderUnavailable, TimeoutError, ValueError) as error:
            return denied(error)

    @router.get("/auth/status")
    def status(request: Request):
        try:
            boundary(request)
            if (
                set(request.query_params) != {"attempt"}
                or len(request.query_params.multi_items()) != 1
            ):
                raise ProviderDenied()
            state = owner.status(_identifier(request.query_params["attempt"]), challenge(request))
            return JSONResponse({"state": state}, headers={"Cache-Control": "no-store"})
        except (ProviderDenied, ProviderUnavailable, TimeoutError, ValueError) as error:
            return denied(error)

    return router

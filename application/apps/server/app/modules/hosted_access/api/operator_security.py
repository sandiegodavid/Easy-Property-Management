"""Protected, source-owned browser session and device endpoints."""

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import model_validator
from starlette.concurrency import run_in_threadpool

from app.modules.host_agent.application.auth_routes import IdentityCookiePolicy
from app.modules.hosted_access.api.handoff_forms import FormTooLarge, read_form
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.infrastructure.source_sessions import SessionExpired, session_hash
from app.platform.hosted_contracts.values import CanonicalId, Contract
from app.platform.hosted_contracts.operations import SemanticConflict

SESSION = "/api/hosted/session"
SECURITY_ROUTES = frozenset(
    {
        SESSION,
        SESSION + "/refresh",
        SESSION + "/logout",
        SESSION + "/logout/check",
        "/api/hosted/sessions",
    }
)
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


class OriginDenied(ProviderDenied):
    pass


class SignOut(Contract):
    operation: CanonicalId
    proof: str
    selection: Literal["current", "all", "other"]
    device: CanonicalId | None = None

    @model_validator(mode="after")
    def fields(self):
        session_hash(self.proof)
        if (self.device is not None) != (self.selection == "other"):
            raise ValueError("Select exactly one device or sign-out scope.")
        return self


def operator_security_router(owner, *, origin):
    router = APIRouter(include_in_schema=False)
    name = IdentityCookiePolicy().operator

    def inspect(request, *, mutating=False, cookie_required=True):
        if (
            str(request.base_url).rstrip("/") != origin
            or request.scope.get("raw_path") != request.url.path.encode("ascii")
            or request.url.query
            or any(
                len(request.headers.getlist(key)) > 1
                for key in (
                    "host",
                    "origin",
                    "cookie",
                    "content-type",
                    "content-length",
                    "x-epm-csrf",
                )
            )
        ):
            raise OriginDenied()
        if mutating and request.headers.get("origin") != origin:
            raise OriginDenied()
        cookies = [
            entry.strip().split("=", 1)
            for entry in request.headers.get("cookie", "").split(";")
            if "=" in entry
        ]
        values = [value for key, value in cookies if key == name]
        if len(values) > 1 or (cookie_required and not values):
            raise ProviderDenied()
        return values[0] if values else None

    def error(exc):
        if isinstance(exc, (OriginDenied, FormTooLarge, SemanticConflict)):
            status = (
                403
                if isinstance(exc, OriginDenied)
                else 413
                if isinstance(exc, FormTooLarge)
                else 409
            )
            return JSONResponse({"state": "rejected"}, status_code=status, headers=HEADERS)
        code, status = (
            ("unavailable", 503)
            if isinstance(exc, (ProviderUnavailable, TimeoutError))
            else ("renewal_required", 401)
            if isinstance(exc, SessionExpired)
            else ("signed_out", 401)
        )
        return JSONResponse({"state": code}, status_code=status, headers=HEADERS)

    @router.get(SESSION)
    def session(request: Request):
        try:
            cookie = inspect(request)
            return JSONResponse(owner.session(cookie), headers=HEADERS)
        except ProviderUnavailable as exc:
            try:
                csrf = owner.refresh_csrf(cookie)
            except ValueError, ProviderUnavailable:
                return error(exc)
            return JSONResponse(
                {"state": "unavailable", "refreshCsrf": csrf}, status_code=503, headers=HEADERS
            )
        except ValueError as exc:
            return error(exc)

    @router.post(SESSION + "/refresh")
    def refresh(request: Request):
        try:
            cookie = inspect(request, mutating=True)
            owner.refresh(cookie, request.headers.get("x-epm-csrf"))
            return JSONResponse(owner.session(cookie), headers=HEADERS)
        except (ValueError, ProviderUnavailable, TimeoutError) as exc:
            return error(exc)

    @router.get("/api/hosted/sessions")
    def sessions(request: Request):
        try:
            return JSONResponse({"items": owner.devices(inspect(request))}, headers=HEADERS)
        except (ValueError, ProviderUnavailable) as exc:
            return error(exc)

    async def sign_out(request, *, check):
        try:
            cookie = inspect(request, mutating=True, cookie_required=not check)
            fields = await read_form(request, {"operation", "proof", "selection", "device"})
            fields["device"] = fields["device"] or None
            value = SignOut.model_validate(fields)
            if check:
                state, clear = await run_in_threadpool(
                    owner.check_sign_out,
                    value.operation,
                    value.proof,
                    cookie=cookie,
                    selection=value.selection,
                    device=value.device,
                )
            else:
                confirmed = await run_in_threadpool(
                    owner.sign_out,
                    cookie,
                    request.headers.get("x-epm-csrf"),
                    value.operation,
                    value.proof,
                    selection=value.selection,
                    device=value.device,
                )
                state = "confirmed" if confirmed else "pending"
                clear = value.selection != "other"
            response = JSONResponse({"state": state}, headers=HEADERS)
            if clear:
                response.delete_cookie(name, secure=True, httponly=True, samesite="lax", path="/")
            return response
        except (ValueError, ProviderUnavailable, TimeoutError) as exc:
            return error(exc)

    @router.post(SESSION + "/logout")
    async def logout(request: Request):
        return await sign_out(request, check=False)

    @router.post(SESSION + "/logout/check")
    async def check_logout(request: Request):
        return await sign_out(request, check=True)

    return router

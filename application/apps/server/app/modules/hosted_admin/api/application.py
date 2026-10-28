"""Separate loopback-only Admin listener. Not mounted in the business application."""

import json
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.modules.hosted_admin.application.contracts import AdminError, BrokerRequest
from app.modules.hosted_admin.infrastructure.broker import MAX_FRAME
from app.modules.hosted_admin.api.sign_in import CSRF_COOKIE, sign_in_page

COOKIE = "epm_private_admin"


def create_admin_app(origin, call):
    # The installed launcher/Host are fixed. Cookies are scoped to this dedicated hostname.
    from urllib.parse import urlsplit

    parsed = urlsplit(origin)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "epm-admin.localhost"
        or parsed.port is None
        or parsed.netloc != f"epm-admin.localhost:{parsed.port}"
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise AdminError("admin_origin_invalid", 503)
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def transport(request, next_handler):
        if (
            request.headers.get("host") != parsed.netloc
            or request.headers.get("sec-fetch-site") not in {None, "same-origin", "none"}
            or any(key.lower().startswith(("forwarded", "x-forwarded-")) for key in request.headers)
            or (request.method != "GET" and request.headers.get("origin") != origin)
            or request.method not in {"GET", "POST"}
            or request.query_params
        ):
            response = JSONResponse({"code": "admin_transport_denied"}, status_code=403)
        else:
            response = await next_handler(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; form-action 'self'",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "same-origin",
            }
        )
        return response

    @app.get("/")
    async def home(request: Request):
        try:
            result = await run_in_threadpool(
                call,
                BrokerRequest(method="session", token=request.cookies.get(COOKIE, "")).model_dump(),
            )
            return sign_in_page(result["identity"], request.cookies.get(CSRF_COOKIE, ""))
        except AdminError as error:
            if error.status == 503:
                return sign_in_page(error="admin_broker_unavailable", status=503)
            return sign_in_page()
        except OSError:
            return sign_in_page(error="admin_broker_unavailable", status=503)

    @app.post("/sign-in")
    @app.post("/sign-out")
    async def native_form(request: Request):
        raw = bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw) > MAX_FRAME:
                return JSONResponse({"code": "admin_request_too_large"}, status_code=413)
        try:
            if request.headers.get("content-type") != "application/x-www-form-urlencoded":
                raise ValueError()
            values = parse_qs(raw.decode(), strict_parsing=True, max_num_fields=1)
            key = "credential" if request.url.path == "/sign-in" else "csrf"
            if set(values) != {key} or len(values[key]) != 1:
                raise ValueError()
            payload = BrokerRequest(
                method="login" if key == "credential" else "logout",
                credential=values[key][0] if key == "credential" else "",
                csrf=values[key][0] if key == "csrf" else "",
                token=request.cookies.get(COOKIE, ""),
            )
            result = await run_in_threadpool(call, payload.model_dump())
            if key == "csrf":
                response = RedirectResponse("/", status_code=303)
                response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict")
                response.delete_cookie(CSRF_COOKIE, path="/", httponly=True, samesite="strict")
                return response
            response = RedirectResponse("/", status_code=303)
            for name, value in ((COOKIE, result["token"]), (CSRF_COOKIE, result["csrf"])):
                response.set_cookie(
                    name, value, httponly=True, samesite="strict", path="/", max_age=28800
                )
            return response
        except AdminError as error:
            return sign_in_page(error=error.code, status=error.status)
        except ValueError:
            return sign_in_page(error="admin_request_invalid", status=400)
        except OSError:
            return sign_in_page(error="admin_broker_unavailable", status=503)

    @app.get("/session")
    async def session(request: Request):
        return await forward(request, {"method": "session"})

    @app.post("/{action}")
    async def command(action: str, request: Request):
        methods = {
            "login": "login",
            "logout": "logout",
            "reauthenticate": "reauthenticate",
            "commands": "command",
            "lookup": "lookup",
            "source-status": "source_status",
        }
        if action not in methods or request.headers.get("content-type") != "application/json":
            return JSONResponse({"code": "admin_request_invalid"}, status_code=400)
        raw = bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw) > MAX_FRAME:
                return JSONResponse({"code": "admin_request_too_large"}, status_code=413)
        try:
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) - {
                "credential",
                "command",
                "operation_id",
                "instance",
            }:
                raise ValueError()
        except ValueError:
            return JSONResponse({"code": "admin_request_invalid"}, status_code=400)
        return await forward(request, body | {"method": methods[action]})

    async def forward(request, payload):
        try:
            envelope = BrokerRequest.model_validate(
                payload
                | {
                    "token": request.cookies.get(COOKIE, ""),
                    "csrf": request.headers.get("x-epm-admin-csrf", ""),
                }
            )
            result = await run_in_threadpool(call, envelope.model_dump())
            response = JSONResponse({key: value for key, value in result.items() if key != "token"})
            if envelope.method == "login":
                response.set_cookie(
                    COOKIE,
                    result["token"],
                    httponly=True,
                    samesite="strict",
                    secure=False,
                    path="/",
                    max_age=28800,
                )
                response.set_cookie(
                    CSRF_COOKIE,
                    result["csrf"],
                    httponly=True,
                    samesite="strict",
                    path="/",
                    max_age=28800,
                )
            if envelope.method == "logout":
                response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict")
                response.delete_cookie(CSRF_COOKIE, path="/", httponly=True, samesite="strict")
            return response
        except AdminError as error:
            return JSONResponse({"code": error.code}, status_code=error.status)
        except ValidationError:
            return JSONResponse({"code": "admin_request_invalid"}, status_code=400)
        except (OSError, ValueError) as _error:
            return JSONResponse({"code": "admin_broker_unavailable"}, status_code=503)

    return app

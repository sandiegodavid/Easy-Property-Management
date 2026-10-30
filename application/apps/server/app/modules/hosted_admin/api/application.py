"""Separate loopback-only Admin listener. Not mounted in the business application."""

import json
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from app.modules.hosted_admin.application.contracts import AdminError, BrokerRequest
from app.modules.hosted_admin.infrastructure.broker import MAX_FRAME
from app.modules.hosted_admin.api.sign_in import CSRF_COOKIE, sign_in_page
from app.modules.hosted_admin.api.console_page import console_page, console_route
from app.platform.api_errors import api_problem, register_api_error_handlers, validation_problem

COOKIE = "epm_private_admin"


def problem_response(problem):
    return JSONResponse({"detail": problem.detail}, status_code=problem.status_code)


def admin_problem(status, code):
    # Fixed prose only: neither validation inputs nor broker exception text is public.
    message = {
        400: "The administration request is invalid.",
        401: "Sign in to private administration.",
        403: "The administration request is not permitted.",
        404: "The administration record was not found.",
        409: "The administration request conflicts with the current state.",
        413: "Request content exceeds an allowed limit.",
        429: "Too many administration attempts. Try again later.",
        503: "Private administration is unavailable. Try again later.",
    }.get(status, "The administration request could not be completed.")
    return problem_response(api_problem(status, code, message))


def create_admin_app(origin, call, assets=None):
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
    assets = Path(assets) if assets else Path(__file__).resolve().parents[3] / "admin_build"
    register_api_error_handlers(app)

    @app.exception_handler(HTTPException)
    async def http_error(_request, error):
        return admin_problem(error.status_code, "admin_request_invalid")

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
            response = admin_problem(403, "admin_transport_denied")
        else:
            response = await next_handler(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "same-origin",
            }
        )
        return response

    @app.get("/")
    @app.get("/operators")
    @app.get("/operators/{instance}")
    @app.get("/operations")
    @app.get("/operations/{operation_id}")
    @app.get("/qualification")
    @app.get("/discrepancies")
    @app.get("/setups")
    @app.get("/setups/new")
    @app.get("/setups/{draft_id}")
    async def home(request: Request):
        if not console_route(request.url.path):
            return admin_problem(404, "admin_request_invalid")
        try:
            result = await run_in_threadpool(
                call,
                BrokerRequest(method="session", token=request.cookies.get(COOKIE, "")).model_dump(),
            )
            return console_page(result["identity"], request.cookies.get(CSRF_COOKIE, ""))
        except AdminError as error:
            if error.status == 503:
                return sign_in_page(
                    error="admin_broker_unavailable", status=503, return_to=request.url.path
                )
            return sign_in_page(return_to=request.url.path)
        except OSError:
            return sign_in_page(
                error="admin_broker_unavailable", status=503, return_to=request.url.path
            )

    @app.post("/sign-in")
    @app.post("/sign-out")
    async def native_form(request: Request):
        return_to = ["/"]
        raw = bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw) > MAX_FRAME:
                return admin_problem(413, "admin_request_too_large")
        try:
            if request.headers.get("content-type") != "application/x-www-form-urlencoded":
                raise ValueError()
            values = parse_qs(raw.decode(), strict_parsing=True, max_num_fields=2)
            key = "credential" if request.url.path == "/sign-in" else "csrf"
            return_to = values.pop("return_to", ["/"])
            if len(return_to) != 1 or not console_route(return_to[0]):
                raise ValueError()
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
            response = RedirectResponse(return_to[0], status_code=303)
            for name, value in ((COOKIE, result["token"]), (CSRF_COOKIE, result["csrf"])):
                response.set_cookie(
                    name, value, httponly=True, samesite="strict", path="/", max_age=28800
                )
            return response
        except AdminError as error:
            return sign_in_page(error=error.code, status=error.status, return_to=return_to[0])
        except ValidationError as error:
            return problem_response(validation_problem(error))
        except ValueError:
            return sign_in_page(error="admin_request_invalid", status=400)
        except OSError:
            return sign_in_page(
                error="admin_broker_unavailable", status=503, return_to=return_to[0]
            )

    @app.get("/session")
    async def session(request: Request):
        return await forward(request, {"method": "session"})

    @app.get("/admin-assets/{filename}")
    async def asset(filename: str, request: Request):
        if filename not in {"admin.js", "admin.css"}:
            return admin_problem(404, "admin_request_invalid")
        try:
            await run_in_threadpool(
                call,
                BrokerRequest(method="session", token=request.cookies.get(COOKIE, "")).model_dump(),
            )
        except AdminError as error:
            return admin_problem(error.status, error.code)
        except OSError:
            return admin_problem(503, "admin_broker_unavailable")
        if not (assets / filename).is_file():
            return admin_problem(503, "admin_console_assets_unavailable")
        return FileResponse(assets / filename)

    @app.get("/admin-api/operators/page/{offset}")
    async def directory(offset: int, request: Request):
        return await forward(request, {"method": "console_directory", "offset": offset})

    @app.get("/admin-api/operators/{instance}")
    async def operator_record(instance: str, request: Request):
        return await forward(request, {"method": "console_record", "instance": instance})

    @app.get("/admin-api/observations/{section}")
    async def host_observation(section: str, request: Request):
        return await forward(request, {"method": "console_observation", "section": section})

    @app.get("/admin-api/operators/{instance}/observations/{section}")
    async def instance_observation(instance: str, section: str, request: Request):
        return await forward(
            request, {"method": "console_observation", "section": section, "instance": instance}
        )

    @app.get("/admin-api/qualification")
    async def qualification(request: Request):
        return await forward(request, {"method": "console_qualification"})

    @app.get("/admin-api/setup-options")
    async def setup_options(request: Request):
        return await forward(request, {"method": "setup_options"})

    @app.get("/admin-api/operators/{instance}/recovery-handoff")
    async def recovery_handoff(instance: str, request: Request):
        return await forward(request, {"method": "recovery_handoff", "instance": instance})

    @app.get("/admin-api/operators/{instance}/source-status")
    async def source_status(instance: str, request: Request):
        return await forward(request, {"method": "source_status", "instance": instance})

    @app.get("/admin-api/setup-drafts")
    async def setup_list(request: Request):
        return await forward(request, {"method": "setup_list"})

    @app.get("/admin-api/setup-drafts/{draft_id}")
    async def setup_get(draft_id: str, request: Request):
        return await forward(request, {"method": "setup_get", "draft_id": draft_id})

    @app.get("/admin-api/setup-status/{draft_id}")
    async def setup_status(draft_id: str, request: Request):
        return await forward(request, {"method": "setup_status", "draft_id": draft_id})

    @app.get("/admin-api/operations")
    async def operations(request: Request):
        return await forward(request, {"method": "operation_list"})

    @app.get("/admin-api/operations/by-key/{operation_id}")
    @app.get("/admin-api/operations/{operation_id}")
    async def operation(operation_id: str, request: Request):
        return await forward(request, {"method": "operation", "operation_id": operation_id})

    @app.get("/admin-api/operation-details/{operation_id}")
    async def operation_details(operation_id: str, request: Request):
        return await forward(request, {"method": "console_operation", "operation_id": operation_id})

    @app.post("/{action}")
    async def command(action: str, request: Request):
        methods = {
            "login": "login",
            "logout": "logout",
            "reauthenticate": "reauthenticate",
            "commands": "command",
            "lookup": "lookup",
            "source-status": "source_status",
            "operation": "operation",
            "resume": "resume",
            "cancel": "cancel",
            "setup-command": "setup_command",
            "recovery-check": "recovery_check",
            "recovery-acknowledge": "recovery_acknowledge",
        }
        if action not in methods or request.headers.get("content-type") != "application/json":
            return admin_problem(400, "admin_request_invalid")
        raw = bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw) > MAX_FRAME:
                return admin_problem(413, "admin_request_too_large")
        try:
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) - {
                "credential",
                "command",
                "operation_id",
                "instance",
                "expected_revision",
                "setup",
                "recovery",
            }:
                raise ValueError()
        except ValueError:
            return admin_problem(400, "admin_request_invalid")
        return await forward(request, body | {"method": methods[action]})

    async def forward(request, payload):
        try:
            envelope = BrokerRequest.model_validate(
                payload
                | {
                    "token": request.cookies.get(COOKIE, ""),
                    "csrf": request.cookies.get(CSRF_COOKIE, "")
                    if request.method == "GET"
                    else request.headers.get("x-epm-admin-csrf", ""),
                }
            )
            result = await run_in_threadpool(call, envelope.model_dump())
            response = JSONResponse(
                {key: value for key, value in result.items() if key != "token"},
                status_code=202
                if envelope.method in {"resume", "cancel"}
                or (envelope.setup and envelope.setup.action == "create")
                else 200,
            )
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
            return admin_problem(error.status, error.code)
        except ValidationError as error:
            return problem_response(validation_problem(error))
        except (OSError, ValueError) as _error:
            return admin_problem(503, "admin_broker_unavailable")

    return app

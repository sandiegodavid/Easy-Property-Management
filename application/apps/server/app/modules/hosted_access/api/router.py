"""Explicit session commands; tokens are returned only as protected cookies."""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict
from uuid import UUID
from starlette.responses import JSONResponse, Response

from app.modules.hosted_access.application.service import (
    HostedAccessService,
    session_csrf,
    token_hash,
)
from app.platform.api_errors import api_problem

SESSION_COOKIE = "__Host-epm_session"


class SessionGrantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csrfToken: str
    expiresAt: AwareDatetime


class SessionResponse(SessionGrantResponse):
    operatorId: UUID
    workspaceId: UUID
    identityBinding: str
    demoExpiresAt: AwareDatetime
    administratorContact: str
    capabilities: list[str]


def build_session_router(service: HostedAccessService | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/hosted")

    def active_service() -> HostedAccessService:
        if service is None:
            raise api_problem(404, "hosted_mode_required", "Hosted sessions are not enabled.")
        return service

    @router.post("/session", operation_id="beginHostedSession", response_model=SessionGrantResponse)
    def begin(request: Request) -> Response:
        grant = active_service().begin_session(request.state.hosted_identity)
        response = JSONResponse(
            {"csrfToken": grant.csrf, "expiresAt": grant.expires_at.isoformat()}
        )
        response.set_cookie(
            SESSION_COOKIE,
            grant.token,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=max(0, int((grant.expires_at - datetime.now(UTC)).total_seconds())),
        )
        return response

    @router.get("/session", operation_id="getHostedSession", response_model=SessionResponse)
    def current(request: Request) -> dict:
        deployment = active_service().deployment
        actor = request.state.hosted_actor
        identity = request.state.hosted_identity
        return {
            "operatorId": actor.operator_id,
            "workspaceId": actor.workspace_id,
            "expiresAt": actor.expires_at.isoformat(),
            "identityBinding": token_hash(identity.issuer + "\0" + identity.subject),
            "demoExpiresAt": deployment.expires_at.isoformat(),
            "administratorContact": deployment.administrator_contact,
            "capabilities": sorted(deployment.capabilities),
            "csrfToken": session_csrf(request.cookies[SESSION_COOKIE]),
        }

    @router.delete("/session", operation_id="endHostedSession", status_code=204)
    def end(request: Request) -> Response:
        active_service().logout(request.state.hosted_actor, request.state.hosted_identity)
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="lax", path="/")
        return response

    @router.delete("/session/all", operation_id="endAllHostedSessions", status_code=204)
    def end_all(request: Request) -> Response:
        active_service().logout(
            request.state.hosted_actor, request.state.hosted_identity, all_devices=True
        )
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="lax", path="/")
        return response

    return router

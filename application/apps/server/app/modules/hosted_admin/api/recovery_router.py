"""Independent Admin Control Recovery HTTP router (/api/admin/recovery/*, H05.6 / D5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_admin.infrastructure.admin_recovery import (
    AdminControlRecoveryService,
    AdminRecoveryDenied,
    AdminRecoveryNotFound,
)
from app.modules.hosted_recovery.domain.models import HostedRecoveryError
from app.platform.hosted_contracts.authority import AdminRecoveryAuthority, ObservationQuery
from app.platform.hosted_contracts.operations import SemanticConflict
from app.platform.hosted_contracts.values import (
    CanonicalId,
    Contract,
    DeploymentScope,
    IdempotencyKey,
    RequestHash,
)

BodyReader = Callable[[Request], Awaitable[dict[str, Any]]]
RecoveryAuthenticator = Callable[[Request, bool, RequestHash | None], AdminRecoveryAuthority]


class ControlPreviewBody(Contract):
    point_id: CanonicalId


class ControlConfirmBody(Contract):
    point_id: CanonicalId
    preview_id: CanonicalId
    idempotency_key: IdempotencyKey
    confirmed_request_hash: RequestHash


class ControlAcceptBody(Contract):
    operation_id: CanonicalId


def _error_response(error: Exception) -> JSONResponse:
    if isinstance(error, ProviderUnavailable):
        return JSONResponse(
            {"code": "unavailable", "message": "Service unavailable."}, status_code=503
        )
    if isinstance(error, ProviderDenied):
        return JSONResponse(
            {"code": "unauthorized", "message": "Authentication required."}, status_code=401
        )
    if isinstance(error, AdminRecoveryNotFound):
        return JSONResponse({"code": error.code, "message": str(error)}, status_code=404)
    if isinstance(error, SemanticConflict):
        return JSONResponse({"code": error.code, "message": str(error)}, status_code=409)
    if isinstance(error, (AdminRecoveryDenied, HostedRecoveryError)):
        return JSONResponse({"code": error.code, "message": str(error)}, status_code=403)
    if isinstance(error, ValidationError):
        return JSONResponse(
            {"code": "invalid_request", "message": "Request validation failed."}, status_code=400
        )
    raise error


def build_admin_recovery_router(
    recovery: AdminControlRecoveryService,
    *,
    authenticate_recovery: RecoveryAuthenticator,
    read_body: BodyReader,
) -> APIRouter:
    """Expose /api/admin/recovery/* independent of main admin.sqlite."""
    router = APIRouter()

    @router.get("/api/admin/recovery/status")
    async def recovery_status(request: Request) -> JSONResponse:
        try:
            actor = await run_in_threadpool(authenticate_recovery, request, False, None)
            mode = await run_in_threadpool(recovery.detect_admin_mode)
            page = await run_in_threadpool(
                recovery.observe,
                actor,
                ObservationQuery(
                    deployment_id=recovery.deployment_id,
                    scope=DeploymentScope(),
                    limit=50,
                ),
            )
            return JSONResponse(
                {
                    "mode": mode.mode,
                    "reason": mode.reason,
                    "activeAdminResourceRef": mode.active_admin_resource_ref,
                    "catalog": page.model_dump(mode="json"),
                }
            )
        except Exception as error:
            return _error_response(error)

    @router.get("/api/admin/recovery/points")
    async def list_points(request: Request) -> JSONResponse:
        try:
            actor = await run_in_threadpool(authenticate_recovery, request, False, None)
            page = await run_in_threadpool(
                recovery.observe,
                actor,
                ObservationQuery(
                    deployment_id=recovery.deployment_id,
                    scope=DeploymentScope(),
                    limit=50,
                ),
            )
            return JSONResponse(page.model_dump(mode="json"))
        except Exception as error:
            return _error_response(error)

    @router.post("/api/admin/recovery/preview")
    async def preview_restore(request: Request) -> JSONResponse:
        try:
            actor = await run_in_threadpool(authenticate_recovery, request, True, None)
            data = await read_body(request)
            parsed = ControlPreviewBody.model_validate(data)
            preview = await run_in_threadpool(
                recovery.preview_control_restore, actor, point_id=parsed.point_id
            )
            return JSONResponse(
                {
                    "previewId": preview.preview_id,
                    "pointId": preview.point_id,
                    "deploymentId": preview.deployment_id,
                    "sourceGeneration": preview.source_generation,
                    "selectedCapturedAt": preview.selected_captured_at,
                    "selectedVerifiedAt": preview.selected_verified_at,
                    "exactRequestHash": preview.exact_request_hash,
                    "expiresAt": preview.expires_at,
                }
            )
        except Exception as error:
            return _error_response(error)

    @router.post("/api/admin/recovery/confirm")
    async def confirm_restore(request: Request) -> JSONResponse:
        try:
            data = await read_body(request)
            parsed = ControlConfirmBody.model_validate(data)
            actor = await run_in_threadpool(
                authenticate_recovery, request, True, parsed.confirmed_request_hash
            )
            outcome = await run_in_threadpool(
                recovery.confirm_control_restore,
                actor,
                point_id=parsed.point_id,
                preview_id=parsed.preview_id,
                idempotency_key=parsed.idempotency_key,
            )
            status_code = 200 if outcome.state.value == "succeeded" else 500
            return JSONResponse(outcome.model_dump(mode="json"), status_code=status_code)
        except Exception as error:
            return _error_response(error)

    @router.post("/api/admin/recovery/accept")
    async def accept_restore(request: Request) -> JSONResponse:
        try:
            actor = await run_in_threadpool(authenticate_recovery, request, True, None)
            data = await read_body(request)
            parsed = ControlAcceptBody.model_validate(data)
            accepted = await run_in_threadpool(
                recovery.accept_control_restore, actor, operation_id=parsed.operation_id
            )
            return JSONResponse(accepted)
        except Exception as error:
            return _error_response(error)

    @router.post("/api/admin/recovery/reconstruct")
    async def reconstruct_catalog(request: Request) -> JSONResponse:
        try:
            actor = await run_in_threadpool(authenticate_recovery, request, True, None)
            result = await run_in_threadpool(recovery.reconstruct_catalog, actor=actor)
            return JSONResponse(
                {
                    "scannedManifests": result.scanned_manifests,
                    "importedPoints": result.imported_points,
                    "skippedPoints": result.skipped_points,
                }
            )
        except Exception as error:
            return _error_response(error)

    return router

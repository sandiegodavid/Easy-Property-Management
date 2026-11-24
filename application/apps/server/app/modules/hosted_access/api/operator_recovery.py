"""Authenticated Operator Recovery API (/api/hosted/recovery/*) for normal & recovery modes."""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field, SecretStr, ValidationError

from app.modules.host_agent.application.auth_routes import IdentityCookiePolicy
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.application.ui_contracts import Recovery
from app.modules.hosted_access.infrastructure.source_sessions import SessionExpired
from app.modules.hosted_recovery.domain.models import HostedRecoveryError
from app.modules.workspace.infrastructure.hosted_recovery import (
    HostedWorkspaceRecoveryService,
    RestoreDeniedError,
    RestoreNotFoundError,
)
from app.platform.hosted_contracts.authority import (
    ObservationQuery,
    OperatorAuthority,
    OperatorRestoreAuthority,
)
from app.platform.hosted_contracts.operations import SemanticConflict
from app.platform.hosted_contracts.ui_states import (
    ActionState,
    Gate,
    Section,
    UIAction,
)
from app.platform.hosted_contracts.values import CanonicalId, Contract, IdempotencyKey

from app.platform.hosted_security_headers import API_SECURITY_HEADERS

RECOVERY_ROUTE_PREFIX = "/api/hosted/recovery/"
HEADERS = API_SECURITY_HEADERS


class PreviewRequest(Contract):
    point_id: CanonicalId


class ConfirmRestoreRequest(Contract):
    point_id: CanonicalId
    preview_id: CanonicalId
    idempotency_key: IdempotencyKey
    recent_auth_grant: str = Field(min_length=16, max_length=12000)


class AcceptRestoreRequest(Contract):
    operation_id: CanonicalId


@dataclass(frozen=True)
class OperatorRecoveryInputs:
    origin: str
    recovery: HostedWorkspaceRecoveryService
    recovery_mode: bool = False


def _read_cookie_and_origin(
    request: Request, *, origin: str, cookie_name: str, require_csrf: bool
) -> tuple[str, str | None]:
    if (
        str(request.base_url).rstrip("/") != origin
        or request.scope.get("raw_path") != request.url.path.encode("ascii")
        or request.url.query
        or any(
            len(request.headers.getlist(key)) > 1
            for key in ("host", "origin", "cookie", "x-epm-csrf", "content-type", "content-length")
        )
    ):
        raise PermissionError("origin_denied")
    if require_csrf and request.headers.get("origin") != origin:
        raise PermissionError("origin_denied")
    cookies = [
        entry.strip().split("=", 1)
        for entry in request.headers.get("cookie", "").split(";")
        if "=" in entry
    ]
    values = [value for key, value in cookies if key == cookie_name]
    if len(values) != 1:
        raise ProviderDenied()
    csrf = request.headers.get("x-epm-csrf") if require_csrf else None
    if require_csrf and not csrf:
        raise ProviderDenied()
    return values[0], csrf


MAX_RECOVERY_JSON_BYTES = 20_000


async def _read_bounded_json(request: Request) -> dict[str, object]:
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise ValueError("invalid_content_type")
    raw = bytearray()
    async with asyncio.timeout(10):
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_RECOVERY_JSON_BYTES:
                raise ValueError("payload_too_large")

    def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = item
        return result

    try:
        parsed = json.loads(raw, object_pairs_hook=_unique)
    except ValueError, RecursionError:
        raise ValueError("invalid_json") from None
    if not isinstance(parsed, dict):
        raise ValueError("invalid_json_object")
    return parsed


def _auth_error_response(error: Exception) -> JSONResponse:
    if isinstance(error, PermissionError):
        return JSONResponse({"state": "rejected"}, status_code=403, headers=HEADERS)
    if isinstance(error, ProviderUnavailable):
        return JSONResponse({"state": "unavailable"}, status_code=503, headers=HEADERS)
    if isinstance(error, SessionExpired):
        return JSONResponse({"state": "renewal_required"}, status_code=401, headers=HEADERS)
    if isinstance(error, ProviderDenied):
        return JSONResponse({"state": "signed_out"}, status_code=401, headers=HEADERS)
    if isinstance(error, RestoreNotFoundError):
        return JSONResponse({"error": {"code": error.code}}, status_code=404, headers=HEADERS)
    if isinstance(error, SemanticConflict):
        return JSONResponse({"error": {"code": error.code}}, status_code=409, headers=HEADERS)
    if isinstance(error, (RestoreDeniedError, HostedRecoveryError)):
        return JSONResponse({"error": {"code": error.code}}, status_code=403, headers=HEADERS)
    return JSONResponse({"state": "unavailable"}, status_code=503, headers=HEADERS)


def _operator_authority(sessions) -> OperatorAuthority:
    binding = sessions.destination.binding()
    return OperatorAuthority(
        deployment_id=binding.deployment_id,
        scope=binding.scope,
        identity_proof_ref=f"session:{binding.scope.operator_id}",
    )


def operator_recovery_router(sessions, inputs: OperatorRecoveryInputs) -> APIRouter:
    """Expose /api/hosted/recovery/* routes for normal and minimal recovery modes."""
    router = APIRouter(include_in_schema=False)
    cookie_name = IdentityCookiePolicy().operator
    recovery = inputs.recovery

    @router.get("/api/hosted/recovery/status")
    def recovery_status(request: Request) -> JSONResponse:
        try:
            cookie, _ = _read_cookie_and_origin(
                request, origin=inputs.origin, cookie_name=cookie_name, require_csrf=False
            )
            sessions.authorize_with_restore(cookie, csrf=None, write=False)
            actor = _operator_authority(sessions)
        except Exception as error:
            return _auth_error_response(error)

        startup = recovery.detect_runtime_mode(force_recovery_mode=inputs.recovery_mode)
        mode: Literal["normal", "recovery"] = (
            "recovery" if (inputs.recovery_mode or startup.mode == "recovery") else "normal"
        )
        page = recovery.observe(
            actor,
            ObservationQuery(
                deployment_id=actor.deployment_id,
                scope=actor.scope,
                limit=50,
            ),
        )
        has_points = len(page.items) > 0
        gates = (
            Gate(name="current_identity", state="passed", evidence_ref=actor.identity_proof_ref),
            Gate(
                name="qualified_engine",
                state="passed",
                evidence_ref="engine:epm-hosted-recovery-v1",
            ),
            Gate(
                name="verified_catalog",
                state="passed" if has_points else "failed",
                evidence_ref=f"point:{page.items[0].resource_id}" if has_points else None,
            ),
            Gate(name="runtime_ready", state="passed", evidence_ref=f"mode:{mode}"),
            Gate(name="strong_step_up", state="pending"),
        )
        state: Literal[
            "unavailable", "choose_point", "confirm", "running", "outcome_unknown", "completed"
        ] = "choose_point" if has_points else "unavailable"
        catalog_section = Section(
            state="ready",
            data=page,
            freshness=page.freshness,
        )
        contract = Recovery(
            scope=actor.scope,
            mode=mode,
            state=state,
            availability_reason=None if has_points else "no_verified_points",
            gates=gates,
            catalog=catalog_section,
            selected_point_id=page.items[0].resource_id if has_points else None,
            actions=(
                ActionState(action=UIAction.LIST_POINTS, enabled=True),
                ActionState(action=UIAction.PREVIEW_RESTORE, enabled=has_points),
            ),
        )
        payload = contract.model_dump(mode="json")
        snap = recovery.read_protection_status()
        payload["protection"] = {
            "state": snap.protection_state,
            "lastPointId": snap.last_point_id,
            "lastCapturedAt": snap.last_captured_at,
            "lastVerifiedAt": snap.last_verified_at,
            "lastCheckedAt": snap.last_checked_at,
            "dirtySince": snap.dirty_since,
            "lastErrorCode": snap.last_error_code,
        }
        payload["startup"] = {
            "mode": mode,
            "reason": startup.reason,
            "interruptedRestoreId": startup.interrupted_restore_id,
            "pendingAcceptanceId": startup.pending_acceptance_id,
        }
        return JSONResponse(payload, headers=HEADERS)

    @router.get("/api/hosted/recovery/points")
    def list_points(request: Request) -> JSONResponse:
        try:
            cookie, _ = _read_cookie_and_origin(
                request, origin=inputs.origin, cookie_name=cookie_name, require_csrf=False
            )
            sessions.authorize_with_restore(cookie, csrf=None, write=False)
            actor = _operator_authority(sessions)
        except Exception as error:
            return _auth_error_response(error)

        page = recovery.observe(
            actor,
            ObservationQuery(
                deployment_id=actor.deployment_id,
                scope=actor.scope,
                limit=50,
            ),
        )
        return JSONResponse(page.model_dump(mode="json"), headers=HEADERS)

    @router.post("/api/hosted/recovery/preview")
    async def preview_restore(request: Request) -> JSONResponse:
        try:
            cookie, csrf = _read_cookie_and_origin(
                request, origin=inputs.origin, cookie_name=cookie_name, require_csrf=True
            )
            sessions.authorize_with_restore(cookie, csrf=csrf, write=True)
            actor = _operator_authority(sessions)
        except Exception as error:
            return _auth_error_response(error)

        try:
            raw = await _read_bounded_json(request)
            body = PreviewRequest.model_validate(raw)
        except ValidationError, ValueError, TimeoutError:
            return JSONResponse(
                {"error": {"code": "invalid_preview_request"}}, status_code=400, headers=HEADERS
            )

        try:
            preview = recovery.preview_restore(actor, point_id=body.point_id)
            challenge_id, challenge_deadline = sessions.begin_recent(
                cookie, csrf, preview.exact_request_hash
            )
        except Exception as error:
            return _auth_error_response(error)

        return JSONResponse(
            {
                "previewId": preview.preview_id,
                "pointId": preview.point_id,
                "workspaceId": preview.workspace_id,
                "sourceEpoch": preview.source_epoch,
                "sourceGeneration": preview.source_generation,
                "currentBusinessRevision": preview.current_business_revision,
                "selectedCapturedAt": preview.selected_captured_at,
                "selectedVerifiedAt": preview.selected_verified_at,
                "exactRequestHash": preview.exact_request_hash,
                "expiresAt": preview.expires_at,
                "recoveryMode": preview.recovery_mode,
                "stepUpChallengeId": challenge_id,
                "stepUpExpiresAt": challenge_deadline,
            },
            headers=HEADERS,
        )

    @router.post("/api/hosted/recovery/confirm")
    async def confirm_restore(request: Request) -> JSONResponse:
        try:
            cookie, csrf = _read_cookie_and_origin(
                request, origin=inputs.origin, cookie_name=cookie_name, require_csrf=True
            )
        except Exception as error:
            return _auth_error_response(error)

        try:
            raw = await _read_bounded_json(request)
            body = ConfirmRestoreRequest.model_validate(raw)
        except ValidationError, ValueError, TimeoutError:
            return JSONResponse(
                {"error": {"code": "invalid_confirm_request"}}, status_code=400, headers=HEADERS
            )

        try:
            sessions.authorize_with_restore(cookie, csrf=csrf, write=True)
            replayed = recovery.lookup_idempotent_restore(
                idempotency_key=body.idempotency_key,
                point_id=body.point_id,
                preview_id=body.preview_id,
            )
            if replayed is not None:
                status_code = 200 if replayed.state.value == "succeeded" else 500
                return JSONResponse(
                    replayed.model_dump(mode="json"), status_code=status_code, headers=HEADERS
                )
        except Exception as error:
            return _auth_error_response(error)

        preview = recovery.get_preview(body.preview_id)
        if preview is None or preview.point_id != body.point_id:
            return JSONResponse(
                {"error": {"code": RestoreDeniedError.code}}, status_code=403, headers=HEADERS
            )

        try:
            with sessions.mutation() as conn:
                sessions.consume_recent(
                    conn,
                    cookie,
                    csrf,
                    preview.exact_request_hash,
                    SecretStr(body.recent_auth_grant),
                    require_mfa=False,
                )
            binding = sessions.destination.binding()
            now = recovery.clock()
            restore_actor = OperatorRestoreAuthority(
                deployment_id=binding.deployment_id,
                scope=binding.scope,
                identity_proof_ref=f"session:{binding.scope.operator_id}",
                step_up_ref=f"stepup:{body.preview_id}",
                step_up_at=now,
                confirmed_request_hash=preview.exact_request_hash,
            )
            outcome = recovery.confirm_restore(
                restore_actor,
                point_id=body.point_id,
                preview_id=body.preview_id,
                idempotency_key=body.idempotency_key,
                authorized_subject=f"operator:{binding.scope.operator_id}",
            )
        except Exception as error:
            return _auth_error_response(error)

        status_code = 200 if outcome.state.value == "succeeded" else 500
        return JSONResponse(
            outcome.model_dump(mode="json"), status_code=status_code, headers=HEADERS
        )

    @router.get("/api/hosted/recovery/operations/{operation_id}")
    def read_operation(operation_id: str, request: Request) -> JSONResponse:
        try:
            cookie, _ = _read_cookie_and_origin(
                request, origin=inputs.origin, cookie_name=cookie_name, require_csrf=False
            )
            sessions.authorize_with_restore(cookie, csrf=None, write=False)
        except Exception as error:
            return _auth_error_response(error)

        detail = recovery.restore_operation_detail(operation_id)
        if detail is None:
            return JSONResponse(
                {"error": {"code": "restore_operation_not_found"}}, status_code=404, headers=HEADERS
            )
        return JSONResponse(
            {
                "operationId": detail.operation_id,
                "pointId": detail.point_id,
                "previewId": detail.preview_id,
                "phase": detail.phase,
                "state": detail.state,
                "priorBusinessRef": detail.prior_business_ref,
                "priorTreeKind": detail.prior_tree_kind,
                "targetBusinessRef": detail.target_business_ref,
                "newSourceGeneration": detail.new_source_generation,
                "newAccessEpoch": detail.new_access_epoch,
                "startedAt": detail.started_at,
                "updatedAt": detail.updated_at,
                "acceptedAt": detail.accepted_at,
                "errorCode": detail.error_code,
            },
            headers=HEADERS,
        )

    @router.post("/api/hosted/recovery/accept")
    async def accept_restore(request: Request) -> JSONResponse:
        try:
            cookie, csrf = _read_cookie_and_origin(
                request, origin=inputs.origin, cookie_name=cookie_name, require_csrf=True
            )
            sessions.authorize_with_restore(cookie, csrf=csrf, write=True)
            actor = _operator_authority(sessions)
        except Exception as error:
            return _auth_error_response(error)

        try:
            raw = await _read_bounded_json(request)
            body = AcceptRestoreRequest.model_validate(raw)
        except ValidationError, ValueError, TimeoutError:
            return JSONResponse(
                {"error": {"code": "invalid_accept_request"}}, status_code=400, headers=HEADERS
            )

        try:
            detail = recovery.accept_restore(actor, operation_id=body.operation_id)
        except Exception as error:
            return _auth_error_response(error)

        return JSONResponse(
            {
                "operationId": detail.operation_id,
                "phase": detail.phase,
                "acceptedAt": detail.accepted_at,
            },
            headers=HEADERS,
        )

    @router.post("/api/hosted/recovery/reconstruct")
    def reconstruct_catalog(request: Request) -> JSONResponse:
        try:
            cookie, csrf = _read_cookie_and_origin(
                request, origin=inputs.origin, cookie_name=cookie_name, require_csrf=True
            )
            sessions.authorize_with_restore(cookie, csrf=csrf, write=True)
            actor = _operator_authority(sessions)
            result = recovery.reconstruct_catalog(actor)
        except Exception as error:
            return _auth_error_response(error)

        return JSONResponse(
            {
                "scannedManifests": result.scanned_manifests,
                "importedPoints": result.imported_points,
                "skippedPoints": result.skipped_points,
            },
            headers=HEADERS,
        )

    return router

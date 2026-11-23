"""Admin-lite HTTP API routes mounted on the protected Admin origin."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Awaitable, Callable
from hmac import compare_digest
from typing import Any
from uuid import UUID, uuid4, uuid5

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.modules.host_agent.application.auth_routes import IdentityCookiePolicy
from app.modules.hosted_access.application.managed_provider import ProviderDenied
from app.modules.hosted_access.infrastructure.admin_sessions import AdminSessions
from app.modules.hosted_admin.application.errors import AdminControlError
from app.modules.hosted_admin.application.pilot_contracts import (
    AdminCommand,
    AdmissionCommitment,
    CreateAssignment,
    RefreshSource,
    ReissueInvitation,
    ResourceCeiling,
)
from app.modules.hosted_admin.application.ui_contracts import AdminFilters
from app.modules.hosted_admin.infrastructure.admin_control import AdminControlService
from app.modules.hosted_admin.infrastructure.capacity_store import load_capacity_state
from app.modules.hosted_admin.infrastructure.policy_bootstrap import (
    FREE_V1_PLAN_CODE,
    FREE_V1_POLICY_VERSION,
)
from app.platform.hosted_contracts.authority import AdminAuthority, ObservationQuery
from app.platform.hosted_contracts.operations import CommandIntent, SemanticConflict
from app.platform.hosted_contracts.reads import ContinuationCursor
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import DeploymentScope, WorkspaceScope

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 50
MAX_CURSOR_BYTES = 4096
ADMIN_HTTP_NAMESPACE = UUID("6b92b5c4-0b8d-5f11-94c8-2a7e4a712301")

CookieReader = Callable[[Request, str], str]
BodyReader = Callable[[Request], Awaitable[dict[str, Any]]]


def _canonical_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise AdminControlError(
            "invalid_identifier", "Invalid canonical ID.", status=400
        ) from error
    if str(parsed) != value:
        raise AdminControlError("invalid_identifier", "Invalid canonical ID.", status=400)
    return value


def _encode_cursor(cursor: ContinuationCursor) -> str:
    raw = cursor.model_dump_json().encode("utf-8")
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(token: str) -> ContinuationCursor:
    if not token or len(token) > MAX_CURSOR_BYTES:
        raise AdminControlError("invalid_cursor", "Invalid pagination cursor.", status=400)
    padding = "=" * (-len(token) % 4)
    try:
        raw = urlsafe_b64decode(token + padding)
        return ContinuationCursor.model_validate_json(raw)
    except (ValueError, ValidationError) as error:
        raise AdminControlError(
            "invalid_cursor", "Invalid pagination cursor.", status=400
        ) from error


def _error_response(error: Exception) -> JSONResponse:
    if isinstance(error, AdminControlError):
        body: dict[str, Any] = {"code": error.code, "message": str(error)}
        limiting = getattr(error, "limiting_resources", ())
        if limiting:
            body["limitingResources"] = list(limiting)
        return JSONResponse(body, status_code=error.status)
    if isinstance(error, SemanticConflict):
        return JSONResponse({"code": error.code, "message": str(error)}, status_code=409)
    if isinstance(error, ValidationError):
        return JSONResponse(
            {"code": "invalid_request", "message": "Request validation failed."},
            status_code=400,
        )
    raise error


def _bootstrap_payload(control: AdminControlService) -> dict[str, Any]:
    with control.engine.connect() as connection:
        meta = (
            connection.execute(
                text(
                    "SELECT deployment_id, public_base_domain, login_origin, registry_generation "
                    "FROM main.control_meta WHERE id = 1"
                )
            )
            .mappings()
            .one_or_none()
        )
        if meta is None:
            raise AdminControlError(
                "deployment_unbound", "Deployment metadata is unavailable.", status=503
            )
        policy = (
            connection.execute(
                text(
                    "SELECT policy_id, plan_code, policy_version, usable_bytes, "
                    "backup_interval_seconds, retained_nightly_points, keep_warm "
                    "FROM main.storage_policies "
                    "WHERE plan_code = :plan AND policy_version = :ver"
                ),
                {"plan": FREE_V1_PLAN_CODE, "ver": FREE_V1_POLICY_VERSION},
            )
            .mappings()
            .one_or_none()
        )
        releases = (
            connection.execute(
                text(
                    "SELECT release_id, artifact_ref, artifact_digest, qualified_at "
                    "FROM main.qualified_releases "
                    "WHERE component = 'operator' AND state = 'qualified' "
                    "ORDER BY qualified_at DESC, release_id ASC"
                )
            )
            .mappings()
            .all()
        )
        capacity_state = load_capacity_state(connection)

    commitment_payload = None
    capacity_summary: dict[str, Any] = {"available": False}
    if capacity_state is not None:
        budget = capacity_state.free_budget
        commitment = AdmissionCommitment(
            warm_memory_bytes=budget.memory_bytes,
            cpu_millis=budget.cpu_millicores,
            workspace=ResourceCeiling(
                bytes=budget.trees.workspace.byte_ceiling,
                inodes=budget.trees.workspace.inode_ceiling,
            ),
            control=ResourceCeiling(
                bytes=budget.trees.control.byte_ceiling,
                inodes=budget.trees.control.inode_ceiling,
            ),
            scratch=ResourceCeiling(
                bytes=budget.trees.scratch.byte_ceiling,
                inodes=budget.trees.scratch.inode_ceiling,
            ),
        )
        commitment_payload = commitment.model_dump(mode="json")
        capacity_summary = {
            "available": capacity_state.snapshot.complete,
            "profileRef": capacity_state.profile.reference,
            "profileRevision": capacity_state.profile.revision,
            "snapshotRevision": capacity_state.snapshot.revision,
            "observedAt": capacity_state.snapshot.observed_at,
            "commitmentCount": len(capacity_state.snapshot.commitments),
        }

    return {
        "deploymentId": meta["deployment_id"],
        "publicBaseDomain": meta["public_base_domain"],
        "loginOrigin": meta["login_origin"],
        "registryGeneration": meta["registry_generation"],
        "freePolicy": dict(policy) if policy is not None else None,
        "qualifiedOperatorReleases": [dict(row) for row in releases],
        "admissionCommitment": commitment_payload,
        "capacity": capacity_summary,
    }


def _workspace_context(control: AdminControlService, operator_id: str) -> tuple[str, str, int, int]:
    with control.engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT o.workspace_id, o.revision, o.access_epoch, "
                    "cd.component_deployment_id "
                    "FROM main.operators o "
                    "JOIN main.component_deployments cd "
                    "  ON cd.operator_id = o.operator_id AND cd.component = 'operator' "
                    "WHERE o.operator_id = :id"
                ),
                {"id": operator_id},
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        raise AdminControlError("operator_not_found", "Operator was not found.", status=404)
    return (
        row["workspace_id"],
        row["component_deployment_id"],
        row["revision"],
        row["access_epoch"],
    )


class _AdminLiteHandlers:
    def __init__(
        self,
        control: AdminControlService,
        sessions: AdminSessions,
        *,
        read_cookie: CookieReader,
        read_body: BodyReader,
    ) -> None:
        self.control = control
        self.sessions = sessions
        self.read_cookie = read_cookie
        self.read_body = read_body
        self.cookies = IdentityCookiePolicy()

    def _authenticate(self, request: Request, *, write: bool, sensitive: bool) -> AdminAuthority:
        admin_cookie = self.read_cookie(request, self.cookies.admin)
        session = self.sessions.authenticate(admin_cookie, sensitive=sensitive)
        if write:
            csrf_header = request.headers.get("x-csrf-token")
            if not csrf_header or not compare_digest(
                csrf_header, self.sessions.csrf_token(admin_cookie)
            ):
                raise ProviderDenied()
        with self.control.engine.connect() as connection:
            deployment_id = connection.execute(
                text("SELECT deployment_id FROM main.control_meta WHERE id = 1")
            ).scalar_one_or_none()
        if deployment_id is None:
            raise AdminControlError(
                "deployment_unbound", "Deployment metadata is unavailable.", status=503
            )
        return AdminAuthority(
            deployment_id=deployment_id,
            principal_id=session.principal_id,
            identity_proof_ref=f"admin-session:{session.managed_session_id}",
            mfa_verified_at=session.mfa_verified_at,
        )

    def bootstrap(self, request: Request) -> JSONResponse:
        try:
            self._authenticate(request, write=False, sensitive=False)
            return JSONResponse(_bootstrap_payload(self.control))
        except (AdminControlError, SemanticConflict, ValidationError) as error:
            return _error_response(error)

    def list_operators(self, request: Request) -> JSONResponse:
        try:
            actor = self._authenticate(request, write=False, sensitive=False)
            raw_limit = request.query_params.get("limit")
            if raw_limit is None:
                limit = DEFAULT_PAGE_LIMIT
            elif (
                raw_limit.isascii()
                and raw_limit.isdigit()
                and 1 <= int(raw_limit) <= MAX_PAGE_LIMIT
            ):
                limit = int(raw_limit)
            else:
                raise AdminControlError("invalid_limit", "Limit must be 1..50.", status=400)
            raw_cursor = request.query_params.get("cursor")
            cursor = _decode_cursor(raw_cursor) if raw_cursor else None
            filters = AdminFilters(
                search=request.query_params.get("search", ""),
                setup_state=request.query_params.get("setup_state", "all"),
                access_state=request.query_params.get("access_state", "all"),
            )
            query = ObservationQuery(
                deployment_id=actor.deployment_id,
                scope=DeploymentScope(),
                limit=limit,
                cursor=cursor,
            )
            result = self.control.list_operators(actor, query, filters)
            payload = result.model_dump(mode="json")
            page = result.directory.data
            payload["nextCursor"] = (
                _encode_cursor(page.continuation)
                if page is not None and page.continuation is not None
                else None
            )
            return JSONResponse(payload)
        except (AdminControlError, SemanticConflict, ValidationError) as error:
            return _error_response(error)

    async def create_operator(self, request: Request) -> JSONResponse:
        try:
            actor = await run_in_threadpool(self._authenticate, request, write=True, sensitive=True)
            data = await self.read_body(request)
            idempotency_key = data.get("idempotencyKey")
            expected_revision = data.get("expectedRevision")
            if not isinstance(idempotency_key, str) or type(expected_revision) is not int:
                raise AdminControlError(
                    "invalid_request",
                    "idempotencyKey and expectedRevision are required.",
                    status=400,
                )
            operator_id = data.get("operatorId") or str(
                uuid5(ADMIN_HTTP_NAMESPACE, f"{actor.deployment_id}:{idempotency_key}:operator")
            )
            workspace_id = data.get("workspaceId") or str(
                uuid5(ADMIN_HTTP_NAMESPACE, f"{actor.deployment_id}:{idempotency_key}:workspace")
            )
            payload = CreateAssignment(
                operator_id=operator_id,
                workspace_id=workspace_id,
                display_name=data.get("displayName", ""),
                email=data.get("email", ""),
                slug=data.get("slug", ""),
                support_contact=data.get("supportContact", ""),
                release_id=data.get("releaseId", ""),
                policy_id=data.get("policyId", ""),
                admission_commitment=AdmissionCommitment.model_validate(
                    data.get("admissionCommitment")
                ),
                initial_data=data.get("initialData", "empty"),
                seed_bundle=data.get("seedBundle"),
            )
            intent = CommandIntent[CreateAssignment](
                deployment_id=actor.deployment_id,
                scope=DeploymentScope(),
                kind="create_assignment",
                expected_revision=expected_revision,
                access_epoch=1,
                payload=payload,
            )
            command = AdminCommand(
                operation_id=data.get("operationId") or str(uuid4()),
                idempotency_key=idempotency_key,
                intent=intent,
                request_hash=semantic_hash(intent),
            )
            outcome = await run_in_threadpool(self.control.execute, actor, command)
            return JSONResponse(outcome.model_dump(mode="json"), status_code=201)
        except (AdminControlError, SemanticConflict, ValidationError) as error:
            return _error_response(error)

    def detail_operator(self, operator_id: str, request: Request) -> JSONResponse:
        try:
            canonical_id = _canonical_uuid(operator_id)
            actor = self._authenticate(request, write=False, sensitive=False)
            detail, operator_revision = self.control.detail_operator_with_revision(
                actor, canonical_id
            )
            payload = detail.model_dump(mode="json")
            payload["operatorRevision"] = operator_revision
            return JSONResponse(payload)
        except (AdminControlError, SemanticConflict, ValidationError) as error:
            return _error_response(error)

    async def issue_invitation(self, operator_id: str, request: Request) -> JSONResponse:
        try:
            canonical_id = _canonical_uuid(operator_id)
            actor = await run_in_threadpool(self._authenticate, request, write=True, sensitive=True)
            data = await self.read_body(request)
            idempotency_key = data.get("idempotencyKey")
            expected_revision = data.get("expectedRevision")
            if not isinstance(idempotency_key, str) or type(expected_revision) is not int:
                raise AdminControlError(
                    "invalid_request",
                    "idempotencyKey and expectedRevision are required.",
                    status=400,
                )
            workspace_id, assignment_id, _, access_epoch = await run_in_threadpool(
                _workspace_context, self.control, canonical_id
            )
            intent = CommandIntent[ReissueInvitation](
                deployment_id=actor.deployment_id,
                scope=WorkspaceScope(operator_id=canonical_id, workspace_id=workspace_id),
                kind="reissue_invitation",
                expected_revision=expected_revision,
                access_epoch=data.get("accessEpoch", access_epoch),
                payload=ReissueInvitation(
                    assignment_id=data.get("assignmentId", assignment_id),
                    verified_identity_ref=actor.identity_proof_ref,
                ),
            )
            command = AdminCommand(
                operation_id=data.get("operationId") or str(uuid4()),
                idempotency_key=idempotency_key,
                intent=intent,
                request_hash=semantic_hash(intent),
            )
            issued = await run_in_threadpool(
                self.control.issue_invitation_with_token, actor, command
            )
            response_body: dict[str, Any] = {
                "outcome": issued.outcome.model_dump(mode="json"),
                "invitationId": issued.invitation_id,
                "token": issued.token.get_secret_value() if issued.token is not None else None,
                "expiresAt": issued.expires_at,
            }
            return JSONResponse(response_body, status_code=201 if issued.token is not None else 200)
        except (AdminControlError, SemanticConflict, ValidationError) as error:
            return _error_response(error)

    async def mark_invitation_delivered(
        self, operator_id: str, invitation_id: str, request: Request
    ) -> JSONResponse:
        try:
            canonical_op = _canonical_uuid(operator_id)
            canonical_inv = _canonical_uuid(invitation_id)
            actor = await run_in_threadpool(self._authenticate, request, write=True, sensitive=True)
            data = await self.read_body(request)
            expected_revision = data.get("expectedRevision")
            if type(expected_revision) is not int:
                raise AdminControlError(
                    "invalid_request", "expectedRevision is required.", status=400
                )
            next_revision = await run_in_threadpool(
                self.control.mark_invitation_sent,
                actor,
                operator_id=canonical_op,
                invitation_id=canonical_inv,
                expected_revision=expected_revision,
            )
            return JSONResponse(
                {"invitationId": canonical_inv, "revision": next_revision, "state": "sent"}
            )
        except (AdminControlError, SemanticConflict, ValidationError) as error:
            return _error_response(error)

    async def refresh_operator_source(self, operator_id: str, request: Request) -> JSONResponse:
        try:
            canonical_id = _canonical_uuid(operator_id)
            actor = await run_in_threadpool(
                self._authenticate, request, write=True, sensitive=False
            )
            data = await self.read_body(request)
            idempotency_key = data.get("idempotencyKey")
            expected_revision = data.get("expectedRevision")
            if not isinstance(idempotency_key, str) or type(expected_revision) is not int:
                raise AdminControlError(
                    "invalid_request",
                    "idempotencyKey and expectedRevision are required.",
                    status=400,
                )
            workspace_id, assignment_id, _, access_epoch = await run_in_threadpool(
                _workspace_context, self.control, canonical_id
            )
            intent = CommandIntent[RefreshSource](
                deployment_id=actor.deployment_id,
                scope=WorkspaceScope(operator_id=canonical_id, workspace_id=workspace_id),
                kind="refresh_source",
                expected_revision=expected_revision,
                access_epoch=data.get("accessEpoch", access_epoch),
                payload=RefreshSource(assignment_id=data.get("assignmentId", assignment_id)),
            )
            command = AdminCommand(
                operation_id=data.get("operationId") or str(uuid4()),
                idempotency_key=idempotency_key,
                intent=intent,
                request_hash=semantic_hash(intent),
            )
            outcome = await run_in_threadpool(self.control.execute, actor, command)
            return JSONResponse(outcome.model_dump(mode="json"))
        except (AdminControlError, SemanticConflict, ValidationError) as error:
            return _error_response(error)


def build_admin_lite_router(
    control: AdminControlService,
    sessions: AdminSessions,
    *,
    read_cookie: CookieReader,
    read_body: BodyReader,
) -> APIRouter:
    """Create the authenticated Admin-lite API router."""
    handlers = _AdminLiteHandlers(control, sessions, read_cookie=read_cookie, read_body=read_body)
    router = APIRouter()
    router.add_api_route("/api/admin/bootstrap", handlers.bootstrap, methods=["GET"])
    router.add_api_route("/api/admin/operators", handlers.list_operators, methods=["GET"])
    router.add_api_route("/api/admin/operators", handlers.create_operator, methods=["POST"])
    router.add_api_route(
        "/api/admin/operators/{operator_id}", handlers.detail_operator, methods=["GET"]
    )
    router.add_api_route(
        "/api/admin/operators/{operator_id}/invitations",
        handlers.issue_invitation,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/admin/operators/{operator_id}/invitations/{invitation_id}/delivered",
        handlers.mark_invitation_delivered,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/admin/operators/{operator_id}/refresh",
        handlers.refresh_operator_source,
        methods=["POST"],
    )
    return router

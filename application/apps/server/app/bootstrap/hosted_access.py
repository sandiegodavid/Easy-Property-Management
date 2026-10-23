"""Explicit hosted composition; ordinary local launches never construct these adapters."""

from datetime import UTC, datetime

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from app.modules.hosted_access.api.middleware import HostedTransportMiddleware
from app.modules.hosted_access.api.router import build_session_router
from app.modules.hosted_access.api.draft_leases import build_draft_lease_router
from app.modules.hosted_access.application.draft_leases import HostedDraftLeaseService
from app.modules.hosted_access.infrastructure.draft_leases import (
    SQLiteDraftLeaseStore,
    HostedRecoveryAuthority,
)
from app.modules.operator.domain.models import OperatorNotFound
from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.application.service import HostedAccessService
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.cloudflare_identity import CloudflareIdentityVerifier
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore
from app.modules.hosted_access.infrastructure.storage_budget import build_storage_budget
from app.modules.workspace.application.runtime import WorkspaceRuntime
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository


def compose_hosted_access(
    app: FastAPI, deployment: HostedDeployment, runtime: WorkspaceRuntime
) -> SQLiteHostedSessionStore:
    storage = build_storage_budget(deployment, runtime.service.paths.root)
    store = SQLiteHostedSessionStore(deployment)
    app.state.hosted_storage_budget = storage
    marker = (
        SQLiteAuditRepository(runtime.service.paths.database).latest_event_id(
            "workspace_restore", str(deployment.workspace_id)
        )
        or "not-restored"
    )
    store.bind_restore_marker(marker, datetime.now(UTC))
    service = HostedAccessService(deployment, store)
    verifier = CloudflareIdentityVerifier(deployment)
    leases = SQLiteDraftLeaseStore(store)
    operator = app.state.operator_service
    operator.recovery_authority = HostedRecoveryAuthority(leases, service.now)

    def revision(record_id):
        try:
            return operator.recovery(record_id)["revision"]
        except OperatorNotFound:
            return 0

    draft_service = HostedDraftLeaseService(leases, revision, now=service.now)

    @app.exception_handler(HostedAccessError)
    async def access_error(_request: Request, error: HostedAccessError) -> JSONResponse:
        return JSONResponse(
            {"detail": {"code": error.code, "message": str(error)}},
            status_code=error.status,
            headers={"Cache-Control": "no-store"},
        )

    app.include_router(build_session_router(service))
    app.include_router(build_draft_lease_router(draft_service, deployment))
    app.add_middleware(
        HostedTransportMiddleware,
        service=service,
        verifier=verifier,
        routes=app.openapi()["paths"],
        workspace_ready=lambda: (
            runtime.ready and runtime.workspace_id == str(deployment.workspace_id)
        ),
        storage=storage,
    )
    return store

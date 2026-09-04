"""Read-only audit history endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.modules.audit.application.recorder import AuditHistoryRepository
from app.modules.audit.domain.models import AuditPresentationPolicyError, AuditSnapshotPolicyRegistry
from app.modules.workspace.application.service import WorkspaceError, WorkspaceService


def build_router(service: WorkspaceService, repository: AuditHistoryRepository,
                 policies: AuditSnapshotPolicyRegistry | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/audit", tags=["audit"])
    history_repository = repository
    policy_registry = policies or AuditSnapshotPolicyRegistry()

    def _open() -> None:
        try:
            service.open()
        except WorkspaceError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error

    @router.get("/events/{entity_type}/{entity_id}")
    def history(entity_type: str, entity_id: str, limit: Annotated[int, Query(ge=1, le=500)] = 100,
                offset: Annotated[int, Query(ge=0)] = 0) -> dict[str, object]:
        _open()
        events = history_repository.history(entity_type, entity_id, limit=limit, offset=offset)
        try:
            return {"events": [event.to_dict(policy_registry.policy_for(event.entity_type, event.schema_version)) for event in events]}
        except AuditPresentationPolicyError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error

    @router.get("/events")
    def activity(correlation_id: str | None = None, action: str | None = None, actor_kind: str | None = None,
                 occurred_after: datetime | None = None, occurred_before: datetime | None = None,
                 limit: Annotated[int, Query(ge=1, le=500)] = 100, offset: Annotated[int, Query(ge=0)] = 0) -> dict[str, object]:
        _open()
        events = history_repository.history(correlation_id=correlation_id, action=action, actor_kind=actor_kind,
                                            occurred_after=occurred_after, occurred_before=occurred_before,
                                            limit=limit, offset=offset)
        try:
            return {"events": [event.to_dict(policy_registry.policy_for(event.entity_type, event.schema_version)) for event in events]}
        except AuditPresentationPolicyError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error

    return router

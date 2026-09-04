"""Local-only workspace status and explicit initialization endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.modules.workspace.application.service import (
    WorkspaceError,
    WorkspaceNotInitializedError,
    WorkspaceService,
)


def build_router(service: WorkspaceService) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        try:
            service.open()
        except WorkspaceNotInitializedError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
        except WorkspaceError as error:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error)) from error
        return {"status": "ok"}

    @router.get("/api/workspace")
    def workspace_status() -> dict[str, object]:
        try:
            manifest = service.open()
        except WorkspaceNotInitializedError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except WorkspaceError as error:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error)) from error
        return {"path": str(service.paths.root), "manifest": manifest.to_dict()}

    @router.post("/api/workspace/initialize", status_code=status.HTTP_201_CREATED)
    def initialize_workspace() -> dict[str, object]:
        try:
            manifest = service.initialize()
        except WorkspaceError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        return {"path": str(service.paths.root), "manifest": manifest.to_dict()}

    return router

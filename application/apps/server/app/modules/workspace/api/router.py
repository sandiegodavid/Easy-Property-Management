"""Local-only workspace status and explicit initialization endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.modules.workspace.application.runtime import WorkspaceRuntime
from app.modules.workspace.application.service import (
    WorkspaceError,
    WorkspaceNotInitializedError,
    WorkspaceService,
)


def build_router(service: WorkspaceService, runtime: WorkspaceRuntime | None = None) -> APIRouter:
    router = APIRouter()

    def startup_error() -> WorkspaceError | None:
        return runtime.error if runtime and runtime.startup_attempted else None

    def require_writer_lock() -> None:
        if runtime and not runtime.can_write:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(runtime.error))

    @router.get("/health")
    def health() -> dict[str, str]:
        if error := startup_error():
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
        try:
            service.open()
        except WorkspaceNotInitializedError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
        except WorkspaceError as error:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error)) from error
        return {"status": "ok"}

    @router.get("/api/workspace")
    def workspace_status() -> dict[str, object]:
        if error := startup_error():
            status_code = status.HTTP_404_NOT_FOUND if isinstance(error, WorkspaceNotInitializedError) else status.HTTP_503_SERVICE_UNAVAILABLE
            raise HTTPException(status_code=status_code, detail=str(error))
        try:
            manifest = service.open()
        except WorkspaceNotInitializedError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except WorkspaceError as error:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error)) from error
        return {"path": str(service.paths.root), "manifest": manifest.to_dict()}

    @router.post("/api/workspace/initialize", status_code=status.HTTP_201_CREATED)
    def initialize_workspace() -> dict[str, object]:
        require_writer_lock()
        try:
            manifest = service.initialize()
        except WorkspaceError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        if runtime and runtime.startup_attempted:
            runtime.refresh()
            if runtime.error:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(runtime.error))
        return {"path": str(service.paths.root), "manifest": manifest.to_dict()}

    return router

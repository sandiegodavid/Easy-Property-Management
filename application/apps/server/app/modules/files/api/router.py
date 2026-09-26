"""Bounded multipart file endpoints."""
from __future__ import annotations

import tempfile
from pathlib import Path
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.background import BackgroundTask
from app.modules.files.application.errors import FileError, MAX_FILE_BYTES
from app.modules.files.application.service import FileService
from app.modules.files.application.verification import FileStorageVerificationService
from app.modules.workspace.application.runtime import WorkspaceRuntime


class ArchiveFileLinkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: StrictBool
    reason: str = Field(min_length=1, max_length=1000)


def _file_http_error(error: FileError) -> HTTPException:
    status_by_code = {
        "file_not_found": 404,
        "file_content_unavailable": 409,
        "file_integrity_failed": 409,
        "file_provider_unavailable": 503,
        "publication_cleanup_incomplete": 503,
        "file_lifecycle_conflict": 409,
    }
    return HTTPException(status_code=status_by_code.get(error.code, 400), detail={"code": error.code, "message": str(error)})


def build_router(service: FileService, runtime: WorkspaceRuntime, verification: FileStorageVerificationService | None = None) -> APIRouter:
    router = APIRouter(tags=["files"])

    def require_ready(*, write: bool) -> None:
        if runtime.error or not runtime.ready: raise HTTPException(status_code=503, detail=str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write: raise HTTPException(status_code=503, detail="Workspace writer lock is unavailable.")

    @router.post("/api/files", status_code=status.HTTP_201_CREATED)
    async def upload(file: UploadFile = File(...), entity_type: str = Form(...), entity_id: str = Form(...), purpose: str = Form(...)) -> dict[str, object]:
        require_ready(write=True)
        staged_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False) as staged:
                staged_path = Path(staged.name); size = 0
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES: raise HTTPException(status_code=413, detail="File exceeds the 50 MiB local upload limit.")
                    staged.write(chunk)
            item = service.add(staged_path, file.filename or "attachment", file.content_type, entity_type=entity_type, entity_id=entity_id, purpose=purpose)
        except FileError as error: raise _file_http_error(error) from error
        except OSError as error: raise HTTPException(status_code=507, detail=f"Unable to stage upload: {error}") from error
        finally:
            if staged_path: staged_path.unlink(missing_ok=True)
        return item.to_dict()

    @router.get("/api/files/{file_id}")
    def metadata(file_id: str) -> dict[str, object]:
        require_ready(write=False)
        try: return service.get(file_id).to_dict()
        except FileError as error: raise _file_http_error(error) from error

    @router.get("/api/files/{file_id}/content")
    def content(file_id: str):
        require_ready(write=False)
        try:
            item = service.get(file_id)
            path = service.content_path(item)
            background = BackgroundTask(path.unlink, missing_ok=True) if item.storage_provider == "s3" else None
            return FileResponse(path, media_type=item.media_type, filename=item.original_name, background=background,
                                headers={"Content-Disposition": f'attachment; filename="{item.original_name}"', "X-Content-Type-Options": "nosniff"})
        except FileError as error: raise _file_http_error(error) from error

    @router.post("/api/files/verify")
    def verify_storage() -> dict[str, object]:
        require_ready(write=True)
        if verification is None:
            raise HTTPException(status_code=503, detail={"code": "file_provider_unavailable", "message": "Storage verification is unavailable."})
        try:
            return verification.verify()
        except FileError as error:
            raise _file_http_error(error) from error

    @router.post("/api/file-links/{link_id}/archive")
    def archive_link(link_id: str, data: ArchiveFileLinkInput) -> dict[str, object]:
        require_ready(write=True)
        try:
            return service.archive_link(link_id, confirmed=data.confirmed, reason=data.reason)
        except FileError as error:
            raise _file_http_error(error) from error
    return router

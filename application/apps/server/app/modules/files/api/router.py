"""Bounded multipart file endpoints."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt
from starlette.background import BackgroundTask

from app.modules.files.application.errors import (
    MAX_FILE_BYTES,
    FileError,
    PublicationCleanupIncomplete,
)
from app.modules.files.application.service import FileService
from app.modules.files.application.commands import FileRevisionConflict
from app.modules.files.application.verification import FileStorageVerificationService
from app.modules.workspace.application.runtime import WorkspaceRuntime


class ArchiveFileLinkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: StrictBool
    reason: str = Field(min_length=1, max_length=1000)
    expectedRevision: StrictInt = Field(ge=1)
    idempotencyKey: UUID


class FileLinkResponse(BaseModel):
    id: UUID
    fileId: UUID | None = None
    entityType: str
    entityId: UUID
    purpose: str
    createdAt: AwareDatetime
    archivedAt: AwareDatetime | None = None
    archiveReason: str | None = None
    revision: StrictInt = Field(ge=1)


class FileMetadataResponse(BaseModel):
    id: UUID
    originalName: str
    mediaType: str
    sizeBytes: StrictInt = Field(ge=0)
    contentSha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    storageProvider: Literal["local", "s3"]
    storageState: Literal["available", "missing", "quarantined"]
    verifiedAt: AwareDatetime
    createdAt: AwareDatetime
    links: list[FileLinkResponse]


class FileUploadResponse(FileMetadataResponse):
    operationId: UUID


class FileArchiveResponse(FileLinkResponse):
    operationId: UUID
    updatedAt: AwareDatetime


class FileConflictResponse(BaseModel):
    class Detail(BaseModel):
        code: str
        message: str
        current: FileLinkResponse | None = None

    detail: Detail


class CleanupAttentionResponse(BaseModel):
    # Local publications use a digest; remote publications use a UUID.
    publicationId: str = Field(min_length=1, max_length=200)
    provider: Literal["local", "s3"]
    openedAt: AwareDatetime


class FileIntegrityAttentionResponse(BaseModel):
    count: StrictInt = Field(ge=0)
    outstanding: list[CleanupAttentionResponse]


class StorageStateCounts(BaseModel):
    available: StrictInt = Field(ge=0)
    missing: StrictInt = Field(ge=0)
    quarantined: StrictInt = Field(ge=0)


class StorageReconciliationCounts(BaseModel):
    referenced: StrictInt = Field(ge=0)
    orphaned: StrictInt = Field(ge=0)
    missing: StrictInt = Field(ge=0)
    unverifiable: StrictInt = Field(ge=0)


class OutstandingCleanupCount(BaseModel):
    outstanding: StrictInt = Field(ge=0)


class StorageVerificationResponse(BaseModel):
    complete: StrictBool
    scanComplete: StrictBool
    continuation: str | None
    files: StrictInt = Field(ge=0)
    states: StorageStateCounts
    reconciliation: dict[Literal["local", "s3"], StorageReconciliationCounts]
    cleanupAttention: OutstandingCleanupCount


def _file_http_error(error: FileError) -> HTTPException:
    status_by_code = {
        "file_not_found": 404,
        "file_content_unavailable": 409,
        "file_integrity_failed": 409,
        "file_provider_unavailable": 503,
        "publication_cleanup_incomplete": 503,
        "file_lifecycle_conflict": 409,
        "file_command_conflict": 409,
        "file_revision_conflict": 409,
        "file_too_large": 413,
    }
    detail: dict[str, object] = {"code": error.code, "message": str(error)}
    if isinstance(error, FileRevisionConflict):
        detail["current"] = error.current
    if isinstance(error, PublicationCleanupIncomplete):
        # Never expose provider locators or cleanup internals.  Operators do
        # get a durable, actionable signal when attention recording itself
        # needs repair after the owning transaction has released its lock.
        detail["repairRequired"] = True
        detail["attentionRecorded"] = error.attention_recording_failure is None
    return HTTPException(status_code=status_by_code.get(error.code, 400), detail=detail)


def build_router(
    service: FileService,
    runtime: WorkspaceRuntime,
    verification: FileStorageVerificationService | None = None,
) -> APIRouter:
    router = APIRouter(tags=["files"], responses={409: {"model": FileConflictResponse}})

    def require_ready(*, write: bool) -> None:
        if runtime.error or not runtime.ready:
            raise HTTPException(
                status_code=503, detail=str(runtime.error or "Workspace is not ready.")
            )
        if write and not runtime.can_write:
            raise HTTPException(status_code=503, detail="Workspace writer lock is unavailable.")

    @router.post(
        "/api/files",
        status_code=status.HTTP_201_CREATED,
        operation_id="uploadFile",
        response_model=FileUploadResponse,
    )
    async def upload(
        file: UploadFile = File(...),
        entity_type: str = Form(...),
        entity_id: UUID = Form(...),
        purpose: str = Form(...),
        idempotency_key: UUID = Form(...),
    ) -> dict[str, object]:
        require_ready(write=True)
        staged_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False) as staged:
                staged_path = Path(staged.name)
                size = 0
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise HTTPException(
                            status_code=413, detail="File exceeds the 50 MiB local upload limit."
                        )
                    staged.write(chunk)
            result = service.upload(
                staged_path,
                file.filename or "attachment",
                file.content_type,
                entity_type=entity_type,
                entity_id=str(entity_id),
                purpose=purpose,
                idempotency_key=str(idempotency_key),
            )
        except FileError as error:
            raise _file_http_error(error) from error
        except OSError as error:
            raise HTTPException(
                status_code=507, detail=f"Unable to stage upload: {error}"
            ) from error
        finally:
            if staged_path:
                staged_path.unlink(missing_ok=True)
        return result

    @router.get(
        "/api/files/commands/by-key/{key}",
        operation_id="recoverFileCommandByKey",
        response_model=FileUploadResponse | FileArchiveResponse,
    )
    def recover_by_key(key: UUID):
        require_ready(write=False)
        try:
            return service.recover_command(key=str(key))
        except FileError as error:
            raise _file_http_error(error) from error

    @router.get(
        "/api/files/commands/{operation_id}",
        operation_id="recoverFileCommand",
        response_model=FileUploadResponse | FileArchiveResponse,
    )
    def recover_by_id(operation_id: UUID):
        require_ready(write=False)
        try:
            return service.recover_command(operation_id=str(operation_id))
        except FileError as error:
            raise _file_http_error(error) from error

    @router.get(
        "/api/files/integrity-attention",
        response_model=FileIntegrityAttentionResponse,
        operation_id="getFileIntegrityAttention",
    )
    def integrity_attention() -> dict[str, object]:
        """Read-only Settings projection for unresolved publication cleanup."""
        require_ready(write=False)
        outstanding = service.unit_of_work.outstanding_cleanup_attentions()
        return {"count": len(outstanding), "outstanding": outstanding}

    @router.get(
        "/api/files/{file_id}", response_model=FileMetadataResponse, operation_id="getFileMetadata"
    )
    def metadata(file_id: UUID) -> dict[str, object]:
        require_ready(write=False)
        try:
            return service.get(str(file_id)).to_dict()
        except FileError as error:
            raise _file_http_error(error) from error

    @router.get(
        "/api/files/{file_id}/content",
        operation_id="downloadFileContent",
        response_class=FileResponse,
        responses={
            200: {
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                }
            }
        },
    )
    def content(file_id: UUID):
        require_ready(write=False)
        try:
            item = service.get(str(file_id))
            path = service.content_path(item)
            background = (
                BackgroundTask(path.unlink, missing_ok=True)
                if item.storage_provider == "s3"
                else None
            )
            # Starlette performs standards-compliant filename quoting and
            # RFC 5987 encoding; never interpolate a user filename into a
            # header ourselves.
            return FileResponse(
                path,
                media_type=item.media_type,
                filename=item.original_name,
                background=background,
                headers={"X-Content-Type-Options": "nosniff"},
            )
        except FileError as error:
            raise _file_http_error(error) from error

    @router.post(
        "/api/files/verify",
        response_model=StorageVerificationResponse,
        operation_id="verifyFileStorage",
    )
    def verify_storage(continuation: str | None = Query(default=None)) -> dict[str, object]:
        require_ready(write=True)
        if verification is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "file_provider_unavailable",
                    "message": "Storage verification is unavailable.",
                },
            )
        try:
            return verification.verify(continuation=continuation)
        except FileError as error:
            raise _file_http_error(error) from error

    @router.post(
        "/api/file-links/{link_id}/archive",
        operation_id="archiveFileLink",
        response_model=FileArchiveResponse,
    )
    def archive_link(link_id: UUID, data: ArchiveFileLinkInput) -> dict[str, object]:
        require_ready(write=True)
        try:
            return service.archive_command(
                str(link_id),
                confirmed=data.confirmed,
                reason=data.reason,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        except FileError as error:
            raise _file_http_error(error) from error

    return router

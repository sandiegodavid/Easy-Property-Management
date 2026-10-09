"""Two approved FILE-001 incomplete forms; no bytes, paths or provider selection."""

from uuid import UUID
from pydantic import Field, StrictBool, StrictInt

from app.modules.operator.domain.models import Contract


class FileUploadForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=0, le=0)
    originalName: str | None = Field(None, max_length=255)
    mediaType: str | None = Field(None, max_length=255)
    contentSha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$", strict=True)
    entityType: str | None = Field(None, max_length=100)
    entityId: UUID | None = None
    purpose: str | None = Field(None, max_length=100)


class FileArchiveForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=1)
    confirmed: StrictBool | None = None
    reason: str | None = Field(None, max_length=1000)


FILE_SCHEMAS = {"file.upload": FileUploadForm, "file.link.archive": FileArchiveForm}

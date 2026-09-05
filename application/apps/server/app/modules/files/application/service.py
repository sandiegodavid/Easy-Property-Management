from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.modules.files.domain.models import StoredFile
from app.modules.workspace.application.service import WorkspaceService
from app.modules.files.application.errors import FileError
from app.modules.files.application.ports import FileAuditChange, FileContentStore, FileLink, FileUnitOfWork

class FileService:
    def __init__(self, workspace: WorkspaceService, content_store: FileContentStore, unit_of_work: FileUnitOfWork) -> None:
        self.workspace = workspace
        self.content_store = content_store
        self.unit_of_work = unit_of_work

    def add(
        self,
        source: Path,
        original_name: str,
        media_type: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        purpose: str = "attachment",
    ) -> StoredFile:
        self.workspace.open()
        entity_type, entity_id, purpose = _link_fields(entity_type, entity_id, purpose)
        name = Path(original_name).name.strip() or "attachment"
        if name != original_name or ".." in name:
            raise FileError("File name must not contain a path.")
        content = None
        persisted = False
        try:
            content = self.content_store.store(source)
            item = StoredFile(
                str(uuid4()),
                name,
                media_type or "application/octet-stream",
                content.size_bytes,
                content.content_sha256,
                content.relative_path,
                datetime.now(UTC).isoformat(),
            )
            link = None if entity_type is None else FileLink(
                id=str(uuid4()), entity_type=entity_type, entity_id=entity_id,
                purpose=purpose, created_at=datetime.now(UTC).isoformat(),
            )
            correlation_id = str(uuid4())
            audit_changes = [FileAuditChange("file", item.id, "created", item.to_dict(), "file_stored", correlation_id)]
            if link is not None:
                audit_changes.append(FileAuditChange("file_link", link.id, "created", {
                    "fileId": item.id, "entityType": link.entity_type, "entityId": link.entity_id,
                    "purpose": link.purpose,
                }, "file_linked", correlation_id))
            self.unit_of_work.write(item, link, audit_changes)
            persisted = True
            try:
                content.commit()
            except OSError:
                # The durable file and metadata are committed; a later retry must not duplicate metadata.
                pass
            return item
        except Exception as error:
            if content is not None and not persisted:
                content.rollback()
            if isinstance(error, OSError):
                raise FileError(f"Unable to store file: {error}") from error
            raise

    def get(self, file_id: str) -> StoredFile:
        item = self.unit_of_work.get(file_id)
        if not item:
            raise FileError("File record was not found.")
        return item

    def content_path(self, item: StoredFile) -> Path:
        return self.content_store.path_for(item.relative_path, item.content_sha256, item.size_bytes)


def _link_fields(entity_type: str | None, entity_id: str | None, purpose: str) -> tuple[str | None, str | None, str]:
    link_requested = entity_type is not None or entity_id is not None
    if not isinstance(purpose, str) or not (trimmed_purpose := purpose.strip()):
        raise FileError("File link purpose must be nonblank text.")
    if not link_requested:
        return None, None, trimmed_purpose
    if not isinstance(entity_type, str) or not (trimmed_type := entity_type.strip()):
        raise FileError("A file link requires a nonblank entity type.")
    if not isinstance(entity_id, str) or not (trimmed_id := entity_id.strip()):
        raise FileError("A file link requires a nonblank entity ID.")
    return trimmed_type, trimmed_id, trimmed_purpose

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.modules.files.domain.models import StoredFile
from app.modules.workspace.application.service import WorkspaceService
from app.modules.files.application.errors import FileError, MAX_FILE_BYTES
from app.modules.files.application.ports import FileContentStore, FileMetadataRepository

class FileService:
    def __init__(self, workspace: WorkspaceService, content_store: FileContentStore, repository: FileMetadataRepository) -> None:
        self.workspace = workspace
        self.content_store = content_store
        self.repository = repository

    def add(self, source: Path, original_name: str, media_type: str, *, entity_type: str | None = None,
            entity_id: str | None = None, purpose: str = "attachment") -> StoredFile:
        self.workspace.open()
        if bool(entity_type) != bool(entity_id): raise FileError("A file link requires both an entity type and entity ID.")
        name = Path(original_name).name.strip() or "attachment"
        if name != original_name or ".." in name: raise FileError("File name must not contain a path.")
        content = None
        persisted = False
        try:
            content = self.content_store.store(source)
            item = StoredFile(str(uuid4()), name, media_type or "application/octet-stream", content.size_bytes, content.content_sha256, content.relative_path, datetime.now(UTC).isoformat())
            self.repository.create(item, entity_type, entity_id, purpose)
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
        item = self.repository.get(file_id)
        if not item: raise FileError("File record was not found.")
        return item

    def content_path(self, item: StoredFile) -> Path:
        return self.content_store.path_for(item.relative_path, item.content_sha256, item.size_bytes)

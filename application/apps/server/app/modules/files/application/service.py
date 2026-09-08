from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.modules.files.domain.models import StoredFile
from app.modules.workspace.application.service import WorkspaceService
from app.modules.files.application.errors import FileError
from app.modules.files.application.ports import FileAuditChange, FileContentStore, FileLink, FileLinkValidator, FileUnitOfWork

class FileService:
    def __init__(self, workspace: WorkspaceService, content_store: FileContentStore,
                 unit_of_work: FileUnitOfWork,
                 additional_stores: dict[str, FileContentStore] | None = None,
                 link_validators: tuple[FileLinkValidator, ...] = ()) -> None:
        self.workspace = workspace
        self.content_store = content_store
        self.unit_of_work = unit_of_work
        self.content_stores = {getattr(content_store, "storage_provider", "local"): content_store, **(additional_stores or {})}
        self.link_validators = {
            entity_type: validator
            for validator in link_validators
            for entity_type in validator.entity_types
        }

    def add(
        self,
        source: Path,
        original_name: str,
        media_type: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        purpose: str = "attachment",
        storage_provider: str | None = None,
    ) -> StoredFile:
        self.workspace.open()
        entity_type, entity_id, purpose = _link_fields(entity_type, entity_id, purpose)
        name = Path(original_name).name.strip() or "attachment"
        if name != original_name or ".." in name:
            raise FileError("File name must not contain a path.")
        link = None if entity_type is None else FileLink(
            id=str(uuid4()), entity_type=entity_type, entity_id=entity_id,
            purpose=purpose, created_at=datetime.now(UTC).isoformat(),
        )
        if link is not None:
            validator = self.link_validators.get(link.entity_type)
            if validator is None:
                raise FileError(f"No owning-domain validator is configured for {link.entity_type} links.")
            validator.validate(link)
        content = None
        persisted = False
        try:
            provider = storage_provider or getattr(self.content_store, "storage_provider", "local")
            store = self.content_stores.get(provider)
            if store is None:
                raise FileError(f"File storage provider is not configured: {provider}.")
            content = store.store(source)
            item = StoredFile(
                str(uuid4()),
                name,
                media_type or "application/octet-stream",
                content.size_bytes,
                content.content_sha256,
                content.storage_provider,
                content.storage_state,
                content.local_relative_path,
                content.s3_bucket,
                content.s3_object_key,
                content.s3_version_id,
                content.provider_etag,
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
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
            if isinstance(error, ValueError) and not isinstance(error, FileError):
                raise FileError(str(error)) from error
            raise

    def get(self, file_id: str) -> StoredFile:
        item = self.unit_of_work.get(file_id)
        if not item:
            raise FileError("File record was not found.")
        return item

    def content_path(self, item: StoredFile) -> Path:
        if item.storage_state != "available":
            raise FileError("Only available file content can be retrieved.")
        store = self.content_stores.get(item.storage_provider)
        if store is None:
            raise FileError("The configured content store cannot retrieve this file.")
        return store.path_for(item)


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

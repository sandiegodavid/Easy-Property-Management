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
        correlation_id: str | None = None,
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
        validator = None
        if link is not None:
            validator = self.link_validators.get(link.entity_type)
            if validator is None:
                raise FileError(f"No owning-domain validator is configured for {link.entity_type} links.")
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
            correlation_id = correlation_id or str(uuid4())
            audit_changes = [FileAuditChange("file", item.id, "created", item.to_dict(), "file_stored", correlation_id)]
            if link is not None:
                audit_changes.append(FileAuditChange(
                    "file_link",
                    link.id,
                    "created",
                    _link_snapshot(_link_for_file(link, item.id)),
                    "file_linked",
                    correlation_id,
                ))
            validation = (lambda connection, candidate: validator.validate_create(connection, candidate)) if validator else None
            self.unit_of_work.write(item, link, audit_changes, validation)
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

    def archive_link(self, link_id: str, *, confirmed: bool, reason: str, correlation_id: str | None = None) -> dict[str, object]:
        if type(confirmed) is not bool or not confirmed:
            raise FileError("Explicit archive confirmation is required.")
        if not isinstance(reason, str) or not (reason := reason.strip()) or len(reason) > 1000:
            raise FileError("Archive reason must be between 1 and 1,000 characters.")
        current = self.unit_of_work.get_link(link_id)
        if current is None:
            raise FileError("File link was not found.")
        if current.archived_at is not None:
            raise FileError("File link is already archived.")
        validator = self.link_validators.get(current.entity_type)
        if validator is None:
            raise FileError(f"No owning-domain validator is configured for {current.entity_type} links.")
        archived = FileLink(current.id, current.entity_type, current.entity_id, current.purpose, current.created_at,
            current.file_id, datetime.now(UTC).isoformat(), reason)
        correlation_id = correlation_id or str(uuid4())
        audit = FileAuditChange("file_link", archived.id, "archived", _link_snapshot(archived),
            "file_link_archived", correlation_id, _link_snapshot(current))
        try:
            self.unit_of_work.archive_link(archived, audit, lambda connection, candidate: validator.validate_archive(connection, candidate))
        except ValueError as error:
            raise FileError(str(error)) from error
        return {"id": archived.id, "fileId": archived.file_id, "entityType": archived.entity_type,
            "entityId": archived.entity_id, "purpose": archived.purpose, "createdAt": archived.created_at,
            "archivedAt": archived.archived_at, "archiveReason": archived.archive_reason}

    def add_in_transaction(self, connection, source: Path, original_name: str, media_type: str, *, entity_type: str, entity_id: str, purpose: str, correlation_id: str):
        """Stage content and persist file/link/audit data on a caller-owned SQLite transaction."""
        entity_type, entity_id, purpose = _link_fields(entity_type, entity_id, purpose)
        name = Path(original_name).name.strip() or "attachment"
        if name != original_name or ".." in name: raise FileError("File name must not contain a path.")
        link = FileLink(str(uuid4()), entity_type, entity_id, purpose, datetime.now(UTC).isoformat())
        provider = getattr(self.content_store, "storage_provider", "local"); content = self.content_stores[provider].store(source)
        try:
            item = StoredFile(str(uuid4()), name, media_type or "application/octet-stream", content.size_bytes, content.content_sha256, content.storage_provider, content.storage_state, content.local_relative_path, content.s3_bucket, content.s3_object_key, content.s3_version_id, content.provider_etag, datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat())
            changes = [
                FileAuditChange("file", item.id, "created", item.to_dict(), "file_stored", correlation_id),
                FileAuditChange(
                    "file_link",
                    link.id,
                    "created",
                    _link_snapshot(_link_for_file(link, item.id)),
                    "file_linked",
                    correlation_id,
                ),
            ]
            writer = getattr(self.unit_of_work, "write_in_transaction", None)
            if writer is None: raise FileError("The configured file store does not support inspection transactions.")
            writer(connection, item, link, changes)
            return item, content
        except Exception:
            content.rollback(); raise

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


def _link_snapshot(link: FileLink) -> dict[str, object]:
    return {
        "fileId": link.file_id,
        "entityType": link.entity_type,
        "entityId": link.entity_id,
        "purpose": link.purpose,
        "createdAt": link.created_at,
        "archivedAt": link.archived_at,
        "archiveReason": link.archive_reason,
    }


def _link_for_file(link: FileLink, file_id: str) -> FileLink:
    return FileLink(
        id=link.id,
        entity_type=link.entity_type,
        entity_id=link.entity_id,
        purpose=link.purpose,
        created_at=link.created_at,
        file_id=file_id,
        archived_at=link.archived_at,
        archive_reason=link.archive_reason,
    )

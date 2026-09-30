"""FILE-001 commands. Logical metadata and a validated owning link commit together."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.modules.files.application.errors import (
    MAX_FILE_BYTES,
    FileError,
    PublicationCleanupIncomplete,
    normalize_filename,
    normalize_media_type,
)
from app.modules.files.application.ports import (
    FileAuditChange,
    FileContentStore,
    FileLink,
    FileLinkPolicyRegistry,
    FileLinkValidator,
    FileUnitOfWork,
)
from app.modules.files.domain.models import StoredFile
from app.modules.workspace.application.service import WorkspaceService


def _now() -> str:
    return datetime.now(UTC).isoformat()


class FileAttachmentBatch:
    """Transaction-scoped attachments with idempotent reverse-order cleanup."""

    def __init__(self, service: "FileService", connection: Any) -> None:
        self.service = service
        self.connection = connection
        self._leases: list[Any] = []
        self._by_digest: dict[str, Any] = {}
        self._closed: str | None = None
        self._correlation_id: str | None = None
        self._cleanup_incomplete: PublicationCleanupIncomplete | None = None

    def add(self, source: Path, original_name: str, media_type: str | None, *, entity_type: str, entity_id: str, purpose: str, correlation_id: str, owning_workflow: bool = False) -> StoredFile:
        if self._closed is not None:
            raise FileError("The attachment batch is already complete.")
        self._correlation_id = self._correlation_id or correlation_id
        link = self.service._new_link(entity_type, entity_id, purpose)
        self.service._validate_link(self.connection, link, generic_upload=not owning_workflow)
        digest = _source_digest(source)
        content = self._by_digest.get(digest)
        if content is None:
            content = self.service.content_store.store(source)
            if content.content_sha256 != digest:
                try:
                    content.rollback()
                finally:
                    raise FileError("Published file content changed while it was prepared.", "file_integrity_failed")
            self._by_digest[digest] = content
            self._leases.append(content)
        item = self.service._stored_item(content, original_name, media_type)
        self.service._write_on_connection(self.connection, item, link, correlation_id)
        # The caller-owned batch needs the stable association ID to create
        # its own immutable aggregate reference without rereading the link.
        return replace(item, links=({"id": link.id, "entityId": link.entity_id},))

    def commit(self) -> None:
        if self._closed is not None:
            return
        self._closed = "committed"
        errors: list[tuple[Any, BaseException]] = []
        for content in self._leases:
            try:
                content.commit()
            except BaseException as error:
                errors.append((content, error))
        if errors:
            publication, error = errors[0]
            incomplete = PublicationCleanupIncomplete(
                str(getattr(publication, "publication_id", getattr(publication, "content_sha256", "unknown"))),
                str(getattr(publication, "storage_provider", "unknown")), error, error,
            )
            self._cleanup_incomplete = incomplete
            self.service._try_record_cleanup_attention(incomplete, self._correlation_id or str(uuid4()))
            raise incomplete from error

    def rollback(self, original_failure: BaseException | None = None) -> None:
        if self._closed is not None:
            return
        self._closed = "rolled_back"
        errors: list[tuple[Any, BaseException]] = []
        for content in reversed(self._leases):
            try:
                content.rollback()
            except BaseException as error:
                errors.append((content, error))
        if errors:
            publication, cleanup_error = errors[0]
            failure = original_failure or cleanup_error
            incomplete = PublicationCleanupIncomplete(
                str(getattr(publication, "publication_id", getattr(publication, "content_sha256", "unknown"))),
                str(getattr(publication, "storage_provider", "unknown")), failure, cleanup_error,
            )
            # Caller-owned transactions can still hold SQLite's single writer
            # lock here.  Leave attention persistence retryable until their
            # rollback has released it.
            self._cleanup_incomplete = incomplete
            raise incomplete from failure

    def persist_cleanup_attention(self) -> PublicationCleanupIncomplete | None:
        """Persist a deferred cleanup warning after the owning transaction ends."""
        incomplete = self._cleanup_incomplete
        if incomplete is not None:
            self.service._try_record_cleanup_attention(
                incomplete, self._correlation_id or str(uuid4())
            )
        return incomplete


class FileService:
    def __init__(self, workspace: WorkspaceService, content_store: FileContentStore,
                 unit_of_work: FileUnitOfWork,
                 additional_stores: dict[str, FileContentStore] | None = None,
                 link_validators: tuple[FileLinkValidator, ...] = ()) -> None:
        self.workspace = workspace
        self.content_store = content_store
        self.unit_of_work = unit_of_work
        self.content_stores = {getattr(content_store, "storage_provider", "local"): content_store, **(additional_stores or {})}
        self.policy_registry = FileLinkPolicyRegistry(link_validators)
        self.link_validators = self.policy_registry.as_mapping()

    def attachment_batch(self, connection: Any) -> FileAttachmentBatch:
        return FileAttachmentBatch(self, connection)

    def add(self, source: Path, original_name: str, media_type: str | None, *, entity_type: str, entity_id: str, purpose: str, correlation_id: str | None = None) -> StoredFile:
        """Create one logical file and one validated association using the primary store."""
        # Runtime opens and validates the workspace before exposing this
        # command.  Do not reopen it here: an in-process caller may be in the
        # middle of constructing a single transaction-scoped attachment batch.
        link = self._new_link(entity_type, entity_id, purpose)
        validator = self._validator(link.entity_type, generic_upload=True)
        content = None
        persisted = False
        correlation = correlation_id or str(uuid4())
        try:
            content = self.content_store.store(source)
            item = self._stored_item(content, original_name, media_type)
            self.unit_of_work.write(item, link, self._audit_changes(item, link, correlation), lambda connection, candidate: validator.validate_create(connection, candidate))
            persisted = True
            content.commit()
            return item
        except Exception as error:
            if content is not None and not persisted:
                try:
                    content.rollback()
                except BaseException as cleanup_error:
                    publication_id = getattr(content, "publication_id", "unknown")
                    incomplete = PublicationCleanupIncomplete(publication_id, getattr(content, "storage_provider", "unknown"), error, cleanup_error)
                    self._try_record_cleanup_attention(incomplete, correlation)
                    raise incomplete from error
            if isinstance(error, PublicationCleanupIncomplete):
                self._try_record_cleanup_attention(error, correlation)
                raise
            if isinstance(error, FileError):
                raise
            if isinstance(error, OSError):
                raise FileError("File storage is unavailable.", "file_provider_unavailable") from error
            if isinstance(error, ValueError):
                raise FileError(str(error)) from error
            raise

    def add_in_transaction(self, connection: Any, source: Path, original_name: str, media_type: str | None, *, entity_type: str, entity_id: str, purpose: str, correlation_id: str, batch: FileAttachmentBatch | None = None, owning_workflow: bool = True) -> tuple[StoredFile, FileAttachmentBatch]:
        """Prepare an owning-workflow attachment on its caller's transaction."""
        current = batch or self.attachment_batch(connection)
        try:
            return current.add(source, original_name, media_type, entity_type=entity_type, entity_id=entity_id, purpose=purpose, correlation_id=correlation_id, owning_workflow=owning_workflow), current
        except Exception as error:
            if batch is None:
                try:
                    current.rollback(error)
                except PublicationCleanupIncomplete:
                    # The structured error keeps the business/database failure
                    # as its cause instead of silently replacing it.
                    raise
            raise

    def link_existing_file(self, file_id: str, *, entity_type: str, entity_id: str, purpose: str, correlation_id: str | None = None) -> FileLink:
        """Internal-only association command; it never creates another file row."""
        link = self._new_link(entity_type, entity_id, purpose)
        validator = self._validator(link.entity_type, generic_upload=False)
        correlation = correlation_id or str(uuid4())
        item = self.unit_of_work.get(file_id)
        if item is None:
            raise FileError("File record was not found.", "file_not_found")
        if item.storage_state != "available":
            raise FileError("Only available file content can be associated.", "file_content_unavailable")
        linked = FileLink(link.id, link.entity_type, link.entity_id, link.purpose, link.created_at, file_id)
        try:
            self.unit_of_work.link_existing(linked, FileAuditChange("file_link", linked.id, "created", _link_snapshot(linked), "file_linked", correlation), lambda connection, candidate: validator.validate_create(connection, candidate))
        except (ValueError, IntegrityError) as error:
            raise FileError(str(error), "file_lifecycle_conflict") from error
        return linked

    def get(self, file_id: str) -> StoredFile:
        item = self.unit_of_work.get(file_id)
        if not item:
            raise FileError("File record was not found.", "file_not_found")
        return item

    def archive_link(self, link_id: str, *, confirmed: bool, reason: str, correlation_id: str | None = None) -> dict[str, object]:
        if type(confirmed) is not bool or not confirmed:
            raise FileError("Explicit archive confirmation is required.")
        if not isinstance(reason, str) or not (reason := reason.strip()) or len(reason) > 1000:
            raise FileError("Archive reason must be between 1 and 1,000 characters.")
        current = self.unit_of_work.get_link(link_id)
        if current is None:
            raise FileError("File link was not found.", "file_not_found")
        if current.archived_at is not None:
            raise FileError("File link is already archived.", "file_lifecycle_conflict")
        validator = self._validator(current.entity_type, generic_upload=False)
        archived = FileLink(current.id, current.entity_type, current.entity_id, current.purpose, current.created_at, current.file_id, _now(), reason)
        audit = FileAuditChange("file_link", archived.id, "archived", _link_snapshot(archived), "file_link_archived", correlation_id or str(uuid4()), _link_snapshot(current))
        try:
            self.unit_of_work.archive_link(archived, audit, lambda connection, candidate: validator.validate_archive(connection, candidate))
        except ValueError as error:
            raise FileError(str(error), "file_lifecycle_conflict") from error
        return _link_snapshot(archived) | {"id": archived.id}

    def content_path(self, item: StoredFile) -> Path:
        if item.storage_state != "available":
            raise FileError("Only available file content can be retrieved.", "file_content_unavailable")
        store = self.content_stores.get(item.storage_provider)
        if store is None:
            raise FileError("The configured content store cannot retrieve this file.", "file_provider_unavailable")
        return store.path_for(item)

    def _new_link(self, entity_type: str, entity_id: str, purpose: str) -> FileLink:
        entity_type, entity_id, purpose = _link_fields(entity_type, entity_id, purpose)
        return FileLink(str(uuid4()), entity_type, entity_id, purpose, _now())

    def _validator(self, entity_type: str, *, generic_upload: bool) -> FileLinkValidator:
        validator = self.link_validators.get(entity_type)
        if validator is None:
            raise FileError(f"No owning-domain validator is configured for {entity_type} links.")
        if generic_upload and not validator.allows_generic_upload:
            raise FileError("This evidence type must be attached by its owning workflow.", "file_lifecycle_conflict")
        return validator

    def _validate_link(self, connection: Any, link: FileLink, *, generic_upload: bool) -> None:
        self._validator(link.entity_type, generic_upload=generic_upload).validate_create(connection, link)

    def _stored_item(self, content: Any, original_name: str, media_type: str | None) -> StoredFile:
        now = _now()
        return StoredFile(str(uuid4()), normalize_filename(original_name), normalize_media_type(media_type), content.size_bytes, content.content_sha256, content.storage_provider, content.storage_state, content.local_relative_path, content.s3_bucket, content.s3_object_key, content.s3_version_id, content.provider_etag, now, now)

    def _audit_changes(self, item: StoredFile, link: FileLink, correlation_id: str) -> list[FileAuditChange]:
        linked = _link_for_file(link, item.id)
        return [FileAuditChange("file", item.id, "created", item.to_dict(), "file_stored", correlation_id), FileAuditChange("file_link", linked.id, "created", _link_snapshot(linked), "file_linked", correlation_id)]

    def _write_on_connection(self, connection: Any, item: StoredFile, link: FileLink, correlation_id: str) -> None:
        writer = getattr(self.unit_of_work, "write_in_transaction", None)
        if writer is None:
            raise FileError("The configured file store does not support caller-owned transactions.")
        writer(connection, item, link, self._audit_changes(item, link, correlation_id))

    def _record_cleanup_attention(self, error: PublicationCleanupIncomplete, correlation_id: str) -> None:
        recorder = getattr(self.unit_of_work, "record_cleanup_incomplete", None)
        if recorder is not None:
            recorder(error.publication_id, error.provider, correlation_id)

    def _try_record_cleanup_attention(self, error: PublicationCleanupIncomplete, correlation_id: str) -> None:
        """Keep cleanup failure primary, but never discard failed attention persistence."""
        try:
            self._record_cleanup_attention(error, correlation_id)
        except BaseException as attention_error:
            # The public error remains privacy-safe and retains the exact
            # cleanup identity; callers can surface this repair-required
            # secondary failure without losing the original business error.
            error.attention_recording_failure = attention_error


def _source_digest(source: Path) -> str:
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as input_file:
            while chunk := input_file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise FileError("File exceeds the 50 MiB upload limit.", "file_too_large")
                digest.update(chunk)
    except OSError as error:
        raise FileError("Unable to read upload content.", "file_provider_unavailable") from error
    return digest.hexdigest()


def _link_fields(entity_type: str, entity_id: str, purpose: str) -> tuple[str, str, str]:
    if not isinstance(entity_type, str) or not (entity_type := entity_type.strip()):
        raise FileError("A file link requires a nonblank entity type.")
    if not isinstance(entity_id, str) or not (entity_id := entity_id.strip()):
        raise FileError("A file link requires a nonblank entity ID.")
    if not isinstance(purpose, str) or not (purpose := purpose.strip()):
        raise FileError("File link purpose must be nonblank text.")
    return entity_type, entity_id, purpose


def _link_snapshot(link: FileLink) -> dict[str, object]:
    return {"fileId": link.file_id, "entityType": link.entity_type, "entityId": link.entity_id, "purpose": link.purpose, "createdAt": link.created_at, "archivedAt": link.archived_at, "archiveReason": link.archive_reason}


def _link_for_file(link: FileLink, file_id: str) -> FileLink:
    return FileLink(link.id, link.entity_type, link.entity_id, link.purpose, link.created_at, file_id, link.archived_at, link.archive_reason)

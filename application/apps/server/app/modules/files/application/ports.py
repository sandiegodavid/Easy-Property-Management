"""Ports for managed content and atomic file metadata writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from app.modules.files.domain.models import StoredFile


class StoredContent(Protocol):
    storage_provider: str
    storage_state: str
    local_relative_path: str | None
    s3_bucket: str | None
    s3_object_key: str | None
    s3_version_id: str | None
    provider_etag: str | None
    size_bytes: int
    content_sha256: str
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class FileContentStore(Protocol):
    def store(self, source: Path) -> StoredContent: ...
    def path_for(self, item: StoredFile) -> Path: ...


@dataclass(frozen=True)
class FileLink:
    id: str
    entity_type: str
    entity_id: str
    purpose: str
    created_at: str
    file_id: str | None = None
    archived_at: str | None = None
    archive_reason: str | None = None


@dataclass(frozen=True)
class FileLinkWithFile:
    """A file link and the immutable metadata of its linked file."""

    id: str
    entity_type: str
    entity_id: str
    purpose: str
    created_at: str
    file_id: str
    archived_at: str | None
    archive_reason: str | None
    original_name: str
    media_type: str
    size_bytes: int
    content_sha256: str


class FileLinkReader(Protocol):
    """Transaction-aware reads of polymorphic file links."""

    def active_link_count(self, connection: Any, entity_type: str, entity_id: str) -> int: ...
    def has_active_available_link(self, connection: Any, entity_type: str, entity_id: str) -> bool: ...
    def active_available_link_count(self, connection: Any, entity_type: str, entity_id: str) -> int: ...
    def link_is_active_available(self, connection: Any, link_id: str) -> bool: ...
    def active_available_links(self, connection: Any, entity_type: str, entity_id: str) -> list[FileLink]: ...
    def links_for_entity(self, connection: Any, entity_type: str, entity_id: str) -> list[FileLink]: ...
    def links_for_entities(self, connection: Any, entity_type: str, entity_ids: Sequence[str]) -> dict[str, list[FileLinkWithFile]]: ...
    def active_link_predicate(self, entity_type: str, entity_id: Any) -> Any: ...
    def entity_ids_with_active_links(self, connection: Any, entity_type: str) -> set[str]: ...
    def active_linked_entity_ids(self, connection: Any, entity_type: str, entity_ids: Sequence[str]) -> set[str]: ...
    def active_link_counts_for_entities(self, connection: Any, entity_type: str, entity_ids: Sequence[str]) -> dict[str, int]: ...
    def active_link_counts_for_entity_groups(self, connection: Any, entity_ids_by_type: dict[str, Sequence[str]]) -> dict[tuple[str, str], int]: ...


@dataclass(frozen=True)
class FileAuditChange:
    entity_type: str
    entity_id: str
    action: str
    after: dict[str, object]
    reason: str
    correlation_id: str
    before: dict[str, object] | None = None


class FileLinkValidator(Protocol):
    """Owning-domain boundary for validating polymorphic file links."""

    entity_types: frozenset[str]

    def validate_create(self, connection: Any, link: FileLink) -> None: ...
    def validate_archive(self, connection: Any, link: FileLink) -> None: ...


class FileUnitOfWork(Protocol):
    """Persists explicit file/link business changes and their audit entries atomically."""

    def write(self, item: StoredFile, link: FileLink | None, audit_changes: list[FileAuditChange], validate_link: Callable[[Any, FileLink], None] | None = None) -> None: ...
    def get(self, file_id: str) -> StoredFile | None: ...
    def get_link(self, link_id: str) -> FileLink | None: ...
    def archive_link(self, link: FileLink, audit_change: FileAuditChange, validate_link: Callable[[Any, FileLink], None]) -> FileLink: ...

"""Ports for managed content and atomic file metadata writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from app.modules.files.domain.models import StoredFile
from app.modules.files.application.commands import FileCommandReceipt


class FileCommandTransaction(Protocol):
    def operation_by_key(self, key: str) -> FileCommandReceipt | None: ...
    def write_file(
        self,
        item: StoredFile,
        link: FileLink,
        changes: list[FileAuditChange],
        validate_link: Callable[[Any, FileLink], None],
    ) -> None: ...
    def get_link(self, link_id: str) -> FileLink | None: ...
    def archive_link(
        self,
        link: FileLink,
        change: FileAuditChange,
        validate_link: Callable[[Any, FileLink], None],
    ) -> None: ...
    def record_operation(self, receipt: FileCommandReceipt) -> None: ...


class StoredContent(Protocol):
    publication_id: str
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
    storage_state: str
    verified_at: str


class FileLinkReader(Protocol):
    """Transaction-aware reads of polymorphic file links."""

    def active_link_count(self, connection: Any, entity_type: str, entity_id: str) -> int: ...
    def has_active_available_link(
        self, connection: Any, entity_type: str, entity_id: str
    ) -> bool: ...
    def active_available_link_count(
        self, connection: Any, entity_type: str, entity_id: str
    ) -> int: ...
    def link_is_active_available(self, connection: Any, link_id: str) -> bool: ...
    def active_available_links(
        self, connection: Any, entity_type: str, entity_id: str
    ) -> list[FileLink]: ...
    def links_for_entity(
        self, connection: Any, entity_type: str, entity_id: str
    ) -> list[FileLink]: ...
    def links_with_files_for_ids(
        self, connection: Any, link_ids: Sequence[str]
    ) -> dict[str, FileLinkWithFile]: ...
    def links_for_entities(
        self, connection: Any, entity_type: str, entity_ids: Sequence[str]
    ) -> dict[str, list[FileLinkWithFile]]: ...
    def active_links_for_entities(
        self, connection: Any, entity_type: str, entity_ids: Sequence[str]
    ) -> dict[str, list[FileLinkWithFile]]: ...
    def active_link_predicate(self, entity_type: str, entity_id: Any) -> Any: ...
    def entity_ids_with_active_links(self, connection: Any, entity_type: str) -> set[str]: ...
    def active_linked_entity_ids(
        self, connection: Any, entity_type: str, entity_ids: Sequence[str]
    ) -> set[str]: ...
    def active_link_counts_for_entities(
        self, connection: Any, entity_type: str, entity_ids: Sequence[str]
    ) -> dict[str, int]: ...
    def active_link_counts_for_entity_groups(
        self, connection: Any, entity_ids_by_type: dict[str, Sequence[str]]
    ) -> dict[tuple[str, str], int]: ...
    def active_entity_ids_for_file(
        self, connection: Any, file_id: str, entity_type: str
    ) -> set[str]: ...


class FileVerificationConsequences(Protocol):
    """Owning-domain state changes caused by a verified storage transition."""

    def apply_storage_verification(
        self, connection: Any, file_id: str, storage_state: str, correlation_id: str
    ) -> None: ...


@dataclass(frozen=True)
class FileAuditChange:
    entity_type: str
    entity_id: str
    action: str
    after: dict[str, object]
    reason: str
    correlation_id: str
    before: dict[str, object] | None = None
    actor_kind: str = "local_operator"


class FileLinkValidator(Protocol):
    """Owning-domain boundary for validating polymorphic file links."""

    entity_types: frozenset[str]
    allows_generic_upload: bool

    def validate_create(self, connection: Any, link: FileLink) -> None: ...
    def validate_archive(self, connection: Any, link: FileLink) -> None: ...
    def validate_retained(self, connection: Any, link: FileLink) -> None: ...


class FileLinkPolicyRegistry:
    """One explicit policy composition for mutation and retained-data checks."""

    def __init__(self, validators: Sequence[FileLinkValidator]) -> None:
        self._by_entity_type: dict[str, FileLinkValidator] = {}
        for validator in validators:
            if not isinstance(getattr(validator, "allows_generic_upload", None), bool):
                raise ValueError(
                    "Every FILE-001 link policy must explicitly declare allows_generic_upload."
                )
            if not callable(getattr(validator, "validate_retained", None)):
                raise ValueError(
                    "Every FILE-001 link policy must implement retained-data validation."
                )
            for entity_type in validator.entity_types:
                if entity_type in self._by_entity_type:
                    raise ValueError(f"Duplicate FILE-001 policy for {entity_type}.")
                self._by_entity_type[entity_type] = validator

    def get(self, entity_type: str) -> FileLinkValidator | None:
        return self._by_entity_type.get(entity_type)

    def as_mapping(self) -> dict[str, FileLinkValidator]:
        return dict(self._by_entity_type)


class FileUnitOfWork(Protocol):
    """Persists explicit file/link business changes and their audit entries atomically."""

    def command(
        self, operation: Callable[[FileCommandTransaction], dict[str, object]]
    ) -> dict[str, object]: ...
    def command_receipt(
        self, *, operation_id: str | None = None, key: str | None = None
    ) -> FileCommandReceipt | None: ...

    def write(
        self,
        item: StoredFile,
        link: FileLink | None,
        audit_changes: list[FileAuditChange],
        validate_link: Callable[[Any, FileLink], None] | None = None,
    ) -> None: ...
    def get(self, file_id: str) -> StoredFile | None: ...
    def get_link(self, link_id: str) -> FileLink | None: ...
    def archive_link(
        self,
        link: FileLink,
        audit_change: FileAuditChange,
        validate_link: Callable[[Any, FileLink], None],
    ) -> FileLink: ...
    def link_existing(
        self,
        link: FileLink,
        audit_change: FileAuditChange,
        validate_link: Callable[[Any, FileLink], None],
    ) -> FileLink: ...
    def files_for_verification(self) -> list[StoredFile]: ...
    def replace_storage_verification(
        self,
        item: StoredFile,
        storage_state: str,
        verified_at: str,
        audit_change: FileAuditChange,
        consequences: FileVerificationConsequences | None = None,
    ) -> None: ...
    def record_cleanup_incomplete(
        self, publication_id: str, provider: str, correlation_id: str
    ) -> None: ...
    def record_cleanup_resolved(self, correlation_id: str) -> None: ...
    def outstanding_cleanup_attentions(self) -> list[dict[str, object]]: ...

"""Ports for managed content and atomic file metadata writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.modules.files.domain.models import StoredFile


class StoredContent(Protocol):
    relative_path: str
    size_bytes: int
    content_sha256: str
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class FileContentStore(Protocol):
    def store(self, source: Path) -> StoredContent: ...
    def path_for(self, relative_path: str, content_hash: str, size: int) -> Path: ...


@dataclass(frozen=True)
class FileLink:
    id: str
    entity_type: str
    entity_id: str
    purpose: str
    created_at: str


@dataclass(frozen=True)
class FileAuditChange:
    entity_type: str
    entity_id: str
    action: str
    after: dict[str, object]
    reason: str
    correlation_id: str


class FileUnitOfWork(Protocol):
    """Persists explicit file/link business changes and their audit entries atomically."""

    def write(self, item: StoredFile, link: FileLink | None, audit_changes: list[FileAuditChange]) -> None: ...
    def get(self, file_id: str) -> StoredFile | None: ...

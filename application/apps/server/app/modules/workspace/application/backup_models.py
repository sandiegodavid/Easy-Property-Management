"""Public types shared by local backup components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.modules.workspace.application.service import WorkspaceError
from app.modules.workspace.infrastructure.encrypted_archive import ArchiveContents

PackageType = Literal["backup", "export"]


class BackupError(WorkspaceError):
    """Raised when a backup, export, validation, or restore cannot complete safely."""


@dataclass(frozen=True)
class BackupResult:
    archive_path: Path
    archive_contents: ArchiveContents
    package_type: PackageType


@dataclass(frozen=True)
class RestoreResult:
    workspace_path: Path
    archive_contents: ArchiveContents

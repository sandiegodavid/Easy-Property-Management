"""Explicit workspace initialization and validation."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.modules.workspace.domain.models import WORKSPACE_FORMAT_VERSION, WorkspaceManifest
from app.modules.workspace.infrastructure.sqlite_store import SQLiteWorkspaceStore, WorkspaceDatabaseError
from app.platform.config import LocalConfig, load_local_config, repository_root
from app.platform.migrations import PlatformMigrationError
from typing import Callable, Protocol


class WorkspaceError(RuntimeError):
    """Raised when a configured workspace cannot be safely initialized or opened."""


class WorkspaceNotInitializedError(WorkspaceError):
    """Raised instead of silently creating a workspace during ordinary startup."""


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path

    @property
    def manifest(self) -> Path:
        return self.root / "workspace.json"

    @property
    def database(self) -> Path:
        return self.root / "database" / "property-management.sqlite"

    @property
    def files(self) -> Path:
        return self.root / "files"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def backups(self) -> Path:
        return self.root / "backups"


class MigrationRunner(Protocol):
    def apply(self, manifest: WorkspaceManifest) -> None: ...


MigrationRunnerFactory = Callable[[Path, Path], MigrationRunner]


class WorkspaceService:
    def __init__(self, config: LocalConfig, migration_runner_factory: MigrationRunnerFactory) -> None:
        self.config = config
        self.paths = WorkspacePaths(root=config.workspace_path)
        self.migration_runner_factory = migration_runner_factory

    @classmethod
    def from_local_config(cls, config_path: Path | None, migration_runner_factory: MigrationRunnerFactory) -> "WorkspaceService":
        return cls(load_local_config(config_path), migration_runner_factory)

    def initialize(self) -> WorkspaceManifest:
        """Explicitly create a new workspace or validate the one already at this path."""
        self._validate_external_location()
        if self.paths.manifest.exists():
            return self.open()

        if self.paths.root.exists() and any(self.paths.root.iterdir()):
            raise WorkspaceError(
                f"Workspace location is not empty and has no manifest: {self.paths.root}. "
                "Choose an empty folder or open a valid existing workspace."
            )

        manifest = WorkspaceManifest(
            workspace_id=str(uuid4()),
            format_version=WORKSPACE_FORMAT_VERSION,
            created_at=datetime.now(UTC),
            database_path="database/property-management.sqlite",
        )
        staging_paths = WorkspacePaths(root=self._staging_root())
        try:
            self._create_workspace_layout(staging_paths)
            SQLiteWorkspaceStore(staging_paths.database).initialize(manifest)
            self._apply_platform_migrations(staging_paths, manifest)
            self._secure_file(staging_paths.database)
            self._write_manifest(staging_paths, manifest)
            self._publish_staging_workspace(staging_paths)
        except (OSError, WorkspaceDatabaseError, PlatformMigrationError) as error:
            self._discard_staging_workspace(staging_paths)
            raise WorkspaceError(f"Unable to initialize workspace at {self.paths.root}: {error}") from error
        return self.open()

    def open(self, *, integrity_check: bool = False, migrate: bool = False) -> WorkspaceManifest:
        """Validate an existing workspace and enforce private local permissions."""
        self._validate_external_location()
        if not self.paths.manifest.is_file():
            raise WorkspaceNotInitializedError(
                f"No workspace manifest found at {self.paths.manifest}. "
                "Run initialize-workspace explicitly or select an existing workspace."
            )
        try:
            raw_manifest = json.loads(self.paths.manifest.read_text(encoding="utf-8"))
            manifest = WorkspaceManifest.from_dict(raw_manifest)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise WorkspaceError(f"Workspace manifest is invalid: {error}") from error

        if manifest.format_version != WORKSPACE_FORMAT_VERSION:
            raise WorkspaceError(
                f"Unsupported workspace format {manifest.format_version}; "
                f"this version supports {WORKSPACE_FORMAT_VERSION}."
            )
        if manifest.database_path != "database/property-management.sqlite":
            raise WorkspaceError("Workspace manifest points to an unsupported database location.")

        try:
            SQLiteWorkspaceStore(self.paths.database).verify(manifest, integrity_check=integrity_check)
            if migrate:
                self._apply_platform_migrations(self.paths, manifest)
        except (WorkspaceDatabaseError, PlatformMigrationError) as error:
            raise WorkspaceError(f"Workspace database is invalid: {error}") from error
        try:
            self._secure_existing_workspace_paths()
        except OSError as error:
            raise WorkspaceError(f"Unable to secure workspace permissions: {error}") from error
        return manifest

    def _apply_platform_migrations(self, paths: WorkspacePaths, manifest: WorkspaceManifest) -> None:
        self.migration_runner_factory(paths.database, paths.backups).apply(manifest)

    def _validate_external_location(self) -> None:
        repository_path = repository_root().resolve()
        workspace_path = self.paths.root.resolve()
        if workspace_path == repository_path or repository_path in workspace_path.parents:
            raise WorkspaceError(
                "localWorkspacePath must point outside the Git repository to keep user data out of version control."
            )

    def _staging_root(self) -> Path:
        return self.paths.root.parent / f".{self.paths.root.name}.initializing.{uuid4().hex}"

    def _create_workspace_layout(self, paths: WorkspacePaths) -> None:
        for directory in (paths.root, paths.database.parent, paths.files, paths.exports, paths.backups):
            self._secure_directory(directory)

    def _publish_staging_workspace(self, staging_paths: WorkspacePaths) -> None:
        if self.paths.root.exists():
            self.paths.root.rmdir()
        staging_paths.root.replace(self.paths.root)
        self._secure_existing_workspace_paths()

    def _discard_staging_workspace(self, staging_paths: WorkspacePaths) -> None:
        if staging_paths.root.exists():
            shutil.rmtree(staging_paths.root, ignore_errors=True)

    def _secure_existing_workspace_paths(self) -> None:
        self._secure_directory(self.paths.root)
        for directory in (self.paths.database.parent, self.paths.files, self.paths.exports, self.paths.backups):
            if directory.exists():
                self._secure_directory(directory)
        for file_path in (
            self.paths.manifest,
            self.paths.database,
            self.paths.database.with_name(f"{self.paths.database.name}-wal"),
            self.paths.database.with_name(f"{self.paths.database.name}-shm"),
        ):
            if file_path.exists():
                self._secure_file(file_path)

    @staticmethod
    def _secure_directory(directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            directory.chmod(0o700)

    @staticmethod
    def _secure_file(file_path: Path) -> None:
        if os.name == "posix":
            file_path.chmod(0o600)

    def _write_manifest(self, paths: WorkspacePaths, manifest: WorkspaceManifest) -> None:
        temporary_manifest = paths.manifest.with_name(f".{paths.manifest.name}.{uuid4().hex}.tmp")
        temporary_manifest.write_text(
            json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self._secure_file(temporary_manifest)
        temporary_manifest.replace(paths.manifest)
        self._secure_file(paths.manifest)

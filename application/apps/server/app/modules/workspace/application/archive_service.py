"""Packaging and complete validation of encrypted workspace archives."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from app.modules.workspace.application.backup_models import BackupError, BackupResult, PackageType
from app.modules.workspace.application.backup_policy import secure_directory, secure_file
from app.modules.workspace.application.service import WorkspaceError, WorkspacePaths, WorkspaceService
from app.modules.workspace.domain.models import WorkspaceManifest
from app.modules.workspace.infrastructure.encrypted_archive import (
    ARCHIVE_FORMAT_VERSION,
    ArchiveContents,
    ArchiveError,
    create_payload_zip,
    decrypt_archive_to_zip,
    extract_payload_zip,
    file_inventory,
    inspect_payload_zip,
    make_header,
    write_encrypted_archive,
)
from app.platform.config import LocalConfig


class WorkspaceArchiveService:
    def __init__(self, workspace_service: WorkspaceService) -> None:
        self.workspace_service = workspace_service

    @property
    def paths(self) -> WorkspacePaths:
        return self.workspace_service.paths

    def validate_workspace(self) -> WorkspaceManifest:
        manifest = self.workspace_service.open(integrity_check=True)
        self.assert_safe_file_tree(self.paths.files)
        return manifest

    def create(
        self,
        passphrase: str,
        package_type: PackageType,
        output_path: Path,
        *,
        validated_manifest: WorkspaceManifest | None = None,
    ) -> BackupResult:
        manifest = validated_manifest or self.validate_workspace()
        archive_written = False
        try:
            with tempfile.TemporaryDirectory(prefix="epm-package-", dir=self.paths.root.parent) as temporary_directory:
                root = Path(temporary_directory)
                payload = root / "payload"
                self._stage_live_workspace(payload)
                package_manifest = self._package_manifest(manifest, package_type, payload)
                (payload / "backup-manifest.json").write_text(
                    json.dumps(package_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                secure_file(payload / "backup-manifest.json")
                zip_path = root / "payload.zip"
                create_payload_zip(payload, zip_path)
                contents: ArchiveContents | None = None

                def validate_temporary_archive(temporary_archive: Path) -> None:
                    nonlocal contents
                    contents = self.validate_archive(temporary_archive, passphrase)

                write_encrypted_archive(
                    zip_path,
                    output_path,
                    make_header(workspace_id=manifest.workspace_id, package_type=package_type),
                    passphrase,
                    validator=validate_temporary_archive,
                )
                archive_written = True
                if contents is None:
                    raise BackupError("Archive validation did not return a result.")
        except (ArchiveError, OSError, sqlite3.Error) as error:
            if archive_written:
                output_path.unlink(missing_ok=True)
            raise BackupError(f"Unable to create {package_type}: {error}") from error
        except BackupError:
            if archive_written:
                output_path.unlink(missing_ok=True)
            raise
        return BackupResult(archive_path=output_path, archive_contents=contents, package_type=package_type)

    def validate_archive(self, archive_path: Path, passphrase: str) -> ArchiveContents:
        try:
            with tempfile.TemporaryDirectory(prefix="epm-archive-validation-") as temporary_directory:
                root = Path(temporary_directory)
                zip_path = root / "payload.zip"
                header = decrypt_archive_to_zip(archive_path.expanduser().resolve(), passphrase, zip_path)
                contents = inspect_payload_zip(zip_path, header)
                workspace_root = root / "workspace"
                workspace_root.mkdir(mode=0o700)
                extract_payload_zip(zip_path, workspace_root, contents)
                self.validate_extracted_workspace(workspace_root, contents)
                return contents
        except (ArchiveError, BackupError, WorkspaceError, OSError, sqlite3.Error) as error:
            raise BackupError(f"Archive validation failed: {error}") from error

    def validate_extracted_workspace(self, workspace_root: Path, contents: ArchiveContents) -> WorkspaceManifest:
        extracted = [{**item, "path": f"workspace/{item['path']}"} for item in file_inventory(workspace_root)]
        if extracted != contents.manifest["files"]:
            raise BackupError("Restored files do not match the validated archive inventory.")
        self._create_runtime_directories(workspace_root)
        service = WorkspaceService(LocalConfig(config_path=self.workspace_service.config.config_path, workspace_path=workspace_root))
        try:
            manifest = service.open(integrity_check=True)
        except WorkspaceError as error:
            raise BackupError(f"Restored workspace is invalid: {error}") from error
        if manifest.workspace_id != contents.header["sourceWorkspaceId"]:
            raise BackupError("Archive workspace identity does not match its encrypted package.")
        self.assert_safe_file_tree(WorkspacePaths(workspace_root).files)
        return manifest

    def _stage_live_workspace(self, payload: Path) -> None:
        workspace = payload / "workspace"
        database = workspace / "database"
        files = workspace / "files"
        database.mkdir(parents=True)
        files.mkdir(parents=True)
        for directory in (workspace, database, files):
            secure_directory(directory)
        shutil.copy2(self.paths.manifest, workspace / "workspace.json")
        secure_file(workspace / "workspace.json")
        try:
            with closing(sqlite3.connect(self.paths.database)) as source, closing(sqlite3.connect(database / self.paths.database.name)) as snapshot:
                source.backup(snapshot)
        except sqlite3.Error as error:
            raise BackupError(f"Unable to create a consistent SQLite snapshot: {error}") from error
        secure_file(database / self.paths.database.name)
        self.assert_safe_file_tree(self.paths.files)
        for source_file in self.paths.files.rglob("*"):
            if source_file.is_dir():
                continue
            target = files / source_file.relative_to(self.paths.files)
            target.parent.mkdir(parents=True, exist_ok=True)
            secure_directory(target.parent)
            shutil.copy2(source_file, target)
            secure_file(target)

    @staticmethod
    def assert_safe_file_tree(root: Path) -> None:
        if not root.is_dir():
            raise BackupError("Workspace attachments directory is missing.")
        if root.is_symlink():
            raise BackupError("Workspace files directory must not be a symbolic link.")
        for path in root.rglob("*"):
            if path.is_symlink():
                raise BackupError("Workspace attachments must not contain symbolic links.")
            if not path.is_file() and not path.is_dir():
                raise BackupError("Workspace attachments contain an unsupported file type.")

    @staticmethod
    def _create_runtime_directories(root: Path) -> None:
        for directory in (root / "database", root / "files", root / "exports", root / "backups"):
            directory.mkdir(parents=True, exist_ok=True)
            secure_directory(directory)
        secure_directory(root)

    @staticmethod
    def _package_manifest(manifest: WorkspaceManifest, package_type: PackageType, payload: Path) -> dict[str, object]:
        return {
            "applicationVersion": "0.1.0", "credentialsExcluded": True, "createdAt": datetime.now(UTC).isoformat(),
            "files": file_inventory(payload), "liveJournalFilesExcluded": True, "packageFormatVersion": ARCHIVE_FORMAT_VERSION,
            "packageType": package_type, "schemaVersion": manifest.format_version, "sourceWorkspaceId": manifest.workspace_id,
        }

"""Coordinator for local encrypted backup, restore, and automatic scheduling workflows."""

from __future__ import annotations

import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.modules.workspace.application.archive_service import WorkspaceArchiveService
from app.modules.workspace.application.backup_models import BackupError, BackupResult, PackageType, RestoreResult
from app.modules.workspace.application.backup_policy import BackupDestinationPolicy, WorkspaceLockCoordinator
from app.modules.workspace.application.backup_state import BackupStateStore
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.infrastructure.encrypted_archive import (
    ArchiveContents,
    ArchiveError,
    decrypt_archive_to_zip,
    extract_payload_zip,
    inspect_payload_zip,
)
from app.platform.secrets import BackupSecretStore, KeyringBackupSecretStore, SecretStoreError


class BackupService:
    """Coordinates focused archive, state, policy, and restore collaborators."""

    def __init__(self, workspace_service: WorkspaceService, secret_store: BackupSecretStore | None = None) -> None:
        self.workspace_service = workspace_service
        self.secret_store = secret_store or KeyringBackupSecretStore()
        self.archives = WorkspaceArchiveService(workspace_service)
        self.destinations = BackupDestinationPolicy(workspace_service)
        self.locks = WorkspaceLockCoordinator(workspace_service.paths)
        self.state = BackupStateStore(workspace_service.paths.backups)

    def configure_destination(self, destination_path: Path):
        with self.locks.operation():
            self.workspace_service.open()
            return self.destinations.configure(destination_path)

    def validate_workspace(self):
        with self.locks.operation():
            return self.archives.validate_workspace()

    def create_backup(self, passphrase: str, *, package_type: PackageType = "backup", output_path: Path | None = None) -> BackupResult:
        with self.locks.operation():
            manifest = self.archives.validate_workspace()
            archive_path = self.destinations.resolve_output(manifest.workspace_id, package_type, output_path)
            result = self.archives.create(
                passphrase,
                package_type,
                archive_path,
                validated_manifest=manifest,
            )
            if package_type == "backup":
                self.state.record_success(result)
                self.state.apply_retention(manifest.workspace_id, archive_path.parent)
            return result

    def validate_archive(self, archive_path: Path, passphrase: str) -> ArchiveContents:
        return self.archives.validate_archive(archive_path, passphrase)

    def restore(self, archive_path: Path, passphrase: str, destination_path: Path) -> RestoreResult:
        destination = destination_path.expanduser().resolve()
        self.destinations.validate_restore_destination(destination)
        with self.locks.restore(destination):
            self.destinations.validate_restore_destination(destination)
            return self._restore_archive(archive_path, passphrase, destination)

    def _restore_archive(self, archive_path: Path, passphrase: str, destination: Path) -> RestoreResult:
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.parent / f".{destination.name}.restoring.{uuid4().hex}"
        try:
            with tempfile.TemporaryDirectory(prefix="epm-restore-archive-", dir=destination.parent) as temporary:
                zip_path = Path(temporary) / "payload.zip"
                header = decrypt_archive_to_zip(archive_path.expanduser().resolve(), passphrase, zip_path)
                contents = inspect_payload_zip(zip_path, header)
                staging.mkdir(mode=0o700)
                extract_payload_zip(zip_path, staging, contents)
            manifest = self.archives.validate_extracted_workspace(staging, contents)
            if manifest.workspace_id != contents.header["sourceWorkspaceId"]:
                raise BackupError("Restored workspace identity does not match the encrypted package.")
            staging.replace(destination)
            return RestoreResult(workspace_path=destination, archive_contents=contents)
        except (ArchiveError, BackupError, OSError) as error:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise BackupError(f"Restore failed without changing the active workspace: {error}") from error

    def enable_automatic_backups(self, passphrase: str) -> None:
        with self.locks.operation():
            manifest = self.archives.validate_workspace()
            self.destinations.require_configured()
            try:
                self.secret_store.set_passphrase(manifest.workspace_id, passphrase)
            except SecretStoreError as error:
                raise BackupError(str(error)) from error
            state = self.state.load()
            state["automaticEnabled"] = True
            state["nextAutomaticBackupAt"] = datetime.now(UTC).isoformat()
            self.state.save(state)

    def disable_automatic_backups(self) -> None:
        with self.locks.operation():
            manifest = self.workspace_service.open()
            try:
                self.secret_store.delete_passphrase(manifest.workspace_id)
            except SecretStoreError as error:
                raise BackupError(str(error)) from error
            state = self.state.load()
            state["automaticEnabled"] = False
            state.pop("nextAutomaticBackupAt", None)
            self.state.save(state)

    def run_due_automatic_backup(self) -> BackupResult | None:
        with self.locks.operation():
            state = self.state.load()
            due_at = self._parse_time(state.get("nextAutomaticBackupAt"))
            if not state.get("automaticEnabled") or (due_at and due_at > datetime.now(UTC)):
                return None
            try:
                manifest = self.archives.validate_workspace()
                passphrase = self.secret_store.get_passphrase(manifest.workspace_id)
                if not passphrase:
                    raise BackupError("Automatic backup credential is unavailable.")
                archive_path = self.destinations.resolve_output(manifest.workspace_id, "backup", None)
                result = self.archives.create(
                    passphrase,
                    "backup",
                    archive_path,
                    validated_manifest=manifest,
                )
                self.state.record_success(result)
                self.state.apply_retention(manifest.workspace_id, archive_path.parent)
                return result
            except SecretStoreError as error:
                self._raise_recorded_failure(str(error))
            except BackupError as error:
                self._raise_recorded_failure(str(error))

    def backup_status(self) -> dict[str, Any]:
        with self.locks.operation():
            return self.state.status()

    def _raise_recorded_failure(self, reason: str) -> None:
        self.state.record_failure(reason)
        raise BackupError(f"Automatic backup failed: {reason}")

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

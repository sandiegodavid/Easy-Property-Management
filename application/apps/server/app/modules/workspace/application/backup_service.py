"""Coordinator for local encrypted backup, restore, and automatic scheduling workflows."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from app.modules.workspace.application.archive_service import WorkspaceArchiveService
from app.modules.workspace.application.backup_models import BackupError, BackupResult, PackageType, RestoreResult
from app.modules.workspace.application.backup_policy import BackupDestinationPolicy, WorkspaceLockCoordinator
from app.modules.workspace.application.backup_state import BackupStateStore, RetentionExecutionError
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.infrastructure.sqlite_store import SQLiteWorkspaceStore
from app.platform.product_migrations import validate_latest_schema
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.workspace.infrastructure.encrypted_archive import (
    ArchiveContents,
    ArchiveError,
    decrypt_archive_to_zip,
    extract_payload_zip,
    inspect_payload_zip,
    require_passphrase,
)
from app.platform.secrets import BackupSecretStore, KeyringBackupSecretStore, SecretStoreError


class BackupService:
    """Coordinates focused archive, state, policy, and restore collaborators."""

    def __init__(self, workspace_service: WorkspaceService, audit_recorder: AuditRecorder,
                 restored_audit_recorder: Callable[[Path], AuditRecorder], secret_store: BackupSecretStore | None = None,
                 remote_materializer=None) -> None:
        self.workspace_service = workspace_service
        self.secret_store = secret_store or KeyringBackupSecretStore()
        self.archives = WorkspaceArchiveService(workspace_service, remote_materializer)
        self.destinations = BackupDestinationPolicy(workspace_service)
        self.locks = WorkspaceLockCoordinator(workspace_service.paths)
        self.state = BackupStateStore(workspace_service.paths.backups)
        self.audit_recorder = audit_recorder
        self.restored_audit_recorder = restored_audit_recorder

    def configure_destination(self, destination_path: Path):
        with self.locks.operation():
            self.workspace_service.open()
            return self.destinations.configure(destination_path)

    def validate_workspace(self):
        with self.locks.operation():
            return self.archives.validate_workspace()

    def create_backup(self, passphrase: str, *, package_type: PackageType = "backup", output_path: Path | None = None) -> BackupResult:
        with self.locks.operation():
            archive_path: Path | None = None
            archive_published = False
            correlation_id = str(uuid4())
            try:
                manifest = self.archives.validate_workspace()
                archive_path = self.destinations.resolve_output(manifest.workspace_id, package_type, output_path)
                result = self.archives.create(passphrase, package_type, archive_path, validated_manifest=manifest)
                archive_published = True
                self._audit("backup_operation", result.archive_path.name, f"{package_type}_created", {
                    "archiveName": result.archive_path.name, "packageType": package_type, "automatic": False,
                }, correlation_id)
                self.state.record_success(result, automatic=False)
            except BackupError as error:
                if archive_published:
                    self._remove_failed_archive(archive_path)
                self.state.record_failure(
                    str(error), package_type, automatic=False,
                    destination=archive_path.parent if archive_path else None,
                    archive_name=archive_path.name if archive_path else None,
                )
                try:
                    self._audit("backup_operation", archive_path.name if archive_path else str(uuid4()), f"{package_type}_failed", {
                        "packageType": package_type, "automatic": False, "reason": str(error),
                    }, correlation_id)
                except BackupError:
                    # The original operation has already failed and its archive was removed.
                    pass
                raise
            if package_type == "backup":
                self._apply_retention(result, manifest.workspace_id, correlation_id)
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
            self._audit_restored_workspace(staging, contents)
            restored_database = staging / "database" / "property-management.sqlite"
            SQLiteWorkspaceStore(restored_database).verify(manifest, integrity_check=True)
            validate_latest_schema(restored_database)
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
                require_passphrase(passphrase)
            except ArchiveError as error:
                raise BackupError(str(error)) from error
            try:
                previous = self.secret_store.get_passphrase(manifest.workspace_id)
                self.secret_store.set_passphrase(manifest.workspace_id, passphrase)
                self.state.configure_automatic(True)
            except SecretStoreError as error:
                raise BackupError(str(error)) from error
            except BackupError as error:
                try:
                    if previous is None:
                        self.secret_store.delete_passphrase(manifest.workspace_id)
                    else:
                        self.secret_store.set_passphrase(manifest.workspace_id, previous)
                except SecretStoreError as compensation_error:
                    raise BackupError(
                        "Automatic backup configuration may be inconsistent; rerun configuration to repair it."
                    ) from compensation_error
                raise error

    def disable_automatic_backups(self) -> None:
        with self.locks.operation():
            manifest = self.workspace_service.open()
            try:
                previous = self.secret_store.get_passphrase(manifest.workspace_id)
                self.secret_store.delete_passphrase(manifest.workspace_id)
                self.state.configure_automatic(False)
            except SecretStoreError as error:
                raise BackupError(str(error)) from error
            except BackupError as error:
                try:
                    if previous is not None:
                        self.secret_store.set_passphrase(manifest.workspace_id, previous)
                except SecretStoreError as compensation_error:
                    raise BackupError(
                        "Automatic backup configuration may be inconsistent; rerun configuration to repair it."
                    ) from compensation_error
                raise error

    def run_due_automatic_backup(self) -> BackupResult | None:
        with self.locks.operation():
            state = self.state.load()
            correlation_id = str(uuid4())
            archive_path: Path | None = None
            archive_published = False
            due_at = state.next_automatic_backup_at
            if not state.automatic_enabled or (due_at and due_at > datetime.now(UTC)):
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
                archive_published = True
                self._audit("backup_operation", result.archive_path.name, "backup_created", {
                    "archiveName": result.archive_path.name, "packageType": "backup", "automatic": True,
                }, correlation_id)
                self.state.record_success(result, automatic=True)
            except SecretStoreError as error:
                if archive_published:
                    self._remove_failed_archive(archive_path)
                self._raise_recorded_failure(str(error), "backup", correlation_id, archive_path)
            except BackupError as error:
                if archive_published:
                    self._remove_failed_archive(archive_path)
                self._raise_recorded_failure(str(error), "backup", correlation_id, archive_path)
            self._apply_retention(result, manifest.workspace_id, correlation_id)
            return result

    def backup_status(self) -> dict[str, Any]:
        with self.locks.operation():
            return self.state.status()

    def _raise_recorded_failure(self, reason: str, package_type: PackageType, correlation_id: str,
                                archive_path: Path | None = None) -> None:
        self.state.record_failure(reason, package_type, automatic=True)
        try:
            self._audit("backup_operation", archive_path.name if archive_path else str(uuid4()), f"{package_type}_failed", {
                "packageType": package_type, "automatic": True, "reason": reason,
            }, correlation_id)
        except BackupError:
            pass
        raise BackupError(f"Automatic backup failed: {reason}")

    def _apply_retention(self, result: BackupResult, workspace_id: str, correlation_id: str) -> None:
        """Retention does not change a successfully validated backup outcome."""
        try:
            recovered = self.state.recover_pending_retention()
            if recovered is not None:
                self._audit("backup_retention", recovered.audit_event_id, recovered.audit_action,
                            recovered.audit_after, recovered.correlation_id, event_id=recovered.audit_event_id,
                            occurred_at=recovered.occurred_at)
                self.state.complete_retention_audit(recovered.audit_event_id)
            retention = self.state.apply_retention(
                workspace_id, result.archive_path.parent, correlation_id=correlation_id,
                archive_name=result.archive_path.name,
            )
        except RetentionExecutionError as error:
            try:
                self.state.record_retention_failure(str(error))
            except BackupError:
                pass
            try:
                pending = self.state.recover_pending_retention()
            except BackupError as recovery_error:
                self._record_retention_audit_failure(
                    f"{error}; retention recovery is pending: {recovery_error}", correlation_id, error.result
                )
                return
            self._record_retention_audit_failure(str(error), correlation_id, error.result)
            return
        except (BackupError, OSError) as error:
            try:
                self.state.record_retention_failure(str(error))
            except BackupError:
                # The archive result is already durable and validated. Retention state is best-effort.
                pass
            self._record_retention_audit_failure(str(error), correlation_id)
            return
        try:
            pending = self.state.recover_pending_retention()
            if pending is None:
                raise BackupError("Retention audit journal is unavailable.")
            self._audit("backup_retention", pending.audit_event_id, pending.audit_action,
                        pending.audit_after, correlation_id, event_id=pending.audit_event_id,
                        occurred_at=pending.occurred_at)
            self.state.complete_retention_audit(pending.audit_event_id)
        except BackupError as error:
            try:
                self.state.record_retention_failure(f"Retention audit could not be recorded: {error}")
            except BackupError:
                pass

    def _record_retention_audit_failure(self, reason: str, correlation_id: str,
                                        result: object | None = None) -> None:
        """Retention telemetry must not reverse an already durable backup result."""
        try:
            details: dict[str, object] = {"reason": reason}
            if result is not None:
                details["partialOutcome"] = result.to_dict()
            self._audit("backup_retention", str(uuid4()), "partial" if result is not None else "failed", details,
                        correlation_id)
        except BackupError:
            pass

    def record_scheduler_failure(self, error: Exception) -> None:
        """Expose an unexpected worker crash in durable backup status before retrying."""
        reason = f"Automatic backup worker failed unexpectedly: {error}"
        try:
            with self.locks.operation():
                self.state.record_failure(reason, "backup", automatic=True)
        except BackupError:
            # The scheduler still retries; the log preserves a failure when state storage is unavailable.
            pass

    @staticmethod
    def _remove_failed_archive(archive_path: Path | None) -> None:
        if archive_path is None:
            return
        try:
            archive_path.unlink(missing_ok=True)
        except OSError as error:
            raise BackupError(f"Published archive could not be removed after a failed operation: {error}") from error

    def _audit(self, entity_type: str, entity_id: str, action: str, after: dict[str, object], correlation_id: str,
               *, event_id: str | None = None, occurred_at: datetime | None = None) -> None:
        try:
            with sqlite3.connect(self.workspace_service.paths.database) as connection:
                self.audit_recorder.record_change(connection, entity_type=entity_type, entity_id=entity_id,
                                                  action=action, before=None, after=after,
                                                  actor_kind="system", reason="backup_operation",
                                                  correlation_id=correlation_id, event_id=event_id,
                                                  occurred_at=occurred_at)
        except sqlite3.IntegrityError as error:
            if event_id is not None:
                with sqlite3.connect(self.workspace_service.paths.database) as connection:
                    row = connection.execute(
                        "SELECT entity_type, entity_id, action, before_snapshot, after_snapshot, "
                        "actor_kind, reason, correlation_id FROM audit_events WHERE id = ?",
                        (event_id,),
                    ).fetchone()
                    expected = (
                        entity_type, entity_id, action, _audit_json(None), _audit_json(after),
                        "system", "backup_operation", correlation_id,
                    )
                    if row == expected:
                        return
            raise BackupError(f"Operational audit could not be recorded: {error}") from error
        except sqlite3.Error as error:
            raise BackupError(f"Operational audit could not be recorded: {error}") from error

    def _audit_restored_workspace(self, destination: Path, contents: ArchiveContents) -> None:
        database = destination / "database" / "property-management.sqlite"
        try:
            recorder = self.restored_audit_recorder(database)
            with sqlite3.connect(database) as connection:
                recorder.record_change(connection, entity_type="workspace_restore",
                                       entity_id=contents.header["sourceWorkspaceId"], action="restored",
                                       before=None, after={"packageType": contents.header["packageType"]},
                                       actor_kind="system", reason="workspace_restored",
                                       correlation_id=str(uuid4()))
        except sqlite3.Error as error:
            raise BackupError(f"Restored workspace audit record could not be written: {error}") from error


def _audit_json(value: object) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

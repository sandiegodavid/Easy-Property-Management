from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.modules.workspace.application.backup_service import BackupError, BackupService
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.infrastructure.encrypted_archive import decrypt_archive_to_zip, make_header, write_encrypted_archive
from app.platform.config import LocalConfig
from app.platform.migrations import build_bootstrap_migration_runner
from app.platform.locking import WorkspaceOperationLock
from app.platform.secrets import BackupSecretStore


PASSPHRASE = "a long test backup passphrase"


class MemorySecretStore(BackupSecretStore):
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_passphrase(self, workspace_id: str) -> str | None:
        return self.values.get(workspace_id)

    def set_passphrase(self, workspace_id: str, passphrase: str) -> None:
        self.values[workspace_id] = passphrase

    def delete_passphrase(self, workspace_id: str) -> None:
        self.values.pop(workspace_id, None)


class BackupServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.workspace_path = self.root / "workspace"
        self.backup_path = self.root / "encrypted-backups"
        self.config_path = self.root / "config.local.json"
        self.config_path.write_text(json.dumps({"localWorkspacePath": str(self.workspace_path)}), encoding="utf-8")
        config = LocalConfig(
            config_path=self.config_path,
            workspace_path=self.workspace_path,
            backup_destination_path=self.backup_path,
        )
        self.workspace = WorkspaceService(config, build_bootstrap_migration_runner)
        self.manifest = self.workspace.initialize()
        self.secrets = MemorySecretStore()
        self.backups = BackupService(self.workspace, self.secrets)

    def test_encrypted_backup_validates_and_restores_to_a_new_workspace(self) -> None:
        attachment = self.workspace.paths.files / "receipts" / "january.txt"
        attachment.parent.mkdir()
        attachment.write_text("rent receipt", encoding="utf-8")

        result = self.backups.create_backup(PASSPHRASE)

        self.assertTrue(result.archive_path.is_file())
        self.assertEqual(result.archive_contents.manifest["sourceWorkspaceId"], self.manifest.workspace_id)
        self.assertNotEqual(result.archive_path.read_bytes()[:2], b"PK")
        self.assertEqual(self.backups.validate_archive(result.archive_path, PASSPHRASE).file_count, 3)

        restored_path = self.root / "restored-workspace"
        restored = self.backups.restore(result.archive_path, PASSPHRASE, restored_path)
        self.assertEqual(restored.workspace_path, restored_path.resolve())
        self.assertEqual((restored_path / "files" / "receipts" / "january.txt").read_text(encoding="utf-8"), "rent receipt")
        restored_service = WorkspaceService(LocalConfig(self.config_path, restored_path), build_bootstrap_migration_runner)
        self.assertEqual(restored_service.open().workspace_id, self.manifest.workspace_id)

    def test_wrong_passphrase_or_tampered_archive_is_rejected(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        with self.assertRaises(BackupError):
            self.backups.validate_archive(result.archive_path, "wrong passphrase")

        contents = bytearray(result.archive_path.read_bytes())
        contents[-1] ^= 1
        result.archive_path.write_bytes(contents)
        with self.assertRaises(BackupError):
            self.backups.validate_archive(result.archive_path, PASSPHRASE)

    def test_validation_rejects_an_authenticated_archive_with_a_corrupt_database(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        corrupted_archive = self.backup_path / "corrupt-database.epm-backup"
        with tempfile.TemporaryDirectory() as temporary_directory:
            zip_path = Path(temporary_directory) / "payload.zip"
            decrypt_archive_to_zip(result.archive_path, PASSPHRASE, zip_path)
            with zipfile.ZipFile(zip_path) as package:
                files = {
                    info.filename: package.read(info.filename)
                    for info in package.infolist()
                    if not info.is_dir()
                }
            database_path = "workspace/database/property-management.sqlite"
            files[database_path] = b"not a SQLite database"
            manifest = json.loads(files["backup-manifest.json"])
            for item in manifest["files"]:
                if item["path"] == database_path:
                    item["bytes"] = len(files[database_path])
                    item["sha256"] = hashlib.sha256(files[database_path]).hexdigest()
            files["backup-manifest.json"] = (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as package:
                for path, contents in files.items():
                    package.writestr(path, contents)
            write_encrypted_archive(
                zip_path,
                corrupted_archive,
                make_header(workspace_id=self.manifest.workspace_id, package_type="backup"),
                PASSPHRASE,
            )

        with self.assertRaisesRegex(BackupError, "SQLite"):
            self.backups.validate_archive(corrupted_archive, PASSPHRASE)

    def test_backup_destination_cannot_be_inside_the_live_workspace(self) -> None:
        with self.assertRaises(BackupError):
            self.backups.create_backup(PASSPHRASE, output_path=self.workspace.paths.backups / "unsafe")

    def test_automatic_backup_is_opt_in_and_uses_the_secret_store(self) -> None:
        self.backups.enable_automatic_backups(PASSPHRASE)
        self.assertEqual(self.secrets.get_passphrase(self.manifest.workspace_id), PASSPHRASE)

        result = self.backups.run_due_automatic_backup()
        self.assertIsNotNone(result)
        self.assertIsNone(self.backups.run_due_automatic_backup())
        self.assertTrue(self.backups.backup_status()["automaticEnabled"])

        self.backups.disable_automatic_backups()
        self.assertIsNone(self.secrets.get_passphrase(self.manifest.workspace_id))
        self.assertFalse(self.backups.backup_status()["automaticEnabled"])

    def test_automatic_backup_failure_is_not_reported_as_not_due(self) -> None:
        self.backups.enable_automatic_backups(PASSPHRASE)
        self.secrets.delete_passphrase(self.manifest.workspace_id)

        with self.assertRaisesRegex(BackupError, "Automatic backup failed"):
            self.backups.run_due_automatic_backup()

        self.assertEqual(self.backups.backup_status()["lastFailure"], "Automatic backup credential is unavailable.")

    @unittest.skipUnless(os.name == "posix", "POSIX permission modes are not available")
    def test_existing_backup_destination_permissions_are_not_changed(self) -> None:
        self.backup_path.mkdir()
        self.backup_path.chmod(0o755)

        self.backups.configure_destination(self.backup_path)

        self.assertEqual(self.backup_path.stat().st_mode & 0o777, 0o755)

    def test_workspace_operations_fail_fast_when_another_process_holds_the_lock(self) -> None:
        lock_path = self.workspace_path.parent / f".{self.workspace_path.name}.operations.lock"
        with WorkspaceOperationLock(lock_path):
            with self.assertRaises(BackupError):
                self.backups.create_backup(PASSPHRASE)

    def test_restore_does_not_require_the_configured_workspace_to_be_available(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        unavailable_workspace = self.root / "unavailable-workspace"
        self.workspace_path.replace(unavailable_workspace)

        restored_path = self.root / "restored-after-loss"
        restored = self.backups.restore(result.archive_path, PASSPHRASE, restored_path)

        self.assertEqual(restored.workspace_path, restored_path.resolve())
        self.assertTrue((restored_path / "database" / "property-management.sqlite").is_file())

    def test_restore_rejects_an_internal_destination_without_creating_lock_artifacts(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        destination = self.workspace.paths.files / "must-not-create"

        with self.assertRaises(BackupError):
            self.backups.restore(result.archive_path, PASSPHRASE, destination)

        self.assertFalse(destination.exists())

    def test_restore_respects_the_active_workspace_operation_lock_when_available(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        lock_path = self.workspace_path.parent / f".{self.workspace_path.name}.operations.lock"
        with WorkspaceOperationLock(lock_path):
            with self.assertRaises(BackupError):
                self.backups.restore(result.archive_path, PASSPHRASE, self.root / "restored-workspace")

    def test_restore_decrypts_the_archive_once(self) -> None:
        result = self.backups.create_backup(PASSPHRASE)
        with patch(
            "app.modules.workspace.application.backup_service.decrypt_archive_to_zip",
            wraps=decrypt_archive_to_zip,
        ) as decrypt:
            self.backups.restore(result.archive_path, PASSPHRASE, self.root / "restored-workspace")

        self.assertEqual(decrypt.call_count, 1)

    def test_backup_validates_the_live_workspace_once(self) -> None:
        with patch.object(self.backups.archives, "validate_workspace", wraps=self.backups.archives.validate_workspace) as validate:
            self.backups.create_backup(PASSPHRASE)

        self.assertEqual(validate.call_count, 1)

    def test_failed_complete_validation_does_not_publish_an_archive(self) -> None:
        with patch.object(self.backups.archives, "validate_archive", side_effect=BackupError("validation failed")):
            with self.assertRaisesRegex(BackupError, "validation failed"):
                self.backups.create_backup(PASSPHRASE)

        self.assertEqual(list(self.backup_path.glob("*.epm-backup")), [])

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.modules.workspace.application.service import WorkspaceError, WorkspaceNotInitializedError, WorkspaceService
from app.modules.workspace.infrastructure.sqlite_store import SQLiteWorkspaceStore
from app.platform.config import LocalConfig, LocalConfigError, load_local_config, repository_root
from app.platform.product_migrations import ProductSchemaError


class WorkspaceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.workspace_path = self.root / "operator-workspace"
        self.service = WorkspaceService(LocalConfig(config_path=self.root / "config.local.json", workspace_path=self.workspace_path))

    def test_initialize_creates_a_stable_manifest_and_persistent_sqlite_store(self) -> None:
        manifest = self.service.initialize()

        self.assertTrue(self.service.paths.manifest.is_file())
        self.assertTrue(self.service.paths.database.is_file())
        self.assertTrue(self.service.paths.files.is_dir())
        self.assertTrue(self.service.paths.exports.is_dir())
        self.assertTrue(self.service.paths.backups.is_dir())
        self.assertEqual(self.service.open(), manifest)
        self.assertEqual(self.service.initialize(), manifest)

        raw_manifest = json.loads(self.service.paths.manifest.read_text(encoding="utf-8"))
        self.assertEqual(raw_manifest["workspaceId"], manifest.workspace_id)
        self.assertEqual(raw_manifest["databasePath"], "database/property-management.sqlite")

    def test_open_does_not_create_an_uninitialized_workspace(self) -> None:
        with self.assertRaises(WorkspaceNotInitializedError):
            self.service.open()
        self.assertFalse(self.workspace_path.exists())

    def test_initialize_rejects_a_nonempty_folder_without_a_manifest(self) -> None:
        self.workspace_path.mkdir()
        (self.workspace_path / "unrelated.txt").write_text("do not overwrite", encoding="utf-8")

        with self.assertRaises(WorkspaceError):
            self.service.initialize()

    def test_initialize_rejects_the_application_checkout(self) -> None:
        unsafe_service = WorkspaceService(LocalConfig(config_path=self.root / "config.local.json", workspace_path=Path.cwd()))
        with self.assertRaises(WorkspaceError):
            unsafe_service.initialize()

    def test_initialize_rejects_a_repository_sibling(self) -> None:
        unsafe_service = WorkspaceService(LocalConfig(config_path=self.root / "config.local.json", workspace_path=repository_root() / "workspace-data-must-not-live-here"))
        with self.assertRaises(WorkspaceError):
            unsafe_service.initialize()

    @unittest.skipUnless(os.name == "posix", "POSIX permission modes are not available")
    def test_workspace_files_are_private_and_open_repairs_existing_modes(self) -> None:
        self.service.initialize()
        self.assertEqual(self.service.paths.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.service.paths.database.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.service.paths.manifest.stat().st_mode & 0o777, 0o600)

        self.service.paths.root.chmod(0o755)
        self.service.paths.database.chmod(0o644)
        self.service.paths.manifest.chmod(0o644)
        self.service.open()

        self.assertEqual(self.service.paths.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.service.paths.database.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.service.paths.manifest.stat().st_mode & 0o777, 0o600)

    def test_failed_publication_leaves_no_partial_workspace(self) -> None:
        with patch.object(self.service, "_publish_staging_workspace", side_effect=OSError("interrupted")):
            with self.assertRaises(WorkspaceError):
                self.service.initialize()

        self.assertFalse(self.workspace_path.exists())
        self.assertEqual(list(self.root.glob(".operator-workspace.initializing.*")), [])

    def test_failed_staging_validation_does_not_publish_workspace(self) -> None:
        with patch("app.modules.workspace.application.service.validate_latest_schema", side_effect=ProductSchemaError("invalid baseline")):
            with self.assertRaisesRegex(WorkspaceError, "invalid baseline"):
                self.service.initialize()
        self.assertFalse(self.workspace_path.exists())
        self.assertEqual(list(self.root.glob(".operator-workspace.initializing.*")), [])

    def test_corrupt_database_is_reported_as_a_workspace_error(self) -> None:
        self.service.initialize()
        self.service.paths.database.write_bytes(b"not a sqlite database")
        self.service.paths.database.with_name(f"{self.service.paths.database.name}-wal").unlink(missing_ok=True)
        self.service.paths.database.with_name(f"{self.service.paths.database.name}-shm").unlink(missing_ok=True)

        with self.assertRaisesRegex(WorkspaceError, "Workspace database is invalid"):
            self.service.open()

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are not supported")
    def test_open_rejects_a_workspace_database_symbolic_link(self) -> None:
        self.service.initialize()
        external_database = self.root / "external.sqlite"
        external_database.write_bytes(self.service.paths.database.read_bytes())
        self.service.paths.database.unlink()
        self.service.paths.database.symlink_to(external_database)
        with self.assertRaisesRegex(WorkspaceError, "symbolic link"):
            self.service.open()

    def test_normal_workspace_open_skips_full_integrity_scan(self) -> None:
        self.service.initialize()
        with patch.object(SQLiteWorkspaceStore, "verify", autospec=True) as verify:
            self.service.open()

        self.assertFalse(verify.call_args.kwargs["integrity_check"])

    def test_config_requires_an_absolute_workspace_path(self) -> None:
        config_path = self.root / "bad-config.json"
        config_path.write_text('{"localWorkspacePath": "relative-workspace"}', encoding="utf-8")

        with self.assertRaises(LocalConfigError):
            load_local_config(config_path)

    def test_config_requires_a_json_object(self) -> None:
        config_path = self.root / "array-config.json"
        config_path.write_text("[]", encoding="utf-8")

        with self.assertRaisesRegex(LocalConfigError, "JSON object"):
            load_local_config(config_path)

    def test_config_accepts_an_optional_absolute_backup_destination(self) -> None:
        config_path = self.root / "backup-config.json"
        backup_destination = self.root / "separate-backups"
        config_path.write_text(
            json.dumps(
                {
                    "localWorkspacePath": str(self.workspace_path),
                    "backupDestinationPath": str(backup_destination),
                }
            ),
            encoding="utf-8",
        )

        config = load_local_config(config_path)

        self.assertEqual(config.backup_destination_path, backup_destination.resolve())

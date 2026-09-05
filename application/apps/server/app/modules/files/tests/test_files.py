from __future__ import annotations

import tempfile
import sqlite3
import unittest
from unittest.mock import patch
from pathlib import Path

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.application.service import FileError, FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileMetadataRepository
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig
from app.platform.migrations import build_bootstrap_migration_runner
from app.platform.file_migrations import FileMigrationError, upgrade_file_schema
from app.platform.file_migrations import _validate_existing
from sqlalchemy import create_engine, text
from app.platform.sqlite_engine import create_sqlite_engine
from sqlalchemy.exc import IntegrityError
from app.modules.files.infrastructure.sqlalchemy_models import FileLinkModel


class FileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); workspace = root / "workspace"
        self.service = WorkspaceService(LocalConfig(root / "config.json", workspace), build_bootstrap_migration_runner)
        self.service.initialize()
        repository = SQLiteAuditRepository(self.service.paths.database)
        self.files = FileService(self.service, FilesystemContentStore(self.service.paths.files), SQLiteFileMetadataRepository(self.service.paths.database, AuditRecorder(repository))); self.audit = repository
        self.source = root / "receipt.pdf"; self.source.write_bytes(b"receipt bytes")

    def test_stores_portable_file_links_and_audits_it(self) -> None:
        item = self.files.add(self.source, "receipt.pdf", "application/pdf", entity_type="expense", entity_id="expense-1", purpose="receipt")
        self.assertEqual(item.relative_path, f"managed/{item.content_sha256}")
        self.assertTrue((self.service.paths.files / item.relative_path).is_file())
        self.assertEqual(self.files.content_path(item).read_bytes(), b"receipt bytes")
        self.assertEqual(self.audit.history("file", item.id)[0].after_snapshot["relativePath"], item.relative_path)
        self.assertEqual(len(self.audit.history("file_link")), 1)

    def test_identical_content_deduplicates_without_sharing_metadata(self) -> None:
        first = self.files.add(self.source, "one.pdf", "application/pdf")
        second = self.files.add(self.source, "two.pdf", "application/pdf")
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(first.relative_path, second.relative_path)

    def test_rejects_path_filenames_without_publishing_content(self) -> None:
        with self.assertRaises(FileError):
            self.files.add(self.source, "../escape.pdf", "application/pdf")
        self.assertFalse((self.service.paths.files / "managed").exists())

    def test_rejects_unowned_existing_file_schema(self) -> None:
        with sqlite3.connect(self.service.paths.database) as connection:
            connection.execute("DROP TABLE alembic_version")
        with self.assertRaises(FileMigrationError):
            upgrade_file_schema(self.service.paths.database, self.service.paths.backups)

    def test_rejects_conflicting_legacy_size_constraints(self) -> None:
        database = Path(self.temp.name) / "conflicting.sqlite"
        with sqlite3.connect(database) as connection:
            connection.executescript("""
                CREATE TABLE file_records (id TEXT PRIMARY KEY, original_name TEXT NOT NULL, media_type TEXT NOT NULL,
                  size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0) CHECK(size_bytes < 0), content_sha256 TEXT NOT NULL,
                  relative_path TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX file_records_content ON file_records(content_sha256);
                CREATE TABLE file_links (id TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES file_records(id),
                  entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, purpose TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX file_links_entity ON file_links(entity_type, entity_id);
                CREATE TABLE platform_schema_migrations (version INTEGER NOT NULL);
                INSERT INTO platform_schema_migrations VALUES (2);
            """)
        engine = create_engine(f"sqlite:///{database}")
        with engine.connect() as connection:
            with self.assertRaises(FileMigrationError):
                _validate_existing(connection)
        engine.dispose()

    def test_sqlalchemy_repository_enforces_file_link_foreign_key(self) -> None:
        repository = self.files.repository
        with self.assertRaises(IntegrityError):
            with repository.engine.begin() as connection:
                connection.execute(FileLinkModel.__table__.insert().values(
                    id="dangling", file_id="missing", entity_type="expense", entity_id="1",
                    purpose="receipt", created_at="2026-01-01T00:00:00+00:00"))

    def test_native_v2_adoption_preserves_data_links_bytes_and_records_audit(self) -> None:
        item = self.files.add(self.source, "receipt.pdf", "application/pdf",
                              entity_type="expense", entity_id="expense-1", purpose="receipt")
        expected_bytes = self.files.content_path(item).read_bytes()
        with sqlite3.connect(self.service.paths.database) as connection:
            connection.execute("DROP TABLE alembic_version")
            connection.execute("INSERT INTO platform_schema_migrations (version, applied_at) VALUES (2, datetime('now'))")
        upgrade_file_schema(self.service.paths.database, self.service.paths.backups)
        restored = self.files.get(item.id)
        self.assertEqual(restored.links[0]["entityId"], "expense-1")
        self.assertEqual(self.files.content_path(restored).read_bytes(), expected_bytes)
        with sqlite3.connect(self.service.paths.database) as connection:
            self.assertEqual(connection.execute("SELECT version_num FROM alembic_version").fetchone(), ("0001_file_records",))
        events = self.audit.history("file_schema", "0001_file_records")
        self.assertEqual(events[0].reason, "file_schema_adopted")

    def test_native_v2_adoption_rolls_back_stamp_when_audit_fails_then_retries(self) -> None:
        with sqlite3.connect(self.service.paths.database) as connection:
            connection.execute("DROP TABLE alembic_version")
            connection.execute("INSERT INTO platform_schema_migrations (version, applied_at) VALUES (2, datetime('now'))")
        with patch("app.platform.file_migrations._record_native_adoption", side_effect=sqlite3.DatabaseError("audit unavailable")):
            with self.assertRaises(FileMigrationError):
                upgrade_file_schema(self.service.paths.database, self.service.paths.backups)
        with sqlite3.connect(self.service.paths.database) as connection:
            version_table = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'").fetchone()
            if version_table:
                self.assertIsNone(connection.execute("SELECT version_num FROM alembic_version WHERE version_num = '0001_file_records'").fetchone())
        upgrade_file_schema(self.service.paths.database, self.service.paths.backups)
        with sqlite3.connect(self.service.paths.database) as connection:
            self.assertEqual(connection.execute("SELECT version_num FROM alembic_version").fetchone(), ("0001_file_records",))

    def test_initializes_workspace_path_with_url_significant_character(self) -> None:
        root = Path(self.temp.name)
        for name in ("workspace?owner=alice", "workspace%owner"):
            workspace = root / name
            service = WorkspaceService(LocalConfig(root / f"{name}.json", workspace), build_bootstrap_migration_runner)
            service.initialize()
            with sqlite3.connect(service.paths.database) as connection:
                self.assertEqual(connection.execute("SELECT version_num FROM alembic_version").fetchone(), ("0001_file_records",))
                self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'file_records'").fetchone())

    def test_shared_sqlite_engine_rolls_back_ddl(self) -> None:
        database = Path(self.temp.name) / "ddl.sqlite"
        engine = create_sqlite_engine(database)
        with self.assertRaises(RuntimeError):
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE rollback_probe (id INTEGER)"))
                raise RuntimeError("force rollback")
        with engine.connect() as connection:
            row = connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'rollback_probe'")).first()
            self.assertIsNone(row)
        engine.dispose()

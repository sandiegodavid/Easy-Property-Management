from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from sqlalchemy.exc import IntegrityError

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.application.service import FileError, FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig
from app.modules.files.infrastructure.sqlalchemy_models import FileLinkModel
from app.platform.sqlite_engine import create_sqlite_engine
from sqlalchemy import text


class FileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); self.service = WorkspaceService(LocalConfig(root / "config.json", root / "workspace")); self.service.initialize()
        self.audit = SQLiteAuditRepository(self.service.paths.database)
        self.files = FileService(self.service, FilesystemContentStore(self.service.paths.files), SQLiteFileUnitOfWork(self.service.paths.database, AuditRecorder(self.audit)))
        self.source = root / "receipt.pdf"; self.source.write_bytes(b"receipt bytes")

    def test_storage_links_and_audit_are_recorded(self) -> None:
        item = self.files.add(self.source, "receipt.pdf", "application/pdf", entity_type="expense", entity_id="expense-1", purpose="receipt")
        self.assertEqual(item.relative_path, f"managed/{item.content_sha256}")
        self.assertEqual(self.files.content_path(item).read_bytes(), b"receipt bytes")
        self.assertEqual(self.audit.history("file", item.id)[0].after_snapshot["relativePath"], item.relative_path)
        self.assertEqual(len(self.audit.history("file_link")), 1)

    def test_file_and_link_audit_events_share_an_operation_correlation_id(self) -> None:
        item = self.files.add(self.source, "receipt.pdf", "application/pdf", entity_type="expense", entity_id="expense-1")
        file_event = self.audit.history("file", item.id)[0]
        link_event = self.audit.history("file_link")[0]
        self.assertEqual(file_event.correlation_id, link_event.correlation_id)

    def test_deduplication_keeps_separate_metadata_and_path_safety_rejects_escape(self) -> None:
        first = self.files.add(self.source, "one.pdf", "application/pdf"); second = self.files.add(self.source, "two.pdf", "application/pdf")
        self.assertNotEqual(first.id, second.id); self.assertEqual(first.relative_path, second.relative_path)
        with self.assertRaises(FileError): self.files.add(self.source, "../escape.pdf", "application/pdf")

    def test_file_links_require_nonblank_type_id_and_purpose(self) -> None:
        for fields in (
            {"entity_type": "", "entity_id": "expense-1"},
            {"entity_type": "expense", "entity_id": "  "},
            {"entity_type": "expense", "entity_id": "expense-1", "purpose": ""},
        ):
            with self.assertRaises(FileError):
                self.files.add(self.source, "receipt.pdf", "application/pdf", **fields)

    def test_file_link_foreign_key_is_enforced(self) -> None:
        with self.assertRaises(IntegrityError):
            with self.files.unit_of_work.engine.begin() as connection:
                connection.execute(FileLinkModel.__table__.insert().values(id="dangling", file_id="missing", entity_type="expense", entity_id="1", purpose="receipt", created_at="2026-01-01T00:00:00+00:00"))

    def test_url_significant_workspace_paths_and_transactional_ddl_work(self) -> None:
        root = Path(self.temp.name)
        service = WorkspaceService(LocalConfig(root / "url.json", root / "workspace?owner=alice%")); service.initialize()
        self.assertTrue(service.paths.database.is_file())
        engine = create_sqlite_engine(root / "ddl.sqlite")
        with self.assertRaises(RuntimeError):
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE rollback_probe (id INTEGER)")); raise RuntimeError("rollback")
        with engine.connect() as connection: self.assertIsNone(connection.execute(text("SELECT name FROM sqlite_master WHERE name='rollback_probe'" )).first())
        engine.dispose()

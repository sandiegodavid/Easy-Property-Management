from __future__ import annotations

import tempfile
import unittest
import json
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.application.service import FileError, FileService
from app.modules.files.application.ports import FileLink
from app.modules.files.infrastructure.content_store import FilesystemContentStore, S3ContentStore
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
        self.files = FileService(
            self.service,
            FilesystemContentStore(self.service.paths.files),
            SQLiteFileUnitOfWork(self.service.paths.database, AuditRecorder(self.audit)),
            link_validators=(_ExpenseLinkValidator(),),
        )
        self.source = root / "receipt.pdf"; self.source.write_bytes(b"receipt bytes")

    def test_storage_links_and_audit_are_recorded(self) -> None:
        item = self.files.add(self.source, "receipt.pdf", "application/pdf", entity_type="expense", entity_id="expense-1", purpose="receipt")
        self.assertEqual(item.local_relative_path, f"managed/{item.content_sha256}")
        self.assertEqual(self.files.content_path(item).read_bytes(), b"receipt bytes")
        self.assertEqual(self.audit.history("file", item.id)[0].after_snapshot["storageProvider"], "local")
        self.assertNotIn("storageLocator", self.audit.history("file", item.id)[0].after_snapshot)
        self.assertEqual(len(self.audit.history("file_link")), 1)

    def test_s3_storage_preserves_logical_file_identity_and_verifies_download(self) -> None:
        client = _FakeS3Client()
        s3 = S3ContentStore(client, "evidence-bucket", "inspection")
        files = FileService(
            self.service,
            FilesystemContentStore(self.service.paths.files),
            SQLiteFileUnitOfWork(self.service.paths.database, AuditRecorder(self.audit)),
            {"s3": s3},
        )
        item = files.add(self.source, "condition.jpg", "image/jpeg", storage_provider="s3")
        self.assertEqual(item.storage_provider, "s3")
        self.assertNotIn("storageLocator", item.to_dict())
        downloaded = files.content_path(item)
        try:
            self.assertEqual(downloaded.read_bytes(), b"receipt bytes")
        finally:
            downloaded.unlink(missing_ok=True)

    def test_s3_publications_are_version_pinned_and_rollback_only_the_failed_object(self) -> None:
        client = _FakeS3Client()
        s3 = S3ContentStore(client, "evidence-bucket", "inspection")
        successful = FileService(
            self.service,
            s3,
            SQLiteFileUnitOfWork(self.service.paths.database, AuditRecorder(self.audit)),
        ).add(self.source, "condition.jpg", "image/jpeg")
        persisted = self.files.unit_of_work.get(successful.id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.s3_version_id, "version-1")
        successful_key = successful.s3_object_key
        second = FileService(
            self.service,
            s3,
            SQLiteFileUnitOfWork(self.service.paths.database, AuditRecorder(self.audit)),
        ).add(self.source, "condition-copy.jpg", "image/jpeg")
        self.assertNotEqual(successful_key, second.s3_object_key)

        with self.assertRaises(FileError):
            FileService(self.service, s3, _FailingFileUnitOfWork()).add(
                self.source, "condition-failed.jpg", "image/jpeg"
            )
        self.assertIn(("evidence-bucket", successful_key), client.objects)
        self.assertIn(("evidence-bucket", second.s3_object_key), client.objects)
        self.assertEqual(len(client.objects), 2)

    def test_s3_missing_version_id_requires_exact_version_cleanup(self) -> None:
        client = _VersionlessFakeS3Client()
        s3 = S3ContentStore(client, "evidence-bucket", "inspection")
        with self.assertRaisesRegex(FileError, "durable version identity"):
            FileService(
                self.service,
                s3,
                SQLiteFileUnitOfWork(self.service.paths.database, AuditRecorder(self.audit)),
            ).add(self.source, "condition.jpg", "image/jpeg")
        self.assertEqual(client.objects, {})

    def test_s3_adapter_remains_available_when_local_is_the_default_upload_provider(self) -> None:
        config_path = Path(self.temp.name) / "s3-available.json"
        config_path.write_text(json.dumps({
            "localWorkspacePath": str(self.service.paths.root),
            "fileStorageProvider": "local",
            "s3Bucket": "evidence-bucket",
            "s3Prefix": "inspection",
        }), encoding="utf-8")
        client = _FakeS3Client()
        fake_boto3 = types.SimpleNamespace(client=lambda service_name: client)
        from app.bootstrap.api import create_app
        with patch.dict("sys.modules", {"boto3": fake_boto3}):
            app = create_app(config_path)
        self.assertEqual(app.state.file_service.content_store.storage_provider, "local")
        self.assertIs(app.state.file_service.content_stores["s3"], app.state.backup_service.archives.remote_materializer.__self__)

    def test_s3_adapter_construction_is_offline_but_upload_checks_versioning(self) -> None:
        client = _UnavailableS3Client()
        store = S3ContentStore(client, "evidence-bucket", "inspection")
        with self.assertRaisesRegex(FileError, "Unable to verify S3 bucket versioning"):
            store.store(self.source)

    def test_file_and_link_audit_events_share_an_operation_correlation_id(self) -> None:
        item = self.files.add(self.source, "receipt.pdf", "application/pdf", entity_type="expense", entity_id="expense-1", purpose="receipt")
        file_event = self.audit.history("file", item.id)[0]
        link_event = self.audit.history("file_link")[0]
        self.assertEqual(file_event.correlation_id, link_event.correlation_id)

    def test_incorrect_link_is_archived_without_deleting_the_file_or_history(self) -> None:
        item = self.files.add(self.source, "receipt.pdf", "application/pdf", entity_type="expense", entity_id="expense-1", purpose="receipt")
        link_id = self.files.get(item.id).links[0]["id"]
        archived = self.files.archive_link(link_id, confirmed=True, reason="Attached to the wrong expense.")
        self.assertEqual(archived["id"], link_id)
        self.assertEqual(self.files.get(item.id).links, ())
        self.assertTrue(self.files.content_path(self.files.get(item.id)).is_file())
        archive_event = self.audit.history("file_link", link_id)[-1]
        creation_event = self.audit.history("file_link", link_id)[0]
        self.assertEqual(archive_event.action, "archived")
        self.assertEqual(archive_event.before_snapshot["fileId"], item.id)
        self.assertEqual(creation_event.after_snapshot, archive_event.before_snapshot)
        self.assertEqual(archive_event.before_snapshot["createdAt"], archive_event.after_snapshot["createdAt"])
        self.assertEqual(set(archive_event.changed_fields), {"archivedAt", "archiveReason"})
        replacement = self.files.add(self.source, "receipt-copy.pdf", "application/pdf", entity_type="expense", entity_id="expense-1", purpose="receipt")
        self.assertEqual(len(self.files.get(replacement.id).links), 1)
        with self.assertRaisesRegex(FileError, "already archived"):
            self.files.archive_link(link_id, confirmed=True, reason="Repeat")

    def test_archived_link_reason_is_redacted_only_from_global_activity(self) -> None:
        item = self.files.add(
            self.source, "receipt.pdf", "application/pdf",
            entity_type="expense", entity_id="expense-1", purpose="receipt",
        )
        link_id = self.files.get(item.id).links[0]["id"]
        self.files.archive_link(link_id, confirmed=True, reason="Contains a private relocation explanation.")
        self.service.config.config_path.write_text(
            json.dumps({"localWorkspacePath": str(self.service.paths.root)}), encoding="utf-8"
        )
        from app.bootstrap.api import create_app
        with TestClient(create_app(self.service.config.config_path)) as client:
            activity = client.get("/api/audit/events").json()["events"]
            contextual = client.get(f"/api/audit/events/file_link/{link_id}").json()["events"]
        activity_event = next(event for event in activity if event["entityId"] == link_id and event["action"] == "archived")
        self.assertEqual(activity_event["after"]["archiveReason"], "[redacted]")
        self.assertEqual(contextual[-1]["after"]["archiveReason"], "Contains a private relocation explanation.")

    def test_link_authorization_runs_inside_the_serialized_mutation_and_archive_is_not_count_limited(self) -> None:
        limited = FileService(
            self.service,
            FilesystemContentStore(self.service.paths.files),
            SQLiteFileUnitOfWork(self.service.paths.database, AuditRecorder(self.audit)),
            link_validators=(_LimitedExpenseLinkValidator(limit=20),),
        )
        for number in range(19):
            limited.add(self.source, f"receipt-{number}.pdf", "application/pdf", entity_type="expense", entity_id="expense-1", purpose="receipt")

        def add_one(number: int):
            try:
                return limited.add(self.source, f"candidate-{number}.pdf", "application/pdf", entity_type="expense", entity_id="expense-1", purpose="receipt")
            except FileError:
                return None

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(add_one, (1, 2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        item = next(result for result in results if result is not None)
        link_id = limited.get(item.id).links[0]["id"]
        limited.archive_link(link_id, confirmed=True, reason="This duplicate was attached in error.")
        self.assertEqual(limited.get(item.id).links, ())

    def test_failed_link_authorization_rolls_back_metadata_and_audit(self) -> None:
        with self.assertRaisesRegex(FileError, "invalid"):
            self.files.add(
                self.source, "receipt.pdf", "application/pdf",
                entity_type="expense", entity_id="wrong", purpose="receipt",
            )
        with self.files.unit_of_work.engine.connect() as connection:
            self.assertEqual(connection.execute(select(func.count()).select_from(FileLinkModel)).scalar_one(), 0)
        self.assertEqual(self.audit.history("file"), [])
        self.assertEqual(self.audit.history("file_link"), [])

    def test_failed_archive_authorization_leaves_link_and_history_unchanged(self) -> None:
        item = self.files.add(
            self.source, "receipt.pdf", "application/pdf",
            entity_type="expense", entity_id="expense-1", purpose="receipt",
        )
        link_id = self.files.get(item.id).links[0]["id"]
        self.files.link_validators["expense"] = _RejectingArchiveValidator()
        with self.assertRaisesRegex(FileError, "not authorized"):
            self.files.archive_link(link_id, confirmed=True, reason="Not needed.")
        self.assertEqual(self.files.get(item.id).links[0]["id"], link_id)
        self.assertEqual(len(self.audit.history("file_link", link_id)), 1)

    def test_deduplication_keeps_separate_metadata_and_path_safety_rejects_escape(self) -> None:
        first = self.files.add(self.source, "one.pdf", "application/pdf"); second = self.files.add(self.source, "two.pdf", "application/pdf")
        self.assertNotEqual(first.id, second.id); self.assertEqual(first.local_relative_path, second.local_relative_path)
        with self.assertRaises(FileError): self.files.add(self.source, "../escape.pdf", "application/pdf")

    def test_file_links_require_nonblank_type_id_and_purpose(self) -> None:
        for fields in (
            {"entity_type": "", "entity_id": "expense-1"},
            {"entity_type": "expense", "entity_id": "  "},
            {"entity_type": "expense", "entity_id": "expense-1", "purpose": ""},
        ):
            with self.assertRaises(FileError):
                self.files.add(self.source, "receipt.pdf", "application/pdf", **fields)

    def test_file_links_require_a_registered_owning_domain_validator(self) -> None:
        with self.assertRaisesRegex(FileError, "No owning-domain validator"):
            self.files.add(
                self.source, "receipt.pdf", "application/pdf",
                entity_type="leaze", entity_id="lease-1", purpose="executed_lease",
            )

    def test_unavailable_file_content_cannot_be_downloaded(self) -> None:
        item = self.files.add(self.source, "receipt.pdf", "application/pdf")
        with self.files.unit_of_work.engine.begin() as connection:
            connection.execute(text(
                "UPDATE file_content_locations SET storage_state='quarantined' WHERE file_id=:id"
            ), {"id": item.id})
        with self.assertRaisesRegex(FileError, "Only available"):
            self.files.content_path(self.files.get(item.id))

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


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}

    def get_bucket_versioning(self, *, Bucket):
        return {"Status": "Enabled"}

    def put_object(self, *, Bucket, Key, Body, Metadata, IfNoneMatch):
        if (Bucket, Key) in self.objects:
            raise AssertionError("Conditional publication attempted to overwrite an object")
        self.objects[(Bucket, Key)] = (Body.read(), Metadata)
        return {"VersionId": "version-1", "ETag": "etag-1"}

    def download_file(self, bucket, key, filename, ExtraArgs=None):
        Path(filename).write_bytes(self.objects[(bucket, key)][0])

    def download_fileobj(self, bucket, key, output, ExtraArgs=None):
        output.write(self.objects[(bucket, key)][0])

    def delete_object(self, *, Bucket, Key, VersionId=None):
        self.objects.pop((Bucket, Key), None)

    def list_object_versions(self, *, Bucket, Prefix):
        return {"Versions": [
            {"Key": key, "VersionId": "version-1", "IsLatest": True}
            for bucket, key in self.objects if bucket == Bucket and key == Prefix
        ]}


class _ExpenseLinkValidator:
    entity_types = frozenset({"expense"})

    def validate_create(self, connection, link: FileLink) -> None:
        if link.entity_id != "expense-1" or link.purpose != "receipt":
            raise FileError("Expense link is invalid.")

    def validate_archive(self, connection, link: FileLink) -> None:
        if link.entity_id != "expense-1" or link.purpose != "receipt":
            raise FileError("Expense link is invalid.")


class _LimitedExpenseLinkValidator:
    entity_types = frozenset({"expense"})

    def __init__(self, limit: int) -> None:
        self.limit = limit

    def validate_create(self, connection, link: FileLink) -> None:
        active = connection.execute(
            select(func.count()).select_from(FileLinkModel).where(
                FileLinkModel.entity_type == link.entity_type,
                FileLinkModel.entity_id == link.entity_id,
                FileLinkModel.archived_at.is_(None),
            )
        ).scalar_one()
        if active >= self.limit:
            raise FileError("Expense evidence limit reached.")

    def validate_archive(self, connection, link: FileLink) -> None:
        return None


class _RejectingArchiveValidator:
    entity_types = frozenset({"expense"})

    def validate_create(self, connection, link: FileLink) -> None:
        return None

    def validate_archive(self, connection, link: FileLink) -> None:
        raise FileError("Archive is not authorized.")


class _VersionlessFakeS3Client(_FakeS3Client):
    def put_object(self, **kwargs):
        super().put_object(**kwargs)
        return {"ETag": "etag-1"}


class _UnavailableS3Client:
    def get_bucket_versioning(self, *, Bucket):
        raise RuntimeError("network unavailable")


class _FailingFileUnitOfWork:
    def write(self, item, link, audit_changes, validate_link=None):
        raise OSError("metadata unavailable")

    def get(self, file_id):
        return None

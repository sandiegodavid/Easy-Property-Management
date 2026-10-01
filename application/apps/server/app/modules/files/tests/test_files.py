from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.application.errors import PublicationCleanupIncomplete
from app.modules.files.application.ports import FileLink
from app.modules.files.application.service import FileError, FileService
from app.modules.files.application.verification import FileStorageVerificationService
from app.modules.files.infrastructure.content_store import FilesystemContentStore, S3ContentStore
from app.modules.files.infrastructure.file_link_reader import SQLiteFileLinkReader
from app.modules.files.infrastructure.sqlalchemy_models import FileLinkModel
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.intake.application.file_links import IntakeSourceFileLinkValidator
from app.modules.intake.application.service import AttachmentInput, IntakeAdmissionCommand, IntakeService
from app.modules.intake.domain.models import EvidenceEnvelope
from app.modules.intake.infrastructure.attention_operations import SQLiteIntakeAttentionOperations
from app.modules.intake.infrastructure.source_reader import SQLiteIntakeSourceReader
from app.modules.intake.infrastructure.integrity_consequences import SQLiteIntakeIntegrityConsequences
from app.modules.intake.infrastructure.unit_of_work import SQLiteIntakeUnitOfWork
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction


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

    def intake_service(self, files: FileService) -> IntakeService:
        recorder = AuditRecorder(self.audit)
        return IntakeService(
            SQLiteIntakeUnitOfWork(self.service.paths.database, recorder, SQLiteFileLinkReader()),
            files,
            attention_operations=SQLiteIntakeAttentionOperations(recorder, SQLiteIntakeSourceReader()),
        )

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
            {"s3": s3}, link_validators=(_ExpenseLinkValidator(),),
        )
        # HTTP and primary-service uploads are server-owned; an S3 store is
        # selected here only as the configured primary for this adapter test.
        files.content_store = s3
        item = files.add(self.source, "condition.jpg", "image/jpeg", entity_type="expense", entity_id="expense-1", purpose="receipt")
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
            SQLiteFileUnitOfWork(self.service.paths.database, AuditRecorder(self.audit)), link_validators=(_ExpenseLinkValidator(),),
        ).add(self.source, "condition.jpg", "image/jpeg", entity_type="expense", entity_id="expense-1", purpose="receipt")
        persisted = self.files.unit_of_work.get(successful.id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.s3_version_id, "version-1")
        successful_key = successful.s3_object_key
        second = FileService(
            self.service,
            s3,
            SQLiteFileUnitOfWork(self.service.paths.database, AuditRecorder(self.audit)), link_validators=(_ExpenseLinkValidator(),),
        ).add(self.source, "condition-copy.jpg", "image/jpeg", entity_type="expense", entity_id="expense-1", purpose="receipt")
        self.assertNotEqual(successful_key, second.s3_object_key)

        with self.assertRaises(FileError):
            FileService(self.service, s3, _FailingFileUnitOfWork(), link_validators=(_ExpenseLinkValidator(),)).add(
                self.source, "condition-failed.jpg", "image/jpeg", entity_type="expense", entity_id="expense-3", purpose="receipt"
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
                link_validators=(_ExpenseLinkValidator(),),
            ).add(self.source, "condition.jpg", "image/jpeg", entity_type="expense", entity_id="expense-1", purpose="receipt")
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

    def test_full_verification_does_not_clear_cleanup_attention_for_quarantined_content(self) -> None:
        item = self.files.add(self.source, "receipt.pdf", "application/pdf", entity_type="expense", entity_id="expense-1", purpose="receipt")
        self.files.content_path(item).write_bytes(b"corrupt retained bytes")
        self.files.unit_of_work.record_cleanup_incomplete("publication-test", "local", str(uuid4()))

        result = FileStorageVerificationService(self.files.unit_of_work, self.files.content_stores).verify()

        self.assertFalse(result["complete"])
        self.assertEqual(result["states"]["quarantined"], 1)
        self.assertEqual(result["cleanupAttention"]["outstanding"], 1)

    def test_verification_transitions_current_intake_evidence_and_restores_it(self) -> None:
        """FILE-001 and INGEST-001 state/audit changes share one transaction."""
        intake_files = FileService(
            self.service, FilesystemContentStore(self.service.paths.files),
            SQLiteFileUnitOfWork(self.service.paths.database, AuditRecorder(self.audit)),
            link_validators=(IntakeSourceFileLinkValidator(),),
        )
        intake = self.intake_service(intake_files)
        admitted = intake.admit(IntakeAdmissionCommand(
            EvidenceEnvelope("operator_note", "internal", "Attached source.",
                             "2026-01-01T12:00:00+00:00"),
            "manual", str(uuid4()),
            attachments=(AttachmentInput(self.source, "receipt.pdf", "application/pdf"),),
        ))
        detail = intake.get(admitted["sourceId"])
        file_id = detail["attachments"][0]["file"]["file_id"]
        item = intake_files.get(file_id)
        self.assertIsNotNone(item)
        managed = intake_files.content_path(item)
        managed.unlink()
        verification = FileStorageVerificationService(
            intake_files.unit_of_work, intake_files.content_stores,
            SQLiteIntakeIntegrityConsequences(AuditRecorder(self.audit), SQLiteFileLinkReader()),
        )

        verification.verify(file_id)
        failed = intake.get(admitted["sourceId"])
        self.assertEqual("failed", failed["technicalStatus"])
        self.assertEqual("attachment_content_unavailable", failed["failureCode"])
        failed_event = next(event for event in reversed(
            self.audit.history("intake_source", admitted["sourceId"])
        ) if event.action == "integrity_failed")
        self.assertEqual(
            self.audit.history("file", file_id)[-1].correlation_id,
            failed_event.correlation_id,
        )

        managed.write_bytes(b"receipt bytes")
        verification.verify(file_id)
        restored = intake.get(admitted["sourceId"])
        self.assertEqual("ready", restored["technicalStatus"])
        self.assertIsNone(restored["failureCode"])
        self.assertTrue(any(
            event.action == "integrity_restored"
            for event in self.audit.history("intake_source", admitted["sourceId"])
        ))

    def test_intake_restoration_waits_for_every_current_attachment(self) -> None:
        second = Path(self.temp.name) / "second.pdf"
        second.write_bytes(b"second receipt bytes")
        intake_files = FileService(
            self.service, FilesystemContentStore(self.service.paths.files),
            SQLiteFileUnitOfWork(self.service.paths.database, AuditRecorder(self.audit)),
            link_validators=(IntakeSourceFileLinkValidator(),),
        )
        intake = self.intake_service(intake_files)
        admitted = intake.admit(IntakeAdmissionCommand(
            EvidenceEnvelope("operator_note", "internal", "Two attachments.",
                             "2026-01-01T12:00:00+00:00"),
            "manual", str(uuid4()),
            attachments=(
                AttachmentInput(self.source, "receipt.pdf", "application/pdf"),
                AttachmentInput(second, "second.pdf", "application/pdf"),
            ),
        ))
        detail = intake.get(admitted["sourceId"])
        items = [intake_files.get(attachment["file"]["file_id"])
                 for attachment in detail["attachments"]]
        self.assertTrue(all(items))
        paths = [intake_files.content_path(item) for item in items]
        verification = FileStorageVerificationService(
            intake_files.unit_of_work, intake_files.content_stores,
            SQLiteIntakeIntegrityConsequences(AuditRecorder(self.audit), SQLiteFileLinkReader()),
        )

        paths[0].unlink()
        verification.verify(items[0].id)
        self.assertEqual("failed", intake.get(admitted["sourceId"])["technicalStatus"])
        paths[1].unlink()
        verification.verify(items[1].id)
        paths[0].write_bytes(b"receipt bytes")
        verification.verify(items[0].id)
        self.assertEqual("failed", intake.get(admitted["sourceId"])["technicalStatus"])
        paths[1].write_bytes(b"second receipt bytes")
        verification.verify(items[1].id)
        self.assertEqual("ready", intake.get(admitted["sourceId"])["technicalStatus"])

    def test_verification_does_not_change_a_superseded_intake_source(self) -> None:
        intake_files = FileService(
            self.service, FilesystemContentStore(self.service.paths.files),
            SQLiteFileUnitOfWork(self.service.paths.database, AuditRecorder(self.audit)),
            link_validators=(IntakeSourceFileLinkValidator(),),
        )
        intake = self.intake_service(intake_files)
        original = intake.admit(IntakeAdmissionCommand(
            EvidenceEnvelope("operator_note", "internal", "Historical attachment.",
                             "2026-01-01T12:00:00+00:00"),
            "manual", str(uuid4()),
            attachments=(AttachmentInput(self.source, "receipt.pdf", "application/pdf"),),
        ))
        replacement = intake.supersede(original["sourceId"], IntakeAdmissionCommand(
            EvidenceEnvelope("operator_note", "internal", "Replacement evidence.",
                             "2026-01-01T12:00:00+00:00"),
            "manual", str(uuid4()),
        ))
        detail = intake.get(original["sourceId"])
        item = intake_files.get(detail["attachments"][0]["file"]["file_id"])
        self.assertIsNotNone(item)
        intake_files.content_path(item).unlink()
        FileStorageVerificationService(
            intake_files.unit_of_work, intake_files.content_stores,
            SQLiteIntakeIntegrityConsequences(AuditRecorder(self.audit), SQLiteFileLinkReader()),
        ).verify(item.id)

        self.assertEqual("superseded", intake.get(original["sourceId"])["technicalStatus"])
        self.assertEqual("ready", intake.get(replacement["sourceId"])["technicalStatus"])
        self.assertFalse(any(
            event.action == "integrity_failed"
            for event in self.audit.history("intake_source", original["sourceId"])
        ))

    def test_cleanup_attention_is_visible_before_a_verification_run(self) -> None:
        self.files.unit_of_work.record_cleanup_incomplete("publication-test", "local", str(uuid4()))
        self.service.config.config_path.write_text(
            json.dumps({"localWorkspacePath": str(self.service.paths.root)}), encoding="utf-8"
        )
        from app.bootstrap.api import create_app
        with TestClient(create_app(self.service.config.config_path)) as client:
            response = client.get("/api/files/integrity-attention")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["outstanding"][0]["publicationId"], "publication-test")

    def test_caller_owned_rollback_persists_cleanup_attention_after_writer_releases(self) -> None:
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()

        class FailedRollbackContent:
            publication_id = "publication-after-rollback"
            storage_provider = "local"
            storage_state = "available"
            local_relative_path = f"managed/{digest}"
            s3_bucket = s3_object_key = s3_version_id = provider_etag = None
            size_bytes = len(b"receipt bytes")
            content_sha256 = digest
            def commit(self): pass
            def rollback(self): raise OSError("simulated cleanup failure")

        self.files.content_store = types.SimpleNamespace(store=lambda source: FailedRollbackContent())
        engine = create_sqlite_engine(self.service.paths.database)
        try:
            try:
                with immediate_transaction(engine) as connection:
                    batch = self.files.attachment_batch(connection)
                    batch.add(self.source, "receipt.pdf", "application/pdf", entity_type="expense", entity_id="expense-1", purpose="receipt", correlation_id=str(uuid4()))
                    with self.assertRaises(PublicationCleanupIncomplete):
                        batch.rollback(ValueError("database write failed"))
                    raise RuntimeError("rollback owning transaction")
            except RuntimeError:
                pass
            batch.persist_cleanup_attention()
        finally:
            engine.dispose()
        attentions = self.files.unit_of_work.outstanding_cleanup_attentions()
        self.assertEqual([row["publicationId"] for row in attentions], ["publication-after-rollback"])

    def test_incorrect_link_is_archived_without_deleting_the_file_or_history(self) -> None:
        item = self.files.add(self.source, "receipt.pdf", "application/pdf", entity_type="expense", entity_id="expense-1", purpose="receipt")
        link_id = self.files.get(item.id).links[0]["id"]
        archived = self.files.archive_link(link_id, confirmed=True, reason="Attached to the wrong expense.")
        self.assertEqual(archived["id"], link_id)
        self.assertEqual(self.files.get(item.id).links[0]["archivedAt"], archived["archivedAt"])
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
        # This focused presentation test uses a lightweight fake expense
        # validator; remove its deliberately non-domain fixture before opening
        # the real application, whose retained-data validation correctly
        # rejects links to a missing expense.
        with sqlite3.connect(self.service.paths.database) as connection:
            connection.execute("DELETE FROM file_links WHERE file_id=?", (item.id,))
            connection.execute("DELETE FROM file_content_locations WHERE file_id=?", (item.id,))
            connection.execute("DELETE FROM file_records WHERE id=?", (item.id,))
            connection.commit()
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
            link_validators=(_LimitedExpenseLinkValidator(limit=2),),
        )
        limited.add(self.source, "receipt.pdf", "application/pdf", entity_type="expense", entity_id="expense-1", purpose="receipt")

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
        self.assertIsNotNone(limited.get(item.id).links[0]["archivedAt"])

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
        first = self.files.add(self.source, "one.pdf", "application/pdf", entity_type="expense", entity_id="expense-1", purpose="receipt"); second = self.files.add(self.source, "two.pdf", "application/pdf", entity_type="expense", entity_id="expense-1", purpose="receipt")
        self.assertNotEqual(first.id, second.id); self.assertEqual(first.local_relative_path, second.local_relative_path)
        with self.assertRaises(FileError): self.files.add(self.source, "../escape.pdf", "application/pdf", entity_type="expense", entity_id="expense-3", purpose="receipt")

    def test_file_links_require_nonblank_type_id_and_purpose(self) -> None:
        for fields in (
            {"entity_type": "", "entity_id": "expense-1", "purpose": "receipt"},
            {"entity_type": "expense", "entity_id": "  ", "purpose": "receipt"},
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
        item = self.files.add(self.source, "receipt.pdf", "application/pdf", entity_type="expense", entity_id="expense-1", purpose="receipt")
        with self.files.unit_of_work.engine.begin() as connection:
            connection.execute(text(
                "UPDATE file_content_locations SET storage_state='quarantined' WHERE file_id=:id"
            ), {"id": item.id})
        with self.assertRaisesRegex(FileError, "Only available"):
            self.files.content_path(self.files.get(item.id))

    def test_file_link_reader_counts_and_reads_archived_links_in_one_bulk_query(self) -> None:
        first = self.files.add(
            self.source, "first.pdf", "application/pdf", entity_type="expense",
            entity_id="expense-1", purpose="receipt",
        )
        second = self.files.add(
            self.source, "second.pdf", "application/pdf", entity_type="expense",
            entity_id="expense-1", purpose="receipt",
        )
        first_link_id = self.files.get(first.id).links[0]["id"]
        self.files.archive_link(first_link_id, confirmed=True, reason="Superseded.")
        reader = SQLiteFileLinkReader()
        engine = self.files.unit_of_work.engine

        with engine.connect() as connection:
            self.assertEqual(reader.active_link_count(connection, "expense", "expense-1"), 1)
            self.assertTrue(reader.has_active_available_link(connection, "expense", "expense-1"))
            self.assertEqual(
                [link.id for link in reader.links_for_entity(connection, "expense", "expense-1")],
                [first_link_id, self.files.get(second.id).links[0]["id"]],
            )
            self.assertEqual(reader.entity_ids_with_active_links(connection, "expense"), {"expense-1"})

        selects = []
        def count_select(*args):
            if args[2].lstrip().upper().startswith("SELECT"):
                selects.append(args[2])
        event.listen(engine, "before_cursor_execute", count_select)
        try:
            with engine.connect() as connection:
                links = reader.links_for_entities(connection, "expense", ["expense-1", "expense-2"])
        finally:
            event.remove(engine, "before_cursor_execute", count_select)
        self.assertEqual(len(selects), 1)
        self.assertEqual([link.id for link in links["expense-1"]], [first_link_id, self.files.get(second.id).links[0]["id"]])
        self.assertEqual(links["expense-1"][0].archived_at is not None, True)
        self.assertEqual(links["expense-2"], [])

        with engine.begin() as connection:
            connection.execute(text(
                "UPDATE file_content_locations SET storage_state='quarantined' WHERE file_id=:id"
            ), {"id": second.id})
        with engine.connect() as connection:
            self.assertFalse(reader.has_active_available_link(connection, "expense", "expense-1"))

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
    allows_generic_upload = True

    def validate_create(self, connection, link: FileLink) -> None:
        if link.entity_id != "expense-1" or link.purpose != "receipt":
            raise FileError("Expense link is invalid.")

    def validate_archive(self, connection, link: FileLink) -> None:
        if link.entity_id != "expense-1" or link.purpose != "receipt":
            raise FileError("Expense link is invalid.")
    def validate_retained(self, connection, link: FileLink) -> None: self.validate_create(connection, link)


class _LimitedExpenseLinkValidator:
    entity_types = frozenset({"expense"})
    allows_generic_upload = True

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
    def validate_retained(self, connection, link: FileLink) -> None: return None


class _RejectingArchiveValidator:
    entity_types = frozenset({"expense"})
    allows_generic_upload = True

    def validate_create(self, connection, link: FileLink) -> None:
        return None

    def validate_archive(self, connection, link: FileLink) -> None:
        raise FileError("Archive is not authorized.")
    def validate_retained(self, connection, link: FileLink) -> None: return None


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

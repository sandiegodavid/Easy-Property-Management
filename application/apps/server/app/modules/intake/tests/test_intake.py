from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.application.errors import PublicationCleanupIncomplete
from app.modules.files.application.service import FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.intake.application.file_links import IntakeSourceFileLinkValidator
from app.modules.intake.api.router import build_router
from app.modules.intake.application.service import AttachmentInput, IntakeAdmissionCommand, IntakeService
from app.modules.intake.domain.models import EvidenceEnvelope, IntakeConflictError
from app.modules.intake.infrastructure.unit_of_work import SQLiteIntakeUnitOfWork
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import initialize_latest_schema, validate_latest_schema
from app.platform.migration_errors import MigrationSchemaError


class IntakeTests(TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "workspace.sqlite"; initialize_latest_schema(self.database)
        self.service = IntakeService(SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))))

    def command(self, key: str | None = None, body: str = "The sink leaks.") -> IntakeAdmissionCommand:
        return IntakeAdmissionCommand(EvidenceEnvelope("operator_note", "internal", body, "2026-01-01T12:00:00+00:00"), "manual", key or str(uuid4()))

    def test_admission_replays_and_retains_canonical_evidence(self) -> None:
        command = self.command(); first = self.service.admit(command); replay = self.service.admit(command)
        self.assertEqual(first, replay)
        detail = self.service.get(first["sourceId"])
        self.assertEqual("The sink leaks.", detail["evidence"]["body"])
        self.assertEqual("ready", detail["technicalStatus"])
        validate_latest_schema(self.database)

    def test_changed_idempotency_payload_is_a_conflict(self) -> None:
        key=str(uuid4()); self.service.admit(self.command(key))
        with self.assertRaises(IntakeConflictError): self.service.admit(self.command(key, "Different evidence."))

    def test_workspace_validation_rejects_an_unregistered_integrity_failure_code(self) -> None:
        source = self.service.admit(self.command())
        import sqlite3
        with sqlite3.connect(self.database) as connection:
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute(
                "UPDATE intake_sources SET technical_status='failed', failure_code='arbitrary_failure' WHERE id=?",
                (source["sourceId"],),
            )
            connection.commit()
        with self.assertRaises(MigrationSchemaError):
            validate_latest_schema(self.database)

    def test_correction_keeps_the_original_revision(self) -> None:
        source=self.service.admit(self.command())
        detail=self.service.correct(source["sourceId"], EvidenceEnvelope("operator_note", "internal", "Corrected evidence.", "2026-01-01T12:00:00+00:00"), "clarified", str(uuid4()))
        self.assertEqual(2, len(detail["revisions"])); self.assertEqual("Corrected evidence.", detail["evidence"]["body"])
        validate_latest_schema(self.database)

    def test_trusted_external_replay_compares_evidence_and_reserves_each_key(self) -> None:
        def trusted(key: str, body: str) -> IntakeAdmissionCommand:
            return IntakeAdmissionCommand(
                EvidenceEnvelope("email_message", "email", body, "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
                "gmail", key, "a" * 64, "transport_verified",
            )
        first = self.service.admit(trusted(str(uuid4()), "A retained email."))
        replay_key = str(uuid4())
        self.assertEqual(first["sourceId"], self.service.admit(trusted(replay_key, "A retained email."))["sourceId"])
        with self.assertRaises(IntakeConflictError):
            self.service.admit(trusted(replay_key, "Changed evidence."))
        with self.assertRaises(IntakeConflictError):
            self.service.admit(trusted(str(uuid4()), "Changed evidence."))

    def test_trusted_external_supersession_replaces_the_current_identity_tip(self) -> None:
        def trusted(key: str, body: str) -> IntakeAdmissionCommand:
            return IntakeAdmissionCommand(
                EvidenceEnvelope("email_message", "email", body,
                                 "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
                "gmail", key, "a" * 64, "transport_verified",
            )

        original = self.service.admit(trusted(str(uuid4()), "Original retained email."))
        replacement = self.service.supersede(
            original["sourceId"], trusted(str(uuid4()), "Corrected retained email."),
        )

        self.assertNotEqual(original["sourceId"], replacement["sourceId"])
        self.assertEqual("superseded", self.service.get(original["sourceId"])["technicalStatus"])
        self.assertEqual(replacement["sourceId"], self.service.admit(
            trusted(str(uuid4()), "Corrected retained email.")
        )["sourceId"])
        with self.assertRaises(IntakeConflictError) as conflict:
            self.service.admit(trusted(str(uuid4()), "Conflicting retained email."))
        self.assertEqual("intake_exact_identity_conflict", conflict.exception.code)
        validate_latest_schema(self.database)

    def test_trusted_historical_replay_and_attachment_set_supersession(self) -> None:
        root = Path(self.temporary.name)
        original_attachment = root / "original.eml"
        replacement_attachment = root / "replacement.eml"
        original_attachment.write_bytes(b"original attachment")
        replacement_attachment.write_bytes(b"replacement attachment")
        files = FileService(
            None, FilesystemContentStore(root / "files"),
            SQLiteFileUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))),
            link_validators=(IntakeSourceFileLinkValidator(),),
        )
        service = IntakeService(SQLiteIntakeUnitOfWork(
            self.database, AuditRecorder(SQLiteAuditRepository(self.database))
        ), files)

        def trusted(key: str, attachment: Path) -> IntakeAdmissionCommand:
            return IntakeAdmissionCommand(
                EvidenceEnvelope("email_message", "email", "Retained email.",
                                 "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
                "gmail", key, "a" * 64, "transport_verified",
                attachments=(AttachmentInput(attachment, attachment.name, "message/rfc822"),),
            )

        original_command = trusted(str(uuid4()), original_attachment)
        original = service.admit(original_command)
        replacement = service.supersede(
            original["sourceId"], trusted(str(uuid4()), replacement_attachment)
        )
        historical = service.admit(trusted(str(uuid4()), original_attachment))
        current = service.admit(trusted(str(uuid4()), replacement_attachment))
        self.assertEqual(original["sourceId"], historical["sourceId"])
        self.assertEqual(replacement["sourceId"], current["sourceId"])
        with self.assertRaises(IntakeConflictError):
            service.admit(IntakeAdmissionCommand(
                EvidenceEnvelope("email_message", "email", "Changed body.",
                                 "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
                "gmail", str(uuid4()), "a" * 64, "transport_verified",
                attachments=(AttachmentInput(replacement_attachment, replacement_attachment.name,
                                             "message/rfc822"),),
            ))
        validate_latest_schema(self.database)

    def test_trusted_replay_resolves_a_noncurrent_revision_after_supersession(self) -> None:
        def trusted(key: str, body: str) -> IntakeAdmissionCommand:
            return IntakeAdmissionCommand(
                EvidenceEnvelope("email_message", "email", body,
                                 "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
                "gmail", key, "a" * 64, "transport_verified",
            )

        original = self.service.admit(trusted(str(uuid4()), "Original retained email."))
        corrected = self.service.correct(
            original["sourceId"],
            EvidenceEnvelope("email_message", "email", "Corrected source evidence.",
                             "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
            "corrected source evidence", str(uuid4()),
        )
        replacement = self.service.supersede(
            original["sourceId"], trusted(str(uuid4()), "Replacement source evidence."),
        )

        replay = self.service.admit(trusted(str(uuid4()), "Original retained email."))
        self.assertEqual(original["sourceId"], replay["sourceId"])
        self.assertEqual(corrected["revision"], replay["revision"])
        self.assertEqual(replacement["sourceId"], self.service.admit(
            trusted(str(uuid4()), "Replacement source evidence.")
        )["sourceId"])
        validate_latest_schema(self.database)

    def test_workspace_validation_rejects_a_tampered_trusted_lineage_identity(self) -> None:
        def trusted(key: str, body: str) -> IntakeAdmissionCommand:
            return IntakeAdmissionCommand(
                EvidenceEnvelope("email_message", "email", body,
                                 "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
                "gmail", key, "a" * 64, "transport_verified",
            )
        original = self.service.admit(trusted(str(uuid4()), "Original email."))
        self.service.supersede(original["sourceId"], trusted(str(uuid4()), "Replacement email."))
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE intake_sources SET origin_system='tampered' WHERE id=?", (original["sourceId"],))
            connection.commit()
        with self.assertRaises(MigrationSchemaError):
            validate_latest_schema(self.database)

    def test_trusted_supersession_rejects_a_changed_identity(self) -> None:
        original = self.service.admit(IntakeAdmissionCommand(
            EvidenceEnvelope("email_message", "email", "Original retained email.",
                             "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
            "gmail", str(uuid4()), "a" * 64, "transport_verified",
        ))
        changed = IntakeAdmissionCommand(
            EvidenceEnvelope("email_message", "email", "Replacement email.",
                             "2026-01-01T12:00:00+00:00", external_source_id="mail-2"),
            "gmail", str(uuid4()), "a" * 64, "transport_verified",
        )
        with self.assertRaisesRegex(IntakeConflictError, "identity"):
            self.service.supersede(original["sourceId"], changed)

    def test_pagination_uses_last_returned_cursor_without_a_gap(self) -> None:
        ids = [self.service.admit(self.command(body=f"Evidence {index}"))["sourceId"] for index in range(3)]
        first, cursor = self.service.list(limit=1)
        second, cursor = self.service.list(limit=1, cursor=tuple(cursor.split("|", 1)))
        third, cursor = self.service.list(limit=1, cursor=tuple(cursor.split("|", 1)))
        self.assertEqual(set(ids), {first[0]["sourceId"], second[0]["sourceId"], third[0]["sourceId"]})

    def test_supersession_is_atomic_and_preserves_lineage(self) -> None:
        original = self.service.admit(self.command())
        replacement = self.service.supersede(
            original["sourceId"],
            self.command(body="Replacement source evidence."),
        )
        old = self.service.get(original["sourceId"])
        self.assertEqual("superseded", old["technicalStatus"])
        self.assertEqual(replacement["sourceId"], old["supersededBySourceId"])
        validate_latest_schema(self.database)

    def test_import_reports_cleanup_repair_when_deferred_attention_recording_fails(self) -> None:
        """The owning HTTP boundary preserves FILE-001's safe 503 contract."""
        class FailingService:
            def admit(self, _command):
                failure = PublicationCleanupIncomplete(
                    "publication-1", "local", RuntimeError("admission failed"),
                    RuntimeError("cleanup failed"),
                )
                failure.attention_recording_failure = RuntimeError("attention write failed")
                raise failure

        class ReadyRuntime:
            ready = True
            can_write = True
            error = None

        app = FastAPI()
        app.include_router(build_router(FailingService(), ReadyRuntime()))
        response = TestClient(app).post(
            "/api/intake/sources/import",
            data={"metadata": '{"sourceKind":"operator_note","channel":"internal",'
                              '"body":"Leaking sink.","occurredAtUtc":"2026-01-01T12:00:00Z",'
                              '"originSystem":"manual","idempotencyKey":"' + str(uuid4()) + '"}'},
        )

        self.assertEqual(503, response.status_code)
        self.assertEqual({"code": "publication_cleanup_incomplete",
                          "message": "File publication cleanup could not be completed.",
                          "repairRequired": True, "attentionRecorded": False}, response.json()["detail"])

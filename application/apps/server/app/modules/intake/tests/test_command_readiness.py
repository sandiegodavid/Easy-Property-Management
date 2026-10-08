"""UI-001 Slice 16: original Intake receipts and concurrency boundaries."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.infrastructure.file_link_reader import SQLiteFileLinkReader
from app.modules.files.application.service import FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.intake.application.file_links import IntakeSourceFileLinkValidator
from app.modules.intake.api.router import build_router
from app.modules.intake.application.service import (
    AttachmentInput,
    IntakeAdmissionCommand,
    IntakeService,
)
from app.modules.intake.domain.models import EvidenceEnvelope, IntakeConflictError, IntakeError
from app.modules.intake.infrastructure.attention_operations import SQLiteIntakeAttentionOperations
from app.modules.intake.infrastructure.source_reader import SQLiteIntakeSourceReader
from app.modules.intake.infrastructure.unit_of_work import SQLiteIntakeUnitOfWork
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema


def command(body: str = "Original evidence.") -> IntakeAdmissionCommand:
    return IntakeAdmissionCommand(
        EvidenceEnvelope("operator_note", "internal", body, "2026-01-01T12:00:00+00:00"),
        "manual",
        str(uuid4()),
    )


class IntakeCommandReadinessTests(TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = WorkspaceService(
            LocalConfig(self.root / "config.local.json", self.root / "workspace")
        )
        self.workspace.initialize()
        self.database = self.workspace.paths.database
        self.recorder = AuditRecorder(SQLiteAuditRepository(self.database))
        self.service = self.make_service(self.database)
        self.original_command = command()
        self.source = self.service.admit(self.original_command)

    def make_service(self, database: Path) -> IntakeService:
        recorder = AuditRecorder(SQLiteAuditRepository(database))
        return IntakeService(
            SQLiteIntakeUnitOfWork(database, recorder, SQLiteFileLinkReader()),
            attention_operations=SQLiteIntakeAttentionOperations(
                recorder, SQLiteIntakeSourceReader()
            ),
        )

    def correction(self, base, key: str):
        return self.service.correct(
            base["sourceId"],
            command("Corrected evidence.").envelope,
            "clarified",
            key,
            expected_source_revision=base["sourceRevision"],
            expected_evidence_revision_id=base["evidenceRevisionId"],
        )

    def attention(self, base, target: str, key: str):
        return self.service.attention(
            base["sourceId"],
            target=target,
            reason="operator decision",
            idempotency_key=key,
            expected_revision=base["evidenceRevisionId"],
            expected_source_revision=base["sourceRevision"],
            expected_status=base["attentionStatus"],
        )

    def test_admission_and_supersession_recover_original_results_after_later_changes(self):
        corrected = self.correction(self.source, str(uuid4()))
        replacement_command = command("Replacement evidence.")
        replacement = self.service.supersede(
            corrected["sourceId"],
            replacement_command,
            expected_source_revision=corrected["sourceRevision"],
            expected_evidence_revision_id=corrected["evidenceRevisionId"],
        )
        self.attention(replacement, "dismissed", str(uuid4()))
        self.assertEqual(self.source, self.service.admit(self.original_command))
        self.assertEqual(
            self.source, self.service.receipt_by_key(self.original_command.idempotency_key)
        )
        self.assertEqual(self.source, self.service.receipt(self.source["operationId"]))
        replay = self.service.supersede(
            corrected["sourceId"],
            replacement_command,
            expected_source_revision=corrected["sourceRevision"],
            expected_evidence_revision_id=corrected["evidenceRevisionId"],
        )
        self.assertEqual(replacement, replay)
        self.assertEqual(
            replacement, self.service.receipt_by_key(replacement_command.idempotency_key)
        )
        validate_latest_schema(self.database)

    def test_attention_aba_rejects_old_source_revision_without_changing_evidence(self):
        dismissed = self.attention(self.source, "dismissed", str(uuid4()))
        reopened = self.attention(dismissed, "unprocessed", str(uuid4()))
        self.assertEqual(self.source["evidenceRevisionId"], reopened["evidenceRevisionId"])
        self.assertEqual(3, reopened["sourceRevision"])
        with self.assertRaises(IntakeConflictError) as failure:
            self.attention(self.source, "dismissed", str(uuid4()))
        self.assertEqual("intake_attention_conflict", failure.exception.code)
        with self.assertRaises(IntakeConflictError):
            self.correction(self.source, str(uuid4()))
        with self.assertRaises(IntakeConflictError):
            self.service.supersede(
                self.source["sourceId"],
                command(),
                expected_source_revision=1,
                expected_evidence_revision_id=self.source["evidenceRevisionId"],
            )
        validate_latest_schema(self.database)

    def test_attention_replay_and_changed_concurrency_metadata(self):
        key = str(uuid4())
        dismissed = self.attention(self.source, "dismissed", key)
        self.attention(dismissed, "unprocessed", str(uuid4()))
        self.assertEqual(dismissed, self.attention(self.source, "dismissed", key))
        self.assertEqual(dismissed, self.service.receipt_by_key(key))
        with self.assertRaises(IntakeConflictError):
            self.attention({**self.source, "sourceRevision": 2}, "dismissed", key)

    def test_source_and_evidence_revision_validation_for_direct_callers(self):
        for revision in (True, 0, -1, "1", None):
            with self.subTest(revision=revision), self.assertRaises(IntakeError):
                self.correction({**self.source, "sourceRevision": revision}, str(uuid4()))
        with self.assertRaises(IntakeConflictError):
            self.correction({**self.source, "evidenceRevisionId": str(uuid4())}, str(uuid4()))
        self.assertEqual(1, self.service.get(self.source["sourceId"])["sourceRevision"])

    def test_one_concurrent_correction_wins_and_duplicate_key_replays(self):
        barrier = Barrier(2)
        key = str(uuid4())

        def submit():
            barrier.wait()
            return self.correction(self.source, key)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(2, results[0]["sourceRevision"])
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                2,
                connection.execute("SELECT count(*) FROM intake_evidence_revisions").fetchone()[0],
            )
        validate_latest_schema(self.database)

    def test_audit_failure_rolls_back_revision_and_receipt(self):
        key = str(uuid4())
        with patch.object(
            self.service.unit_of_work.recorder,
            "record_change",
            side_effect=RuntimeError("audit failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "audit failed"):
                self.correction(self.source, key)
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                1, connection.execute("SELECT source_revision FROM intake_sources").fetchone()[0]
            )
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT count(*) FROM intake_source_operations WHERE idempotency_key=?", (key,)
                ).fetchone()[0],
            )
        validate_latest_schema(self.database)

    def attachment_command(self):
        source = self.root / "attachment.txt"
        source.write_text("Retained evidence bytes.", encoding="utf-8")
        files = FileService(
            self.workspace,
            FilesystemContentStore(self.workspace.paths.files),
            SQLiteFileUnitOfWork(self.database, self.recorder),
            link_validators=(IntakeSourceFileLinkValidator(),),
        )
        self.service.files = files
        base = command("Evidence with an attachment.")
        return IntakeAdmissionCommand(
            base.envelope,
            base.origin_system,
            base.idempotency_key,
            (AttachmentInput(source, "evidence.txt", "text/plain"),),
        ), files

    def test_import_receipt_recovery_never_republishes_and_commit_failure_rolls_back_bytes(self):
        payload, files = self.attachment_command()
        engine = self.service.unit_of_work.engine

        def fail_commit(_connection):
            raise RuntimeError("database commit failed")

        event.listen(engine, "commit", fail_commit)
        try:
            with self.assertRaisesRegex(RuntimeError, "database commit failed"):
                self.service.admit(payload)
        finally:
            event.remove(engine, "commit", fail_commit)
        self.assertEqual([], list((self.workspace.paths.files / "managed").iterdir()))
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                0, connection.execute("SELECT count(*) FROM file_records").fetchone()[0]
            )
        result = self.service.admit(payload)
        payload.attachments[0].source.unlink()
        with patch.object(files, "attachment_batch", side_effect=AssertionError("republication")):
            self.assertEqual(result, self.service.receipt_by_key(payload.idempotency_key))
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(
                1, connection.execute("SELECT count(*) FROM file_records").fetchone()[0]
            )
        validate_latest_schema(self.database)

    def test_recovery_is_bounded_and_sensitive_receipts_require_audit(self):
        key = str(uuid4())
        corrected = self.correction(self.source, key)
        statements = []

        def capture(_connection, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        engine = self.service.unit_of_work.engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            self.assertEqual(corrected, self.service.receipt_by_key(key))
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        self.assertLessEqual(len(statements), 2)
        with patch.object(
            self.service.unit_of_work.recorder,
            "record_change",
            side_effect=RuntimeError("audit failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "audit failed"):
                self.service.receipt(corrected["operationId"])

    def test_retained_validation_rejects_rewritten_source_revision_or_receipt(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE intake_sources SET source_revision=2")
        with self.assertRaises(MigrationSchemaError):
            validate_latest_schema(self.database)
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE intake_sources SET source_revision=1")
            connection.execute("DROP TRIGGER intake_source_operations_no_update")
            result = {**self.source, "operationId": str(uuid4())}
            connection.execute(
                "UPDATE intake_source_operations SET result_json=?",
                (json.dumps(result, sort_keys=True, separators=(",", ":")),),
            )
        from app.modules.intake.infrastructure.schema_validation import validate_intake_data

        with self.service.unit_of_work.engine.connect() as connection:
            with self.assertRaises(MigrationSchemaError):
                validate_intake_data(connection)

    def test_encrypted_backup_restores_original_receipts_and_revisions(self):
        self.original_command, _files = self.attachment_command()
        self.source = self.service.admit(self.original_command)
        key = str(uuid4())
        corrected = self.correction(self.source, key)
        self.attention(corrected, "dismissed", str(uuid4()))
        backups = BackupService(
            self.workspace,
            self.recorder,
            lambda database: AuditRecorder(SQLiteAuditRepository(database)),
        )
        passphrase = "a sufficiently long intake backup passphrase"
        archive = backups.create_backup(passphrase, output_path=self.root / "intake.epm-backup")
        restored_root = self.root / "restored"
        backups.restore(archive.archive_path, passphrase, restored_root)
        restored_database = restored_root / "database" / "property-management.sqlite"
        restored = self.make_service(restored_database)
        self.assertEqual(
            self.source, restored.receipt_by_key(self.original_command.idempotency_key)
        )
        self.assertEqual(corrected, restored.receipt_by_key(key))
        self.assertEqual(3, restored.get(self.source["sourceId"])["sourceRevision"])
        validate_latest_schema(restored_database)

    def test_api_requires_concurrency_fields_and_exposes_safe_recovery(self):
        class Runtime:
            ready = True
            can_write = True
            error = None

        app = FastAPI()
        app.include_router(build_router(self.service, Runtime()))
        with TestClient(app) as client:
            response = client.get(
                f"/api/intake/sources/operations/by-key/{self.original_command.idempotency_key}"
            )
            self.assertEqual(200, response.status_code)
            self.assertEqual(self.source, response.json())
            payload = {
                "reason": "dismiss",
                "idempotencyKey": str(uuid4()),
                "expectedRevision": self.source["evidenceRevisionId"],
                "expectedStatus": "unprocessed",
            }
            route = f"/api/intake/sources/{self.source['sourceId']}/dismiss"
            self.assertEqual(422, client.post(route, json=payload).status_code)
            self.assertEqual(
                422,
                client.post(route, json={**payload, "expectedSourceRevision": True}).status_code,
            )
            payload["expectedSourceRevision"] = 1
            first = client.post(route, json=payload)
            self.assertEqual(200, first.status_code)
            self.assertEqual(first.json(), client.post(route, json=payload).json())
            self.assertEqual(
                409,
                client.post(route, json={**payload, "idempotencyKey": str(uuid4())}).status_code,
            )
            stale = client.post(route, json={**payload, "idempotencyKey": str(uuid4())})
            self.assertEqual(2, stale.json()["detail"]["currentRevision"])
            self.assertEqual(
                self.source["evidenceRevisionId"],
                stale.json()["detail"]["currentEvidenceRevisionId"],
            )

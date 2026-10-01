from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from sqlalchemy import event

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.application.errors import PublicationCleanupIncomplete
from app.modules.intake.api.router import build_router
from app.modules.intake.application.ports import (
    MAX_INTAKE_SOURCE_BATCH,
    IntakeEvidenceReadContext,
)
from app.modules.intake.application.service import IntakeAdmissionCommand, IntakeService
from app.modules.intake.domain.models import EvidenceEnvelope, IntakeConflictError, IntakeReadLimitError
from app.modules.intake.infrastructure.unit_of_work import SQLiteIntakeUnitOfWork
from app.modules.intake.infrastructure.source_reader import SQLiteIntakeSourceReader
from app.platform.product_migrations import initialize_latest_schema, validate_latest_schema
from app.platform.sqlite_engine import immediate_transaction


class IntakeTests(TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "workspace.sqlite"; initialize_latest_schema(self.database)
        self.recorder = AuditRecorder(SQLiteAuditRepository(self.database))
        self.service = IntakeService(SQLiteIntakeUnitOfWork(self.database, self.recorder))

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

    def test_consumer_source_reader_supports_bounded_current_and_historical_reads(self) -> None:
        first = self.service.admit(self.command(body="First evidence."))
        second = self.service.admit(self.command(body="Second evidence."))
        corrected = self.service.correct(
            first["sourceId"],
            EvidenceEnvelope("operator_note", "internal", "Corrected first evidence.", "2026-01-01T12:00:00+00:00"),
            "clarified", str(uuid4()),
        )
        reader = SQLiteIntakeSourceReader(self.recorder)
        statements: list[str] = []

        def capture(*args):
            if args[2].lstrip().upper().startswith("SELECT"):
                statements.append(args[2])

        engine = self.service.unit_of_work.engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            with engine.connect() as connection:
                self.assertEqual({}, reader.source_projections(connection, ()))
                start = len(statements)
                summaries = reader.source_projections(connection, (first["sourceId"], second["sourceId"], first["sourceId"]))
                self.assertEqual(1, len(statements) - start)
                self.assertEqual({first["sourceId"], second["sourceId"]}, set(summaries))
                self.assertEqual(corrected["revision"], summaries[first["sourceId"]]["revision"])
                original = reader.revision_projection(connection, first["sourceId"], first["revision"])
                self.assertEqual(first["revision"], original["revision"])
                self.assertEqual("submitted", original["revisionKind"])
                detail = reader.evidence_detail(
                    connection, first["sourceId"], corrected["revision"],
                    audit=IntakeEvidenceReadContext("local_operator", None, "intake_evidence_read", str(uuid4())),
                    max_history=1,
                )
                self.assertEqual("Corrected first evidence.", detail["evidence"]["body"])
                self.assertTrue(detail["historyTruncated"])
                self.assertIsNone(reader.revision_projection(connection, second["sourceId"], first["revision"]))
        finally:
            event.remove(engine, "before_cursor_execute", capture)

    def test_consumer_evidence_detail_is_audited_and_fails_closed(self) -> None:
        source = self.service.admit(self.command())
        reader = SQLiteIntakeSourceReader(self.recorder)
        correlation_id = str(uuid4())
        context = IntakeEvidenceReadContext("local_operator", None, "intake_evidence_read", correlation_id)
        engine = self.service.unit_of_work.engine
        with immediate_transaction(engine) as connection:
            detail = reader.evidence_detail(connection, source["sourceId"], source["revision"], audit=context)
            self.assertEqual("The sink leaks.", detail["evidence"]["body"])
        with engine.connect() as connection:
            audit = connection.exec_driver_sql(
                "SELECT action, correlation_id, after_snapshot FROM audit_events WHERE correlation_id = ?",
                (correlation_id,),
            ).mappings().one()
        self.assertEqual("evidence_read", audit["action"])
        self.assertEqual(correlation_id, audit["correlation_id"])
        self.assertIn(source["revision"], audit["after_snapshot"])

        class FailingRecorder:
            def record_change(self, *args, **kwargs):
                raise RuntimeError("audit unavailable")

        with immediate_transaction(engine) as connection:
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                SQLiteIntakeSourceReader(FailingRecorder()).evidence_detail(
                    connection, source["sourceId"], source["revision"], audit=IntakeEvidenceReadContext(
                        "local_operator", None, "intake_evidence_read", str(uuid4()),
                    ),
                )

    def test_consumer_source_reader_enforces_the_unique_batch_limit(self) -> None:
        source = self.service.admit(self.command())
        reader = SQLiteIntakeSourceReader(self.recorder)
        engine = self.service.unit_of_work.engine
        exact_limit = (source["sourceId"], *(str(uuid4()) for _ in range(MAX_INTAKE_SOURCE_BATCH - 1)))
        duplicate_at_limit = (*exact_limit, source["sourceId"])
        over_limit = (*exact_limit, str(uuid4()))
        statements: list[str] = []

        def capture(*args):
            if args[2].lstrip().upper().startswith("SELECT"):
                statements.append(args[2])

        event.listen(engine, "before_cursor_execute", capture)
        try:
            with engine.connect() as connection:
                self.assertEqual({}, reader.source_projections(connection, ()))
                self.assertIn(source["sourceId"], reader.source_projections(connection, exact_limit))
                self.assertIn(source["sourceId"], reader.source_projections(connection, duplicate_at_limit))
                before = len(statements)
                with self.assertRaises(IntakeReadLimitError):
                    reader.source_projections(connection, over_limit)
                self.assertEqual(before, len(statements))
        finally:
            event.remove(engine, "before_cursor_execute", capture)

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

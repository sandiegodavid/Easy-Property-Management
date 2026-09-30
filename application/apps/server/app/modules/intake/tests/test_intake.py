from __future__ import annotations
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.application.errors import PublicationCleanupIncomplete
from app.modules.intake.api.router import build_router
from app.modules.intake.application.service import IntakeAdmissionCommand, IntakeService
from app.modules.intake.domain.models import EvidenceEnvelope, IntakeConflictError
from app.modules.intake.infrastructure.schema_validation import validate_intake_data
from app.modules.intake.infrastructure.unit_of_work import SQLiteIntakeUnitOfWork
from app.platform.migration_errors import MigrationSchemaError
from app.platform.sqlite_engine import immediate_transaction
from app.platform.product_migrations import initialize_latest_schema, validate_latest_schema


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

    def test_retained_validation_requires_correlated_operation_audits(self) -> None:
        source = self.service.admit(self.command())
        with immediate_transaction(SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine) as connection:
            connection.exec_driver_sql("DROP TRIGGER audit_events_no_delete")
            connection.exec_driver_sql("DELETE FROM audit_events WHERE entity_type = 'intake_source' AND entity_id = ? AND action = 'admitted'", (source["sourceId"],))
        with self.assertRaises(MigrationSchemaError):
            with SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine.connect() as connection:
                validate_intake_data(connection)

    def test_retained_validation_rejects_operation_result_from_another_source(self) -> None:
        first = self.service.admit(self.command(body="First source."))
        second = self.service.admit(self.command(body="Second source."))
        first_revision = self.service.get(first["sourceId"])["revision"]
        with immediate_transaction(SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine) as connection:
            connection.exec_driver_sql("INSERT INTO intake_source_operations (id, operation_type, idempotency_key, request_fingerprint, request_payload_json, source_id, result_revision_id, outcome, error_code, correlation_id, actor_kind, actor_reference, created_at) SELECT ?, 'correct', ?, request_fingerprint, request_payload_json, ?, ?, 'succeeded', NULL, correlation_id, 'local_operator', NULL, created_at FROM intake_source_operations LIMIT 1", (str(uuid4()), str(uuid4()), second["sourceId"], first_revision))
        with self.assertRaises(MigrationSchemaError):
            validate_latest_schema(self.database)

    def test_retained_validation_requires_duplicate_candidate_audit(self) -> None:
        self.service.admit(self.command(body="Duplicate source."))
        self.service.admit(self.command(body="Duplicate source."))
        with immediate_transaction(SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine) as connection:
            candidate_id = connection.exec_driver_sql("SELECT id FROM intake_source_duplicate_candidates").scalar_one()
            connection.exec_driver_sql("DROP TRIGGER audit_events_no_delete")
            connection.exec_driver_sql("DELETE FROM audit_events WHERE entity_type = 'intake_source_duplicate_candidate' AND entity_id = ?", (candidate_id,))
        with self.assertRaises(MigrationSchemaError):
            with SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine.connect() as connection:
                validate_intake_data(connection)

    def test_retained_validation_rejects_present_but_wrong_admission_snapshot(self) -> None:
        source = self.service.admit(self.command())
        with immediate_transaction(SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine) as connection:
            connection.exec_driver_sql("DROP TRIGGER audit_events_no_update")
            connection.exec_driver_sql("UPDATE audit_events SET after_snapshot = '{}' WHERE entity_type = 'intake_source' AND entity_id = ? AND action = 'admitted'", (source["sourceId"],))
        with self.assertRaises(MigrationSchemaError):
            with SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine.connect() as connection:
                validate_intake_data(connection)

    def test_retained_validation_rejects_dangling_sensitive_read_audit(self) -> None:
        source = self.service.admit(self.command())
        self.service.get(source["sourceId"])
        with immediate_transaction(SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine) as connection:
            connection.exec_driver_sql("DROP TRIGGER audit_events_no_update")
            connection.exec_driver_sql("UPDATE audit_events SET after_snapshot = ? WHERE entity_type = 'intake_source' AND entity_id = ? AND action = 'evidence_read'", (json.dumps({"sourceId": source["sourceId"], "revision": str(uuid4())}), source["sourceId"]))
        with self.assertRaises(MigrationSchemaError):
            with SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine.connect() as connection:
                validate_intake_data(connection)

    def test_retained_validation_rejects_mismatched_exact_content_candidate(self) -> None:
        first = self.service.admit(self.command(body="First evidence."))
        second = self.service.admit(self.command(body="Different evidence."))
        candidate_id = str(uuid4())
        with immediate_transaction(SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine) as connection:
            rows = list(connection.exec_driver_sql("SELECT id, source_id, correlation_id, created_at FROM intake_source_operations ORDER BY created_at").mappings())
            operation = next(row for row in rows if row["source_id"] == second["sourceId"])
            left, right = sorted((first["sourceId"], second["sourceId"]))
            connection.exec_driver_sql("INSERT INTO intake_source_duplicate_candidates (id, source_id, candidate_source_id, reason, confidence_label, confidence_provenance, disposition, decided_at, decision_reason, created_at) VALUES (?, ?, ?, 'content_fingerprint', 'high', 'exact_canonical_evidence', 'unreviewed', NULL, NULL, ?)", (candidate_id, left, right, operation["created_at"]))
            AuditRecorder(SQLiteAuditRepository(self.database)).record_change(
                connection.connection.driver_connection,
                entity_type="intake_source_duplicate_candidate", entity_id=candidate_id, action="created",
                before=None,
                after={"sourceId": left, "candidateSourceId": right, "introducedSourceId": second["sourceId"], "reason": "content_fingerprint", "disposition": "unreviewed"},
                reason="intake_duplicate_candidate_detected", correlation_id=operation["correlation_id"],
            )
        with self.assertRaises(MigrationSchemaError):
            validate_latest_schema(self.database)

    def test_retained_validation_rejects_reused_candidate_correlation(self) -> None:
        first = self.service.admit(self.command(body="Duplicate evidence."))
        self.service.admit(self.command(body="Duplicate evidence."))
        with immediate_transaction(SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine) as connection:
            candidate_id = connection.exec_driver_sql("SELECT id FROM intake_source_duplicate_candidates").scalar_one()
            original_correlation = connection.exec_driver_sql("SELECT correlation_id FROM intake_source_operations WHERE source_id = ?", (first["sourceId"],)).scalar_one()
            connection.exec_driver_sql("DROP TRIGGER audit_events_no_update")
            connection.exec_driver_sql("UPDATE audit_events SET correlation_id = ? WHERE entity_type = 'intake_source_duplicate_candidate' AND entity_id = ?", (original_correlation, candidate_id))
        with self.assertRaises(MigrationSchemaError):
            with SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine.connect() as connection:
                validate_intake_data(connection)

    def test_retained_validation_rejects_two_operations_sharing_one_audit_set(self) -> None:
        source = self.service.admit(self.command())
        with immediate_transaction(SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine) as connection:
            connection.exec_driver_sql(
                "INSERT INTO intake_source_operations (id, operation_type, idempotency_key, request_fingerprint, request_payload_json, source_id, result_revision_id, outcome, error_code, correlation_id, actor_kind, actor_reference, created_at) SELECT ?, operation_type, ?, request_fingerprint, request_payload_json, source_id, result_revision_id, outcome, error_code, correlation_id, actor_kind, actor_reference, created_at FROM intake_source_operations WHERE source_id = ?",
                (str(uuid4()), str(uuid4()), source["sourceId"]),
            )
        with self.assertRaises(MigrationSchemaError):
            with SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine.connect() as connection:
                validate_intake_data(connection)

    def test_retained_validation_rejects_illegal_attention_transition(self) -> None:
        source = self.service.admit(self.command())
        self.service.attention(source["sourceId"], target="dismissed", reason="No action needed.",
                               idempotency_key=str(uuid4()), expected_revision=source["revision"],
                               expected_status="unprocessed")
        with immediate_transaction(SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine) as connection:
            connection.exec_driver_sql("DROP TRIGGER audit_events_no_update")
            connection.exec_driver_sql("UPDATE intake_sources SET attention_status = 'resolved' WHERE id = ?", (source["sourceId"],))
            connection.exec_driver_sql("UPDATE audit_events SET before_snapshot = ?, after_snapshot = ? WHERE entity_type = 'intake_source' AND entity_id = ? AND action = 'attention_changed'", (json.dumps({"attentionStatus": "unprocessed"}), json.dumps({"attentionStatus": "resolved"}), source["sourceId"]))
        with self.assertRaises(MigrationSchemaError):
            with SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine.connect() as connection:
                validate_intake_data(connection)

    def test_retained_validation_rejects_tampered_operation_fingerprint_before_retry(self) -> None:
        command = self.command()
        self.service.admit(command)
        with immediate_transaction(SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine) as connection:
            connection.exec_driver_sql("DROP TRIGGER intake_source_operations_no_update")
            connection.exec_driver_sql("UPDATE intake_source_operations SET request_fingerprint = ? WHERE idempotency_key = ?", ("0" * 64, command.idempotency_key))
        with self.assertRaises(MigrationSchemaError):
            with SQLiteIntakeUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database))).engine.connect() as connection:
                validate_intake_data(connection)
        with self.assertRaises(IntakeConflictError):
            self.service.admit(command)

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

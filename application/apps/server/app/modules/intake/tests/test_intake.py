from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.intake.application.service import IntakeAdmissionCommand, IntakeService
from app.modules.intake.domain.models import EvidenceEnvelope, IntakeConflictError
from app.modules.intake.infrastructure.unit_of_work import SQLiteIntakeUnitOfWork
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

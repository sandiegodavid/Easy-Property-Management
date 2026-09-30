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
from app.modules.intake.application.service import AttachmentInput, IntakeAdmissionCommand, IntakeService
from app.modules.intake.domain.models import EvidenceEnvelope, IntakeConflictError, IntakePayloadTooLargeError
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

    def test_list_api_filters_by_account_identity_state(self) -> None:
        confirmed = self.service.admit(IntakeAdmissionCommand(
            EvidenceEnvelope("operator_note", "internal", "Confirmed source.", "2026-01-01T12:00:00+00:00"),
            "manual", str(uuid4()), "a" * 64, "operator_confirmed",
        ))
        self.service.admit(IntakeAdmissionCommand(
            EvidenceEnvelope("operator_note", "internal", "Unverified source.", "2026-01-01T12:00:00+00:00"),
            "manual", str(uuid4()), None, "unverified_claim",
        ))

        class ReadyRuntime:
            ready = True
            can_write = True
            error = None

        app = FastAPI()
        app.include_router(build_router(self.service, ReadyRuntime()))
        response = TestClient(app).get(
            "/api/intake/sources", params={"accountIdentityState": "operator_confirmed"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual([confirmed["sourceId"]], [item["sourceId"] for item in response.json()["items"]])
        invalid = TestClient(app).get(
            "/api/intake/sources", params={"accountIdentityState": "invented"},
        )
        self.assertEqual(422, invalid.status_code)
        self.assertEqual("intake_validation", invalid.json()["detail"]["code"])

    def test_oversized_json_and_import_content_return_413(self) -> None:
        class ReadyRuntime:
            ready = True
            can_write = True
            error = None

        app = FastAPI()
        app.include_router(build_router(self.service, ReadyRuntime()))
        client = TestClient(app)
        payload = {
            "sourceKind": "operator_note", "channel": "internal", "body": "x" * 131_073,
            "occurredAtUtc": "2026-01-01T12:00:00Z", "originSystem": "manual",
            "idempotencyKey": str(uuid4()),
        }

        json_response = client.post("/api/intake/sources", json=payload)
        import_response = client.post(
            "/api/intake/sources/import", data={"metadata": json.dumps(payload)},
        )

        for response in (json_response, import_response):
            self.assertEqual(413, response.status_code)
            self.assertEqual("intake_payload_too_large", response.json()["detail"]["code"])

    def test_too_many_import_attachments_returns_413(self) -> None:
        class ReadyRuntime:
            ready = True
            can_write = True
            error = None

        app = FastAPI()
        app.include_router(build_router(self.service, ReadyRuntime()))
        metadata = {
            "sourceKind": "operator_note", "channel": "internal", "body": "Bounded evidence.",
            "occurredAtUtc": "2026-01-01T12:00:00Z", "originSystem": "manual",
            "idempotencyKey": str(uuid4()),
        }
        response = TestClient(app).post(
            "/api/intake/sources/import",
            data={"metadata": json.dumps(metadata)},
            files=[("files", (f"attachment-{index}.txt", b"", "text/plain")) for index in range(21)],
        )

        self.assertEqual(413, response.status_code)
        self.assertEqual("intake_payload_too_large", response.json()["detail"]["code"])

    def test_direct_admission_classifies_all_attachment_limit_overflows(self) -> None:
        root = Path(self.temporary.name)
        small = root / "small.bin"
        small.write_bytes(b"x")
        with self.assertRaises(IntakePayloadTooLargeError):
            IntakeAdmissionCommand(
                self.command().envelope, "manual", str(uuid4()),
                attachments=tuple(AttachmentInput(small, f"{index}.bin", None) for index in range(21)),
            )

        oversized = root / "oversized.bin"
        with oversized.open("wb") as handle:
            handle.seek(50 * 1024 * 1024)
            handle.write(b"x")
        with self.assertRaises(IntakePayloadTooLargeError):
            self.service.admit(IntakeAdmissionCommand(
                self.command().envelope, "manual", str(uuid4()),
                attachments=(AttachmentInput(oversized, "oversized.bin", None),),
            ))

        aggregate = []
        for index, size in enumerate((50 * 1024 * 1024, 50 * 1024 * 1024, 1)):
            path = root / f"aggregate-{index}.bin"
            with path.open("wb") as handle:
                handle.seek(size - 1)
                handle.write(b"x")
            aggregate.append(AttachmentInput(path, path.name, None))
        with self.assertRaises(IntakePayloadTooLargeError):
            self.service.admit(IntakeAdmissionCommand(
                self.command().envelope, "manual", str(uuid4()), attachments=tuple(aggregate),
            ))

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

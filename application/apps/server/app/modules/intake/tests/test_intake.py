from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.audit.api.router import build_router as build_audit_router
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.domain.models import DEFAULT_SNAPSHOT_POLICY, AuditSnapshotPolicyRegistry
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.application.errors import PublicationCleanupIncomplete
from app.modules.files.application.service import FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.intake.api.router import build_router
from app.modules.intake.application.file_links import IntakeSourceFileLinkValidator
from app.modules.intake.application.service import (
    AttachmentInput,
    IntakeAdmissionCommand,
    IntakeService,
    TrustedIntakeAdmission,
)
from app.modules.intake.domain.audit_policy import INTAKE_ACTIVITY_POLICY
from app.modules.intake.domain.models import (
    AttentionTransition,
    EvidenceEnvelope,
    IntakeAdmissionContext,
    IntakeConflictError,
    IntakeError,
)
from app.modules.intake.infrastructure.attention_operations import SQLiteIntakeAttentionOperations
from app.modules.intake.domain.models import IntakePayloadTooLargeError
from app.modules.intake.infrastructure.schema_validation import validate_intake_data
from app.modules.intake.infrastructure.unit_of_work import SQLiteIntakeUnitOfWork
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import initialize_latest_schema, validate_latest_schema
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction


class IntakeTests(TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "workspace.sqlite"; initialize_latest_schema(self.database)
        self.recorder = AuditRecorder(SQLiteAuditRepository(self.database))
        self.attention_operations = SQLiteIntakeAttentionOperations(self.recorder)
        self.service = IntakeService(
            SQLiteIntakeUnitOfWork(self.database, self.recorder),
            attention_operations=self.attention_operations,
        )
        self.trusted_admission = TrustedIntakeAdmission(self.service)

    def admit_trusted(self, command: IntakeAdmissionCommand, reference: str = "connection-1") -> dict[str, object]:
        return self.trusted_admission.admit(
            command,
            IntakeAdmissionContext("assistant_connection", reference, "a" * 64, "transport_verified"),
        )

    def supersede_trusted(self, source_id: str, replacement: IntakeAdmissionCommand) -> dict[str, object]:
        return self.admit_trusted(replace(replacement, supersedes_source_id=source_id))

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

    def test_correction_replay_returns_its_recorded_revision_after_a_later_correction(self) -> None:
        source = self.service.admit(self.command())
        first_key = str(uuid4())
        first_envelope = EvidenceEnvelope("operator_note", "internal", "First correction.", "2026-01-01T12:00:00+00:00")
        first = self.service.correct(source["sourceId"], first_envelope, "first clarification", first_key)
        second = self.service.correct(
            source["sourceId"],
            EvidenceEnvelope("operator_note", "internal", "Second correction.", "2026-01-01T12:00:00+00:00"),
            "second clarification", str(uuid4()),
        )

        replay = self.service.correct(source["sourceId"], first_envelope, "first clarification", first_key)

        self.assertEqual(first, replay)
        self.assertNotEqual(second["revision"], replay["revision"])
        self.assertEqual(2, len(replay["revisions"]))

    def test_correction_replay_is_unchanged_after_later_attention_integrity_and_duplicate_changes(self) -> None:
        source = self.service.admit(self.command())
        key = str(uuid4())
        envelope = EvidenceEnvelope("operator_note", "internal", "Corrected evidence.", "2026-01-01T12:00:00+00:00")
        first = self.service.correct(source["sourceId"], envelope, "clarified", key)

        self.service.attention(
            source["sourceId"], target="in_review", reason="review needed",
            idempotency_key=str(uuid4()), expected_revision=first["revision"], expected_status="unprocessed",
        )
        self.service.set_integrity(
            source["sourceId"], available=False, reason="attachment_content_unavailable",
            idempotency_key=str(uuid4()),
        )
        self.service.admit(self.command(body="Corrected evidence."))

        self.assertEqual(
            first,
            self.service.correct(source["sourceId"], envelope, "clarified", key),
        )

    def test_correction_replay_is_unchanged_after_source_supersession(self) -> None:
        source = self.service.admit(self.command())
        key = str(uuid4())
        envelope = EvidenceEnvelope("operator_note", "internal", "Corrected evidence.", "2026-01-01T12:00:00+00:00")
        first = self.service.correct(source["sourceId"], envelope, "clarified", key)

        self.service.supersede(source["sourceId"], self.command(body="Replacement evidence."))

        self.assertEqual(
            first,
            self.service.correct(source["sourceId"], envelope, "clarified", key),
        )

    def test_trusted_external_replay_compares_evidence_and_reserves_each_key(self) -> None:
        def trusted(key: str, body: str) -> IntakeAdmissionCommand:
            return IntakeAdmissionCommand(
                EvidenceEnvelope("email_message", "email", body, "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
                "gmail", key,
            )
        replay_key = str(uuid4())
        first = self.admit_trusted(trusted(replay_key, "A retained email."))
        self.assertEqual(first, self.admit_trusted(trusted(replay_key, "A retained email.")))
        with self.assertRaises(IntakeConflictError):
            self.admit_trusted(trusted(replay_key, "A retained email."), "connection-2")
        self.assertEqual(first["sourceId"], self.admit_trusted(trusted(str(uuid4()), "A retained email."), "connection-2")["sourceId"])

    def test_trusted_admission_audits_authenticated_actors(self) -> None:
        assistant = self.admit_trusted(self.command(), "connection-7")
        voice_context = IntakeAdmissionContext("voice_workflow", "voice-grant-8", "a" * 64, "transport_verified")
        voice = self.trusted_admission.admit(self.command(), voice_context)
        replacement = self.trusted_admission.admit(
            replace(self.command(body="Replacement evidence."), supersedes_source_id=assistant["sourceId"]),
            voice_context,
        )

        with sqlite3.connect(self.database) as connection:
            for result, actor_kind, reference in (
                (assistant, "ai_assistant", "connection-7"),
                (voice, "connector", "voice-grant-8"),
            ):
                source_audit = connection.execute(
                    "SELECT actor_kind, actor_reference FROM audit_events WHERE entity_type='intake_source' AND entity_id=? AND action='admitted'",
                    (result["sourceId"],),
                ).fetchone()
                revision_audit = connection.execute(
                    "SELECT actor_kind, actor_reference FROM audit_events WHERE entity_type='intake_evidence_revision' AND entity_id=? AND action='created'",
                    (result["revision"],),
                ).fetchone()
                self.assertEqual((actor_kind, reference), source_audit)
                self.assertEqual((actor_kind, reference), revision_audit)
            superseded = connection.execute(
                "SELECT actor_kind, actor_reference FROM audit_events WHERE entity_type='intake_source' AND entity_id=? AND action='superseded'",
                (assistant["sourceId"],),
            ).fetchone()
        self.assertEqual(("connector", "voice-grant-8"), superseded)
        self.assertNotEqual(assistant["sourceId"], replacement["sourceId"])

    def test_trusted_context_normalizes_submitter_reference(self) -> None:
        self.assertEqual("connection-9", IntakeAdmissionContext("assistant_connection", " connection-9 ").submitter_reference)
        for invalid in ("bad\u0085reference", "x" * 501):
            with self.assertRaises(IntakeError):
                IntakeAdmissionContext("assistant_connection", invalid)

    def test_trusted_external_supersession_replaces_the_current_identity_tip(self) -> None:
        def trusted(key: str, body: str) -> IntakeAdmissionCommand:
            return IntakeAdmissionCommand(
                EvidenceEnvelope("email_message", "email", body,
                                 "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
                "gmail", key,
            )

        original = self.admit_trusted(trusted(str(uuid4()), "Original retained email."))
        replacement = self.supersede_trusted(
            original["sourceId"], trusted(str(uuid4()), "Corrected retained email."),
        )

        self.assertNotEqual(original["sourceId"], replacement["sourceId"])
        self.assertEqual("superseded", self.service.get(original["sourceId"])["technicalStatus"])
        self.assertEqual(replacement["sourceId"], self.admit_trusted(
            trusted(str(uuid4()), "Corrected retained email.")
        )["sourceId"])
        with self.assertRaises(IntakeConflictError) as conflict:
            self.admit_trusted(trusted(str(uuid4()), "Conflicting retained email."))
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
        recorder = AuditRecorder(SQLiteAuditRepository(self.database))
        service = IntakeService(
            SQLiteIntakeUnitOfWork(self.database, recorder),
            files,
            attention_operations=SQLiteIntakeAttentionOperations(recorder),
        )

        def trusted(key: str, attachment: Path) -> IntakeAdmissionCommand:
            return IntakeAdmissionCommand(
                EvidenceEnvelope("email_message", "email", "Retained email.",
                                 "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
                "gmail", key,
                attachments=(AttachmentInput(attachment, attachment.name, "message/rfc822"),),
            )

        trusted_admission = TrustedIntakeAdmission(service)
        context = IntakeAdmissionContext("assistant_connection", "connection-1", "a" * 64, "transport_verified")
        admit = lambda command: trusted_admission.admit(command, context)
        original_command = trusted(str(uuid4()), original_attachment)
        original = admit(original_command)
        replacement = admit(replace(trusted(str(uuid4()), replacement_attachment), supersedes_source_id=original["sourceId"]))
        historical = admit(trusted(str(uuid4()), original_attachment))
        current = admit(trusted(str(uuid4()), replacement_attachment))
        self.assertEqual(original["sourceId"], historical["sourceId"])
        self.assertEqual(replacement["sourceId"], current["sourceId"])
        with self.assertRaises(IntakeConflictError):
            admit(IntakeAdmissionCommand(
                EvidenceEnvelope("email_message", "email", "Changed body.",
                                 "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
                "gmail", str(uuid4()),
                attachments=(AttachmentInput(replacement_attachment, replacement_attachment.name,
                                             "message/rfc822"),),
            ))
        validate_latest_schema(self.database)

    def test_trusted_replay_resolves_a_noncurrent_revision_after_supersession(self) -> None:
        def trusted(key: str, body: str) -> IntakeAdmissionCommand:
            return IntakeAdmissionCommand(
                EvidenceEnvelope("email_message", "email", body,
                                 "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
                "gmail", key,
            )

        original = self.admit_trusted(trusted(str(uuid4()), "Original retained email."))
        corrected = self.service.correct(
            original["sourceId"],
            EvidenceEnvelope("email_message", "email", "Corrected source evidence.",
                             "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
            "corrected source evidence", str(uuid4()),
        )
        replacement = self.supersede_trusted(
            original["sourceId"], trusted(str(uuid4()), "Replacement source evidence."),
        )

        replay = self.admit_trusted(trusted(str(uuid4()), "Original retained email."))
        self.assertEqual(original["sourceId"], replay["sourceId"])
        self.assertEqual(corrected["revision"], replay["revision"])
        self.assertEqual(replacement["sourceId"], self.admit_trusted(
            trusted(str(uuid4()), "Replacement source evidence.")
        )["sourceId"])
        validate_latest_schema(self.database)

    def test_workspace_validation_rejects_a_tampered_trusted_lineage_identity(self) -> None:
        def trusted(key: str, body: str) -> IntakeAdmissionCommand:
            return IntakeAdmissionCommand(
                EvidenceEnvelope("email_message", "email", body,
                                 "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
                "gmail", key,
            )
        original = self.admit_trusted(trusted(str(uuid4()), "Original email."))
        self.supersede_trusted(original["sourceId"], trusted(str(uuid4()), "Replacement email."))
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE intake_sources SET origin_system='tampered' WHERE id=?", (original["sourceId"],))
            connection.commit()
        with self.assertRaises(MigrationSchemaError):
            validate_latest_schema(self.database)

    def test_trusted_supersession_rejects_a_changed_identity(self) -> None:
        original = self.admit_trusted(IntakeAdmissionCommand(
            EvidenceEnvelope("email_message", "email", "Original retained email.",
                             "2026-01-01T12:00:00+00:00", external_source_id="mail-1"),
            "gmail", str(uuid4()),
        ))
        changed = IntakeAdmissionCommand(
            EvidenceEnvelope("email_message", "email", "Replacement email.",
                             "2026-01-01T12:00:00+00:00", external_source_id="mail-2"),
            "gmail", str(uuid4()),
        )
        with self.assertRaisesRegex(IntakeConflictError, "identity"):
            self.supersede_trusted(original["sourceId"], changed)

    def test_pagination_uses_last_returned_cursor_without_a_gap(self) -> None:
        ids = [self.service.admit(self.command(body=f"Evidence {index}"))["sourceId"] for index in range(3)]
        first, cursor = self.service.list(limit=1)
        second, cursor = self.service.list(limit=1, cursor=tuple(cursor.split("|", 1)))
        third, cursor = self.service.list(limit=1, cursor=tuple(cursor.split("|", 1)))
        self.assertEqual(set(ids), {first[0]["sourceId"], second[0]["sourceId"], third[0]["sourceId"]})

    def test_list_api_filters_by_account_identity_state(self) -> None:
        confirmed = self.trusted_admission.admit(
            IntakeAdmissionCommand(
                EvidenceEnvelope("operator_note", "internal", "Confirmed source.", "2026-01-01T12:00:00+00:00"),
                "manual", str(uuid4()),
            ),
            IntakeAdmissionContext("assistant_connection", "confirmed-connection", "a" * 64, "operator_confirmed"),
        )
        self.trusted_admission.admit(
            IntakeAdmissionCommand(
                EvidenceEnvelope("operator_note", "internal", "Unverified source.", "2026-01-01T12:00:00+00:00"),
                "manual", str(uuid4()),
            ),
            IntakeAdmissionContext("assistant_connection", "unverified-connection", None, "unverified_claim"),
        )

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

    def test_transaction_attention_operation_normalizes_actors_and_records_reason(self) -> None:
        """Every Intake caller identity maps to AUDIT-001 and retains its reason."""
        engine = create_sqlite_engine(self.database)
        actors = (
            ("local_operator", None, "local_operator"),
            ("assistant_connection", "connection-42", "ai_assistant"),
            ("system", None, "system"),
        )
        for actor_kind, actor_reference, audit_actor in actors:
            source = self.service.admit(self.command())
            transition = AttentionTransition(
                source_id=source["sourceId"], target="in_review",
                reason="review was admitted", idempotency_key=str(uuid4()),
                expected_revision=source["revision"], expected_status="unprocessed",
                correlation_id=str(uuid4()), actor_kind=actor_kind,
                actor_reference=actor_reference,
            )
            with immediate_transaction(engine) as connection:
                result = self.attention_operations.transition_attention(connection, transition)

            self.assertEqual("in_review", result["attentionStatus"])
            with sqlite3.connect(self.database) as connection:
                operation = connection.execute(
                    "SELECT actor_kind FROM intake_source_operations WHERE idempotency_key = ?",
                    (transition.idempotency_key,),
                ).fetchone()
                audit = connection.execute(
                    "SELECT actor_kind, actor_reference, reason FROM audit_events "
                    "WHERE entity_type = 'intake_source' AND entity_id = ? "
                    "AND action = 'attention_changed' AND correlation_id = ?",
                    (source["sourceId"], transition.correlation_id),
                ).fetchone()
            self.assertEqual((audit_actor,), operation)
            self.assertEqual((audit_actor, actor_reference, "review was admitted"), audit)
        self.assertEqual("[redacted]", INTAKE_ACTIVITY_POLICY.redact_reason("review was admitted"))
        validate_latest_schema(self.database)

    def test_transaction_attention_replay_returns_original_result_and_rollback_leaves_no_history(self) -> None:
        engine = create_sqlite_engine(self.database)
        source = self.service.admit(self.command())
        first = AttentionTransition(
            source_id=source["sourceId"], target="in_review", reason="review admitted",
            idempotency_key=str(uuid4()), expected_revision=source["revision"],
            expected_status="unprocessed", correlation_id=str(uuid4()),
        )
        with immediate_transaction(engine) as connection:
            original = self.attention_operations.transition_attention(connection, first)
        second = AttentionTransition(
            source_id=source["sourceId"], target="dismissed", reason="not actionable",
            idempotency_key=str(uuid4()), expected_revision=source["revision"],
            expected_status="in_review", correlation_id=str(uuid4()),
        )
        with immediate_transaction(engine) as connection:
            self.attention_operations.transition_attention(connection, second)
        with immediate_transaction(engine) as connection:
            replay = self.attention_operations.transition_attention(connection, first)
        self.assertEqual(original, replay)
        self.assertEqual("in_review", replay["attentionStatus"])

        rolled_back = self.service.admit(self.command())
        aborted = AttentionTransition(
            source_id=rolled_back["sourceId"], target="in_review", reason="must not persist",
            idempotency_key=str(uuid4()), expected_revision=rolled_back["revision"],
            expected_status="unprocessed", correlation_id=str(uuid4()),
        )
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with immediate_transaction(engine) as connection:
                self.attention_operations.transition_attention(connection, aborted)
                raise RuntimeError("rollback")
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(0, connection.execute(
                "SELECT COUNT(*) FROM intake_source_operations WHERE idempotency_key = ?",
                (aborted.idempotency_key,),
            ).fetchone()[0])
            self.assertEqual(0, connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE correlation_id = ?",
                (aborted.correlation_id,),
            ).fetchone()[0])

    def test_attention_idempotency_binds_actor_and_activity_redacts_connection(self) -> None:
        engine = create_sqlite_engine(self.database)
        source = self.service.admit(self.command())
        key = str(uuid4())
        assistant = AttentionTransition(
            source_id=source["sourceId"], target="in_review", reason="assistant triage",
            idempotency_key=key, expected_revision=source["revision"],
            expected_status="unprocessed", correlation_id=str(uuid4()),
            actor_kind="assistant_connection", actor_reference="connection-42",
        )
        with immediate_transaction(engine) as connection:
            original = self.attention_operations.transition_attention(connection, assistant)
        with immediate_transaction(engine) as connection:
            self.assertEqual(original, self.attention_operations.transition_attention(connection, assistant))

        different_actor = AttentionTransition(
            source_id=source["sourceId"], target="in_review", reason="assistant triage",
            idempotency_key=key, expected_revision=source["revision"],
            expected_status="unprocessed", correlation_id=str(uuid4()),
            actor_kind="assistant_connection", actor_reference="connection-99",
        )
        with self.assertRaisesRegex(IntakeConflictError, "Idempotency key"):
            with immediate_transaction(engine) as connection:
                self.attention_operations.transition_attention(connection, different_actor)

        class ReadyRuntime:
            ready = True
            error = None

        policies = AuditSnapshotPolicyRegistry(
            {("intake_source", 1): DEFAULT_SNAPSHOT_POLICY},
            activity_policies={("intake_source", 1): INTAKE_ACTIVITY_POLICY},
        )
        app = FastAPI()
        app.include_router(build_audit_router(ReadyRuntime(), SQLiteAuditRepository(self.database), policies))
        activity = TestClient(app).get(
            "/api/audit/events", params={"correlation_id": assistant.correlation_id},
        ).json()["events"]
        event = next(item for item in activity if item["correlationId"] == assistant.correlation_id)
        self.assertEqual("ai_assistant", event["actorKind"])
        self.assertEqual("[redacted]", event["actorReference"])
        self.assertEqual("[redacted]", event["reason"])

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

    def test_retained_validation_recomputes_an_operation_fingerprint(self) -> None:
        command = self.command()
        self.service.admit(command)
        engine = create_sqlite_engine(self.database)
        with immediate_transaction(engine) as connection:
            connection.exec_driver_sql("DROP TRIGGER intake_source_operations_no_update")
            connection.exec_driver_sql(
                "UPDATE intake_source_operations SET request_fingerprint = ? WHERE idempotency_key = ?",
                ("0" * 64, command.idempotency_key),
            )
        with engine.connect() as connection:
            with self.assertRaises(MigrationSchemaError):
                validate_intake_data(connection)

    def test_operator_api_rejects_trusted_provenance_fields(self) -> None:
        class ReadyRuntime:
            ready = True
            can_write = True
            error = None

        app = FastAPI()
        app.include_router(build_router(self.service, ReadyRuntime()))
        response = TestClient(app).post("/api/intake/sources", json={
            "sourceKind": "operator_note", "channel": "internal", "body": "Operator evidence.",
            "occurredAtUtc": "2026-01-01T12:00:00Z", "originSystem": "manual",
            "idempotencyKey": str(uuid4()), "accountIdentityState": "transport_verified",
        })
        self.assertEqual(422, response.status_code)

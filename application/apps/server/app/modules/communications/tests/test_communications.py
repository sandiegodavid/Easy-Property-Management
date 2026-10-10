"""Focused COM-001 lifecycle and persistence regressions."""

from __future__ import annotations

import inspect
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.platform.testing_client import LocalApiClient as TestClient
from fastapi import FastAPI
from sqlalchemy import event, text

from app.bootstrap.api import create_app
from app.bootstrap.communication_context import SQLiteCommunicationContextOperations
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.communications.application.service import (
    CommunicationCommand,
    CommunicationConflictError,
    CommunicationChangedKeyError,
    CommunicationStaleRevisionError,
    CommunicationError,
    CommunicationService,
    FollowUpInput,
    LinkInput,
    ParticipantInput,
    PatchCommand,
    command_fingerprint,
)
from app.modules.communications.api.router import build_router
from app.modules.communications.infrastructure.receipt_reader import (
    SQLiteCommunicationReceiptReader,
)
from app.modules.communications.infrastructure.link_reader import SQLiteCommunicationLinkReader
from app.modules.communications.infrastructure.schema_validation import (
    OPERATION_TRIGGERS,
    validate_communication_schema,
)
from app.platform.migration_errors import MigrationSchemaError
from app.modules.communications.infrastructure.unit_of_work import SQLiteCommunicationUnitOfWork
from app.modules.intake.infrastructure.source_reader import SQLiteIntakeSourceReader
from app.modules.tasks.infrastructure.transaction_operations import SQLiteTaskTransactionOperations
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.config import LocalConfig
from app.platform.product_migrations import (
    ProductSchemaError,
    initialize_latest_schema,
    validate_latest_schema,
)
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

PARTY_ID = "11111111-1111-4111-8111-111111111111"


class CommunicationWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = Path(tempfile.mkdtemp()) / "workspace.sqlite"
        initialize_latest_schema(self.database)
        engine = create_sqlite_engine(self.database)
        with immediate_transaction(engine) as connection:
            connection.execute(
                text(
                    "INSERT INTO parties (id, party_kind, display_name, created_at, updated_at, archived_at) VALUES (:id, 'individual', 'Taylor', :now, :now, NULL)"
                ),
                {"id": PARTY_ID, "now": "2026-01-01T00:00:00+00:00"},
            )
        self.service = CommunicationService(
            SQLiteCommunicationUnitOfWork(
                self.database,
                AuditRecorder(SQLiteAuditRepository(self.database)),
                SQLiteCommunicationContextOperations(
                    SQLiteTaskTransactionOperations(),
                    SQLiteIntakeSourceReader(),
                ),
            )
        )

    def command(
        self,
        *,
        record: bool = False,
        subject: str = "Repair update",
        occurred_at: str = "2026-01-01T12:00:00+00:00",
        follow_up: FollowUpInput | None = None,
    ) -> CommunicationCommand:
        return CommunicationCommand(
            "inbound",
            "phone",
            subject,
            "The tenant called back.",
            occurred_at,
            "UTC",
            (ParticipantInput(PARTY_ID, "sender"),),
            follow_up=follow_up,
            record=record,
        )

    def test_draft_record_correction_and_idempotency_are_atomic(self) -> None:
        draft = self.service.create(self.command(), "22222222-2222-4222-8222-222222222222", 0)
        self.assertEqual("draft", draft["status"])
        recorded = self.service.record(draft["id"], None, "33333333-3333-4333-8333-333333333333", 1)
        self.assertEqual("recorded", recorded["status"])
        retry = self.service.record(draft["id"], None, "33333333-3333-4333-8333-333333333333", 1)
        self.assertEqual(recorded["id"], retry["id"])
        corrected = self.service.correct(
            draft["id"],
            self.command(record=True),
            "Corrected summary.",
            "44444444-4444-4444-8444-444444444444",
            2,
        )
        self.assertEqual(draft["id"], corrected["supersedesCommunicationId"])
        self.assertEqual(
            corrected["id"], self.service.get(draft["id"])["supersededByCommunicationId"]
        )
        with self.assertRaises(CommunicationConflictError):
            self.service.correct(
                draft["id"],
                self.command(record=True),
                "Again.",
                "55555555-5555-4555-8555-555555555555",
                2,
            )

    def test_every_command_replays_original_receipt_after_later_mutations(self) -> None:
        create_key, patch_key, record_key, correction_key = (str(uuid4()) for _ in range(4))
        draft = self.service.create(self.command(), create_key, 0)
        patched = self.service.patch(draft["id"], PatchCommand(subject="Updated"), patch_key, 1)
        recorded = self.service.record(draft["id"], None, record_key, 2)
        corrected = self.service.correct(
            draft["id"], self.command(record=True), "Fix", correction_key, 3
        )
        self.service.correct(corrected["id"], self.command(record=True), "Next", str(uuid4()), 1)
        for original, replay in (
            (draft, lambda: self.service.create(self.command(), create_key, 0)),
            (
                patched,
                lambda: self.service.patch(
                    draft["id"], PatchCommand(subject="Updated"), patch_key, 1
                ),
            ),
            (recorded, lambda: self.service.record(draft["id"], None, record_key, 2)),
            (
                corrected,
                lambda: self.service.correct(
                    draft["id"], self.command(record=True), "Fix", correction_key, 3
                ),
            ),
        ):
            with self.subTest(operation=original["operationId"]):
                self.assertEqual(original, replay())
                self.assertEqual(original, self.service.receipt(original["operationId"]))
        direct_key = str(uuid4())
        direct = self.service.create(self.command(record=True), direct_key, 0)
        self.service.correct(direct["id"], self.command(record=True), "Direct fix", str(uuid4()), 1)
        self.assertEqual(direct, self.service.create(self.command(record=True), direct_key, 0))
        with create_sqlite_engine(self.database).connect() as connection:
            validate_communication_schema(connection)

    def test_changed_key_precedes_stale_and_lifecycle_for_every_command(self) -> None:
        key = str(uuid4())
        draft = self.service.create(self.command(), key, 0)
        with self.assertRaises(CommunicationChangedKeyError):
            self.service.create(self.command(subject="Different"), key, 0)
        patch_key = str(uuid4())
        self.service.patch(draft["id"], PatchCommand(subject="Updated"), patch_key, 1)
        with self.assertRaises(CommunicationChangedKeyError):
            self.service.patch(draft["id"], PatchCommand(body="Different"), patch_key, 1)
        record_key = str(uuid4())
        self.service.record(draft["id"], None, record_key, 2)
        with self.assertRaises(CommunicationChangedKeyError):
            self.service.record(draft["id"], FollowUpInput("Different"), record_key, 2)
        correct_key = str(uuid4())
        self.service.correct(draft["id"], self.command(record=True), "Fix", correct_key, 3)
        with self.assertRaises(CommunicationChangedKeyError):
            self.service.correct(
                draft["id"], self.command(record=True), "Different", correct_key, 3
            )
        for attempt in (
            lambda: self.service.patch(draft["id"], PatchCommand(), str(uuid4()), 1),
            lambda: self.service.record(draft["id"], None, str(uuid4()), 1),
            lambda: self.service.correct(
                draft["id"], self.command(record=True), "Fix", str(uuid4()), 1
            ),
        ):
            with self.assertRaises(CommunicationStaleRevisionError) as error:
                attempt()
            self.assertEqual(4, error.exception.current_revision)

    def test_empty_and_unchanged_patch_have_durable_no_op_receipts(self) -> None:
        draft = self.service.create(self.command(), str(uuid4()), 0)
        engine = create_sqlite_engine(self.database)
        with engine.connect() as connection:
            audit_count = connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one()
        receipts = []
        for command in (
            PatchCommand(),
            PatchCommand(
                subject=draft["subject"],
                body=draft["body"],
                participants=(ParticipantInput(PARTY_ID, "sender"),),
                links=(),
            ),
        ):
            key = str(uuid4())
            result = self.service.patch(draft["id"], command, key, 1)
            receipts.append((command, key, result))
            self.assertEqual("no_op", result["outcome"])
            self.assertEqual(1, result["revision"])
            self.assertEqual(draft["updatedAt"], result["updatedAt"])
            self.assertEqual(result, self.service.patch(draft["id"], command, key, 1))
            self.assertEqual(result, self.service.receipt(result["operationId"]))
        with engine.connect() as connection:
            self.assertEqual(
                audit_count,
                connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one(),
            )
            validate_communication_schema(connection)
        self.service.record(draft["id"], None, str(uuid4()), 1)
        for command, key, result in receipts:
            self.assertEqual(result, self.service.patch(draft["id"], command, key, 1))
            self.assertEqual(result, self.service.receipt(result["operationId"]))
        with engine.connect() as connection:
            validate_communication_schema(connection)

    def test_application_metadata_is_required_and_strict(self) -> None:
        with self.assertRaises(TypeError):
            self.service.create(self.command(), str(uuid4()))
        for revision in (True, -1, "0", None):
            with self.subTest(revision=revision), self.assertRaises(CommunicationError):
                self.service.create(self.command(), str(uuid4()), revision)
        with self.assertRaises(CommunicationStaleRevisionError) as error:
            self.service.create(self.command(), str(uuid4()), 1)
        self.assertEqual(0, error.exception.current_revision)

    def test_public_fingerprint_and_recovery_reader_match_committed_contract(self) -> None:
        key = str(uuid4())
        command = self.command()
        result = self.service.create(command, key, 0)
        with create_sqlite_engine(self.database).connect() as connection:
            receipt = SQLiteCommunicationReceiptReader().receipt(connection, key)
        self.assertEqual(result["operationId"], receipt["id"])
        self.assertEqual(result["id"], receipt["result_communication_id"])
        self.assertEqual(result["revision"], receipt["result_revision"])
        self.assertEqual(result, json.loads(receipt["response_json"]))
        self.assertEqual(
            command_fingerprint("created", None, command, 0), receipt["request_fingerprint"]
        )
        self.assertNotEqual(
            command_fingerprint("created", None, command, 1), receipt["request_fingerprint"]
        )

    def test_shared_revision_tracks_participants_links_payload_and_lifecycle(self) -> None:
        draft = self.service.create(self.command(), str(uuid4()), 0)
        participant = self.service.patch(
            draft["id"],
            PatchCommand(participants=(ParticipantInput(PARTY_ID, "reporter"),)),
            str(uuid4()),
            1,
        )
        linked = self.service.patch(
            draft["id"], PatchCommand(links=(LinkInput("party", PARTY_ID),)), str(uuid4()), 2
        )
        payload = self.service.patch(
            draft["id"], PatchCommand(body="Updated body"), str(uuid4()), 3
        )
        recorded = self.service.record(draft["id"], None, str(uuid4()), 4)
        corrected = self.service.correct(
            draft["id"], self.command(record=True), "Fix", str(uuid4()), 5
        )
        self.assertEqual(
            [1, 2, 3, 4, 5],
            [item["revision"] for item in (draft, participant, linked, payload, recorded)],
        )
        self.assertEqual(6, self.service.get(draft["id"])["revision"])
        self.assertEqual(1, corrected["revision"])
        with create_sqlite_engine(self.database).connect() as connection:
            validate_communication_schema(connection)

    def test_replay_and_receipt_lookup_use_one_select_without_detail_queries(self) -> None:
        key = str(uuid4())
        created = self.service.create(self.command(), key, 0)
        statements = []
        engine = self.service.unit_of_work.engine

        def capture(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement.strip().split()[0].upper())

        event.listen(engine, "before_cursor_execute", capture)
        try:
            self.assertEqual(created, self.service.create(self.command(), key, 0))
            self.assertEqual(1, statements.count("SELECT"))
            self.assertFalse({"INSERT", "UPDATE", "DELETE"} & set(statements))
            statements.clear()
            self.assertEqual(created, self.service.receipt(created["operationId"]))
            self.assertEqual(1, statements.count("SELECT"))
            self.assertFalse({"INSERT", "UPDATE", "DELETE"} & set(statements))
        finally:
            event.remove(engine, "before_cursor_execute", capture)

    def test_http_receipts_replay_stale_conflicts_and_required_openapi_metadata(self) -> None:
        app = FastAPI()
        app.include_router(
            build_router(self.service, SimpleNamespace(ready=True, error=None, can_write=True))
        )
        with TestClient(app) as client:
            payload = {
                "direction": "inbound",
                "channel": "phone",
                "subject": "Called",
                "body": "Details",
                "occurredAtUtc": "2026-01-01T12:00:00Z",
                "occurredTimezone": "UTC",
                "participants": [{"partyId": PARTY_ID, "role": "sender"}],
                "idempotencyKey": str(uuid4()),
                "expectedRevision": 0,
            }
            for field in ("idempotencyKey", "expectedRevision"):
                incomplete = {key: value for key, value in payload.items() if key != field}
                self.assertEqual(
                    422, client.post("/api/communications", json=incomplete).status_code
                )
            created = client.post("/api/communications", json=payload)
            self.assertEqual(200, created.status_code, created.text)
            original = created.json()
            target = f"/api/communications/{original['id']}"
            patched = client.patch(
                target,
                json={"subject": "Later", "idempotencyKey": str(uuid4()), "expectedRevision": 1},
            )
            self.assertEqual(200, patched.status_code, patched.text)
            self.assertEqual(2, patched.json()["revision"])
            replay = client.post("/api/communications", json=payload)
            self.assertEqual(original, replay.json())
            self.assertEqual(
                original,
                client.get(f"/api/communications/operations/{original['operationId']}").json(),
            )
            self.assertEqual("Later", client.get(target).json()["subject"])
            stale = client.post(
                target + "/record", json={"idempotencyKey": str(uuid4()), "expectedRevision": 1}
            )
            self.assertEqual(409, stale.status_code)
            self.assertEqual("stale_revision", stale.json()["detail"]["code"])
            self.assertEqual(2, stale.json()["detail"]["currentRevision"])
            changed = client.post("/api/communications", json={**payload, "subject": "Different"})
            self.assertEqual(409, changed.status_code)
            self.assertEqual("idempotency_conflict", changed.json()["detail"]["code"])
            noop = client.patch(
                target, json={"idempotencyKey": str(uuid4()), "expectedRevision": 2}
            )
            self.assertEqual("no_op", noop.json()["outcome"])
            self.assertEqual(2, noop.json()["revision"])
            self.assertEqual(
                404, client.get(f"/api/communications/operations/{uuid4()}").status_code
            )
            schema = client.get("/openapi.json").json()
            for name in ("CommunicationInput", "PatchInput", "RecordInput", "CorrectionInput"):
                self.assertTrue(
                    {"idempotencyKey", "expectedRevision"}
                    <= set(schema["components"]["schemas"][name]["required"])
                )
            receipt_schema = schema["components"]["schemas"]["CommunicationReceiptResponse"]
            self.assertTrue(
                {"operationId", "revision", "outcome"} <= set(receipt_schema["required"])
            )
            route = schema["paths"]["/api/communications/operations/{operation_id}"]["get"]
            self.assertEqual(
                "#/components/schemas/CommunicationReceiptResponse",
                route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
            )
            self.assertIn(
                "409",
                schema["paths"]["/api/communications/{communication_id}"]["patch"]["responses"],
            )

    def test_retained_validator_rejects_receipt_and_canonical_payload_tampering(self) -> None:
        created = self.service.create(self.command(), str(uuid4()), 0)
        noop = self.service.patch(created["id"], PatchCommand(), str(uuid4()), 1)
        engine = create_sqlite_engine(self.database)

        class Rollback(Exception):
            pass

        for operation_id, mutation in (
            (created["operationId"], "response"),
            (noop["operationId"], "response"),
            (created["operationId"], "fingerprint"),
            (created["operationId"], "canonical"),
            (created["operationId"], "payload"),
        ):
            with (
                self.subTest(mutation=mutation, operation_id=operation_id),
                self.assertRaises(Rollback),
            ):
                with immediate_transaction(engine) as connection:
                    connection.execute(text("DROP TRIGGER communication_operations_no_update"))
                    row = (
                        connection.execute(
                            text("SELECT * FROM communication_operations WHERE id = :id"),
                            {"id": operation_id},
                        )
                        .mappings()
                        .one()
                    )
                    if mutation == "response":
                        value = json.loads(row["response_json"])
                        value["subject"] = "Rewritten receipt"
                        updates = {
                            "response_json": json.dumps(
                                value, sort_keys=True, separators=(",", ":")
                            )
                        }
                    elif mutation == "fingerprint":
                        updates = {"request_fingerprint": "0" * 64}
                    elif mutation == "canonical":
                        updates = {
                            "request_json": json.dumps(json.loads(row["request_json"])),
                            "request_fingerprint": hashlib.sha256(
                                json.dumps(json.loads(row["request_json"])).encode()
                            ).hexdigest(),
                        }
                    else:
                        value = json.loads(row["request_json"])
                        value["value"]["body"] = "Different request"
                        request = json.dumps(value, sort_keys=True, separators=(",", ":"))
                        updates = {
                            "request_json": request,
                            "request_fingerprint": hashlib.sha256(request.encode()).hexdigest(),
                        }
                    assignments = ", ".join(f"{name} = :{name}" for name in updates)
                    connection.execute(
                        text(f"UPDATE communication_operations SET {assignments} WHERE id = :id"),
                        {**updates, "id": operation_id},
                    )
                    connection.execute(
                        text(OPERATION_TRIGGERS["communication_operations_no_update"])
                    )
                    with self.assertRaises(MigrationSchemaError):
                        validate_communication_schema(connection)
                    raise Rollback()
        with engine.connect() as connection:
            validate_communication_schema(connection)
        for sql in (
            "UPDATE communication_operations SET response_json = '{}' WHERE id = :id",
            "DELETE FROM communication_operations WHERE id = :id",
            "INSERT OR REPLACE INTO communication_operations SELECT * FROM communication_operations WHERE id = :id",
        ):
            with self.assertRaises(Exception):
                with immediate_transaction(engine) as connection:
                    connection.execute(text(sql), {"id": created["operationId"]})
        with self.assertRaises(Exception):
            with immediate_transaction(engine) as connection:
                columns = list(
                    connection.execute(
                        text("SELECT * FROM communication_operations WHERE id = :id"),
                        {"id": created["operationId"]},
                    )
                    .mappings()
                    .one()
                    .keys()
                )
                values = ", ".join(":new_id" if column == "id" else column for column in columns)
                connection.execute(
                    text(
                        f"INSERT OR REPLACE INTO communication_operations SELECT {values} FROM communication_operations WHERE id = :id"
                    ),
                    {"id": created["operationId"], "new_id": str(uuid4())},
                )

    def test_follow_up_failure_rolls_back_all_commands_and_allows_retry(self) -> None:
        class FailingContext(SQLiteCommunicationContextOperations):
            def create_follow_up(self, connection, **kwargs):
                super().create_follow_up(connection, **kwargs)
                raise RuntimeError("follow-up failed after insert")

        failed = CommunicationService(
            SQLiteCommunicationUnitOfWork(
                self.database,
                AuditRecorder(SQLiteAuditRepository(self.database)),
                FailingContext(SQLiteTaskTransactionOperations(), SQLiteIntakeSourceReader()),
            )
        )
        draft = self.service.create(self.command(), str(uuid4()), 0)
        recorded = self.service.create(self.command(record=True), str(uuid4()), 0)
        attempts = (
            lambda service, key: service.create(
                self.command(record=True, follow_up=FollowUpInput("Call")), key, 0
            ),
            lambda service, key: service.record(draft["id"], FollowUpInput("Call"), key, 1),
            lambda service, key: service.correct(
                recorded["id"],
                self.command(record=True, follow_up=FollowUpInput("Call")),
                "Fix",
                key,
                1,
            ),
        )
        engine = create_sqlite_engine(self.database)
        for attempt in attempts:
            with engine.connect() as connection:
                before = [
                    connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                    for table in (
                        "communications",
                        "communication_operations",
                        "tasks",
                        "audit_events",
                    )
                ]
            key = str(uuid4())
            with self.assertRaises(RuntimeError):
                attempt(failed, key)
            with engine.connect() as connection:
                after = [
                    connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                    for table in (
                        "communications",
                        "communication_operations",
                        "tasks",
                        "audit_events",
                    )
                ]
            self.assertEqual(before, after)
            result = attempt(self.service, key)
            self.assertEqual(result, attempt(self.service, key))

    def test_requires_active_party_and_current_schema_data_is_validated(self) -> None:
        with self.assertRaises(CommunicationError):
            self.service.create(self.command(), "not-a-uuid", 0)
        created = self.service.create(self.command(), "66666666-6666-4666-8666-666666666666", 0)
        validate_latest_schema(self.database)
        engine = create_sqlite_engine(self.database)
        with immediate_transaction(engine) as connection:
            connection.execute(
                text("UPDATE communications SET occurred_timezone = 'Not/AZone' WHERE id = :id"),
                {"id": created["id"]},
            )
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.database)

    def test_record_revalidates_draft_participants_without_publishing_history(self) -> None:
        draft = self.service.create(self.command(), "12121212-1212-4212-8212-121212121212", 0)
        engine = create_sqlite_engine(self.database)
        with immediate_transaction(engine) as connection:
            connection.execute(
                text("UPDATE parties SET archived_at = :now WHERE id = :id"),
                {
                    "id": PARTY_ID,
                    "now": "2026-01-02T00:00:00+00:00",
                },
            )
        with self.assertRaises(ValueError):
            self.service.record(draft["id"], None, "13131313-1313-4313-8313-131313131313", 1)
        self.assertEqual("draft", self.service.get(draft["id"])["status"])

    def test_recorded_correction_requires_a_reason_in_persisted_schema(self) -> None:
        created = self.service.create(
            self.command(record=True), "14141414-1414-4414-8414-141414141414", 0
        )
        engine = create_sqlite_engine(self.database)
        with self.assertRaises(Exception):
            with immediate_transaction(engine) as connection:
                connection.execute(
                    text(
                        "UPDATE communications SET supersedes_communication_id = :id, correction_reason = NULL WHERE id = :id"
                    ),
                    {"id": created["id"]},
                )

    def test_activity_hides_follow_up_task_identity_but_context_retains_it(self) -> None:
        result = self.service.create(
            self.command(record=True, follow_up=FollowUpInput("Call back")),
            "15151515-1515-4515-8515-151515151515",
            0,
        )
        events = SQLiteAuditRepository(self.database).history(entity_type="task")
        self.assertEqual(1, len(events))
        from app.modules.tasks.domain.audit_policy import TASK_ACTIVITY_POLICY

        activity = events[0].to_dict(TASK_ACTIVITY_POLICY)
        self.assertEqual("[redacted]", activity["entityId"])
        self.assertEqual("[redacted]", activity["after"]["id"])
        self.assertEqual(result["followUpTasks"][0]["id"], events[0].entity_id)

    def test_schema_rejects_orphaned_communication_follow_up_task(self) -> None:
        created = self.service.create(
            self.command(record=True, follow_up=FollowUpInput("Call back")),
            "16161616-1616-4616-8616-161616161616",
            0,
        )
        engine = create_sqlite_engine(self.database)
        with immediate_transaction(engine) as connection:
            connection.execute(
                text("UPDATE tasks SET related_entity_id = :missing WHERE id = :id"),
                {
                    "missing": "17171717-1717-4717-8717-171717171717",
                    "id": created["followUpTasks"][0]["id"],
                },
            )
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.database)

    def test_operation_idempotency_records_are_append_only(self) -> None:
        self.service.create(self.command(), "23232323-2323-4232-8232-232323232323", 0)
        engine = create_sqlite_engine(self.database)
        with self.assertRaises(Exception):
            with immediate_transaction(engine) as connection:
                connection.execute(text("DELETE FROM communication_operations"))

    def test_schema_rejects_follow_up_when_both_correlated_audits_are_missing(self) -> None:
        created = self.service.create(
            self.command(record=True, follow_up=FollowUpInput("Call back")),
            "24242424-2424-4242-8242-242424242424",
            0,
        )
        task_id = created["followUpTasks"][0]["id"]
        task_event = SQLiteAuditRepository(self.database).history(
            entity_type="task", entity_id=task_id
        )[0]
        engine = create_sqlite_engine(self.database)
        with immediate_transaction(engine) as connection:
            connection.execute(text("DROP TRIGGER audit_events_no_delete"))
            connection.execute(
                text(
                    "DELETE FROM audit_events WHERE entity_type = 'task' AND entity_id = :task_id"
                ),
                {"task_id": task_id},
            )
            connection.execute(
                text(
                    "DELETE FROM audit_events WHERE entity_type = 'communication' AND entity_id = :id AND action = 'follow_up_created' AND correlation_id = :correlation"
                ),
                {
                    "id": created["id"],
                    "correlation": task_event.correlation_id,
                },
            )
            connection.execute(
                text(
                    "CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"
                )
            )
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.database)

    def test_schema_rejects_missing_record_operation(self) -> None:
        draft = self.service.create(self.command(), "25252525-2525-4252-8252-252525252525", 0)
        self.service.record(draft["id"], None, "26262626-2626-4262-8262-262626262626", 1)
        self._delete_operation("recorded")
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.database)

    def test_schema_rejects_missing_patch_operation(self) -> None:
        draft = self.service.create(self.command(), "27272727-2727-4272-8272-272727272727", 0)
        self.service.patch(
            draft["id"], PatchCommand(subject="Updated"), "28282828-2828-4282-8282-282828282828", 1
        )
        self._delete_operation("patched")
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.database)

    def _delete_operation(self, action: str) -> None:
        engine = create_sqlite_engine(self.database)
        with immediate_transaction(engine) as connection:
            connection.execute(text("DROP TRIGGER communication_operations_no_delete"))
            connection.execute(
                text("DELETE FROM communication_operations WHERE action = :action"),
                {"action": action},
            )
            connection.execute(
                text(
                    "CREATE TRIGGER communication_operations_no_delete BEFORE DELETE ON communication_operations BEGIN SELECT RAISE(ABORT, 'communication operations are immutable'); END"
                )
            )

    def test_cursor_local_date_and_linked_task_status_filters(self) -> None:
        first = self.service.create(
            self.command(record=True, subject="First", occurred_at="2026-01-01T23:30:00+00:00"),
            "88888888-8888-4888-8888-888888888888",
            0,
        )
        second = self.service.create(
            self.command(
                record=True,
                subject="Second",
                occurred_at="2026-01-02T00:30:00+00:00",
                follow_up=FollowUpInput("Call back"),
            ),
            "99999999-9999-4999-8999-999999999999",
            0,
        )
        page, cursor = self.service.list(limit=1)
        self.assertEqual(second["id"], page[0]["id"])
        self.assertIsNotNone(cursor)
        following, after = self.service.list(limit=1, cursor=cursor)
        self.assertEqual(first["id"], following[0]["id"])
        self.assertIsNone(after)
        filtered, _ = self.service.list(
            occurred_on_or_after="2026-01-02",
            occurred_on_or_before="2026-01-02",
            linked_task_status="open",
        )
        self.assertEqual([second["id"]], [item["id"] for item in filtered])

    def test_link_summaries_apply_per_entity_limit_in_one_set_based_query(self) -> None:
        first = self.service.create(
            self.command(record=True, subject="First", occurred_at="2026-01-01T12:00:00+00:00"),
            "10101010-2020-4020-8020-202020202020",
            0,
        )
        second = self.service.create(
            self.command(record=True, subject="Second", occurred_at="2026-01-02T12:00:00+00:00"),
            "11111110-2020-4020-8020-202020202020",
            0,
        )
        third = self.service.create(
            self.command(record=True, subject="Third", occurred_at="2026-01-03T12:00:00+00:00"),
            "12121210-2020-4020-8020-202020202020",
            0,
        )
        issue_one, issue_two = (
            "21111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
        )
        engine = create_sqlite_engine(self.database)
        try:
            with immediate_transaction(engine) as connection:
                for index, (communication_id, issue_id) in enumerate(
                    (
                        (first["id"], issue_one),
                        (second["id"], issue_one),
                        (third["id"], issue_one),
                        (first["id"], issue_two),
                    )
                ):
                    connection.execute(
                        text(
                            "INSERT INTO communication_links (id, communication_id, entity_type, entity_id, property_timezone_snapshot) "
                            "VALUES (:id, :communication_id, 'maintenance_issue', :entity_id, 'UTC')"
                        ),
                        {
                            "id": f"30000000-0000-4000-8000-{index:012d}",
                            "communication_id": communication_id,
                            "entity_id": issue_id,
                        },
                    )
            statements = []

            def capture(*args):
                if args[2].lstrip().upper().startswith("SELECT"):
                    statements.append(args[2])

            event.listen(engine, "before_cursor_execute", capture)
            try:
                with engine.connect() as connection:
                    result = SQLiteCommunicationLinkReader().summaries_for_entities(
                        connection,
                        "maintenance_issue",
                        {issue_one, issue_two},
                        limit_per_entity=2,
                    )
                self.assertEqual(["Third", "Second"], [row["subject"] for row in result[issue_one]])
                self.assertEqual(["First"], [row["subject"] for row in result[issue_two]])
                self.assertEqual(1, len(statements))
            finally:
                event.remove(engine, "before_cursor_execute", capture)
        finally:
            engine.dispose()

    def test_local_date_filter_advances_through_bounded_database_chunks(self) -> None:
        import app.modules.communications.infrastructure.unit_of_work as adapter

        original_chunk = adapter.LIST_SCAN_CHUNK
        adapter.LIST_SCAN_CHUNK = 2
        try:
            for index, day in enumerate(("04", "03", "02", "01"), start=20):
                self.service.create(
                    self.command(
                        record=True,
                        subject=f"Day {day}",
                        occurred_at=f"2026-01-{day}T12:00:00+00:00",
                    ),
                    f"{index:08d}-2020-4020-8020-202020202020",
                    0,
                )
            page, cursor = self.service.list(
                occurred_on_or_after="2026-01-01",
                occurred_on_or_before="2026-01-01",
            )
            self.assertEqual(["Day 01"], [item["subject"] for item in page])
            self.assertIsNone(cursor)
        finally:
            adapter.LIST_SCAN_CHUNK = original_chunk

    def test_selective_filter_returns_a_continuation_after_scan_budget(self) -> None:
        import app.modules.communications.infrastructure.unit_of_work as adapter

        original_chunk, original_maximum = adapter.LIST_SCAN_CHUNK, adapter.MAX_LIST_CANDIDATES
        adapter.LIST_SCAN_CHUNK, adapter.MAX_LIST_CANDIDATES = 2, 2
        try:
            for index, day in enumerate(("03", "02", "01"), start=30):
                self.service.create(
                    self.command(
                        record=True,
                        subject=f"Budget {day}",
                        occurred_at=f"2026-01-{day}T12:00:00+00:00",
                    ),
                    f"{index:08d}-3030-4030-8030-303030303030",
                    0,
                )
            first, cursor = self.service.list(
                occurred_on_or_after="2026-01-01",
                occurred_on_or_before="2026-01-01",
            )
            self.assertEqual([], first)
            self.assertIsNotNone(cursor)
            second, next_cursor = self.service.list(
                occurred_on_or_after="2026-01-01",
                occurred_on_or_before="2026-01-01",
                cursor=cursor,
            )
            self.assertEqual(["Budget 01"], [item["subject"] for item in second])
            self.assertIsNone(next_cursor)
        finally:
            adapter.LIST_SCAN_CHUNK, adapter.MAX_LIST_CANDIDATES = original_chunk, original_maximum

    def test_draft_property_link_refreshes_its_timezone_snapshot(self) -> None:
        property_id = "20202020-2020-4020-8020-202020202020"
        engine = create_sqlite_engine(self.database)
        with immediate_transaction(engine) as connection:
            connection.execute(
                text("""
                INSERT INTO properties (
                    id, display_name, address_line_1, address_line_2, city, region, postal_code,
                    country_code, time_zone, notes, status, created_at, updated_at, archived_at,
                    property_type, inventory_layout, property_revision
                ) VALUES (
                    :id, 'Home', '1 Main', NULL, 'Austin', 'TX', '78701', 'US', 'America/Chicago',
                    NULL, 'active', :now, :now, NULL, 'single_family_home', 'single_space', 1
                )
            """),
                {"id": property_id, "now": "2026-01-01T00:00:00+00:00"},
            )
        created = self.service.create(
            CommunicationCommand(
                "inbound",
                "phone",
                "Property update",
                "Discussed the move.",
                "2026-01-01T12:00:00+00:00",
                "America/Chicago",
                (ParticipantInput(PARTY_ID, "sender"),),
                (LinkInput("property", property_id),),
                record=False,
            ),
            "21212121-2121-4121-8121-212121212121",
            0,
        )
        with immediate_transaction(engine) as connection:
            connection.execute(
                text("UPDATE properties SET time_zone = 'America/New_York' WHERE id = :id"),
                {"id": property_id},
            )
        updated = self.service.patch(
            created["id"],
            PatchCommand(occurred_timezone="America/New_York"),
            "22222222-2222-4222-8222-222222222223",
            1,
        )
        self.assertEqual("America/New_York", updated["links"][0]["propertyTimezoneSnapshot"])
        with engine.connect() as connection:
            validate_communication_schema(
                connection,
                SQLiteCommunicationContextOperations(
                    SQLiteTaskTransactionOperations(),
                    SQLiteIntakeSourceReader(),
                ),
            )

    def test_follow_up_and_audit_failure_roll_back_one_transaction(self) -> None:
        class FailingRecorder:
            def record_change(self, *args, **kwargs):
                raise RuntimeError("audit unavailable")

        failed = CommunicationService(
            SQLiteCommunicationUnitOfWork(
                self.database,
                FailingRecorder(),
                SQLiteCommunicationContextOperations(
                    SQLiteTaskTransactionOperations(),
                    SQLiteIntakeSourceReader(),
                ),
            )
        )
        with self.assertRaises(RuntimeError):
            failed.create(
                self.command(record=True, follow_up=FollowUpInput("Call back")),
                "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                0,
            )
        self.assertEqual([], self.service.list()[0])
        result = self.service.create(
            self.command(record=True, follow_up=FollowUpInput("Call back")),
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            0,
        )
        self.assertEqual(1, len(result["followUpTasks"]))

    @fast_backup_encryption()
    def test_communication_dataset_survives_encrypted_backup_and_restore(self) -> None:
        root = Path(tempfile.mkdtemp())
        workspace = WorkspaceService(
            LocalConfig(
                root / "config.json", root / "workspace", backup_destination_path=root / "backups"
            )
        )
        workspace.initialize()
        engine = create_sqlite_engine(workspace.paths.database)
        with immediate_transaction(engine) as connection:
            connection.execute(
                text(
                    "INSERT INTO parties (id, party_kind, display_name, created_at, updated_at, archived_at) VALUES (:id, 'individual', 'Taylor', :now, :now, NULL)"
                ),
                {"id": PARTY_ID, "now": "2026-01-01T00:00:00+00:00"},
            )
        recorder = AuditRecorder(SQLiteAuditRepository(workspace.paths.database))
        service = CommunicationService(
            SQLiteCommunicationUnitOfWork(
                workspace.paths.database,
                recorder,
                SQLiteCommunicationContextOperations(
                    SQLiteTaskTransactionOperations(),
                    SQLiteIntakeSourceReader(),
                ),
            )
        )
        created = service.create(
            self.command(record=True, follow_up=FollowUpInput("Call back")),
            "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            0,
        )
        service.correct(
            created["id"], self.command(record=True), "Direct correction", str(uuid4()), 1
        )
        create_key, patch_key, record_key, correction_key = (str(uuid4()) for _ in range(4))
        draft = service.create(self.command(), create_key, 0)
        patched = service.patch(draft["id"], PatchCommand(subject="Backup update"), patch_key, 1)
        recorded = service.record(draft["id"], FollowUpInput("Backup call"), record_key, 2)
        corrected = service.correct(
            draft["id"], self.command(record=True), "Backup correction", correction_key, 3
        )
        service.correct(
            corrected["id"], self.command(record=True), "Later correction", str(uuid4()), 1
        )
        backups = BackupService(
            workspace, recorder, lambda database: AuditRecorder(SQLiteAuditRepository(database))
        )
        archive = backups.create_backup("a long test backup passphrase")
        destination = root / "restored"
        backups.restore(archive.archive_path, "a long test backup passphrase", destination)
        restored = CommunicationService(
            SQLiteCommunicationUnitOfWork(
                destination / "database" / "property-management.sqlite",
                AuditRecorder(
                    SQLiteAuditRepository(destination / "database" / "property-management.sqlite")
                ),
                SQLiteCommunicationContextOperations(
                    SQLiteTaskTransactionOperations(),
                    SQLiteIntakeSourceReader(),
                ),
            )
        )
        view = restored.get(created["id"])
        self.assertEqual("superseded", view["status"])
        self.assertEqual(PARTY_ID, view["participants"][0]["partyId"])
        self.assertEqual(1, len(view["followUpTasks"]))
        for original, replay in (
            (
                created,
                lambda: restored.create(
                    self.command(record=True, follow_up=FollowUpInput("Call back")),
                    "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                    0,
                ),
            ),
            (draft, lambda: restored.create(self.command(), create_key, 0)),
            (
                patched,
                lambda: restored.patch(
                    draft["id"], PatchCommand(subject="Backup update"), patch_key, 1
                ),
            ),
            (
                recorded,
                lambda: restored.record(draft["id"], FollowUpInput("Backup call"), record_key, 2),
            ),
            (
                corrected,
                lambda: restored.correct(
                    draft["id"], self.command(record=True), "Backup correction", correction_key, 3
                ),
            ),
        ):
            with self.subTest(operation_id=original["operationId"]):
                self.assertEqual(original, restored.receipt(original["operationId"]))
                self.assertEqual(original, replay())
        validate_latest_schema(destination / "database" / "property-management.sqlite")

    def test_configured_http_contract_records_and_returns_a_communication(self) -> None:
        root = Path(tempfile.mkdtemp())
        config = root / "config.json"
        config.write_text(
            json.dumps({"localWorkspacePath": str(root / "workspace")}), encoding="utf-8"
        )
        with TestClient(create_app(config)) as client:
            self.assertEqual(201, client.post("/api/workspace/initialize").status_code)
            party = client.post(
                "/api/parties",
                json={
                    "partyKind": "individual",
                    "displayName": "Taylor",
                    "expectedRevision": 0,
                    "idempotencyKey": str(uuid4()),
                    "confirmedNewParty": True,
                },
            )
            self.assertEqual(201, party.status_code)
            response = client.post(
                "/api/communications",
                json={
                    "direction": "inbound",
                    "channel": "phone",
                    "subject": "Called",
                    "body": "Discussed repair.",
                    "occurredAtUtc": "2026-01-01T12:00:00Z",
                    "occurredTimezone": "UTC",
                    "record": True,
                    "participants": [{"partyId": party.json()["id"], "role": "sender"}],
                    "idempotencyKey": "77777777-7777-4777-8777-777777777777",
                    "expectedRevision": 0,
                },
            )
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual("recorded", response.json()["status"])
            self.assertEqual(
                422,
                client.patch(
                    f"/api/communications/{response.json()['id']}",
                    json={
                        "subject": None,
                        "idempotencyKey": "18181818-1818-4818-8818-181818181818",
                        "expectedRevision": 1,
                    },
                ).status_code,
            )
            self.assertEqual(
                422, client.get("/api/communications", params={"entityType": "party"}).status_code
            )
            correction = client.post(
                f"/api/communications/{response.json()['id']}/correct",
                json={
                    "direction": "inbound",
                    "channel": "phone",
                    "subject": "Corrected",
                    "body": "Corrected repair discussion.",
                    "occurredAtUtc": "2026-01-01T12:30:00Z",
                    "occurredTimezone": "UTC",
                    "participants": [{"partyId": party.json()["id"], "role": "sender"}],
                    "followUp": {"title": "Confirm repair"},
                    "correctionReason": "Clarified details.",
                    "idempotencyKey": "19191919-1919-4919-8919-191919191919",
                    "expectedRevision": 1,
                },
            )
            self.assertEqual(200, correction.status_code, correction.text)
            self.assertEqual(1, len(correction.json()["followUpTasks"]))
            self.assertEqual(2, len(client.get("/api/communications").json()["items"]))
            activity = client.get("/api/audit/events").json()["events"]
            communication_event = next(
                item for item in activity if item["entityType"] == "communication"
            )
            self.assertEqual("[redacted]", communication_event["after"]["subject"])
            history = client.get(f"/api/audit/events/communication/{response.json()['id']}").json()[
                "events"
            ]
            self.assertEqual("Called", history[0]["after"]["subject"])

    def test_application_layer_has_no_sqlalchemy_or_adapter_import(self) -> None:
        import app.modules.communications.application.service as service_module

        source = inspect.getsource(service_module)
        self.assertNotIn("sqlalchemy", source)
        self.assertNotIn("communications.infrastructure", source)

    def test_communications_sqlite_adapter_has_no_foreign_module_models(self) -> None:
        from app.modules.communications.infrastructure import unit_of_work

        source = inspect.getsource(unit_of_work)
        self.assertNotIn("modules.tasks.infrastructure", source)
        self.assertNotIn("modules.portfolio.infrastructure", source)

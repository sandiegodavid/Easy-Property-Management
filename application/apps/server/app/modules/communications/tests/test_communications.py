"""Focused COM-001 lifecycle and persistence regressions."""

from __future__ import annotations

import tempfile
import unittest
import json
import inspect
from pathlib import Path

from sqlalchemy import text

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.communications.application.service import (
    CommunicationCommand, CommunicationConflictError, CommunicationError, FollowUpInput,
    CommunicationService, LinkInput, ParticipantInput, PatchCommand,
)
from app.modules.communications.infrastructure.schema_validation import validate_communication_schema
from app.bootstrap.communication_context import SQLiteCommunicationContextOperations
from app.modules.communications.infrastructure.unit_of_work import SQLiteCommunicationUnitOfWork
from app.platform.product_migrations import ProductSchemaError, initialize_latest_schema, validate_latest_schema
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.application.backup_service import BackupService
from app.platform.config import LocalConfig
from app.bootstrap.api import create_app
from fastapi.testclient import TestClient

PARTY_ID = "11111111-1111-4111-8111-111111111111"


class CommunicationWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = Path(tempfile.mkdtemp()) / "workspace.sqlite"
        initialize_latest_schema(self.database)
        engine = create_sqlite_engine(self.database)
        with immediate_transaction(engine) as connection:
            connection.execute(text("INSERT INTO parties (id, party_kind, display_name, created_at, updated_at, archived_at) VALUES (:id, 'individual', 'Taylor', :now, :now, NULL)"), {"id": PARTY_ID, "now": "2026-01-01T00:00:00+00:00"})
        self.service = CommunicationService(SQLiteCommunicationUnitOfWork(self.database, AuditRecorder(SQLiteAuditRepository(self.database)), SQLiteCommunicationContextOperations()))

    def command(self, *, record: bool = False, subject: str = "Repair update", occurred_at: str = "2026-01-01T12:00:00+00:00", follow_up: FollowUpInput | None = None) -> CommunicationCommand:
        return CommunicationCommand("inbound", "phone", subject, "The tenant called back.", occurred_at, "UTC", (ParticipantInput(PARTY_ID, "sender"),), follow_up=follow_up, record=record)

    def test_draft_record_correction_and_idempotency_are_atomic(self) -> None:
        draft = self.service.create(self.command(), "22222222-2222-4222-8222-222222222222")
        self.assertEqual("draft", draft["status"])
        recorded = self.service.record(draft["id"], None, "33333333-3333-4333-8333-333333333333")
        self.assertEqual("recorded", recorded["status"])
        retry = self.service.record(draft["id"], None, "33333333-3333-4333-8333-333333333333")
        self.assertEqual(recorded["id"], retry["id"])
        corrected = self.service.correct(draft["id"], self.command(record=True), "Corrected summary.", "44444444-4444-4444-8444-444444444444")
        self.assertEqual(draft["id"], corrected["supersedesCommunicationId"])
        self.assertEqual(corrected["id"], self.service.get(draft["id"])["supersededByCommunicationId"])
        with self.assertRaises(CommunicationConflictError):
            self.service.correct(draft["id"], self.command(record=True), "Again.", "55555555-5555-4555-8555-555555555555")

    def test_requires_active_party_and_current_schema_data_is_validated(self) -> None:
        with self.assertRaises(CommunicationError):
            self.service.create(self.command(), "not-a-uuid")
        created = self.service.create(self.command(), "66666666-6666-4666-8666-666666666666")
        validate_latest_schema(self.database)
        engine = create_sqlite_engine(self.database)
        with immediate_transaction(engine) as connection:
            connection.execute(text("UPDATE communications SET occurred_timezone = 'Not/AZone' WHERE id = :id"), {"id": created["id"]})
        with self.assertRaises(ProductSchemaError): validate_latest_schema(self.database)

    def test_record_revalidates_draft_participants_without_publishing_history(self) -> None:
        draft = self.service.create(self.command(), "12121212-1212-4212-8212-121212121212")
        engine = create_sqlite_engine(self.database)
        with immediate_transaction(engine) as connection:
            connection.execute(text("UPDATE parties SET archived_at = :now WHERE id = :id"), {
                "id": PARTY_ID,
                "now": "2026-01-02T00:00:00+00:00",
            })
        with self.assertRaises(ValueError):
            self.service.record(draft["id"], None, "13131313-1313-4313-8313-131313131313")
        self.assertEqual("draft", self.service.get(draft["id"])["status"])

    def test_recorded_correction_requires_a_reason_in_persisted_schema(self) -> None:
        created = self.service.create(self.command(record=True), "14141414-1414-4414-8414-141414141414")
        engine = create_sqlite_engine(self.database)
        with self.assertRaises(Exception):
            with immediate_transaction(engine) as connection:
                connection.execute(text(
                    "UPDATE communications SET supersedes_communication_id = :id, correction_reason = NULL WHERE id = :id"
                ), {"id": created["id"]})

    def test_activity_hides_follow_up_task_identity_but_context_retains_it(self) -> None:
        result = self.service.create(self.command(record=True, follow_up=FollowUpInput("Call back")), "15151515-1515-4515-8515-151515151515")
        events = SQLiteAuditRepository(self.database).history(entity_type="task")
        self.assertEqual(1, len(events))
        from app.modules.tasks.domain.audit_policy import TASK_ACTIVITY_POLICY
        activity = events[0].to_dict(TASK_ACTIVITY_POLICY)
        self.assertEqual("[redacted]", activity["entityId"])
        self.assertEqual("[redacted]", activity["after"]["id"])
        self.assertEqual(result["followUpTasks"][0]["id"], events[0].entity_id)

    def test_schema_rejects_orphaned_communication_follow_up_task(self) -> None:
        created = self.service.create(self.command(record=True, follow_up=FollowUpInput("Call back")), "16161616-1616-4616-8616-161616161616")
        engine = create_sqlite_engine(self.database)
        with immediate_transaction(engine) as connection:
            connection.execute(text("UPDATE tasks SET related_entity_id = :missing WHERE id = :id"), {
                "missing": "17171717-1717-4717-8717-171717171717",
                "id": created["followUpTasks"][0]["id"],
            })
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.database)

    def test_operation_idempotency_records_are_append_only(self) -> None:
        self.service.create(self.command(), "23232323-2323-4232-8232-232323232323")
        engine = create_sqlite_engine(self.database)
        with self.assertRaises(Exception):
            with immediate_transaction(engine) as connection:
                connection.execute(text("DELETE FROM communication_operations"))

    def test_schema_rejects_follow_up_when_both_correlated_audits_are_missing(self) -> None:
        created = self.service.create(self.command(record=True, follow_up=FollowUpInput("Call back")), "24242424-2424-4242-8242-242424242424")
        task_id = created["followUpTasks"][0]["id"]
        task_event = SQLiteAuditRepository(self.database).history(entity_type="task", entity_id=task_id)[0]
        engine = create_sqlite_engine(self.database)
        with immediate_transaction(engine) as connection:
            connection.execute(text("DROP TRIGGER audit_events_no_delete"))
            connection.execute(text("DELETE FROM audit_events WHERE entity_type = 'task' AND entity_id = :task_id"), {"task_id": task_id})
            connection.execute(text("DELETE FROM audit_events WHERE entity_type = 'communication' AND entity_id = :id AND action = 'follow_up_created' AND correlation_id = :correlation"), {
                "id": created["id"], "correlation": task_event.correlation_id,
            })
            connection.execute(text("CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"))
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.database)

    def test_schema_rejects_missing_record_operation(self) -> None:
        draft = self.service.create(self.command(), "25252525-2525-4252-8252-252525252525")
        self.service.record(draft["id"], None, "26262626-2626-4262-8262-262626262626")
        self._delete_operation("recorded")
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.database)

    def test_schema_rejects_missing_patch_operation(self) -> None:
        draft = self.service.create(self.command(), "27272727-2727-4272-8272-272727272727")
        self.service.patch(draft["id"], PatchCommand(subject="Updated"), "28282828-2828-4282-8282-282828282828")
        self._delete_operation("patched")
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.database)

    def _delete_operation(self, action: str) -> None:
        engine = create_sqlite_engine(self.database)
        with immediate_transaction(engine) as connection:
            connection.execute(text("DROP TRIGGER communication_operations_no_delete"))
            connection.execute(text("DELETE FROM communication_operations WHERE action = :action"), {"action": action})
            connection.execute(text("CREATE TRIGGER communication_operations_no_delete BEFORE DELETE ON communication_operations BEGIN SELECT RAISE(ABORT, 'communication operations are immutable'); END"))

    def test_cursor_local_date_and_linked_task_status_filters(self) -> None:
        first = self.service.create(self.command(record=True, subject="First", occurred_at="2026-01-01T23:30:00+00:00"), "88888888-8888-4888-8888-888888888888")
        second = self.service.create(self.command(record=True, subject="Second", occurred_at="2026-01-02T00:30:00+00:00", follow_up=FollowUpInput("Call back")), "99999999-9999-4999-8999-999999999999")
        page, cursor = self.service.list(limit=1)
        self.assertEqual(second["id"], page[0]["id"])
        self.assertIsNotNone(cursor)
        following, after = self.service.list(limit=1, cursor=cursor)
        self.assertEqual(first["id"], following[0]["id"]); self.assertIsNone(after)
        filtered, _ = self.service.list(occurred_on_or_after="2026-01-02", occurred_on_or_before="2026-01-02", linked_task_status="open")
        self.assertEqual([second["id"]], [item["id"] for item in filtered])

    def test_local_date_filter_advances_through_bounded_database_chunks(self) -> None:
        import app.modules.communications.infrastructure.unit_of_work as adapter
        original_chunk = adapter.LIST_SCAN_CHUNK
        adapter.LIST_SCAN_CHUNK = 2
        try:
            for index, day in enumerate(("04", "03", "02", "01"), start=20):
                self.service.create(
                    self.command(record=True, subject=f"Day {day}", occurred_at=f"2026-01-{day}T12:00:00+00:00"),
                    f"{index:08d}-2020-4020-8020-202020202020",
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
                    self.command(record=True, subject=f"Budget {day}", occurred_at=f"2026-01-{day}T12:00:00+00:00"),
                    f"{index:08d}-3030-4030-8030-303030303030",
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
            connection.execute(text("""
                INSERT INTO properties (id, display_name, address_line_1, address_line_2, city, region,
                postal_code, country_code, time_zone, notes, status, created_at, updated_at, archived_at,
                property_type, inventory_layout)
                VALUES (:id, 'Home', '1 Main', NULL, 'Austin', 'TX', '78701', 'US', 'America/Chicago',
                NULL, 'active', :now, :now, NULL, 'single_family_home', 'single_space')
            """), {"id": property_id, "now": "2026-01-01T00:00:00+00:00"})
        created = self.service.create(CommunicationCommand(
            "inbound", "phone", "Property update", "Discussed the move.", "2026-01-01T12:00:00+00:00",
            "America/Chicago", (ParticipantInput(PARTY_ID, "sender"),),
            (LinkInput("property", property_id),), record=False,
        ), "21212121-2121-4121-8121-212121212121")
        with immediate_transaction(engine) as connection:
            connection.execute(text("UPDATE properties SET time_zone = 'America/New_York' WHERE id = :id"), {"id": property_id})
        updated = self.service.patch(created["id"], PatchCommand(occurred_timezone="America/New_York"), "22222222-2222-4222-8222-222222222223")
        self.assertEqual("America/New_York", updated["links"][0]["propertyTimezoneSnapshot"])
        with engine.connect() as connection:
            validate_communication_schema(connection, SQLiteCommunicationContextOperations())

    def test_follow_up_and_audit_failure_roll_back_one_transaction(self) -> None:
        class FailingRecorder:
            def record_change(self, *args, **kwargs): raise RuntimeError("audit unavailable")
        failed = CommunicationService(SQLiteCommunicationUnitOfWork(self.database, FailingRecorder(), SQLiteCommunicationContextOperations()))
        with self.assertRaises(RuntimeError):
            failed.create(self.command(record=True, follow_up=FollowUpInput("Call back")), "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        self.assertEqual([], self.service.list()[0])
        result = self.service.create(self.command(record=True, follow_up=FollowUpInput("Call back")), "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
        self.assertEqual(1, len(result["followUpTasks"]))

    def test_communication_dataset_survives_encrypted_backup_and_restore(self) -> None:
        root = Path(tempfile.mkdtemp()); workspace = WorkspaceService(LocalConfig(root / "config.json", root / "workspace", backup_destination_path=root / "backups")); workspace.initialize()
        engine = create_sqlite_engine(workspace.paths.database)
        with immediate_transaction(engine) as connection:
            connection.execute(text("INSERT INTO parties (id, party_kind, display_name, created_at, updated_at, archived_at) VALUES (:id, 'individual', 'Taylor', :now, :now, NULL)"), {"id": PARTY_ID, "now": "2026-01-01T00:00:00+00:00"})
        recorder = AuditRecorder(SQLiteAuditRepository(workspace.paths.database))
        service = CommunicationService(SQLiteCommunicationUnitOfWork(workspace.paths.database, recorder, SQLiteCommunicationContextOperations()))
        created = service.create(self.command(record=True, follow_up=FollowUpInput("Call back")), "cccccccc-cccc-4ccc-8ccc-cccccccccccc")
        backups = BackupService(workspace, recorder, lambda database: AuditRecorder(SQLiteAuditRepository(database)))
        archive = backups.create_backup("a long test backup passphrase")
        destination = root / "restored"; backups.restore(archive.archive_path, "a long test backup passphrase", destination)
        restored = CommunicationService(SQLiteCommunicationUnitOfWork(destination / "database" / "property-management.sqlite", AuditRecorder(SQLiteAuditRepository(destination / "database" / "property-management.sqlite")), SQLiteCommunicationContextOperations()))
        view = restored.get(created["id"])
        self.assertEqual("recorded", view["status"]); self.assertEqual(PARTY_ID, view["participants"][0]["partyId"]); self.assertEqual(1, len(view["followUpTasks"]))

    def test_configured_http_contract_records_and_returns_a_communication(self) -> None:
        root = Path(tempfile.mkdtemp()); config = root / "config.json"
        config.write_text(json.dumps({"localWorkspacePath": str(root / "workspace")}), encoding="utf-8")
        with TestClient(create_app(config)) as client:
            self.assertEqual(201, client.post("/api/workspace/initialize").status_code)
            party = client.post("/api/parties", json={"partyKind": "individual", "displayName": "Taylor", "confirmedNewParty": True})
            self.assertEqual(201, party.status_code)
            response = client.post("/api/communications", json={
                "direction": "inbound", "channel": "phone", "subject": "Called", "body": "Discussed repair.",
                "occurredAtUtc": "2026-01-01T12:00:00Z", "occurredTimezone": "UTC", "record": True,
                "participants": [{"partyId": party.json()["id"], "role": "sender"}], "idempotencyKey": "77777777-7777-4777-8777-777777777777",
            })
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual("recorded", response.json()["status"])
            self.assertEqual(422, client.patch(
                f"/api/communications/{response.json()['id']}",
                json={"subject": None, "idempotencyKey": "18181818-1818-4818-8818-181818181818"},
            ).status_code)
            self.assertEqual(422, client.get("/api/communications", params={"entityType": "party"}).status_code)
            correction = client.post(f"/api/communications/{response.json()['id']}/correct", json={
                "direction": "inbound", "channel": "phone", "subject": "Corrected", "body": "Corrected repair discussion.",
                "occurredAtUtc": "2026-01-01T12:30:00Z", "occurredTimezone": "UTC",
                "participants": [{"partyId": party.json()["id"], "role": "sender"}],
                "followUp": {"title": "Confirm repair"}, "correctionReason": "Clarified details.",
                "idempotencyKey": "19191919-1919-4919-8919-191919191919",
            })
            self.assertEqual(200, correction.status_code, correction.text)
            self.assertEqual(1, len(correction.json()["followUpTasks"]))
            self.assertEqual(2, len(client.get("/api/communications").json()["items"]))
            activity = client.get("/api/audit/events").json()["events"]
            communication_event = next(item for item in activity if item["entityType"] == "communication")
            self.assertEqual("[redacted]", communication_event["after"]["subject"])
            history = client.get(f"/api/audit/events/communication/{response.json()['id']}").json()["events"]
            self.assertEqual("Called", history[0]["after"]["subject"])

    def test_application_layer_has_no_sqlalchemy_or_adapter_import(self) -> None:
        import app.modules.communications.application.service as service_module
        source = inspect.getsource(service_module)
        self.assertNotIn("sqlalchemy", source)
        self.assertNotIn("communications.infrastructure", source)

    def test_communications_sqlite_adapter_has_no_foreign_module_models(self) -> None:
        import app.modules.communications.infrastructure.unit_of_work as unit_of_work
        source = inspect.getsource(unit_of_work)
        self.assertNotIn("modules.tasks.infrastructure", source)
        self.assertNotIn("modules.portfolio.infrastructure", source)

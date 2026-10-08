"""Manual command receipts and conflicts against the real latest SQLite schema."""

from __future__ import annotations

from app.modules.portfolio.tests.commands import inventory_command

import json
import sqlite3
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.leases.tests import test_leases as lease_fixtures
from app.modules.portfolio.application.status_contracts import (
    ManualStatusMutationResponse,
    SpaceStatusResponse,
)
from app.modules.portfolio.application.service import (
    AvailabilityCommand,
    OccupancyCommand,
    OwnershipInput,
    PortfolioNotFoundError,
    PortfolioService,
    SpaceClassificationCommand,
)
from app.modules.portfolio.infrastructure.receipt_triggers import STATUS_OPERATION_TRIGGERS
from app.modules.portfolio.infrastructure.schema_validation import validate_portfolio_schema
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
from app.modules.portfolio.infrastructure.unit_of_work import (
    SQLitePortfolioLeaseOperations,
    SQLitePortfolioUnitOfWork,
)
from app.modules.portfolio.tests import test_portfolio as fixtures
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.test_backup_service import MemorySecretStore
from app.platform.migration_errors import MigrationSchemaError
from app.platform.sqlite_engine import create_sqlite_engine


class CommandReadinessTests(unittest.TestCase):
    setUp = fixtures.PortfolioTests.setUp
    _property = fixtures.PortfolioTests._property

    def _space(self):
        property = self._property([OwnershipInput("local_operator")])
        return self.service.get_property(property.id)["spaces"][0]["id"]

    def _availability(self, space_id, key="first", revision=0):
        return self.service.change_availability(
            space_id,
            AvailabilityCommand("available_now"),
            expected_revision=revision,
            idempotency_key=key,
        )

    def _validate(self):
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.connect() as connection:
                validate_portfolio_schema(connection)
        finally:
            engine.dispose()

    def test_original_replay_and_both_receipt_lookups_after_later_change(self):
        space_id = self._space()
        config = Path(self.temp.name) / "receipt-api.json"
        config.write_text(json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}))
        instant = datetime.now(UTC)
        with patch.object(PortfolioService, "_instant", return_value=instant):
            with TestClient(create_app(config)) as client:
                request = {
                    "availabilityStatus": "available_now",
                    "expectedRevision": 0,
                    "idempotencyKey": "original",
                }
                url = f"/api/spaces/{space_id}/availability"
                original = client.put(url, json=request)
                self.assertEqual(original.status_code, 200)
                later = client.put(
                    url,
                    json={
                        **request,
                        "availabilityStatus": "not_available",
                        "expectedRevision": 1,
                        "idempotencyKey": "later",
                    },
                )
                self.assertEqual(later.status_code, 200)
                audit_count = len(self.audit.history())
                replay = client.put(url, json=request)
                self.assertEqual(replay.status_code, 200)
                self.assertEqual(replay.json(), original.json())
                operation_id = original.json()["operationId"]
                by_id = client.get(f"/api/portfolio/status-operations/{operation_id}")
                by_key = client.get(f"/api/spaces/{space_id}/status-operations/original")
                self.assertEqual(by_id.status_code, 200)
                self.assertEqual(by_key.status_code, 200)
                self.assertEqual(by_id.json(), by_key.json())
                self.assertEqual(by_id.json()["result"], original.json())
                self.assertEqual(by_id.json()["revision"], 1)
                self.assertEqual(len(self.audit.history()), audit_count)
                current = client.get(f"/api/spaces/{space_id}/status").json()
                self.assertEqual(current["revision"], 2)
                self.assertEqual(current["availability"]["availabilityStatus"], "not_available")
                self.assertIsNone(current["operationId"])
                self.assertEqual(
                    client.get(
                        "/api/spaces/00000000-0000-4000-8000-000000000000/status-operations/original"
                    ).status_code,
                    404,
                )
                self.assertEqual(
                    client.get(
                        "/api/portfolio/status-operations/00000000-0000-4000-8000-000000000000"
                    ).status_code,
                    404,
                )
                schemas = client.get("/openapi.json").json()["components"]["schemas"]
                self.assertIn("operationId", schemas["ManualStatusMutationResponse"]["required"])
                self.assertIn("revision", schemas["ManualStatusMutationResponse"]["required"])
                self.assertNotIn("operationId", schemas["SpaceStatusResponse"]["required"])
                property_id = self.service.unit_of_work.get_space(space_id).property_id
                inventory_command(self.service, "archive_property", property_id, confirmed=True)
                self.assertEqual(client.put(url, json=request).json(), original.json())
                self.assertEqual(
                    client.get(f"/api/portfolio/status-operations/{operation_id}").json(),
                    by_id.json(),
                )
        self._validate()

    def test_combined_classification_conflict_returns_committed_snapshot(self):
        space_id = self._space()
        with sqlite3.connect(self.workspace.paths.database) as connection:
            connection.execute(
                "UPDATE space_availability SET source_kind = 'listing', source_id = 'listing-1' "
                "WHERE space_id = ?",
                (space_id,),
            )
        config = Path(self.temp.name) / "classification-conflict-api.json"
        config.write_text(json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}))
        with patch.object(PortfolioService, "_instant", return_value=datetime.now(UTC)):
            with TestClient(create_app(config)) as client:
                before = client.get(f"/api/spaces/{space_id}/status").json()
                events = self.audit.history()
                response = client.put(
                    f"/api/spaces/{space_id}/classification",
                    json={
                        "occupancy": {
                            "occupancyStatus": "vacant",
                            "effectiveOn": before["effectiveLocalDate"],
                        },
                        "availability": {"availabilityStatus": "available_now"},
                        "expectedRevision": 0,
                        "idempotencyKey": "combined",
                    },
                )
                self.assertEqual(response.status_code, 409)
                detail = response.json()["detail"]
                self.assertEqual(detail["code"], "portfolio_status_lifecycle_conflict")
                self.assertEqual(detail["currentStatus"], before)
                self.assertEqual(client.get(f"/api/spaces/{space_id}/status").json(), before)
                self.assertEqual(self.audit.history(), events)
                self.assertEqual(
                    client.get(f"/api/spaces/{space_id}/status-operations/combined").status_code,
                    404,
                )

    def test_receipt_lookup_reads_one_retained_row_without_status_hydration(self):
        original = self._availability(self._space())
        queries = []

        def count_query(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                queries.append(statement)

        engine = self.service.unit_of_work.engine
        event.listen(engine, "before_cursor_execute", count_query)
        try:
            receipt = self.service.get_status_operation(operation_id=original["operationId"])
        finally:
            event.remove(engine, "before_cursor_execute", count_query)
        self.assertEqual(receipt["result"], original)
        self.assertEqual(len(queries), 1)
        self.assertIn("space_status_operations", queries[0])

    def test_changed_reuse_stale_and_archived_conflicts_include_full_snapshot(self):
        space_id = self._space()
        other_id = self._space()
        original = self._availability(space_id)
        self.service.change_occupancy(
            space_id,
            OccupancyCommand("vacant", "2090-01-01"),
            expected_revision=1,
            idempotency_key="schedule",
        )
        config = Path(self.temp.name) / "conflicts-api.json"
        config.write_text(json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}))
        with patch.object(PortfolioService, "_instant", return_value=datetime.now(UTC)):
            with TestClient(create_app(config)) as client:
                for status, revision, key, target, code in (
                    ("not_available", 0, "first", space_id, "portfolio_status_payload_conflict"),
                    ("available_now", 2, "first", space_id, "portfolio_status_payload_conflict"),
                    ("available_now", 0, "fresh", space_id, "portfolio_status_revision_conflict"),
                    ("available_now", 0, "first", other_id, "portfolio_status_payload_conflict"),
                ):
                    with self.subTest(code=code, target=target, revision=revision):
                        response = client.put(
                            f"/api/spaces/{target}/availability",
                            json={
                                "availabilityStatus": status,
                                "expectedRevision": revision,
                                "idempotencyKey": key,
                            },
                        )
                        self.assertEqual(response.status_code, 409)
                        detail = response.json()["detail"]
                        self.assertEqual(detail["code"], code)
                        expected = client.get(f"/api/spaces/{target}/status").json()
                        self.assertEqual(detail["currentStatus"], expected)
                other = self.service.unit_of_work.get_space(other_id)
                inventory_command(
                    self.service, "archive_property", other.property_id, confirmed=True
                )
                archived = client.put(
                    f"/api/spaces/{other_id}/availability",
                    json={
                        "availabilityStatus": "available_now",
                        "expectedRevision": 0,
                        "idempotencyKey": "archived",
                    },
                )
                self.assertEqual(archived.status_code, 409)
                detail = archived.json()["detail"]
                self.assertEqual(detail["code"], "portfolio_status_lifecycle_conflict")
                self.assertEqual(detail["currentStatus"]["status"], "archived")
        self.assertEqual(
            self.service.get_status_operation(operation_id=original["operationId"])["result"],
            original,
        )
        self._validate()

    def test_audit_failure_rolls_back_receipt_revision_history_and_retry(self):
        space_id = self._space()
        before = self.service.get_space_status(space_id)
        events = self.audit.history()
        recorder = self.service.unit_of_work.recorder
        record_change = recorder.record_change
        calls = 0

        def fail_second_audit(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise sqlite3.DatabaseError("audit unavailable")
            return record_change(*args, **kwargs)

        with patch.object(
            recorder,
            "record_change",
            side_effect=fail_second_audit,
        ):
            with self.assertRaises(sqlite3.DatabaseError):
                self.service.classify_space(
                    space_id,
                    SpaceClassificationCommand(
                        OccupancyCommand("vacant", before["effectiveLocalDate"]),
                        AvailabilityCommand("available_now"),
                    ),
                    expected_revision=0,
                    idempotency_key="first",
                )
        self.assertEqual(calls, 2)
        after = self.service.get_space_status(space_id)
        for key in ("revision", "availability", "currentOccupancy", "scheduledOccupancyTimeline"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(self.audit.history(), events)
        with self.assertRaises(PortfolioNotFoundError):
            self.service.get_status_operation(space_id=space_id, idempotency_key="first")
        receipt = self._availability(space_id)
        self.assertEqual(receipt["revision"], 1)
        self._validate()

    def test_retained_receipt_and_audit_trigger_corruption_are_rejected(self):
        space_id = self._space()
        original = self._availability(space_id)
        self._validate()
        with sqlite3.connect(self.workspace.paths.database) as connection:
            raw = connection.execute(
                "SELECT result_snapshot FROM space_status_operations"
            ).fetchone()[0]
        for field, value in (
            ("operationId", "changed"),
            ("revision", 8),
            ("id", "other-space"),
            ("scheduledOccupancyTimeline", None),
        ):
            with self.subTest(field=field):
                corrupt = {**original, field: value}
                with sqlite3.connect(self.workspace.paths.database) as connection:
                    # Simulate offline corruption, then restore the required
                    # trigger so validation must inspect the retained data.
                    connection.execute("DROP TRIGGER space_status_operations_conditional_update")
                    connection.execute(
                        "UPDATE space_status_operations SET result_snapshot = ?",
                        (json.dumps(corrupt),),
                    )
                    connection.execute(
                        STATUS_OPERATION_TRIGGERS["space_status_operations_conditional_update"]
                    )
                with self.assertRaises(MigrationSchemaError):
                    self._validate()
        with sqlite3.connect(self.workspace.paths.database) as connection:
            connection.execute("DROP TRIGGER space_status_operations_conditional_update")
            connection.execute("UPDATE space_status_operations SET result_snapshot = ?", (raw,))
            connection.execute(
                STATUS_OPERATION_TRIGGERS["space_status_operations_conditional_update"]
            )
            connection.execute("DROP TRIGGER space_status_operations_no_delete")
            connection.execute("DELETE FROM space_status_operations")
            connection.execute(STATUS_OPERATION_TRIGGERS["space_status_operations_no_delete"])
        with self.assertRaisesRegex(MigrationSchemaError, "revisions are incomplete"):
            self._validate()

    def test_audit_history_is_append_only_and_trigger_body_is_validated(self):
        self._space()
        with sqlite3.connect(self.workspace.paths.database) as connection:
            for sql in ("UPDATE audit_events SET reason = 'changed'", "DELETE FROM audit_events"):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                    connection.execute(sql)
            connection.execute("DROP TRIGGER audit_events_no_update")
            connection.execute(
                "CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events BEGIN SELECT 1; END"
            )
        with self.assertRaisesRegex(MigrationSchemaError, "append-only"):
            self._validate()

    def test_mutation_contract_requires_identity_but_get_contract_does_not(self):
        status = self.service.get_space_status(self._space())
        SpaceStatusResponse.model_validate(status)
        with self.assertRaises(ValidationError):
            ManualStatusMutationResponse.model_validate(status)

    def test_manual_receipts_reject_updates_deletes_and_replace(self):
        space_id = self._space()
        original = self._availability(space_id)
        with sqlite3.connect(self.workspace.paths.database) as connection:
            for sql, parameters in (
                ("UPDATE space_status_operations SET id = 'changed'", ()),
                ("UPDATE space_status_operations SET space_id = 'changed'", ()),
                ("UPDATE space_status_operations SET idempotency_key = 'changed'", ()),
                ("UPDATE space_status_operations SET request_fingerprint = 'changed'", ()),
                ("UPDATE space_status_operations SET result_revision = 99", ()),
                ("UPDATE space_status_operations SET created_at = 'changed'", ()),
                ("UPDATE space_status_operations SET result_snapshot = 'malformed'", ()),
                ("UPDATE space_status_operations SET result_snapshot = result_snapshot", ()),
                (
                    "UPDATE space_status_operations SET result_snapshot = ?",
                    (json.dumps({**original, "consumerResult": {"pretend": "lease"}}),),
                ),
                ("DELETE FROM space_status_operations", ()),
                (
                    "INSERT OR REPLACE INTO space_status_operations SELECT * FROM space_status_operations",
                    (),
                ),
                (
                    "INSERT OR REPLACE INTO space_status_operations "
                    "SELECT 'replacement', space_id, idempotency_key, request_fingerprint, "
                    "result_revision, result_snapshot, created_at FROM space_status_operations",
                    (),
                ),
            ):
                with self.subTest(sql=sql):
                    with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                        connection.execute(sql, parameters)
        self.assertEqual(
            self.service.get_status_operation(operation_id=original["operationId"])["result"],
            original,
        )
        self._validate()

    def test_receipt_trigger_missing_or_weakened_is_rejected(self):
        for name, sql in STATUS_OPERATION_TRIGGERS.items():
            with self.subTest(trigger=name):
                with sqlite3.connect(self.workspace.paths.database) as connection:
                    connection.execute(f"DROP TRIGGER {name}")
                with self.assertRaisesRegex(MigrationSchemaError, "immutability triggers"):
                    self._validate()
                action = (
                    "INSERT"
                    if name.endswith("replace")
                    else ("DELETE" if name.endswith("delete") else "UPDATE")
                )
                with sqlite3.connect(self.workspace.paths.database) as connection:
                    connection.execute(
                        f"CREATE TRIGGER {name} BEFORE {action} ON space_status_operations "
                        "BEGIN SELECT 1; END"
                    )
                with self.assertRaisesRegex(MigrationSchemaError, "immutability triggers"):
                    self._validate()
                with sqlite3.connect(self.workspace.paths.database) as connection:
                    connection.execute(f"DROP TRIGGER {name}")
                    connection.execute(sql)

    def test_encrypted_restore_preserves_original_receipt_and_replay(self):
        space_id = self._space()
        original = self._availability(space_id)
        self.service.change_availability(
            space_id,
            AvailabilityCommand("not_available"),
            expected_revision=1,
            idempotency_key="later",
        )
        backups = BackupService(
            self.workspace,
            AuditRecorder(self.audit),
            lambda database: AuditRecorder(SQLiteAuditRepository(database)),
            MemorySecretStore(),
        )
        passphrase = "portfolio receipt encrypted restore test"
        archive = backups.create_backup(
            passphrase, output_path=Path(self.temp.name) / "receipts.epmbackup"
        )
        self.assertNotEqual(archive.archive_path.read_bytes()[:2], b"PK")
        restored = backups.restore(
            archive.archive_path, passphrase, Path(self.temp.name) / "restored"
        )
        database = restored.workspace_path / "database" / "property-management.sqlite"
        service = PortfolioService(
            SQLitePortfolioUnitOfWork(database, AuditRecorder(SQLiteAuditRepository(database))),
            time_zone_resolver=BundledAddressTimeZoneResolver(),
        )
        receipt = service.get_status_operation(operation_id=original["operationId"])
        self.assertEqual(receipt["result"], original)
        self.assertEqual(service.get_space_status(space_id)["revision"], 2)
        replay = service.change_availability(
            space_id,
            AvailabilityCommand("available_now"),
            expected_revision=0,
            idempotency_key="first",
        )
        self.assertEqual(replay, original)


class LeaseReceiptCompatibilityTests(unittest.TestCase):
    def setUp(self):
        # This fixture executes a real lease command and attaches its
        # consumerResult through the existing production transaction.
        lease_fixtures.LeaseTerminationTests.setUp(self)

    def test_real_lease_atomic_attachment_replays_and_then_becomes_immutable(self):
        replay = self.service.execute(
            self.lease["id"],
            executed_on=date.today(),
            confirmed=True,
            expected_revision=self._execute_revision,
            expected_lease_revision=1,
            idempotency_key=self._execute_key,
        )
        self.assertEqual(replay, self.lease)
        with self.assertRaises(PortfolioNotFoundError):
            self.portfolio.get_status_operation(operation_id=self.lease["operationId"])
        with sqlite3.connect(self.workspace.paths.database) as connection:
            raw = connection.execute(
                "SELECT result_snapshot FROM space_status_operations"
            ).fetchone()[0]
            snapshot = json.loads(raw)
            self.assertEqual(snapshot["consumerResult"], self.lease)
            for changed in (
                {**snapshot, "consumerResult": {"changed": True}},
                {key: value for key, value in snapshot.items() if key != "consumerResult"},
                {**snapshot, "action": "changed"},
            ):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    connection.execute(
                        "UPDATE space_status_operations SET result_snapshot = ?",
                        (json.dumps(changed),),
                    )
        engine = create_sqlite_engine(self.workspace.paths.database)
        with engine.connect() as connection:
            validate_portfolio_schema(connection)

    def test_pending_lease_attachment_cannot_alter_other_fields_and_is_one_time(self):
        engine = create_sqlite_engine(self.workspace.paths.database)
        operations = SQLitePortfolioLeaseOperations(self.workspace.paths.database)
        with engine.connect() as connection:
            row = dict(
                connection.exec_driver_sql("SELECT * FROM space_status_operations").mappings().one()
            )
            snapshot = json.loads(row["result_snapshot"])
            snapshot.pop("consumerResult")
            snapshot["operationId"] = "pending-test"
            snapshot["revision"] += 1
            row.update(
                id="pending-test",
                idempotency_key="pending-test",
                result_revision=snapshot["revision"],
                result_snapshot=json.dumps(snapshot),
            )
            connection.exec_driver_sql(
                "INSERT INTO space_status_operations "
                "(id, space_id, idempotency_key, request_fingerprint, result_revision, result_snapshot, created_at) "
                "VALUES (:id, :space_id, :idempotency_key, :request_fingerprint, :result_revision, :result_snapshot, :created_at)",
                row,
            )
            for changed in (
                {**snapshot, "action": "changed", "consumerResult": self.lease},
                {**snapshot, "requestContext": {}, "consumerResult": self.lease},
                {**snapshot, "consumerResult": None},
                {**snapshot, "consumerResult": []},
            ):
                with self.subTest(snapshot=changed):
                    with self.assertRaisesRegex(IntegrityError, "immutable"):
                        connection.exec_driver_sql(
                            "UPDATE space_status_operations SET result_snapshot = ? WHERE id = 'pending-test'",
                            (json.dumps(changed),),
                        )
            operations.store_source_timeline_consumer_result(connection, "pending-test", self.lease)
            recorded = operations.status_operation(connection, "pending-test")
            self.assertEqual(
                json.loads(recorded["result_snapshot"]), {**snapshot, "consumerResult": self.lease}
            )
            with self.assertRaisesRegex(IntegrityError, "immutable"):
                connection.exec_driver_sql(
                    "UPDATE space_status_operations SET result_snapshot = ? WHERE id = 'pending-test'",
                    (json.dumps({**snapshot, "consumerResult": self.lease}),),
                )
            # Leaving the connection without committing rolls back the synthetic
            # pending receipt and preserves the real lease fixture.

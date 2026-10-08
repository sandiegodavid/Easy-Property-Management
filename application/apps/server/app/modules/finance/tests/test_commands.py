"""Real SQLite proofs for Slice 15's rent-ledger command boundary."""

import json
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, exc, text

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.finance.application.commands import FinanceCommandIdentity, FinanceScope
from app.modules.finance.domain.command_audit_policy import FINANCE_COMMAND_ACTIVITY_POLICY
from app.modules.finance.domain.models import (
    FinanceConflictError,
    FinanceValidationError,
    ReceiptAllocationCommand,
    RecordReceiptCommand,
    SynchronizeExpectationsCommand,
    VoidCommand,
    TimelinessReviewCommand,
)
from app.modules.finance.infrastructure.command_models import FINANCE_COMMAND_TRIGGERS
from app.modules.finance.infrastructure.command_operations import SQLiteFinanceCommandTransaction
from app.modules.finance.infrastructure.command_validation import validate_finance_commands
from app.modules.finance.tests import test_finance as fixtures
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction


class FinanceCommandTests(unittest.TestCase):
    def setUp(self):
        fixtures.FinanceWorkflowTests.setUp(self)
        self.schedule = SynchronizeExpectationsCommand(
            self.lease["terms"][0]["id"],
            (date.today() + timedelta(days=60)).isoformat(),
            date.today().replace(day=1).isoformat(),
        )
        self.synchronization_key = str(uuid4())
        self.synchronization = self.finance.synchronize(
            self.lease["id"],
            self.schedule,
            expected_revision=0,
            idempotency_key=self.synchronization_key,
        )
        self.expectation = self.synchronization["items"][0]
        self.command = RecordReceiptCommand(
            self.lease["id"],
            str(uuid4()),
            date.today().isoformat(),
            self.expectation["expectedAmountMinor"],
            "USD",
            (
                ReceiptAllocationCommand(
                    self.expectation["id"], self.expectation["expectedAmountMinor"]
                ),
            ),
            "cash",
        )
        self.engine = self.finance.unit_of_work.engine

    def test_original_receipt_replay_survives_later_void_and_source_changes(self):
        receipt = self.finance.record_receipt(self.command, expected_revision=1)
        self.assertEqual(receipt["rentLedgerRevision"], 2)
        voided = self.finance.void_receipt(
            receipt["id"],
            VoidCommand(True, "Recorded twice"),
            expected_revision=2,
            idempotency_key=str(uuid4()),
        )
        self.assertEqual(voided["rentLedgerRevision"], 3)
        self.assertIsNotNone(self.finance.receipt(receipt["id"])["voidedAt"])
        with patch(
            "app.modules.finance.application.service.record_receipt_in_transaction",
            side_effect=AssertionError("replay reran money policy"),
        ):
            self.assertEqual(
                receipt, self.finance.record_receipt(self.command, expected_revision=1)
            )
        recovery = self.finance.command_operation(self.command.idempotency_key)
        self.assertEqual(recovery["result"], receipt)
        self.assertEqual(recovery["expectedRevision"], 1)
        self.assertEqual(
            self.finance.rent_ledger_revision(self.lease["id"])["rentLedgerRevision"], 3
        )
        validate_latest_schema(self.workspace.paths.database)

    def test_changed_reuse_and_stale_revision_do_not_write(self):
        receipt = self.finance.record_receipt(self.command, expected_revision=1)
        with self.assertRaises(FinanceConflictError) as changed:
            self.finance.record_receipt(
                replace(self.command, notes="changed request"), expected_revision=1
            )
        self.assertEqual(changed.exception.code, "finance_idempotency_conflict")
        with self.assertRaises(FinanceConflictError) as stale:
            self.finance.void_receipt(
                receipt["id"],
                VoidCommand(True, "Correction"),
                expected_revision=1,
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(stale.exception.code, "finance_revision_conflict")
        self.assertEqual(stale.exception.details["currentRevision"], 2)
        self.assertIsNone(self.finance.receipt(receipt["id"])["voidedAt"])

    def test_concurrent_exact_retries_create_one_receipt_and_allocation(self):
        from app.modules.finance.application.receipt_handoff import record_receipt_in_transaction

        with patch(
            "app.modules.finance.application.service.record_receipt_in_transaction",
            wraps=record_receipt_in_transaction,
        ) as record:
            with ThreadPoolExecutor(max_workers=2) as workers:
                futures = [
                    workers.submit(self.finance.record_receipt, self.command, expected_revision=1)
                    for _ in range(2)
                ]
                results = [future.result() for future in futures]
            self.assertEqual(results[0], results[1])
            self.assertEqual(record.call_count, 1)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM rent_receipts")), 1)
            self.assertEqual(
                connection.scalar(text("SELECT count(*) FROM rent_receipt_allocations")), 1
            )
        self.assertEqual(
            self.finance.rent_ledger_revision(self.lease["id"])["rentLedgerRevision"], 2
        )
        validate_latest_schema(self.workspace.paths.database)

    def test_signature_and_non_http_validation_are_required(self):
        with self.assertRaises(TypeError):
            self.finance.record_receipt(self.command)
        for revision in (True, False, -1, "1", None):
            with self.subTest(revision=revision), self.assertRaises(FinanceValidationError):
                self.finance.record_receipt(self.command, expected_revision=revision)
        for key in ("", "not-a-uuid", str(uuid4()).upper()):
            with self.subTest(key=key), self.assertRaises(FinanceValidationError):
                self.finance.synchronize(
                    self.lease["id"], self.schedule, expected_revision=1, idempotency_key=key
                )

    def test_result_and_audit_failure_roll_back_receipt_allocations_and_revision(self):
        def counts():
            with self.engine.connect() as connection:
                return tuple(
                    connection.scalar(text(f"SELECT count(*) FROM {table}"))
                    for table in (
                        "rent_receipts",
                        "rent_receipt_allocations",
                        "finance_command_operations",
                        "audit_events",
                    )
                )

        before = counts()
        with patch.object(
            SQLiteFinanceCommandTransaction,
            "store_command",
            side_effect=RuntimeError("receipt persistence failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "persistence failed"):
                self.finance.record_receipt(self.command, expected_revision=1)
        self.assertEqual(counts(), before)
        recorder = self.finance.unit_of_work.recorder
        original = recorder.record_change

        def fail_operation_audit(*args, **kwargs):
            if kwargs["entity_type"] == "finance_command_operation":
                raise RuntimeError("audit unavailable")
            return original(*args, **kwargs)

        with patch.object(recorder, "record_change", side_effect=fail_operation_audit):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                self.finance.record_receipt(self.command, expected_revision=1)
        self.assertEqual(counts(), before)
        self.assertEqual(
            self.finance.rent_ledger_revision(self.lease["id"])["rentLedgerRevision"], 1
        )

    def test_noop_synchronization_records_receipt_without_advancing_revision(self):
        key = str(uuid4())
        response = self.finance.synchronize(
            self.lease["id"], self.schedule, expected_revision=1, idempotency_key=key
        )
        self.assertEqual(response["items"], [])
        self.assertEqual(response["rentLedgerRevision"], 1)
        self.assertEqual(
            self.finance.synchronize(
                self.lease["id"], self.schedule, expected_revision=1, idempotency_key=key
            ),
            response,
        )
        validate_latest_schema(self.workspace.paths.database)

    def test_review_and_expectation_void_replay_preserve_original_state(self):
        from datetime import UTC, datetime

        self.finance.now = lambda: datetime.now(UTC) + timedelta(days=150)
        key = str(uuid4())
        review = TimelinessReviewCommand("mark_missed", "Follow-up confirmed", True)
        marked = self.finance.review_timeliness(
            self.expectation["id"], review, expected_revision=1, idempotency_key=key
        )
        self.assertTrue(marked["effectiveMissedReview"])
        self.finance.review_timeliness(
            self.expectation["id"],
            TimelinessReviewCommand("clear_missed", "Corrected review", True),
            expected_revision=2,
            idempotency_key=str(uuid4()),
        )
        self.assertEqual(
            self.finance.review_timeliness(
                self.expectation["id"], review, expected_revision=1, idempotency_key=key
            ),
            marked,
        )
        void_key = str(uuid4())
        void_command = VoidCommand(True, "Duplicate schedule entry")
        voided = self.finance.void_expectation(
            self.expectation["id"], void_command, expected_revision=3, idempotency_key=void_key
        )
        self.assertEqual(voided["rentLedgerRevision"], 4)
        self.assertEqual(
            self.finance.void_expectation(
                self.expectation["id"], void_command, expected_revision=3, idempotency_key=void_key
            ),
            voided,
        )
        self.assertEqual(
            self.finance.synchronize(
                self.lease["id"],
                self.schedule,
                expected_revision=0,
                idempotency_key=self.synchronization_key,
            ),
            self.synchronization,
        )
        validate_latest_schema(self.workspace.paths.database)

    def test_missing_business_audit_is_rejected_on_workspace_open(self):
        receipt = self.finance.record_receipt(self.command, expected_revision=1)
        with immediate_transaction(self.engine) as connection:
            trigger = connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE name = 'audit_events_no_delete'"
            ).scalar_one()
            connection.exec_driver_sql("DROP TRIGGER audit_events_no_delete")
            connection.exec_driver_sql(
                "DELETE FROM audit_events WHERE entity_type = 'rent_receipt' AND entity_id = ?",
                (receipt["id"],),
            )
            connection.exec_driver_sql(trigger)
            with self.assertRaises(MigrationSchemaError):
                validate_finance_commands(connection)

    def test_recovery_is_one_select_and_batch_revisions_are_bounded(self):
        statements = []

        def count(_connection, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", count)
        try:
            self.finance.command_operation(self.synchronization_key)
            self.assertEqual(len(statements), 1)
            statements.clear()
            scopes = [FinanceScope("rent_ledger", self.lease["id"])] + [
                FinanceScope("rent_ledger", str(uuid4())) for _ in range(499)
            ]
            projection = self.finance.unit_of_work.read(
                lambda tx: tx.commands.command_revisions(scopes)
            )
            self.assertEqual(len(statements), 1)
            self.assertEqual(projection[scopes[0]], 1)
            self.assertEqual(len(projection), 500)
            statements.clear()
            self.assertEqual(
                self.finance.unit_of_work.read(lambda tx: tx.commands.command_revisions([])), {}
            )
            self.assertEqual(statements, [])
            with self.assertRaises(ValueError):
                self.finance.unit_of_work.read(
                    lambda tx: tx.commands.command_revisions(
                        scopes + [FinanceScope("rent_ledger", str(uuid4()))]
                    )
                )
        finally:
            event.remove(self.engine, "before_cursor_execute", count)

    def test_receipt_payload_is_frozen_and_general_activity_is_private(self):
        payload = {"allocations": [{"amountMinor": 100}]}
        identity = FinanceCommandIdentity(
            FinanceScope("rent_ledger", self.lease["id"]),
            "record_receipt",
            self.lease["id"],
            1,
            str(uuid4()),
            payload,
        )
        before = identity.request_json
        payload["allocations"][0]["amountMinor"] = 200
        self.assertEqual(identity.request_json, before)
        receipt = self.finance.record_receipt(self.command, expected_revision=1)
        operation = self.finance.unit_of_work.read(
            lambda tx: tx.commands.command_operation(self.command.idempotency_key)
        )
        public = FINANCE_COMMAND_ACTIVITY_POLICY.redact(operation)
        for field in (
            "request_json",
            "response_json",
            "idempotency_key",
            "request_fingerprint",
            "response_fingerprint",
            "scope_id",
            "target_id",
        ):
            self.assertNotIn(field, public)
        self.assertEqual(public["id"], receipt["operationId"])

    def test_append_only_and_retained_result_tampering(self):
        for mutation in (
            "UPDATE finance_command_operations SET action = 'void_receipt'",
            "DELETE FROM finance_command_operations",
            "INSERT OR REPLACE INTO finance_command_operations SELECT * FROM finance_command_operations",
        ):
            with (
                self.subTest(mutation=mutation),
                self.assertRaises(exc.IntegrityError),
                immediate_transaction(self.engine) as connection,
            ):
                connection.exec_driver_sql(mutation)
        with immediate_transaction(self.engine) as connection:
            connection.exec_driver_sql("DROP TRIGGER finance_command_operations_no_update")
            connection.exec_driver_sql("UPDATE finance_command_operations SET response_json = '{}'")
            connection.exec_driver_sql(
                FINANCE_COMMAND_TRIGGERS["finance_command_operations_no_update"]
            )
            with self.assertRaises(MigrationSchemaError):
                validate_finance_commands(connection)

    def test_http_contract_replay_recovery_and_stale_details(self):
        payload = {
            "leaseId": self.command.lease_id,
            "idempotencyKey": self.command.idempotency_key,
            "receivedOn": self.command.received_on,
            "amountMinor": self.command.amount_minor,
            "currencyCode": "USD",
            "paymentMethodKind": "cash",
            "allocations": [
                {"expectationId": self.expectation["id"], "amountMinor": self.command.amount_minor}
            ],
            "expectedRevision": 1,
        }
        with TestClient(create_app(self.workspace.config.config_path)) as client:
            schema = client.get("/openapi.json").json()
            operation = schema["paths"]["/api/rent-receipts"]["post"]
            self.assertEqual(operation["operationId"], "recordRentReceipt")
            input_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
            self.assertIn(
                "expectedRevision",
                schema["components"]["schemas"][input_ref.rsplit("/", 1)[1]]["required"],
            )
            missing = client.post(
                "/api/rent-receipts",
                json={key: value for key, value in payload.items() if key != "expectedRevision"},
            )
            self.assertEqual(missing.status_code, 422)
            created = client.post("/api/rent-receipts", json=payload)
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(client.post("/api/rent-receipts", json=payload).json(), created.json())
            recovered = client.get(
                f"/api/finance/command-operations/{self.command.idempotency_key}"
            )
            self.assertEqual(recovered.status_code, 200, recovered.text)
            self.assertEqual(recovered.json()["result"], created.json())
            stale = client.post(
                f"/api/rent-receipts/{created.json()['id']}/void",
                json={
                    "confirmed": True,
                    "voidReason": "Correction",
                    "expectedRevision": 1,
                    "idempotencyKey": str(uuid4()),
                },
            )
            self.assertEqual(stale.status_code, 409, stale.text)
            self.assertEqual(stale.json()["detail"]["currentRevision"], 2)
            self.assertEqual(stale.json()["detail"]["code"], "finance_revision_conflict")

    @fast_backup_encryption()
    def test_encrypted_backup_preserves_original_receipts_and_revisions(self):
        receipt = self.finance.record_receipt(self.command, expected_revision=1)

        def repository(database):
            return AuditRecorder(SQLiteAuditRepository(database))

        backup = BackupService(
            self.workspace, repository(self.workspace.paths.database), repository
        )
        archive = backup.create_backup(
            "a sufficiently long backup passphrase",
            output_path=Path(self.temp.name) / "commands.epm-backup",
        )
        target = Path(self.temp.name) / "restored-commands"
        backup.restore(archive.archive_path, "a sufficiently long backup passphrase", target)
        restored_database = target / "database" / "property-management.sqlite"
        validate_latest_schema(restored_database)
        restored_engine = create_sqlite_engine(restored_database)
        try:
            with self.engine.connect() as source, restored_engine.connect() as restored:
                for table in ("finance_command_operations", "finance_command_revisions"):
                    self.assertEqual(
                        source.exec_driver_sql(f"SELECT * FROM {table}").all(),
                        restored.exec_driver_sql(f"SELECT * FROM {table}").all(),
                    )
                audit_query = "SELECT * FROM audit_events WHERE entity_type IN ('finance_command_scope', 'finance_command_operation', 'rent_receipt', 'rent_receipt_allocation') ORDER BY id"
                self.assertEqual(
                    source.exec_driver_sql(audit_query).all(),
                    restored.exec_driver_sql(audit_query).all(),
                )
                recorded = restored.exec_driver_sql(
                    "SELECT response_json FROM finance_command_operations WHERE idempotency_key = ?",
                    (self.command.idempotency_key,),
                ).scalar_one()
                self.assertEqual(json.loads(recorded), receipt)
        finally:
            restored_engine.dispose()

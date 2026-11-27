"""Focused proofs for FIN-009 Slice 4: late-fee receipts, combined receipts, and FIN-003 reporting."""

import unittest
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.bootstrap.api import create_app
from app.modules.finance.application.late_fee_service import LateFeeService
from app.modules.finance.domain.late_fee_models import (
    AssessLateFeeCommand,
    CreateLateFeePolicyCommand,
    LateFeeReceiptAllocationCommand,
    RecordCombinedReceiptCommand,
    RecordLateFeeReceiptCommand,
    VoidLateFeeReceiptCommand,
)
from app.modules.finance.domain.models import (
    FinanceConflictError,
    FinanceValidationError,
    ReceiptAllocationCommand,
    SynchronizeExpectationsCommand,
)
from app.modules.finance.tests import test_finance as fixtures
from app.platform.product_migrations import validate_latest_schema
from app.platform.testing_client import LocalApiClient as TestClient


class LateFeeReceiptsAndReportingSlice4Tests(unittest.TestCase):
    def setUp(self):
        fixtures.FinanceWorkflowTests.setUp(self)
        self.lease_id = self.lease["id"]
        self.term_id = self.lease["terms"][0]["id"]
        self.zone = ZoneInfo("America/Los_Angeles")
        self.sync = self.finance.synchronize(
            self.lease_id,
            SynchronizeExpectationsCommand(
                self.term_id,
                (date.today() + timedelta(days=90)).isoformat(),
                date.today().replace(day=1).isoformat(),
            ),
            expected_revision=0,
            idempotency_key=str(uuid4()),
        )
        self.expectation = next(item for item in self.sync["items"] if not item["isProrated"])
        self.due = date.fromisoformat(self.expectation["dueOn"])
        self.first_eligible = self.due + timedelta(days=6)
        self.eligible_instant = datetime.combine(
            self.first_eligible, datetime.min.time(), self.zone
        ).astimezone(UTC) + timedelta(hours=12)
        self.svc = LateFeeService(self.finance.unit_of_work, now=lambda: self.eligible_instant)

        policy = self.svc.create_policy(
            self.lease_id,
            CreateLateFeePolicyCommand(
                effective_on=(self.due - timedelta(days=30)).isoformat(),
                rule_basis="Lease Section 5(b)",
                grace_period_days=5,
                calculation_basis="unpaid_rent_at_grace_end",
                formula_kind="fixed_flat",
                flat_amount_minor=5000,
                rounding_mode="half_up",
                applies_to_prorated_periods=False,
                operator_confirmed=True,
            ),
            expected_revision=self.sync["rentLedgerRevision"],
            idempotency_key=str(uuid4()),
        )
        preview = self.svc.preview_late_fees(
            self.lease_id,
            as_of_date=self.first_eligible.isoformat(),
            rent_expectation_id=self.expectation["id"],
        )
        self.assessment = self.svc.assess_late_fee(
            self.lease_id,
            AssessLateFeeCommand(
                rent_expectation_id=self.expectation["id"],
                as_of_date=self.first_eligible.isoformat(),
                preview_fingerprint=preview["items"][0]["previewFingerprint"],
                operator_confirmed=True,
            ),
            expected_revision=policy["rentLedgerRevision"],
            idempotency_key=str(uuid4()),
        )
        self.rev = self.assessment["rentLedgerRevision"]

    def test_standalone_late_fee_receipt_masked_reference_void_replace_and_recovery(self):
        # FIN-006 masked-reference enforcement rejects raw unmasked numbers.
        with self.assertRaises(FinanceValidationError):
            RecordLateFeeReceiptCommand(
                received_on=self.first_eligible.isoformat(),
                amount_minor=2000,
                currency_code="USD",
                allocations=(LateFeeReceiptAllocationCommand(self.assessment["id"], 2000),),
                payment_method_kind="check",
                masked_reference="123456789",
            )

        # Partial payment with valid safe masked reference.
        fee_key = str(uuid4())
        partial = self.svc.record_late_fee_receipt(
            self.lease_id,
            RecordLateFeeReceiptCommand(
                received_on=self.first_eligible.isoformat(),
                amount_minor=2000,
                currency_code="USD",
                allocations=(LateFeeReceiptAllocationCommand(self.assessment["id"], 2000),),
                payment_method_kind="check",
                masked_reference="Check •••• 9182",
            ),
            expected_revision=self.rev,
            idempotency_key=fee_key,
        )
        self.assertEqual(partial["amountMinor"], 2000)
        self.assertEqual(partial["maskedReference"], "Check •••• 9182")
        self.assertIsNone(partial["paymentBatchId"])
        rev = partial["rentLedgerRevision"]

        # Assessment reflects partial payment without contaminating rent_receipts.
        detail = self.svc.get_assessment(self.assessment["id"])
        self.assertEqual(detail["paidAmountMinor"], 2000)
        self.assertEqual(detail["remainingBalanceMinor"], 3000)
        self.assertEqual(detail["settlementStatus"], "partially_paid")
        self.assertEqual(self.finance.list_receipts(lease_id=self.lease_id)["items"], [])

        # Voiding the receipt restores full unpaid balance and allows void-and-replace.
        void_key = str(uuid4())
        voided = self.svc.void_late_fee_receipt(
            partial["id"],
            VoidLateFeeReceiptCommand(True, "Wrong check reference."),
            expected_revision=rev,
            idempotency_key=void_key,
        )
        self.assertIsNotNone(voided["voidedAt"])
        rev = voided["rentLedgerRevision"]
        self.assertEqual(self.svc.get_assessment(self.assessment["id"])["paidAmountMinor"], 0)

        replaced = self.svc.record_late_fee_receipt(
            self.lease_id,
            RecordLateFeeReceiptCommand(
                received_on=self.first_eligible.isoformat(),
                amount_minor=5000,
                currency_code="USD",
                allocations=(LateFeeReceiptAllocationCommand(self.assessment["id"], 5000),),
                payment_method_kind="check",
                masked_reference="Check •••• 4455",
                replaces_receipt_id=partial["id"],
            ),
            expected_revision=rev,
            idempotency_key=str(uuid4()),
        )
        self.assertEqual(replaced["replacesReceiptId"], partial["id"])
        self.assertEqual(self.svc.get_assessment(self.assessment["id"])["settlementStatus"], "paid")

        # HTTP detail & command recovery work cleanly.
        with TestClient(create_app(self.config)) as client:
            got = client.get(f"/api/late-fee-receipts/{replaced['id']}")
            self.assertEqual(got.status_code, 200, got.text)
            self.assertEqual(got.json()["amountMinor"], 5000)
            for key, action in (
                (fee_key, "record_late_fee_receipt"),
                (void_key, "void_late_fee_receipt"),
            ):
                rec = client.get(f"/api/finance/command-operations/{key}")
                self.assertEqual(rec.status_code, 200, rec.text)
                self.assertEqual(rec.json()["action"], action)

        validate_latest_schema(self.workspace.paths.database)

    def test_combined_receipt_atomicity_rollback_and_fin003_reporting_separation(self):
        # 1. Atomicity: if late-fee allocation exceeds remaining balance, rent half rolls back too!
        with self.assertRaises(FinanceConflictError) as over:
            self.svc.record_combined_receipt(
                self.lease_id,
                RecordCombinedReceiptCommand(
                    received_on=self.first_eligible.isoformat(),
                    currency_code="USD",
                    rent_allocations=(
                        ReceiptAllocationCommand(
                            self.expectation["id"], self.expectation["expectedAmountMinor"]
                        ),
                    ),
                    late_fee_allocations=(
                        LateFeeReceiptAllocationCommand(self.assessment["id"], 5001),
                    ),
                    payment_method_kind="check",
                    masked_reference="Check •••• 7777",
                ),
                expected_revision=self.rev,
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(over.exception.code, "late_fee_allocation_exceeds_balance")
        self.assertEqual(self.finance.list_receipts(lease_id=self.lease_id)["items"], [])
        self.assertEqual(
            self.finance.rent_ledger_revision(self.lease_id)["rentLedgerRevision"], self.rev
        )

        # 2. Valid combined payment creates separate rent & fee receipts sharing paymentBatchId.
        combined_key = str(uuid4())
        rent_amt = self.expectation["expectedAmountMinor"]
        fee_amt = 5000
        combined = self.svc.record_combined_receipt(
            self.lease_id,
            RecordCombinedReceiptCommand(
                received_on=self.first_eligible.isoformat(),
                currency_code="USD",
                rent_allocations=(ReceiptAllocationCommand(self.expectation["id"], rent_amt),),
                late_fee_allocations=(
                    LateFeeReceiptAllocationCommand(self.assessment["id"], fee_amt),
                ),
                payment_method_kind="check",
                masked_reference="Check •••• 8888",
            ),
            expected_revision=self.rev,
            idempotency_key=combined_key,
        )
        batch_id = combined["paymentBatchId"]
        self.assertEqual(combined["rentAmountMinor"], rent_amt)
        self.assertEqual(combined["lateFeeAmountMinor"], fee_amt)
        self.assertEqual(combined["totalAmountMinor"], rent_amt + fee_amt)
        self.assertEqual(combined["rentReceipt"]["paymentBatchId"], batch_id)
        self.assertEqual(combined["lateFeeReceipt"]["paymentBatchId"], batch_id)
        self.assertEqual(combined["rentReceipt"]["amountMinor"], rent_amt)
        self.assertEqual(combined["lateFeeReceipt"]["amountMinor"], fee_amt)

        # 3. FIN-003 reporting shows lateFeesReceived separately without contaminating rentReceived
        # or operatingRemainder (Rent less net expenses).
        from_on = (self.first_eligible - timedelta(days=5)).isoformat()
        through_on = (self.first_eligible + timedelta(days=5)).isoformat()
        with TestClient(create_app(self.config)) as client:
            summary = client.get(f"/api/money/summary?fromOn={from_on}&throughOn={through_on}")
            self.assertEqual(summary.status_code, 200, summary.text)
            op = summary.json()["operating"]
            expected_rent_str = f"{rent_amt // 100}.{rent_amt % 100:02d}"
            self.assertEqual(op["rentReceived"], expected_rent_str)
            self.assertEqual(op["operatingRemainder"], expected_rent_str)
            self.assertEqual(op["rentReceiptCount"], 1)
            self.assertEqual(op["lateFeesReceived"], "50.00")
            self.assertEqual(op["lateFeeReceiptCount"], 1)

            # Drill-down on metric=lateFeesReceived returns the late_fee_receipt with detailRoute.
            sources = client.get(
                f"/api/money/sources?fromOn={from_on}&throughOn={through_on}&metric=lateFeesReceived"
            )
            self.assertEqual(sources.status_code, 200, sources.text)
            src_body = sources.json()
            self.assertEqual(src_body["total"], "50.00")
            self.assertEqual(src_body["matchingTotal"], 1)
            self.assertEqual(src_body["items"][0]["sourceKind"], "late_fee_receipt")
            self.assertEqual(
                src_body["items"][0]["detailRoute"],
                f"/api/late-fee-receipts/{combined['lateFeeReceipt']['id']}",
            )

            # Command recovery works for record_combined_receipt.
            rec = client.get(f"/api/finance/command-operations/{combined_key}")
            self.assertEqual(rec.status_code, 200, rec.text)
            self.assertEqual(rec.json()["action"], "record_combined_receipt")
            self.assertEqual(rec.json()["result"]["paymentBatchId"], batch_id)
            self.assertEqual(rec.json()["result"]["totalAmountMinor"], rent_amt + fee_amt)

        validate_latest_schema(self.workspace.paths.database)

    def test_local002_encrypted_backup_restore_preserves_all_fin009_records(self):
        from pathlib import Path
        from app.modules.audit.application.recorder import AuditRecorder
        from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
        from app.modules.workspace.application.backup_service import BackupService
        from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
        from app.platform.sqlite_engine import create_sqlite_engine

        # Record a combined receipt so policy, assessment, receipt, allocation, and batch ID all exist.
        combined = self.svc.record_combined_receipt(
            self.lease_id,
            RecordCombinedReceiptCommand(
                received_on=self.first_eligible.isoformat(),
                currency_code="USD",
                rent_allocations=(
                    ReceiptAllocationCommand(
                        self.expectation["id"], self.expectation["expectedAmountMinor"]
                    ),
                ),
                late_fee_allocations=(
                    LateFeeReceiptAllocationCommand(self.assessment["id"], 5000),
                ),
                payment_method_kind="check",
                masked_reference="Check •••• 1111",
            ),
            expected_revision=self.rev,
            idempotency_key=str(uuid4()),
        )
        self.assertIsNotNone(combined["paymentBatchId"])

        def make_recorder(database):
            return AuditRecorder(SQLiteAuditRepository(database))

        with fast_backup_encryption():
            backups = BackupService(
                self.workspace,
                make_recorder(self.workspace.paths.database),
                make_recorder,
            )
            archive = backups.create_backup(
                "a sufficiently long backup passphrase",
                output_path=Path(self.temp.name) / "fin009.epm-backup",
            )
            target = Path(self.temp.name) / "restored-fin009"
            backups.restore(archive.archive_path, "a sufficiently long backup passphrase", target)

        restored_db = target / "database" / "property-management.sqlite"
        validate_latest_schema(restored_db)
        restored_engine = create_sqlite_engine(restored_db)
        try:
            with (
                self.finance.unit_of_work.engine.connect() as src,
                restored_engine.connect() as dst,
            ):
                for table in (
                    "late_fee_policy_versions",
                    "late_fee_assessments",
                    "late_fee_waivers",
                    "late_fee_receipts",
                    "late_fee_receipt_allocations",
                ):
                    self.assertEqual(
                        src.exec_driver_sql(f"SELECT * FROM {table} ORDER BY id").all(),
                        dst.exec_driver_sql(f"SELECT * FROM {table} ORDER BY id").all(),
                    )
        finally:
            restored_engine.dispose()

    def test_restore_schema_validation_rejects_broken_fee_conservation_and_over_settlement(self):
        import sqlite3

        from app.modules.finance.infrastructure.schema_validation import MigrationSchemaError

        fee = self.assessment
        rec = self.svc.record_late_fee_receipt(
            self.lease_id,
            RecordLateFeeReceiptCommand(
                received_on=self.first_eligible.isoformat(),
                amount_minor=2000,
                currency_code="USD",
                allocations=(LateFeeReceiptAllocationCommand(fee["id"], 2000),),
                payment_method_kind="check",
                masked_reference="Check •••• 5001",
            ),
            expected_revision=self.rev,
            idempotency_key=str(uuid4()),
        )
        self.rev = rec["rentLedgerRevision"]
        validate_latest_schema(self.workspace.paths.database)

        def snapshot_db(dest):
            with (
                sqlite3.connect(self.workspace.paths.database) as src,
                sqlite3.connect(dest) as dst,
            ):
                src.backup(dst)

        # Case 1: Delete allocation row so non-voided receipt amount != sum(allocations) -> must fail restore check!
        corrupt1 = self.workspace.paths.database.parent / "corrupt_missing_alloc.sqlite"
        snapshot_db(corrupt1)
        with sqlite3.connect(corrupt1) as conn:
            trigger_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='trg_late_fee_receipt_allocations_no_delete'"
            ).fetchone()
            conn.execute("DROP TRIGGER IF EXISTS trg_late_fee_receipt_allocations_no_delete")
            conn.execute(
                "DELETE FROM late_fee_receipt_allocations WHERE receipt_id = ?",
                (rec["id"],),
            )
            if trigger_sql and trigger_sql[0]:
                conn.execute(trigger_sql[0])
            conn.commit()
        with self.assertRaisesRegex(MigrationSchemaError, "FIN-009 data integrity"):
            validate_latest_schema(corrupt1)

        # Case 2: Active allocations + waivers exceed assessed_amount_minor -> must fail restore check!
        corrupt2 = self.workspace.paths.database.parent / "corrupt_over_settled.sqlite"
        snapshot_db(corrupt2)
        with sqlite3.connect(corrupt2) as conn:
            conn.execute(
                """INSERT INTO late_fee_waivers (
                    id, assessment_id, lease_id, waived_amount_minor, currency_code, waived_on,
                    reason, internal_notes, waived_at, waived_by_actor
                ) VALUES (?, ?, ?, ?, 'USD', ?, ?, NULL, ?, 'operator')""",
                (
                    str(uuid4()),
                    fee["id"],
                    self.lease_id,
                    4000,  # 2000 paid + 4000 waived = 6000 > 5000 assessed!
                    self.first_eligible.isoformat(),
                    "Corrupt over-waiver",
                    self.eligible_instant.isoformat(),
                ),
            )
            conn.commit()
        with self.assertRaisesRegex(MigrationSchemaError, "FIN-009 data integrity"):
            validate_latest_schema(corrupt2)

        # Case 3 (Finding 6): Voided receipt with missing allocation history MUST ALSO fail restore check!
        voided = self.svc.void_late_fee_receipt(
            rec["id"],
            VoidLateFeeReceiptCommand(True, "Voided for replacement"),
            expected_revision=self.rev,
            idempotency_key=str(uuid4()),
        )
        self.rev = voided["rentLedgerRevision"]
        validate_latest_schema(self.workspace.paths.database)

        corrupt3 = self.workspace.paths.database.parent / "corrupt_voided_missing_alloc.sqlite"
        snapshot_db(corrupt3)
        with sqlite3.connect(corrupt3) as conn:
            trigger_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='trg_late_fee_receipt_allocations_no_delete'"
            ).fetchone()
            conn.execute("DROP TRIGGER IF EXISTS trg_late_fee_receipt_allocations_no_delete")
            conn.execute(
                "DELETE FROM late_fee_receipt_allocations WHERE receipt_id = ?",
                (rec["id"],),
            )
            if trigger_sql and trigger_sql[0]:
                conn.execute(trigger_sql[0])
            conn.commit()
        with self.assertRaisesRegex(MigrationSchemaError, "FIN-009 data integrity"):
            validate_latest_schema(corrupt3)


if __name__ == "__main__":
    unittest.main()

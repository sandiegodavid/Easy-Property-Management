from __future__ import annotations

import tempfile
import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import unittest
from uuid import uuid4
from sqlalchemy import event, exc, text
from fastapi.testclient import TestClient

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.finance.application.service import FinanceService, _boundary_extension_piece, _schedule
from app.modules.finance.application.prepaid_check_service import PrepaidCheckService
from app.modules.finance.application.deposit_service import DepositService
from app.modules.finance.infrastructure.deposit_unit_of_work import SQLiteDepositUnitOfWork
from app.modules.finance.domain.deposit_models import DeductionCommand, DepositAccountCreateCommand, DepositReceiptCommand, DepositRefundCommand, SettlementCreateCommand, signed_money
from app.modules.finance.api.router import ExpectationResponse
from app.modules.finance.api.deposit_router import DepositResponse, ReceiptResponse, SettlementResponse
from app.modules.finance.application.ports import LeaseTermFinanceSnapshot
from app.modules.finance.domain.models import FinanceConflictError, FinanceError, PrepaidCheckCommand, PrepaidCheckTransitionCommand, RecordReceiptCommand, ReceiptAllocationCommand, RentExpectation, RentReceipt, SynchronizeExpectationsCommand, VoidCommand
from app.modules.finance.infrastructure.unit_of_work import SQLiteFinanceUnitOfWork
from app.modules.leases.application.service import LeaseCreateCommand, LeaseService, ParticipantCommand, TermCommand
from app.modules.leases.infrastructure.context_reader import SQLiteLeaseContextReader
from app.modules.leases.infrastructure.unit_of_work import SQLiteLeaseUnitOfWork
from app.modules.parties.application.service import SharedPartyFactory
from app.modules.parties.infrastructure.unit_of_work import SQLitePartyOperations, SQLitePartyReadOperations
from app.modules.portfolio.application.service import OwnershipInput, PortfolioService, PropertyCreateCommand
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioLeaseOperations, SQLitePortfolioUnitOfWork
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.tenants.application.service import TenantCreateCommand, TenantService
from app.modules.tenants.infrastructure.unit_of_work import SQLiteTenantProfileAvailability, SQLiteTenantUnitOfWork
from app.modules.leases.infrastructure.unit_of_work import SQLiteLeaseParticipationGuard
from app.modules.tasks.infrastructure.transaction_operations import SQLiteTaskTransactionOperations
from app.modules.inspections.infrastructure.context_reader import SQLiteInspectionContextReader
from app.modules.files.application.service import FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.modules.files.infrastructure.file_link_reader import SQLiteFileLinkReader
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.finance.application.deposit_file_links import DepositFileLinkValidator
from app.modules.finance.infrastructure.deposit_file_links import SQLiteDepositFileLinkOperations
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.config import LocalConfig
from app.platform.product_migrations import ProductSchemaError, validate_latest_schema
from app.bootstrap.api import create_app


class FinanceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); root=Path(self.temp.name)
        self.config = root / "config.json"
        self.config.write_text(json.dumps({"localWorkspacePath": str(root / "workspace")}), encoding="utf-8")
        self.workspace=WorkspaceService(LocalConfig(self.config,root/"workspace")); self.workspace.initialize(); db=self.workspace.paths.database
        recorder=AuditRecorder(SQLiteAuditRepository(db)); party_operations=SQLitePartyOperations(db)
        portfolio=PortfolioService(SQLitePortfolioUnitOfWork(db,recorder),time_zone_resolver=BundledAddressTimeZoneResolver())
        property_record=portfolio.create_property(PropertyCreateCommand("Rent home","1 Main Street","Portland","US","single_family_home",(OwnershipInput("local_operator"),),region="OR")); space_id=portfolio.get_property(property_record.id)["spaces"][0]["id"]
        tenant=TenantService(SQLiteTenantUnitOfWork(db,recorder,SQLiteLeaseParticipationGuard(),party_operations,SQLitePartyReadOperations(party_operations)),SharedPartyFactory()).create(TenantCreateCommand("individual","Rent Tenant"))
        leases=LeaseService(SQLiteLeaseUnitOfWork(db,recorder,SQLiteTenantProfileAvailability(),SQLitePortfolioLeaseOperations(db)))
        today=date.today(); lease=leases.create(LeaseCreateCommand(space_id,"residential",today,today+timedelta(days=90),today,TermCommand(100_000,"USD","monthly",1,0),(ParticipantCommand(tenant["id"],"primary_tenant"),))); self.lease=leases.execute(lease["id"],executed_on=today,confirmed=True)
        self.finance=FinanceService(SQLiteFinanceUnitOfWork(db,recorder,SQLiteLeaseContextReader(),SQLitePortfolioContextReader(),party_operations),now=lambda:datetime.now(UTC))
        self.file_reader = SQLiteFileLinkReader()
        self.deposits=DepositService(SQLiteDepositUnitOfWork(db,recorder,SQLiteLeaseContextReader(),SQLitePortfolioContextReader(),party_operations,SQLiteInspectionContextReader(),self.file_reader),now=lambda:datetime.now(UTC))
        self.files = FileService(
            self.workspace, FilesystemContentStore(self.workspace.paths.files),
            SQLiteFileUnitOfWork(db, recorder),
            link_validators=(DepositFileLinkValidator(SQLiteDepositFileLinkOperations(self.file_reader)),),
        )

    def test_security_deposit_account_receipt_and_zero_settlement_lifecycle(self):
        term = self.lease["terms"][0]
        account = self.deposits.create_account(self.lease["id"], DepositAccountCreateCommand(term["id"]))
        DepositResponse.model_validate(account)
        receipt = self.deposits.record_receipt(account["id"], DepositReceiptCommand(
            str(uuid4()), date.today().isoformat(), "10.00", "USD", "local_operator",
            overage_confirmed=True, overage_reason="Correction deposit received",
        ))
        self.assertEqual(receipt["amount"], "10.00")
        ReceiptResponse.model_validate(receipt)
        # The draft lifecycle is auditable and its timing override is explicit.
        settlement = self.deposits.create_settlement(account["id"], SettlementCreateCommand(
            date.today().isoformat(), eligibility_override_confirmed=True,
            eligibility_override_reason="Early documented closure",
        ))
        self.assertEqual(settlement["status"], "draft")
        SettlementResponse.model_validate(settlement)

    def test_rejected_current_snapshot_does_not_query_rent_responsibility(self):
        term_id = self.lease["terms"][0]["id"]
        engine = self.finance.unit_of_work.engine
        with engine.begin() as connection:
            connection.execute(text("UPDATE leases SET status='draft', executed_on=NULL WHERE id=:id"), {"id": self.lease["id"]})
        statements = []
        def capture(*args):
            if args[2].lstrip().upper().startswith("SELECT"):
                statements.append(args[2])
        event.listen(engine, "before_cursor_execute", capture)
        try:
            self.assertIsNone(self.finance.unit_of_work.read(
                lambda tx: tx.lease_term_snapshot(self.lease["id"], term_id)
            ))
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        self.assertEqual(len(statements), 2)
        self.assertFalse(any("LEASE_TERMINATION" in statement.upper() for statement in statements))

    def test_historical_snapshot_batch_never_falls_back_to_single_space_reads(self):
        term_id = self.lease["terms"][0]["id"]
        unit_of_work = self.finance.unit_of_work
        original_portfolio = unit_of_work.portfolio_operations

        class MissingBatchPortfolioContext:
            single_reads = 0
            def contexts_for_spaces(self, connection, space_ids): return {}
            def context_for_space(self, connection, space_id):
                self.single_reads += 1
                raise AssertionError("batch snapshots must not use single-space reads")

        missing_context = MissingBatchPortfolioContext()
        unit_of_work.portfolio_operations = missing_context
        statements = []
        def capture(*args):
            if args[2].lstrip().upper().startswith("SELECT"):
                statements.append(args[2])
        event.listen(unit_of_work.engine, "before_cursor_execute", capture)
        try:
            snapshots = unit_of_work.read(
                lambda tx: tx.historical_term_snapshots([(self.lease["id"], term_id)])
            )
        finally:
            event.remove(unit_of_work.engine, "before_cursor_execute", capture)
            unit_of_work.portfolio_operations = original_portfolio
        self.assertEqual(snapshots, {})
        self.assertEqual(missing_context.single_reads, 0)
        self.assertEqual(len(statements), 3)

    def test_deduction_evidence_must_be_available_and_archived_before_deletion(self):
        term = self.lease["terms"][0]
        account = self.deposits.create_account(self.lease["id"], DepositAccountCreateCommand(term["id"]))
        settlement = self.deposits.create_settlement(
            account["id"], SettlementCreateCommand(
                date.today().isoformat(), eligibility_override_confirmed=True,
                eligibility_override_reason="Documented test closure",
            ),
        )
        deduction = self.deposits.add_deduction(
            settlement["id"], DeductionCommand("damage", "1.00", "Wall repair", "Photo evidence"),
        )
        source = Path(self.temp.name) / "damage-photo.txt"
        source.write_bytes(b"damage")
        stored = self.files.add(
            source, source.name, "text/plain", entity_type="security_deposit_deduction",
            entity_id=deduction["id"], purpose="supporting_document",
        )
        link_id = self.files.get(stored.id).links[0]["id"]
        with self.assertRaisesRegex(FinanceConflictError, "Archive deduction evidence"):
            self.deposits.delete_deduction(deduction["id"])

        with self.files.unit_of_work.engine.begin() as connection:
            connection.execute(text(
                "UPDATE file_content_locations SET storage_state='quarantined' WHERE file_id=:id"
            ), {"id": stored.id})
        with self.assertRaisesRegex(FinanceConflictError, "requires at least one source"):
            self.deposits.approve_settlement(
                settlement["id"], True, zero_dollar_closure_confirmed=True,
            )

        self.files.archive_link(link_id, confirmed=True, reason="Evidence was attached in error.")
        self.assertEqual(self.deposits.delete_deduction(deduction["id"]), {
            "deleted": True, "id": deduction["id"],
        })

    def test_prepaid_check_deposit_is_correlated_with_one_expectation(self):
        term = self.lease["terms"][0]
        expectations = self.finance.synchronize(self.lease["id"], SynchronizeExpectationsCommand(
            term["id"], (date.today() + timedelta(days=60)).isoformat(), date.today().replace(day=1).isoformat(),
        ))
        expectation = next(item for item in expectations if not item["isProrated"])
        db = self.workspace.paths.database
        clock = lambda: datetime.combine(date.today() + timedelta(days=2), datetime.min.time(), UTC)
        prepaid = PrepaidCheckService(SQLiteFinanceUnitOfWork(
            db, AuditRecorder(SQLiteAuditRepository(db)),
            SQLiteLeaseContextReader(), SQLitePortfolioContextReader(), SQLitePartyOperations(db),
            SQLiteTaskTransactionOperations(),
        ), now=clock)
        check = prepaid.create(PrepaidCheckCommand(
            expectation["id"], self.lease["participants"][0]["tenantPartyId"], date.today().isoformat(),
            (date.today() + timedelta(days=1)).isoformat(), "Check •••• 1234", str(uuid4()),
        ))
        self.assertEqual(check["depositEligibility"], "eligible")
        deposited = prepaid.deposit(check["id"], PrepaidCheckTransitionCommand(str(uuid4()), True))
        self.assertEqual(deposited["status"], "deposited")
        self.assertIsNotNone(deposited["receiptId"])
        self.assertEqual(self.finance.expectation(expectation["id"])["settlementStatus"], "paid")
        with TestClient(create_app(self.config)) as client:
            response = client.get(f"/api/prepaid-checks/{check['id']}")
            malformed = client.get("/api/prepaid-checks/not-a-uuid")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["receiptId"], deposited["receiptId"])
        self.assertEqual(malformed.status_code, 422)

    def test_voided_prepaid_check_can_be_replaced_once(self):
        term = self.lease["terms"][0]
        expectations = self.finance.synchronize(self.lease["id"], SynchronizeExpectationsCommand(
            term["id"], (date.today() + timedelta(days=60)).isoformat(), date.today().replace(day=1).isoformat(),
        ))
        expectation = next(item for item in expectations if not item["isProrated"])
        db = self.workspace.paths.database
        prepaid = PrepaidCheckService(SQLiteFinanceUnitOfWork(
            db, AuditRecorder(SQLiteAuditRepository(db)),
            SQLiteLeaseContextReader(), SQLitePortfolioContextReader(), SQLitePartyOperations(db), SQLiteTaskTransactionOperations(),
        ))
        check = prepaid.create(PrepaidCheckCommand(
            expectation["id"], self.lease["participants"][0]["tenantPartyId"], date.today().isoformat(),
            (date.today() + timedelta(days=3)).isoformat(), None, str(uuid4()),
        ))
        prepaid.void(check["id"], PrepaidCheckTransitionCommand(str(uuid4()), True, "Replacement check received"))
        replacement = prepaid.replace(check["id"], PrepaidCheckCommand(
            expectation["id"], self.lease["participants"][0]["tenantPartyId"], date.today().isoformat(),
            (date.today() + timedelta(days=4)).isoformat(), None, str(uuid4()),
        ), confirmed=True, reason="Replacement check issued")
        self.assertEqual(replacement["status"], "scheduled")
        self.assertEqual(prepaid.get(check["id"])["status"], "replaced")

    def test_prepaid_check_rejects_prorated_expectations_and_requires_explicit_replacement(self):
        term = self.lease["terms"][0]
        expectations = self.finance.synchronize(self.lease["id"], SynchronizeExpectationsCommand(
            term["id"], (date.today() + timedelta(days=60)).isoformat(), date.today().replace(day=1).isoformat(),
        ))
        prorated = next(item for item in expectations if item["isProrated"])
        complete = next(item for item in expectations if not item["isProrated"])
        prepaid = PrepaidCheckService(SQLiteFinanceUnitOfWork(
            self.workspace.paths.database, AuditRecorder(SQLiteAuditRepository(self.workspace.paths.database)),
            SQLiteLeaseContextReader(), SQLitePortfolioContextReader(), SQLitePartyOperations(self.workspace.paths.database), SQLiteTaskTransactionOperations(),
        ))
        with self.assertRaises(FinanceConflictError):
            prepaid.create(PrepaidCheckCommand(prorated["id"], self.lease["participants"][0]["tenantPartyId"], date.today().isoformat(), (date.today() + timedelta(days=2)).isoformat(), None, str(uuid4())))
        check = prepaid.create(PrepaidCheckCommand(complete["id"], self.lease["participants"][0]["tenantPartyId"], date.today().isoformat(), (date.today() + timedelta(days=2)).isoformat(), None, str(uuid4())))
        prepaid.void(check["id"], PrepaidCheckTransitionCommand(str(uuid4()), True, "Printed check was spoiled"))
        with self.assertRaises(FinanceConflictError):
            prepaid.create(PrepaidCheckCommand(complete["id"], self.lease["participants"][0]["tenantPartyId"], date.today().isoformat(), (date.today() + timedelta(days=3)).isoformat(), None, str(uuid4())))
        replacement = prepaid.replace(check["id"], PrepaidCheckCommand(complete["id"], self.lease["participants"][0]["tenantPartyId"], date.today().isoformat(), (date.today() + timedelta(days=3)).isoformat(), None, str(uuid4())), confirmed=True, reason="A corrected printed check was received")
        self.assertEqual(replacement["reminderStatus"], "pending")
        self.assertEqual(prepaid.get(check["id"])["replacementReason"], "A corrected printed check was received")

    def test_prepaid_check_can_adopt_one_compatible_existing_receipt(self):
        term = self.lease["terms"][0]
        expectations = self.finance.synchronize(self.lease["id"], SynchronizeExpectationsCommand(
            term["id"], (date.today() + timedelta(days=60)).isoformat(), date.today().replace(day=1).isoformat(),
        ))
        expectation = next(item for item in expectations if not item["isProrated"])
        clock = lambda: datetime.combine(date.today() + timedelta(days=2), datetime.min.time(), UTC)
        prepaid = PrepaidCheckService(SQLiteFinanceUnitOfWork(
            self.workspace.paths.database, AuditRecorder(SQLiteAuditRepository(self.workspace.paths.database)),
            SQLiteLeaseContextReader(), SQLitePortfolioContextReader(), SQLitePartyOperations(self.workspace.paths.database), SQLiteTaskTransactionOperations(),
        ), now=clock)
        check = prepaid.create(PrepaidCheckCommand(
            expectation["id"], self.lease["participants"][0]["tenantPartyId"], date.today().isoformat(),
            (date.today() + timedelta(days=1)).isoformat(), "Check •••• 4321", str(uuid4()),
        ))
        receipt = self.finance.record_receipt(RecordReceiptCommand(
            self.lease["id"], str(uuid4()), date.today().isoformat(), expectation["expectedAmountMinor"], "USD",
            (ReceiptAllocationCommand(expectation["id"], expectation["expectedAmountMinor"]),), "check",
        ))
        deposited = prepaid.deposit(check["id"], PrepaidCheckTransitionCommand(str(uuid4()), True, existing_receipt_id=receipt["id"]))
        self.assertEqual(deposited["receiptId"], receipt["id"])

    def test_prepaid_check_restore_rejects_one_way_replacement_lineage(self):
        term = self.lease["terms"][0]
        expectations = self.finance.synchronize(self.lease["id"], SynchronizeExpectationsCommand(
            term["id"], (date.today() + timedelta(days=60)).isoformat(), date.today().replace(day=1).isoformat(),
        ))
        expectation = next(item for item in expectations if not item["isProrated"])
        prepaid = PrepaidCheckService(SQLiteFinanceUnitOfWork(
            self.workspace.paths.database, AuditRecorder(SQLiteAuditRepository(self.workspace.paths.database)),
            SQLiteLeaseContextReader(), SQLitePortfolioContextReader(), SQLitePartyOperations(self.workspace.paths.database), SQLiteTaskTransactionOperations(),
        ))
        original = prepaid.create(PrepaidCheckCommand(expectation["id"], self.lease["participants"][0]["tenantPartyId"], date.today().isoformat(), (date.today() + timedelta(days=2)).isoformat(), None, str(uuid4())))
        prepaid.void(original["id"], PrepaidCheckTransitionCommand(str(uuid4()), True, "Spoiled"))
        prepaid.replace(original["id"], PrepaidCheckCommand(expectation["id"], self.lease["participants"][0]["tenantPartyId"], date.today().isoformat(), (date.today() + timedelta(days=3)).isoformat(), None, str(uuid4())), confirmed=True, reason="Reissued")
        connection = sqlite3.connect(self.workspace.paths.database)
        try:
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute("UPDATE prepaid_checks SET status = 'voided', replaced_by_prepaid_check_id = NULL, replacement_reason = NULL WHERE id = ?", (original["id"],))
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.workspace.paths.database)

    def test_signed_deposit_variance_is_not_distorted_for_underfunded_accounts(self):
        self.assertEqual(signed_money(-1), "-0.01")
        self.assertEqual(signed_money(-50), "-0.50")
        self.assertEqual(signed_money(-100), "-1.00")
        self.assertEqual(signed_money(-12_345), "-123.45")

    def test_account_reload_includes_the_current_settlement_state(self):
        term = self.lease["terms"][0]
        account = self.deposits.create_account(self.lease["id"], DepositAccountCreateCommand(term["id"]))
        settlement = self.deposits.create_settlement(account["id"], SettlementCreateCommand(
            date.today().isoformat(), eligibility_override_confirmed=True,
            eligibility_override_reason="Early documented closure",
        ))
        reloaded = self.deposits.account_for_lease(self.lease["id"])
        self.assertEqual(reloaded["settlementId"], settlement["id"])
        self.assertEqual(reloaded["settlementStatus"], "draft")
        self.assertIn(reloaded["deadlineState"], {"due", "due_today", "overdue"})
        self.assertTrue(reloaded["unresolvedBalance"])

    def test_later_source_lifecycle_changes_warn_without_invalidating_approval(self):
        term = self.lease["terms"][0]
        expectation = self.finance.synchronize(self.lease["id"], SynchronizeExpectationsCommand(
            term["id"], (date.today() + timedelta(days=60)).isoformat(), date.today().replace(day=1).isoformat(),
        ))[0]
        account = self.deposits.create_account(self.lease["id"], DepositAccountCreateCommand(term["id"]))
        self.deposits.record_receipt(account["id"], DepositReceiptCommand(
            str(uuid4()), date.today().isoformat(), "1.00", "USD", "local_operator",
            overage_confirmed=True, overage_reason="Documented receipt",
        ))
        settlement = self.deposits.create_settlement(account["id"], SettlementCreateCommand(
            date.today().isoformat(), eligibility_override_confirmed=True,
            eligibility_override_reason="Early documented closure",
        ))
        deduction = self.deposits.add_deduction(settlement["id"], DeductionCommand("unpaid_rent", "1.00", "Rent", "Review"))
        source = self.deposits.add_deduction_source(deduction["id"], "rent_expectation", expectation["id"])
        approved = self.deposits.approve_settlement(settlement["id"], True)
        self.finance.void_expectation(expectation["id"], VoidCommand(True, "Corrected rent expectation"))
        validate_latest_schema(self.workspace.paths.database)
        detail = self.deposits.settlement(approved["id"])
        self.assertIn(f"historical_source:{source['id']}", detail["sourceWarnings"])

    def test_completed_settlement_refund_must_be_corrected_through_settlement_replacement(self):
        term = self.lease["terms"][0]
        account = self.deposits.create_account(self.lease["id"], DepositAccountCreateCommand(term["id"]))
        self.deposits.record_receipt(account["id"], DepositReceiptCommand(
            str(uuid4()), date.today().isoformat(), "1.00", "USD", "local_operator",
            overage_confirmed=True, overage_reason="Documented receipt",
        ))
        settlement = self.deposits.create_settlement(account["id"], SettlementCreateCommand(
            date.today().isoformat(), eligibility_override_confirmed=True,
            eligibility_override_reason="Early documented closure",
        ))
        approved = self.deposits.approve_settlement(settlement["id"], True)
        refund = self.deposits.record_refund(approved["id"], DepositRefundCommand(
            str(uuid4()), self.lease["participants"][0]["tenantPartyId"], date.today().isoformat(), "1.00", "USD",
        ))
        self.deposits.complete_settlement(approved["id"], False)
        with self.assertRaises(FinanceConflictError):
            self.deposits.void_refund(refund["id"], VoidCommand(True, "Incorrect payment"))

    def test_rent_expectation_source_snapshots_active_outstanding_balance(self):
        term = self.lease["terms"][0]
        expectation = self.finance.synchronize(
            self.lease["id"],
            SynchronizeExpectationsCommand(term["id"], (date.today() + timedelta(days=60)).isoformat(), date.today().replace(day=1).isoformat()),
        )[0]
        self.finance.record_receipt(RecordReceiptCommand(
            self.lease["id"], str(uuid4()), date.today().isoformat(), expectation["expectedAmountMinor"], "USD",
            (ReceiptAllocationCommand(expectation["id"], expectation["expectedAmountMinor"]),),
            "cash",
        ))
        account = self.deposits.create_account(self.lease["id"], DepositAccountCreateCommand(term["id"]))
        settlement = self.deposits.create_settlement(account["id"], SettlementCreateCommand(
            date.today().isoformat(), eligibility_override_confirmed=True, eligibility_override_reason="Early documented closure",
        ))
        deduction = self.deposits.add_deduction(settlement["id"], DeductionCommand("unpaid_rent", "1.00", "Rent", "Review"))
        source = self.deposits.add_deduction_source(deduction["id"], "rent_expectation", expectation["id"])
        self.assertEqual(source["outstandingAmount"], "0.00")

    def test_restore_validation_rejects_orphaned_deposit_foreign_key(self):
        raw = self.finance.unit_of_work.engine.raw_connection()
        try:
            raw.execute("PRAGMA foreign_keys = OFF")
            raw.execute("INSERT INTO security_deposit_accounts (id, lease_id, lease_term_id, property_id, space_id, agreed_amount_minor, currency_code, created_at, updated_at) VALUES ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000005', 0, 'USD', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')")
            raw.commit()
        finally:
            raw.close()
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.workspace.paths.database)

    def test_zero_dollar_closure_requires_distinct_approval_confirmation(self):
        term = self.lease["terms"][0]
        account = self.deposits.create_account(self.lease["id"], DepositAccountCreateCommand(term["id"]))
        settlement = self.deposits.create_settlement(account["id"], SettlementCreateCommand(
            date.today().isoformat(), eligibility_override_confirmed=True,
            eligibility_override_reason="Early documented closure",
        ))
        with self.assertRaises(FinanceConflictError):
            self.deposits.approve_settlement(settlement["id"], True)
        approved = self.deposits.approve_settlement(
            settlement["id"], True, zero_dollar_closure_confirmed=True,
        )
        self.assertEqual(approved["status"], "approved")
        completed = self.deposits.complete_settlement(approved["id"], True)
        self.assertEqual(completed["status"], "completed")

    def test_empty_settlement_requires_zero_dollar_confirmation_when_deposit_was_expected(self):
        term = self.lease["terms"][0]
        with self.finance.unit_of_work.engine.begin() as connection:
            connection.execute(text(
                "UPDATE lease_term_versions SET agreed_security_deposit_minor = 10000 WHERE id = :id"
            ), {"id": term["id"]})
        account = self.deposits.create_account(self.lease["id"], DepositAccountCreateCommand(term["id"]))
        settlement = self.deposits.create_settlement(account["id"], SettlementCreateCommand(
            date.today().isoformat(), eligibility_override_confirmed=True,
            eligibility_override_reason="Early documented closure",
        ))
        with self.assertRaises(FinanceConflictError):
            self.deposits.approve_settlement(settlement["id"], True)
        approved = self.deposits.approve_settlement(
            settlement["id"], True, zero_dollar_closure_confirmed=True,
        )
        self.assertEqual(approved["receiptTotal"], "0.00")

    def test_deposit_receipt_and_refund_checks_reject_voids_without_reasons(self):
        term = self.lease["terms"][0]
        account = self.deposits.create_account(self.lease["id"], DepositAccountCreateCommand(term["id"]))
        receipt = self.deposits.record_receipt(account["id"], DepositReceiptCommand(
            str(uuid4()), date.today().isoformat(), "1.00", "USD", "local_operator",
            overage_confirmed=True, overage_reason="Documented receipt",
        ))
        settlement = self.deposits.create_settlement(account["id"], SettlementCreateCommand(
            date.today().isoformat(), eligibility_override_confirmed=True,
            eligibility_override_reason="Early documented closure",
        ))
        approved = self.deposits.approve_settlement(settlement["id"], True)
        recipient_id = self.lease["participants"][0]["tenantPartyId"]
        refund = self.deposits.record_refund(approved["id"], DepositRefundCommand(
            str(uuid4()), recipient_id, date.today().isoformat(), "1.00", "USD",
        ))
        with self.assertRaises(exc.IntegrityError):
            with self.finance.unit_of_work.engine.begin() as connection:
                connection.execute(text(
                    "UPDATE security_deposit_receipts SET voided_at = :stamp, void_reason = NULL WHERE id = :id"
                ), {"id": receipt["id"], "stamp": datetime.now(UTC).isoformat()})
        with self.assertRaises(exc.IntegrityError):
            with self.finance.unit_of_work.engine.begin() as connection:
                connection.execute(text(
                    "UPDATE security_deposit_refunds SET voided_at = :stamp, void_reason = NULL WHERE id = :id"
                ), {"id": refund["id"], "stamp": datetime.now(UTC).isoformat()})

    def test_deposit_database_rejects_invalid_persisted_dates_and_aggregate_amounts(self):
        term = self.lease["terms"][0]
        account = self.deposits.create_account(self.lease["id"], DepositAccountCreateCommand(term["id"]))
        receipt = self.deposits.record_receipt(account["id"], DepositReceiptCommand(
            str(uuid4()), date.today().isoformat(), "1.00", "USD", "local_operator",
            overage_confirmed=True, overage_reason="Documented receipt",
        ))
        settlement = self.deposits.create_settlement(account["id"], SettlementCreateCommand(
            date.today().isoformat(), eligibility_override_confirmed=True,
            eligibility_override_reason="Early documented closure",
        ))
        with self.assertRaises(exc.IntegrityError):
            with self.finance.unit_of_work.engine.begin() as connection:
                connection.execute(text(
                    "UPDATE security_deposit_receipts SET received_on = '1899-12-31' WHERE id = :id"
                ), {"id": receipt["id"]})
        with self.assertRaises(exc.IntegrityError):
            with self.finance.unit_of_work.engine.begin() as connection:
                connection.execute(text(
                    "UPDATE security_deposit_settlements SET settlement_due_on = '2026-02-30' WHERE id = :id"
                ), {"id": settlement["id"]})
        with self.assertRaises(exc.IntegrityError):
            with self.finance.unit_of_work.engine.begin() as connection:
                connection.execute(text(
                    "UPDATE security_deposit_settlements SET receipt_total_minor = 10000000000, credit_total_minor = 0, deduction_total_minor = 0, refund_due_minor = 10000000000, approved_at = :stamp WHERE id = :id"
                ), {"id": settlement["id"], "stamp": datetime.now(UTC).isoformat()})

    def test_restore_rejects_removed_receipt_capture_from_voided_approved_settlement(self):
        term = self.lease["terms"][0]
        account = self.deposits.create_account(self.lease["id"], DepositAccountCreateCommand(term["id"]))
        self.deposits.record_receipt(account["id"], DepositReceiptCommand(
            str(uuid4()), date.today().isoformat(), "1.00", "USD", "local_operator",
            overage_confirmed=True, overage_reason="Documented receipt",
        ))
        settlement = self.deposits.create_settlement(account["id"], SettlementCreateCommand(
            date.today().isoformat(), eligibility_override_confirmed=True,
            eligibility_override_reason="Early documented closure",
        ))
        approved = self.deposits.approve_settlement(settlement["id"], True)
        self.deposits.void_settlement(approved["id"], VoidCommand(True, "Settlement correction"))
        with self.finance.unit_of_work.engine.begin() as connection:
            connection.execute(text(
                "DELETE FROM security_deposit_settlement_receipts WHERE settlement_id = :id"
            ), {"id": approved["id"]})
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.workspace.paths.database)

    def test_restore_rejects_missing_rent_snapshot_from_voided_approved_settlement(self):
        term = self.lease["terms"][0]
        expectation = self.finance.synchronize(
            self.lease["id"],
            SynchronizeExpectationsCommand(
                term["id"], (date.today() + timedelta(days=60)).isoformat(),
                date.today().replace(day=1).isoformat(),
            ),
        )[0]
        account = self.deposits.create_account(self.lease["id"], DepositAccountCreateCommand(term["id"]))
        self.deposits.record_receipt(account["id"], DepositReceiptCommand(
            str(uuid4()), date.today().isoformat(), "1.00", "USD", "local_operator",
            overage_confirmed=True, overage_reason="Documented receipt",
        ))
        settlement = self.deposits.create_settlement(account["id"], SettlementCreateCommand(
            date.today().isoformat(), eligibility_override_confirmed=True,
            eligibility_override_reason="Early documented closure",
        ))
        deduction = self.deposits.add_deduction(
            settlement["id"], DeductionCommand("unpaid_rent", "1.00", "Rent", "Review"),
        )
        source = self.deposits.add_deduction_source(
            deduction["id"], "rent_expectation", expectation["id"],
        )
        approved = self.deposits.approve_settlement(settlement["id"], True)
        self.deposits.void_settlement(approved["id"], VoidCommand(True, "Settlement correction"))
        with self.finance.unit_of_work.engine.begin() as connection:
            connection.execute(text(
                "UPDATE security_deposit_deduction_sources SET outstanding_amount_minor = NULL WHERE id = :id"
            ), {"id": source["id"]})
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.workspace.paths.database)

    def test_restore_rejects_removed_source_from_voided_approved_deduction(self):
        term = self.lease["terms"][0]
        expectation = self.finance.synchronize(
            self.lease["id"],
            SynchronizeExpectationsCommand(
                term["id"], (date.today() + timedelta(days=60)).isoformat(),
                date.today().replace(day=1).isoformat(),
            ),
        )[0]
        account = self.deposits.create_account(self.lease["id"], DepositAccountCreateCommand(term["id"]))
        self.deposits.record_receipt(account["id"], DepositReceiptCommand(
            str(uuid4()), date.today().isoformat(), "1.00", "USD", "local_operator",
            overage_confirmed=True, overage_reason="Documented receipt",
        ))
        settlement = self.deposits.create_settlement(account["id"], SettlementCreateCommand(
            date.today().isoformat(), eligibility_override_confirmed=True,
            eligibility_override_reason="Early documented closure",
        ))
        deduction = self.deposits.add_deduction(
            settlement["id"], DeductionCommand("unpaid_rent", "1.00", "Rent", "Review"),
        )
        source = self.deposits.add_deduction_source(
            deduction["id"], "rent_expectation", expectation["id"],
        )
        approved = self.deposits.approve_settlement(settlement["id"], True)
        self.deposits.void_settlement(approved["id"], VoidCommand(True, "Settlement correction"))
        with self.finance.unit_of_work.engine.begin() as connection:
            connection.execute(text(
                "DELETE FROM security_deposit_deduction_sources WHERE id = :id"
            ), {"id": source["id"]})
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.workspace.paths.database)

    def test_restore_rejects_unconfirmed_expense_reuse_across_approved_settlements(self):
        term = self.lease["terms"][0]
        account = self.deposits.create_account(self.lease["id"], DepositAccountCreateCommand(term["id"]))
        self.deposits.record_receipt(account["id"], DepositReceiptCommand(
            str(uuid4()), date.today().isoformat(), "2.00", "USD", "local_operator",
            overage_confirmed=True, overage_reason="Documented receipt",
        ))
        expense_id = str(uuid4())
        stamp = datetime.now(UTC).isoformat()
        with self.finance.unit_of_work.engine.begin() as connection:
            category_id = connection.execute(text(
                "SELECT id FROM expense_categories WHERE archived_at IS NULL ORDER BY display_order, id LIMIT 1"
            )).scalar_one()
            connection.execute(text(
                """INSERT INTO expenses (
                    id, idempotency_key, request_fingerprint, property_id, space_id,
                    category_id, provider_party_id, payee_name, paid_by_kind,
                    paid_by_party_id, paid_on, amount_minor, currency_code, description,
                    reference, notes, replaces_expense_id, voided_at, void_reason,
                    created_at, updated_at
                ) VALUES (
                    :id, :key, :fingerprint, :property_id, :space_id,
                    :category_id, NULL, 'Repair shop', 'local_operator',
                    NULL, :paid_on, 100, 'USD', 'Repair expense',
                    NULL, NULL, NULL, NULL, NULL, :stamp, :stamp
                )"""
            ), {
                "id": expense_id, "key": str(uuid4()), "fingerprint": "a" * 64,
                "property_id": account["propertyId"], "space_id": account["spaceId"],
                "category_id": category_id, "paid_on": date.today().isoformat(), "stamp": stamp,
            })

        def settlement(replaces_settlement_id=None, *, duplicate_use_confirmed=False):
            item = self.deposits.create_settlement(account["id"], SettlementCreateCommand(
                date.today().isoformat(), eligibility_override_confirmed=True,
                eligibility_override_reason="Early documented closure",
                replaces_settlement_id=replaces_settlement_id,
            ))
            deduction = self.deposits.add_deduction(
                item["id"], DeductionCommand("damage", "1.00", "Repair", "Documented cost"),
            )
            source = self.deposits.add_deduction_source(
                deduction["id"], "expense", expense_id,
                duplicate_use_confirmed=duplicate_use_confirmed,
            )
            return self.deposits.approve_settlement(item["id"], True), source

        first, _ = settlement()
        self.deposits.void_settlement(first["id"], VoidCommand(True, "Settlement correction"))
        _, repeated_source = settlement(first["id"], duplicate_use_confirmed=True)
        validate_latest_schema(self.workspace.paths.database)
        with self.finance.unit_of_work.engine.begin() as connection:
            connection.execute(text(
                "UPDATE security_deposit_deduction_sources SET duplicate_use_confirmed = 0 WHERE id = :id"
            ), {"id": repeated_source["id"]})
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.workspace.paths.database)

    def test_security_deposit_http_responses_validate_the_persisted_detail_shape(self):
        term = self.lease["terms"][0]
        account = self.deposits.create_account(self.lease["id"], DepositAccountCreateCommand(term["id"]))
        settlement = self.deposits.create_settlement(
            account["id"],
            SettlementCreateCommand(
                date.today().isoformat(),
                eligibility_override_confirmed=True,
                eligibility_override_reason="Early documented closure",
            ),
        )
        deduction = self.deposits.add_deduction(
            settlement["id"],
            DeductionCommand("damage", "1.00", "Wall repair", "Inspection estimate"),
        )
        recorded = self.deposits.record_receipt(account["id"], DepositReceiptCommand(
            str(uuid4()), date.today().isoformat(), "2.00", "USD", "local_operator",
            overage_confirmed=True, overage_reason="Documented receipt",
        ))
        with TestClient(create_app(self.workspace.config.config_path)) as client:
            account_response = client.get("/api/security-deposits")
            lease_account_response = client.get(f"/api/leases/{self.lease['id']}/security-deposit")
            detail_response = client.get(f"/api/security-deposit-settlements/{settlement['id']}")
            receipts_response = client.get(f"/api/security-deposits/{account['id']}/receipts")
            deduction_response = client.patch(
                f"/api/security-deposit-deductions/{deduction['id']}",
                json={"category": "damage", "amount": "1.00", "description": "Wall repair", "rationale": "Inspection estimate"},
            )
        self.assertEqual(account_response.status_code, 200, account_response.text)
        self.assertEqual(lease_account_response.status_code, 200, lease_account_response.text)
        self.assertEqual(detail_response.status_code, 200, detail_response.text)
        self.assertEqual(receipts_response.status_code, 200, receipts_response.text)
        self.assertEqual(deduction_response.status_code, 200, deduction_response.text)
        self.assertEqual(receipts_response.json()[0]["id"], recorded["id"])
        self.assertEqual(lease_account_response.json()["settlementId"], settlement["id"])
        self.assertEqual(detail_response.json()["deductions"][0]["sources"], [])
        self.assertEqual(detail_response.json()["deductions"][0]["evidence"], [])
    def test_synchronize_is_idempotent_and_receipt_settles_expectation(self):
        term=self.lease["terms"][0]; command=SynchronizeExpectationsCommand(term["id"],(date.today()+timedelta(days=60)).isoformat(),date.today().replace(day=1).isoformat())
        rows=self.finance.synchronize(self.lease["id"],command); self.assertTrue(rows); self.assertEqual([],self.finance.synchronize(self.lease["id"],command))
        expectation=rows[0]; receipt=self.finance.record_receipt(RecordReceiptCommand(self.lease["id"],str(uuid4()),date.today().isoformat(),expectation["expectedAmountMinor"],"USD",(ReceiptAllocationCommand(expectation["id"],expectation["expectedAmountMinor"]),),"cash"))
        self.assertEqual(receipt["allocations"][0]["expectationId"],expectation["id"])
        view = self.finance.expectation(expectation["id"])
        self.assertEqual(view["settlementStatus"],"paid")
        self.assertEqual(view["allocationSummaries"][0]["receiptId"], receipt["id"])
        self.assertEqual(view["allocationSummaries"][0]["receiptLifecycleStatus"], "active")
        self.assertNotIn("voidedAt", view["allocationSummaries"][0])
        ExpectationResponse.model_validate(view)
        self.finance.void_receipt(receipt["id"], VoidCommand(True, "Correction"))
        voided = self.finance.void_expectation(expectation["id"], VoidCommand(True, "Duplicate"))
        self.assertEqual(voided["allocationCount"], 1)
        self.assertEqual(voided["allocationSummaries"][0]["receiptLifecycleStatus"], "voided")

    def test_receipt_payment_method_is_immutable_and_idempotency_sensitive(self):
        term = self.lease["terms"][0]
        expectation = self.finance.synchronize(
            self.lease["id"],
            SynchronizeExpectationsCommand(
                term["id"], (date.today() + timedelta(days=60)).isoformat(),
                date.today().replace(day=1).isoformat(),
            ),
        )[0]
        key = str(uuid4())
        command = RecordReceiptCommand(
            self.lease["id"], key, date.today().isoformat(),
            expectation["expectedAmountMinor"], "USD",
            (ReceiptAllocationCommand(expectation["id"], expectation["expectedAmountMinor"]),),
            "check", "Personal check", "Check •••• 9182",
        )
        receipt = self.finance.record_receipt(command)
        self.assertEqual(receipt["paymentMethodKind"], "check")
        self.assertEqual(receipt["maskedReference"], "Check •••• 9182")
        self.assertEqual(self.finance.record_receipt(command)["id"], receipt["id"])
        with self.assertRaises(FinanceConflictError):
            self.finance.record_receipt(RecordReceiptCommand(
                self.lease["id"], key, date.today().isoformat(),
                expectation["expectedAmountMinor"], "USD",
                (ReceiptAllocationCommand(expectation["id"], expectation["expectedAmountMinor"]),),
                "cash",
            ))

    def test_payment_method_validation_and_suggestion_route(self):
        with self.assertRaises(FinanceError):
            RecordReceiptCommand(
                self.lease["id"], str(uuid4()), date.today().isoformat(), 100, "USD",
                (ReceiptAllocationCommand(str(uuid4()), 100),), "other",
            )
        with self.assertRaises(FinanceError):
            RecordReceiptCommand(
                self.lease["id"], str(uuid4()), date.today().isoformat(), 100, "USD",
                (ReceiptAllocationCommand(str(uuid4()), 100),), "bank_transfer",
                masked_reference="123456789",
            )
        with TestClient(create_app(self.workspace.config.config_path)) as client:
            empty = client.get(f"/api/leases/{self.lease['id']}/rent-receipts/payment-method-suggestion")
        self.assertEqual(empty.status_code, 204, empty.text)
        term = self.lease["terms"][0]
        expectation = self.finance.synchronize(
            self.lease["id"],
            SynchronizeExpectationsCommand(
                term["id"], (date.today() + timedelta(days=60)).isoformat(),
                date.today().replace(day=1).isoformat(),
            ),
        )[0]
        self.finance.record_receipt(RecordReceiptCommand(
            self.lease["id"], str(uuid4()), date.today().isoformat(),
            expectation["expectedAmountMinor"], "USD",
            (ReceiptAllocationCommand(expectation["id"], expectation["expectedAmountMinor"]),),
            "other", other_payment_method_note="Money order",
        ))
        with TestClient(create_app(self.workspace.config.config_path)) as client:
            suggested = client.get(f"/api/leases/{self.lease['id']}/rent-receipts/payment-method-suggestion")
        self.assertEqual(suggested.status_code, 200, suggested.text)
        self.assertEqual(suggested.json()["paymentMethodKind"], "other")
        self.assertEqual(suggested.json()["otherPaymentMethodNote"], "Money order")

    def test_receipt_http_contract_requires_and_returns_payment_method_snapshot(self):
        term = self.lease["terms"][0]
        expectation = self.finance.synchronize(
            self.lease["id"],
            SynchronizeExpectationsCommand(
                term["id"], (date.today() + timedelta(days=60)).isoformat(),
                date.today().replace(day=1).isoformat(),
            ),
        )[0]
        payload = {
            "leaseId": self.lease["id"], "idempotencyKey": str(uuid4()),
            "receivedOn": date.today().isoformat(),
            "amountMinor": expectation["expectedAmountMinor"], "currencyCode": "USD",
            "allocations": [{"expectationId": expectation["id"], "amountMinor": expectation["expectedAmountMinor"]}],
            "paymentMethodKind": "online_payment", "paymentMethodLabel": "Tenant portal",
            "maskedReference": "•••• 4421", "otherPaymentMethodNote": None,
        }
        with TestClient(create_app(self.workspace.config.config_path)) as client:
            invalid = client.post("/api/rent-receipts", json={**payload, "paymentMethodKind": "other"})
            created = client.post("/api/rent-receipts", json=payload)
            listed = client.get("/api/rent-receipts")
        self.assertEqual(invalid.status_code, 422, invalid.text)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["paymentMethodKind"], "online_payment")
        self.assertEqual(created.json()["maskedReference"], "•••• 4421")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["items"][0]["paymentMethodLabel"], "Tenant portal")

    def test_duplicate_receipt_requires_explicit_transactional_review(self):
        term = self.lease["terms"][0]
        rows = self.finance.synchronize(
            self.lease["id"],
            SynchronizeExpectationsCommand(term["id"], (date.today() + timedelta(days=90)).isoformat(), date.today().replace(day=1).isoformat()),
        )
        first, second = rows[:2]
        self.finance.record_receipt(RecordReceiptCommand(
            self.lease["id"], str(uuid4()), date.today().isoformat(), 100, "USD",
            (ReceiptAllocationCommand(first["id"], 100),), "cash",
        ))
        with self.assertRaises(FinanceConflictError):
            self.finance.record_receipt(RecordReceiptCommand(
                self.lease["id"], str(uuid4()), date.today().isoformat(), 100, "USD",
                (ReceiptAllocationCommand(second["id"], 100),), "online_payment",
            ))
        confirmed = self.finance.record_receipt(RecordReceiptCommand(
            self.lease["id"], str(uuid4()), date.today().isoformat(), 100, "USD",
            (ReceiptAllocationCommand(second["id"], 100),), "online_payment",
            duplicate_confirmed=True, duplicate_reason="Separate same-day payment.",
        ))
        event = SQLiteAuditRepository(self.workspace.paths.database).history(
            "rent_receipt", confirmed["id"], action="recorded",
        )[0]
        self.assertTrue(event.after_snapshot["duplicateConfirmed"])
        self.assertEqual(event.after_snapshot["duplicateReason"], "Separate same-day payment.")

    def test_safe_masked_reference_rejects_corrupted_workspace_data(self):
        with self.assertRaises(FinanceError):
            RecordReceiptCommand(
                self.lease["id"], str(uuid4()), date.today().isoformat(), 100, "USD",
                (ReceiptAllocationCommand(str(uuid4()), 100),), "online_payment",
                masked_reference="access_token=sk-live-secret",
            )
        term = self.lease["terms"][0]
        expectation = self.finance.synchronize(
            self.lease["id"],
            SynchronizeExpectationsCommand(term["id"], (date.today() + timedelta(days=60)).isoformat(), date.today().replace(day=1).isoformat()),
        )[0]
        receipt = self.finance.record_receipt(RecordReceiptCommand(
            self.lease["id"], str(uuid4()), date.today().isoformat(), expectation["expectedAmountMinor"], "USD",
            (ReceiptAllocationCommand(expectation["id"], expectation["expectedAmountMinor"]),),
            "check", masked_reference="Check •••• 9182",
        ))
        with self.finance.unit_of_work.engine.begin() as connection:
            connection.execute(text(
                "UPDATE rent_receipts SET masked_reference = '4111111111111111' WHERE id = :id"
            ), {"id": receipt["id"]})
        with self.assertRaises(ProductSchemaError):
            validate_latest_schema(self.workspace.paths.database)

    def test_suggestion_skips_voided_receipts_and_activity_hides_method_details(self):
        stamp = datetime.now(UTC).isoformat()
        first = RentReceipt(str(uuid4()), self.lease["id"], str(uuid4()), "2026-01-01", 100, "USD", "cash", "Cash drawer", None, None, None, None, None, None, None, stamp)
        latest = RentReceipt(str(uuid4()), self.lease["id"], str(uuid4()), "2026-01-02", 100, "USD", "check", "Personal check", "Check •••• 9182", None, None, None, None, None, None, stamp)
        self.finance.unit_of_work.write(lambda tx: (tx.insert_receipt(first), tx.insert_receipt(latest)))
        self.assertEqual(self.finance.payment_method_suggestion(self.lease["id"])["paymentMethodKind"], "check")
        self.finance.void_receipt(latest.id, VoidCommand(True, "Corrected receipt"))
        self.assertEqual(self.finance.payment_method_suggestion(self.lease["id"])["paymentMethodKind"], "cash")
        term = self.lease["terms"][0]
        expectation = self.finance.synchronize(self.lease["id"], SynchronizeExpectationsCommand(term["id"], (date.today() + timedelta(days=60)).isoformat(), date.today().replace(day=1).isoformat()))[0]
        created = self.finance.record_receipt(RecordReceiptCommand(
            self.lease["id"], str(uuid4()), date.today().isoformat(), expectation["expectedAmountMinor"], "USD",
            (ReceiptAllocationCommand(expectation["id"], expectation["expectedAmountMinor"]),), "other",
            payment_method_label="Internal transfer", masked_reference="•••• 1234", other_payment_method_note="Recorded from portal receipt",
        ))
        with TestClient(create_app(self.workspace.config.config_path)) as client:
            activity = client.get("/api/audit/events").json()["events"]
            contextual = client.get(f"/api/audit/events/rent_receipt/{created['id']}").json()["events"]
        event = next(item for item in activity if item["entityId"] == created["id"])
        self.assertNotIn("paymentMethodLabel", event["after"])
        self.assertNotIn("maskedReference", event["after"])
        self.assertNotIn("otherPaymentMethodNote", event["after"])
        self.assertEqual(contextual[-1]["after"]["maskedReference"], "•••• 1234")

    @fast_backup_encryption()
    def test_receipt_method_snapshot_survives_encrypted_backup_and_restore(self):
        term = self.lease["terms"][0]
        expectation = self.finance.synchronize(self.lease["id"], SynchronizeExpectationsCommand(
            term["id"], (date.today() + timedelta(days=60)).isoformat(), date.today().replace(day=1).isoformat(),
        ))[0]
        receipt = self.finance.record_receipt(RecordReceiptCommand(
            self.lease["id"], str(uuid4()), date.today().isoformat(), expectation["expectedAmountMinor"], "USD",
            (ReceiptAllocationCommand(expectation["id"], expectation["expectedAmountMinor"]),),
            "check", "Personal check", "Check •••• 9182",
        ))
        backups = BackupService(
            self.workspace, AuditRecorder(SQLiteAuditRepository(self.workspace.paths.database)),
            lambda database: AuditRecorder(SQLiteAuditRepository(database)),
        )
        root = self.workspace.paths.root.parent
        archive = backups.create_backup(
            "a sufficiently long backup passphrase", output_path=root / "fin006.epm-backup",
        )
        restored_path = root / "restored-fin006"
        backups.restore(archive.archive_path, "a sufficiently long backup passphrase", restored_path)
        database = restored_path / "database" / "property-management.sqlite"
        restored = FinanceService(SQLiteFinanceUnitOfWork(
            database, AuditRecorder(SQLiteAuditRepository(database)),
            SQLiteLeaseContextReader(), SQLitePortfolioContextReader(), SQLitePartyOperations(database),
        ))
        restored_receipt = restored.receipt(receipt["id"])
        self.assertEqual(restored_receipt["paymentMethodKind"], "check")
        self.assertEqual(restored_receipt["maskedReference"], "Check •••• 9182")

    def test_replacement_chain_filter_returns_complete_lineage(self):
        term = self.lease["terms"][0]
        expectation = self.finance.synchronize(self.lease["id"], SynchronizeExpectationsCommand(term["id"], (date.today() + timedelta(days=60)).isoformat(), date.today().replace(day=1).isoformat()))[0]
        def record(replaces=None):
            return self.finance.record_receipt(RecordReceiptCommand(self.lease["id"], str(uuid4()), date.today().isoformat(), expectation["expectedAmountMinor"], "USD", (ReceiptAllocationCommand(expectation["id"], expectation["expectedAmountMinor"]),), "cash", replaces_receipt_id=replaces))
        first = record()
        self.finance.void_receipt(first["id"], VoidCommand(True, "Correction"))
        second = record(first["id"])
        self.finance.void_receipt(second["id"], VoidCommand(True, "Correction"))
        third = record(second["id"])
        lineage = self.finance.list_receipts(replaces_receipt_id=first["id"], include_voided=True)
        self.assertEqual({item["id"] for item in lineage["items"]}, {first["id"], second["id"], third["id"]})

    def test_schedule_uses_horizon_only_for_complete_periods_and_correct_stub_denominator(self):
        snapshot = LeaseTermFinanceSnapshot("term", "lease", "executed", "property", "space", "America/Los_Angeles", "2026-01-15", None, 3_100, "USD", "monthly", 1, None, None)
        command = SynchronizeExpectationsCommand(str(uuid4()), "2026-02-15", "2026-02-01")
        rows = _schedule(snapshot, command, datetime(2026, 1, 1, tzinfo=UTC))
        self.assertEqual([(row.period_starts_on, row.period_ends_on, row.expected_amount_minor, row.proration_denominator_days) for row in rows], [("2026-01-15", "2026-01-31", 1_700, 31)])

    def test_schedule_intersects_actual_move_out_with_term_boundary(self):
        snapshot = LeaseTermFinanceSnapshot("term", "lease", "terminated", "property", "space", "America/Los_Angeles", "2026-01-01", "2026-04-01", 3_100, "USD", "monthly", 1, "2026-02-10", None)
        rows = _schedule(snapshot, SynchronizeExpectationsCommand(str(uuid4()), "2026-04-01", "2026-01-01"), datetime(2026, 1, 1, tzinfo=UTC))
        self.assertEqual(rows[-1].period_ends_on, "2026-02-09")

    def test_shortened_first_stub_is_emitted_and_one_day_stub_is_rejected(self):
        snapshot = LeaseTermFinanceSnapshot("term", "lease", "executed", "property", "space", "America/Los_Angeles", "2026-01-15", None, 31_000, "USD", "monthly", 1, None, None)
        command = SynchronizeExpectationsCommand(str(uuid4()), "2026-02-15", "2026-02-01", "2026-01-20", "Approved early boundary", True)
        rows = _schedule(snapshot, command, datetime(2026, 1, 1, tzinfo=UTC))
        self.assertEqual([(row.period_starts_on, row.period_ends_on, row.expected_amount_minor) for row in rows], [("2026-01-15", "2026-01-20", 6_000)])
        one_day = SynchronizeExpectationsCommand(str(uuid4()), "2026-02-15", "2026-02-01", "2026-01-15", "Approved early boundary", True)
        with self.assertRaises(FinanceError):
            _schedule(snapshot, one_day, datetime(2026, 1, 1, tzinfo=UTC))

    def test_boundary_extension_piece_uses_full_rent_and_has_stable_interval_identity(self):
        snapshot = LeaseTermFinanceSnapshot("term", "lease", "executed", "property", "space", "America/Los_Angeles", "2026-06-01", None, 100_000, "USD", "monthly", 1, None, None)
        original = _schedule(snapshot, SynchronizeExpectationsCommand(str(uuid4()), "2026-07-31", "2026-06-01", "2026-06-11", "Initial boundary", True), datetime(2026, 6, 1, tzinfo=UTC))[0]
        extended = _schedule(snapshot, SynchronizeExpectationsCommand(str(uuid4()), "2026-07-31", "2026-06-01", "2026-06-16", "Extended boundary", True), datetime(2026, 6, 1, tzinfo=UTC))[0]
        supplement = _boundary_extension_piece(original, extended, snapshot.base_rent_minor)
        self.assertEqual((original.period_starts_on, original.period_ends_on, original.expected_amount_minor), ("2026-06-01", "2026-06-11", 36_667))
        self.assertEqual((supplement.period_starts_on, supplement.period_ends_on, supplement.expected_amount_minor), ("2026-06-12", "2026-06-16", 16_667))
        repeated = _boundary_extension_piece(original, extended, snapshot.base_rent_minor)
        self.assertEqual(
            (repeated.period_starts_on, repeated.period_ends_on, repeated.due_on),
            (supplement.period_starts_on, supplement.period_ends_on, supplement.due_on),
        )

    def test_synchronizing_an_extended_boundary_creates_one_correct_supplement(self):
        term = self.lease["terms"][0]
        start = date.fromisoformat(term["effectiveOn"])
        anchor = start.replace(day=1)
        regular_due = date(start.year, start.month, 1)
        if regular_due < start:
            regular_due = date(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1)
        initial_boundary = regular_due + timedelta(days=10)
        extended_boundary = regular_due + timedelta(days=15)
        initial = SynchronizeExpectationsCommand(
            term["id"],
            (start + timedelta(days=60)).isoformat(),
            anchor.isoformat(),
            initial_boundary.isoformat(),
            "Initial responsibility boundary",
            True,
        )
        self.finance.synchronize(self.lease["id"], initial)
        extended = SynchronizeExpectationsCommand(
            term["id"],
            (start + timedelta(days=60)).isoformat(),
            None,
            extended_boundary.isoformat(),
            "Extended responsibility boundary",
            True,
        )
        supplement = self.finance.synchronize(self.lease["id"], extended)
        self.assertEqual(len(supplement), 1)
        next_regular_due = date(regular_due.year + (regular_due.month == 12), 1 if regular_due.month == 12 else regular_due.month + 1, 1)
        denominator = (next_regular_due - regular_due).days
        self.assertEqual(supplement[0]["expectedAmountMinor"], int((Decimal(100_000) * Decimal(5) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
        self.assertEqual(self.finance.synchronize(self.lease["id"], extended), [])
        second_extension = SynchronizeExpectationsCommand(
            term["id"],
            (start + timedelta(days=60)).isoformat(),
            None,
            (regular_due + timedelta(days=20)).isoformat(),
            "Second responsibility extension",
            True,
        )
        second_supplement = self.finance.synchronize(self.lease["id"], second_extension)
        self.assertEqual(len(second_supplement), 1)
        self.assertEqual(second_supplement[0]["expectedAmountMinor"], supplement[0]["expectedAmountMinor"])
        self.assertEqual(self.finance.synchronize(self.lease["id"], second_extension), [])
        full_interval = SynchronizeExpectationsCommand(
            term["id"],
            (start + timedelta(days=60)).isoformat(),
            None,
            (next_regular_due - timedelta(days=1)).isoformat(),
            "Responsibility through the complete period",
            True,
        )
        final_supplement = self.finance.synchronize(self.lease["id"], full_interval)
        self.assertEqual(len(final_supplement), 1)
        first_interval = self.finance.list_expectations(lease_id=self.lease["id"], page_size=100)["items"]
        covered = [item for item in first_interval if item["periodStartsOn"] >= regular_due.isoformat() and item["periodEndsOn"] <= (next_regular_due - timedelta(days=1)).isoformat()]
        self.assertEqual(sum(item["expectedAmountMinor"] for item in covered), 100_000)
        self.assertEqual(self.finance.synchronize(self.lease["id"], full_interval), [])

    def test_horizon_does_not_prorate_first_stub_without_a_boundary(self):
        snapshot = LeaseTermFinanceSnapshot("term", "lease", "executed", "property", "space", "America/Los_Angeles", "2026-01-15", None, 31_000, "USD", "monthly", 1, None, None)
        horizon_only = SynchronizeExpectationsCommand(str(uuid4()), "2026-01-20", "2026-02-01")
        self.assertEqual(_schedule(snapshot, horizon_only, datetime(2026, 1, 1, tzinfo=UTC)), [])

    def test_derived_expectation_filter_scans_beyond_early_nonmatches(self):
        term = self.lease["terms"][0]
        start = date.today()
        created = datetime.now(UTC).isoformat()
        rows = []
        for offset in range(3):
            period_start = start + timedelta(days=offset * 3)
            record = RentExpectation(
                str(uuid4()), self.lease["id"], term["id"], period_start.isoformat(),
                (period_start + timedelta(days=2)).isoformat(),
                period_start.isoformat(), 100, "USD", "monthly",
                start.replace(day=1).isoformat(), False, None, None, None, None,
                None, None, created,
            )
            rows.append(record)
        self.finance.unit_of_work.write(lambda tx: [tx.insert_expectation(row) for row in rows])
        self.finance.record_receipt(RecordReceiptCommand(
            self.lease["id"], str(uuid4()), start.isoformat(), 100, "USD",
            (ReceiptAllocationCommand(rows[2].id, 100),),
            "cash",
        ))
        page = self.finance.list_expectations(lease_id=self.lease["id"], status="paid", page_size=1)
        self.assertEqual([item["id"] for item in page["items"]], [rows[2].id])

    def test_conflicting_anchor_is_rejected_after_first_schedule(self):
        term = self.lease["terms"][0]
        self.finance.synchronize(self.lease["id"], SynchronizeExpectationsCommand(term["id"], (date.today() + timedelta(days=60)).isoformat(), date.today().replace(day=1).isoformat()))
        with self.assertRaises(FinanceConflictError):
            self.finance.synchronize(self.lease["id"], SynchronizeExpectationsCommand(term["id"], (date.today() + timedelta(days=60)).isoformat(), (date.today() + timedelta(days=7)).isoformat()))

    def test_historical_expectation_remains_presentable_after_lease_void(self):
        term = self.lease["terms"][0]
        item = self.finance.synchronize(self.lease["id"], SynchronizeExpectationsCommand(term["id"], (date.today() + timedelta(days=60)).isoformat(), date.today().replace(day=1).isoformat()))[0]
        with self.finance.unit_of_work.engine.begin() as connection:
            connection.execute(text("UPDATE leases SET status='void', actual_move_out_on=NULL, end_reason=NULL WHERE id=:id"), {"id": self.lease["id"]})
        self.assertEqual(self.finance.expectation(item["id"])["id"], item["id"])

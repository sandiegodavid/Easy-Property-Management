"""FIN-003 reconciliation and bounded SQLite read acceptance tests."""

from app.modules.finance.tests.commands import deposit_command, expense_command, rent_command
from app.modules.owner_accounting.tests.commands import owner_command
from app.platform.sqlite_engine import create_sqlite_engine

from app.modules.portfolio.tests.commands import inventory_command

import json
import unittest
import tempfile
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.files.infrastructure.file_link_reader import SQLiteFileLinkReader
from app.modules.finance.application.expense_service import ExpenseService
from app.modules.finance.application.service import FinanceService
from app.modules.finance.application.deposit_service import DepositService
from app.modules.finance.application.money_models import (
    Metric,
    MoneyError,
    MoneyQuery,
    MoneyUnavailable,
    MoneyViewChanged,
    MoneyWorkspaceUnavailable,
    money,
)
from app.modules.finance.application.money_service import MoneySummaryService
from app.modules.finance.domain.deposit_models import (
    DepositAccountCreateCommand,
    DepositReceiptCommand,
    DepositRefundCommand,
    SettlementCreateCommand,
    DeductionCommand,
    CreditCommand,
)
from app.modules.finance.domain.expense_models import ExpenseCreateCommand, RefundCreateCommand
from app.modules.finance.domain.models import (
    RecordReceiptCommand,
    ReceiptAllocationCommand,
    SynchronizeExpectationsCommand,
    VoidCommand,
)
from app.modules.finance.infrastructure.expense_unit_of_work import SQLiteExpenseUnitOfWork
from app.modules.finance.infrastructure.unit_of_work import SQLiteFinanceUnitOfWork
from app.modules.finance.infrastructure.deposit_unit_of_work import SQLiteDepositUnitOfWork
from app.modules.finance.infrastructure.money_unit_of_work import (
    SQLiteMoneySummaryUnitOfWork,
    SQLiteMoneyReadTransaction,
)
from app.modules.leases.tests.commands import lease_command
from app.modules.leases.application.service import (
    LeaseService,
    LeaseCreateCommand,
    TermCommand,
    ParticipantCommand,
)
from app.modules.leases.infrastructure.unit_of_work import (
    SQLiteLeaseUnitOfWork,
    SQLiteLeaseParticipationGuard,
)
from app.modules.leases.infrastructure.context_reader import SQLiteLeaseContextReader
from app.modules.inspections.infrastructure.context_reader import SQLiteInspectionContextReader
from app.modules.parties.application.service import SharedPartyFactory
from app.modules.parties.application.service import PartyCreateCommand
from app.modules.leases.infrastructure.location_relation import SQLiteLeaseLocationRelation
from app.modules.parties.infrastructure.unit_of_work import (
    SQLitePartyOperations,
    SQLitePartyReadOperations,
)
from app.modules.portfolio.application.service import (
    PortfolioService,
    PropertyCreateCommand,
    OwnershipInput,
)
from app.modules.portfolio.infrastructure.context_reader import SQLitePortfolioContextReader
from app.modules.portfolio.infrastructure.location_relations import SQLitePortfolioLocationRelations
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
from app.modules.portfolio.infrastructure.unit_of_work import (
    SQLitePortfolioUnitOfWork,
    SQLitePortfolioLeaseOperations,
)
from app.modules.tenants.application.service import TenantService, TenantCreateCommand
from app.modules.tenants.infrastructure.unit_of_work import (
    SQLiteTenantUnitOfWork,
    SQLiteTenantProfileAvailability,
)
from app.modules.vendors.infrastructure.context_reader import SQLiteProviderContextReader
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceError, WorkspaceService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.modules.owner_accounting.application.service import OwnerRentReportService
from app.modules.owner_accounting.domain.models import (
    OwnerRentReportCommand,
    VerifyOwnerRentReportCommand,
)
from app.modules.owner_accounting.infrastructure.unit_of_work import SQLiteOwnerRentReportUnitOfWork
from app.modules.owner_accounting.infrastructure.file_link_facts import (
    SQLiteOwnerRentReportFileLinkFacts,
)
from app.modules.owner_accounting.application.file_links import OwnerRentReportFileLinkValidator
from app.modules.finance.infrastructure.receipt_transaction_operations import (
    SQLiteReceiptTransactionOperations,
)
from app.modules.files.application.service import FileService
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.platform.product_migrations import validate_latest_schema
from app.platform.config import LocalConfig


class FixtureLeaseDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 1, 1)


class MoneySummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        config = root / "config.json"
        config.write_text(
            json.dumps({"localWorkspacePath": str(root / "workspace")}), encoding="utf-8"
        )
        self.workspace = WorkspaceService(LocalConfig(config, root / "workspace"))
        self.workspace.initialize()
        self.db = self.workspace.paths.database
        recorder = AuditRecorder(SQLiteAuditRepository(self.db))
        parties = SQLitePartyOperations(self.db)
        self.portfolio = PortfolioService(
            SQLitePortfolioUnitOfWork(self.db, recorder),
            time_zone_resolver=BundledAddressTimeZoneResolver(),
            now=lambda: datetime(2026, 1, 1, 12, tzinfo=UTC),
        )
        property_record = inventory_command(
            self.portfolio,
            "create_property",
            PropertyCreateCommand(
                "Rent home",
                "1 Main Street",
                "Portland",
                "US",
                "single_family_home",
                (OwnershipInput("local_operator"),),
                region="OR",
            ),
        )
        self.property_id = property_record.id
        space = self.portfolio.get_property(self.property_id)["spaces"][0]["id"]
        self.tenant = TenantService(
            SQLiteTenantUnitOfWork(
                self.db,
                recorder,
                SQLiteLeaseParticipationGuard(),
                parties,
                SQLitePartyReadOperations(parties),
            ),
            SharedPartyFactory(),
        ).create(
            TenantCreateCommand("individual", "Tenant"),
            expected_revision=0,
            idempotency_key=str(uuid4()),
        )
        self.leases = LeaseService(
            SQLiteLeaseUnitOfWork(
                self.db,
                recorder,
                SQLiteTenantProfileAvailability(),
                SQLitePortfolioLeaseOperations(self.db),
                SQLiteInspectionContextReader(),
            )
        )
        lease = lease_command(
            self.leases,
            "create",
            LeaseCreateCommand(
                space,
                "residential",
                date(2026, 1, 1),
                date(2026, 12, 31),
                date(2026, 1, 1),
                TermCommand(100000, "USD", "monthly", 1, 0),
                (ParticipantCommand(self.tenant["id"], "primary_tenant"),),
            ),
        )
        # Execute at the fixture's historical start, then inspect corrected money
        # in October. Leasing has no injected calendar yet; freeze its clock here.
        with (
            patch("app.modules.leases.application.service.date", FixtureLeaseDate),
            patch(
                "app.modules.leases.application.service._now",
                return_value="2026-01-01T12:00:00+00:00",
            ),
        ):
            self.lease = lease_command(
                self.leases,
                "execute",
                lease["id"],
                executed_on="2026-01-01",
                confirmed=True,
                expected_revision=self.portfolio.get_space_status(space)["revision"],
                idempotency_key=str(uuid4()),
            )
        self.finance = FinanceService(
            SQLiteFinanceUnitOfWork(
                self.db,
                recorder,
                SQLiteLeaseContextReader(),
                SQLitePortfolioContextReader(),
                parties,
            ),
            now=lambda: datetime(2026, 10, 6, 12, tzinfo=UTC),
        )
        self.deposits = DepositService(
            SQLiteDepositUnitOfWork(
                self.db,
                recorder,
                SQLiteLeaseContextReader(),
                SQLitePortfolioContextReader(),
                parties,
                SQLiteInspectionContextReader(),
                SQLiteFileLinkReader(),
            ),
            now=lambda: datetime(2026, 10, 6, 12, tzinfo=UTC),
        )
        self.identity = (self.workspace.open().workspace_id, str(uuid4()))
        self.reader = self.make_reader(self.db)
        self.expenses = ExpenseService(
            SQLiteExpenseUnitOfWork(
                self.db,
                recorder,
                SQLitePortfolioContextReader(),
                SQLiteProviderContextReader(),
                SQLitePartyOperations(self.db),
                SQLiteFileLinkReader(),
            ),
            now=lambda: datetime(2026, 10, 6, 12, tzinfo=UTC),
        )
        self.query = MoneyQuery("2026-01-01", "2026-01-31")

    def make_reader(self, database, identity=None):
        portfolio = SQLitePortfolioLocationRelations()
        return MoneySummaryService(
            SQLiteMoneySummaryUnitOfWork(
                database,
                portfolio,
                SQLiteLeaseLocationRelation(portfolio),
                SQLiteAuditReadMarker(),
            ),
            read_identity=lambda: identity or self.identity,
            now=lambda: datetime(2026, 10, 6, 12, tzinfo=UTC),
        )

    def lease_for_property(self, property_id):
        space = self.portfolio.get_property(property_id)["spaces"][0]["id"]
        lease = lease_command(
            self.leases,
            "create",
            LeaseCreateCommand(
                space,
                "residential",
                date(2026, 1, 1),
                date(2026, 12, 31),
                date(2026, 1, 1),
                TermCommand(100000, "USD", "monthly", 1, 0),
                (ParticipantCommand(self.tenant["id"], "primary_tenant"),),
            ),
        )
        with (
            patch("app.modules.leases.application.service.date", FixtureLeaseDate),
            patch(
                "app.modules.leases.application.service._now",
                return_value="2026-01-01T12:00:00+00:00",
            ),
        ):
            return lease_command(
                self.leases,
                "execute",
                lease["id"],
                executed_on="2026-01-01",
                confirmed=True,
                expected_revision=self.portfolio.get_space_status(space)["revision"],
                idempotency_key=str(uuid4()),
            )

    def record_sources(self, deposits=True):
        term = self.lease["terms"][0]
        expectations = rent_command(
            self.finance,
            "synchronize",
            self.lease["id"],
            SynchronizeExpectationsCommand(
                term["id"],
                (date.fromisoformat(term["effectiveOn"]) + timedelta(days=70)).isoformat(),
                term["effectiveOn"],
            ),
        )
        self.receipt = rent_command(
            self.finance,
            "record_receipt",
            RecordReceiptCommand(
                self.lease["id"],
                str(uuid4()),
                "2026-01-15",
                120000,
                "USD",
                tuple(ReceiptAllocationCommand(row["id"], 60000) for row in expectations[:2]),
                "cash",
            ),
        )
        category = self.expenses.list_categories()[0]
        self.expense = expense_command(
            self.expenses,
            "record_expense",
            ExpenseCreateCommand(
                str(uuid4()),
                self.property_id,
                category["id"],
                "local_operator",
                "2026-01-10",
                "400.00",
                "USD",
                "Recorded maintenance",
                payee_name="Contractor",
            ),
        )
        self.refund = expense_command(
            self.expenses,
            "record_refund",
            self.expense["id"],
            RefundCreateCommand(
                str(uuid4()),
                "2026-02-10",
                "100.00",
                "USD",
            ),
        )
        if not deposits:
            return
        self.account = deposit_command(
            self.deposits,
            "create_account",
            self.lease["id"],
            DepositAccountCreateCommand(term["id"]),
        )
        self.deposit_receipt = deposit_command(
            self.deposits,
            "record_receipt",
            self.account["id"],
            DepositReceiptCommand(
                str(uuid4()),
                "2026-01-10",
                "1000.00",
                "USD",
                "local_operator",
                overage_confirmed=True,
                overage_reason="Documented actual receipt",
            ),
        )
        draft = deposit_command(
            self.deposits,
            "create_settlement",
            self.account["id"],
            SettlementCreateCommand(
                "2026-02-20",
                eligibility_override_confirmed=True,
                eligibility_override_reason="Early settlement agreed",
            ),
        )
        deduction = deposit_command(
            self.deposits,
            "add_deduction",
            draft["id"],
            DeductionCommand(
                "damage",
                "200.00",
                "Repair",
                "Documented repair cost",
            ),
        )
        deposit_command(
            self.deposits, "add_deduction_source", deduction["id"], "expense", self.expense["id"]
        )
        self.deposits.now = lambda: datetime(2026, 2, 2, 0, 30, tzinfo=UTC)
        self.settlement = deposit_command(self.deposits, "approve_settlement", draft["id"], True)
        self.deposits.now = lambda: datetime(2026, 10, 6, 12, tzinfo=UTC)
        participant = self.lease["participants"][0]["tenantPartyId"]
        self.deposit_refund = deposit_command(
            self.deposits,
            "record_refund",
            self.settlement["id"],
            DepositRefundCommand(
                str(uuid4()),
                participant,
                "2026-02-10",
                "300.00",
                "USD",
            ),
        )

    def count_queries(self, operation):
        statements = []

        def capture(_, __, sql, *args):
            if sql.lstrip().upper().startswith(("SELECT", "WITH")):
                statements.append(sql)

        engine = self.reader.unit_of_work.engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            result = operation()
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        return result, statements

    def test_reconciliation_and_every_metric_has_exact_contributions(self):
        self.record_sources()
        january = self.reader.summary(self.query)
        february_query = replace(self.query, from_on="2026-02-01", through_on="2026-02-28")
        february = self.reader.summary(february_query)
        self.assertEqual(january.operating.rent_received, "1200.00")
        self.assertEqual(january.operating.rent_receipt_count, 1)
        self.assertEqual(january.operating.operating_remainder, "800.00")
        self.assertEqual(february.operating.net_recorded_expenses, "-100.00")
        self.assertEqual(february.operating.operating_remainder, "100.00")
        self.assertEqual(february.deposit_activity.settlement_deductions, "200.00")
        self.assertEqual(february.deposit_activity.deposit_refunds, "300.00")
        self.assertEqual(january.deposit_obligations.net_recorded_obligation, "500.00")
        for query, summary in ((self.query, january), (february_query, february)):
            for descriptor in summary.metrics:
                page = self.reader.sources(
                    replace(query, source_revision=summary.source_revision), descriptor.metric
                )
                self.assertEqual(page.total, descriptor.amount)
                self.assertEqual(
                    sum((Decimal(item.contribution) for item in page.items), Decimal(0)),
                    Decimal(page.total),
                )
        accounts = self.reader.deposit_accounts(self.query)
        self.assertEqual(accounts.items[0].recorded_deposit_obligation, "500.00")
        self.assertEqual(accounts.items[0].approved_refund_due, "800.00")
        self.assertEqual(accounts.items[0].unsettled_receipt_amount, "0.00")
        validate_latest_schema(self.db)

    def test_corrections_restate_original_dates_and_surviving_refunds(self):
        self.record_sources()
        rent_command(
            self.finance, "void_receipt", self.receipt["id"], VoidCommand(True, "Incorrect receipt")
        )
        result = self.reader.summary(self.query)
        self.assertEqual(result.operating.rent_received, "0.00")
        self.assertEqual(result.operating.operating_remainder, "-400.00")
        deposit_command(
            self.deposits,
            "void_settlement",
            self.settlement["id"],
            VoidCommand(True, "Correction needed"),
        )
        result = self.reader.summary(
            replace(self.query, from_on="2026-02-01", through_on="2026-02-28")
        )
        self.assertEqual(result.deposit_activity.settlement_deductions, "0.00")
        self.assertEqual(result.deposit_activity.deposit_refunds, "300.00")
        self.assertEqual(result.deposit_obligations.net_recorded_obligation, "700.00")
        self.assertEqual(
            self.reader.sources(self.query, Metric.CURRENT_REFUNDS).items[0].authorization_id,
            self.settlement["id"],
        )
        expense_command(
            self.expenses, "void_refund", self.refund["id"], VoidCommand(True, "Incorrect refund")
        )
        expense_command(
            self.expenses,
            "void_expense",
            self.expense["id"],
            VoidCommand(True, "Incorrect expense"),
        )
        self.assertEqual(
            self.reader.summary(
                replace(self.query, from_on="2026-02-01", through_on="2026-02-28")
            ).operating.expense_refunds_received,
            "0.00",
        )

    def test_negative_reconciliation_and_replacement_decisions_are_not_netted_away(self):
        self.record_sources()
        deposit_command(
            self.deposits,
            "void_settlement",
            self.settlement["id"],
            VoidCommand(True, "Incorrect decision"),
        )
        deposit_command(
            self.deposits,
            "void_receipt",
            self.deposit_receipt["id"],
            VoidCommand(True, "Erroneous receipt"),
        )
        result = self.reader.summary(self.query)
        self.assertEqual(result.deposit_obligations.positive_obligations, "0.00")
        self.assertEqual(result.deposit_obligations.negative_reconciliation_amount, "-300.00")
        self.assertEqual(result.deposit_obligations.negative_account_count, 1)
        self.assertTrue(self.reader.deposit_accounts(self.query).items[0].requires_review)
        # Reconcile receipt facts, then replace only the settlement decision;
        # the refund retains its original authorization and contributes once.
        deposit_command(
            self.deposits,
            "record_receipt",
            self.account["id"],
            DepositReceiptCommand(
                str(uuid4()),
                "2026-01-10",
                "1000.00",
                "USD",
                "local_operator",
                overage_confirmed=True,
                overage_reason="Corrected receipt",
                replaces_receipt_id=self.deposit_receipt["id"],
            ),
        )
        replacement = deposit_command(
            self.deposits,
            "create_settlement",
            self.account["id"],
            SettlementCreateCommand(
                "2026-10-20",
                eligibility_override_confirmed=True,
                eligibility_override_reason="Early settlement agreed",
                replaces_settlement_id=self.settlement["id"],
            ),
        )
        deposit_command(
            self.deposits,
            "add_credit",
            replacement["id"],
            CreditCommand("other", "20.00", "Approved credit"),
        )
        # Draft credit is never part of the obligation or period approvals.
        self.assertEqual(
            self.reader.summary(self.query).deposit_obligations.net_recorded_obligation, "700.00"
        )
        deposit_command(self.deposits, "approve_settlement", replacement["id"], True)
        result = self.reader.summary(
            replace(self.query, from_on="2026-10-01", through_on="2026-10-31")
        )
        self.assertEqual(result.deposit_obligations.net_recorded_obligation, "720.00")
        self.assertEqual(result.deposit_activity.settlement_credits, "20.00")
        self.assertEqual(result.deposit_activity.approved_settlement_count, 1)
        self.assertEqual(self.reader.sources(self.query, Metric.CURRENT_REFUNDS).matching_total, 1)

    def test_approval_and_completion_use_distinct_property_local_dates_and_late_receipts(self):
        self.record_sources()
        participant = self.lease["participants"][0]["tenantPartyId"]
        deposit_command(
            self.deposits,
            "record_refund",
            self.settlement["id"],
            DepositRefundCommand(
                str(uuid4()),
                participant,
                "2026-02-20",
                "500.00",
                "USD",
            ),
        )
        self.deposits.now = lambda: datetime(2026, 3, 1, 0, 30, tzinfo=UTC)
        deposit_command(self.deposits, "complete_settlement", self.settlement["id"], False)
        feb = replace(self.query, from_on="2026-02-01", through_on="2026-02-28")
        result = self.reader.summary(feb)
        self.assertEqual(result.deposit_activity.completed_settlement_count, 1)
        self.assertEqual(result.deposit_activity.approved_settlement_count, 1)
        march = self.reader.summary(
            replace(self.query, from_on="2026-03-01", through_on="2026-03-31")
        )
        self.assertEqual(march.deposit_activity.completed_settlement_count, 0)
        self.assertEqual(result.deposit_obligations.net_recorded_obligation, "0.00")
        self.assertEqual(result.deposit_obligations.unresolved_account_count, 0)
        self.deposits.now = lambda: datetime(2026, 10, 6, 12, tzinfo=UTC)
        deposit_command(
            self.deposits,
            "record_receipt",
            self.account["id"],
            DepositReceiptCommand(
                str(uuid4()),
                "2026-03-10",
                "100.00",
                "USD",
                "local_operator",
                overage_confirmed=True,
                overage_reason="Late actual receipt",
            ),
        )
        account = self.reader.deposit_accounts(self.query).items[0]
        self.assertEqual(account.settlement_status, "completed")
        self.assertEqual(account.unsettled_receipt_amount, "100.00")
        self.assertEqual(account.recorded_deposit_obligation, "100.00")
        self.assertTrue(account.unresolved)

    def test_positive_and_negative_accounts_remain_separate_in_bounded_pages(self):
        self.record_sources()
        deposit_command(
            self.deposits,
            "void_settlement",
            self.settlement["id"],
            VoidCommand(True, "Incorrect decision"),
        )
        deposit_command(
            self.deposits,
            "void_receipt",
            self.deposit_receipt["id"],
            VoidCommand(True, "Erroneous receipt"),
        )
        property_record = inventory_command(
            self.portfolio,
            "create_property",
            PropertyCreateCommand(
                "Second deposit property",
                "1 Main Street",
                "Portland",
                "US",
                "single_family_home",
                (OwnershipInput("local_operator"),),
                region="OR",
            ),
        )
        lease = self.lease_for_property(property_record.id)
        account = deposit_command(
            self.deposits,
            "create_account",
            lease["id"],
            DepositAccountCreateCommand(lease["terms"][0]["id"]),
        )
        deposit_command(
            self.deposits,
            "record_receipt",
            account["id"],
            DepositReceiptCommand(
                str(uuid4()),
                "2026-01-10",
                "1000.00",
                "USD",
                "local_operator",
                overage_confirmed=True,
                overage_reason="Documented receipt",
            ),
        )
        query = replace(self.query, page_size=1)
        first, statements = self.count_queries(lambda: self.reader.deposit_accounts(query))
        self.assertLessEqual(len(statements), 8)
        self.assertEqual(first.matching_total, 2)
        self.assertEqual(first.totals.positive_obligations, "1000.00")
        self.assertEqual(first.totals.negative_reconciliation_amount, "-300.00")
        self.assertEqual(first.totals.net_recorded_obligation, "700.00")
        second = self.reader.deposit_accounts(replace(query, cursor=first.next_cursor))
        self.assertEqual(
            {first.items[0].account_id, second.items[0].account_id},
            {account["id"], self.account["id"]},
        )
        self.assertIsNone(second.next_cursor)

    def test_settlement_dates_across_dst_are_property_local(self):
        self.record_sources()
        predecessor = self.settlement["id"]
        for instant, local_day in (
            (datetime(2026, 3, 8, 7, 30, tzinfo=UTC), "2026-03-07"),
            (datetime(2026, 3, 8, 10, 30, tzinfo=UTC), "2026-03-08"),
        ):
            deposit_command(
                self.deposits,
                "void_settlement",
                predecessor,
                VoidCommand(True, "Replace reviewed decision"),
            )
            self.deposits.now = lambda: instant
            draft = deposit_command(
                self.deposits,
                "create_settlement",
                self.account["id"],
                SettlementCreateCommand(
                    "2026-03-20",
                    eligibility_override_confirmed=True,
                    eligibility_override_reason="Early settlement agreed",
                    replaces_settlement_id=predecessor,
                ),
            )
            approved = deposit_command(self.deposits, "approve_settlement", draft["id"], True)
            query = replace(self.query, from_on=local_day, through_on=local_day)
            self.assertEqual(
                self.reader.summary(query).deposit_activity.approved_settlement_count, 1
            )
            self.assertEqual(
                self.reader.sources(query, Metric.CREDITS).items[0].business_on, local_day
            )
            predecessor = approved["id"]

    def test_long_history_has_constant_query_cost_and_indexed_period_reads(self):
        self.record_sources(False)
        first, first_sql = self.count_queries(
            lambda: self.reader.sources(self.query, Metric.EXPENSES)
        )
        category = self.expenses.list_categories()[0]
        for index in range(150):
            expense_command(
                self.expenses,
                "record_expense",
                ExpenseCreateCommand(
                    str(uuid4()),
                    self.property_id,
                    category["id"],
                    "local_operator",
                    "2026-01-11",
                    "1.00",
                    "USD",
                    "Recorded small expense",
                    payee_name=f"Contractor {index}",
                ),
            )
        second, second_sql = self.count_queries(
            lambda: self.reader.sources(self.query, Metric.EXPENSES)
        )
        self.assertEqual(len(first_sql), len(second_sql))
        self.assertLessEqual(len(second_sql), 8)
        self.assertEqual(second.matching_total, 151)
        self.assertEqual(len(second.items), 50)
        self.assertTrue(second.next_cursor)
        uow = self.reader.unit_of_work
        with uow.engine.connect() as connection:
            tx = SQLiteMoneyReadTransaction(connection, uow.portfolio, uow.leases, uow.marker)
            sql = str(
                tx._period_group(self.query).compile(
                    dialect=uow.engine.dialect, compile_kwargs={"literal_binds": True}
                )
            )
            plan = "\n".join(
                row[3] for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + sql)
            )
        for index in (
            "rent_receipts_lifecycle_received",
            "expenses_lifecycle_paid",
            "expense_refunds_lifecycle",
            "security_deposit_receipts_lifecycle_date",
            "security_deposit_refunds_lifecycle_paid",
            "security_deposit_settlements_status_approval",
        ):
            self.assertIn(index, plan)
        validate_latest_schema(self.db)

    def test_archived_history_and_empty_property_are_distinct(self):
        self.record_sources(False)
        recorder = AuditRecorder(SQLiteAuditRepository(self.db))
        portfolio = PortfolioService(
            SQLitePortfolioUnitOfWork(self.db, recorder),
            time_zone_resolver=BundledAddressTimeZoneResolver(),
        )
        empty = inventory_command(
            portfolio,
            "create_property",
            PropertyCreateCommand(
                "Empty retained property",
                "1 Main Street",
                "Portland",
                "US",
                "single_family_home",
                (OwnershipInput("local_operator"),),
                region="OR",
            ),
        )
        inventory_command(portfolio, "archive_property", empty.id, confirmed=True)
        page = self.reader.properties(self.query)
        self.assertEqual(page.matching_total, 2)
        self.assertEqual(
            sum(Decimal(row.operating.operating_remainder) for row in page.items),
            Decimal(page.summary.operating.operating_remainder),
        )
        empty_row = next(row for row in page.items if row.property_id == empty.id)
        self.assertEqual(empty_row.operating.rent_receipt_count, 0)
        self.assertTrue(empty_row.operating.available)
        active = self.reader.summary(replace(self.query, property_state="active"))
        self.assertEqual(active.scope.property_count, 1)
        self.assertEqual(active.scope.excluded_property_count, 1)
        self.assertEqual(
            self.reader.summary(replace(self.query, property_ids=(empty.id,))).scope.property_count,
            1,
        )

    def test_intermediate_read_failure_and_source_write_rollback_leave_no_partial_results(self):
        self.record_sources(False)
        before = self.reader.summary(self.query)
        with patch.object(
            SQLiteMoneyReadTransaction,
            "obligation_totals",
            side_effect=MoneyUnavailable("Unavailable source"),
        ):
            with self.assertRaises(MoneyUnavailable):
                self.reader.summary(self.query)
        self.assertEqual(before, self.reader.summary(self.query))

        def failed_write(tx):
            tx.connection.execute(
                text("UPDATE rent_receipts SET amount_minor=1 WHERE id=:id"),
                {"id": self.receipt["id"]},
            )
            raise RuntimeError("Failure after source write")

        with self.assertRaises(RuntimeError):
            self.finance.unit_of_work.write(failed_write)
        self.assertEqual(before, self.reader.summary(self.query))

    def test_empty_reads_and_repeated_reads_never_write(self):
        before = self.finance.unit_of_work.read(
            lambda tx: tx.connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one()
        )
        first = self.reader.summary(self.query)
        self.assertEqual(first, self.reader.summary(self.query))
        self.assertEqual(first.operating.operating_remainder, "0.00")
        self.assertEqual(first.scope.property_count, 1)
        self.assertEqual(first.deposit_obligations.account_count, 0)
        after = self.finance.unit_of_work.read(
            lambda tx: tx.connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one()
        )
        self.assertEqual(before, after)

    def test_owner_report_adoption_does_not_create_a_second_money_source(self):
        recorder = AuditRecorder(SQLiteAuditRepository(self.db))
        parties = SQLitePartyOperations(self.db)
        owner = self.portfolio.create_party(PartyCreateCommand("individual", "Client owner"))
        property_record = inventory_command(
            self.portfolio,
            "create_property",
            PropertyCreateCommand(
                "Managed property",
                "1 Main Street",
                "Portland",
                "US",
                "single_family_home",
                (OwnershipInput("client_owner", party_id=owner.id),),
                region="OR",
            ),
        )
        lease = self.lease_for_property(property_record.id)
        expectation = rent_command(
            self.finance,
            "synchronize",
            lease["id"],
            SynchronizeExpectationsCommand(
                lease["terms"][0]["id"],
                "2026-03-01",
                "2026-01-01",
            ),
        )[0]
        receipt = rent_command(
            self.finance,
            "record_receipt",
            RecordReceiptCommand(
                lease["id"],
                str(uuid4()),
                "2026-01-15",
                100000,
                "USD",
                (ReceiptAllocationCommand(expectation["id"], 100000),),
                "cash",
                received_by_party_id=owner.id,
            ),
        )
        reports = OwnerRentReportService(
            SQLiteOwnerRentReportUnitOfWork(
                self.db,
                recorder,
                SQLiteLeaseContextReader(),
                SQLitePortfolioContextReader(),
                parties,
                SQLiteFileLinkReader(),
                SQLiteReceiptTransactionOperations(
                    recorder,
                    SQLiteLeaseContextReader(),
                    SQLitePortfolioContextReader(),
                    parties,
                ),
            ),
            now=lambda: datetime(2026, 10, 6, 12, tzinfo=UTC),
        )
        report = owner_command(
            reports,
            "create",
            OwnerRentReportCommand(
                lease["id"],
                owner.id,
                "2026-01-15",
                100000,
                "cash",
                str(uuid4()),
                "2026-10-06T12:00:00+00:00",
            ),
        )
        source = Path(self.temp.name) / "owner-evidence.txt"
        source.write_text("Owner statement", encoding="utf-8")
        files = FileService(
            self.workspace,
            FilesystemContentStore(self.workspace.paths.files),
            SQLiteFileUnitOfWork(self.db, recorder),
            link_validators=(
                OwnerRentReportFileLinkValidator(
                    SQLiteOwnerRentReportFileLinkFacts(), SQLiteFileLinkReader()
                ),
            ),
        )
        files.add(
            source,
            "owner-evidence.txt",
            "text/plain",
            entity_type="owner_rent_report",
            entity_id=report["id"],
            purpose="owner_statement",
        )
        before = self.reader.summary(self.query)
        owner_command(
            reports,
            "verify",
            report["id"],
            VerifyOwnerRentReportCommand(True, "Matches recorded receipt", receipt["id"]),
            str(uuid4()),
        )
        after = self.reader.summary(self.query)
        self.assertEqual(before.operating, after.operating)
        self.assertEqual(after.operating.rent_receipt_count, 1)
        self.assertEqual(after.operating.rent_received, "1000.00")
        contribution = self.reader.sources(self.query, Metric.RENT).items[0]
        self.assertEqual(contribution.party_id, owner.id)
        self.assertEqual(contribution.property_id, property_record.id)
        page = self.reader.properties(self.query)
        self.assertEqual(
            sum(Decimal(row.operating.rent_received) for row in page.items), Decimal("1000.00")
        )

    def test_database_currency_and_overflow_errors_are_sanitized(self):
        self.record_sources(False)
        raw = self.finance.unit_of_work.engine.raw_connection()
        try:
            raw.execute("PRAGMA ignore_check_constraints=ON")
            raw.execute(
                "UPDATE rent_receipts SET currency_code='EUR' WHERE id=?", (self.receipt["id"],)
            )
            raw.commit()
        finally:
            raw.close()
        with self.assertRaises(MoneyUnavailable):
            self.reader.summary(self.query)
        with self.finance.unit_of_work.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE rent_receipts SET currency_code='USD', amount_minor=9223372036854775807 WHERE id=:id"
                ),
                {"id": self.receipt["id"]},
            )
            connection.execute(
                text(
                    "INSERT INTO rent_receipts (id,lease_id,idempotency_key,received_on,amount_minor,currency_code,payment_method_kind,created_at) VALUES (:id,:lease,:key,'2026-01-15',1,'USD','cash','2026-01-15T12:00:00+00:00')"
                ),
                {"id": str(uuid4()), "lease": self.lease["id"], "key": str(uuid4())},
            )
        with self.assertRaisesRegex(MoneyUnavailable, "could not be read safely") as error:
            self.reader.summary(self.query)
        self.assertNotIn("SELECT", str(error.exception))

    def test_completed_zero_obligation_does_not_implicitly_complete_an_approved_settlement(self):
        self.record_sources()
        deposit_command(
            self.deposits,
            "record_refund",
            self.settlement["id"],
            DepositRefundCommand(
                str(uuid4()),
                self.tenant["id"],
                "2026-02-20",
                "500.00",
                "USD",
            ),
        )
        account = self.reader.deposit_accounts(self.query).items[0]
        self.assertEqual(account.recorded_deposit_obligation, "0.00")
        self.assertEqual(account.settlement_status, "approved")
        self.assertTrue(account.unresolved)

    def test_paging_unicode_names_scope_and_query_budgets(self):
        recorder = AuditRecorder(SQLiteAuditRepository(self.db))
        portfolio = PortfolioService(
            SQLitePortfolioUnitOfWork(self.db, recorder),
            time_zone_resolver=BundledAddressTimeZoneResolver(),
        )
        counts = []
        for target in (1, 50):
            if target == 50:
                for index in range(49):
                    inventory_command(
                        portfolio,
                        "create_property",
                        PropertyCreateCommand(
                            f"Éclair {index:02d}",
                            "1 Main Street",
                            "Portland",
                            "US",
                            "single_family_home",
                            (OwnershipInput("local_operator"),),
                            region="OR",
                        ),
                    )
            result, sql = self.count_queries(
                lambda: self.reader.properties(replace(self.query, page_size=1))
            )
            self.assertEqual(result.matching_total, target)
            self.assertEqual(len(result.items), 1)
            self.assertLessEqual(len(sql), 16)
            counts.append(len(sql))
        self.assertEqual(*counts)
        identities = []
        query = replace(self.query, page_size=7)
        while True:
            page = self.reader.properties(query)
            identities.extend(item.property_id for item in page.items)
            if not page.next_cursor:
                break
            query = replace(query, cursor=page.next_cursor)
        self.assertEqual(len(identities), 50)
        self.assertEqual(len(set(identities)), 50)
        summary, sql = self.count_queries(lambda: self.reader.summary(self.query))
        self.assertLessEqual(len(sql), 12)
        self.assertEqual(summary.scope.property_count, 50)

    def test_source_pages_do_not_skip_and_invalidate_on_audit_or_epoch_change(self):
        self.record_sources(False)
        query = replace(self.query, page_size=1)
        first, sql = self.count_queries(lambda: self.reader.sources(query, Metric.REMAINDER))
        self.assertLessEqual(len(sql), 8)
        second = self.reader.sources(replace(query, cursor=first.next_cursor), Metric.REMAINDER)
        self.assertEqual(
            {first.items[0].source_id, second.items[0].source_id},
            {self.receipt["id"], self.expense["id"]},
        )
        self.assertIsNone(second.next_cursor)
        with self.assertRaises(MoneyViewChanged):
            self.reader.sources(
                replace(query, cursor=first.next_cursor, property_state="active"), Metric.REMAINDER
            )
        other = self.make_reader(self.db, (self.identity[0], str(uuid4())))
        with self.assertRaises(MoneyViewChanged):
            other.sources(replace(query, cursor=first.next_cursor), Metric.REMAINDER)
        rent_command(
            self.finance, "void_receipt", self.receipt["id"], VoidCommand(True, "Correction")
        )
        with self.assertRaises(MoneyViewChanged):
            self.reader.sources(replace(query, cursor=first.next_cursor), Metric.REMAINDER)

    def test_one_snapshot_survives_concurrent_financial_change(self):
        self.record_sources(False)
        with self.finance.unit_of_work.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        fired = []

        def mutate(_, __, sql, *args):
            if not fired and "max(rowid)" in sql:
                fired.append(True)
                rent_command(
                    self.finance,
                    "void_receipt",
                    self.receipt["id"],
                    VoidCommand(True, "Concurrent correction"),
                )

        engine = self.reader.unit_of_work.engine
        event.listen(engine, "after_cursor_execute", mutate)
        try:
            summary = self.reader.summary(self.query)
        finally:
            event.remove(engine, "after_cursor_execute", mutate)
        self.assertTrue(fired)
        self.assertEqual(summary.operating.rent_received, "1200.00")
        self.assertEqual(self.reader.summary(self.query).operating.rent_received, "0.00")

    def test_invalid_inputs_integrity_and_integer_overflow_fail_closed(self):
        for fields in (
            {"through_on": "2025-12-31"},
            {"through_on": "2040-01-01"},
            {"page_size": True},
            {"property_ids": ("bad",)},
            {"property_state": "draft"},
            {"source_revision": "invalid"},
        ):
            with self.assertRaises(MoneyError):
                replace(self.query, **fields)
        with self.assertRaises(MoneyError):
            self.reader.properties(replace(self.query, cursor="invalid"))
        with self.assertRaises(MoneyUnavailable):
            money(2**63)
        self.record_sources(False)
        raw = self.finance.unit_of_work.engine.raw_connection()
        try:
            raw.execute("PRAGMA foreign_keys=OFF")
            raw.execute(
                "UPDATE rent_receipts SET lease_id=? WHERE id=?", (str(uuid4()), self.receipt["id"])
            )
            raw.commit()
        finally:
            raw.close()
        with self.assertRaises(MoneyUnavailable):
            self.reader.summary(self.query)

    def test_api_contract_and_unknown_filters(self):
        with TestClient(create_app(self.workspace.config.config_path)) as client:
            params = {"fromOn": "2026-01-01", "throughOn": "2026-01-31"}
            response = client.get("/api/money/summary", params=params)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["operating"]["rentReceived"], "0.00")
            self.assertEqual(response.json()["periodBasis"], "property_local_business_date")
            for path in (
                "/api/money/properties",
                "/api/money/deposit-accounts",
                f"/api/properties/{self.property_id}/money-summary",
            ):
                response = client.get(path, params=params)
                self.assertEqual(response.status_code, 200, response.text)
            response = client.get(
                "/api/money/sources", params={**params, "metric": "operatingRemainder"}
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["total"], "0.00")
            self.assertEqual(
                client.get(
                    "/api/money/summary", params={**params, "unexpected": "yes"}
                ).status_code,
                422,
            )
            self.assertEqual(
                client.get(
                    "/api/money/summary", params={**params, "propertyIds": "bad"}
                ).status_code,
                422,
            )
            self.assertEqual(
                client.get(
                    "/api/money/properties", params={**params, "cursor": "x" * 4097}
                ).status_code,
                413,
            )
            self.assertEqual(
                client.get(f"/api/properties/{uuid4()}/money-summary", params=params).status_code,
                404,
            )
            schema = client.get("/openapi.json").json()
            self.assertEqual(
                schema["paths"]["/api/money/summary"]["get"]["operationId"], "getMoneySummary"
            )
            revision = client.get("/api/money/summary", params=params).json()["sourceRevision"]
            client.app.state.workspace_runtime.refresh()
            response = client.get(
                "/api/money/summary", params={**params, "sourceRevision": revision}
            )
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"]["code"], "money_view_changed")

    def test_direct_readers_reject_failed_refresh_until_validation_succeeds(self):
        with TestClient(create_app(self.workspace.config.config_path)) as client:
            reader = client.app.state.money_summary_reader
            runtime = client.app.state.workspace_runtime
            original_revision = reader.summary(self.query).source_revision
            with patch.object(
                runtime.service, "open", side_effect=WorkspaceError("Validation failed.")
            ):
                runtime.refresh()
            self.assertFalse(runtime.ready)
            self.assert_direct_readers_unavailable(reader)

            # Merely retrying a failed validation must not re-enable reads.
            with patch.object(
                runtime.service, "open", side_effect=WorkspaceError("Still invalid.")
            ):
                runtime.refresh()
            self.assert_direct_readers_unavailable(reader)
            runtime.refresh()
            self.assertTrue(runtime.ready)
            self.assert_direct_readers_available(reader)
            self.assertNotEqual(reader.summary(self.query).source_revision, original_revision)

    def test_direct_readers_reject_stopped_runtime_until_successful_restart(self):
        with TestClient(create_app(self.workspace.config.config_path)) as client:
            reader = client.app.state.money_summary_reader
            runtime = client.app.state.workspace_runtime
            original_revision = reader.summary(self.query).source_revision
            runtime.stop()
            self.assertFalse(runtime.ready)
            self.assert_direct_readers_unavailable(reader)
            runtime.refresh()  # No writer lock: refresh alone cannot restore readiness.
            self.assert_direct_readers_unavailable(reader)
            runtime.start()
            self.assertTrue(runtime.ready)
            self.assert_direct_readers_available(reader)
            self.assertNotEqual(reader.summary(self.query).source_revision, original_revision)

    def direct_reader_operations(self, reader):
        return {
            "summary": lambda: reader.summary(self.query),
            "properties": lambda: reader.properties(self.query),
            "sources": lambda: reader.sources(self.query, Metric.REMAINDER),
            "deposit_accounts": lambda: reader.deposit_accounts(self.query),
        }

    def assert_direct_readers_unavailable(self, reader):
        with patch.object(reader.unit_of_work, "read", wraps=reader.unit_of_work.read) as read:
            for name, operation in self.direct_reader_operations(reader).items():
                with self.subTest(reader=name):
                    with self.assertRaises(MoneyWorkspaceUnavailable) as failure:
                        operation()
                    self.assertEqual(failure.exception.status_code, 503)
                    self.assertEqual(failure.exception.code, "workspace_unavailable")
            read.assert_not_called()

    def assert_direct_readers_available(self, reader):
        for name, operation in self.direct_reader_operations(reader).items():
            with self.subTest(reader=name):
                self.assertIsNotNone(operation())

    @fast_backup_encryption()
    def test_backup_restore_reproduces_money_and_invalidates_old_cursor(self):
        self.record_sources()
        before = self.reader.summary(self.query)
        sources = self.reader.sources(replace(self.query, page_size=1), Metric.REMAINDER)
        backups = BackupService(
            self.workspace,
            AuditRecorder(SQLiteAuditRepository(self.db)),
            lambda db: AuditRecorder(SQLiteAuditRepository(db)),
        )
        archive = backups.create_backup(
            "a sufficiently long backup passphrase",
            output_path=self.db.parents[2] / "money.epm-backup",
        )
        restored_path = self.db.parents[2] / "restored-money"
        backups.restore(
            archive.archive_path, "a sufficiently long backup passphrase", restored_path
        )
        restored = self.make_reader(
            restored_path / "database" / "property-management.sqlite",
            (self.identity[0], str(uuid4())),
        )
        after = restored.summary(self.query)
        restored_engine = create_sqlite_engine(
            restored_path / "database" / "property-management.sqlite"
        )
        try:
            with (
                self.finance.unit_of_work.engine.connect() as original,
                restored_engine.connect() as restored_connection,
            ):
                for table, order in (
                    ("finance_command_operations", "sequence"),
                    ("finance_command_revisions", "scope_kind, scope_id"),
                ):
                    query = f"SELECT * FROM {table} ORDER BY {order}"
                    self.assertEqual(
                        original.exec_driver_sql(query).all(),
                        restored_connection.exec_driver_sql(query).all(),
                    )
        finally:
            restored_engine.dispose()
        self.assertEqual(before.operating, after.operating)
        self.assertEqual(before.deposit_activity, after.deposit_activity)
        self.assertEqual(before.deposit_obligations, after.deposit_obligations)
        self.assertEqual(
            self.reader.sources(self.query, Metric.OBLIGATION).items,
            restored.sources(self.query, Metric.OBLIGATION).items,
        )
        with self.assertRaises(MoneyViewChanged):
            restored.sources(
                replace(self.query, page_size=1, cursor=sources.next_cursor), Metric.REMAINDER
            )

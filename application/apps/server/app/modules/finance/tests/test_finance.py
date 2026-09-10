from __future__ import annotations

import tempfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import unittest
from uuid import uuid4
from sqlalchemy import text

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.finance.application.service import FinanceService, _boundary_extension_piece, _schedule
from app.modules.finance.api.router import ExpectationResponse
from app.modules.finance.application.ports import LeaseTermFinanceSnapshot
from app.modules.finance.domain.models import FinanceConflictError, FinanceError, RecordReceiptCommand, ReceiptAllocationCommand, RentExpectation, SynchronizeExpectationsCommand, VoidCommand
from app.modules.finance.infrastructure.unit_of_work import SQLiteFinanceUnitOfWork
from app.modules.leases.application.service import LeaseCreateCommand, LeaseService, ParticipantCommand, TermCommand
from app.modules.leases.infrastructure.finance_operations import SQLiteLeaseFinanceOperations
from app.modules.leases.infrastructure.unit_of_work import SQLiteLeaseUnitOfWork
from app.modules.parties.application.service import SharedPartyFactory
from app.modules.parties.infrastructure.unit_of_work import SQLitePartyOperations, SQLitePartyReadOperations
from app.modules.portfolio.application.service import OwnershipInput, PortfolioService, PropertyCreateCommand
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioLeaseOperations, SQLitePortfolioUnitOfWork
from app.modules.portfolio.infrastructure.finance_operations import SQLitePortfolioFinanceOperations
from app.modules.tenants.application.service import TenantCreateCommand, TenantService
from app.modules.tenants.infrastructure.unit_of_work import SQLiteTenantProfileAvailability, SQLiteTenantUnitOfWork
from app.modules.leases.infrastructure.unit_of_work import SQLiteLeaseParticipationGuard
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig


class FinanceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); root=Path(self.temp.name)
        self.workspace=WorkspaceService(LocalConfig(root/"config.json",root/"workspace")); self.workspace.initialize(); db=self.workspace.paths.database
        recorder=AuditRecorder(SQLiteAuditRepository(db)); party_operations=SQLitePartyOperations(db)
        portfolio=PortfolioService(SQLitePortfolioUnitOfWork(db,recorder),time_zone_resolver=BundledAddressTimeZoneResolver())
        property_record=portfolio.create_property(PropertyCreateCommand("Rent home","1 Main Street","Portland","US","single_family_home",(OwnershipInput("local_operator"),),region="OR")); space_id=portfolio.get_property(property_record.id)["spaces"][0]["id"]
        tenant=TenantService(SQLiteTenantUnitOfWork(db,recorder,SQLiteLeaseParticipationGuard(),party_operations,SQLitePartyReadOperations(party_operations)),SharedPartyFactory()).create(TenantCreateCommand("individual","Rent Tenant"))
        leases=LeaseService(SQLiteLeaseUnitOfWork(db,recorder,SQLiteTenantProfileAvailability(),SQLitePortfolioLeaseOperations(db)))
        today=date.today(); lease=leases.create(LeaseCreateCommand(space_id,"residential",today,today+timedelta(days=90),today,TermCommand(100_000,"USD","monthly",1,0),(ParticipantCommand(tenant["id"],"primary_tenant"),))); self.lease=leases.execute(lease["id"],executed_on=today,confirmed=True)
        self.finance=FinanceService(SQLiteFinanceUnitOfWork(db,recorder,SQLiteLeaseFinanceOperations(SQLitePortfolioFinanceOperations()),party_operations),now=lambda:datetime.now(UTC))
    def test_synchronize_is_idempotent_and_receipt_settles_expectation(self):
        term=self.lease["terms"][0]; command=SynchronizeExpectationsCommand(term["id"],(date.today()+timedelta(days=60)).isoformat(),date.today().replace(day=1).isoformat())
        rows=self.finance.synchronize(self.lease["id"],command); self.assertTrue(rows); self.assertEqual([],self.finance.synchronize(self.lease["id"],command))
        expectation=rows[0]; receipt=self.finance.record_receipt(RecordReceiptCommand(self.lease["id"],str(uuid4()),date.today().isoformat(),expectation["expectedAmountMinor"],"USD",(ReceiptAllocationCommand(expectation["id"],expectation["expectedAmountMinor"]),)))
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

    def test_replacement_chain_filter_returns_complete_lineage(self):
        term = self.lease["terms"][0]
        expectation = self.finance.synchronize(self.lease["id"], SynchronizeExpectationsCommand(term["id"], (date.today() + timedelta(days=60)).isoformat(), date.today().replace(day=1).isoformat()))[0]
        def record(replaces=None):
            return self.finance.record_receipt(RecordReceiptCommand(self.lease["id"], str(uuid4()), date.today().isoformat(), expectation["expectedAmountMinor"], "USD", (ReceiptAllocationCommand(expectation["id"], expectation["expectedAmountMinor"]),), replaces_receipt_id=replaces))
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

"""Focused proofs for FIN-009 Slice 2: deterministic preview engine & query budget."""

import unittest
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import event, text

from app.bootstrap.api import create_app
from app.modules.finance.application.late_fee_ports import PendingPaymentSummary
from app.modules.finance.application.late_fee_service import LateFeeService
from app.modules.finance.application.prepaid_check_service import PrepaidCheckService
from app.modules.finance.domain.late_fee_calculator import (
    PriorAssessmentFact,
    calculate_late_fee_preview,
)
from app.modules.finance.domain.late_fee_models import (
    CreateLateFeePolicyCommand,
    LateFeePolicyVersion,
)
from app.modules.finance.domain.models import (
    FinanceValidationError,
    PrepaidCheckCommand,
    ReceiptAllocationCommand,
    RecordReceiptCommand,
    RentExpectation,
    SynchronizeExpectationsCommand,
    VoidCommand,
)
from app.modules.finance.infrastructure.unit_of_work import SQLiteFinanceUnitOfWork
from app.modules.finance.tests import test_finance as fixtures
from app.modules.tasks.infrastructure.transaction_operations import SQLiteTaskTransactionOperations
from app.platform.testing_client import LocalApiClient as TestClient


class _StubPendingPaymentReader:
    def __init__(self, by_expectation: dict[str, PendingPaymentSummary]):
        self._by_expectation = by_expectation

    def processing_for_expectations(self, connection, expectation_ids):
        return {
            exp_id: self._by_expectation[exp_id]
            for exp_id in expectation_ids
            if exp_id in self._by_expectation
        }

    def processing_for_assessments(self, connection, assessment_ids):
        return {}


class LateFeeCalculatorUnitTests(unittest.TestCase):
    def _expectation(
        self, *, due_on="2026-03-01", expected_amount_minor=100_000, is_prorated=False
    ):
        return RentExpectation(
            id=str(uuid4()),
            lease_id=str(uuid4()),
            lease_term_id=str(uuid4()),
            period_starts_on=due_on,
            period_ends_on="2026-03-31",
            due_on=due_on,
            expected_amount_minor=expected_amount_minor,
            currency_code="USD",
            payment_frequency="monthly",
            schedule_anchor_on=due_on,
            is_prorated=is_prorated,
            proration_numerator_days=15 if is_prorated else None,
            proration_denominator_days=31 if is_prorated else None,
            responsibility_boundary_on=None,
            responsibility_override_reason=None,
            voided_at=None,
            void_reason=None,
            created_at="2026-01-01T00:00:00+00:00",
        )

    def _policy(self, **overrides):
        base = dict(
            id=str(uuid4()),
            lease_id=str(uuid4()),
            lease_term_id=None,
            version_number=1,
            effective_on="2026-01-01",
            ends_on=None,
            rule_basis="Lease Section 5(b)",
            grace_period_days=5,
            calculation_basis="unpaid_rent_at_grace_end",
            formula_kind="fixed_flat",
            flat_amount_minor=5000,
            percentage_bps=None,
            daily_amount_minor=None,
            max_accrual_days=None,
            per_period_cap_minor=None,
            per_period_min_minor=None,
            minimum_unpaid_threshold_minor=0,
            rounding_mode="half_up",
            applies_to_prorated_periods=False,
            status="active",
            supersedes_policy_version_id=None,
            notes=None,
            operator_confirmed_at="2026-01-01T00:00:00+00:00",
            operator_confirmed_by_actor="local_operator",
            voided_at=None,
            void_reason=None,
            created_at="2026-01-01T00:00:00+00:00",
        )
        base.update(overrides)
        return LateFeePolicyVersion(**base)

    def test_percentage_once_half_up_and_floor_exact_integer_rounding(self):
        exp = self._expectation(expected_amount_minor=1_000)
        # 1000 * 125 / 10000 = 12.5 cents -> half_up=13, floor=12
        half_up_policy = self._policy(
            formula_kind="percentage_once",
            flat_amount_minor=None,
            percentage_bps=125,
            rounding_mode="half_up",
        )
        floor_policy = self._policy(
            formula_kind="percentage_once",
            flat_amount_minor=None,
            percentage_bps=125,
            rounding_mode="floor",
        )
        res_half = calculate_late_fee_preview(
            lease_id=exp.lease_id,
            expectation=exp,
            policy=half_up_policy,
            as_of_date="2026-03-07",
            time_zone="America/Los_Angeles",
            rent_ledger_revision=1,
            paid_through_grace_minor=0,
            paid_after_grace_through_as_of_minor=0,
        )
        res_floor = calculate_late_fee_preview(
            lease_id=exp.lease_id,
            expectation=exp,
            policy=floor_policy,
            as_of_date="2026-03-07",
            time_zone="America/Los_Angeles",
            rent_ledger_revision=1,
            paid_through_grace_minor=0,
            paid_after_grace_through_as_of_minor=0,
        )
        self.assertEqual(res_half["eligibilityStatus"], "eligible")
        self.assertEqual(res_half["calculatedAmountMinor"], 13)
        self.assertEqual(res_floor["calculatedAmountMinor"], 12)
        self.assertIsNotNone(res_half["previewFingerprint"])
        self.assertNotEqual(res_half["previewFingerprint"], res_floor["previewFingerprint"])

    def test_fixed_plus_daily_flat_d13_and_incremental_occurrences_with_caps(self):
        exp = self._expectation(due_on="2026-03-01", expected_amount_minor=200_000)
        # DST spring-forward occurs 2026-03-08 in America/Los_Angeles; due 03-01 + 5d = 03-06,
        # first eligible = 03-07.
        policy = self._policy(
            formula_kind="fixed_plus_daily_flat",
            flat_amount_minor=5000,
            daily_amount_minor=1000,
            max_accrual_days=5,
            per_period_cap_minor=8500,
        )
        # Day 1 (2026-03-07): flat only (5000 + 0 * 1000 = 5000).
        day1 = calculate_late_fee_preview(
            lease_id=exp.lease_id,
            expectation=exp,
            policy=policy,
            as_of_date="2026-03-07",
            time_zone="America/Los_Angeles",
            rent_ledger_revision=1,
            paid_through_grace_minor=0,
            paid_after_grace_through_as_of_minor=0,
        )
        self.assertEqual(day1["calculatedAmountMinor"], 5000)
        self.assertEqual(day1["accrualStartsOn"], "2026-03-07")
        self.assertEqual(day1["accrualEndsOn"], "2026-03-07")
        self.assertEqual(day1["accrualDays"], 1)

        # Day 3 (2026-03-09, crossing DST spring-forward): 5000 + 2 * 1000 = 7000.
        day3 = calculate_late_fee_preview(
            lease_id=exp.lease_id,
            expectation=exp,
            policy=policy,
            as_of_date="2026-03-09",
            time_zone="America/Los_Angeles",
            rent_ledger_revision=1,
            paid_through_grace_minor=0,
            paid_after_grace_through_as_of_minor=0,
        )
        self.assertEqual(day3["calculatedAmountMinor"], 7000)
        self.assertEqual(day3["accrualDays"], 3)

        # Incremental occurrence 2 after occurrence 1 covered [03-07, 03-09] for 7000:
        # At 03-15, raw_days = 6 (03-10..03-15), max_accrual_days remaining = 2 -> [03-10, 03-11],
        # raw = 2 * 1000 = 2000, capped by remaining_cap = 8500 - 7000 = 1500!
        prior = (PriorAssessmentFact(1, "2026-03-07", "2026-03-09", 3, 7000),)
        occ2 = calculate_late_fee_preview(
            lease_id=exp.lease_id,
            expectation=exp,
            policy=policy,
            as_of_date="2026-03-15",
            time_zone="America/Los_Angeles",
            rent_ledger_revision=2,
            paid_through_grace_minor=0,
            paid_after_grace_through_as_of_minor=0,
            active_assessments=prior,
        )
        self.assertEqual(occ2["occurrenceNumber"], 2)
        self.assertEqual(occ2["accrualStartsOn"], "2026-03-10")
        self.assertEqual(occ2["accrualEndsOn"], "2026-03-11")
        self.assertEqual(occ2["accrualDays"], 2)
        self.assertEqual(occ2["calculatedAmountMinor"], 1500)

        # Once occurrence 2 (1500) is assessed, cumulative cap & max days are reached.
        prior_full = (
            PriorAssessmentFact(1, "2026-03-07", "2026-03-09", 3, 7000),
            PriorAssessmentFact(2, "2026-03-10", "2026-03-11", 2, 1500),
        )
        capped = calculate_late_fee_preview(
            lease_id=exp.lease_id,
            expectation=exp,
            policy=policy,
            as_of_date="2026-03-15",
            time_zone="America/Los_Angeles",
            rent_ledger_revision=3,
            paid_through_grace_minor=0,
            paid_after_grace_through_as_of_minor=0,
            active_assessments=prior_full,
        )
        self.assertEqual(capped["eligibilityStatus"], "max_accrual_days_reached")
        self.assertEqual(capped["calculatedAmountMinor"], 0)
        self.assertIsNone(capped["previewFingerprint"])

    def test_calculation_basis_after_grace_payment_threshold_and_proration(self):
        exp = self._expectation(expected_amount_minor=100_000)
        # Paid 40_000 before grace end, 60_000 after grace end (now fully paid).
        grace_basis = self._policy(
            formula_kind="percentage_once",
            flat_amount_minor=None,
            percentage_bps=500,
            calculation_basis="unpaid_rent_at_grace_end",
        )
        current_basis = self._policy(
            formula_kind="percentage_once",
            flat_amount_minor=None,
            percentage_bps=500,
            calculation_basis="current_unpaid_rent",
        )
        scheduled_basis = self._policy(
            formula_kind="percentage_once",
            flat_amount_minor=None,
            percentage_bps=500,
            calculation_basis="scheduled_rent",
        )
        r_grace = calculate_late_fee_preview(
            lease_id=exp.lease_id,
            expectation=exp,
            policy=grace_basis,
            as_of_date="2026-03-10",
            time_zone="America/Los_Angeles",
            rent_ledger_revision=1,
            paid_through_grace_minor=40_000,
            paid_after_grace_through_as_of_minor=60_000,
        )
        r_current = calculate_late_fee_preview(
            lease_id=exp.lease_id,
            expectation=exp,
            policy=current_basis,
            as_of_date="2026-03-10",
            time_zone="America/Los_Angeles",
            rent_ledger_revision=1,
            paid_through_grace_minor=40_000,
            paid_after_grace_through_as_of_minor=60_000,
        )
        r_scheduled = calculate_late_fee_preview(
            lease_id=exp.lease_id,
            expectation=exp,
            policy=scheduled_basis,
            as_of_date="2026-03-10",
            time_zone="America/Los_Angeles",
            rent_ledger_revision=1,
            paid_through_grace_minor=40_000,
            paid_after_grace_through_as_of_minor=60_000,
        )
        self.assertEqual(r_grace["calculatedAmountMinor"], 3000)  # 5% of 60_000
        self.assertEqual(r_current["eligibilityStatus"], "paid_in_full")
        self.assertEqual(r_scheduled["calculatedAmountMinor"], 5000)  # 5% of 100_000

        # Prorated period excluded by policy.
        prorated_exp = self._expectation(is_prorated=True)
        r_prorated = calculate_late_fee_preview(
            lease_id=prorated_exp.lease_id,
            expectation=prorated_exp,
            policy=grace_basis,
            as_of_date="2026-03-10",
            time_zone="America/Los_Angeles",
            rent_ledger_revision=1,
            paid_through_grace_minor=0,
            paid_after_grace_through_as_of_minor=0,
        )
        self.assertEqual(r_prorated["eligibilityStatus"], "excluded_prorated_period")


class LateFeePreviewIntegrationTests(unittest.TestCase):
    def setUp(self):
        fixtures.FinanceWorkflowTests.setUp(self)
        self.lease_id = self.lease["id"]
        self.term_id = self.lease["terms"][0]["id"]
        self.engine = self.finance.unit_of_work.engine
        self.sync = self.finance.synchronize(
            self.lease_id,
            SynchronizeExpectationsCommand(
                self.term_id,
                (date.today() + timedelta(days=750)).isoformat(),
                date.today().replace(day=1).isoformat(),
            ),
            expected_revision=0,
            idempotency_key=str(uuid4()),
        )
        self.expectations = self.sync["items"]
        self.first_exp = next(item for item in self.expectations if not item["isProrated"])
        self.rev = self.sync["rentLedgerRevision"]

    def test_timezone_boundary_returned_payment_warnings_and_http_preview(self):
        due = date.fromisoformat(self.first_exp["dueOn"])
        grace_end = due + timedelta(days=5)
        first_eligible = grace_end + timedelta(days=1)

        # Configure a 5% percentage_once policy with 5-day grace period.
        created = LateFeeService(self.finance.unit_of_work).create_policy(
            self.lease_id,
            CreateLateFeePolicyCommand(
                effective_on=(due - timedelta(days=30)).isoformat(),
                rule_basis="Lease Section 5(b)",
                grace_period_days=5,
                calculation_basis="unpaid_rent_at_grace_end",
                formula_kind="percentage_once",
                percentage_bps=500,
                rounding_mode="half_up",
                applies_to_prorated_periods=False,
                operator_confirmed=True,
            ),
            expected_revision=self.rev,
            idempotency_key=str(uuid4()),
        )
        rev = created["rentLedgerRevision"]

        # Schedule a FIN-007 prepaid check on first_exp (must NOT reduce unpaid rent).
        prepaid_uow = SQLiteFinanceUnitOfWork(
            self.workspace.paths.database,
            self.finance.unit_of_work.recorder,
            self.finance.unit_of_work.lease_operations,
            self.finance.unit_of_work.portfolio_operations,
            self.finance.unit_of_work.party_operations,
            SQLiteTaskTransactionOperations(),
        )
        prepaid_service = PrepaidCheckService(
            prepaid_uow,
            now=lambda: datetime.combine(due, datetime.min.time(), UTC) + timedelta(hours=12),
        )
        prepaid = prepaid_service.create(
            PrepaidCheckCommand(
                self.first_exp["id"],
                self.lease["participants"][0]["tenantPartyId"],
                due.isoformat(),
                (due + timedelta(days=2)).isoformat(),
                "Check •••• 1234",
                str(uuid4()),
            ),
            expected_revision=rev,
        )
        rev = prepaid["rentLedgerRevision"]

        # Wire a stub PendingPaymentReader to verify processing warnings + acknowledgment flag.
        uow_with_pending = SQLiteFinanceUnitOfWork(
            self.workspace.paths.database,
            self.finance.unit_of_work.recorder,
            self.finance.unit_of_work.lease_operations,
            self.finance.unit_of_work.portfolio_operations,
            self.finance.unit_of_work.party_operations,
            self.finance.unit_of_work.task_operations,
            pending_payment_reader=_StubPendingPaymentReader(
                {
                    self.first_exp["id"]: PendingPaymentSummary(
                        count=1, total_minor=50_000, earliest_submitted_on=due.isoformat()
                    )
                }
            ),
        )
        # Property timezone is America/Los_Angeles (UTC-8 in Nov/Dec/Jan/Feb, UTC-7 in DST).
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("America/Los_Angeles")
        before_midnight = datetime.combine(first_eligible, datetime.min.time(), zone).astimezone(
            UTC
        ) - timedelta(seconds=1)
        at_midnight = datetime.combine(first_eligible, datetime.min.time(), zone).astimezone(UTC)

        # 1 second before property-local midnight: still within grace period!
        svc_before = LateFeeService(uow_with_pending, now=lambda: before_midnight)
        preview_before = svc_before.preview_late_fees(
            self.lease_id, rent_expectation_id=self.first_exp["id"]
        )
        self.assertEqual(preview_before["currentPropertyLocalDate"], grace_end.isoformat())
        self.assertEqual(preview_before["items"][0]["eligibilityStatus"], "within_grace_period")
        self.assertEqual(preview_before["items"][0]["calculatedAmountMinor"], 0)
        self.assertFalse(preview_before["futureProjection"])

        # Exactly at property-local midnight: eligible, with both prepaid & processing warnings!
        svc_at = LateFeeService(uow_with_pending, now=lambda: at_midnight)
        preview_at = svc_at.preview_late_fees(
            self.lease_id, rent_expectation_id=self.first_exp["id"]
        )
        item = preview_at["items"][0]
        self.assertEqual(preview_at["currentPropertyLocalDate"], first_eligible.isoformat())
        self.assertEqual(item["eligibilityStatus"], "eligible")
        self.assertEqual(
            item["calculatedAmountMinor"], self.first_exp["expectedAmountMinor"] * 500 // 10_000
        )
        self.assertEqual(item["scheduledPrepaidChecks"]["count"], 1)
        self.assertEqual(item["processingPayments"]["count"], 1)
        self.assertTrue(item["requiresProcessingAcknowledgment"])

        # Future-date preview horizon (D14): +31 days allowed, +32 days rejected.
        future_ok = svc_at.preview_late_fees(
            self.lease_id,
            as_of_date=(first_eligible + timedelta(days=31)).isoformat(),
            rent_expectation_id=self.first_exp["id"],
        )
        self.assertTrue(future_ok["futureProjection"])
        with self.assertRaises(FinanceValidationError):
            svc_at.preview_late_fees(
                self.lease_id,
                as_of_date=(first_eligible + timedelta(days=32)).isoformat(),
                rent_expectation_id=self.first_exp["id"],
            )

        # Voided/returned rent receipt restores unpaid rent cleanly.
        receipt = self.finance.record_receipt(
            RecordReceiptCommand(
                self.lease_id,
                str(uuid4()),
                date.today().isoformat(),
                self.first_exp["expectedAmountMinor"],
                "USD",
                (
                    ReceiptAllocationCommand(
                        self.first_exp["id"], self.first_exp["expectedAmountMinor"]
                    ),
                ),
                "bank_transfer",
            ),
            expected_revision=rev,
        )
        rev = receipt["rentLedgerRevision"]
        paid_preview = svc_at.preview_late_fees(
            self.lease_id, rent_expectation_id=self.first_exp["id"]
        )
        self.assertEqual(paid_preview["items"][0]["eligibilityStatus"], "paid_in_full")

        voided = self.finance.void_receipt(
            receipt["id"],
            VoidCommand(True, "ACH returned NSF"),
            expected_revision=rev,
            idempotency_key=str(uuid4()),
        )
        rev = voided["rentLedgerRevision"]
        returned_preview = svc_at.preview_late_fees(
            self.lease_id, rent_expectation_id=self.first_exp["id"]
        )
        self.assertEqual(returned_preview["items"][0]["eligibilityStatus"], "eligible")

        # HTTP POST /api/leases/{leaseId}/late-fees/preview works end-to-end and is read-only.
        with TestClient(create_app(self.config)) as client:
            resp = client.post(
                f"/api/leases/{self.lease_id}/late-fees/preview",
                json={
                    "asOfDate": first_eligible.isoformat(),
                    "rentExpectationId": self.first_exp["id"],
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertTrue(body["previewOnly"])
            self.assertEqual(body["rentLedgerRevision"], rev)
            self.assertEqual(body["items"][0]["eligibilityStatus"], "eligible")
            self.assertIsNotNone(body["items"][0]["previewFingerprint"])

    def test_preview_query_budget_at_most_8_selects_for_1_and_24_periods(self):
        # Seed additional active expectations so the lease has 24 open periods.
        last_due = date.fromisoformat(self.expectations[-1]["dueOn"])
        needed = 24 - len(self.expectations)
        with self.engine.begin() as conn:
            for idx in range(1, needed + 1):
                period_start = last_due + timedelta(days=31 * idx)
                period_end = period_start + timedelta(days=27)
                conn.execute(
                    text(
                        """
                        INSERT INTO rent_expectations (
                            id, lease_id, lease_term_id, period_starts_on, period_ends_on,
                            due_on, expected_amount_minor, currency_code, payment_frequency,
                            schedule_anchor_on, is_prorated, proration_numerator_days,
                            proration_denominator_days, responsibility_boundary_on,
                            responsibility_override_reason, voided_at, void_reason, created_at
                        ) VALUES (
                            :id, :lease_id, :term_id, :start, :end,
                            :start, 100000, 'USD', 'monthly',
                            :start, 0, NULL, NULL, NULL, NULL, NULL, NULL, :created_at
                        )
                        """
                    ),
                    {
                        "id": str(uuid4()),
                        "lease_id": self.lease_id,
                        "term_id": self.term_id,
                        "start": period_start.isoformat(),
                        "end": period_end.isoformat(),
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                )
        due = date.fromisoformat(self.expectations[0]["dueOn"])
        LateFeeService(self.finance.unit_of_work).create_policy(
            self.lease_id,
            CreateLateFeePolicyCommand(
                effective_on=(due - timedelta(days=30)).isoformat(),
                rule_basis="Lease Section 5(b)",
                grace_period_days=5,
                calculation_basis="unpaid_rent_at_grace_end",
                formula_kind="fixed_flat",
                flat_amount_minor=5000,
                rounding_mode="half_up",
                applies_to_prorated_periods=True,
                operator_confirmed=True,
            ),
            expected_revision=self.rev,
            idempotency_key=str(uuid4()),
        )
        svc = LateFeeService(self.finance.unit_of_work)

        def count_queries(rent_expectation_id):
            selects = []
            writes = []

            def listener(_conn, _cursor, statement, _params, _ctx, _many):
                verb = statement.lstrip().split()[0].upper()
                if verb == "SELECT":
                    selects.append(statement)
                elif verb in {"INSERT", "UPDATE", "DELETE"}:
                    writes.append(statement)

            event.listen(self.engine, "before_cursor_execute", listener)
            try:
                result = svc.preview_late_fees(
                    self.lease_id,
                    rent_expectation_id=rent_expectation_id,
                )
            finally:
                event.remove(self.engine, "before_cursor_execute", listener)
            return result, len(selects), len(writes)

        single_res, single_selects, single_writes = count_queries(self.first_exp["id"])
        batch_res, batch_selects, batch_writes = count_queries(None)

        self.assertEqual(len(single_res["items"]), 1)
        self.assertEqual(len(batch_res["items"]), 24)
        self.assertEqual(single_writes, 0)
        self.assertEqual(batch_writes, 0)
        self.assertLessEqual(single_selects, 8)
        self.assertLessEqual(batch_selects, 8)
        self.assertEqual(single_selects, batch_selects)

    def test_bulk_preview_filters_closed_ontime_periods_keeps_late_paid_and_supports_cursor(self):
        # Insert 26 additional expectations so we have 29 total; pay the first 25 on time,
        # pay #26 late (after grace), and leave #27..#29 open. Bulk preview must NOT be crowded out!
        due0 = date.fromisoformat(self.expectations[0]["dueOn"])
        base = date.fromisoformat(self.expectations[-1]["periodEndsOn"]) + timedelta(days=1)
        all_exps = list(self.expectations)
        with self.engine.begin() as conn:
            for offset in range(26):
                period_start = base + timedelta(days=30 * offset)
                period_end = period_start + timedelta(days=29)
                exp_id = str(uuid4())
                conn.execute(
                    text(
                        """
                        INSERT INTO rent_expectations (
                            id, lease_id, lease_term_id, period_starts_on, period_ends_on,
                            due_on, expected_amount_minor, currency_code, payment_frequency,
                            schedule_anchor_on, is_prorated, proration_numerator_days,
                            proration_denominator_days, responsibility_boundary_on,
                            responsibility_override_reason, voided_at, void_reason, created_at
                        ) VALUES (
                            :id, :lease_id, :term_id, :start, :end,
                            :start, 100000, 'USD', 'monthly',
                            :start, 0, NULL, NULL, NULL, NULL, NULL, NULL, :created_at
                        )
                        """
                    ),
                    {
                        "id": exp_id,
                        "lease_id": self.lease_id,
                        "term_id": self.term_id,
                        "start": period_start.isoformat(),
                        "end": period_end.isoformat(),
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                )
                all_exps.append(
                    {
                        "id": exp_id,
                        "dueOn": period_start.isoformat(),
                        "expectedAmountMinor": 100000,
                    }
                )
        policy_res = LateFeeService(self.finance.unit_of_work).create_policy(
            self.lease_id,
            CreateLateFeePolicyCommand(
                effective_on=(due0 - timedelta(days=30)).isoformat(),
                rule_basis="Lease Section 5(b)",
                grace_period_days=5,
                calculation_basis="unpaid_rent_at_grace_end",
                formula_kind="fixed_flat",
                flat_amount_minor=5000,
                rounding_mode="half_up",
                applies_to_prorated_periods=True,
                operator_confirmed=True,
            ),
            expected_revision=self.rev,
            idempotency_key=str(uuid4()),
        )
        rev = policy_res["rentLedgerRevision"]
        open_exp = all_exps[26]
        open_due = date.fromisoformat(open_exp["dueOn"])
        as_of_iso = (open_due + timedelta(days=10)).isoformat()

        def future_clock():
            return datetime.fromisoformat(f"{as_of_iso}T18:00:00+00:00")

        self.finance.now = future_clock
        for exp in all_exps[:25]:
            rec = self.finance.record_receipt(
                RecordReceiptCommand(
                    lease_id=self.lease_id,
                    idempotency_key=str(uuid4()),
                    received_on=exp["dueOn"],
                    amount_minor=exp["expectedAmountMinor"],
                    currency_code="USD",
                    allocations=(ReceiptAllocationCommand(exp["id"], exp["expectedAmountMinor"]),),
                    payment_method_kind="check",
                ),
                expected_revision=rev,
            )
            rev = rec["rentLedgerRevision"]
        # Period #26 (index 25): paid in full 7 days late (still eligible under unpaid_rent_at_grace_end!)
        late_paid_exp = all_exps[25]
        late_due = date.fromisoformat(late_paid_exp["dueOn"])
        late_rec = self.finance.record_receipt(
            RecordReceiptCommand(
                lease_id=self.lease_id,
                idempotency_key=str(uuid4()),
                received_on=(late_due + timedelta(days=7)).isoformat(),
                amount_minor=late_paid_exp["expectedAmountMinor"],
                currency_code="USD",
                allocations=(
                    ReceiptAllocationCommand(
                        late_paid_exp["id"], late_paid_exp["expectedAmountMinor"]
                    ),
                ),
                payment_method_kind="check",
            ),
            expected_revision=rev,
        )
        rev = late_rec["rentLedgerRevision"]

        svc = LateFeeService(self.finance.unit_of_work, now=future_clock)
        bulk = svc.preview_late_fees(self.lease_id, as_of_date=as_of_iso)
        returned_ids = [item["rentExpectationId"] for item in bulk["items"]]
        self.assertIn(late_paid_exp["id"], returned_ids)
        self.assertIn(open_exp["id"], returned_ids)
        self.assertNotIn(self.expectations[0]["id"], returned_ids)
        late_item = next(
            item for item in bulk["items"] if item["rentExpectationId"] == late_paid_exp["id"]
        )
        self.assertEqual(late_item["eligibilityStatus"], "eligible")
        self.assertEqual(late_item["calculatedAmountMinor"], 5000)


if __name__ == "__main__":
    unittest.main()

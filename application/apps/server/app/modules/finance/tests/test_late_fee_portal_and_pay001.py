"""Focused proofs for FIN-009 Slice 5: LateFeeReadPort scopes and PAY-001 contracts."""

import unittest
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.modules.finance.application.late_fee_ports import PendingPaymentSummary
from app.modules.finance.application.late_fee_service import LateFeeService
from app.modules.finance.application.pay001_late_fee_adapter import (
    apply_provider_payment_outcome_in_transaction,
    apply_provider_return_in_transaction,
    build_charge_allocation_preview,
    plan_autopay_occurrence,
)
from app.modules.finance.domain.late_fee_models import (
    AssessLateFeeCommand,
    CreateLateFeePolicyCommand,
    LateFeeReceiptAllocationCommand,
    RecordLateFeeReceiptCommand,
    VoidLateFeeAssessmentCommand,
    WaiveLateFeeCommand,
)
from app.modules.finance.domain.models import (
    FinanceValidationError,
    SynchronizeExpectationsCommand,
)
from app.modules.finance.domain.pay001_contracts import (
    ChargeAllocationTarget,
    ProviderPaymentOutcomeCommand,
    validate_partial_refund_attribution,
)
from app.modules.finance.infrastructure.late_fee_read_adapter import SQLiteLateFeeReadAdapter
from app.modules.finance.tests import test_finance as fixtures


class _StubPendingReader:
    def __init__(self, *, expectations=None, assessments=None):
        self._exp = expectations or {}
        self._ass = assessments or {}

    def processing_for_expectations(self, connection, expectation_ids):
        return {eid: self._exp[eid] for eid in expectation_ids if eid in self._exp}

    def processing_for_assessments(self, connection, assessment_ids):
        return {aid: self._ass[aid] for aid in assessment_ids if aid in self._ass}


class LateFeePortalAndPay001Slice5Tests(unittest.TestCase):
    def setUp(self):
        fixtures.FinanceWorkflowTests.setUp(self)
        self.lease_id = self.lease["id"]
        self.term_id = self.lease["terms"][0]["id"]
        self.engine = self.finance.unit_of_work.engine
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
        self.expectations = [item for item in self.sync["items"] if not item["isProrated"]]
        self.exp1 = self.expectations[0]
        self.exp2 = self.expectations[1]
        self.due1 = date.fromisoformat(self.exp1["dueOn"])
        self.due2 = date.fromisoformat(self.exp2["dueOn"])
        self.eligible_date = self.due2 + timedelta(days=6)
        self.eligible_instant = datetime.combine(
            self.eligible_date, datetime.min.time(), self.zone
        ).astimezone(UTC) + timedelta(hours=12)
        self.svc = LateFeeService(self.finance.unit_of_work, now=lambda: self.eligible_instant)

        policy = self.svc.create_policy(
            self.lease_id,
            CreateLateFeePolicyCommand(
                effective_on=(self.due1 - timedelta(days=30)).isoformat(),
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
        self.rev = policy["rentLedgerRevision"]

    def _assess(
        self, expectation_id: str, *, as_of_date: str | None = None, notes: str | None = None
    ):
        target_date = as_of_date or self.eligible_date.isoformat()
        preview = self.svc.preview_late_fees(
            self.lease_id, as_of_date=target_date, rent_expectation_id=expectation_id
        )
        assessed = self.svc.assess_late_fee(
            self.lease_id,
            AssessLateFeeCommand(
                rent_expectation_id=expectation_id,
                as_of_date=target_date,
                preview_fingerprint=preview["items"][0]["previewFingerprint"],
                operator_confirmed=True,
                internal_notes=notes,
            ),
            expected_revision=self.rev,
            idempotency_key=str(uuid4()),
        )
        self.rev = assessed["rentLedgerRevision"]
        return assessed

    def test_late_fee_read_port_cross_scope_privacy_and_consistency(self):
        active = self._assess(
            self.exp1["id"],
            as_of_date=(self.due1 + timedelta(days=6)).isoformat(),
            notes="Operator-only internal note about tenant call.",
        )
        waived = self.svc.waive_late_fee(
            active["id"],
            WaiveLateFeeCommand(
                waived_amount_minor=1500,
                waived_on=self.eligible_date.isoformat(),
                reason="One-time courtesy reduction.",
                confirmed=True,
                internal_notes="Internal manager approval note.",
            ),
            expected_revision=self.rev,
            idempotency_key=str(uuid4()),
        )
        self.rev = waived["rentLedgerRevision"]
        paid = self.svc.record_late_fee_receipt(
            self.lease_id,
            RecordLateFeeReceiptCommand(
                received_on=self.eligible_date.isoformat(),
                amount_minor=1000,
                currency_code="USD",
                allocations=(LateFeeReceiptAllocationCommand(active["id"], 1000),),
                payment_method_kind="check",
                masked_reference="Check •••• 1234",
            ),
            expected_revision=self.rev,
            idempotency_key=str(uuid4()),
        )
        self.rev = paid["rentLedgerRevision"]

        # Create and void a second assessment; tenant & owner must never see voided assessments.
        to_void = self._assess(self.exp2["id"], notes="Will be voided.")
        voided = self.svc.void_assessment(
            to_void["id"],
            VoidLateFeeAssessmentCommand(True, "Entered in error."),
            expected_revision=self.rev,
            idempotency_key=str(uuid4()),
        )
        self.rev = voided["rentLedgerRevision"]

        adapter = SQLiteLateFeeReadAdapter()
        with self.engine.connect() as conn:
            op_list = adapter.list_assessed_late_fees_for_lease(
                conn,
                lease_id=self.lease_id,
                scope="operator",
                as_of=self.eligible_instant,
                include_voided=True,
            )
            tenant_list = adapter.list_assessed_late_fees_for_lease(
                conn,
                lease_id=self.lease_id,
                scope="tenant",
                as_of=self.eligible_instant,
                include_voided=True,  # Must be ignored for tenant scope!
            )
            owner_list = adapter.list_assessed_late_fees_for_lease(
                conn,
                lease_id=self.lease_id,
                scope="owner",
                as_of=self.eligible_instant,
                include_voided=True,  # Must be ignored for owner scope!
            )
            self.assertEqual(len(op_list["items"]), 2)
            self.assertEqual(len(tenant_list["items"]), 1)
            self.assertEqual(len(owner_list["items"]), 1)

            op_item = adapter.get_assessed_late_fee(
                conn, assessment_id=active["id"], scope="operator", as_of=self.eligible_instant
            )
            t_item = adapter.get_assessed_late_fee(
                conn, assessment_id=active["id"], scope="tenant", as_of=self.eligible_instant
            )
            o_item = adapter.get_assessed_late_fee(
                conn, assessment_id=active["id"], scope="owner", as_of=self.eligible_instant
            )
            assert op_item and t_item and o_item

            # Single source of truth: identical cents, dates, basis, and math across all 3 scopes.
            for field in (
                "assessedAmountMinor",
                "waivedAmountMinor",
                "paidAmountMinor",
                "remainingBalanceMinor",
                "ruleBasisSnapshot",
                "calculationSteps",
                "timeZone",
                "asOfDate",
            ):
                self.assertEqual(op_item[field], t_item[field])
                self.assertEqual(op_item[field], o_item[field])

            # Privacy & redaction: tenant & owner never see internal notes or operator warnings.
            for private_field in (
                "internalNotes",
                "processingAcknowledgmentReason",
                "sourceDriftWarning",
                "assessedByActor",
                "voidReason",
                "allocations",
            ):
                self.assertNotIn(private_field, t_item)
                self.assertNotIn(private_field, o_item)
            self.assertNotIn("internalNotes", t_item["waivers"][0])
            self.assertNotIn("internalNotes", o_item["waivers"][0])
            self.assertEqual(t_item["waivers"][0]["reason"], "One-time courtesy reduction.")
            self.assertEqual(t_item["appliedFeePaymentTotalMinor"], 1000)
            self.assertEqual(t_item["appliedFeePaymentCount"], 1)
            self.assertEqual(o_item["collectedFeeTotalMinor"], 1000)
            self.assertEqual(o_item["collectedFeeReceiptCount"], 1)

            # Voided assessment is invisible to tenant and owner get_assessed_late_fee.
            self.assertIsNotNone(
                adapter.get_assessed_late_fee(
                    conn, assessment_id=to_void["id"], scope="operator", as_of=self.eligible_instant
                )
            )
            self.assertIsNone(
                adapter.get_assessed_late_fee(
                    conn, assessment_id=to_void["id"], scope="tenant", as_of=self.eligible_instant
                )
            )
            self.assertIsNone(
                adapter.get_assessed_late_fee(
                    conn, assessment_id=to_void["id"], scope="owner", as_of=self.eligible_instant
                )
            )

    def test_pay001_allocation_order_reservations_and_autopay_mandate_fence(self):
        fee1 = self._assess(self.exp1["id"], as_of_date=(self.due1 + timedelta(days=6)).isoformat())
        fee2 = self._assess(self.exp2["id"], as_of_date=self.eligible_date.isoformat())
        rent1 = self.exp1["expectedAmountMinor"]
        rent2 = self.exp2["expectedAmountMinor"]

        with self.engine.connect() as conn:
            # Full open preview allocates oldest rent first (exp1, exp2), then oldest fee (fee1, fee2).
            full = build_charge_allocation_preview(conn, lease_id=self.lease_id)
            self.assertEqual(
                [(a.charge_kind, a.target_id, a.amount_minor) for a in full.allocations[:4]],
                [
                    ("rent_expectation", self.exp1["id"], rent1),
                    ("rent_expectation", self.exp2["id"], rent2),
                    ("late_fee_assessment", fee1["id"], 5000),
                    ("late_fee_assessment", fee2["id"], 5000),
                ],
            )
            self.assertEqual(
                full.rent_total_minor, sum(e["expectedAmountMinor"] for e in self.sync["items"])
            )
            self.assertEqual(full.late_fee_total_minor, 10_000)

            # Partial payment covering exp1 + 2000 into exp2 never touches late fees.
            partial = build_charge_allocation_preview(
                conn, lease_id=self.lease_id, payment_amount_minor=rent1 + 2000
            )
            self.assertEqual(partial.rent_total_minor, rent1 + 2000)
            self.assertEqual(partial.late_fee_total_minor, 0)

            # PendingPaymentReader reservations reduce eligible amounts so in-flight cents aren't double-allocated.
            reader = _StubPendingReader(
                expectations={
                    self.exp1["id"]: PendingPaymentSummary(1, rent1, self.due1.isoformat())
                },
                assessments={
                    fee1["id"]: PendingPaymentSummary(1, 3000, self.eligible_date.isoformat())
                },
            )
            with_res = build_charge_allocation_preview(
                conn,
                lease_id=self.lease_id,
                payment_amount_minor=full.rent_total_minor - rent1 + 4000,
                pending_payment_reader=reader,
            )
            fee_targets = [
                a for a in with_res.allocations if a.charge_kind == "late_fee_assessment"
            ]
            self.assertEqual(
                [(a.target_id, a.amount_minor) for a in fee_targets],
                [(fee1["id"], 2000), (fee2["id"], 2000)],
            )

            # Autopay D10 fence: rent_only MUST exclude all late fees even with huge cap.
            rent_only = plan_autopay_occurrence(
                conn,
                lease_id=self.lease_id,
                mandate_scope="rent_only",
                max_amount_minor=9_999_999,
                scheduled_on=self.due2.isoformat(),
            )
            self.assertEqual(rent_only.late_fee_total_minor, 0)
            self.assertTrue(all(a.charge_kind == "rent_expectation" for a in rent_only.allocations))
            # Future rent periods beyond scheduled_on (due2) MUST NOT be included even with huge cap!
            self.assertEqual(rent_only.rent_total_minor, rent1 + rent2)

            # Autopay rent_and_assessed_late_fees includes fees AFTER due rent, excluding future rent, strictly capped.
            cap = rent1 + rent2 + 6000
            with_fees = plan_autopay_occurrence(
                conn,
                lease_id=self.lease_id,
                mandate_scope="rent_and_assessed_late_fees",
                max_amount_minor=cap,
                scheduled_on=self.due2.isoformat(),
            )
            self.assertEqual(with_fees.rent_total_minor, rent1 + rent2)
            self.assertEqual(with_fees.late_fee_total_minor, 6000)
            self.assertEqual(with_fees.gross_total_minor, cap)

            # Verify future rent (exp2 due after due1) is excluded when scheduled_on == due1,
            # even when max_amount_minor exceeds due rent + assessed fees!
            future_plan = plan_autopay_occurrence(
                conn,
                lease_id=self.lease_id,
                mandate_scope="rent_and_assessed_late_fees",
                max_amount_minor=9_999_999,
                scheduled_on=self.due1.isoformat(),
            )
            planned_ids = {a.target_id for a in future_plan.allocations}
            self.assertIn(self.exp1["id"], planned_ids)
            self.assertNotIn(self.exp2["id"], planned_ids)
            self.assertEqual(future_plan.rent_total_minor, rent1)
            self.assertEqual(future_plan.late_fee_total_minor, 10_000)

    def test_provider_outcome_unapplied_funds_on_waiver_race_return_and_partial_refund(self):
        fee1 = self._assess(self.exp1["id"], as_of_date=(self.due1 + timedelta(days=6)).isoformat())
        rent1 = self.exp1["expectedAmountMinor"]

        # Simulate operator waiving 3000 of fee1 AFTER tenant authorized 5000 but BEFORE settlement.
        waived = self.svc.waive_late_fee(
            fee1["id"],
            WaiveLateFeeCommand(
                waived_amount_minor=3000,
                waived_on=self.eligible_date.isoformat(),
                reason="Courtesy waiver before settlement.",
                confirmed=True,
            ),
            expected_revision=self.rev,
            idempotency_key=str(uuid4()),
        )
        self.rev = waived["rentLedgerRevision"]

        # Provider settles authorized rent1 + 5000 fee: 2000 applies to fee1, 3000 routes to unapplied funds!
        outcome = self.finance.unit_of_work.write(
            lambda tx: apply_provider_payment_outcome_in_transaction(
                tx,
                ProviderPaymentOutcomeCommand(
                    lease_id=self.lease_id,
                    payment_attempt_id=str(uuid4()),
                    received_on=self.eligible_date.isoformat(),
                    allocations=(
                        ChargeAllocationTarget("rent_expectation", self.exp1["id"], rent1),
                        ChargeAllocationTarget("late_fee_assessment", fee1["id"], 5000),
                    ),
                    payment_method_kind="online_payment",
                    masked_reference="Bank •••• 4321",
                ),
                now=self.eligible_instant,
                correlation_id=str(uuid4()),
            )
        )
        self.assertEqual(outcome["appliedRentMinor"], rent1)
        self.assertEqual(outcome["appliedLateFeeMinor"], 2000)
        self.assertEqual(outcome["unappliedProcessorFundsMinor"], 3000)
        self.assertEqual(
            outcome["unappliedProcessorFunds"][0]["reason"],
            "late_fee_waived_or_paid_before_settlement",
        )
        self.assertEqual(self.svc.get_assessment(fee1["id"])["settlementStatus"], "paid")

        # Bank return reverses both linked receipts atomically without auto-assessing any new fee.
        returned = self.finance.unit_of_work.write(
            lambda tx: apply_provider_return_in_transaction(
                tx,
                rent_receipt_id=outcome["rentReceiptId"],
                late_fee_receipt_id=outcome["lateFeeReceiptId"],
                reason="ACH R01 Insufficient Funds",
                now=self.eligible_instant,
                correlation_id=str(uuid4()),
            )
        )
        self.assertEqual(returned["reversedRentReceiptId"], outcome["rentReceiptId"])
        self.assertEqual(returned["reversedLateFeeReceiptId"], outcome["lateFeeReceiptId"])
        self.assertFalse(returned["autoAssessedLateFee"])
        self.assertEqual(self.svc.get_assessment(fee1["id"])["remainingBalanceMinor"], 2000)

        # Partial refund attribution requires explicit split and never auto-waives late fees.
        attr = validate_partial_refund_attribution(
            rent_refund_minor=10_000,
            late_fee_refund_minor=1000,
            settled_rent_minor=rent1,
            settled_late_fee_minor=2000,
        )
        self.assertEqual(attr.total_refund_minor, 11_000)
        self.assertFalse(attr.waives_assessed_late_fees)
        with self.assertRaises(FinanceValidationError):
            validate_partial_refund_attribution(
                rent_refund_minor=0,
                late_fee_refund_minor=2500,
                settled_rent_minor=rent1,
                settled_late_fee_minor=2000,
            )

    def test_provider_outcome_replay_idempotency_and_same_day_equal_settlements(self):
        fee1 = self._assess(self.exp1["id"], as_of_date=(self.due1 + timedelta(days=6)).isoformat())
        rent1 = self.exp1["expectedAmountMinor"]

        # 1. Fee-only settlement replay: exact replay must NOT create a second receipt or reduce balance twice.
        attempt_id = str(uuid4())
        cmd = ProviderPaymentOutcomeCommand(
            lease_id=self.lease_id,
            payment_attempt_id=attempt_id,
            received_on=self.eligible_date.isoformat(),
            allocations=(ChargeAllocationTarget("late_fee_assessment", fee1["id"], 2000),),
            payment_method_kind="online_payment",
            masked_reference="Bank •••• 7777",
        )
        first = self.finance.unit_of_work.write(
            lambda tx: apply_provider_payment_outcome_in_transaction(
                tx, cmd, now=self.eligible_instant, correlation_id=str(uuid4())
            )
        )
        replayed = self.finance.unit_of_work.write(
            lambda tx: apply_provider_payment_outcome_in_transaction(
                tx, cmd, now=self.eligible_instant, correlation_id=str(uuid4())
            )
        )
        self.assertEqual(first, replayed)
        self.assertEqual(self.svc.get_assessment(fee1["id"])["remainingBalanceMinor"], 3000)
        with self.engine.connect() as conn:
            receipt_count = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM late_fee_receipts WHERE lease_id = ?", (self.lease_id,)
            ).scalar_one()
        self.assertEqual(receipt_count, 1)

        # Replay of an outcome with unapplied funds also returns exact saved result without re-allocating.
        unapplied_attempt = str(uuid4())
        unapplied_cmd = ProviderPaymentOutcomeCommand(
            lease_id=self.lease_id,
            payment_attempt_id=unapplied_attempt,
            received_on=self.eligible_date.isoformat(),
            allocations=(ChargeAllocationTarget("late_fee_assessment", fee1["id"], 4000),),
            payment_method_kind="online_payment",
            masked_reference="Bank •••• 7778",
        )
        u_first = self.finance.unit_of_work.write(
            lambda tx: apply_provider_payment_outcome_in_transaction(
                tx, unapplied_cmd, now=self.eligible_instant, correlation_id=str(uuid4())
            )
        )
        u_replayed = self.finance.unit_of_work.write(
            lambda tx: apply_provider_payment_outcome_in_transaction(
                tx, unapplied_cmd, now=self.eligible_instant, correlation_id=str(uuid4())
            )
        )
        self.assertEqual(u_first, u_replayed)
        self.assertEqual(u_first["appliedLateFeeMinor"], 3000)
        self.assertEqual(u_first["unappliedProcessorFundsMinor"], 1000)

        # 2. Two distinct same-day equal provider settlements against separate open rent charges succeed
        # without being blocked by the manual receipt duplicate heuristic.
        same_day_1 = self.finance.unit_of_work.write(
            lambda tx: apply_provider_payment_outcome_in_transaction(
                tx,
                ProviderPaymentOutcomeCommand(
                    lease_id=self.lease_id,
                    payment_attempt_id=str(uuid4()),
                    received_on=self.eligible_date.isoformat(),
                    allocations=(
                        ChargeAllocationTarget("rent_expectation", self.exp1["id"], rent1),
                    ),
                    payment_method_kind="online_payment",
                    masked_reference="Bank •••• 9901",
                ),
                now=self.eligible_instant,
                correlation_id=str(uuid4()),
            )
        )
        same_day_2 = self.finance.unit_of_work.write(
            lambda tx: apply_provider_payment_outcome_in_transaction(
                tx,
                ProviderPaymentOutcomeCommand(
                    lease_id=self.lease_id,
                    payment_attempt_id=str(uuid4()),
                    received_on=self.eligible_date.isoformat(),
                    allocations=(
                        ChargeAllocationTarget("rent_expectation", self.exp2["id"], rent1),
                    ),
                    payment_method_kind="online_payment",
                    masked_reference="Bank •••• 9902",
                ),
                now=self.eligible_instant,
                correlation_id=str(uuid4()),
            )
        )
        self.assertNotEqual(same_day_1["rentReceiptId"], same_day_2["rentReceiptId"])
        self.assertEqual(same_day_1["appliedRentMinor"], rent1)
        self.assertEqual(same_day_2["appliedRentMinor"], rent1)


if __name__ == "__main__":
    unittest.main()

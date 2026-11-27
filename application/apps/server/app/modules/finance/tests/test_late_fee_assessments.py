"""Focused proofs for FIN-009 Slice 3: assessment, waiver, void/replace, drift, and rollback."""

import unittest
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import event, text

from app.bootstrap.api import create_app
from app.modules.finance.application.late_fee_ports import PendingPaymentSummary
from app.modules.finance.application.late_fee_service import LateFeeService
from app.modules.finance.application.service import FinanceService
from app.modules.finance.domain.late_fee_models import (
    AssessLateFeeCommand,
    CreateLateFeePolicyCommand,
    VoidLateFeeAssessmentCommand,
    WaiveLateFeeCommand,
)
from app.modules.finance.domain.models import (
    FinanceConflictError,
    FinanceValidationError,
    ReceiptAllocationCommand,
    RecordReceiptCommand,
    SynchronizeExpectationsCommand,
    VoidCommand,
)
from app.modules.finance.infrastructure.unit_of_work import SQLiteFinanceUnitOfWork
from app.modules.finance.tests import test_finance as fixtures
from app.platform.product_migrations import validate_latest_schema
from app.platform.testing_client import LocalApiClient as TestClient


class _StubPendingReader:
    def __init__(self, *, expectations=None, assessments=None):
        self._exp = expectations or {}
        self._ass = assessments or {}

    def processing_for_expectations(self, connection, expectation_ids):
        return {eid: self._exp[eid] for eid in expectation_ids if eid in self._exp}

    def processing_for_assessments(self, connection, assessment_ids):
        return {aid: self._ass[aid] for aid in assessment_ids if aid in self._ass}


class LateFeeAssessmentSlice3Tests(unittest.TestCase):
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
        self.rev = policy["rentLedgerRevision"]

    def _preview(self, *, svc=None, as_of_date=None):
        target = svc or self.svc
        return target.preview_late_fees(
            self.lease_id,
            as_of_date=as_of_date or self.first_eligible.isoformat(),
            rent_expectation_id=self.expectation["id"],
        )

    def test_assess_waive_void_replace_recovery_and_schema_validation(self):
        preview = self._preview()
        item = preview["items"][0]
        self.assertEqual(item["eligibilityStatus"], "eligible")
        fp = item["previewFingerprint"]

        # Future asOfDate assessment is strictly rejected (D14).
        future_date = (self.first_eligible + timedelta(days=1)).isoformat()
        future_preview = self._preview(as_of_date=future_date)["items"][0]
        with self.assertRaises(FinanceValidationError):
            self.svc.assess_late_fee(
                self.lease_id,
                AssessLateFeeCommand(
                    rent_expectation_id=self.expectation["id"],
                    as_of_date=future_date,
                    preview_fingerprint=future_preview["previewFingerprint"],
                    operator_confirmed=True,
                ),
                expected_revision=self.rev,
                idempotency_key=str(uuid4()),
            )

        # Stale previewFingerprint is rejected with 409.
        with self.assertRaises(FinanceConflictError) as bad_fp:
            self.svc.assess_late_fee(
                self.lease_id,
                AssessLateFeeCommand(
                    rent_expectation_id=self.expectation["id"],
                    as_of_date=self.first_eligible.isoformat(),
                    preview_fingerprint="0" * 64,
                    operator_confirmed=True,
                ),
                expected_revision=self.rev,
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(bad_fp.exception.code, "late_fee_preview_fingerprint_mismatch")

        # Assess with valid fingerprint.
        assess_key = str(uuid4())
        cmd = AssessLateFeeCommand(
            rent_expectation_id=self.expectation["id"],
            as_of_date=self.first_eligible.isoformat(),
            preview_fingerprint=fp,
            operator_confirmed=True,
            internal_notes="Verified unpaid after grace end.",
        )
        assessed = self.svc.assess_late_fee(
            self.lease_id, cmd, expected_revision=self.rev, idempotency_key=assess_key
        )
        self.assertEqual(assessed["assessedAmountMinor"], 5000)
        self.assertEqual(assessed["remainingBalanceMinor"], 5000)
        self.assertEqual(assessed["settlementStatus"], "unpaid")
        self.assertFalse(assessed["sourceDriftWarning"])
        self.assertEqual(assessed["rentLedgerRevision"], self.rev + 1)

        # Exact idempotency replay returns identical original result without bumping revision.
        self.assertEqual(
            self.svc.assess_late_fee(
                self.lease_id, cmd, expected_revision=self.rev, idempotency_key=assess_key
            ),
            assessed,
        )
        rev = assessed["rentLedgerRevision"]

        # Second assessment on one-time formula conflicts.
        with self.assertRaises(FinanceConflictError) as dup:
            self.svc.assess_late_fee(
                self.lease_id,
                cmd,
                expected_revision=rev,
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(dup.exception.code, "late_fee_already_assessed")

        # Expectation cannot be voided while an active assessment exists (D9).
        with self.assertRaises(FinanceConflictError) as exp_protected:
            self.finance.void_expectation(
                self.expectation["id"],
                VoidCommand(True, "Attempting to void"),
                expected_revision=rev,
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(exp_protected.exception.code, "expectation_has_active_late_fees")

        # Partial waiver + over-waiver guard + full waiver conservation.
        waive_key = str(uuid4())
        partial = self.svc.waive_late_fee(
            assessed["id"],
            WaiveLateFeeCommand(
                waived_amount_minor=2000,
                waived_on=self.first_eligible.isoformat(),
                reason="First-time courtesy partial waiver.",
                confirmed=True,
                internal_notes="Approved by manager.",
            ),
            expected_revision=rev,
            idempotency_key=waive_key,
        )
        self.assertEqual(partial["waivedAmountMinor"], 2000)
        self.assertEqual(partial["remainingBalanceMinor"], 3000)
        self.assertEqual(partial["settlementStatus"], "partially_paid")
        self.assertEqual(len(partial["waivers"]), 1)
        rev = partial["rentLedgerRevision"]

        with self.assertRaises(FinanceConflictError) as over_waive:
            self.svc.waive_late_fee(
                assessed["id"],
                WaiveLateFeeCommand(
                    waived_amount_minor=3001,
                    waived_on=self.first_eligible.isoformat(),
                    reason="Exceeds remaining",
                    confirmed=True,
                ),
                expected_revision=rev,
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(over_waive.exception.code, "late_fee_waiver_exceeds_balance")

        full = self.svc.waive_late_fee(
            assessed["id"],
            WaiveLateFeeCommand(
                waived_amount_minor=3000,
                waived_on=self.first_eligible.isoformat(),
                reason="Waived remaining balance.",
                confirmed=True,
            ),
            expected_revision=rev,
            idempotency_key=str(uuid4()),
        )
        self.assertEqual(full["waivedAmountMinor"], 5000)
        self.assertEqual(full["remainingBalanceMinor"], 0)
        self.assertEqual(full["settlementStatus"], "waived")
        self.assertEqual(len(full["waivers"]), 2)
        rev = full["rentLedgerRevision"]

        # Void assessment & void-and-replace lineage.
        void_key = str(uuid4())
        voided = self.svc.void_assessment(
            assessed["id"],
            VoidLateFeeAssessmentCommand(True, "Assessed under wrong date."),
            expected_revision=rev,
            idempotency_key=void_key,
        )
        self.assertEqual(voided["settlementStatus"], "voided")
        self.assertEqual(voided["remainingBalanceMinor"], 0)
        rev = voided["rentLedgerRevision"]

        # Fresh preview is now eligible again and can replace the voided assessment.
        fresh_fp = self._preview()["items"][0]["previewFingerprint"]
        replaced = self.svc.assess_late_fee(
            self.lease_id,
            AssessLateFeeCommand(
                rent_expectation_id=self.expectation["id"],
                as_of_date=self.first_eligible.isoformat(),
                preview_fingerprint=fresh_fp,
                operator_confirmed=True,
                replaces_assessment_id=assessed["id"],
            ),
            expected_revision=rev,
            idempotency_key=str(uuid4()),
        )
        self.assertEqual(replaced["replacesAssessmentId"], assessed["id"])
        self.assertEqual(
            self.svc.get_assessment(assessed["id"])["replacedByAssessmentId"], replaced["id"]
        )
        rev = replaced["rentLedgerRevision"]

        # Command recovery works via HTTP for assess, waive, and void.
        with TestClient(create_app(self.config)) as client:
            for key, expected_action in (
                (assess_key, "assess_late_fee"),
                (waive_key, "waive_late_fee"),
                (void_key, "void_late_fee_assessment"),
            ):
                rec = client.get(f"/api/finance/command-operations/{key}")
                self.assertEqual(rec.status_code, 200, rec.text)
                self.assertEqual(rec.json()["action"], expected_action)

            # Detail & list endpoints return consistent views.
            detail = client.get(f"/api/late-fee-assessments/{replaced['id']}")
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertEqual(detail.json()["rentLedgerRevision"], rev)

            lease_list = client.get(f"/api/leases/{self.lease_id}/late-fee-assessments")
            self.assertEqual(lease_list.status_code, 200)
            self.assertEqual([x["id"] for x in lease_list.json()["items"]], [replaced["id"]])

            portfolio_list = client.get(
                f"/api/late-fee-assessments?propertyId={self.expectation['propertyId']}&includeVoided=true"
            )
            self.assertEqual(portfolio_list.status_code, 200)
            self.assertEqual(len(portfolio_list.json()["items"]), 2)

        validate_latest_schema(self.workspace.paths.database)

    def test_source_drift_warning_processing_guards_and_rollback_atomicity(self):
        # 1. Transaction rollback on audit fault leaves zero partial rows or revision bumps.
        fp = self._preview()["items"][0]["previewFingerprint"]
        with (
            patch.object(
                self.finance.unit_of_work.recorder,
                "record_change",
                side_effect=RuntimeError("audit write failed"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.svc.assess_late_fee(
                self.lease_id,
                AssessLateFeeCommand(
                    rent_expectation_id=self.expectation["id"],
                    as_of_date=self.first_eligible.isoformat(),
                    preview_fingerprint=fp,
                    operator_confirmed=True,
                ),
                expected_revision=self.rev,
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(self.svc.list_assessments(lease_id=self.lease_id)["items"], [])
        self.assertEqual(
            self.finance.rent_ledger_revision(self.lease_id)["rentLedgerRevision"], self.rev
        )

        # 2. Processing payment requires explicit acknowledgment on assess.
        pending_uow = SQLiteFinanceUnitOfWork(
            self.workspace.paths.database,
            self.finance.unit_of_work.recorder,
            self.finance.unit_of_work.lease_operations,
            self.finance.unit_of_work.portfolio_operations,
            self.finance.unit_of_work.party_operations,
            self.finance.unit_of_work.task_operations,
            pending_payment_reader=_StubPendingReader(
                expectations={
                    self.expectation["id"]: PendingPaymentSummary(
                        count=1, total_minor=50_000, earliest_submitted_on=self.due.isoformat()
                    )
                }
            ),
        )
        pending_svc = LateFeeService(pending_uow, now=lambda: self.eligible_instant)
        fp_pending = self._preview(svc=pending_svc)["items"][0]["previewFingerprint"]
        with self.assertRaises(FinanceConflictError) as ack_req:
            pending_svc.assess_late_fee(
                self.lease_id,
                AssessLateFeeCommand(
                    rent_expectation_id=self.expectation["id"],
                    as_of_date=self.first_eligible.isoformat(),
                    preview_fingerprint=fp_pending,
                    operator_confirmed=True,
                ),
                expected_revision=self.rev,
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(ack_req.exception.code, "late_fee_processing_acknowledgment_required")

        # Assessing WITH acknowledgment succeeds.
        assessed = pending_svc.assess_late_fee(
            self.lease_id,
            AssessLateFeeCommand(
                rent_expectation_id=self.expectation["id"],
                as_of_date=self.first_eligible.isoformat(),
                preview_fingerprint=fp_pending,
                operator_confirmed=True,
                acknowledge_processing_payments=True,
                processing_acknowledgment_reason="Verified ACH will not cover full rent.",
            ),
            expected_revision=self.rev,
            idempotency_key=str(uuid4()),
        )
        rev = assessed["rentLedgerRevision"]
        self.assertFalse(assessed["sourceDriftWarning"])

        # 3. Waiver & void are fenced against live PAY-001 reservations on the assessment.
        reserved_uow = SQLiteFinanceUnitOfWork(
            self.workspace.paths.database,
            self.finance.unit_of_work.recorder,
            self.finance.unit_of_work.lease_operations,
            self.finance.unit_of_work.portfolio_operations,
            self.finance.unit_of_work.party_operations,
            self.finance.unit_of_work.task_operations,
            pending_payment_reader=_StubPendingReader(
                assessments={
                    assessed["id"]: PendingPaymentSummary(
                        count=1,
                        total_minor=3000,
                        earliest_submitted_on=self.first_eligible.isoformat(),
                    )
                }
            ),
        )
        reserved_svc = LateFeeService(reserved_uow, now=lambda: self.eligible_instant)
        with self.assertRaises(FinanceConflictError) as res_waive:
            reserved_svc.waive_late_fee(
                assessed["id"],
                WaiveLateFeeCommand(
                    waived_amount_minor=2500,
                    waived_on=self.first_eligible.isoformat(),
                    reason="Conflicts with 3000 reserved",
                    confirmed=True,
                ),
                expected_revision=rev,
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(res_waive.exception.code, "late_fee_processing_reservation_conflict")
        with self.assertRaises(FinanceConflictError) as res_void:
            reserved_svc.void_assessment(
                assessed["id"],
                VoidLateFeeAssessmentCommand(True, "Blocked by processing payment"),
                expected_revision=rev,
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(res_void.exception.code, "late_fee_has_active_receipts")

        # 4. Backdated/later rent receipt triggers sourceDriftWarning without mutating assessment.
        receipt = self.finance.record_receipt(
            RecordReceiptCommand(
                self.lease_id,
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
            ),
            expected_revision=rev,
        )
        self.assertEqual(receipt["rentLedgerRevision"], rev + 1)
        drifted = self.svc.get_assessment(assessed["id"])
        self.assertTrue(drifted["sourceDriftWarning"])
        self.assertEqual(drifted["assessedAmountMinor"], 5000)

        # 5. List query budget is <= 6 SELECTs.
        selects = []

        def listener(_conn, _cursor, statement, _params, _ctx, _many):
            if statement.lstrip().split()[0].upper() == "SELECT":
                selects.append(statement)

        event.listen(self.engine, "before_cursor_execute", listener)
        try:
            listed = self.svc.list_assessments(lease_id=self.lease_id)
        finally:
            event.remove(self.engine, "before_cursor_execute", listener)
        self.assertEqual(len(listed["items"]), 1)
        self.assertTrue(listed["items"][0]["sourceDriftWarning"])
        self.assertLessEqual(len(selects), 6)

        # 6. Active late_fee_receipt_allocations block voiding assessment.
        fee_receipt_id = str(uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO late_fee_receipts (
                        id, lease_id, idempotency_key, payment_batch_id, received_on,
                        amount_minor, currency_code, payment_method_kind, payment_method_label,
                        masked_reference, other_payment_method_note, received_by_party_id,
                        replaces_receipt_id, notes, voided_at, void_reason, created_at
                    ) VALUES (
                        :id, :lease_id, :key, NULL, :received_on,
                        5000, 'USD', 'cash', NULL, NULL, NULL, NULL,
                        NULL, NULL, NULL, NULL, :now
                    )
                    """
                ),
                {
                    "id": fee_receipt_id,
                    "lease_id": self.lease_id,
                    "key": str(uuid4()),
                    "received_on": self.first_eligible.isoformat(),
                    "now": self.eligible_instant.isoformat(),
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO late_fee_receipt_allocations (
                        id, receipt_id, assessment_id, amount_minor, created_at
                    ) VALUES (:id, :receipt_id, :assessment_id, 5000, :now)
                    """
                ),
                {
                    "id": str(uuid4()),
                    "receipt_id": fee_receipt_id,
                    "assessment_id": assessed["id"],
                    "now": self.eligible_instant.isoformat(),
                },
            )
        with self.assertRaises(FinanceConflictError) as paid_void:
            self.svc.void_assessment(
                assessed["id"],
                VoidLateFeeAssessmentCommand(True, "Blocked by active fee receipt"),
                expected_revision=receipt["rentLedgerRevision"],
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(paid_void.exception.code, "late_fee_has_active_receipts")

    def test_queue_filters_settlement_before_pagination_and_binds_cursor_to_filters_and_ttl(self):
        # Insert 52 assessments: 1 oldest waived assessment + 51 newer unpaid assessments.
        waived_id = str(uuid4())
        policy_id = self.svc.list_policies(self.lease_id)["items"][0]["id"]
        base_snap = '{"graceEndsOn":"2026-01-06","paidThroughGraceMinor":0,"paidAfterGraceThroughAsOfMinor":0,"calculationSteps":[]}'
        with self.finance.unit_of_work.engine.begin() as conn:
            for idx in range(52):
                aid = waived_id if idx == 0 else str(uuid4())
                as_of = (date(2026, 1, 7) + timedelta(days=idx)).isoformat()
                conn.execute(
                    text(
                        """
                        INSERT INTO late_fee_assessments (
                            id, lease_id, rent_expectation_id, policy_version_id,
                            occurrence_number, as_of_date, accrual_starts_on, accrual_ends_on,
                            accrual_days, assessed_amount_minor, currency_code, time_zone,
                            rule_basis_snapshot, calculation_snapshot_json, calculation_snapshot_hash,
                            processing_acknowledged, processing_acknowledgment_reason, internal_notes,
                            replaces_assessment_id, voided_at, void_reason, assessed_at, assessed_by_actor
                        ) VALUES (
                            :id, :lease_id, :exp_id, :policy_id,
                            :occ, :as_of, :as_of, :as_of,
                            1, 5000, 'USD', 'America/Los_Angeles',
                            'Lease Section 5(b)', :snap, :hash,
                            0, NULL, NULL, NULL, NULL, NULL, :now, 'operator'
                        )
                        """
                    ),
                    {
                        "id": aid,
                        "lease_id": self.lease_id,
                        "exp_id": self.expectation["id"],
                        "policy_id": policy_id,
                        "occ": idx + 1,
                        "as_of": as_of,
                        "snap": base_snap,
                        "hash": "a" * 64,
                        "now": self.eligible_instant.isoformat(),
                    },
                )
            conn.execute(
                text(
                    """
                    INSERT INTO late_fee_waivers (
                        id, assessment_id, lease_id, waived_amount_minor, currency_code, waived_on,
                        reason, internal_notes, waived_at, waived_by_actor
                    ) VALUES (:id, :aid, :lease_id, 5000, 'USD', '2026-01-07', 'Full waiver', NULL, :now, 'operator')
                    """
                ),
                {
                    "id": str(uuid4()),
                    "aid": waived_id,
                    "lease_id": self.lease_id,
                    "now": self.eligible_instant.isoformat(),
                },
            )

        # Page 1 with settlement_status="waived" MUST find the 1 matching row beyond 51 newer unpaid rows!
        waived_page = self.svc.list_assessments(settlement_status="waived", page_size=50)
        self.assertEqual([item["id"] for item in waived_page["items"]], [waived_id])
        self.assertIsNone(waived_page["nextCursor"])

        # Finding 5: A partially waived fee with ZERO receipts has domain status "partially_paid"
        # and MUST appear under settlement_status="partially_paid" and NOT under "unpaid".
        partial_waived_id = str(uuid4())
        with self.finance.unit_of_work.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO late_fee_assessments (
                        id, lease_id, rent_expectation_id, policy_version_id,
                        occurrence_number, as_of_date, accrual_starts_on, accrual_ends_on,
                        accrual_days, assessed_amount_minor, currency_code, time_zone,
                        rule_basis_snapshot, calculation_snapshot_json, calculation_snapshot_hash,
                        processing_acknowledged, processing_acknowledgment_reason, internal_notes,
                        replaces_assessment_id, voided_at, void_reason, assessed_at, assessed_by_actor
                    ) VALUES (
                        :id, :lease_id, :exp_id, :policy_id,
                        99, '2026-01-06', '2026-01-06', '2026-01-06',
                        1, 5000, 'USD', 'America/Los_Angeles',
                        'Lease Section 5(b)', :snap, :hash,
                        0, NULL, NULL, NULL, NULL, NULL, :now, 'operator'
                    )
                    """
                ),
                {
                    "id": partial_waived_id,
                    "lease_id": self.lease_id,
                    "exp_id": self.expectation["id"],
                    "policy_id": policy_id,
                    "snap": base_snap,
                    "hash": "b" * 64,
                    "now": self.eligible_instant.isoformat(),
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO late_fee_waivers (
                        id, assessment_id, lease_id, waived_amount_minor, currency_code, waived_on,
                        reason, internal_notes, waived_at, waived_by_actor
                    ) VALUES (:id, :aid, :lease_id, 1000, 'USD', '2026-01-06', 'Partial waiver', NULL, :now, 'operator')
                    """
                ),
                {
                    "id": str(uuid4()),
                    "aid": partial_waived_id,
                    "lease_id": self.lease_id,
                    "now": self.eligible_instant.isoformat(),
                },
            )
        partial_page = self.svc.list_assessments(settlement_status="partially_paid", page_size=50)
        self.assertEqual([item["id"] for item in partial_page["items"]], [partial_waived_id])
        self.assertEqual(partial_page["items"][0]["settlementStatus"], "partially_paid")
        unpaid_all = self.svc.list_assessments(settlement_status="unpaid", page_size=100)
        self.assertNotIn(partial_waived_id, [item["id"] for item in unpaid_all["items"]])

        # Pagination cursor for unpaid rows is bound to filters and 15-minute TTL.
        page1 = self.svc.list_assessments(settlement_status="unpaid", page_size=10)
        self.assertEqual(len(page1["items"]), 10)
        self.assertIsNotNone(page1["nextCursor"])

        # Valid continuation within 15 minutes succeeds.
        page2 = self.svc.list_assessments(
            settlement_status="unpaid", page_size=10, cursor=page1["nextCursor"]
        )
        self.assertEqual(len(page2["items"]), 10)
        self.assertTrue(
            set(x["id"] for x in page1["items"]).isdisjoint(x["id"] for x in page2["items"])
        )

        # Changing filters with the same cursor fails with cursor_filter_mismatch (409).
        with self.assertRaises(FinanceConflictError) as mismatch:
            self.svc.list_assessments(
                settlement_status="paid", page_size=10, cursor=page1["nextCursor"]
            )
        self.assertEqual(mismatch.exception.code, "cursor_filter_mismatch")

        # Advancing clock past 15 minutes fails with cursor_expired (409).
        expired_svc = LateFeeService(
            self.finance.unit_of_work,
            now=lambda: self.eligible_instant + timedelta(minutes=16),
        )
        with self.assertRaises(FinanceConflictError) as expired:
            expired_svc.list_assessments(
                settlement_status="unpaid", page_size=10, cursor=page1["nextCursor"]
            )
        self.assertEqual(expired.exception.code, "cursor_expired")

    def test_auto_assess_lease_level_waiver_and_expectation_filter(self):
        from app.modules.finance.domain.late_fee_models import (
            CreateLeaseLateFeeWaiverCommand,
            RevokeLeaseLateFeeWaiverCommand,
        )

        # Auto-assess creates the eligible late fee idempotently.
        first_sync = self.svc.sync_auto_assessments(lease_id=self.lease_id)
        self.assertEqual(first_sync["createdCount"], 1)
        second_sync = self.svc.sync_auto_assessments(lease_id=self.lease_id)
        self.assertEqual(second_sync["createdCount"], 0)

        # Filtering by rent_expectation_id returns the auto-assessed charge.
        by_exp = self.svc.list_assessments(rent_expectation_id=self.expectation["id"])
        self.assertEqual(len(by_exp["items"]), 1)
        self.assertEqual(by_exp["items"][0]["assessedAmountMinor"], 5000)
        self.assertEqual(by_exp["items"][0]["settlementStatus"], "unpaid")

        # Lease-level waiver with waive_open_assessments=True waives open fees and pauses auto-assess.
        state = self.svc.get_lease_waiver_state(self.lease_id)
        self.assertIsNone(state["activeWaiver"])
        created_waiver = self.svc.create_lease_waiver(
            self.lease_id,
            CreateLeaseLateFeeWaiverCommand(
                reason="Hardship agreement: waive late fees for this lease.",
                confirmed=True,
                waive_open_assessments=True,
            ),
            expected_revision=state["rentLedgerRevision"],
            idempotency_key=str(uuid4()),
        )
        self.assertEqual(created_waiver["status"], "active")
        self.assertEqual(created_waiver["waivedOpenAssessmentsCount"], 1)

        after_waive = self.svc.list_assessments(rent_expectation_id=self.expectation["id"])
        self.assertEqual(after_waive["items"][0]["settlementStatus"], "waived")
        self.assertEqual(after_waive["items"][0]["remainingBalanceMinor"], 0)

        # Revoking the lease-level waiver re-enables auto-assessment for future periods.
        revoked = self.svc.revoke_lease_waiver(
            self.lease_id,
            RevokeLeaseLateFeeWaiverCommand(
                reason="Hardship period ended.",
                confirmed=True,
            ),
            expected_revision=created_waiver["rentLedgerRevision"],
            idempotency_key=str(uuid4()),
        )
        self.assertEqual(revoked["status"], "revoked")
        self.assertIsNone(self.svc.get_lease_waiver_state(self.lease_id)["activeWaiver"])
        validate_latest_schema(self.workspace.paths.database)

    def test_review_9cd114d_get_readonly_scoped_sync_revision_fence_paging_waiver_exclusion_bulk_conflict_and_d9(
        self,
    ):
        from app.modules.finance.domain.late_fee_models import (
            CreateLeaseLateFeeWaiverCommand,
            RevokeLeaseLateFeeWaiverCommand,
        )

        # 1. [P1] GET list endpoints are strictly read-only (0 assessments, 0 audit rows written).
        with TestClient(create_app(self.config)) as client:
            with self.engine.connect() as conn:
                before_assessments = conn.execute(
                    text("SELECT count(*) FROM late_fee_assessments")
                ).scalar_one()
                before_audits = conn.execute(text("SELECT count(*) FROM audit_events")).scalar_one()
            r1 = client.get(f"/api/leases/{self.lease_id}/late-fee-assessments")
            self.assertEqual(r1.status_code, 200)
            r2 = client.get("/api/late-fee-assessments")
            self.assertEqual(r2.status_code, 200)
            with self.engine.connect() as conn:
                after_assessments = conn.execute(
                    text("SELECT count(*) FROM late_fee_assessments")
                ).scalar_one()
                after_audits = conn.execute(text("SELECT count(*) FROM audit_events")).scalar_one()
            self.assertEqual(after_assessments, before_assessments)
            self.assertEqual(after_audits, before_audits)

            # 2. [P2] Scoped sync by rent_expectation_id touches only the targeted lease, not an unrelated eligible lease.
            other_lease = self._create_other_eligible_lease(client)
            pre_rev = self.svc.list_policies(self.lease_id)["rentLedgerRevision"]
            scoped = self.svc.sync_auto_assessments(rent_expectation_id=self.expectation["id"])
            self.assertEqual(scoped["createdCount"], 1)
            self.assertEqual(
                len(self.svc.list_assessments(lease_id=other_lease["leaseId"])["items"]), 0
            )

            # 3. [P1] Effective sync advances rentLedgerRevision, rejects stale revision commands, and no-op retry preserves revision.
            post_rev = self.svc.list_policies(self.lease_id)["rentLedgerRevision"]
            self.assertEqual(post_rev, pre_rev + 1)
            with self.assertRaises(FinanceConflictError):
                self.svc.create_lease_waiver(
                    self.lease_id,
                    CreateLeaseLateFeeWaiverCommand(reason="Stale rev", confirmed=True),
                    expected_revision=pre_rev,
                    idempotency_key=str(uuid4()),
                )
            noop = self.svc.sync_auto_assessments(lease_id=self.lease_id)
            self.assertEqual(noop["createdCount"], 0)
            self.assertEqual(self.svc.list_policies(self.lease_id)["rentLedgerRevision"], post_rev)

            # 4. [P2] Bulk lease-level waiver is all-or-nothing when any open fee has a processing reservation.
            other_sync = self.svc.sync_auto_assessments(lease_id=other_lease["leaseId"])
            self.assertEqual(other_sync["createdCount"], 1)
            reserved_id = other_sync["assessmentIds"][0]
            reserved_uow = SQLiteFinanceUnitOfWork(
                self.workspace.paths.database,
                self.finance.unit_of_work.recorder,
                self.finance.unit_of_work.lease_operations,
                self.finance.unit_of_work.portfolio_operations,
                self.finance.unit_of_work.party_operations,
                self.finance.unit_of_work.task_operations,
                pending_payment_reader=_StubPendingReader(
                    assessments={
                        reserved_id: PendingPaymentSummary(1, 5000, self.first_eligible.isoformat())
                    }
                ),
            )
            reserved_svc = LateFeeService(reserved_uow, now=lambda: self.eligible_instant)
            other_rev = reserved_svc.list_policies(other_lease["leaseId"])["rentLedgerRevision"]
            with self.assertRaises(FinanceConflictError) as conflict:
                reserved_svc.create_lease_waiver(
                    other_lease["leaseId"],
                    CreateLeaseLateFeeWaiverCommand(
                        reason="Bulk conflict test",
                        confirmed=True,
                        waive_open_assessments=True,
                    ),
                    expected_revision=other_rev,
                    idempotency_key=str(uuid4()),
                )
            self.assertEqual(conflict.exception.code, "late_fee_processing_reservation_conflict")
            self.assertIsNone(
                reserved_svc.get_lease_waiver_state(other_lease["leaseId"])["activeWaiver"]
            )

            # 5. [P2] Timely rent receipt later voided stays manual (FIN-009 D9).
            d9_lease = self._create_other_eligible_lease(client)
            d9_exp = d9_lease["expectation"]
            d9_rev = self.svc.list_policies(d9_lease["leaseId"])["rentLedgerRevision"]
            rcpt_key = str(uuid4())
            paid_rcpt = self.finance.record_receipt(
                RecordReceiptCommand(
                    lease_id=d9_lease["leaseId"],
                    idempotency_key=rcpt_key,
                    received_on=date.today().isoformat(),
                    amount_minor=d9_exp["expectedAmountMinor"],
                    currency_code="USD",
                    allocations=(
                        ReceiptAllocationCommand(d9_exp["id"], d9_exp["expectedAmountMinor"]),
                    ),
                    payment_method_kind="bank_transfer",
                ),
                expected_revision=d9_rev,
            )
            self.finance.void_receipt(
                paid_rcpt["id"],
                VoidCommand(True, "ACH returned NSF"),
                expected_revision=paid_rcpt["rentLedgerRevision"],
                idempotency_key=str(uuid4()),
            )
            self.assertEqual(
                self.svc.sync_auto_assessments(lease_id=d9_lease["leaseId"])["createdCount"], 0
            )

            # 5b. [P2] Under current_unpaid_rent, a fully covering after-grace receipt later voided stays manual (FIN-009 D9).
            d9_cur_lease = self._create_other_eligible_lease(
                client, calculation_basis="current_unpaid_rent"
            )
            d9_cur_exp = d9_cur_lease["expectation"]
            d9_cur_rev = self.svc.list_policies(d9_cur_lease["leaseId"])["rentLedgerRevision"]
            after_grace_svc = FinanceService(
                self.finance.unit_of_work, now=lambda: self.eligible_instant
            )
            cur_key = str(uuid4())
            cur_rcpt = after_grace_svc.record_receipt(
                RecordReceiptCommand(
                    lease_id=d9_cur_lease["leaseId"],
                    idempotency_key=cur_key,
                    received_on=self.first_eligible.isoformat(),
                    amount_minor=d9_cur_exp["expectedAmountMinor"],
                    currency_code="USD",
                    allocations=(
                        ReceiptAllocationCommand(
                            d9_cur_exp["id"], d9_cur_exp["expectedAmountMinor"]
                        ),
                    ),
                    payment_method_kind="bank_transfer",
                ),
                expected_revision=d9_cur_rev,
            )
            after_grace_svc.void_receipt(
                cur_rcpt["id"],
                VoidCommand(True, "After-grace ACH returned"),
                expected_revision=cur_rcpt["rentLedgerRevision"],
                idempotency_key=str(uuid4()),
            )
            self.assertEqual(
                self.svc.sync_auto_assessments(lease_id=d9_cur_lease["leaseId"])["createdCount"], 0
            )

            # 5c. [P2] A partial after-grace receipt that left the same fixed fee eligible before and after voiding does not suppress auto-assessment.
            d9_partial_lease = self._create_other_eligible_lease(
                client, calculation_basis="current_unpaid_rent"
            )
            d9_partial_exp = d9_partial_lease["expectation"]
            d9_partial_rev = self.svc.list_policies(d9_partial_lease["leaseId"])[
                "rentLedgerRevision"
            ]
            partial_rcpt = after_grace_svc.record_receipt(
                RecordReceiptCommand(
                    lease_id=d9_partial_lease["leaseId"],
                    idempotency_key=str(uuid4()),
                    received_on=self.first_eligible.isoformat(),
                    amount_minor=100,
                    currency_code="USD",
                    allocations=(ReceiptAllocationCommand(d9_partial_exp["id"], 100),),
                    payment_method_kind="bank_transfer",
                ),
                expected_revision=d9_partial_rev,
            )
            after_grace_svc.void_receipt(
                partial_rcpt["id"],
                VoidCommand(True, "Small partial receipt voided"),
                expected_revision=partial_rcpt["rentLedgerRevision"],
                idempotency_key=str(uuid4()),
            )
            partial_sync = self.svc.sync_auto_assessments(lease_id=d9_partial_lease["leaseId"])
            self.assertEqual(partial_sync["createdCount"], 1)
            partial_fees = self.svc.list_assessments(lease_id=d9_partial_lease["leaseId"])["items"]
            self.assertEqual(len(partial_fees), 1)
            self.assertEqual(partial_fees[0]["assessedAmountMinor"], 5000)

            # 5d. [P2] Replacing a 60% partial receipt with an identical 60% allocation does not double-count the lineage and still auto-assesses the unchanged $50 fee.
            d9_repl_lease = self._create_other_eligible_lease(client)
            d9_repl_exp = d9_repl_lease["expectation"]
            sixty_pct = (d9_repl_exp["expectedAmountMinor"] * 60) // 100
            d9_repl_rev = self.svc.list_policies(d9_repl_lease["leaseId"])["rentLedgerRevision"]
            orig_rcpt = self.finance.record_receipt(
                RecordReceiptCommand(
                    lease_id=d9_repl_lease["leaseId"],
                    idempotency_key=str(uuid4()),
                    received_on=date.today().isoformat(),
                    amount_minor=sixty_pct,
                    currency_code="USD",
                    allocations=(ReceiptAllocationCommand(d9_repl_exp["id"], sixty_pct),),
                    payment_method_kind="bank_transfer",
                ),
                expected_revision=d9_repl_rev,
            )
            voided_orig = self.finance.void_receipt(
                orig_rcpt["id"],
                VoidCommand(True, "Correcting receipt reference"),
                expected_revision=orig_rcpt["rentLedgerRevision"],
                idempotency_key=str(uuid4()),
            )
            self.finance.record_receipt(
                RecordReceiptCommand(
                    lease_id=d9_repl_lease["leaseId"],
                    idempotency_key=str(uuid4()),
                    received_on=date.today().isoformat(),
                    amount_minor=sixty_pct,
                    currency_code="USD",
                    allocations=(ReceiptAllocationCommand(d9_repl_exp["id"], sixty_pct),),
                    payment_method_kind="bank_transfer",
                    replaces_receipt_id=orig_rcpt["id"],
                ),
                expected_revision=voided_orig["rentLedgerRevision"],
            )
            repl_sync = self.svc.sync_auto_assessments(lease_id=d9_repl_lease["leaseId"])
            self.assertEqual(repl_sync["createdCount"], 1)
            repl_fees = self.svc.list_assessments(lease_id=d9_repl_lease["leaseId"])["items"]
            self.assertEqual(len(repl_fees), 1)
            self.assertEqual(repl_fees[0]["assessedAmountMinor"], 5000)

            # 6. [P2] Revoked lease waiver permanently excludes waived interval for both one-time and daily fees.
            ot_lease = self._create_other_eligible_lease(client)
            ot_rev = self.svc.list_policies(ot_lease["leaseId"])["rentLedgerRevision"]
            pre_waive_svc = LateFeeService(
                self.finance.unit_of_work,
                now=lambda: self.eligible_instant - timedelta(days=2),
            )
            ot_waived = pre_waive_svc.create_lease_waiver(
                ot_lease["leaseId"],
                CreateLeaseLateFeeWaiverCommand(reason="Waive during grace", confirmed=True),
                expected_revision=ot_rev,
                idempotency_key=str(uuid4()),
            )
            post_waive_svc = LateFeeService(
                self.finance.unit_of_work,
                now=lambda: self.eligible_instant + timedelta(days=1),
            )
            post_waive_svc.revoke_lease_waiver(
                ot_lease["leaseId"],
                RevokeLeaseLateFeeWaiverCommand(reason="Resume after grace", confirmed=True),
                expected_revision=ot_waived["rentLedgerRevision"],
                idempotency_key=str(uuid4()),
            )
            later_svc = LateFeeService(
                self.finance.unit_of_work,
                now=lambda: self.eligible_instant + timedelta(days=5),
            )
            self.assertEqual(
                later_svc.sync_auto_assessments(lease_id=ot_lease["leaseId"])["createdCount"], 0
            )

            # 6a-2. [P2] Pre-waiver already-eligible unassessed one-time fee is also excluded on resume.
            pre_arrears_lease = self._create_other_eligible_lease(client)
            pa_rev = self.svc.list_policies(pre_arrears_lease["leaseId"])["rentLedgerRevision"]
            pa_waive_svc = LateFeeService(
                self.finance.unit_of_work,
                now=lambda: self.eligible_instant + timedelta(days=2),
            )
            pa_waived = pa_waive_svc.create_lease_waiver(
                pre_arrears_lease["leaseId"],
                CreateLeaseLateFeeWaiverCommand(reason="Pause after eligibility", confirmed=True),
                expected_revision=pa_rev,
                idempotency_key=str(uuid4()),
            )
            pa_revoke_svc = LateFeeService(
                self.finance.unit_of_work,
                now=lambda: self.eligible_instant + timedelta(days=4),
            )
            pa_revoke_svc.revoke_lease_waiver(
                pre_arrears_lease["leaseId"],
                RevokeLeaseLateFeeWaiverCommand(reason="Resume future only", confirmed=True),
                expected_revision=pa_waived["rentLedgerRevision"],
                idempotency_key=str(uuid4()),
            )
            pa_later_svc = LateFeeService(
                self.finance.unit_of_work,
                now=lambda: self.eligible_instant + timedelta(days=6),
            )
            self.assertEqual(
                pa_later_svc.sync_auto_assessments(lease_id=pre_arrears_lease["leaseId"])[
                    "createdCount"
                ],
                0,
            )

            daily_lease = self._create_other_eligible_lease(client, formula_kind="daily_flat")
            day1 = self.svc.sync_auto_assessments(lease_id=daily_lease["leaseId"])
            self.assertEqual(day1["createdCount"], 1)
            day2_svc = LateFeeService(
                self.finance.unit_of_work, now=lambda: self.eligible_instant + timedelta(days=1)
            )
            d_rev = day2_svc.list_policies(daily_lease["leaseId"])["rentLedgerRevision"]
            d_waiver = day2_svc.create_lease_waiver(
                daily_lease["leaseId"],
                CreateLeaseLateFeeWaiverCommand(reason="Pause days 2-4", confirmed=True),
                expected_revision=d_rev,
                idempotency_key=str(uuid4()),
            )
            day4_svc = LateFeeService(
                self.finance.unit_of_work, now=lambda: self.eligible_instant + timedelta(days=3)
            )
            day4_svc.revoke_lease_waiver(
                daily_lease["leaseId"],
                RevokeLeaseLateFeeWaiverCommand(reason="Resume after day 4", confirmed=True),
                expected_revision=d_waiver["rentLedgerRevision"],
                idempotency_key=str(uuid4()),
            )
            day6_svc = LateFeeService(
                self.finance.unit_of_work, now=lambda: self.eligible_instant + timedelta(days=5)
            )
            day6_sync = day6_svc.sync_auto_assessments(lease_id=daily_lease["leaseId"])
            self.assertEqual(day6_sync["createdCount"], 1)
            day6_detail = day6_svc.get_assessment(day6_sync["assessmentIds"][0])
            self.assertEqual(day6_detail["accrualDays"], 2)
            self.assertEqual(day6_detail["assessedAmountMinor"], 2000)

            # 7. [P2] Paging beyond 500 older ineligible candidates still reaches a newer eligible period.
            long_lease = self._create_other_eligible_lease(client)
            with self.engine.begin() as conn:
                template = dict(
                    conn.execute(
                        text("SELECT * FROM rent_expectations WHERE id = :id"),
                        {"id": long_lease["expectation"]["id"]},
                    )
                    .mappings()
                    .one()
                )
                cols = list(template.keys())
                insert_sql = text(
                    f"INSERT INTO rent_expectations ({', '.join(cols)}) "
                    f"VALUES ({', '.join(':' + col for col in cols)})"
                )
                base_day = date(1975, 1, 1)
                for idx in range(510):
                    d_start = (base_day + timedelta(days=idx * 2)).isoformat()
                    d_end = (base_day + timedelta(days=idx * 2 + 1)).isoformat()
                    row = {
                        **template,
                        "id": str(uuid4()),
                        "period_starts_on": d_start,
                        "period_ends_on": d_end,
                        "due_on": d_start,
                    }
                    conn.execute(insert_sql, row)
            long_sync = self.svc.sync_auto_assessments(lease_id=long_lease["leaseId"])
            self.assertEqual(long_sync["createdCount"], 1)
        validate_latest_schema(self.workspace.paths.database)

    def _create_other_eligible_lease(
        self,
        client,
        *,
        formula_kind: str = "fixed_flat",
        calculation_basis: str = "unpaid_rent_at_grace_end",
    ) -> dict[str, object]:
        prop_res = client.post(
            "/api/properties",
            json={
                "expectedPropertyRevision": 0,
                "idempotencyKey": str(uuid4()),
                "displayName": f"Other {uuid4().hex[:6]}",
                "addressLine1": "99 Pine St",
                "city": "Portland",
                "region": "OR",
                "postalCode": "97201",
                "countryCode": "US",
                "propertyType": "single_family_home",
                "ownerships": [{"ownerKind": "local_operator", "sharePercent": 100}],
            },
        )
        self.assertEqual(prop_res.status_code, 201, prop_res.text)
        prop = prop_res.json()
        tenant_res = client.post(
            "/api/tenants",
            json={
                "expectedRevision": 0,
                "idempotencyKey": str(uuid4()),
                "partyKind": "individual",
                "displayName": f"Tenant {uuid4().hex[:6]}",
                "officialIds": [
                    {"documentType": "passport", "issuingCountry": "US", "lastFour": "9999"}
                ],
            },
        )
        self.assertEqual(tenant_res.status_code, 201, tenant_res.text)
        tenant = tenant_res.json()
        draft_res = client.post(
            "/api/leases",
            json={
                "expectedLeaseRevision": 0,
                "idempotencyKey": str(uuid4()),
                "spaceId": prop["spaces"][0]["id"],
                "leaseKind": "residential",
                "contractStartsOn": min(self.due.isoformat(), prop["effectiveLocalDate"]),
                "occupancyStartsOn": prop["effectiveLocalDate"],
                "initialTerm": {
                    "baseRentMinor": 100_000,
                    "currencyCode": "USD",
                    "paymentFrequency": "monthly",
                    "paymentDueDay": 1,
                    "agreedSecurityDepositMinor": 100_000,
                },
                "participants": [
                    {"tenantPartyId": tenant["id"], "participantRole": "primary_tenant"}
                ],
            },
        )
        self.assertEqual(draft_res.status_code, 201, draft_res.text)
        draft = draft_res.json()
        exec_res = client.post(
            f"/api/leases/{draft['id']}/execute",
            json={
                "expectedLeaseRevision": draft["leaseRevision"],
                "expectedRevision": prop["spaces"][0]["revision"],
                "idempotencyKey": str(uuid4()),
                "confirmed": True,
                "executedOn": prop["effectiveLocalDate"],
            },
        )
        self.assertEqual(exec_res.status_code, 200, exec_res.text)
        synced = self.finance.synchronize(
            draft["id"],
            SynchronizeExpectationsCommand(
                draft["terms"][0]["id"],
                (self.due + timedelta(days=35)).isoformat(),
                date.today().replace(day=1).isoformat(),
            ),
            expected_revision=0,
            idempotency_key=str(uuid4()),
        )
        non_prorated = next(item for item in synced["items"] if not item["isProrated"])
        self.svc.create_policy(
            draft["id"],
            CreateLateFeePolicyCommand(
                effective_on=non_prorated["dueOn"],
                rule_basis="Lease Section 6",
                grace_period_days=5,
                calculation_basis=calculation_basis,
                formula_kind=formula_kind,
                flat_amount_minor=5000 if formula_kind == "fixed_flat" else None,
                daily_amount_minor=1000 if formula_kind == "daily_flat" else None,
                max_accrual_days=30 if formula_kind == "daily_flat" else None,
                rounding_mode="half_up",
                applies_to_prorated_periods=False,
                operator_confirmed=True,
            ),
            expected_revision=synced["rentLedgerRevision"],
            idempotency_key=str(uuid4()),
        )
        return {
            "leaseId": draft["id"],
            "termId": draft["terms"][0]["id"],
            "propertyId": prop["id"],
            "spaceId": prop["spaces"][0]["id"],
            "expectation": non_prorated,
        }


if __name__ == "__main__":
    unittest.main()

"""Focused SQLite and HTTP proofs for FIN-009 Slice 1: schema & policy versioning."""

import hashlib
import json
import unittest
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import exc, text

from app.bootstrap.api import create_app
from app.modules.finance.application.late_fee_service import LateFeeService
from app.modules.finance.domain.late_fee_models import (
    CreateLateFeePolicyCommand,
    VoidLateFeePolicyCommand,
)
from app.modules.finance.domain.models import (
    FinanceConflictError,
    FinanceValidationError,
    SynchronizeExpectationsCommand,
)
from app.modules.finance.infrastructure.schema_validation import validate_finance_schema
from app.modules.finance.tests import test_finance as fixtures
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema
from app.platform.testing_client import LocalApiClient as TestClient


class LateFeePolicySlice1Tests(unittest.TestCase):
    def setUp(self):
        fixtures.FinanceWorkflowTests.setUp(self)
        self.late_fees = LateFeeService(self.finance.unit_of_work)
        self.engine = self.finance.unit_of_work.engine
        self.lease_id = self.lease["id"]
        self.term_id = self.lease["terms"][0]["id"]

    def _fixed_payload(self, **overrides):
        base = {
            "expectedRevision": 0,
            "idempotencyKey": str(uuid4()),
            "effectiveOn": "2026-01-01",
            "endsOn": None,
            "leaseTermId": self.term_id,
            "ruleBasis": "Lease Section 5(b), signed 2026-01-01",
            "gracePeriodDays": 5,
            "calculationBasis": "unpaid_rent_at_grace_end",
            "formulaKind": "fixed_flat",
            "flatAmountMinor": 5000,
            "roundingMode": "half_up",
            "appliesToProratedPeriods": False,
            "operatorConfirmed": True,
            "notes": "Standard residential flat fee.",
        }
        base.update(overrides)
        return base

    def test_http_create_list_supersede_void_and_command_recovery(self):
        app = create_app(self.config)
        with TestClient(app) as client:
            empty = client.get(f"/api/leases/{self.lease_id}/late-fee-policies")
            self.assertEqual(empty.status_code, 200)
            self.assertEqual(empty.json()["items"], [])
            self.assertEqual(empty.json()["rentLedgerRevision"], 0)

            create_key = str(uuid4())
            created = client.post(
                f"/api/leases/{self.lease_id}/late-fee-policies",
                json=self._fixed_payload(idempotencyKey=create_key),
            )
            self.assertEqual(created.status_code, 201, created.text)
            v1 = created.json()
            self.assertEqual(v1["versionNumber"], 1)
            self.assertEqual(v1["status"], "active")
            self.assertEqual(v1["rentLedgerRevision"], 1)
            self.assertEqual(v1["flatAmountMinor"], 5000)
            self.assertFalse(v1["appliesToProratedPeriods"])

            # Exact replay returns identical original response without revision bump.
            replay = client.post(
                f"/api/leases/{self.lease_id}/late-fee-policies",
                json=self._fixed_payload(idempotencyKey=create_key),
            )
            self.assertEqual(replay.status_code, 201)
            self.assertEqual(replay.json(), v1)

            # Changed payload under same key returns 409.
            changed = client.post(
                f"/api/leases/{self.lease_id}/late-fee-policies",
                json=self._fixed_payload(idempotencyKey=create_key, flatAmountMinor=7500),
            )
            self.assertEqual(changed.status_code, 409)
            self.assertEqual(changed.json()["detail"]["code"], "finance_idempotency_conflict")

            # Command recovery returns original committed response.
            recovered = client.get(f"/api/finance/command-operations/{create_key}")
            self.assertEqual(recovered.status_code, 200, recovered.text)
            self.assertEqual(recovered.json()["action"], "create_late_fee_policy")
            self.assertEqual(recovered.json()["result"], v1)

            # Supersede v1 with a percentage_once policy starting 2026-06-01.
            supersede = client.post(
                f"/api/leases/{self.lease_id}/late-fee-policies",
                json={
                    "expectedRevision": 1,
                    "idempotencyKey": str(uuid4()),
                    "effectiveOn": "2026-06-01",
                    "ruleBasis": "Addendum A, signed 2026-05-15",
                    "gracePeriodDays": 3,
                    "calculationBasis": "current_unpaid_rent",
                    "formulaKind": "percentage_once",
                    "percentageBps": 500,
                    "perPeriodMinMinor": 2500,
                    "perPeriodCapMinor": 15000,
                    "minimumUnpaidThresholdMinor": 10000,
                    "roundingMode": "floor",
                    "appliesToProratedPeriods": True,
                    "supersedesPolicyVersionId": v1["id"],
                    "operatorConfirmed": True,
                },
            )
            self.assertEqual(supersede.status_code, 201, supersede.text)
            v2 = supersede.json()
            self.assertEqual(v2["versionNumber"], 2)
            self.assertEqual(v2["status"], "active")
            self.assertEqual(v2["supersedesPolicyVersionId"], v1["id"])
            self.assertEqual(v2["rentLedgerRevision"], 2)

            # List returns active v2 first, then superseded v1 with endsOn = 2026-06-01.
            listed = client.get(f"/api/leases/{self.lease_id}/late-fee-policies")
            self.assertEqual(listed.status_code, 200)
            items = listed.json()["items"]
            self.assertEqual([item["versionNumber"] for item in items], [2, 1])
            self.assertEqual(items[0]["status"], "active")
            self.assertEqual(items[1]["status"], "superseded")
            self.assertEqual(items[1]["endsOn"], "2026-06-01")

            # Void unused v2.
            void_key = str(uuid4())
            voided = client.post(
                f"/api/leases/{self.lease_id}/late-fee-policies/{v2['id']}/void",
                json={
                    "expectedRevision": 2,
                    "idempotencyKey": void_key,
                    "confirmed": True,
                    "reason": "Entered wrong percentage basis points.",
                },
            )
            self.assertEqual(voided.status_code, 200, voided.text)
            v2_void = voided.json()
            self.assertEqual(v2_void["status"], "voided")
            self.assertIsNotNone(v2_void["voidedAt"])
            self.assertEqual(v2_void["rentLedgerRevision"], 3)

            # Command recovery works for void as well.
            void_recovered = client.get(f"/api/finance/command-operations/{void_key}")
            self.assertEqual(void_recovered.status_code, 200)
            self.assertEqual(void_recovered.json()["action"], "void_late_fee_policy")
            self.assertEqual(void_recovered.json()["result"], v2_void)

            # Voided window [2026-06-01, None) can now be replaced by a new daily policy.
            v3 = client.post(
                f"/api/leases/{self.lease_id}/late-fee-policies",
                json={
                    "expectedRevision": 3,
                    "idempotencyKey": str(uuid4()),
                    "effectiveOn": "2026-06-01",
                    "ruleBasis": "Addendum B, signed 2026-05-20",
                    "gracePeriodDays": 5,
                    "calculationBasis": "scheduled_rent",
                    "formulaKind": "fixed_plus_daily_flat",
                    "flatAmountMinor": 5000,
                    "dailyAmountMinor": 1000,
                    "maxAccrualDays": 15,
                    "perPeriodCapMinor": 20000,
                    "roundingMode": "half_up",
                    "appliesToProratedPeriods": False,
                    "operatorConfirmed": True,
                },
            )
            self.assertEqual(v3.status_code, 201, v3.text)
            self.assertEqual(v3.json()["versionNumber"], 3)
            self.assertEqual(v3.json()["rentLedgerRevision"], 4)

            # Superseding an already-superseded or voided policy fails with 409.
            bad_supersede = client.post(
                f"/api/leases/{self.lease_id}/late-fee-policies",
                json=self._fixed_payload(
                    expectedRevision=4,
                    effectiveOn="2027-01-01",
                    supersedesPolicyVersionId=v1["id"],
                ),
            )
            self.assertEqual(bad_supersede.status_code, 409)
            self.assertEqual(bad_supersede.json()["detail"]["code"], "late_fee_policy_not_active")

            # Superseding with effectiveOn <= prior.effectiveOn fails with 422.
            early_supersede = client.post(
                f"/api/leases/{self.lease_id}/late-fee-policies",
                json=self._fixed_payload(
                    expectedRevision=4,
                    effectiveOn="2026-06-01",
                    supersedesPolicyVersionId=v3.json()["id"],
                ),
            )
            self.assertEqual(early_supersede.status_code, 422)

            # Voiding an already-voided policy fails with 409.
            double_void = client.post(
                f"/api/leases/{self.lease_id}/late-fee-policies/{v2['id']}/void",
                json={
                    "expectedRevision": 4,
                    "idempotencyKey": str(uuid4()),
                    "confirmed": True,
                    "reason": "Already voided.",
                },
            )
            self.assertEqual(double_void.status_code, 409)
            self.assertEqual(double_void.json()["detail"]["code"], "late_fee_policy_already_voided")

            # Missing lease or unknown leaseTermId returns 404.
            missing_lease = client.get(f"/api/leases/{uuid4()}/late-fee-policies")
            self.assertEqual(missing_lease.status_code, 404)
            bad_term = client.post(
                f"/api/leases/{self.lease_id}/late-fee-policies",
                json=self._fixed_payload(
                    expectedRevision=4,
                    effectiveOn="2027-01-01",
                    leaseTermId=str(uuid4()),
                ),
            )
            self.assertEqual(bad_term.status_code, 404)

        validate_latest_schema(self.workspace.paths.database)

    def test_formula_validation_and_invalid_combinations(self):
        base = dict(
            effective_on="2026-01-01",
            rule_basis="Lease Section 5(b)",
            grace_period_days=5,
            calculation_basis="unpaid_rent_at_grace_end",
            formula_kind="fixed_flat",
            flat_amount_minor=5000,
            rounding_mode="half_up",
            applies_to_prorated_periods=False,
            operator_confirmed=True,
        )
        # Valid daily_flat with only per_period_cap_minor.
        CreateLateFeePolicyCommand(
            **{
                **base,
                "formula_kind": "daily_flat",
                "flat_amount_minor": None,
                "daily_amount_minor": 1000,
                "per_period_cap_minor": 10000,
            }
        )
        # Valid daily_flat with only max_accrual_days.
        CreateLateFeePolicyCommand(
            **{
                **base,
                "formula_kind": "daily_flat",
                "flat_amount_minor": None,
                "daily_amount_minor": 1000,
                "max_accrual_days": 10,
            }
        )
        invalid_cases = [
            {"operator_confirmed": False},
            {"rule_basis": "   "},
            {"ends_on": "2026-01-01"},
            {"ends_on": "2025-12-31"},
            {"grace_period_days": -1},
            {"grace_period_days": 61},
            {"formula_kind": "fixed_flat", "flat_amount_minor": None},
            {"formula_kind": "fixed_flat", "percentage_bps": 500},
            {"formula_kind": "fixed_flat", "max_accrual_days": 10},
            {"formula_kind": "percentage_once", "flat_amount_minor": None, "percentage_bps": None},
            {"formula_kind": "percentage_once", "flat_amount_minor": 5000, "percentage_bps": 500},
            {"formula_kind": "daily_flat", "flat_amount_minor": None, "daily_amount_minor": 1000},
            {
                "formula_kind": "fixed_plus_daily_flat",
                "flat_amount_minor": 5000,
                "daily_amount_minor": 1000,
            },
            {"per_period_min_minor": 10000, "per_period_cap_minor": 5000},
        ]
        for overrides in invalid_cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(FinanceValidationError):
                    CreateLateFeePolicyCommand(**{**base, **overrides})

    def test_overlap_stale_revision_and_void_guard(self):
        v1 = self.late_fees.create_policy(
            self.lease_id,
            CreateLateFeePolicyCommand(
                effective_on="2026-01-01",
                ends_on="2026-07-01",
                rule_basis="Lease Section 5(b)",
                grace_period_days=5,
                calculation_basis="unpaid_rent_at_grace_end",
                formula_kind="fixed_flat",
                flat_amount_minor=5000,
                rounding_mode="half_up",
                applies_to_prorated_periods=False,
                operator_confirmed=True,
            ),
            expected_revision=0,
            idempotency_key=str(uuid4()),
        )
        # Overlapping window conflicts.
        with self.assertRaises(FinanceConflictError) as overlap:
            self.late_fees.create_policy(
                self.lease_id,
                CreateLateFeePolicyCommand(
                    effective_on="2026-06-15",
                    rule_basis="Lease Addendum",
                    grace_period_days=5,
                    calculation_basis="unpaid_rent_at_grace_end",
                    formula_kind="fixed_flat",
                    flat_amount_minor=6000,
                    rounding_mode="half_up",
                    applies_to_prorated_periods=False,
                    operator_confirmed=True,
                ),
                expected_revision=1,
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(overlap.exception.code, "late_fee_policy_overlap")

        # Stale revision conflicts.
        with self.assertRaises(FinanceConflictError) as stale:
            self.late_fees.void_policy(
                self.lease_id,
                v1["id"],
                VoidLateFeePolicyCommand(True, "Test"),
                expected_revision=0,
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(stale.exception.code, "finance_revision_conflict")

        # Adjacent window [2026-07-01, None) succeeds without superseding.
        v2 = self.late_fees.create_policy(
            self.lease_id,
            CreateLateFeePolicyCommand(
                effective_on="2026-07-01",
                rule_basis="Renewal Addendum",
                grace_period_days=5,
                calculation_basis="unpaid_rent_at_grace_end",
                formula_kind="fixed_flat",
                flat_amount_minor=7500,
                rounding_mode="half_up",
                applies_to_prorated_periods=False,
                operator_confirmed=True,
            ),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
        self.assertEqual(v2["versionNumber"], 2)

        # Synchronize an expectation and attach an active assessment referencing v1.
        sync = self.finance.synchronize(
            self.lease_id,
            SynchronizeExpectationsCommand(
                self.term_id,
                (date.today() + timedelta(days=60)).isoformat(),
                date.today().replace(day=1).isoformat(),
            ),
            expected_revision=2,
            idempotency_key=str(uuid4()),
        )
        expectation_id = sync["items"][0]["id"]
        now = datetime.now(UTC).isoformat()
        snapshot = json.dumps({"steps": []}, separators=(",", ":"))
        snapshot_hash = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
        assessment_id = str(uuid4())
        with self.engine.begin() as conn:
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
                        :id, :lease_id, :expectation_id, :policy_id,
                        1, '2026-01-10', '2026-01-07', '2026-01-07',
                        1, 5000, 'USD', 'America/New_York',
                        'Lease Section 5(b)', :snapshot, :snapshot_hash,
                        0, NULL, NULL,
                        NULL, NULL, NULL, :now, 'local_operator'
                    )
                    """
                ),
                {
                    "id": assessment_id,
                    "lease_id": self.lease_id,
                    "expectation_id": expectation_id,
                    "policy_id": v1["id"],
                    "snapshot": snapshot,
                    "snapshot_hash": snapshot_hash,
                    "now": now,
                },
            )

        # Voiding v1 is blocked by the active assessment void guard.
        with self.assertRaises(FinanceConflictError) as in_use:
            self.late_fees.void_policy(
                self.lease_id,
                v1["id"],
                VoidLateFeePolicyCommand(True, "Attempt to void in-use policy"),
                expected_revision=sync["rentLedgerRevision"],
                idempotency_key=str(uuid4()),
            )
        self.assertEqual(in_use.exception.code, "late_fee_policy_in_use")

        validate_latest_schema(self.workspace.paths.database)

    def test_immutability_triggers_and_schema_tamper_detection(self):
        v1 = self.late_fees.create_policy(
            self.lease_id,
            CreateLateFeePolicyCommand(
                effective_on="2026-01-01",
                rule_basis="Lease Section 5(b)",
                grace_period_days=5,
                calculation_basis="unpaid_rent_at_grace_end",
                formula_kind="fixed_flat",
                flat_amount_minor=5000,
                rounding_mode="half_up",
                applies_to_prorated_periods=False,
                operator_confirmed=True,
            ),
            expected_revision=0,
            idempotency_key=str(uuid4()),
        )
        # Policy rule mutation and DELETE are rejected by triggers.
        with self.assertRaises(exc.DatabaseError):
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE late_fee_policy_versions SET flat_amount_minor = 9999 WHERE id = :id"
                    ),
                    {"id": v1["id"]},
                )
        with self.assertRaises(exc.DatabaseError):
            with self.engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM late_fee_policy_versions WHERE id = :id"),
                    {"id": v1["id"]},
                )

        # Insert an assessment + waiver and test their immutability triggers.
        sync = self.finance.synchronize(
            self.lease_id,
            SynchronizeExpectationsCommand(
                self.term_id,
                (date.today() + timedelta(days=60)).isoformat(),
                date.today().replace(day=1).isoformat(),
            ),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
        expectation_id = sync["items"][0]["id"]
        now = datetime.now(UTC).isoformat()
        snapshot = json.dumps({"steps": []}, separators=(",", ":"))
        snapshot_hash = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
        assessment_id = str(uuid4())
        waiver_id = str(uuid4())
        with self.engine.begin() as conn:
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
                        :id, :lease_id, :expectation_id, :policy_id,
                        1, '2026-01-10', '2026-01-07', '2026-01-07',
                        1, 5000, 'USD', 'America/New_York',
                        'Lease Section 5(b)', :snapshot, :snapshot_hash,
                        0, NULL, NULL,
                        NULL, NULL, NULL, :now, 'local_operator'
                    )
                    """
                ),
                {
                    "id": assessment_id,
                    "lease_id": self.lease_id,
                    "expectation_id": expectation_id,
                    "policy_id": v1["id"],
                    "snapshot": snapshot,
                    "snapshot_hash": snapshot_hash,
                    "now": now,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO late_fee_waivers (
                        id, assessment_id, lease_id, waived_amount_minor, currency_code,
                        reason, internal_notes, waived_on, waived_at, waived_by_actor
                    ) VALUES (
                        :id, :assessment_id, :lease_id, 2000, 'USD',
                        'Courtesy waiver', NULL, '2026-01-11', :now, 'local_operator'
                    )
                    """
                ),
                {
                    "id": waiver_id,
                    "assessment_id": assessment_id,
                    "lease_id": self.lease_id,
                    "now": now,
                },
            )

        # Partial unique index blocks duplicate active occurrence.
        with self.assertRaises(exc.IntegrityError):
            with self.engine.begin() as conn:
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
                            :id, :lease_id, :expectation_id, :policy_id,
                            1, '2026-01-10', '2026-01-07', '2026-01-07',
                            1, 5000, 'USD', 'America/New_York',
                            'Lease Section 5(b)', :snapshot, :snapshot_hash,
                            0, NULL, NULL,
                            NULL, NULL, NULL, :now, 'local_operator'
                        )
                        """
                    ),
                    {
                        "id": str(uuid4()),
                        "lease_id": self.lease_id,
                        "expectation_id": expectation_id,
                        "policy_id": v1["id"],
                        "snapshot": snapshot,
                        "snapshot_hash": snapshot_hash,
                        "now": now,
                    },
                )

        # Assessment amount update & DELETE are rejected.
        with self.assertRaises(exc.DatabaseError):
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE late_fee_assessments SET assessed_amount_minor = 100 WHERE id = :id"
                    ),
                    {"id": assessment_id},
                )
        with self.assertRaises(exc.DatabaseError):
            with self.engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM late_fee_assessments WHERE id = :id"),
                    {"id": assessment_id},
                )

        # Single valid void on assessment is permitted, but second update is rejected.
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE late_fee_assessments SET voided_at = :now, void_reason = 'Error' WHERE id = :id"
                ),
                {"now": now, "id": assessment_id},
            )
        with self.assertRaises(exc.DatabaseError):
            with self.engine.begin() as conn:
                conn.execute(
                    text("UPDATE late_fee_assessments SET void_reason = 'Changed' WHERE id = :id"),
                    {"id": assessment_id},
                )

        # Waivers are strictly append-only (UPDATE & DELETE rejected).
        with self.assertRaises(exc.DatabaseError):
            with self.engine.begin() as conn:
                conn.execute(
                    text("UPDATE late_fee_waivers SET waived_amount_minor = 100 WHERE id = :id"),
                    {"id": waiver_id},
                )
        with self.assertRaises(exc.DatabaseError):
            with self.engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM late_fee_waivers WHERE id = :id"),
                    {"id": waiver_id},
                )

        # Dropping a trigger causes schema validation to fail closed.
        with self.engine.begin() as conn:
            conn.execute(text("DROP TRIGGER late_fee_waivers_no_delete"))
            with self.assertRaises(MigrationSchemaError):
                validate_finance_schema(conn)


if __name__ == "__main__":
    unittest.main()

"""Deterministic FIN-009 late-fee calculation engine (zero floating-point math)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.modules.finance.application.commands import canonical_json, fingerprint
from app.modules.finance.application.late_fee_ports import (
    EMPTY_PENDING_PAYMENTS,
    PendingPaymentSummary,
)
from app.modules.finance.domain.late_fee_models import LateFeePolicyVersion
from app.modules.finance.domain.models import FinanceValidationError, RentExpectation

MAX_FUTURE_PREVIEW_DAYS = 31


@dataclass(frozen=True)
class PriorAssessmentFact:
    occurrence_number: int
    accrual_starts_on: str
    accrual_ends_on: str
    accrual_days: int
    assessed_amount_minor: int


@dataclass(frozen=True)
class ScheduledPrepaidCheckWarning:
    check_id: str
    check_dated_on: str
    amount_minor: int


@dataclass(frozen=True)
class CalculationStep:
    step_code: str
    label: str
    inputs: dict[str, object]
    result_minor: int | None
    expression: str

    def to_dict(self) -> dict[str, object]:
        return {
            "stepCode": self.step_code,
            "label": self.label,
            "inputs": self.inputs,
            "resultMinor": self.result_minor,
            "expression": self.expression,
        }


def resolve_applicable_policy(
    policies: list[LateFeePolicyVersion], due_on: str
) -> LateFeePolicyVersion | None:
    """Return the unique non-voided policy covering `due_on` in [effective_on, ends_on)."""
    for policy in policies:
        if policy.status == "voided":
            continue
        if policy.effective_on <= due_on and (policy.ends_on is None or due_on < policy.ends_on):
            return policy
    return None


def validate_preview_as_of_date(as_of_date: str, current_property_local_date: str) -> bool:
    """Validate preview asOfDate horizon (<= today + 31 days) and return future_projection."""
    as_of = date.fromisoformat(as_of_date)
    today = date.fromisoformat(current_property_local_date)
    if as_of > today + timedelta(days=MAX_FUTURE_PREVIEW_DAYS):
        raise FinanceValidationError(
            f"Preview asOfDate cannot be more than {MAX_FUTURE_PREVIEW_DAYS} days in the future."
        )
    return as_of > today


def compute_preview_fingerprint(
    *,
    lease_id: str,
    rent_expectation_id: str,
    policy_version_id: str,
    as_of_date: str,
    occurrence_number: int,
    accrual_starts_on: str,
    accrual_ends_on: str,
    rent_ledger_revision: int,
    calculated_amount_minor: int,
    calculation_snapshot: dict[str, object],
) -> str:
    payload = {
        "leaseId": lease_id,
        "rentExpectationId": rent_expectation_id,
        "policyVersionId": policy_version_id,
        "asOfDate": as_of_date,
        "occurrenceNumber": occurrence_number,
        "accrualStartsOn": accrual_starts_on,
        "accrualEndsOn": accrual_ends_on,
        "rentLedgerRevision": rent_ledger_revision,
        "calculatedAmountMinor": calculated_amount_minor,
        "calculationSnapshot": calculation_snapshot,
    }
    return fingerprint(canonical_json(payload))


def calculate_late_fee_preview(
    *,
    lease_id: str,
    expectation: RentExpectation,
    policy: LateFeePolicyVersion | None,
    as_of_date: str,
    time_zone: str,
    rent_ledger_revision: int,
    paid_through_grace_minor: int,
    paid_after_grace_through_as_of_minor: int,
    active_assessments: tuple[PriorAssessmentFact, ...] = (),
    scheduled_prepaid_checks: tuple[ScheduledPrepaidCheckWarning, ...] = (),
    processing_payments: PendingPaymentSummary = EMPTY_PENDING_PAYMENTS,
    excluded_waiver_windows: tuple[tuple[str, str], ...] = (),
) -> dict[str, object]:
    """Deterministically compute a read-only late-fee quote for one active expectation."""
    due_date = date.fromisoformat(expectation.due_on)
    as_of = date.fromisoformat(as_of_date)
    steps: list[CalculationStep] = []

    prepaid_warning = {
        "count": len(scheduled_prepaid_checks),
        "totalMinor": sum(item.amount_minor for item in scheduled_prepaid_checks),
        "checkDates": [item.check_dated_on for item in scheduled_prepaid_checks],
    }
    processing_warning = processing_payments.to_dict()
    requires_processing_ack = processing_payments.count > 0

    def _result(
        *,
        eligibility_status: str,
        calculated_amount_minor: int = 0,
        grace_ends_on: str | None = None,
        first_eligible_on: str | None = None,
        unpaid_at_grace_end_minor: int | None = None,
        unpaid_as_of_date_minor: int | None = None,
        basis_amount_minor: int | None = None,
        occurrence_number: int | None = None,
        accrual_starts_on: str | None = None,
        accrual_ends_on: str | None = None,
        accrual_days: int | None = None,
        previously_assessed_minor: int = 0,
    ) -> dict[str, object]:
        step_dicts = [step.to_dict() for step in steps]
        snapshot: dict[str, object] = {
            "policyVersionId": policy.id if policy else None,
            "policyVersionNumber": policy.version_number if policy else None,
            "ruleBasis": policy.rule_basis if policy else None,
            "formulaKind": policy.formula_kind if policy else None,
            "calculationBasis": policy.calculation_basis if policy else None,
            "roundingMode": policy.rounding_mode if policy else None,
            "timeZone": time_zone,
            "asOfDate": as_of_date,
            "dueOn": expectation.due_on,
            "graceEndsOn": grace_ends_on,
            "firstEligibleOn": first_eligible_on,
            "expectedAmountMinor": expectation.expected_amount_minor,
            "paidThroughGraceMinor": paid_through_grace_minor,
            "paidAfterGraceThroughAsOfMinor": paid_after_grace_through_as_of_minor,
            "unpaidAtGraceEndMinor": unpaid_at_grace_end_minor,
            "unpaidAsOfDateMinor": unpaid_as_of_date_minor,
            "basisAmountMinor": basis_amount_minor,
            "previouslyAssessedMinor": previously_assessed_minor,
            "occurrenceNumber": occurrence_number,
            "accrualStartsOn": accrual_starts_on,
            "accrualEndsOn": accrual_ends_on,
            "accrualDays": accrual_days,
            "calculatedAmountMinor": calculated_amount_minor,
            "calculationSteps": step_dicts,
        }
        preview_fp: str | None = None
        if (
            eligibility_status == "eligible"
            and policy is not None
            and occurrence_number is not None
            and accrual_starts_on is not None
            and accrual_ends_on is not None
            and calculated_amount_minor > 0
        ):
            preview_fp = compute_preview_fingerprint(
                lease_id=lease_id,
                rent_expectation_id=expectation.id,
                policy_version_id=policy.id,
                as_of_date=as_of_date,
                occurrence_number=occurrence_number,
                accrual_starts_on=accrual_starts_on,
                accrual_ends_on=accrual_ends_on,
                rent_ledger_revision=rent_ledger_revision,
                calculated_amount_minor=calculated_amount_minor,
                calculation_snapshot=snapshot,
            )
        return {
            "rentExpectationId": expectation.id,
            "periodStartsOn": expectation.period_starts_on,
            "periodEndsOn": expectation.period_ends_on,
            "dueOn": expectation.due_on,
            "isProrated": bool(expectation.is_prorated),
            "expectedAmountMinor": expectation.expected_amount_minor,
            "policyVersionId": policy.id if policy else None,
            "policyVersionNumber": policy.version_number if policy else None,
            "ruleBasis": policy.rule_basis if policy else None,
            "formulaKind": policy.formula_kind if policy else None,
            "calculationBasis": policy.calculation_basis if policy else None,
            "roundingMode": policy.rounding_mode if policy else None,
            "eligibilityStatus": eligibility_status,
            "graceEndsOn": grace_ends_on,
            "firstEligibleOn": first_eligible_on,
            "paidThroughGraceMinor": paid_through_grace_minor,
            "paidAfterGraceThroughAsOfMinor": paid_after_grace_through_as_of_minor,
            "unpaidAtGraceEndMinor": unpaid_at_grace_end_minor,
            "unpaidAsOfDateMinor": unpaid_as_of_date_minor,
            "basisAmountMinor": basis_amount_minor,
            "previouslyAssessedMinor": previously_assessed_minor,
            "occurrenceNumber": occurrence_number,
            "accrualStartsOn": accrual_starts_on,
            "accrualEndsOn": accrual_ends_on,
            "accrualDays": accrual_days,
            "calculatedAmountMinor": calculated_amount_minor,
            "currencyCode": "USD",
            "scheduledPrepaidChecks": prepaid_warning,
            "processingPayments": processing_warning,
            "requiresProcessingAcknowledgment": requires_processing_ack,
            "calculationSteps": step_dicts,
            "calculationSnapshot": snapshot,
            "previewFingerprint": preview_fp,
        }

    # Step 2: Policy & prorated applicability
    if policy is None:
        steps.append(
            CalculationStep(
                step_code="policy_lookup",
                label="No applicable late-fee policy covers this rent due date.",
                inputs={"dueOn": expectation.due_on},
                result_minor=0,
                expression="no_applicable_policy",
            )
        )
        return _result(eligibility_status="no_applicable_policy")

    if expectation.is_prorated and not policy.applies_to_prorated_periods:
        steps.append(
            CalculationStep(
                step_code="proration_check",
                label="Policy excludes prorated rent periods.",
                inputs={
                    "isProrated": True,
                    "appliesToProratedPeriods": False,
                    "policyVersionNumber": policy.version_number,
                },
                result_minor=0,
                expression="excluded_prorated_period",
            )
        )
        return _result(eligibility_status="excluded_prorated_period")

    # Step 3: Property-local grace boundary
    grace_ends_date = due_date + timedelta(days=policy.grace_period_days)
    first_eligible_date = grace_ends_date + timedelta(days=1)
    grace_ends_on = grace_ends_date.isoformat()
    first_eligible_on = first_eligible_date.isoformat()
    steps.append(
        CalculationStep(
            step_code="grace_boundary",
            label="Compute property-local grace boundary and first eligible date.",
            inputs={
                "dueOn": expectation.due_on,
                "gracePeriodDays": policy.grace_period_days,
                "timeZone": time_zone,
                "asOfDate": as_of_date,
            },
            result_minor=None,
            expression=(
                f"grace_ends_on = {expectation.due_on} + {policy.grace_period_days}d = {grace_ends_on}; "
                f"first_eligible_on = {first_eligible_on}"
            ),
        )
    )
    if as_of < first_eligible_date:
        return _result(
            eligibility_status="within_grace_period",
            grace_ends_on=grace_ends_on,
            first_eligible_on=first_eligible_on,
        )

    # Step 4: Active rent receipt facts
    unpaid_at_grace_end_minor = max(0, expectation.expected_amount_minor - paid_through_grace_minor)
    unpaid_as_of_date_minor = max(
        0,
        expectation.expected_amount_minor
        - paid_through_grace_minor
        - paid_after_grace_through_as_of_minor,
    )
    steps.append(
        CalculationStep(
            step_code="rent_balances",
            label="Compute unpaid rent at grace end and as of the review date.",
            inputs={
                "expectedAmountMinor": expectation.expected_amount_minor,
                "paidThroughGraceMinor": paid_through_grace_minor,
                "paidAfterGraceThroughAsOfMinor": paid_after_grace_through_as_of_minor,
            },
            result_minor=unpaid_as_of_date_minor,
            expression=(
                f"unpaid_at_grace_end = max(0, {expectation.expected_amount_minor} - {paid_through_grace_minor}) = {unpaid_at_grace_end_minor}; "
                f"unpaid_as_of_date = max(0, {expectation.expected_amount_minor} - {paid_through_grace_minor} - {paid_after_grace_through_as_of_minor}) = {unpaid_as_of_date_minor}"
            ),
        )
    )

    # Step 5: Delinquency gate & calculation basis
    if policy.calculation_basis == "unpaid_rent_at_grace_end":
        gate_amount_minor = unpaid_at_grace_end_minor
        basis_amount_minor = unpaid_at_grace_end_minor
    elif policy.calculation_basis == "current_unpaid_rent":
        gate_amount_minor = unpaid_as_of_date_minor
        basis_amount_minor = unpaid_as_of_date_minor
    else:  # scheduled_rent
        gate_amount_minor = unpaid_at_grace_end_minor
        basis_amount_minor = expectation.expected_amount_minor

    if gate_amount_minor == 0:
        steps.append(
            CalculationStep(
                step_code="delinquency_gate",
                label="No unpaid rent remains under the policy calculation basis.",
                inputs={
                    "calculationBasis": policy.calculation_basis,
                    "gateAmountMinor": 0,
                },
                result_minor=0,
                expression="gate_amount_minor == 0 -> paid_in_full",
            )
        )
        return _result(
            eligibility_status="paid_in_full",
            grace_ends_on=grace_ends_on,
            first_eligible_on=first_eligible_on,
            unpaid_at_grace_end_minor=unpaid_at_grace_end_minor,
            unpaid_as_of_date_minor=unpaid_as_of_date_minor,
            basis_amount_minor=basis_amount_minor,
        )

    if gate_amount_minor < policy.minimum_unpaid_threshold_minor:
        steps.append(
            CalculationStep(
                step_code="minimum_threshold",
                label="Eligible unpaid rent is below the policy minimum unpaid threshold.",
                inputs={
                    "gateAmountMinor": gate_amount_minor,
                    "minimumUnpaidThresholdMinor": policy.minimum_unpaid_threshold_minor,
                },
                result_minor=0,
                expression=(
                    f"{gate_amount_minor} < {policy.minimum_unpaid_threshold_minor} -> below_minimum_threshold"
                ),
            )
        )
        return _result(
            eligibility_status="below_minimum_threshold",
            grace_ends_on=grace_ends_on,
            first_eligible_on=first_eligible_on,
            unpaid_at_grace_end_minor=unpaid_at_grace_end_minor,
            unpaid_as_of_date_minor=unpaid_as_of_date_minor,
            basis_amount_minor=basis_amount_minor,
        )

    steps.append(
        CalculationStep(
            step_code="calculation_basis",
            label="Select calculation basis amount.",
            inputs={
                "calculationBasis": policy.calculation_basis,
                "gateAmountMinor": gate_amount_minor,
                "minimumUnpaidThresholdMinor": policy.minimum_unpaid_threshold_minor,
            },
            result_minor=basis_amount_minor,
            expression=f"basis_amount_minor ({policy.calculation_basis}) = {basis_amount_minor}",
        )
    )

    # Step 6: Existing active assessments & occurrence/accrual window
    previously_assessed_minor = sum(item.assessed_amount_minor for item in active_assessments)
    prior_days_assessed = sum(item.accrual_days for item in active_assessments)

    is_one_time = policy.formula_kind in {"fixed_flat", "percentage_once"}
    excluded_by_waiver = (
        any(first_eligible_on <= w_end for _w_start, w_end in excluded_waiver_windows)
        if is_one_time
        else any(
            w_start <= first_eligible_on <= w_end for w_start, w_end in excluded_waiver_windows
        )
    )
    if excluded_by_waiver:
        steps.append(
            CalculationStep(
                step_code="lease_waiver_exclusion",
                label=(
                    "Period became eligible on or before a revoked lease-level waiver ended and is excluded."
                    if is_one_time
                    else "Period first became eligible while a lease-level waiver was active and is excluded."
                ),
                inputs={
                    "firstEligibleOn": first_eligible_on,
                    "excludedWaiverWindows": [
                        {"waivedOn": w_start, "revokedOn": w_end}
                        for w_start, w_end in excluded_waiver_windows
                    ],
                },
                result_minor=0,
                expression="excluded_by_lease_waiver -> 0",
            )
        )
        return _result(
            eligibility_status="calculated_zero",
            grace_ends_on=grace_ends_on,
            first_eligible_on=first_eligible_on,
            unpaid_at_grace_end_minor=unpaid_at_grace_end_minor,
            unpaid_as_of_date_minor=unpaid_as_of_date_minor,
            basis_amount_minor=basis_amount_minor,
            previously_assessed_minor=previously_assessed_minor,
        )

    if is_one_time:
        if active_assessments:
            steps.append(
                CalculationStep(
                    step_code="occurrence_check",
                    label="One-time late fee has already been assessed for this rent period.",
                    inputs={"existingActiveAssessments": len(active_assessments)},
                    result_minor=0,
                    expression="already_assessed",
                )
            )
            return _result(
                eligibility_status="already_assessed",
                grace_ends_on=grace_ends_on,
                first_eligible_on=first_eligible_on,
                unpaid_at_grace_end_minor=unpaid_at_grace_end_minor,
                unpaid_as_of_date_minor=unpaid_as_of_date_minor,
                basis_amount_minor=basis_amount_minor,
                previously_assessed_minor=previously_assessed_minor,
            )
        occurrence_number = 1
        accrual_starts_date = first_eligible_date
        accrual_ends_date = first_eligible_date
        accrual_days = 1
    else:
        if not active_assessments:
            occurrence_number = 1
            accrual_starts_date = first_eligible_date
        else:
            occurrence_number = max(item.occurrence_number for item in active_assessments) + 1
            last_accrual_end = max(
                date.fromisoformat(item.accrual_ends_on) for item in active_assessments
            )
            accrual_starts_date = last_accrual_end + timedelta(days=1)

        # Exclude any days covered by historical revoked lease-level waivers (no back-billing).
        for w_start_str, w_end_str in sorted(excluded_waiver_windows):
            w_start = date.fromisoformat(w_start_str)
            w_end = date.fromisoformat(w_end_str)
            if w_start <= as_of and accrual_starts_date <= w_end:
                accrual_starts_date = max(accrual_starts_date, w_end + timedelta(days=1))

        if accrual_starts_date > as_of:
            steps.append(
                CalculationStep(
                    step_code="accrual_window",
                    label="All delinquent days through the review date have already been assessed.",
                    inputs={
                        "nextAccrualStartsOn": accrual_starts_date.isoformat(),
                        "asOfDate": as_of_date,
                    },
                    result_minor=0,
                    expression="already_assessed_through_date",
                )
            )
            return _result(
                eligibility_status="already_assessed_through_date",
                grace_ends_on=grace_ends_on,
                first_eligible_on=first_eligible_on,
                unpaid_at_grace_end_minor=unpaid_at_grace_end_minor,
                unpaid_as_of_date_minor=unpaid_as_of_date_minor,
                basis_amount_minor=basis_amount_minor,
                previously_assessed_minor=previously_assessed_minor,
            )

        raw_days = (as_of - accrual_starts_date).days + 1
        if policy.max_accrual_days is not None:
            remaining_days = max(0, policy.max_accrual_days - prior_days_assessed)
            accrual_days = min(raw_days, remaining_days)
        else:
            accrual_days = raw_days

        if accrual_days == 0:
            steps.append(
                CalculationStep(
                    step_code="max_accrual_days",
                    label="Cumulative maximum accrual days have already been reached.",
                    inputs={
                        "priorDaysAssessed": prior_days_assessed,
                        "maxAccrualDays": policy.max_accrual_days,
                    },
                    result_minor=0,
                    expression="max_accrual_days_reached",
                )
            )
            return _result(
                eligibility_status="max_accrual_days_reached",
                grace_ends_on=grace_ends_on,
                first_eligible_on=first_eligible_on,
                unpaid_at_grace_end_minor=unpaid_at_grace_end_minor,
                unpaid_as_of_date_minor=unpaid_as_of_date_minor,
                basis_amount_minor=basis_amount_minor,
                previously_assessed_minor=previously_assessed_minor,
            )
        accrual_ends_date = accrual_starts_date + timedelta(days=accrual_days - 1)
        steps.append(
            CalculationStep(
                step_code="accrual_window",
                label="Determine non-overlapping daily accrual window.",
                inputs={
                    "occurrenceNumber": occurrence_number,
                    "accrualStartsOn": accrual_starts_date.isoformat(),
                    "accrualEndsOn": accrual_ends_date.isoformat(),
                    "rawDays": raw_days,
                    "priorDaysAssessed": prior_days_assessed,
                    "maxAccrualDays": policy.max_accrual_days,
                },
                result_minor=None,
                expression=(
                    f"[{accrual_starts_date.isoformat()}, {accrual_ends_date.isoformat()}] = {accrual_days} day(s)"
                ),
            )
        )

    accrual_starts_on = accrual_starts_date.isoformat()
    accrual_ends_on = accrual_ends_date.isoformat()

    # Step 7: Exact integer arithmetic
    if policy.formula_kind == "fixed_flat":
        assert policy.flat_amount_minor is not None
        raw_minor = policy.flat_amount_minor
        steps.append(
            CalculationStep(
                step_code="formula",
                label="Apply fixed flat late fee.",
                inputs={"flatAmountMinor": policy.flat_amount_minor},
                result_minor=raw_minor,
                expression=f"fixed_flat = {raw_minor}",
            )
        )
    elif policy.formula_kind == "percentage_once":
        assert policy.percentage_bps is not None
        numerator = basis_amount_minor * policy.percentage_bps
        if policy.rounding_mode == "half_up":
            raw_minor = (numerator + 5_000) // 10_000
            expr = f"({basis_amount_minor} * {policy.percentage_bps} + 5000) // 10000 = {raw_minor}"
        else:
            raw_minor = numerator // 10_000
            expr = f"({basis_amount_minor} * {policy.percentage_bps}) // 10000 = {raw_minor}"
        steps.append(
            CalculationStep(
                step_code="formula",
                label="Apply one-time percentage late fee with exact integer rounding.",
                inputs={
                    "basisAmountMinor": basis_amount_minor,
                    "percentageBps": policy.percentage_bps,
                    "roundingMode": policy.rounding_mode,
                },
                result_minor=raw_minor,
                expression=expr,
            )
        )
    elif policy.formula_kind == "daily_flat":
        assert policy.daily_amount_minor is not None
        raw_minor = policy.daily_amount_minor * accrual_days
        steps.append(
            CalculationStep(
                step_code="formula",
                label="Apply daily flat late fee across eligible days.",
                inputs={
                    "dailyAmountMinor": policy.daily_amount_minor,
                    "accrualDays": accrual_days,
                },
                result_minor=raw_minor,
                expression=f"{policy.daily_amount_minor} * {accrual_days} = {raw_minor}",
            )
        )
    else:  # fixed_plus_daily_flat (D13)
        assert policy.flat_amount_minor is not None and policy.daily_amount_minor is not None
        if occurrence_number == 1:
            daily_days = max(0, accrual_days - 1)
            raw_minor = policy.flat_amount_minor + policy.daily_amount_minor * daily_days
            expr = f"{policy.flat_amount_minor} + ({policy.daily_amount_minor} * {daily_days}) = {raw_minor}"
            inputs: dict[str, object] = {
                "occurrenceNumber": 1,
                "flatAmountMinor": policy.flat_amount_minor,
                "dailyAmountMinor": policy.daily_amount_minor,
                "accrualDays": accrual_days,
                "dailyDays": daily_days,
            }
        else:
            raw_minor = policy.daily_amount_minor * accrual_days
            expr = f"{policy.daily_amount_minor} * {accrual_days} = {raw_minor}"
            inputs = {
                "occurrenceNumber": occurrence_number,
                "dailyAmountMinor": policy.daily_amount_minor,
                "accrualDays": accrual_days,
            }
        steps.append(
            CalculationStep(
                step_code="formula",
                label="Apply initial flat fee (day 1) plus daily flat fee for subsequent days.",
                inputs=inputs,
                result_minor=raw_minor,
                expression=expr,
            )
        )

    # Step 8: Floor (per_period_min_minor) & cumulative cap (per_period_cap_minor)
    after_min = raw_minor
    if occurrence_number == 1 and raw_minor > 0 and policy.per_period_min_minor is not None:
        after_min = max(raw_minor, policy.per_period_min_minor)
        steps.append(
            CalculationStep(
                step_code="per_period_min",
                label="Apply per-period minimum fee.",
                inputs={"rawMinor": raw_minor, "perPeriodMinMinor": policy.per_period_min_minor},
                result_minor=after_min,
                expression=f"max({raw_minor}, {policy.per_period_min_minor}) = {after_min}",
            )
        )

    final_minor = after_min
    if policy.per_period_cap_minor is not None:
        remaining_cap = max(0, policy.per_period_cap_minor - previously_assessed_minor)
        final_minor = min(after_min, remaining_cap)
        steps.append(
            CalculationStep(
                step_code="per_period_cap",
                label="Apply cumulative per-period fee cap.",
                inputs={
                    "afterMinMinor": after_min,
                    "perPeriodCapMinor": policy.per_period_cap_minor,
                    "previouslyAssessedMinor": previously_assessed_minor,
                    "remainingCapMinor": remaining_cap,
                },
                result_minor=final_minor,
                expression=f"min({after_min}, max(0, {policy.per_period_cap_minor} - {previously_assessed_minor})) = {final_minor}",
            )
        )
        if final_minor == 0:
            return _result(
                eligibility_status="period_cap_reached",
                calculated_amount_minor=0,
                grace_ends_on=grace_ends_on,
                first_eligible_on=first_eligible_on,
                unpaid_at_grace_end_minor=unpaid_at_grace_end_minor,
                unpaid_as_of_date_minor=unpaid_as_of_date_minor,
                basis_amount_minor=basis_amount_minor,
                occurrence_number=occurrence_number,
                accrual_starts_on=accrual_starts_on,
                accrual_ends_on=accrual_ends_on,
                accrual_days=accrual_days,
                previously_assessed_minor=previously_assessed_minor,
            )

    if final_minor == 0:
        return _result(
            eligibility_status="calculated_zero",
            calculated_amount_minor=0,
            grace_ends_on=grace_ends_on,
            first_eligible_on=first_eligible_on,
            unpaid_at_grace_end_minor=unpaid_at_grace_end_minor,
            unpaid_as_of_date_minor=unpaid_as_of_date_minor,
            basis_amount_minor=basis_amount_minor,
            occurrence_number=occurrence_number,
            accrual_starts_on=accrual_starts_on,
            accrual_ends_on=accrual_ends_on,
            accrual_days=accrual_days,
            previously_assessed_minor=previously_assessed_minor,
        )

    return _result(
        eligibility_status="eligible",
        calculated_amount_minor=final_minor,
        grace_ends_on=grace_ends_on,
        first_eligible_on=first_eligible_on,
        unpaid_at_grace_end_minor=unpaid_at_grace_end_minor,
        unpaid_as_of_date_minor=unpaid_as_of_date_minor,
        basis_amount_minor=basis_amount_minor,
        occurrence_number=occurrence_number,
        accrual_starts_on=accrual_starts_on,
        accrual_ends_on=accrual_ends_on,
        accrual_days=accrual_days,
        previously_assessed_minor=previously_assessed_minor,
    )

"""FIN-009 late-fee policy versioning service (Slice 1)."""

from __future__ import annotations

import base64
import binascii
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from json import JSONDecodeError, loads
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

from app.modules.audit.application.recorder import invocation_actor
from app.modules.finance.application.commands import (
    FinanceCommandIdentity,
    FinanceCommandOutcome,
    FinanceScope,
    apply_finance_command,
    canonical_json,
    canonical_uuid,
    fingerprint,
)
from app.modules.finance.application.late_fee_ports import EMPTY_PENDING_PAYMENTS
from app.modules.finance.application.receipt_handoff import record_receipt_in_transaction
from app.modules.finance.domain.late_fee_calculator import (
    calculate_late_fee_preview,
    resolve_applicable_policy,
    validate_preview_as_of_date,
)
from app.modules.finance.domain.late_fee_models import (
    AssessLateFeeCommand,
    CreateLateFeePolicyCommand,
    CreateLeaseLateFeeWaiverCommand,
    LateFeeAssessment,
    LateFeeLeaseWaiver,
    LateFeePolicyVersion,
    LateFeeReceipt,
    LateFeeWaiver,
    RecordCombinedReceiptCommand,
    RecordLateFeeReceiptCommand,
    RevokeLeaseLateFeeWaiverCommand,
    VoidLateFeeAssessmentCommand,
    VoidLateFeePolicyCommand,
    VoidLateFeeReceiptCommand,
    WaiveLateFeeCommand,
    derive_assessment_settlement_status,
    windows_overlap,
)
from app.modules.finance.domain.models import (
    FinanceConflictError,
    FinanceNotFoundError,
    FinanceValidationError,
    RecordReceiptCommand,
)

QUEUE_CURSOR_TTL_SECONDS = 900


def _encode_queue_cursor(payload: dict[str, object]) -> str:
    raw = canonical_json(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_queue_cursor(token: str) -> dict[str, object]:
    if not isinstance(token, str) or not token:
        raise FinanceValidationError("Assessment cursor is invalid.")
    padding = "=" * (-len(token) % 4)
    try:
        decoded = base64.urlsafe_b64decode((token + padding).encode("ascii"))
        payload = loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, binascii.Error, JSONDecodeError) as error:
        raise FinanceValidationError("Assessment cursor is invalid.") from error
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise FinanceValidationError("Assessment cursor is invalid.")
    last = payload.get("last")
    if not isinstance(last, list) or len(last) != 2:
        raise FinanceValidationError("Assessment cursor is invalid.")
    try:
        last_date = date.fromisoformat(str(last[0])).isoformat()
        last_id = canonical_uuid(str(last[1]))
        as_of = datetime.fromisoformat(str(payload.get("asOf")))
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("missing tz")
    except (TypeError, ValueError) as error:
        raise FinanceValidationError("Assessment cursor is invalid.") from error
    filters = payload.get("filters")
    if not isinstance(filters, str) or not filters:
        raise FinanceValidationError("Assessment cursor is invalid.")
    return {"last": (last_date, last_id), "asOf": as_of.astimezone(UTC), "filters": filters}


def _actor_snapshot() -> str:
    kind, reference = invocation_actor("local_operator", None)
    return kind if reference is None else f"{kind}:{reference}"


def _policy_sort_key(item: LateFeePolicyVersion) -> tuple[int, int]:
    status_rank = 0 if item.status == "active" else (1 if item.status == "superseded" else 2)
    return (status_rank, -item.version_number)


class LateFeeService:
    def __init__(self, unit_of_work, *, now=lambda: datetime.now(UTC)) -> None:
        self.unit_of_work = unit_of_work
        self.now = now

    def list_policies(self, lease_id: str) -> dict[str, object]:
        lease_id = canonical_uuid(lease_id)

        def operation(tx):
            lease = tx.lease_status(lease_id)
            if lease is None:
                raise FinanceNotFoundError("Lease was not found.")
            policies = sorted(tx.late_fee_policies(lease_id), key=_policy_sort_key)
            revision = tx.commands.command_revision(FinanceScope("rent_ledger", lease_id))
            return {
                "leaseId": lease_id,
                "rentLedgerRevision": revision,
                "items": [item.to_dict() for item in policies],
            }

        return self.unit_of_work.read(operation)

    def preview_late_fees(
        self,
        lease_id: str,
        *,
        as_of_date: str | None = None,
        rent_expectation_id: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, object]:
        lease_id = canonical_uuid(lease_id)
        if rent_expectation_id is not None:
            rent_expectation_id = canonical_uuid(rent_expectation_id)
        if as_of_date is not None:
            try:
                as_of_date = date.fromisoformat(as_of_date).isoformat()
            except (TypeError, ValueError) as error:
                raise FinanceValidationError(
                    "asOfDate must be a valid ISO calendar date."
                ) from error
        cursor_key: tuple[str, str] | None = None
        if cursor is not None:
            if rent_expectation_id is not None:
                raise FinanceValidationError(
                    "Preview cursor cannot be combined with a specific rentExpectationId."
                )
            if not isinstance(cursor, str) or "|" not in cursor:
                raise FinanceValidationError("Preview cursor is invalid.")
            parts = cursor.split("|", 1)
            try:
                cursor_key = (date.fromisoformat(parts[0]).isoformat(), canonical_uuid(parts[1]))
            except (TypeError, ValueError) as error:
                raise FinanceValidationError("Preview cursor is invalid.") from error
        captured_at = self.now().astimezone(UTC)

        def operation(tx):
            context = tx.lease_preview_context(lease_id)
            if context is None:
                raise FinanceNotFoundError("Lease was not found.")
            time_zone = context["time_zone"]
            current_local_date = captured_at.astimezone(ZoneInfo(time_zone)).date().isoformat()
            resolved_as_of_date = current_local_date if as_of_date is None else as_of_date
            future_projection = validate_preview_as_of_date(resolved_as_of_date, current_local_date)
            revision = tx.commands.command_revision(FinanceScope("rent_ledger", lease_id))
            policies = tx.late_fee_policies(lease_id)
            page_limit = 24
            raw_expectations = tx.preview_rent_expectations(
                lease_id,
                rent_expectation_id=rent_expectation_id,
                cursor=cursor_key,
                limit=page_limit + 1,
            )
            if rent_expectation_id is not None:
                if raw_expectations is None:
                    raise FinanceNotFoundError("Rent expectation was not found on this lease.")
                if raw_expectations[0].voided_at is not None:
                    raise FinanceConflictError(
                        "Cannot preview late fees for a voided rent expectation.",
                        code="rent_expectation_voided",
                    )
                expectations = raw_expectations
                next_cursor = None
            else:
                assert raw_expectations is not None
                has_more = len(raw_expectations) > page_limit
                expectations = raw_expectations[:page_limit]
                next_cursor = (
                    f"{expectations[-1].due_on}|{expectations[-1].id}"
                    if has_more and expectations
                    else None
                )
            expectation_ids = [item.id for item in expectations]
            allocations_by_exp = tx.active_rent_allocations_by_date(
                expectation_ids, through_on=resolved_as_of_date
            )
            assessments_by_exp = tx.active_late_fee_assessments_for_expectations(expectation_ids)
            prepaid_by_exp = tx.scheduled_prepaid_checks_for_expectations(expectation_ids)
            processing_by_exp = tx.pending_payments_for_expectations(expectation_ids)

            items: list[dict[str, object]] = []
            for expectation in expectations:
                policy = resolve_applicable_policy(policies, expectation.due_on)
                paid_through_grace = 0
                paid_after_grace = 0
                if policy is not None:
                    grace_ends_on = (
                        date.fromisoformat(expectation.due_on)
                        + timedelta(days=policy.grace_period_days)
                    ).isoformat()
                    for received_on, amount_minor in allocations_by_exp.get(expectation.id, ()):
                        if received_on <= grace_ends_on:
                            paid_through_grace += amount_minor
                        elif received_on <= resolved_as_of_date:
                            paid_after_grace += amount_minor
                else:
                    for received_on, amount_minor in allocations_by_exp.get(expectation.id, ()):
                        if received_on <= resolved_as_of_date:
                            paid_through_grace += amount_minor
                items.append(
                    calculate_late_fee_preview(
                        lease_id=lease_id,
                        expectation=expectation,
                        policy=policy,
                        as_of_date=resolved_as_of_date,
                        time_zone=time_zone,
                        rent_ledger_revision=revision,
                        paid_through_grace_minor=paid_through_grace,
                        paid_after_grace_through_as_of_minor=paid_after_grace,
                        active_assessments=assessments_by_exp.get(expectation.id, ()),
                        scheduled_prepaid_checks=prepaid_by_exp.get(expectation.id, ()),
                        processing_payments=processing_by_exp.get(
                            expectation.id, EMPTY_PENDING_PAYMENTS
                        ),
                    )
                )
            return {
                "previewOnly": True,
                "leaseId": lease_id,
                "timeZone": time_zone,
                "asOf": captured_at.isoformat(),
                "asOfDate": resolved_as_of_date,
                "currentPropertyLocalDate": current_local_date,
                "futureProjection": future_projection,
                "rentLedgerRevision": revision,
                "items": items,
                "nextCursor": next_cursor,
            }

        return self.unit_of_work.read(operation)

    def create_policy(
        self,
        lease_id: str,
        command: CreateLateFeePolicyCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        lease_id = canonical_uuid(lease_id)
        identity = FinanceCommandIdentity(
            FinanceScope("rent_ledger", lease_id),
            "create_late_fee_policy",
            lease_id,
            expected_revision,
            idempotency_key,
            command.command_payload(),
        )
        instant = self.now()

        def operation(tx):
            def mutate(context):
                lease = tx.lease_status(lease_id)
                if lease is None:
                    raise FinanceNotFoundError("Lease was not found.")
                if lease["status"] == "void":
                    raise FinanceConflictError(
                        "Cannot configure a late-fee policy for a void lease.",
                        code="lease_void",
                    )
                if command.lease_term_id is not None:
                    term = tx.historical_term_snapshot(lease_id, command.lease_term_id)
                    if term is None:
                        raise FinanceNotFoundError("Lease term was not found for this lease.")
                existing = tx.late_fee_policies(lease_id)
                superseded_before: LateFeePolicyVersion | None = None
                superseded_after: LateFeePolicyVersion | None = None
                if command.supersedes_policy_version_id is not None:
                    superseded_before = next(
                        (
                            item
                            for item in existing
                            if item.id == command.supersedes_policy_version_id
                        ),
                        None,
                    )
                    if superseded_before is None:
                        raise FinanceNotFoundError(
                            "Superseded late-fee policy version was not found on this lease."
                        )
                    if superseded_before.status != "active":
                        raise FinanceConflictError(
                            "Only an active late-fee policy version can be superseded.",
                            code="late_fee_policy_not_active",
                        )
                    if command.effective_on <= superseded_before.effective_on:
                        raise FinanceValidationError(
                            "Superseding policy effective date must be after the prior policy effective date."
                        )
                    prior_ends_on = (
                        command.effective_on
                        if (
                            superseded_before.ends_on is None
                            or superseded_before.ends_on > command.effective_on
                        )
                        else superseded_before.ends_on
                    )
                    superseded_after = replace(
                        superseded_before, status="superseded", ends_on=prior_ends_on
                    )
                for item in existing:
                    candidate = (
                        superseded_after
                        if superseded_after is not None and item.id == superseded_after.id
                        else item
                    )
                    if candidate.status == "voided":
                        continue
                    if windows_overlap(
                        command.effective_on,
                        command.ends_on,
                        candidate.effective_on,
                        candidate.ends_on,
                    ):
                        raise FinanceConflictError(
                            "Late-fee policy effective dates overlap an existing policy version on this lease.",
                            code="late_fee_policy_overlap",
                        )
                next_version = max((item.version_number for item in existing), default=0) + 1
                if superseded_before is not None and superseded_after is not None:
                    tx.supersede_late_fee_policy(superseded_after)
                    tx.record_change(
                        entity_type="late_fee_policy_version",
                        entity_id=superseded_after.id,
                        action="superseded",
                        before=superseded_before.to_dict(),
                        after=superseded_after.to_dict(),
                        reason="late_fee_policy_superseded",
                        correlation_id=context.correlation_id,
                    )
                created = LateFeePolicyVersion(
                    id=str(uuid4()),
                    lease_id=lease_id,
                    lease_term_id=command.lease_term_id,
                    version_number=next_version,
                    effective_on=command.effective_on,
                    ends_on=command.ends_on,
                    rule_basis=command.rule_basis,
                    grace_period_days=command.grace_period_days,
                    calculation_basis=command.calculation_basis,
                    formula_kind=command.formula_kind,
                    flat_amount_minor=command.flat_amount_minor,
                    percentage_bps=command.percentage_bps,
                    daily_amount_minor=command.daily_amount_minor,
                    max_accrual_days=command.max_accrual_days,
                    per_period_cap_minor=command.per_period_cap_minor,
                    per_period_min_minor=command.per_period_min_minor,
                    minimum_unpaid_threshold_minor=command.minimum_unpaid_threshold_minor,
                    rounding_mode=command.rounding_mode,
                    applies_to_prorated_periods=command.applies_to_prorated_periods,
                    status="active",
                    supersedes_policy_version_id=command.supersedes_policy_version_id,
                    notes=command.notes,
                    operator_confirmed_at=context.committed_at,
                    operator_confirmed_by_actor=_actor_snapshot(),
                    voided_at=None,
                    void_reason=None,
                    created_at=context.committed_at,
                )
                tx.insert_late_fee_policy(created)
                tx.record_change(
                    entity_type="late_fee_policy_version",
                    entity_id=created.id,
                    action="created",
                    before=None,
                    after=created.to_dict(),
                    reason="late_fee_policy_created",
                    correlation_id=context.correlation_id,
                )
                return FinanceCommandOutcome(created.to_dict(), effective=True)

            return apply_finance_command(tx.commands, identity, mutate, instant=instant)

        return self.unit_of_work.write(operation)

    def void_policy(
        self,
        lease_id: str,
        policy_version_id: str,
        command: VoidLateFeePolicyCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        lease_id = canonical_uuid(lease_id)
        policy_version_id = canonical_uuid(policy_version_id)
        identity = FinanceCommandIdentity(
            FinanceScope("rent_ledger", lease_id),
            "void_late_fee_policy",
            policy_version_id,
            expected_revision,
            idempotency_key,
            {"confirmed": command.confirmed, "reason": command.reason},
        )
        instant = self.now()

        def operation(tx):
            def mutate(context):
                lease = tx.lease_status(lease_id)
                if lease is None:
                    raise FinanceNotFoundError("Lease was not found.")
                policy = tx.late_fee_policy(lease_id, policy_version_id)
                if policy is None:
                    raise FinanceNotFoundError("Late-fee policy version was not found.")
                if policy.status == "voided":
                    raise FinanceConflictError(
                        "Late-fee policy version is already voided.",
                        code="late_fee_policy_already_voided",
                    )
                if tx.late_fee_policy_has_active_assessments(policy.id):
                    raise FinanceConflictError(
                        "Late-fee policy version is referenced by active assessments and cannot be voided.",
                        code="late_fee_policy_in_use",
                    )
                voided = replace(
                    policy,
                    status="voided",
                    voided_at=context.committed_at,
                    void_reason=command.reason,
                )
                tx.void_late_fee_policy(voided)
                tx.record_change(
                    entity_type="late_fee_policy_version",
                    entity_id=voided.id,
                    action="voided",
                    before=policy.to_dict(),
                    after=voided.to_dict(),
                    reason=command.reason,
                    correlation_id=context.correlation_id,
                )
                return FinanceCommandOutcome(voided.to_dict(), effective=True)

            return apply_finance_command(tx.commands, identity, mutate, instant=instant)

        return self.unit_of_work.write(operation)

    def assess_late_fee(
        self,
        lease_id: str,
        command: AssessLateFeeCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        lease_id = canonical_uuid(lease_id)
        identity = FinanceCommandIdentity(
            FinanceScope("rent_ledger", lease_id),
            "assess_late_fee",
            command.rent_expectation_id,
            expected_revision,
            idempotency_key,
            command.command_payload(),
        )
        instant = self.now().astimezone(UTC)

        def operation(tx):
            def mutate(context):
                lease_ctx = tx.lease_preview_context(lease_id)
                if lease_ctx is None:
                    raise FinanceNotFoundError("Lease was not found.")
                if lease_ctx["status"] == "void":
                    raise FinanceConflictError(
                        "Cannot assess a late fee for a void lease.",
                        code="lease_void",
                    )
                time_zone = lease_ctx["time_zone"]
                current_local_date = instant.astimezone(ZoneInfo(time_zone)).date().isoformat()
                if command.as_of_date > current_local_date:
                    raise FinanceValidationError(
                        "Late-fee assessment asOfDate cannot be in the future."
                    )
                expectations = tx.preview_rent_expectations(
                    lease_id, rent_expectation_id=command.rent_expectation_id
                )
                if expectations is None:
                    raise FinanceNotFoundError("Rent expectation was not found on this lease.")
                expectation = expectations[0]
                if expectation.voided_at is not None:
                    raise FinanceConflictError(
                        "Cannot assess a late fee for a voided rent expectation.",
                        code="rent_expectation_voided",
                    )
                if command.replaces_assessment_id is not None:
                    replaced = tx.late_fee_assessment(command.replaces_assessment_id)
                    if replaced is None:
                        raise FinanceNotFoundError("Replaced late-fee assessment was not found.")
                    if (
                        replaced.lease_id != lease_id
                        or replaced.rent_expectation_id != expectation.id
                    ):
                        raise FinanceConflictError(
                            "Replaced assessment must belong to the same lease and rent expectation.",
                            code="replacement_assessment_mismatch",
                        )
                    if replaced.voided_at is None:
                        raise FinanceConflictError(
                            "Only a voided late-fee assessment can be replaced.",
                            code="replacement_requires_voided_assessment",
                        )
                    if tx.late_fee_assessment_replaced_by(replaced.id) is not None:
                        raise FinanceConflictError(
                            "This voided late-fee assessment has already been replaced.",
                            code="assessment_already_replaced",
                        )
                policies = tx.late_fee_policies(lease_id)
                policy = resolve_applicable_policy(policies, expectation.due_on)
                allocations_by_exp = tx.active_rent_allocations_by_date(
                    [expectation.id], through_on=command.as_of_date
                )
                paid_through_grace = 0
                paid_after_grace = 0
                if policy is not None:
                    grace_ends_on = (
                        date.fromisoformat(expectation.due_on)
                        + timedelta(days=policy.grace_period_days)
                    ).isoformat()
                    for received_on, amount_minor in allocations_by_exp.get(expectation.id, ()):
                        if received_on <= grace_ends_on:
                            paid_through_grace += amount_minor
                        elif received_on <= command.as_of_date:
                            paid_after_grace += amount_minor
                assessments_by_exp = tx.active_late_fee_assessments_for_expectations(
                    [expectation.id]
                )
                prepaid_by_exp = tx.scheduled_prepaid_checks_for_expectations([expectation.id])
                processing_by_exp = tx.pending_payments_for_expectations([expectation.id])
                computed = calculate_late_fee_preview(
                    lease_id=lease_id,
                    expectation=expectation,
                    policy=policy,
                    as_of_date=command.as_of_date,
                    time_zone=time_zone,
                    rent_ledger_revision=expected_revision,
                    paid_through_grace_minor=paid_through_grace,
                    paid_after_grace_through_as_of_minor=paid_after_grace,
                    active_assessments=assessments_by_exp.get(expectation.id, ()),
                    scheduled_prepaid_checks=prepaid_by_exp.get(expectation.id, ()),
                    processing_payments=processing_by_exp.get(
                        expectation.id, EMPTY_PENDING_PAYMENTS
                    ),
                )
                if computed["eligibilityStatus"] != "eligible" or policy is None:
                    raise FinanceConflictError(
                        f"Rent period is not eligible for late-fee assessment ({computed['eligibilityStatus']}).",
                        code=f"late_fee_{computed['eligibilityStatus']}",
                    )
                if computed["previewFingerprint"] != command.preview_fingerprint:
                    raise FinanceConflictError(
                        "Late-fee preview is stale or does not match current ledger state.",
                        code="late_fee_preview_fingerprint_mismatch",
                    )
                if (
                    computed["requiresProcessingAcknowledgment"]
                    and not command.acknowledge_processing_payments
                ):
                    raise FinanceConflictError(
                        "Processing payments exist for this rent period; explicit acknowledgment and reason are required.",
                        code="late_fee_processing_acknowledgment_required",
                    )
                snapshot_json = canonical_json(computed["calculationSnapshot"])
                if len(snapshot_json) > 16_384:
                    raise FinanceValidationError(
                        "Calculation snapshot exceeds the 16 KiB storage bound."
                    )
                created = LateFeeAssessment(
                    id=str(uuid4()),
                    lease_id=lease_id,
                    rent_expectation_id=expectation.id,
                    policy_version_id=policy.id,
                    occurrence_number=int(computed["occurrenceNumber"]),
                    as_of_date=command.as_of_date,
                    accrual_starts_on=str(computed["accrualStartsOn"]),
                    accrual_ends_on=str(computed["accrualEndsOn"]),
                    accrual_days=int(computed["accrualDays"]),
                    assessed_amount_minor=int(computed["calculatedAmountMinor"]),
                    currency_code="USD",
                    time_zone=time_zone,
                    rule_basis_snapshot=policy.rule_basis,
                    calculation_snapshot_json=snapshot_json,
                    calculation_snapshot_hash=fingerprint(snapshot_json),
                    processing_acknowledged=command.acknowledge_processing_payments,
                    processing_acknowledgment_reason=command.processing_acknowledgment_reason,
                    internal_notes=command.internal_notes,
                    replaces_assessment_id=command.replaces_assessment_id,
                    voided_at=None,
                    void_reason=None,
                    assessed_at=context.committed_at,
                    assessed_by_actor=_actor_snapshot(),
                )
                tx.insert_late_fee_assessment(created)
                tx.record_change(
                    entity_type="late_fee_assessment",
                    entity_id=created.id,
                    action="assessed",
                    before=None,
                    after=created.to_dict(),
                    reason="late_fee_assessed",
                    correlation_id=context.correlation_id,
                )
                return FinanceCommandOutcome(
                    self._assessment_detail_dict(
                        created,
                        waivers=[],
                        allocations=[],
                        replaced_by_id=None,
                        source_drift_warning=False,
                    ),
                    effective=True,
                )

            return apply_finance_command(tx.commands, identity, mutate, instant=instant)

        return self.unit_of_work.write(operation)

    def waive_late_fee(
        self,
        assessment_id: str,
        command: WaiveLateFeeCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        assessment_id = canonical_uuid(assessment_id)
        instant = self.now().astimezone(UTC)

        def operation(tx):
            prior_op = tx.commands.command_operation(idempotency_key)
            if prior_op is not None:
                lease_id = prior_op["scope_id"]
            else:
                existing = tx.late_fee_assessment(assessment_id)
                if existing is None:
                    raise FinanceNotFoundError("Late-fee assessment was not found.")
                lease_id = existing.lease_id
            identity = FinanceCommandIdentity(
                FinanceScope("rent_ledger", lease_id),
                "waive_late_fee",
                assessment_id,
                expected_revision,
                idempotency_key,
                command.command_payload(),
            )

            def mutate(context):
                assessment = tx.late_fee_assessment(assessment_id)
                if assessment is None:
                    raise FinanceNotFoundError("Late-fee assessment was not found.")
                if assessment.voided_at is not None:
                    raise FinanceConflictError(
                        "Cannot waive a voided late-fee assessment.",
                        code="late_fee_assessment_voided",
                    )
                current_local_date = (
                    instant.astimezone(ZoneInfo(assessment.time_zone)).date().isoformat()
                )
                if command.waived_on > current_local_date:
                    raise FinanceValidationError("Waiver date cannot be in the future.")
                prior_waivers = tx.late_fee_waivers_for_assessment(assessment.id)
                prior_waived = sum(item.waived_amount_minor for item in prior_waivers)
                active_paid = tx.late_fee_paid_totals([assessment.id]).get(assessment.id, 0)
                remaining = max(0, assessment.assessed_amount_minor - prior_waived - active_paid)
                if command.waived_amount_minor > remaining:
                    raise FinanceConflictError(
                        "Waiver amount exceeds the remaining unpaid balance.",
                        code="late_fee_waiver_exceeds_balance",
                    )
                processing = tx.pending_payments_for_assessments([assessment.id]).get(
                    assessment.id, EMPTY_PENDING_PAYMENTS
                )
                if command.waived_amount_minor > max(0, remaining - processing.total_minor):
                    raise FinanceConflictError(
                        "Waiver amount conflicts with processing payments on this late fee.",
                        code="late_fee_processing_reservation_conflict",
                    )
                waiver = LateFeeWaiver(
                    id=str(uuid4()),
                    assessment_id=assessment.id,
                    lease_id=assessment.lease_id,
                    waived_amount_minor=command.waived_amount_minor,
                    currency_code="USD",
                    reason=command.reason,
                    internal_notes=command.internal_notes,
                    waived_on=command.waived_on,
                    waived_at=context.committed_at,
                    waived_by_actor=_actor_snapshot(),
                )
                tx.insert_late_fee_waiver(waiver)
                tx.record_change(
                    entity_type="late_fee_waiver",
                    entity_id=waiver.id,
                    action="recorded",
                    before=None,
                    after=waiver.to_dict(),
                    reason=command.reason,
                    correlation_id=context.correlation_id,
                )
                return FinanceCommandOutcome(
                    self._assessment_detail_dict(
                        assessment,
                        waivers=[*prior_waivers, waiver],
                        allocations=tx.late_fee_allocations_for_assessment(assessment.id),
                        replaced_by_id=tx.late_fee_assessment_replaced_by(assessment.id),
                        source_drift_warning=self._compute_drift_for_single(tx, assessment),
                    ),
                    effective=True,
                )

            return apply_finance_command(tx.commands, identity, mutate, instant=instant)

        return self.unit_of_work.write(operation)

    def void_assessment(
        self,
        assessment_id: str,
        command: VoidLateFeeAssessmentCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        assessment_id = canonical_uuid(assessment_id)
        instant = self.now().astimezone(UTC)

        def operation(tx):
            prior_op = tx.commands.command_operation(idempotency_key)
            if prior_op is not None:
                lease_id = prior_op["scope_id"]
            else:
                existing = tx.late_fee_assessment(assessment_id)
                if existing is None:
                    raise FinanceNotFoundError("Late-fee assessment was not found.")
                lease_id = existing.lease_id
            identity = FinanceCommandIdentity(
                FinanceScope("rent_ledger", lease_id),
                "void_late_fee_assessment",
                assessment_id,
                expected_revision,
                idempotency_key,
                {"confirmed": command.confirmed, "reason": command.reason},
            )

            def mutate(context):
                assessment = tx.late_fee_assessment(assessment_id)
                if assessment is None:
                    raise FinanceNotFoundError("Late-fee assessment was not found.")
                if assessment.voided_at is not None:
                    raise FinanceConflictError(
                        "Late-fee assessment is already voided.",
                        code="late_fee_assessment_already_voided",
                    )
                active_paid = tx.late_fee_paid_totals([assessment.id]).get(assessment.id, 0)
                if active_paid > 0:
                    raise FinanceConflictError(
                        "Cannot void a late-fee assessment that has active fee receipts.",
                        code="late_fee_has_active_receipts",
                    )
                processing = tx.pending_payments_for_assessments([assessment.id]).get(
                    assessment.id, EMPTY_PENDING_PAYMENTS
                )
                if processing.count > 0:
                    raise FinanceConflictError(
                        "Cannot void a late-fee assessment while processing payments exist.",
                        code="late_fee_has_active_receipts",
                    )
                voided = replace(
                    assessment,
                    voided_at=context.committed_at,
                    void_reason=command.reason,
                )
                tx.void_late_fee_assessment(voided)
                tx.record_change(
                    entity_type="late_fee_assessment",
                    entity_id=voided.id,
                    action="voided",
                    before=assessment.to_dict(),
                    after=voided.to_dict(),
                    reason=command.reason,
                    correlation_id=context.correlation_id,
                )
                return FinanceCommandOutcome(
                    self._assessment_detail_dict(
                        voided,
                        waivers=tx.late_fee_waivers_for_assessment(voided.id),
                        allocations=tx.late_fee_allocations_for_assessment(voided.id),
                        replaced_by_id=tx.late_fee_assessment_replaced_by(voided.id),
                        source_drift_warning=False,
                    ),
                    effective=True,
                )

            return apply_finance_command(tx.commands, identity, mutate, instant=instant)

        return self.unit_of_work.write(operation)

    def get_lease_waiver_state(self, lease_id: str) -> dict[str, object]:
        lease_id = canonical_uuid(lease_id)

        def operation(tx):
            if tx.lease_status(lease_id) is None:
                raise FinanceNotFoundError("Lease was not found.")
            waivers = tx.lease_late_fee_waivers(lease_id)
            active = next((item for item in waivers if item.status == "active"), None)
            revision = tx.commands.command_revision(FinanceScope("rent_ledger", lease_id))
            return {
                "leaseId": lease_id,
                "rentLedgerRevision": revision,
                "activeWaiver": active.to_dict() if active else None,
                "history": [item.to_dict() for item in waivers],
            }

        return self.unit_of_work.read(operation)

    def create_lease_waiver(
        self,
        lease_id: str,
        command: CreateLeaseLateFeeWaiverCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        lease_id = canonical_uuid(lease_id)
        instant = self.now().astimezone(UTC)

        def operation(tx):
            identity = FinanceCommandIdentity(
                FinanceScope("rent_ledger", lease_id),
                "create_lease_late_fee_waiver",
                lease_id,
                expected_revision,
                idempotency_key,
                command.command_payload(),
            )

            def mutate(context):
                lease_ctx = tx.lease_preview_context(lease_id)
                if lease_ctx is None:
                    raise FinanceNotFoundError("Lease was not found.")
                if tx.active_lease_late_fee_waiver(lease_id) is not None:
                    raise FinanceConflictError(
                        "Late fees are already waived at the lease level.",
                        code="lease_late_fee_waiver_already_active",
                    )
                waived_count = 0
                if command.waive_open_assessments:
                    current_local_date = (
                        instant.astimezone(ZoneInfo(lease_ctx["time_zone"])).date().isoformat()
                    )
                    open_assessments = tx.active_late_fee_assessments_for_lease(lease_id)
                    if open_assessments:
                        ids = [item.id for item in open_assessments]
                        waived_totals = tx.late_fee_waiver_totals(ids)
                        paid_totals = tx.late_fee_paid_totals(ids)
                        processing_map = tx.pending_payments_for_assessments(ids)
                        to_waive: list[tuple[LateFeeAssessment, int]] = []
                        for assessment in open_assessments:
                            remaining = (
                                assessment.assessed_amount_minor
                                - waived_totals.get(assessment.id, 0)
                                - paid_totals.get(assessment.id, 0)
                            )
                            if remaining <= 0:
                                continue
                            if processing_map.get(assessment.id, EMPTY_PENDING_PAYMENTS).count > 0:
                                raise FinanceConflictError(
                                    "Cannot waive all open late fees while one or more assessments "
                                    "have processing payment reservations. Pause auto-assessment "
                                    "without bulk-waiving open fees, or review individual assessments.",
                                    code="late_fee_processing_reservation_conflict",
                                )
                            to_waive.append((assessment, remaining))
                        for assessment, remaining in to_waive:
                            occ_waiver = LateFeeWaiver(
                                id=str(uuid4()),
                                assessment_id=assessment.id,
                                lease_id=lease_id,
                                waived_amount_minor=remaining,
                                currency_code="USD",
                                reason=command.reason,
                                internal_notes=command.internal_notes,
                                waived_on=current_local_date,
                                waived_at=context.committed_at,
                                waived_by_actor=_actor_snapshot(),
                            )
                            tx.insert_late_fee_waiver(occ_waiver)
                            tx.record_change(
                                entity_type="late_fee_waiver",
                                entity_id=occ_waiver.id,
                                action="recorded",
                                before=None,
                                after=occ_waiver.to_dict(),
                                reason=command.reason,
                                correlation_id=context.correlation_id,
                            )
                            waived_count += 1
                lease_waiver = LateFeeLeaseWaiver(
                    id=str(uuid4()),
                    lease_id=lease_id,
                    status="active",
                    reason=command.reason,
                    internal_notes=command.internal_notes,
                    waived_at=context.committed_at,
                    waived_by_actor=_actor_snapshot(),
                    waived_open_assessments_count=waived_count,
                )
                tx.insert_lease_late_fee_waiver(lease_waiver)
                tx.record_change(
                    entity_type="late_fee_lease_waiver",
                    entity_id=lease_waiver.id,
                    action="created",
                    before=None,
                    after=lease_waiver.to_dict(),
                    reason=command.reason,
                    correlation_id=context.correlation_id,
                )
                return FinanceCommandOutcome(lease_waiver.to_dict(), effective=True)

            return apply_finance_command(tx.commands, identity, mutate, instant=instant)

        return self.unit_of_work.write(operation)

    def revoke_lease_waiver(
        self,
        lease_id: str,
        command: RevokeLeaseLateFeeWaiverCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        lease_id = canonical_uuid(lease_id)
        instant = self.now().astimezone(UTC)

        def operation(tx):
            identity = FinanceCommandIdentity(
                FinanceScope("rent_ledger", lease_id),
                "revoke_lease_late_fee_waiver",
                lease_id,
                expected_revision,
                idempotency_key,
                command.command_payload(),
            )

            def mutate(context):
                if tx.lease_status(lease_id) is None:
                    raise FinanceNotFoundError("Lease was not found.")
                active = tx.active_lease_late_fee_waiver(lease_id)
                if active is None:
                    raise FinanceConflictError(
                        "No active lease-level late-fee waiver exists on this lease.",
                        code="no_active_lease_late_fee_waiver",
                    )
                revoked = replace(
                    active,
                    status="revoked",
                    revoked_at=context.committed_at,
                    revoked_by_actor=_actor_snapshot(),
                    revoke_reason=command.reason,
                )
                tx.revoke_lease_late_fee_waiver(revoked)
                tx.record_change(
                    entity_type="late_fee_lease_waiver",
                    entity_id=revoked.id,
                    action="revoked",
                    before=active.to_dict(),
                    after=revoked.to_dict(),
                    reason=command.reason,
                    correlation_id=context.correlation_id,
                )
                return FinanceCommandOutcome(revoked.to_dict(), effective=True)

            return apply_finance_command(tx.commands, identity, mutate, instant=instant)

        return self.unit_of_work.write(operation)

    def sync_auto_assessments(
        self,
        *,
        lease_id: str | None = None,
        property_id: str | None = None,
        rent_expectation_id: str | None = None,
    ) -> dict[str, object]:
        """Idempotently auto-assess eligible overdue late fees for active non-waived leases."""
        if lease_id is not None:
            lease_id = canonical_uuid(lease_id)
        if property_id is not None:
            property_id = canonical_uuid(property_id)
        if rent_expectation_id is not None:
            rent_expectation_id = canonical_uuid(rent_expectation_id)
        captured_at = self.now().astimezone(UTC)

        def find_candidates(tx):
            if rent_expectation_id is not None:
                owning_lease = tx.expectation_lease_id(rent_expectation_id)
                if owning_lease is None:
                    return []
                if lease_id is not None and owning_lease != lease_id:
                    return []
                return tx.leases_with_active_late_fee_policies(lease_id=owning_lease)
            return tx.leases_with_active_late_fee_policies(
                lease_id=lease_id, property_id=property_id
            )

        candidate_leases = self.unit_of_work.read(find_candidates)
        created_ids: list[str] = []
        for lid in candidate_leases:
            created_ids.extend(
                self._auto_assess_lease(lid, captured_at, rent_expectation_id=rent_expectation_id)
            )
        return {"createdCount": len(created_ids), "assessmentIds": created_ids}

    def _collect_auto_expectations(
        self, tx, lease_id: str, current_local_date: str, rent_expectation_id: str | None
    ):
        if rent_expectation_id is not None:
            single = tx.preview_rent_expectations(
                lease_id, rent_expectation_id=rent_expectation_id, cursor=None, limit=1
            )
            if not single or single[0].voided_at is not None:
                return []
            return [exp for exp in single if exp.due_on <= current_local_date]
        expectations = []
        cursor: tuple[str, str] | None = None
        page_size = 200
        while True:
            batch = (
                tx.preview_rent_expectations(
                    lease_id, rent_expectation_id=None, cursor=cursor, limit=page_size
                )
                or []
            )
            if not batch:
                break
            expectations.extend(exp for exp in batch if exp.due_on <= current_local_date)
            if len(batch) < page_size:
                break
            cursor = (batch[-1].due_on, batch[-1].id)
        return expectations

    @staticmethod
    def _voided_receipt_changed_fee(
        *,
        lease_id: str,
        expectation,
        policy,
        current_local_date: str,
        grace_ends_on: str,
        time_zone: str,
        revision: int,
        paid_through_grace: int,
        paid_after_grace: int,
        lineage_allocations: list[tuple[str, str, int, bool]]
        | tuple[tuple[str, str, int, bool], ...],
        active_assessments,
        scheduled_prepaid_checks,
        processing_payments,
        excluded_waiver_windows: tuple[tuple[str, str], ...],
        computed_amount_minor: int,
    ) -> bool:
        """FIN-009 D9: return True when voiding/replacing receipt(s) created eligibility or changed the fee."""
        active_by_chain: dict[str, tuple[int, int]] = {}
        voided_by_chain: dict[str, list[tuple[int, int]]] = {}
        for chain_root, received_on, amount_minor, is_voided in lineage_allocations:
            if received_on > current_local_date:
                continue
            tg = amount_minor if received_on <= grace_ends_on else 0
            ag = 0 if received_on <= grace_ends_on else amount_minor
            if is_voided:
                voided_by_chain.setdefault(chain_root, []).append((tg, ag))
            else:
                prev_tg, prev_ag = active_by_chain.get(chain_root, (0, 0))
                active_by_chain[chain_root] = (prev_tg + tg, prev_ag + ag)
        if not voided_by_chain:
            return False
        pre_through_grace = paid_through_grace
        pre_after_grace = paid_after_grace
        use_current_basis = policy.calculation_basis == "current_unpaid_rent"
        for chain_root, voided_entries in voided_by_chain.items():
            act_tg, act_ag = active_by_chain.get(chain_root, (0, 0))
            best_tg, best_ag = max(
                voided_entries,
                key=(lambda pair: (pair[0] + pair[1], pair[0]))
                if use_current_basis
                else (lambda pair: (pair[0], pair[1])),
            )
            pre_through_grace = pre_through_grace - act_tg + best_tg
            pre_after_grace = pre_after_grace - act_ag + best_ag
        with_voided = calculate_late_fee_preview(
            lease_id=lease_id,
            expectation=expectation,
            policy=policy,
            as_of_date=current_local_date,
            time_zone=time_zone,
            rent_ledger_revision=revision,
            paid_through_grace_minor=max(0, pre_through_grace),
            paid_after_grace_through_as_of_minor=max(0, pre_after_grace),
            active_assessments=active_assessments,
            scheduled_prepaid_checks=scheduled_prepaid_checks,
            processing_payments=processing_payments,
            excluded_waiver_windows=excluded_waiver_windows,
        )
        return (
            with_voided["eligibilityStatus"] != "eligible"
            or int(with_voided["calculatedAmountMinor"]) != computed_amount_minor
        )

    def _auto_assess_lease(
        self,
        lease_id: str,
        captured_at: datetime,
        *,
        rent_expectation_id: str | None = None,
    ) -> list[str]:
        def operation(tx):
            lease_waivers = tx.lease_late_fee_waivers(lease_id)
            if any(item.status == "active" for item in lease_waivers):
                return []
            context = tx.lease_preview_context(lease_id)
            if context is None:
                return []
            time_zone = context["time_zone"]
            tz = ZoneInfo(time_zone)
            current_local_date = captured_at.astimezone(tz).date().isoformat()
            excluded_waiver_windows = tuple(
                (
                    datetime.fromisoformat(item.waived_at).astimezone(tz).date().isoformat(),
                    datetime.fromisoformat(item.revoked_at).astimezone(tz).date().isoformat(),
                )
                for item in lease_waivers
                if item.status == "revoked" and item.revoked_at is not None
            )
            policies = tx.late_fee_policies(lease_id)
            expectations = self._collect_auto_expectations(
                tx, lease_id, current_local_date, rent_expectation_id
            )
            if not expectations:
                return []
            exp_ids = [exp.id for exp in expectations]
            all_assessments_by_exp = tx.late_fee_assessments_for_expectations_all(exp_ids)
            active_assessment_ids = [
                item.id
                for items in all_assessments_by_exp.values()
                for item in items
                if item.voided_at is None
            ]
            waived_totals = tx.late_fee_waiver_totals(active_assessment_ids)
            allocs_by_exp = tx.active_rent_allocations_by_date(
                exp_ids, through_on=current_local_date
            )
            lineage_allocs_by_exp = tx.rent_receipt_lineage_allocations_by_expectation(
                lease_id, exp_ids
            )
            prepaid_by_exp = tx.scheduled_prepaid_checks_for_expectations(exp_ids)
            processing_by_exp = tx.pending_payments_for_expectations(exp_ids)
            active_facts_by_exp = tx.active_late_fee_assessments_for_expectations(exp_ids)
            revision = tx.commands.command_revision(FinanceScope("rent_ledger", lease_id))

            pending_rows: list[tuple[LateFeeAssessment, str]] = []
            for exp in expectations:
                exp_all = all_assessments_by_exp.get(exp.id, [])
                replaced_ids = {
                    item.replaces_assessment_id
                    for item in exp_all
                    if item.replaces_assessment_id is not None
                }
                if any(
                    item.voided_at is not None and item.id not in replaced_ids for item in exp_all
                ):
                    continue
                if any(
                    item.voided_at is None and waived_totals.get(item.id, 0) > 0 for item in exp_all
                ):
                    continue
                policy = resolve_applicable_policy(policies, exp.due_on)
                if policy is None:
                    continue
                grace_ends_on = (
                    date.fromisoformat(exp.due_on) + timedelta(days=policy.grace_period_days)
                ).isoformat()
                paid_through_grace = 0
                paid_after_grace = 0
                for received_on, amount_minor in allocs_by_exp.get(exp.id, ()):
                    if received_on <= grace_ends_on:
                        paid_through_grace += amount_minor
                    elif received_on <= current_local_date:
                        paid_after_grace += amount_minor
                computed = calculate_late_fee_preview(
                    lease_id=lease_id,
                    expectation=exp,
                    policy=policy,
                    as_of_date=current_local_date,
                    time_zone=time_zone,
                    rent_ledger_revision=revision,
                    paid_through_grace_minor=paid_through_grace,
                    paid_after_grace_through_as_of_minor=paid_after_grace,
                    active_assessments=active_facts_by_exp.get(exp.id, ()),
                    scheduled_prepaid_checks=prepaid_by_exp.get(exp.id, ()),
                    processing_payments=processing_by_exp.get(exp.id, EMPTY_PENDING_PAYMENTS),
                    excluded_waiver_windows=excluded_waiver_windows,
                )
                if (
                    computed["eligibilityStatus"] != "eligible"
                    or computed["requiresProcessingAcknowledgment"]
                ):
                    continue
                if self._voided_receipt_changed_fee(
                    lease_id=lease_id,
                    expectation=exp,
                    policy=policy,
                    current_local_date=current_local_date,
                    grace_ends_on=grace_ends_on,
                    time_zone=time_zone,
                    revision=revision,
                    paid_through_grace=paid_through_grace,
                    paid_after_grace=paid_after_grace,
                    lineage_allocations=lineage_allocs_by_exp.get(exp.id, ()),
                    active_assessments=active_facts_by_exp.get(exp.id, ()),
                    scheduled_prepaid_checks=prepaid_by_exp.get(exp.id, ()),
                    processing_payments=processing_by_exp.get(exp.id, EMPTY_PENDING_PAYMENTS),
                    excluded_waiver_windows=excluded_waiver_windows,
                    computed_amount_minor=int(computed["calculatedAmountMinor"]),
                ):
                    continue
                snapshot_json = canonical_json(computed["calculationSnapshot"])
                if len(snapshot_json) > 16_384:
                    continue
                created = LateFeeAssessment(
                    id=str(uuid4()),
                    lease_id=lease_id,
                    rent_expectation_id=exp.id,
                    policy_version_id=policy.id,
                    occurrence_number=int(computed["occurrenceNumber"]),
                    as_of_date=current_local_date,
                    accrual_starts_on=str(computed["accrualStartsOn"]),
                    accrual_ends_on=str(computed["accrualEndsOn"]),
                    accrual_days=int(computed["accrualDays"]),
                    assessed_amount_minor=int(computed["calculatedAmountMinor"]),
                    currency_code="USD",
                    time_zone=time_zone,
                    rule_basis_snapshot=policy.rule_basis,
                    calculation_snapshot_json=snapshot_json,
                    calculation_snapshot_hash=fingerprint(snapshot_json),
                    processing_acknowledged=False,
                    processing_acknowledgment_reason=None,
                    internal_notes="Automatically assessed per confirmed lease late-fee policy.",
                    replaces_assessment_id=None,
                    voided_at=None,
                    void_reason=None,
                    assessed_at=captured_at.isoformat(),
                    assessed_by_actor="system:auto_late_fee",
                )
                pending_rows.append((created, policy.rule_basis))

            if not pending_rows:
                return []

            command_payload = {
                "asOfDate": current_local_date,
                "rentExpectationId": rent_expectation_id,
                "items": [
                    {
                        "rentExpectationId": row.rent_expectation_id,
                        "occurrenceNumber": row.occurrence_number,
                        "assessedAmountMinor": row.assessed_amount_minor,
                    }
                    for row, _basis in pending_rows
                ],
            }
            idempotency_key = str(
                uuid5(
                    NAMESPACE_URL,
                    f"epm-auto-late-fee/{lease_id}/{revision}/{fingerprint(canonical_json(command_payload))}",
                )
            )
            identity = FinanceCommandIdentity(
                FinanceScope("rent_ledger", lease_id),
                "auto_assess_late_fees",
                lease_id,
                revision,
                idempotency_key,
                command_payload,
            )

            def mutate(cmd_context):
                created_ids: list[str] = []
                for row, rule_basis in pending_rows:
                    committed_row = replace(row, assessed_at=cmd_context.committed_at)
                    tx.insert_late_fee_assessment(committed_row)
                    tx.record_change(
                        entity_type="late_fee_assessment",
                        entity_id=committed_row.id,
                        action="auto_assessed",
                        before=None,
                        after=self._assessment_detail_dict(
                            committed_row,
                            waivers=[],
                            allocations=[],
                            replaced_by_id=None,
                            source_drift_warning=False,
                        ),
                        reason=f"Automatically assessed per {rule_basis}.",
                        correlation_id=cmd_context.correlation_id,
                    )
                    created_ids.append(committed_row.id)
                return FinanceCommandOutcome(
                    {"createdCount": len(created_ids), "assessmentIds": created_ids},
                    effective=True,
                )

            result = apply_finance_command(tx.commands, identity, mutate, instant=captured_at)
            return list(result["assessmentIds"])

        return self.unit_of_work.write(operation)

    def get_assessment(self, assessment_id: str) -> dict[str, object]:
        assessment_id = canonical_uuid(assessment_id)

        def operation(tx):
            assessment = tx.late_fee_assessment(assessment_id)
            if assessment is None:
                raise FinanceNotFoundError("Late-fee assessment was not found.")
            revision = tx.commands.command_revision(
                FinanceScope("rent_ledger", assessment.lease_id)
            )
            detail = self._assessment_detail_dict(
                assessment,
                waivers=tx.late_fee_waivers_for_assessment(assessment.id),
                allocations=tx.late_fee_allocations_for_assessment(assessment.id),
                replaced_by_id=tx.late_fee_assessment_replaced_by(assessment.id),
                source_drift_warning=self._compute_drift_for_single(tx, assessment),
            )
            detail["rentLedgerRevision"] = revision
            return detail

        return self.unit_of_work.read(operation)

    def list_assessments(
        self,
        *,
        lease_id: str | None = None,
        property_id: str | None = None,
        rent_expectation_id: str | None = None,
        settlement_status: str | None = None,
        include_voided: bool = False,
        cursor: str | None = None,
        page_size: int = 50,
    ) -> dict[str, object]:
        if lease_id is not None:
            lease_id = canonical_uuid(lease_id)
        if property_id is not None:
            property_id = canonical_uuid(property_id)
        if rent_expectation_id is not None:
            rent_expectation_id = canonical_uuid(rent_expectation_id)
        if settlement_status is not None and settlement_status not in {
            "unpaid",
            "partially_paid",
            "paid",
            "waived",
            "voided",
        }:
            raise FinanceValidationError("Settlement status filter is invalid.")
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise FinanceValidationError("Page size must be between 1 and 100.")
        captured_at = self.now().astimezone(UTC)
        effective_include_voided = bool(include_voided or settlement_status == "voided")
        filter_fingerprint = fingerprint(
            canonical_json(
                {
                    "leaseId": lease_id,
                    "propertyId": property_id,
                    "rentExpectationId": rent_expectation_id,
                    "settlementStatus": settlement_status,
                    "includeVoided": effective_include_voided,
                    "pageSize": page_size,
                }
            )
        )
        cursor_key: tuple[str, str] | None = None
        cursor_as_of = captured_at
        if cursor is not None:
            decoded = _decode_queue_cursor(cursor)
            if decoded["filters"] != filter_fingerprint:
                raise FinanceConflictError(
                    "This continuation no longer matches the current late-fee filters.",
                    code="cursor_filter_mismatch",
                )
            cursor_as_of = decoded["asOf"]  # type: ignore[assignment]
            elapsed = (captured_at - cursor_as_of).total_seconds()
            if elapsed < 0 or elapsed > QUEUE_CURSOR_TTL_SECONDS:
                raise FinanceConflictError(
                    "This continuation has expired. Refresh the late-fee list.",
                    code="cursor_expired",
                )
            cursor_key = decoded["last"]  # type: ignore[assignment]

        def operation(tx):
            lease_ids_filter: list[str] | None = None
            if lease_id is not None:
                if tx.lease_status(lease_id) is None:
                    raise FinanceNotFoundError("Lease was not found.")
            elif property_id is not None:
                lease_ids_filter = tx.lease_ids_for_property(property_id)

            rows = tx.late_fee_assessment_page(
                lease_id=lease_id,
                lease_ids=lease_ids_filter,
                rent_expectation_id=rent_expectation_id,
                settlement_status=settlement_status,
                include_voided=effective_include_voided,
                cursor=cursor_key,
                limit=page_size + 1,
            )
            has_more = len(rows) > page_size
            page_rows = rows[:page_size]
            if not page_rows:
                return {"items": [], "nextCursor": None}

            assessment_ids = [item.id for item in page_rows]
            waived_totals = tx.late_fee_waiver_totals(assessment_ids)
            paid_totals = tx.late_fee_paid_totals(assessment_ids)
            replaced_by_map = tx.late_fee_assessments_replaced_by_map(assessment_ids)
            active_rows = [item for item in page_rows if item.voided_at is None]
            if active_rows:
                max_as_of = max(item.as_of_date for item in active_rows)
                allocs_by_exp = tx.active_rent_allocations_by_date(
                    [item.rent_expectation_id for item in active_rows],
                    through_on=max_as_of,
                )
            else:
                allocs_by_exp = {}

            items: list[dict[str, object]] = []
            for item in page_rows:
                waived = waived_totals.get(item.id, 0)
                paid = paid_totals.get(item.id, 0)
                status, remaining = derive_assessment_settlement_status(
                    assessed_amount_minor=item.assessed_amount_minor,
                    waived_amount_minor=waived,
                    paid_amount_minor=paid,
                    voided_at=item.voided_at,
                )
                if settlement_status is not None and status != settlement_status:
                    continue
                snapshot = loads(item.calculation_snapshot_json)
                drift = self._has_source_drift(
                    item, snapshot, allocs_by_exp.get(item.rent_expectation_id, ())
                )
                items.append(
                    {
                        "id": item.id,
                        "leaseId": item.lease_id,
                        "rentExpectationId": item.rent_expectation_id,
                        "policyVersionId": item.policy_version_id,
                        "occurrenceNumber": item.occurrence_number,
                        "asOfDate": item.as_of_date,
                        "accrualStartsOn": item.accrual_starts_on,
                        "accrualEndsOn": item.accrual_ends_on,
                        "accrualDays": item.accrual_days,
                        "assessedAmountMinor": item.assessed_amount_minor,
                        "waivedAmountMinor": waived,
                        "paidAmountMinor": paid,
                        "remainingBalanceMinor": remaining,
                        "settlementStatus": status,
                        "currencyCode": item.currency_code,
                        "timeZone": item.time_zone,
                        "ruleBasisSnapshot": item.rule_basis_snapshot,
                        "processingAcknowledged": item.processing_acknowledged,
                        "processingAcknowledgmentReason": item.processing_acknowledgment_reason,
                        "internalNotes": item.internal_notes,
                        "replacesAssessmentId": item.replaces_assessment_id,
                        "replacedByAssessmentId": replaced_by_map.get(item.id),
                        "voidedAt": item.voided_at,
                        "voidReason": item.void_reason,
                        "assessedAt": item.assessed_at,
                        "assessedByActor": item.assessed_by_actor,
                        "sourceDriftWarning": drift,
                    }
                )
            next_cursor = (
                _encode_queue_cursor(
                    {
                        "v": 1,
                        "asOf": cursor_as_of.isoformat(),
                        "filters": filter_fingerprint,
                        "last": [page_rows[-1].as_of_date, page_rows[-1].id],
                    }
                )
                if has_more
                else None
            )
            return {"items": items, "nextCursor": next_cursor}

        return self.unit_of_work.read(operation)

    @staticmethod
    def _has_source_drift(
        assessment: LateFeeAssessment,
        snapshot: dict[str, object],
        current_allocations: list[tuple[str, int]],
    ) -> bool:
        if assessment.voided_at is not None:
            return False
        grace_ends_on = snapshot.get("graceEndsOn")
        if not isinstance(grace_ends_on, str):
            return False
        current_through_grace = 0
        current_after_grace = 0
        for received_on, amount_minor in current_allocations:
            if received_on <= grace_ends_on:
                current_through_grace += amount_minor
            elif received_on <= assessment.as_of_date:
                current_after_grace += amount_minor
        return current_through_grace != snapshot.get(
            "paidThroughGraceMinor", 0
        ) or current_after_grace != snapshot.get("paidAfterGraceThroughAsOfMinor", 0)

    def _compute_drift_for_single(self, tx, assessment: LateFeeAssessment) -> bool:
        if assessment.voided_at is not None:
            return False
        snapshot = loads(assessment.calculation_snapshot_json)
        allocs = tx.active_rent_allocations_by_date(
            [assessment.rent_expectation_id], through_on=assessment.as_of_date
        ).get(assessment.rent_expectation_id, ())
        return self._has_source_drift(assessment, snapshot, allocs)

    @staticmethod
    def _assessment_detail_dict(
        assessment: LateFeeAssessment,
        *,
        waivers: list[LateFeeWaiver],
        allocations: list[dict[str, object]],
        replaced_by_id: str | None,
        source_drift_warning: bool,
    ) -> dict[str, object]:
        waived_minor = sum(item.waived_amount_minor for item in waivers)
        paid_minor = sum(
            int(item["amountMinor"])
            for item in allocations
            if item["receiptLifecycleStatus"] == "active"
        )
        status, remaining = derive_assessment_settlement_status(
            assessed_amount_minor=assessment.assessed_amount_minor,
            waived_amount_minor=waived_minor,
            paid_amount_minor=paid_minor,
            voided_at=assessment.voided_at,
        )
        snapshot = loads(assessment.calculation_snapshot_json)
        return {
            "id": assessment.id,
            "leaseId": assessment.lease_id,
            "rentExpectationId": assessment.rent_expectation_id,
            "policyVersionId": assessment.policy_version_id,
            "occurrenceNumber": assessment.occurrence_number,
            "asOfDate": assessment.as_of_date,
            "accrualStartsOn": assessment.accrual_starts_on,
            "accrualEndsOn": assessment.accrual_ends_on,
            "accrualDays": assessment.accrual_days,
            "assessedAmountMinor": assessment.assessed_amount_minor,
            "waivedAmountMinor": waived_minor,
            "paidAmountMinor": paid_minor,
            "remainingBalanceMinor": remaining,
            "settlementStatus": status,
            "currencyCode": assessment.currency_code,
            "timeZone": assessment.time_zone,
            "ruleBasisSnapshot": assessment.rule_basis_snapshot,
            "calculationSnapshotHash": assessment.calculation_snapshot_hash,
            "calculationSnapshot": snapshot,
            "calculationSteps": snapshot.get("calculationSteps", []),
            "processingAcknowledged": assessment.processing_acknowledged,
            "processingAcknowledgmentReason": assessment.processing_acknowledgment_reason,
            "internalNotes": assessment.internal_notes,
            "replacesAssessmentId": assessment.replaces_assessment_id,
            "replacedByAssessmentId": replaced_by_id,
            "voidedAt": assessment.voided_at,
            "voidReason": assessment.void_reason,
            "assessedAt": assessment.assessed_at,
            "assessedByActor": assessment.assessed_by_actor,
            "sourceDriftWarning": source_drift_warning,
            "waivers": [item.to_dict() for item in waivers],
            "allocations": allocations,
        }

    def _record_late_fee_receipt_in_tx(
        self,
        tx,
        *,
        lease_id: str,
        command: RecordLateFeeReceiptCommand,
        receipt_idempotency_key: str,
        payment_batch_id: str | None,
        instant: datetime,
        correlation_id: str,
        audit_reason: str,
    ) -> dict[str, object]:
        lease_ctx = tx.lease_preview_context(lease_id)
        if lease_ctx is None:
            raise FinanceNotFoundError("Lease was not found.")
        if lease_ctx["status"] == "void":
            raise FinanceConflictError(
                "Cannot record a late-fee receipt for a void lease.",
                code="lease_void",
            )
        current_local_date = instant.astimezone(ZoneInfo(lease_ctx["time_zone"])).date().isoformat()
        if command.received_on > current_local_date:
            raise FinanceValidationError("Received date cannot be in the future.")
        if command.received_by_party_id and not tx.party_exists(command.received_by_party_id):
            raise FinanceNotFoundError("Recipient party was not found.")
        if command.replaces_receipt_id:
            replaced = tx.late_fee_receipt(command.replaces_receipt_id)
            if replaced is None:
                raise FinanceNotFoundError("Replaced late-fee receipt was not found.")
            if replaced.voided_at is None or replaced.lease_id != lease_id:
                raise FinanceConflictError(
                    "Replacement must target a voided late-fee receipt on the same lease.",
                    code="late_fee_receipt_replacement_invalid",
                )
            if tx.late_fee_receipt_replacement_exists(replaced.id):
                raise FinanceConflictError(
                    "A replacement late-fee receipt already exists.",
                    code="late_fee_receipt_already_replaced",
                )
        assessment_ids = [item.assessment_id for item in command.allocations]
        waived_totals = tx.late_fee_waiver_totals(assessment_ids)
        paid_totals = tx.late_fee_paid_totals(assessment_ids)
        processing_map = tx.pending_payments_for_assessments(assessment_ids)
        for allocation in command.allocations:
            assessment = tx.late_fee_assessment(allocation.assessment_id)
            if assessment is None:
                raise FinanceNotFoundError("Allocated late-fee assessment was not found.")
            if assessment.lease_id != lease_id or assessment.voided_at is not None:
                raise FinanceConflictError(
                    "Allocated late-fee assessment is not active on this lease.",
                    code="late_fee_assessment_not_eligible",
                )
            remaining = max(
                0,
                assessment.assessed_amount_minor
                - waived_totals.get(assessment.id, 0)
                - paid_totals.get(assessment.id, 0),
            )
            if allocation.amount_minor > remaining:
                raise FinanceConflictError(
                    "Late-fee allocation exceeds the remaining unpaid assessment balance.",
                    code="late_fee_allocation_exceeds_balance",
                )
            processing = processing_map.get(assessment.id, EMPTY_PENDING_PAYMENTS)
            if allocation.amount_minor > max(0, remaining - processing.total_minor):
                raise FinanceConflictError(
                    "Late-fee receipt conflicts with processing payments on this assessment.",
                    code="late_fee_processing_reservation_conflict",
                )
        created_at = instant.astimezone(UTC).isoformat()
        receipt = LateFeeReceipt(
            id=str(uuid4()),
            lease_id=lease_id,
            idempotency_key=receipt_idempotency_key,
            payment_batch_id=payment_batch_id,
            received_on=command.received_on,
            amount_minor=command.amount_minor,
            currency_code="USD",
            payment_method_kind=command.payment_method_kind,
            payment_method_label=command.payment_method_label,
            masked_reference=command.masked_reference,
            other_payment_method_note=command.other_payment_method_note,
            received_by_party_id=command.received_by_party_id,
            replaces_receipt_id=command.replaces_receipt_id,
            notes=command.notes,
            voided_at=None,
            void_reason=None,
            created_at=created_at,
        )
        tx.insert_late_fee_receipt(receipt)
        tx.record_change(
            entity_type="late_fee_receipt",
            entity_id=receipt.id,
            action="recorded",
            before=None,
            after=receipt.to_dict(),
            reason=audit_reason,
            correlation_id=correlation_id,
        )
        allocation_views: list[dict[str, object]] = []
        for allocation in command.allocations:
            row = {
                "id": str(uuid4()),
                "receipt_id": receipt.id,
                "assessment_id": allocation.assessment_id,
                "amount_minor": allocation.amount_minor,
                "created_at": created_at,
            }
            tx.insert_late_fee_receipt_allocation(row)
            view = {
                "id": row["id"],
                "receiptId": receipt.id,
                "assessmentId": allocation.assessment_id,
                "amountMinor": allocation.amount_minor,
                "createdAt": created_at,
            }
            tx.record_change(
                entity_type="late_fee_receipt_allocation",
                entity_id=row["id"],
                action="created",
                before=None,
                after=view,
                reason=audit_reason,
                correlation_id=correlation_id,
            )
            allocation_views.append(view)
        return {**receipt.to_dict(), "allocations": allocation_views}

    def record_late_fee_receipt(
        self,
        lease_id: str,
        command: RecordLateFeeReceiptCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        lease_id = canonical_uuid(lease_id)
        identity = FinanceCommandIdentity(
            FinanceScope("rent_ledger", lease_id),
            "record_late_fee_receipt",
            lease_id,
            expected_revision,
            idempotency_key,
            command.command_payload(),
        )
        instant = self.now().astimezone(UTC)

        def operation(tx):
            def mutate(context):
                view = self._record_late_fee_receipt_in_tx(
                    tx,
                    lease_id=lease_id,
                    command=command,
                    receipt_idempotency_key=idempotency_key,
                    payment_batch_id=None,
                    instant=instant,
                    correlation_id=context.correlation_id,
                    audit_reason="late_fee_receipt_recorded",
                )
                return FinanceCommandOutcome(view, effective=True)

            return apply_finance_command(tx.commands, identity, mutate, instant=instant)

        return self.unit_of_work.write(operation)

    def record_combined_receipt(
        self,
        lease_id: str,
        command: RecordCombinedReceiptCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        lease_id = canonical_uuid(lease_id)
        identity = FinanceCommandIdentity(
            FinanceScope("rent_ledger", lease_id),
            "record_combined_receipt",
            lease_id,
            expected_revision,
            idempotency_key,
            command.command_payload(),
        )
        instant = self.now().astimezone(UTC)

        def operation(tx):
            def mutate(context):
                batch_id = str(uuid4())
                rent_cmd = RecordReceiptCommand(
                    lease_id=lease_id,
                    idempotency_key=str(uuid4()),
                    received_on=command.received_on,
                    amount_minor=command.rent_amount_minor,
                    currency_code="USD",
                    allocations=command.rent_allocations,
                    payment_method_kind=command.payment_method_kind,
                    payment_method_label=command.payment_method_label,
                    masked_reference=command.masked_reference,
                    other_payment_method_note=command.other_payment_method_note,
                    received_by_party_id=command.received_by_party_id,
                    notes=command.notes,
                    duplicate_confirmed=command.duplicate_confirmed,
                    duplicate_reason=command.duplicate_reason,
                )
                rent_receipt = record_receipt_in_transaction(
                    tx,
                    rent_cmd,
                    now=lambda: instant,
                    correlation_id=context.correlation_id,
                    audit_reason="combined_receipt_recorded",
                    payment_batch_id=batch_id,
                )
                fee_cmd = RecordLateFeeReceiptCommand(
                    received_on=command.received_on,
                    amount_minor=command.late_fee_amount_minor,
                    currency_code="USD",
                    allocations=command.late_fee_allocations,
                    payment_method_kind=command.payment_method_kind,
                    payment_method_label=command.payment_method_label,
                    masked_reference=command.masked_reference,
                    other_payment_method_note=command.other_payment_method_note,
                    received_by_party_id=command.received_by_party_id,
                    notes=command.notes,
                )
                fee_receipt_view = self._record_late_fee_receipt_in_tx(
                    tx,
                    lease_id=lease_id,
                    command=fee_cmd,
                    receipt_idempotency_key=str(uuid4()),
                    payment_batch_id=batch_id,
                    instant=instant,
                    correlation_id=context.correlation_id,
                    audit_reason="combined_receipt_recorded",
                )
                rent_allocs = [
                    {
                        "id": row["id"],
                        "receiptId": rent_receipt.id,
                        "expectationId": row["expectation_id"],
                        "amountMinor": int(row["amount_minor"]),
                        "createdAt": row["created_at"],
                    }
                    for row in tx.receipt_allocations(rent_receipt.id)
                ]
                return FinanceCommandOutcome(
                    {
                        "paymentBatchId": batch_id,
                        "leaseId": lease_id,
                        "receivedOn": command.received_on,
                        "rentAmountMinor": command.rent_amount_minor,
                        "lateFeeAmountMinor": command.late_fee_amount_minor,
                        "totalAmountMinor": command.total_amount_minor,
                        "currencyCode": "USD",
                        "rentReceipt": {**rent_receipt.to_dict(), "allocations": rent_allocs},
                        "lateFeeReceipt": fee_receipt_view,
                    },
                    effective=True,
                )

            return apply_finance_command(tx.commands, identity, mutate, instant=instant)

        return self.unit_of_work.write(operation)

    def get_late_fee_receipt(self, receipt_id: str) -> dict[str, object]:
        receipt_id = canonical_uuid(receipt_id)

        def operation(tx):
            receipt = tx.late_fee_receipt(receipt_id)
            if receipt is None:
                raise FinanceNotFoundError("Late-fee receipt was not found.")
            return {
                **receipt.to_dict(),
                "replacedByReceiptId": tx.late_fee_receipt_replaced_by(receipt.id),
                "rentLedgerRevision": tx.commands.command_revision(
                    FinanceScope("rent_ledger", receipt.lease_id)
                ),
                "allocations": tx.late_fee_receipt_allocations_for_receipt(receipt.id),
            }

        return self.unit_of_work.read(operation)

    def void_late_fee_receipt(
        self,
        receipt_id: str,
        command: VoidLateFeeReceiptCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        receipt_id = canonical_uuid(receipt_id)
        instant = self.now().astimezone(UTC)

        def operation(tx):
            prior_op = tx.commands.command_operation(idempotency_key)
            if prior_op is not None:
                lease_id = prior_op["scope_id"]
            else:
                existing = tx.late_fee_receipt(receipt_id)
                if existing is None:
                    raise FinanceNotFoundError("Late-fee receipt was not found.")
                lease_id = existing.lease_id
            identity = FinanceCommandIdentity(
                FinanceScope("rent_ledger", lease_id),
                "void_late_fee_receipt",
                receipt_id,
                expected_revision,
                idempotency_key,
                {"confirmed": command.confirmed, "reason": command.reason},
            )

            def mutate(context):
                receipt = tx.late_fee_receipt(receipt_id)
                if receipt is None:
                    raise FinanceNotFoundError("Late-fee receipt was not found.")
                if receipt.voided_at is not None:
                    raise FinanceConflictError(
                        "Late-fee receipt is already voided.",
                        code="late_fee_receipt_already_voided",
                    )
                voided = replace(
                    receipt,
                    voided_at=context.committed_at,
                    void_reason=command.reason,
                )
                tx.void_late_fee_receipt(voided)
                tx.record_change(
                    entity_type="late_fee_receipt",
                    entity_id=voided.id,
                    action="voided",
                    before=receipt.to_dict(),
                    after=voided.to_dict(),
                    reason=command.reason,
                    correlation_id=context.correlation_id,
                )
                return FinanceCommandOutcome(
                    {
                        **voided.to_dict(),
                        "allocations": tx.late_fee_receipt_allocations_for_receipt(voided.id),
                    },
                    effective=True,
                )

            return apply_finance_command(tx.commands, identity, mutate, instant=instant)

        return self.unit_of_work.write(operation)

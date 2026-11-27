"""Finance-owned PAY-001 late-fee allocation, outcome, return, and autopay helpers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from json import loads
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import func, select

from app.modules.finance.application.commands import (
    FinanceScope,
    canonical_json,
    canonical_uuid,
    fingerprint,
)
from app.modules.finance.application.late_fee_ports import (
    EMPTY_PENDING_PAYMENTS,
    NoOpPendingPaymentReader,
    PendingPaymentReader,
)
from app.modules.finance.application.receipt_handoff import (
    record_receipt_in_transaction,
    void_receipt_in_transaction,
)
from app.modules.finance.domain.late_fee_models import (
    LateFeeReceipt,
    LateFeeReceiptAllocationCommand,
    RecordLateFeeReceiptCommand,
)
from app.modules.finance.domain.models import (
    FinanceConflictError,
    FinanceValidationError,
    ReceiptAllocationCommand,
    RecordReceiptCommand,
)
from app.modules.finance.domain.pay001_contracts import (
    ALLOCATION_ORDER_EXPLANATION,
    VALID_AUTOPAY_MANDATE_SCOPES,
    AutopayMandateScope,
    AutopayOccurrencePlan,
    ChargeAllocationPreview,
    ChargeAllocationTarget,
    ProviderPaymentOutcomeCommand,
    UnappliedProcessorFundsException,
)
from app.modules.finance.infrastructure.command_models import FinanceCommandRevisionModel
from app.modules.finance.infrastructure.sqlalchemy_models import (
    LateFeeAssessmentModel,
    LateFeeReceiptAllocationModel,
    LateFeeReceiptModel,
    LateFeeWaiverModel,
    RentExpectationModel,
    RentReceiptAllocationModel,
    RentReceiptModel,
)


def build_charge_allocation_preview(
    connection: Any,
    *,
    lease_id: str,
    payment_amount_minor: int | None = None,
    include_late_fees: bool = True,
    rent_due_on_or_before: str | None = None,
    pending_payment_reader: PendingPaymentReader | None = None,
) -> ChargeAllocationPreview:
    """Allocate oldest eligible unpaid rent first, then oldest eligible unpaid assessed late fees."""
    lease_id = canonical_uuid(lease_id)
    reader = pending_payment_reader or NoOpPendingPaymentReader()
    if payment_amount_minor is not None and (
        type(payment_amount_minor) is not int or payment_amount_minor <= 0
    ):
        raise FinanceValidationError("Payment amount must be a positive integer.")
    if rent_due_on_or_before is not None:
        try:
            rent_due_on_or_before = date.fromisoformat(rent_due_on_or_before).isoformat()
        except (TypeError, ValueError) as error:
            raise FinanceValidationError(
                "rentDueOnOrBefore must be a valid ISO calendar date."
            ) from error

    revision = (
        connection.scalar(
            select(FinanceCommandRevisionModel.revision).where(
                FinanceCommandRevisionModel.scope_kind == "rent_ledger",
                FinanceCommandRevisionModel.scope_id == lease_id,
            )
        )
        or 0
    )

    # 1. Load active rent expectations ordered by (due_on, id) and subtract active paid + reserved.
    exp_query = (
        select(
            RentExpectationModel.id,
            RentExpectationModel.expected_amount_minor,
        )
        .where(
            RentExpectationModel.lease_id == lease_id,
            RentExpectationModel.voided_at.is_(None),
        )
        .order_by(RentExpectationModel.due_on, RentExpectationModel.id)
    )
    if rent_due_on_or_before is not None:
        exp_query = exp_query.where(RentExpectationModel.due_on <= rent_due_on_or_before)
    exp_rows = connection.execute(exp_query).mappings().all()
    exp_ids = [row["id"] for row in exp_rows]
    rent_paid: dict[str, int] = {}
    if exp_ids:
        for exp_id, total in connection.execute(
            select(
                RentReceiptAllocationModel.expectation_id,
                func.sum(RentReceiptAllocationModel.amount_minor),
            )
            .join(RentReceiptModel, RentReceiptModel.id == RentReceiptAllocationModel.receipt_id)
            .where(
                RentReceiptAllocationModel.expectation_id.in_(exp_ids),
                RentReceiptModel.voided_at.is_(None),
            )
            .group_by(RentReceiptAllocationModel.expectation_id)
        ).all():
            rent_paid[exp_id] = int(total)
    rent_pending = reader.processing_for_expectations(connection, exp_ids) if exp_ids else {}

    ordered_open: list[tuple[str, str, int]] = []
    for row in exp_rows:
        exp_id = row["id"]
        reserved = rent_pending.get(exp_id, EMPTY_PENDING_PAYMENTS).total_minor
        eligible = max(0, int(row["expected_amount_minor"]) - rent_paid.get(exp_id, 0) - reserved)
        if eligible > 0:
            ordered_open.append(("rent_expectation", exp_id, eligible))

    # 2. Load active late-fee assessments ordered by (as_of_date, assessed_at, id).
    if include_late_fees:
        ass_rows = (
            connection.execute(
                select(
                    LateFeeAssessmentModel.id,
                    LateFeeAssessmentModel.assessed_amount_minor,
                )
                .where(
                    LateFeeAssessmentModel.lease_id == lease_id,
                    LateFeeAssessmentModel.voided_at.is_(None),
                )
                .order_by(
                    LateFeeAssessmentModel.as_of_date,
                    LateFeeAssessmentModel.assessed_at,
                    LateFeeAssessmentModel.id,
                )
            )
            .mappings()
            .all()
        )
        ass_ids = [row["id"] for row in ass_rows]
        waived_map: dict[str, int] = {}
        paid_map: dict[str, int] = {}
        if ass_ids:
            for aid, total in connection.execute(
                select(
                    LateFeeWaiverModel.assessment_id,
                    func.sum(LateFeeWaiverModel.waived_amount_minor),
                )
                .where(LateFeeWaiverModel.assessment_id.in_(ass_ids))
                .group_by(LateFeeWaiverModel.assessment_id)
            ).all():
                waived_map[aid] = int(total)
            for aid, total in connection.execute(
                select(
                    LateFeeReceiptAllocationModel.assessment_id,
                    func.sum(LateFeeReceiptAllocationModel.amount_minor),
                )
                .join(
                    LateFeeReceiptModel,
                    LateFeeReceiptModel.id == LateFeeReceiptAllocationModel.receipt_id,
                )
                .where(
                    LateFeeReceiptAllocationModel.assessment_id.in_(ass_ids),
                    LateFeeReceiptModel.voided_at.is_(None),
                )
                .group_by(LateFeeReceiptAllocationModel.assessment_id)
            ).all():
                paid_map[aid] = int(total)
        fee_pending = reader.processing_for_assessments(connection, ass_ids) if ass_ids else {}
        for row in ass_rows:
            aid = row["id"]
            reserved = fee_pending.get(aid, EMPTY_PENDING_PAYMENTS).total_minor
            eligible = max(
                0,
                int(row["assessed_amount_minor"])
                - waived_map.get(aid, 0)
                - paid_map.get(aid, 0)
                - reserved,
            )
            if eligible > 0:
                ordered_open.append(("late_fee_assessment", aid, eligible))

    total_eligible = sum(amount for _, _, amount in ordered_open)
    if payment_amount_minor is not None and payment_amount_minor > total_eligible:
        raise FinanceConflictError(
            "Requested payment amount exceeds total eligible unpaid balance.",
            code="payment_exceeds_eligible_balance",
        )

    remaining_to_allocate = total_eligible if payment_amount_minor is None else payment_amount_minor
    allocations: list[ChargeAllocationTarget] = []
    rent_total = 0
    fee_total = 0
    for kind, target_id, eligible in ordered_open:
        if remaining_to_allocate <= 0:
            break
        take = min(eligible, remaining_to_allocate)
        allocations.append(ChargeAllocationTarget(kind, target_id, take))  # type: ignore[arg-type]
        if kind == "rent_expectation":
            rent_total += take
        else:
            fee_total += take
        remaining_to_allocate -= take

    return ChargeAllocationPreview(
        lease_id=lease_id,
        rent_total_minor=rent_total,
        late_fee_total_minor=fee_total,
        gross_total_minor=rent_total + fee_total,
        allocations=tuple(allocations),
        allocation_order_explanation=ALLOCATION_ORDER_EXPLANATION,
        rent_ledger_revision=int(revision),
    )


def plan_autopay_occurrence(
    connection: Any,
    *,
    lease_id: str,
    mandate_scope: AutopayMandateScope,
    max_amount_minor: int,
    scheduled_on: str | date,
    pending_payment_reader: PendingPaymentReader | None = None,
) -> AutopayOccurrencePlan:
    """Plan one autopay occurrence honoring mandate_scope (D10), scheduled_on due cutoff, and cap."""
    if mandate_scope not in VALID_AUTOPAY_MANDATE_SCOPES:
        raise FinanceValidationError(
            "mandateScope must be rent_only or rent_and_assessed_late_fees."
        )
    if type(max_amount_minor) is not int or max_amount_minor <= 0:
        raise FinanceValidationError("Autopay maxAmountMinor must be a positive integer.")
    if isinstance(scheduled_on, date) and not isinstance(scheduled_on, datetime):
        scheduled_on_iso = scheduled_on.isoformat()
    elif isinstance(scheduled_on, str):
        try:
            scheduled_on_iso = date.fromisoformat(scheduled_on).isoformat()
        except ValueError as error:
            raise FinanceValidationError(
                "Autopay scheduledOn must be a valid ISO calendar date."
            ) from error
    else:
        raise FinanceValidationError("Autopay scheduledOn must be a valid calendar date.")

    include_fees = mandate_scope == "rent_and_assessed_late_fees"
    full_open = build_charge_allocation_preview(
        connection,
        lease_id=lease_id,
        payment_amount_minor=None,
        include_late_fees=include_fees,
        rent_due_on_or_before=scheduled_on_iso,
        pending_payment_reader=pending_payment_reader,
    )
    capped_amount = min(full_open.gross_total_minor, max_amount_minor)
    if capped_amount == 0:
        return AutopayOccurrencePlan(
            lease_id=full_open.lease_id,
            mandate_scope=mandate_scope,
            max_amount_minor=max_amount_minor,
            rent_total_minor=0,
            late_fee_total_minor=0,
            gross_total_minor=0,
            allocations=(),
            allocation_order_explanation=ALLOCATION_ORDER_EXPLANATION,
            rent_ledger_revision=full_open.rent_ledger_revision,
        )
    capped = build_charge_allocation_preview(
        connection,
        lease_id=lease_id,
        payment_amount_minor=capped_amount,
        include_late_fees=include_fees,
        rent_due_on_or_before=scheduled_on_iso,
        pending_payment_reader=pending_payment_reader,
    )
    return AutopayOccurrencePlan(
        lease_id=capped.lease_id,
        mandate_scope=mandate_scope,
        max_amount_minor=max_amount_minor,
        rent_total_minor=capped.rent_total_minor,
        late_fee_total_minor=capped.late_fee_total_minor,
        gross_total_minor=capped.gross_total_minor,
        allocations=capped.allocations,
        allocation_order_explanation=ALLOCATION_ORDER_EXPLANATION,
        rent_ledger_revision=capped.rent_ledger_revision,
    )


def apply_provider_payment_outcome_in_transaction(
    tx,
    command: ProviderPaymentOutcomeCommand,
    *,
    now: datetime,
    correlation_id: str,
) -> dict[str, object]:
    """Atomically settle typed rent + late-fee lines with durable attempt-level idempotency."""
    instant = now.astimezone(UTC)
    attempt_op_key = str(uuid5(NAMESPACE_URL, f"epm:pay001:outcome:{command.payment_attempt_id}"))
    request_json = canonical_json(
        {
            "scopeKind": "rent_ledger",
            "scopeId": command.lease_id,
            "action": "apply_provider_payment_outcome",
            "targetId": command.payment_attempt_id,
            "payload": {
                "paymentAttemptId": command.payment_attempt_id,
                "leaseId": command.lease_id,
                "receivedOn": command.received_on,
                "paymentMethodKind": command.payment_method_kind,
                "paymentMethodLabel": command.payment_method_label,
                "maskedReference": command.masked_reference,
                "otherPaymentMethodNote": command.other_payment_method_note,
                "receivedByPartyId": command.received_by_party_id,
                "notes": command.notes,
                "allocations": [
                    {
                        "chargeKind": item.charge_kind,
                        "targetId": item.target_id,
                        "amountMinor": item.amount_minor,
                    }
                    for item in command.allocations
                ],
            },
        }
    )
    request_hash = fingerprint(request_json)
    prior = tx.commands.command_operation(attempt_op_key)
    if prior is not None:
        if prior["request_fingerprint"] != request_hash:
            raise FinanceConflictError(
                "Provider payment attempt key was reused with a different payload.",
                code="finance_idempotency_conflict",
            )
        return loads(prior["response_json"])

    batch_id = str(uuid5(NAMESPACE_URL, f"epm:pay001:batch:{command.payment_attempt_id}"))
    rent_receipt_key = str(
        uuid5(NAMESPACE_URL, f"epm:pay001:rent_receipt:{command.payment_attempt_id}")
    )
    fee_receipt_key = str(
        uuid5(NAMESPACE_URL, f"epm:pay001:fee_receipt:{command.payment_attempt_id}")
    )
    rent_allocs: list[ReceiptAllocationCommand] = []
    fee_allocs: list[LateFeeReceiptAllocationCommand] = []
    unapplied: list[UnappliedProcessorFundsException] = []

    for target in command.allocations:
        if target.charge_kind == "rent_expectation":
            expectation = tx.expectation(target.target_id)
            if (
                expectation is None
                or expectation.lease_id != command.lease_id
                or expectation.voided_at is not None
            ):
                unapplied.append(
                    UnappliedProcessorFundsException(
                        "rent_expectation",
                        target.target_id,
                        target.amount_minor,
                        "target_voided_or_missing_before_settlement",
                    )
                )
                continue
            remaining = max(
                0, expectation.expected_amount_minor - tx.allocated_amount(expectation.id)
            )
            apply_minor = min(target.amount_minor, remaining)
            excess = target.amount_minor - apply_minor
            if apply_minor > 0:
                rent_allocs.append(ReceiptAllocationCommand(expectation.id, apply_minor))
            if excess > 0:
                unapplied.append(
                    UnappliedProcessorFundsException(
                        "rent_expectation",
                        target.target_id,
                        excess,
                        "balance_reduced_before_settlement",
                    )
                )
        else:
            assessment = tx.late_fee_assessment(target.target_id)
            if (
                assessment is None
                or assessment.lease_id != command.lease_id
                or assessment.voided_at is not None
            ):
                unapplied.append(
                    UnappliedProcessorFundsException(
                        "late_fee_assessment",
                        target.target_id,
                        target.amount_minor,
                        "late_fee_voided_or_missing_before_settlement",
                    )
                )
                continue
            waived = tx.late_fee_waiver_totals([assessment.id]).get(assessment.id, 0)
            paid = tx.late_fee_paid_totals([assessment.id]).get(assessment.id, 0)
            remaining = max(0, assessment.assessed_amount_minor - waived - paid)
            apply_minor = min(target.amount_minor, remaining)
            excess = target.amount_minor - apply_minor
            if apply_minor > 0:
                fee_allocs.append(LateFeeReceiptAllocationCommand(assessment.id, apply_minor))
            if excess > 0:
                unapplied.append(
                    UnappliedProcessorFundsException(
                        "late_fee_assessment",
                        target.target_id,
                        excess,
                        "late_fee_waived_or_paid_before_settlement",
                    )
                )

    rent_receipt_id: str | None = None
    late_fee_receipt_id: str | None = None

    if rent_allocs:
        rent_total = sum(item.amount_minor for item in rent_allocs)
        rent_receipt = record_receipt_in_transaction(
            tx,
            RecordReceiptCommand(
                lease_id=command.lease_id,
                idempotency_key=rent_receipt_key,
                received_on=command.received_on,
                amount_minor=rent_total,
                currency_code="USD",
                allocations=tuple(rent_allocs),
                payment_method_kind=command.payment_method_kind,
                payment_method_label=command.payment_method_label,
                masked_reference=command.masked_reference,
                other_payment_method_note=command.other_payment_method_note,
                received_by_party_id=command.received_by_party_id,
                notes=command.notes,
            ),
            now=lambda: instant,
            correlation_id=correlation_id,
            audit_reason="provider_payment_settled",
            payment_batch_id=batch_id,
            skip_duplicate_check=True,
        )
        rent_receipt_id = rent_receipt.id

    if fee_allocs:
        fee_total = sum(item.amount_minor for item in fee_allocs)
        fee_cmd = RecordLateFeeReceiptCommand(
            received_on=command.received_on,
            amount_minor=fee_total,
            currency_code="USD",
            allocations=tuple(fee_allocs),
            payment_method_kind=command.payment_method_kind,
            payment_method_label=command.payment_method_label,
            masked_reference=command.masked_reference,
            other_payment_method_note=command.other_payment_method_note,
            received_by_party_id=command.received_by_party_id,
            notes=command.notes,
        )
        created_at = instant.isoformat()
        fee_receipt = LateFeeReceipt(
            id=str(uuid4()),
            lease_id=command.lease_id,
            idempotency_key=fee_receipt_key,
            payment_batch_id=batch_id,
            received_on=fee_cmd.received_on,
            amount_minor=fee_cmd.amount_minor,
            currency_code="USD",
            payment_method_kind=fee_cmd.payment_method_kind,
            payment_method_label=fee_cmd.payment_method_label,
            masked_reference=fee_cmd.masked_reference,
            other_payment_method_note=fee_cmd.other_payment_method_note,
            received_by_party_id=fee_cmd.received_by_party_id,
            replaces_receipt_id=None,
            notes=fee_cmd.notes,
            voided_at=None,
            void_reason=None,
            created_at=created_at,
        )
        tx.insert_late_fee_receipt(fee_receipt)
        tx.record_change(
            entity_type="late_fee_receipt",
            entity_id=fee_receipt.id,
            action="recorded",
            before=None,
            after=fee_receipt.to_dict(),
            reason="provider_payment_settled",
            correlation_id=correlation_id,
        )
        for item in fee_allocs:
            row = {
                "id": str(uuid4()),
                "receipt_id": fee_receipt.id,
                "assessment_id": item.assessment_id,
                "amount_minor": item.amount_minor,
                "created_at": created_at,
            }
            tx.insert_late_fee_receipt_allocation(row)
            tx.record_change(
                entity_type="late_fee_receipt_allocation",
                entity_id=row["id"],
                action="created",
                before=None,
                after={
                    "id": row["id"],
                    "receiptId": fee_receipt.id,
                    "assessmentId": item.assessment_id,
                    "amountMinor": item.amount_minor,
                    "createdAt": created_at,
                },
                reason="provider_payment_settled",
                correlation_id=correlation_id,
            )
        late_fee_receipt_id = fee_receipt.id

    scope = FinanceScope("rent_ledger", command.lease_id)
    current_revision = tx.commands.command_revision(scope)
    effective = int(bool(rent_allocs or fee_allocs))
    result_revision = current_revision + effective
    operation_id = str(uuid4())
    response: dict[str, object] = {
        "paymentAttemptId": command.payment_attempt_id,
        "paymentBatchId": batch_id,
        "leaseId": command.lease_id,
        "rentReceiptId": rent_receipt_id,
        "lateFeeReceiptId": late_fee_receipt_id,
        "appliedRentMinor": sum(item.amount_minor for item in rent_allocs),
        "appliedLateFeeMinor": sum(item.amount_minor for item in fee_allocs),
        "unappliedProcessorFundsMinor": sum(item.excess_amount_minor for item in unapplied),
        "unappliedProcessorFunds": [item.to_dict() for item in unapplied],
        "rentLedgerRevision": result_revision,
        "operationId": operation_id,
    }
    response_json = canonical_json(response)
    tx.commands.store_command(
        {
            "id": operation_id,
            "scope_kind": scope.kind,
            "scope_id": scope.id,
            "idempotency_key": attempt_op_key,
            "action": "apply_provider_payment_outcome",
            "target_id": command.payment_attempt_id,
            "expected_revision": current_revision,
            "result_revision": result_revision,
            "effective": effective,
            "request_json": request_json,
            "request_fingerprint": request_hash,
            "response_json": response_json,
            "response_fingerprint": fingerprint(response_json),
            "correlation_id": correlation_id,
            "created_at": instant.isoformat(),
        }
    )
    return response


def apply_provider_return_in_transaction(
    tx,
    *,
    rent_receipt_id: str | None,
    late_fee_receipt_id: str | None,
    reason: str,
    now: datetime,
    correlation_id: str,
) -> dict[str, object]:
    """Atomically reverse linked rent and/or late-fee receipts on bank return; never auto-assess."""
    instant = now.astimezone(UTC)
    if rent_receipt_id is None and late_fee_receipt_id is None:
        raise FinanceValidationError("At least one receipt ID is required to apply a bank return.")
    reversed_rent_id: str | None = None
    reversed_fee_id: str | None = None
    if rent_receipt_id is not None:
        rent_receipt = tx.receipt(rent_receipt_id)
        if rent_receipt is None:
            raise FinanceConflictError("Linked rent receipt was not found.")
        void_receipt_in_transaction(
            tx, rent_receipt, now=lambda: instant, reason=reason, correlation_id=correlation_id
        )
        reversed_rent_id = rent_receipt.id
    if late_fee_receipt_id is not None:
        fee_receipt = tx.late_fee_receipt(late_fee_receipt_id)
        if fee_receipt is None:
            raise FinanceConflictError("Linked late-fee receipt was not found.")
        if fee_receipt.voided_at is not None:
            raise FinanceConflictError("Linked late-fee receipt is already voided.")
        voided = replace(fee_receipt, voided_at=instant.isoformat(), void_reason=reason)
        tx.void_late_fee_receipt(voided)
        tx.record_change(
            entity_type="late_fee_receipt",
            entity_id=voided.id,
            action="voided",
            before=fee_receipt.to_dict(),
            after=voided.to_dict(),
            reason=reason,
            correlation_id=correlation_id,
        )
        reversed_fee_id = voided.id
    return {
        "reversedRentReceiptId": reversed_rent_id,
        "reversedLateFeeReceiptId": reversed_fee_id,
        "autoAssessedLateFee": False,
    }


# Keep FinanceScope exported for callers coordinating on rent_ledger revision.
__all__ = [
    "FinanceScope",
    "apply_provider_payment_outcome_in_transaction",
    "apply_provider_return_in_transaction",
    "build_charge_allocation_preview",
    "plan_autopay_occurrence",
]

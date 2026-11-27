"""Rebuild bounded OPS finance forms with Finance-owned command identities."""

from dataclasses import asdict

from app.modules.finance.application.commands import (
    FinanceCommandIdentity,
    FinanceScope,
    fingerprint,
)
from app.modules.finance.domain.late_fee_models import (
    AssessLateFeeCommand,
    CreateLateFeePolicyCommand,
    LateFeeReceiptAllocationCommand,
    RecordCombinedReceiptCommand,
    RecordLateFeeReceiptCommand,
    VoidLateFeeAssessmentCommand,
    VoidLateFeePolicyCommand,
    VoidLateFeeReceiptCommand,
    WaiveLateFeeCommand,
)
from app.modules.finance.domain.models import (
    FinanceError,
    PrepaidCheckCommand,
    PrepaidCheckTransitionCommand,
    ReceiptAllocationCommand,
    RecordReceiptCommand,
    SynchronizeExpectationsCommand,
    TimelinessReviewCommand,
    VoidCommand,
)
from app.modules.operator.domain.models import OperatorError


def finance_request(action, source_id, payload, key):
    expected = payload.get("expectedRevision")
    if type(expected) is not int or expected < 0:
        raise OperatorError("Complete the expected rent-ledger revision.")
    try:
        scope = FinanceScope("rent_ledger", source_id)
        target, request = _payload(action, source_id, payload, key)
        return fingerprint(
            FinanceCommandIdentity(scope, action, target, expected, key, request).request_json
        )
    except FinanceError as error:
        raise OperatorError(
            "Complete a valid financial command before starting an attempt."
        ) from error


def _payload(action, lease_id, payload, key):
    if action == "synchronize_expectations":
        command = SynchronizeExpectationsCommand(
            payload["leaseTermId"],
            payload["throughOn"],
            payload.get("scheduleAnchorOn"),
            payload.get("responsibilityEndsOnOverride"),
            payload.get("overrideReason"),
            payload.get("overrideConfirmed", False),
        )
        target, request = lease_id, asdict(command)
    elif action == "void_expectation":
        command = VoidCommand(payload["confirmed"], payload["voidReason"])
        target, request = payload["expectationId"], asdict(command)
    elif action == "review_timeliness":
        command = TimelinessReviewCommand(
            payload["decision"], payload["reason"], payload["confirmed"]
        )
        target, request = payload["expectationId"], asdict(command)
    elif action == "record_receipt":
        command = RecordReceiptCommand(
            lease_id=lease_id,
            idempotency_key=key,
            received_on=payload["receivedOn"],
            amount_minor=payload["amountMinor"],
            currency_code=payload["currencyCode"],
            allocations=tuple(
                ReceiptAllocationCommand(item["expectationId"], item["amountMinor"])
                for item in payload["allocations"]
            ),
            payment_method_kind=payload["paymentMethodKind"],
            payment_method_label=payload.get("paymentMethodLabel"),
            masked_reference=payload.get("maskedReference"),
            other_payment_method_note=payload.get("otherPaymentMethodNote"),
            received_by_party_id=payload.get("receivedByPartyId"),
            replaces_receipt_id=payload.get("replacesReceiptId"),
            notes=payload.get("notes"),
            duplicate_confirmed=payload.get("duplicateConfirmed", False),
            duplicate_reason=payload.get("duplicateReason"),
        )
        request = asdict(command)
        request["allocations"] = sorted(
            request["allocations"],
            key=lambda item: (item["expectation_id"], item["amount_minor"]),
        )
        target = lease_id
    elif action == "void_receipt":
        command = VoidCommand(payload["confirmed"], payload["voidReason"])
        target, request = payload["receiptId"], asdict(command)
    elif action == "create_prepaid_check":
        command = PrepaidCheckCommand(
            payload["expectationId"],
            payload["payerPartyId"],
            payload["receivedOn"],
            payload["checkDatedOn"],
            payload.get("maskedReference"),
            key,
        )
        target, request = command.expectation_id, asdict(command)
    elif action in {
        "deposit_prepaid_check",
        "return_prepaid_check",
        "void_prepaid_check",
    }:
        command = PrepaidCheckTransitionCommand(
            key,
            payload["confirmed"],
            payload.get("reason"),
            payload.get("returnedOn") or payload.get("occurredOn"),
            payload.get("existingReceiptId"),
        )
        target, request = payload["prepaidCheckId"], asdict(command)
    elif action == "replace_prepaid_check":
        command = PrepaidCheckCommand(
            payload["expectationId"],
            payload["payerPartyId"],
            payload["receivedOn"],
            payload["checkDatedOn"],
            payload.get("maskedReference"),
            key,
        )
        target, request = (
            payload["prepaidCheckId"],
            {
                **asdict(command),
                "confirmed": payload["confirmed"],
                "reason": payload["reason"].strip(),
            },
        )
    else:
        return _late_fee_payload(action, lease_id, payload)
    return target, request


def _late_fee_payload(action, lease_id, payload):
    if action == "create_late_fee_policy":
        command = CreateLateFeePolicyCommand(
            effective_on=payload["effectiveOn"],
            ends_on=payload.get("endsOn"),
            lease_term_id=payload.get("leaseTermId"),
            rule_basis=payload["ruleBasis"],
            grace_period_days=payload["gracePeriodDays"],
            calculation_basis=payload["calculationBasis"],
            formula_kind=payload["formulaKind"],
            flat_amount_minor=payload.get("flatAmountMinor"),
            percentage_bps=payload.get("percentageBps"),
            daily_amount_minor=payload.get("dailyAmountMinor"),
            max_accrual_days=payload.get("maxAccrualDays"),
            per_period_cap_minor=payload.get("perPeriodCapMinor"),
            per_period_min_minor=payload.get("perPeriodMinMinor"),
            minimum_unpaid_threshold_minor=payload.get("minimumUnpaidThresholdMinor", 0),
            rounding_mode=payload["roundingMode"],
            applies_to_prorated_periods=payload["appliesToProratedPeriods"],
            supersedes_policy_version_id=payload.get("supersedesPolicyVersionId"),
            notes=payload.get("notes"),
            operator_confirmed=payload["operatorConfirmed"],
        )
        return lease_id, command.command_payload()
    if action == "void_late_fee_policy":
        command = VoidLateFeePolicyCommand(payload["confirmed"], payload["reason"])
        return payload["policyVersionId"], {
            "confirmed": command.confirmed,
            "reason": command.reason,
        }
    if action == "assess_late_fee":
        command = AssessLateFeeCommand(
            rent_expectation_id=payload["rentExpectationId"],
            as_of_date=payload["asOfDate"],
            preview_fingerprint=payload["previewFingerprint"],
            operator_confirmed=payload["operatorConfirmed"],
            acknowledge_processing_payments=payload.get("acknowledgeProcessingPayments", False),
            processing_acknowledgment_reason=payload.get("processingAcknowledgmentReason"),
            internal_notes=payload.get("internalNotes"),
            replaces_assessment_id=payload.get("replacesAssessmentId"),
        )
        return command.rent_expectation_id, command.command_payload()
    if action == "waive_late_fee":
        command = WaiveLateFeeCommand(
            waived_amount_minor=payload["waivedAmountMinor"],
            waived_on=payload["waivedOn"],
            reason=payload["reason"],
            confirmed=payload["confirmed"],
            internal_notes=payload.get("internalNotes"),
        )
        return payload["assessmentId"], command.command_payload()
    if action == "void_late_fee_assessment":
        command = VoidLateFeeAssessmentCommand(payload["confirmed"], payload["reason"])
        return payload["assessmentId"], {"confirmed": command.confirmed, "reason": command.reason}
    return _late_fee_receipt_payload(action, lease_id, payload)


def _late_fee_receipt_payload(action, lease_id, payload):
    if action == "record_late_fee_receipt":
        command = RecordLateFeeReceiptCommand(
            received_on=payload["receivedOn"],
            amount_minor=payload["amountMinor"],
            currency_code=payload["currencyCode"],
            allocations=tuple(
                LateFeeReceiptAllocationCommand(item["assessmentId"], item["amountMinor"])
                for item in payload["allocations"]
            ),
            payment_method_kind=payload["paymentMethodKind"],
            payment_method_label=payload.get("paymentMethodLabel"),
            masked_reference=payload.get("maskedReference"),
            other_payment_method_note=payload.get("otherPaymentMethodNote"),
            received_by_party_id=payload.get("receivedByPartyId"),
            replaces_receipt_id=payload.get("replacesReceiptId"),
            notes=payload.get("notes"),
        )
        return lease_id, command.command_payload()
    if action == "void_late_fee_receipt":
        command = VoidLateFeeReceiptCommand(payload["confirmed"], payload["reason"])
        return payload["receiptId"], {"confirmed": command.confirmed, "reason": command.reason}
    if action == "record_combined_receipt":
        command = RecordCombinedReceiptCommand(
            received_on=payload["receivedOn"],
            currency_code=payload["currencyCode"],
            rent_allocations=tuple(
                ReceiptAllocationCommand(item["expectationId"], item["amountMinor"])
                for item in payload["rentAllocations"]
            ),
            late_fee_allocations=tuple(
                LateFeeReceiptAllocationCommand(item["assessmentId"], item["amountMinor"])
                for item in payload["lateFeeAllocations"]
            ),
            payment_method_kind=payload["paymentMethodKind"],
            payment_method_label=payload.get("paymentMethodLabel"),
            masked_reference=payload.get("maskedReference"),
            other_payment_method_note=payload.get("otherPaymentMethodNote"),
            received_by_party_id=payload.get("receivedByPartyId"),
            notes=payload.get("notes"),
            duplicate_confirmed=payload.get("duplicateConfirmed", False),
            duplicate_reason=payload.get("duplicateReason"),
        )
        return lease_id, command.command_payload()
    raise OperatorError("Finance command form is not registered.")

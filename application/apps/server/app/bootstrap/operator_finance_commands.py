"""Rebuild bounded OPS finance forms with Finance-owned command identities."""

from dataclasses import asdict

from app.modules.finance.application.commands import (
    FinanceCommandIdentity,
    FinanceScope,
    fingerprint,
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
        raise OperatorError("Finance command form is not registered.")
    return target, request

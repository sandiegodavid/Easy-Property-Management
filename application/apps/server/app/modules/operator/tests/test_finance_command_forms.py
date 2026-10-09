"""Slice 31: bounded financial OPS forms preserve owning Finance identities."""

from dataclasses import asdict
from uuid import uuid4

import pytest

from app.bootstrap.operator_command_forms import finance_request, require_complete_form
from app.modules.finance.application.commands import (
    FinanceCommandIdentity,
    FinanceScope,
    fingerprint,
)
from app.modules.finance.domain.models import (
    PrepaidCheckCommand,
    PrepaidCheckTransitionCommand,
    ReceiptAllocationCommand,
    RecordReceiptCommand,
    SynchronizeExpectationsCommand,
    TimelinessReviewCommand,
    VoidCommand,
)
from app.modules.operator.application.command_forms import COMMAND_SCHEMAS
from app.modules.operator.domain.models import OperatorError
from app.modules.operator.application.recovery_schemas import validate_payload

LEASE_ID, KEY = str(uuid4()), str(uuid4())
REVISION = 4


def _expected(action, target_id, payload):
    return fingerprint(
        FinanceCommandIdentity(
            FinanceScope("rent_ledger", LEASE_ID),
            action,
            target_id,
            REVISION,
            KEY,
            payload,
        ).request_json
    )


def test_finance_forms_are_registered_with_lease_source_identity():
    expected = {
        "finance.rent_expectation.synchronize": "synchronize_expectations",
        "finance.rent_expectation.void": "void_expectation",
        "finance.rent_expectation.timeliness_review": "review_timeliness",
        "finance.rent_receipt.create": "record_receipt",
        "finance.rent_receipt.void": "void_receipt",
        "finance.prepaid_check.create": "create_prepaid_check",
        "finance.prepaid_check.deposit": "deposit_prepaid_check",
        "finance.prepaid_check.return": "return_prepaid_check",
        "finance.prepaid_check.void": "void_prepaid_check",
        "finance.prepaid_check.replace": "replace_prepaid_check",
    }
    assert set(expected) <= set(COMMAND_SCHEMAS)
    assert all(COMMAND_SCHEMAS[key].model_config["extra"] == "forbid" for key in expected)


@pytest.mark.parametrize(
    ("form_key", "action", "payload", "target", "expected_payload"),
    [
        (
            "finance.rent_expectation.void",
            "void_expectation",
            {"expectationId": str(uuid4()), "confirmed": True, "voidReason": "Correction"},
            lambda p: p["expectationId"],
            lambda p: asdict(VoidCommand(True, "Correction")),
        ),
        (
            "finance.rent_expectation.timeliness_review",
            "review_timeliness",
            {
                "expectationId": str(uuid4()),
                "decision": "mark_missed",
                "reason": "No payment",
                "confirmed": True,
            },
            lambda p: p["expectationId"],
            lambda p: asdict(TimelinessReviewCommand("mark_missed", "No payment", True)),
        ),
        (
            "finance.rent_receipt.create",
            "record_receipt",
            {
                "receivedOn": "2026-10-01",
                "amountMinor": 1000,
                "currencyCode": "USD",
                "allocations": [
                    {"expectationId": str(uuid4()), "amountMinor": 1000},
                ],
                "paymentMethodKind": "bank_transfer",
            },
            lambda p: LEASE_ID,
            lambda p: _receipt_request(p),
        ),
        (
            "finance.rent_receipt.void",
            "void_receipt",
            {"receiptId": str(uuid4()), "confirmed": True, "voidReason": "Reversed"},
            lambda p: p["receiptId"],
            lambda p: asdict(VoidCommand(True, "Reversed")),
        ),
        (
            "finance.prepaid_check.create",
            "create_prepaid_check",
            {
                "expectationId": str(uuid4()),
                "payerPartyId": str(uuid4()),
                "receivedOn": "2026-10-01",
                "checkDatedOn": "2026-10-15",
            },
            lambda p: p["expectationId"],
            lambda p: asdict(
                PrepaidCheckCommand(
                    p["expectationId"],
                    p["payerPartyId"],
                    p["receivedOn"],
                    p["checkDatedOn"],
                    None,
                    KEY,
                )
            ),
        ),
        (
            "finance.prepaid_check.deposit",
            "deposit_prepaid_check",
            {"prepaidCheckId": str(uuid4()), "confirmed": True},
            lambda p: p["prepaidCheckId"],
            lambda p: asdict(PrepaidCheckTransitionCommand(KEY, True)),
        ),
        (
            "finance.prepaid_check.return",
            "return_prepaid_check",
            {
                "prepaidCheckId": str(uuid4()),
                "confirmed": True,
                "reason": "Returned",
                "returnedOn": "2026-10-02",
            },
            lambda p: p["prepaidCheckId"],
            lambda p: asdict(PrepaidCheckTransitionCommand(KEY, True, "Returned", "2026-10-02")),
        ),
        (
            "finance.prepaid_check.void",
            "void_prepaid_check",
            {"prepaidCheckId": str(uuid4()), "confirmed": True, "reason": "Wrong check"},
            lambda p: p["prepaidCheckId"],
            lambda p: asdict(PrepaidCheckTransitionCommand(KEY, True, "Wrong check")),
        ),
        (
            "finance.prepaid_check.replace",
            "replace_prepaid_check",
            {
                "prepaidCheckId": str(uuid4()),
                "expectationId": str(uuid4()),
                "payerPartyId": str(uuid4()),
                "receivedOn": "2026-10-01",
                "checkDatedOn": "2026-10-15",
                "confirmed": True,
                "reason": "Unreadable",
            },
            lambda p: p["prepaidCheckId"],
            lambda p: {
                **asdict(
                    PrepaidCheckCommand(
                        p["expectationId"],
                        p["payerPartyId"],
                        p["receivedOn"],
                        p["checkDatedOn"],
                        None,
                        KEY,
                    )
                ),
                "confirmed": True,
                "reason": "Unreadable",
            },
        ),
    ],
)
def test_form_fingerprint_matches_finance_command_identity(
    form_key, action, payload, target, expected_payload
):
    assert form_key in COMMAND_SCHEMAS
    payload = {"expectedRevision": REVISION, **payload}
    actual = finance_request(action, LEASE_ID, payload, KEY)
    assert actual == _expected(action, target(payload), expected_payload(payload))


def _receipt_request(payload):
    command = RecordReceiptCommand(
        LEASE_ID,
        KEY,
        payload["receivedOn"],
        payload["amountMinor"],
        payload["currencyCode"],
        tuple(
            ReceiptAllocationCommand(item["expectationId"], item["amountMinor"])
            for item in payload["allocations"]
        ),
        payload["paymentMethodKind"],
    )
    result = asdict(command)
    result["allocations"] = sorted(
        result["allocations"], key=lambda item: (item["expectation_id"], item["amount_minor"])
    )
    return result


def test_incomplete_finance_forms_are_rejected_before_attempt_creation():
    with pytest.raises(OperatorError):
        require_complete_form("finance.rent_expectation.synchronize", {})
    with pytest.raises(OperatorError):
        require_complete_form("finance.rent_receipt.create", {"allocations": []})
    with pytest.raises(OperatorError):
        require_complete_form(
            "finance.prepaid_check.replace",
            {"confirmed": True, "reason": "replacement"},
        )


@pytest.mark.parametrize("override", [False, True])
def test_synchronization_fingerprint_uses_source_command_defaults_and_normalization(override):
    term_id = str(uuid4())
    payload = {"expectedRevision": REVISION, "leaseTermId": term_id, "throughOn": "2026-10-31"}
    if override:
        payload.update(
            responsibilityEndsOnOverride="2026-10-25",
            overrideReason="  agreed boundary  ",
            overrideConfirmed=True,
        )
    command = SynchronizeExpectationsCommand(
        term_id,
        "2026-10-31",
        responsibility_ends_on_override=payload.get("responsibilityEndsOnOverride"),
        override_reason=payload.get("overrideReason"),
        override_confirmed=override,
    )
    assert finance_request("synchronize_expectations", LEASE_ID, payload, KEY) == _expected(
        "synchronize_expectations", LEASE_ID, asdict(command)
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"expectedRevision": True},
        {"leaseTermId": "invalid"},
        {"throughOn": "invalid"},
        {"overrideConfirmed": 1},
        {"unexpected": "field"},
    ],
)
def test_synchronization_schema_rejects_malformed_inputs(changes):
    with pytest.raises(OperatorError):
        validate_payload(
            "finance.rent_expectation.synchronize",
            1,
            {
                "expectedRevision": REVISION,
                "leaseTermId": str(uuid4()),
                "throughOn": "2026-10-31",
                **changes,
            },
        )


def test_unconfirmed_responsibility_override_cannot_prepare_synchronization():
    with pytest.raises(OperatorError):
        finance_request(
            "synchronize_expectations",
            LEASE_ID,
            {
                "expectedRevision": REVISION,
                "leaseTermId": str(uuid4()),
                "throughOn": "2026-10-31",
                "responsibilityEndsOnOverride": "2026-10-25",
            },
            KEY,
        )

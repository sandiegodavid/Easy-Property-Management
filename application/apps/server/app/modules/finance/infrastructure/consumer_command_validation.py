"""Source-owned proofs for prepaid, Expense and Deposit command receipts."""

from json import loads

from sqlalchemy import text


def validate_consumer_result(connection, receipt, response, events):
    scope = receipt["scope_kind"]
    if scope == "expense":
        _expense(receipt, response, events)
    elif scope == "deposit_account":
        _deposit(receipt, response, events)
    elif receipt["action"] in {"create_late_fee_policy", "void_late_fee_policy"}:
        _late_fee_policy(receipt, response, events)
    elif receipt["action"] in {"assess_late_fee", "waive_late_fee", "void_late_fee_assessment"}:
        _late_fee_assessment(receipt, response, events)
    elif receipt["action"] in {
        "record_late_fee_receipt",
        "record_combined_receipt",
        "void_late_fee_receipt",
    }:
        _late_fee_receipt(receipt, response, events)
    elif receipt["action"] == "apply_provider_payment_outcome":
        _provider_payment_outcome(receipt, response, events)
    else:
        _prepaid(connection, receipt, response, events)


def _primary(receipt, response, events, entity, action):
    matching = [
        event
        for event in events
        if event["entity_type"] == entity
        and event["action"] == action
        and event["entity_id"] == response["id"]
    ]
    if len(matching) != int(receipt["effective"]):
        raise ValueError("Financial command business audit is missing or duplicated.")
    if not matching:
        if events:
            raise ValueError("No-op command has business mutations.")
        return
    event = matching[0]
    if action == "deleted":
        if (
            event["after_snapshot"] is not None
            or loads(event["before_snapshot"])["id"] != response["id"]
        ):
            raise ValueError("Deleted child history is invalid.")
        return
    after = loads(event["after_snapshot"])
    if after["id"] != response["id"] or any(
        response[name] != value for name, value in after.items() if name in response
    ):
        raise ValueError("Financial result differs from its correlated after-state.")
    if "amountMinor" in after and "amount" in response:
        value = after["amountMinor"]
        if response["amount"] != f"{value // 100}.{value % 100:02d}":
            raise ValueError("Recorded amount differs from original result.")


def _expense(receipt, response, events):
    from app.modules.finance.api.expense_router import (
        ExpenseMutationResponse,
        RefundMutationResponse,
    )

    refund = receipt["action"] in {"record_refund", "void_refund"}
    (RefundMutationResponse if refund else ExpenseMutationResponse).model_validate(response)
    if (response["expenseId"] if refund else response["id"]) != receipt["scope_id"]:
        raise ValueError("Expense command scope differs from result.")
    action = {
        "record_expense": "recorded",
        "patch_expense": "updated",
        "void_expense": "voided",
        "record_refund": "recorded",
        "void_refund": "voided",
    }[receipt["action"]]
    _primary(receipt, response, events, "expense_refund" if refund else "expense", action)
    if len(events) != int(receipt["effective"]):
        raise ValueError("Expense command has unsupported correlated mutations.")


def _deposit(receipt, response, events):
    from app.modules.finance.api import deposit_router as api

    action = receipt["action"]
    kind = (
        "account"
        if action == "create_account"
        else "receipt"
        if action in {"record_receipt", "void_receipt"}
        else "refund"
        if action in {"record_refund", "void_refund"}
        else "deduction_source"
        if action in {"add_deduction_source", "delete_deduction_source"}
        else "deduction"
        if action in {"add_deduction", "update_deduction", "delete_deduction"}
        else "credit"
        if action in {"add_credit", "update_credit", "delete_credit"}
        else "settlement"
    )
    model = (
        api.DeletedMutationResponse
        if action.startswith("delete_")
        else {
            "account": api.DepositMutationResponse,
            "receipt": api.ReceiptMutationResponse,
            "refund": api.RefundMutationResponse,
            "deduction_source": api.DeductionSourceMutationResponse,
            "deduction": api.DeductionLineMutationResponse,
            "credit": api.CreditMutationResponse,
            "settlement": api.SettlementMutationResponse,
        }[kind]
    )
    model.model_validate(response)
    audit_action = (
        "draft_created"
        if action == "create_settlement"
        else "created"
        if action.startswith(("create_", "add_"))
        else "recorded"
        if action.startswith("record_")
        else "voided"
        if action.startswith("void_")
        else "deleted"
        if action.startswith("delete_")
        else "updated"
        if action.startswith(("update_", "patch_"))
        else "approved"
        if action == "approve_settlement"
        else "completed"
    )
    _primary(receipt, response, events, "security_deposit_" + kind, audit_action)
    primary = [event for event in events if event["entity_type"] == "security_deposit_" + kind]
    children = [event for event in events if event not in primary]
    if len(primary) != int(receipt["effective"]):
        raise ValueError("Deposit command has contradictory primary events.")
    allowed = {"approve_settlement": "snapshotted", "delete_deduction": "deleted"}.get(action)
    if any(
        event["entity_type"] != "security_deposit_deduction_source" or event["action"] != allowed
        for event in children
    ):
        raise ValueError("Deposit command has unsupported child events.")
    if kind == "account" and response["id"] != receipt["scope_id"]:
        raise ValueError("Deposit account scope differs.")
    if (
        kind in {"receipt", "refund", "settlement"}
        and not action.startswith("delete_")
        and response["accountId"] != receipt["scope_id"]
    ):
        raise ValueError("Deposit child belongs to a different account.")


def _prepaid(connection, receipt, response, events):
    from app.modules.finance.api.prepaid_check_router import PrepaidCheckMutationResponse

    PrepaidCheckMutationResponse.model_validate(response)
    action = receipt["action"].split("_", 1)[0]
    legacy = (
        connection.execute(
            text("SELECT * FROM prepaid_check_operations WHERE id=:id"), {"id": receipt["id"]}
        )
        .mappings()
        .first()
    )
    if (
        legacy is None
        or legacy["idempotency_key"] != receipt["idempotency_key"]
        or legacy["correlation_id"] != receipt["correlation_id"]
        or legacy["action"] != action
        or legacy["result_prepaid_check_id"] != response["id"]
        or legacy["created_at"] != receipt["created_at"]
        or response["leaseId"] != receipt["scope_id"]
    ):
        raise ValueError("Prepaid operation and shared-ledger command differ.")
    current = [event for event in events if event["entity_type"] == "prepaid_check"]
    expected = {
        (
            response["id"],
            {
                "create": "created",
                "deposit": "deposited",
                "return": "returned",
                "void": "voided",
                "replace": "created",
            }[action],
        )
    }
    if action == "replace":
        expected.add((receipt["target_id"], "replaced"))
    if {(event["entity_id"], event["action"]) for event in current} != expected or len(
        current
    ) != len(expected):
        raise ValueError("Prepaid command audit cardinality differs.")
    _primary(
        receipt,
        response,
        current,
        "prepaid_check",
        "created" if action == "replace" else next(iter(expected))[1],
    )
    payload = loads(receipt["request_json"])["payload"]
    money = [
        event
        for event in events
        if event["entity_type"] in {"rent_receipt", "rent_receipt_allocation"}
    ]
    expected_money = (
        2
        if action == "deposit" and payload["existing_receipt_id"] is None
        else 1
        if action == "return"
        else 0
    )
    if len(money) != expected_money or any(
        loads(event["after_snapshot"]).get("receiptId", event["entity_id"]) != response["receiptId"]
        for event in money
    ):
        raise ValueError("Prepaid receipt handoff history differs.")
    tasks = [event for event in events if event["entity_type"] == "task"]
    reminders = [event for event in events if event["entity_type"] == "task_reminder"]
    if action in {"create", "replace"}:
        if (
            len(tasks) != 1
            or len(reminders) != 1
            or tasks[0]["entity_id"] != response["reminderTaskId"]
        ):
            raise ValueError("Prepaid reminder creation history is incomplete.")
    elif any(
        event["entity_id"] != response["reminderTaskId"]
        or event["action"] not in {"status_changed", "task_waiting_cleared"}
        or (
            event["action"] == "status_changed"
            and loads(event["after_snapshot"]).get("status") != "cancelled"
        )
        for event in tasks
    ) or any(event["action"] != "dismissed" for event in reminders):
        raise ValueError("Prepaid reminder lifecycle history is invalid.")


def _late_fee_policy(receipt, response, events):
    from app.modules.finance.api.late_fee_router import LateFeePolicyMutationResponse

    LateFeePolicyMutationResponse.model_validate(response)
    if response["leaseId"] != receipt["scope_id"] or not receipt["effective"]:
        raise ValueError("Late-fee policy command must belong to its Lease and be effective.")
    action = receipt["action"]
    if action == "create_late_fee_policy":
        expected = {(response["id"], "created")}
        if response.get("supersedesPolicyVersionId") is not None:
            expected.add((response["supersedesPolicyVersionId"], "superseded"))
        primary_action = "created"
    else:
        if (
            response["id"] != receipt["target_id"]
            or response["voidedAt"] != receipt["created_at"]
            or response["status"] != "voided"
        ):
            raise ValueError("Late-fee policy void result differs from the committed command.")
        expected = {(response["id"], "voided")}
        primary_action = "voided"
    if any(event["entity_type"] != "late_fee_policy_version" for event in events):
        raise ValueError("Late-fee policy command has unsupported correlated mutations.")
    if {(event["entity_id"], event["action"]) for event in events} != expected or len(
        events
    ) != len(expected):
        raise ValueError("Late-fee policy command audit cardinality differs.")
    _primary(receipt, response, events, "late_fee_policy_version", primary_action)


def _late_fee_assessment(receipt, response, events):
    from app.modules.finance.api.late_fee_router import LateFeeAssessmentMutationResponse

    LateFeeAssessmentMutationResponse.model_validate(response)
    if response["leaseId"] != receipt["scope_id"] or not receipt["effective"]:
        raise ValueError("Late-fee assessment command must belong to its Lease and be effective.")
    action = receipt["action"]
    if action == "assess_late_fee":
        if (
            response["rentExpectationId"] != receipt["target_id"]
            or response["voidedAt"] is not None
        ):
            raise ValueError("Late-fee assessment creation result is invalid.")
        expected = {(response["id"], "assessed")}
        if (
            any(event["entity_type"] != "late_fee_assessment" for event in events)
            or {(event["entity_id"], event["action"]) for event in events} != expected
        ):
            raise ValueError("Late-fee assessment creation audit differs.")
        _primary(receipt, response, events, "late_fee_assessment", "assessed")
    elif action == "void_late_fee_assessment":
        if response["id"] != receipt["target_id"] or response["voidedAt"] != receipt["created_at"]:
            raise ValueError("Late-fee assessment void result differs from committed command.")
        expected = {(response["id"], "voided")}
        if (
            any(event["entity_type"] != "late_fee_assessment" for event in events)
            or {(event["entity_id"], event["action"]) for event in events} != expected
        ):
            raise ValueError("Late-fee assessment void audit differs.")
        _primary(receipt, response, events, "late_fee_assessment", "voided")
    else:  # waive_late_fee
        if response["id"] != receipt["target_id"]:
            raise ValueError("Late-fee waiver target differs from committed command.")
        if (
            len(events) != 1
            or events[0]["entity_type"] != "late_fee_waiver"
            or events[0]["action"] != "recorded"
        ):
            raise ValueError("Late-fee waiver audit cardinality differs.")
        after = loads(events[0]["after_snapshot"])
        if (
            after.get("assessmentId") != receipt["target_id"]
            or after.get("waivedAt") != receipt["created_at"]
        ):
            raise ValueError("Late-fee waiver audit differs from committed command.")


def _late_fee_receipt(receipt, response, events):
    from app.modules.finance.api.late_fee_router import (
        CombinedReceiptMutationResponse,
        LateFeeReceiptMutationResponse,
    )

    action = receipt["action"]
    if action == "record_combined_receipt":
        CombinedReceiptMutationResponse.model_validate(response)
        if response["leaseId"] != receipt["scope_id"] or not receipt["effective"]:
            raise ValueError("Combined receipt command must belong to its Lease and be effective.")
        rent_view = response["rentReceipt"]
        fee_view = response["lateFeeReceipt"]
        expected = (
            {("rent_receipt", rent_view["id"], "recorded")}
            | {
                ("rent_receipt_allocation", item["id"], "created")
                for item in rent_view["allocations"]
            }
            | {("late_fee_receipt", fee_view["id"], "recorded")}
            | {
                ("late_fee_receipt_allocation", item["id"], "created")
                for item in fee_view["allocations"]
            }
        )
        actual = {(event["entity_type"], event["entity_id"], event["action"]) for event in events}
        if actual != expected or len(events) != len(expected):
            raise ValueError("Combined receipt audit cardinality differs.")
        return

    LateFeeReceiptMutationResponse.model_validate(response)
    if response["leaseId"] != receipt["scope_id"] or not receipt["effective"]:
        raise ValueError("Late-fee receipt command must belong to its Lease and be effective.")
    if action == "record_late_fee_receipt":
        if (
            response["idempotencyKey"] != receipt["idempotency_key"]
            or response["voidedAt"] is not None
        ):
            raise ValueError("Late-fee receipt creation result is invalid.")
        expected = {("late_fee_receipt", response["id"], "recorded")} | {
            ("late_fee_receipt_allocation", item["id"], "created")
            for item in response["allocations"]
        }
    else:  # void_late_fee_receipt
        if response["id"] != receipt["target_id"] or response["voidedAt"] != receipt["created_at"]:
            raise ValueError("Late-fee receipt void result differs from committed command.")
        expected = {("late_fee_receipt", response["id"], "voided")}
    actual = {(event["entity_type"], event["entity_id"], event["action"]) for event in events}
    if actual != expected or len(events) != len(expected):
        raise ValueError("Late-fee receipt audit cardinality differs.")


def _provider_payment_outcome(receipt, response, events):
    if response.get("leaseId") != receipt["scope_id"]:
        raise ValueError("Provider payment outcome must belong to its Lease.")
    if response.get("paymentAttemptId") != receipt["target_id"]:
        raise ValueError("Provider payment outcome target differs from committed command.")
    if not receipt["effective"]:
        if events:
            raise ValueError("No-op provider payment outcome has business mutations.")
        return
    if not events:
        raise ValueError("Effective provider payment outcome is missing audit events.")

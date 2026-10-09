"""Explicit Slice 31C–E composition of source-owned financial commands."""

from dataclasses import asdict, fields, MISSING
from datetime import datetime
import re

from app.modules.finance.application.category_commands import ExpenseCategoryCommand
from app.modules.finance.application.commands import (
    FinanceCommandIdentity,
    FinanceScope,
    canonical_json,
    fingerprint,
)
from app.modules.finance.domain.expense_models import (
    CategoryCreateCommand,
    CategoryPatchCommand,
    ExpenseCreateCommand,
    ExpensePatchCommand,
    RefundCreateCommand,
)
from app.modules.finance.domain.deposit_models import (
    CreditCommand,
    DeductionCommand,
    DepositAccountCreateCommand,
    DepositReceiptCommand,
    DepositRefundCommand,
    SettlementCreateCommand,
)
from app.modules.finance.domain.models import FinanceError, ReceiptAllocationCommand, VoidCommand
from app.modules.owner_accounting.domain.models import (
    OwnerRentReportCommand,
    RejectOwnerRentReportCommand,
    VerifyOwnerRentReportCommand,
    OwnerReportError,
)
from app.modules.operator.application.ports import RecoveryBinding
from app.modules.operator.domain.models import OperatorError


EXPENSE_ACTIONS = {
    "finance.expense.create": "record_expense",
    "finance.expense.patch": "patch_expense",
    "finance.expense.void": "void_expense",
    "finance.expense_refund.create": "record_refund",
    "finance.expense_refund.void": "void_refund",
}
DEPOSIT_ACTIONS = {
    "finance.deposit_account.create": "create_account",
    "finance.deposit_receipt.create": "record_receipt",
    "finance.deposit_receipt.void": "void_receipt",
    "finance.deposit_settlement.create": "create_settlement",
    "finance.deposit_settlement.patch": "patch_settlement",
    "finance.deposit_settlement.approve": "approve_settlement",
    "finance.deposit_settlement.complete": "complete_settlement",
    "finance.deposit_settlement.void": "void_settlement",
    **{
        f"finance.deposit_{kind}.{verb}": f"{action}_{kind}"
        for kind in ("deduction", "credit")
        for verb, action in (("create", "add"), ("update", "update"), ("delete", "delete"))
    },
    "finance.deposit_deduction_source.add": "add_deduction_source",
    "finance.deposit_deduction_source.delete": "delete_deduction_source",
    "finance.deposit_refund.create": "record_refund",
    "finance.deposit_refund.void": "void_refund",
}


def values(payload):
    result = {re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower(): v for k, v in payload.items()}
    if result.get("reported_at_utc") is not None:
        result["reported_at_utc"] = datetime.fromisoformat(result["reported_at_utc"]).isoformat()
    return result


def construct(model, supplied):
    arguments = {}
    for field in fields(model):
        if field.name in supplied:
            arguments[field.name] = supplied[field.name]
        elif field.default is MISSING and field.default_factory is MISSING:
            raise OperatorError("Complete the financial command fields.")
    return model(**arguments)


def expense_payload(action, payload, key):
    supplied = values(payload)
    models = {
        "record_expense": ExpenseCreateCommand,
        "record_refund": RefundCreateCommand,
    }
    if action in models:
        return asdict(construct(models[action], {**supplied, "idempotency_key": key}))
    if action == "patch_expense":
        changes = values(payload.get("changes") or {})
        result = asdict(
            construct(
                ExpensePatchCommand,
                {**changes, "fields": frozenset(changes) & {"category_id", "notes"}},
            )
        )
        result["fields"] = sorted(result["fields"])
        return result
    return asdict(VoidCommand(payload.get("confirmed"), payload.get("reason")))


def expense_request(action, source, payload, key):
    scope = key if action == "record_expense" else source
    target = payload.get("targetId") if action == "void_refund" else scope
    return fingerprint(
        FinanceCommandIdentity(
            FinanceScope("expense", scope),
            action,
            target,
            payload["expectedRevision"],
            key,
            expense_payload(action, payload, key),
        ).request_json
    )


def category_request(action, source, payload, key):
    if action == "create":
        supplied = values(payload)
        command = construct(CategoryCreateCommand, supplied)
        request = asdict(command)
    elif action == "patch":
        supplied = values(payload.get("changes") or {})
        command = construct(CategoryPatchCommand, {**supplied, "fields": frozenset(supplied)})
        request = {field: getattr(command, field) for field in command.fields}
    else:
        request = asdict(VoidCommand(payload.get("confirmed"), payload.get("reason")))
    return fingerprint(
        canonical_json(
            ExpenseCategoryCommand(
                action,
                source,
                payload["expectedRevision"],
                key,
                request,
            ).request()
        )
    )


DEPOSIT_MODELS = {
    "create_account": DepositAccountCreateCommand,
    "record_receipt": DepositReceiptCommand,
    "create_settlement": SettlementCreateCommand,
    "add_deduction": DeductionCommand,
    "update_deduction": DeductionCommand,
    "add_credit": CreditCommand,
    "update_credit": CreditCommand,
    "record_refund": DepositRefundCommand,
}


def deposit_payload(action, payload, key):
    supplied = values(payload)
    if action in DEPOSIT_MODELS:
        return asdict(construct(DEPOSIT_MODELS[action], {**supplied, "idempotency_key": key}))
    return deposit_scalar_payload(action, supplied)


def deposit_scalar_payload(action, supplied):
    if action.startswith("delete_"):
        return {}
    if action.startswith("void_"):
        return asdict(VoidCommand(supplied.get("confirmed"), supplied.get("reason")))
    if action == "patch_settlement":
        changes = values(supplied.get("changes") or {})
        allowed = {
            "settlement_due_on",
            "legal_rule_reference",
            "review_notes",
            "deadline_override_confirmed",
            "deadline_override_reason",
        }
        if not changes or not set(changes) <= allowed:
            raise OperatorError("Select valid settlement fields.")
        return {"fields": sorted(changes), **{field: changes.get(field) for field in allowed}}
    if action == "add_deduction_source":
        if supplied.get("source_kind") is None or supplied.get("source_id") is None:
            raise OperatorError("Select a deduction source.")
        return {
            field: supplied.get(field, default)
            for field, default in (
                ("source_kind", None),
                ("source_id", None),
                ("historical_confirmed", False),
                ("historical_reason", None),
                ("duplicate_use_confirmed", False),
            )
        }
    if action == "approve_settlement":
        if supplied.get("confirmed") is not True:
            raise OperatorError("Confirm settlement approval.")
        return {
            "confirmed": True,
            "zero_dollar_closure_confirmed": supplied.get("zero_dollar_closure_confirmed", False),
        }
    if type(supplied.get("zero_refund_confirmed")) is not bool:
        raise OperatorError("Complete the settlement closure confirmation.")
    return {"zero_refund_confirmed": supplied["zero_refund_confirmed"]}


def deposit_request(action, source, payload, key):
    scope = key if action == "create_account" else source
    if action == "create_account":
        target = payload["leaseId"]
    elif action in {"record_receipt", "create_settlement"}:
        target = source
    else:
        target = payload.get("targetId")
        if target is None:
            raise OperatorError("Select the deposit command target.")
    return fingerprint(
        FinanceCommandIdentity(
            FinanceScope("deposit_account", scope),
            action,
            target,
            payload["expectedRevision"],
            key,
            deposit_payload(action, payload, key),
        ).request_json
    )


def owner_request(action, source, payload, key):
    if action == "create":
        request = asdict(
            construct(OwnerRentReportCommand, {**values(payload), "idempotency_key": key})
        )
    elif action == "patch":
        request = {"values": values(payload.get("changes") or {})}
    elif action == "reject":
        request = asdict(
            RejectOwnerRentReportCommand(payload.get("confirmed"), payload.get("reason"))
        )
    else:
        supplied = values(payload)
        supplied["allocations"] = tuple(
            construct(ReceiptAllocationCommand, values(item))
            for item in payload.get("allocations", ())
        )
        command = construct(VerifyOwnerRentReportCommand, supplied)
        if command.existing_receipt_id is None and not command.allocations:
            raise OperatorError("Complete receipt allocations.")
        if type(payload.get("expectedLedgerRevision")) is not int:
            raise OperatorError("Complete the expected rent-ledger revision.")
        request = asdict(command) | {"expected_ledger_revision": payload["expectedLedgerRevision"]}
    return fingerprint(
        canonical_json(
            {
                "action": action,
                "reportId": source,
                "expectedRevision": payload["expectedRevision"],
                "payload": request,
            }
        )
    )


def bind_batch(reader, family, actions, request):
    source_kind = {
        "expense": "expense",
        "deposit": "security_deposit_account",
        "expense_category": "expense_category",
        "owner_rent_report": "owner_rent_report",
    }[family]
    return {
        form: RecoveryBinding(
            None
            if form.endswith(".create") and action in {"record_expense", "create_account", "create"}
            else source_kind,
            action,
            family,
            reader,
            lambda source, payload, key, action=action: financial_fingerprint(
                request, action, source, payload, key
            ),
            source_kind,
        )
        for form, action in actions.items()
    }


def financial_fingerprint(request, action, source, payload, key):
    if (
        action in {"record_expense", "create_account", "create"}
        and payload.get("expectedRevision") != 0
    ):
        raise OperatorError("Financial creation requires revision zero.")
    try:
        return request(action, source, payload, key)
    except (FinanceError, OwnerReportError) as error:
        raise OperatorError("Complete a valid owning financial command.") from error


def compose_financial_batches(expenses, deposits, categories, reports):
    return {
        **bind_batch(expenses, "expense", EXPENSE_ACTIONS, expense_request),
        **bind_batch(
            deposits,
            "deposit",
            DEPOSIT_ACTIONS,
            deposit_request,
        ),
        **bind_batch(
            categories,
            "expense_category",
            {
                f"finance.expense_category.{action}": action
                for action in ("create", "patch", "archive", "restore")
            },
            category_request,
        ),
        **bind_batch(
            reports,
            "owner_rent_report",
            {
                f"owner_rent_report.{action}": action
                for action in ("create", "patch", "verify", "reject")
            },
            owner_request,
        ),
    }

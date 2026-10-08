"""Explicit command metadata for older financial business-rule fixtures.

Contract tests call the real service methods directly. This helper does not
replace or monkeypatch any service method or hide concurrency in test setup.
"""

from uuid import uuid4

from app.modules.finance.application.commands import FinanceScope


def expense_command(service, action, *args, **kwargs):
    """Explicit concurrency metadata at expense business-rule call sites."""
    creation = action in {"record_expense", "record_refund"}
    key = args[-1].idempotency_key if creation else kwargs.pop("idempotency_key", str(uuid4()))

    def read(tx):
        prior = tx.commands.command_operation(key)
        if prior is not None:
            return prior["expected_revision"]
        if action == "record_expense":
            return 0
        expense_id = tx.refund(args[0]).expense_id if action == "void_refund" else args[0]
        return tx.commands.command_revision(FinanceScope("expense", expense_id))

    kwargs.setdefault("expected_revision", service.unit_of_work.read(read))
    if not creation:
        kwargs["idempotency_key"] = key
    return getattr(service, action)(*args, **kwargs)


def prepaid_command(service, action, *args, **kwargs):
    """Use the real public signature with the selected ledger revision."""
    command = args[-1]

    def read(tx):
        prior = tx.commands.command_operation(command.idempotency_key)
        if prior is not None:
            return prior["expected_revision"]
        lease_id = (
            tx.expectation(command.expectation_id).lease_id
            if action == "create"
            else tx.prepaid_check(args[0]).lease_id
        )
        return tx.commands.command_revision(FinanceScope("rent_ledger", lease_id))

    kwargs.setdefault("expected_revision", service.unit_of_work.read(read))
    return getattr(service, action)(*args, **kwargs)


def deposit_command(service, action, *args, **kwargs):
    """Select account concurrency explicitly at deposit business-rule call sites."""
    keyed = action in {"record_receipt", "record_refund"}
    key = args[-1].idempotency_key if keyed else kwargs.pop("idempotency_key", str(uuid4()))

    def read(tx):
        prior = tx.commands.command_operation(key)
        if prior is not None:
            return prior["expected_revision"]
        if action == "create_account":
            return 0
        kind = (
            "account"
            if action in {"record_receipt", "create_settlement"}
            else "receipt"
            if action == "void_receipt"
            else "refund"
            if action == "void_refund"
            else "deduction_source"
            if action == "delete_deduction_source"
            else "deduction"
            if action in {"update_deduction", "delete_deduction", "add_deduction_source"}
            else "credit"
            if action in {"update_credit", "delete_credit"}
            else "settlement"
        )
        return tx.commands.command_revision(
            FinanceScope("deposit_account", service._scope_id(tx, kind, args[0]))
        )

    kwargs.setdefault("expected_revision", service.unit_of_work.read(read))
    if not keyed:
        kwargs["idempotency_key"] = key
    result = getattr(service, action)(*args, **kwargs)
    return {
        key: value
        for key, value in result.items()
        if key != "operationId" and (key != "depositAccountRevision" or action == "create_account")
    }


def rent_command(service, action, *args, **kwargs):
    key = kwargs.pop("idempotency_key", None)
    if action == "record_receipt":
        key = args[0].idempotency_key
        lease_id = args[0].lease_id
    elif action == "synchronize":
        lease_id = args[0]
    else:
        kind = "receipt" if action == "void_receipt" else "expectation"
        lease_id = service.unit_of_work.read(lambda tx: getattr(tx, kind)(args[0]).lease_id)
    key = key or str(uuid4())
    prior = service.unit_of_work.read(lambda tx: tx.commands.command_operation(key))
    revision = (
        prior["expected_revision"]
        if prior is not None
        else service.rent_ledger_revision(lease_id)["rentLedgerRevision"]
    )
    kwargs.setdefault("expected_revision", revision)
    if action != "record_receipt":
        kwargs["idempotency_key"] = key
    result = getattr(service, action)(*args, **kwargs)
    if action == "synchronize":
        return result["items"]
    return {
        key: value
        for key, value in result.items()
        if key not in {"rentLedgerRevision", "operationId"}
    }

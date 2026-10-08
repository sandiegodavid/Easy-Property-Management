"""Neutral transaction-scoped access to the FIN-001 receipt policy."""

from sqlalchemy import select

from app.modules.finance.application.ports import RecordedReceipt
from app.modules.finance.application.commands import (
    FinanceCommandIdentity,
    FinanceCommandOutcome,
    FinanceScope,
    apply_finance_command,
    validate_command_concurrency,
)
from app.modules.finance.application.receipt_handoff import record_receipt_in_transaction
from app.modules.finance.application.service import (
    _command_payload,
    _receipt_payload,
    _receipt_command_request,
)
from app.modules.finance.domain.models import FinanceConflictError, RentReceipt
from app.modules.finance.infrastructure.command_operations import SQLiteFinanceCommandTransaction
from app.modules.finance.infrastructure.sqlalchemy_models import RentReceiptModel
from app.modules.finance.infrastructure.unit_of_work import _Tx


class SQLiteReceiptTransactionOperations:
    def __init__(self, recorder, lease_operations, portfolio_operations, party_operations):
        self.recorder = recorder
        self.lease_operations = lease_operations
        self.portfolio_operations = portfolio_operations
        self.party_operations = party_operations

    def transaction(self, connection):
        return _Tx(
            connection,
            self.recorder,
            self.lease_operations,
            self.portfolio_operations,
            self.party_operations,
            None,
        )

    def command_transaction(self, connection):
        return SQLiteFinanceCommandTransaction(connection, self.recorder)

    def record_receipt(
        self,
        connection,
        command,
        *,
        expected_revision,
        now,
        correlation_id,
        audit_reason,
        duplicate_conflict=None,
    ):
        tx = self.transaction(connection)
        validate_command_concurrency(expected_revision, command.idempotency_key)
        prior = tx.receipt_by_key(command.idempotency_key)
        if prior is not None:
            if _receipt_payload(prior, tx.receipt_allocations(prior.id)) != _command_payload(
                command
            ):
                raise FinanceConflictError(
                    "Idempotency key was already used for a different receipt."
                )
            return RecordedReceipt(prior, created=False)
        instant = now()
        receipt = None

        def mutation(context):
            nonlocal receipt
            receipt = record_receipt_in_transaction(
                tx,
                command,
                now=lambda: instant,
                correlation_id=context.correlation_id,
                audit_reason=audit_reason,
                duplicate_conflict=duplicate_conflict,
            )
            return FinanceCommandOutcome(
                {
                    **receipt.to_dict(),
                    "allocations": tx.receipt_projection([receipt.id])[receipt.id],
                },
                True,
            )

        apply_finance_command(
            tx.commands,
            FinanceCommandIdentity(
                FinanceScope("rent_ledger", command.lease_id),
                "record_receipt",
                command.lease_id,
                expected_revision,
                command.idempotency_key,
                _receipt_command_request(command),
            ),
            mutation,
            instant=instant,
            correlation_id=correlation_id,
        )
        if receipt is None:
            raise FinanceConflictError(
                "Receipt creation key was already used; select the receipt explicitly."
            )
        return RecordedReceipt(receipt, created=True)

    def receipt_contexts(self, connection, receipt_ids):
        ids = list(dict.fromkeys(receipt_ids))
        if not ids:
            return {}
        return {
            row["id"]: RentReceipt(**dict(row))
            for row in connection.execute(
                select(RentReceiptModel.__table__).where(RentReceiptModel.id.in_(ids))
            ).mappings()
        }

    def receipt_lifecycle_predicate(self, lifecycle, receipt_id):
        condition = (
            RentReceiptModel.voided_at.is_(None)
            if lifecycle == "active"
            else RentReceiptModel.voided_at.is_not(None)
        )
        return (
            select(RentReceiptModel.id)
            .where(
                RentReceiptModel.id == receipt_id,
                condition,
            )
            .exists()
        )

    def replacement_receipt(self, connection, receipt_id):
        row = (
            connection.execute(
                select(RentReceiptModel.__table__).where(
                    RentReceiptModel.replaces_receipt_id == receipt_id,
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else RentReceipt(**dict(row))

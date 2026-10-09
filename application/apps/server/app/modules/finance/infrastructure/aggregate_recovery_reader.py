"""Source-owned, transaction-bound recovery for Expense and Deposit aggregates."""

from json import loads

from sqlalchemy import select

from app.modules.finance.application.commands import recovery_request_fingerprint
from app.modules.finance.infrastructure.command_models import (
    FinanceCommandOperationModel,
    FinanceCommandRevisionModel,
)
from app.modules.finance.infrastructure.sqlalchemy_models import (
    ExpenseCategoryModel,
    ExpenseCategoryCommandOperationModel,
    ExpenseModel,
    ExpenseRefundModel,
    SecurityDepositAccountModel,
    SecurityDepositReceiptModel,
    SecurityDepositSettlementModel,
    SecurityDepositDeductionModel,
    SecurityDepositCreditModel,
    SecurityDepositDeductionSourceModel,
    SecurityDepositRefundModel,
)
from app.platform.command_recovery import CommandOutcome, CommandResult


class SQLiteFinancialAggregateRecoveryReader:
    def __init__(self, family, lease_reader):
        if family not in {"expense", "deposit"}:
            raise ValueError("Unsupported financial aggregate.")
        self.family, self.lease_reader = family, lease_reader
        self.scope_kind = "expense" if family == "expense" else "deposit_account"

    def state(self, connection, source_id):
        model = ExpenseModel if self.family == "expense" else SecurityDepositAccountModel
        columns = [model.id]
        if self.family == "expense":
            columns.append(model.voided_at)
        row = connection.execute(select(*columns).where(model.id == source_id)).mappings().first()
        if row is None:
            return None
        revision = connection.scalar(
            select(FinanceCommandRevisionModel.revision).where(
                FinanceCommandRevisionModel.scope_kind == self.scope_kind,
                FinanceCommandRevisionModel.scope_id == source_id,
            )
        )
        return {"revision": revision or 0, "status": "voided" if row.get("voided_at") else "active"}

    def outcome(self, connection, key, *, family):
        if family != self.family:
            raise ValueError("Unsupported financial recovery family.")
        row = (
            connection.execute(
                select(FinanceCommandOperationModel.__table__).where(
                    FinanceCommandOperationModel.idempotency_key == key,
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        result = loads(row["response_json"])
        return CommandOutcome(
            row["id"],
            row["action"],
            row["scope_id"],
            recovery_request_fingerprint(row["request_json"], key),
            CommandResult(
                result.get("id") or row["target_id"],
                row["result_revision"],
                result.get("status") or result.get("lifecycleStatus"),
            ),
        )

    def creation_state(self, connection, payload):
        if self.family == "expense":
            return expense_category_selection(connection, payload)
        if payload.get("leaseId") is None:
            return "available"  # Incomplete autosave; preparation requires both IDs.
        lease = self.lease_reader.state(connection, payload.get("leaseId"))
        term = self.lease_reader.term_state(connection, payload.get("leaseTermId"))
        if lease is None or lease["status"] not in {"executed", "ended", "terminated"}:
            return "source_unavailable"
        if payload.get("leaseTermId") is not None and (
            term is None or term["source_id"] != payload.get("leaseId")
        ):
            return "source_unavailable"
        return "available"

    def related_state(self, connection, kind, target):
        if self.family == "expense":
            row = (
                connection.execute(
                    select(ExpenseRefundModel.expense_id, ExpenseRefundModel.voided_at).where(
                        ExpenseRefundModel.id == target
                    )
                )
                .mappings()
                .first()
            )
            return (
                None
                if row is None
                else {
                    "source_id": row["expense_id"],
                    "status": "voided" if row["voided_at"] else "active",
                }
            )
        return deposit_related_state(connection, kind, target)


DEPOSIT_MODELS = {
    "receipt": SecurityDepositReceiptModel,
    "settlement": SecurityDepositSettlementModel,
    "deduction": SecurityDepositDeductionModel,
    "credit": SecurityDepositCreditModel,
    "deduction_source": SecurityDepositDeductionSourceModel,
    "refund": SecurityDepositRefundModel,
}


def expense_category_selection(connection, payload):
    if payload.get("categoryId") is None:
        return "available"
    row = connection.execute(
        select(ExpenseCategoryModel.archived_at).where(
            ExpenseCategoryModel.id == payload["categoryId"]
        )
    ).first()
    if row is None:
        return "source_unavailable"
    historical = payload.get("historicalEntryConfirmed") is True and bool(
        (payload.get("historicalEntryReason") or "").strip()
    )
    return "available" if row.archived_at is None or historical else "source_unavailable"


def deposit_related_state(connection, kind, target):
    model = DEPOSIT_MODELS[kind]
    statement = select(model.__table__)
    if kind == "deduction_source":
        statement = (
            statement.add_columns(
                SecurityDepositSettlementModel.account_id,
                SecurityDepositSettlementModel.status.label("settlement_status"),
            )
            .join(
                SecurityDepositDeductionModel,
                model.deduction_id == SecurityDepositDeductionModel.id,
            )
            .join(
                SecurityDepositSettlementModel,
                SecurityDepositDeductionModel.settlement_id == SecurityDepositSettlementModel.id,
            )
        )
    elif kind in {"deduction", "credit"}:
        statement = statement.add_columns(
            SecurityDepositSettlementModel.account_id,
            SecurityDepositSettlementModel.status.label("settlement_status"),
        ).join(
            SecurityDepositSettlementModel, model.settlement_id == SecurityDepositSettlementModel.id
        )
    row = connection.execute(statement.where(model.id == target)).mappings().first()
    if row is None:
        return None
    return {
        "source_id": row["account_id"],
        "status": row.get("status") or ("voided" if row.get("voided_at") else "active"),
        "settlement_status": row.get("settlement_status"),
    }


class SQLiteExpenseCategoryRecoveryReader:
    def state(self, connection, source_id):
        row = (
            connection.execute(
                select(ExpenseCategoryModel.revision, ExpenseCategoryModel.archived_at).where(
                    ExpenseCategoryModel.id == source_id
                )
            )
            .mappings()
            .first()
        )
        return (
            None
            if row is None
            else {
                "revision": row["revision"],
                "status": "archived" if row["archived_at"] else "active",
            }
        )

    def outcome(self, connection, key, *, family):
        if family != "expense_category":
            raise ValueError("Unsupported category recovery family.")
        row = (
            connection.execute(
                select(ExpenseCategoryCommandOperationModel.__table__).where(
                    ExpenseCategoryCommandOperationModel.idempotency_key == key
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        result = loads(row["result_json"])
        return CommandOutcome(
            row["id"],
            row["action"],
            row["category_id"],
            row["request_fingerprint"],
            CommandResult(
                row["category_id"],
                row["resulting_revision"],
                "archived" if result["archivedAt"] else "active",
            ),
        )

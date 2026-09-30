"""Finance-owned transaction facts used by FILE-001 evidence policies."""
from __future__ import annotations

from sqlalchemy import select

from app.modules.finance.infrastructure.sqlalchemy_models import (
    ExpenseModel,
    SecurityDepositDeductionModel,
    SecurityDepositReceiptModel,
    SecurityDepositRefundModel,
    SecurityDepositSettlementModel,
)


class SQLiteExpenseFileLinkFacts:
    def expense_exists(self, connection, entity_id: str) -> bool:
        return connection.execute(select(ExpenseModel.id).where(ExpenseModel.id == entity_id).limit(1)).first() is not None
class SQLiteDepositFileLinkFacts:
    _models = {
        "security_deposit_receipt": SecurityDepositReceiptModel,
        "security_deposit_deduction": SecurityDepositDeductionModel,
        "security_deposit_refund": SecurityDepositRefundModel,
        "security_deposit_settlement": SecurityDepositSettlementModel,
    }
    def exists(self, connection, entity_type: str, entity_id: str) -> bool:
        model = self._models.get(entity_type)
        return model is not None and connection.execute(select(model.id).where(model.id == entity_id).limit(1)).first() is not None

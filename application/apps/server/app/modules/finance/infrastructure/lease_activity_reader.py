"""Transaction-aware Finance activity reader for lease void guards."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.modules.finance.infrastructure.sqlalchemy_models import (
    RentReceiptModel,
    SecurityDepositAccountModel,
    SecurityDepositReceiptModel,
)


class SQLiteLeaseFinanceActivityReader:
    """Reports whether a lease has active (non-voided) rent or deposit receipts."""

    def has_active_financial_activity(self, connection: Any, lease_id: str) -> bool:
        rent_row = connection.execute(
            select(RentReceiptModel.id)
            .where(
                RentReceiptModel.lease_id == lease_id,
                RentReceiptModel.voided_at.is_(None),
            )
            .limit(1)
        ).first()
        if rent_row is not None:
            return True
        deposit_row = connection.execute(
            select(SecurityDepositReceiptModel.id)
            .join(
                SecurityDepositAccountModel,
                SecurityDepositReceiptModel.account_id == SecurityDepositAccountModel.id,
            )
            .where(
                SecurityDepositAccountModel.lease_id == lease_id,
                SecurityDepositReceiptModel.voided_at.is_(None),
            )
            .limit(1)
        ).first()
        return deposit_row is not None

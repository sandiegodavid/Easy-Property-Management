"""Consumer-neutral FIN-002 expense projections for caller-owned transactions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.modules.finance.infrastructure.sqlalchemy_models import ExpenseModel, ExpenseRefundModel


class SQLiteExpenseContextReader:
    def expense_context(self, connection: Any, expense_id: str) -> dict[str, object] | None:
        row = connection.execute(
            ExpenseModel.__table__.select().where(ExpenseModel.id == expense_id)
        ).mappings().first()
        if row is None:
            return None
        refunds = connection.execute(select(func.coalesce(func.sum(ExpenseRefundModel.amount_minor), 0)).where(
            ExpenseRefundModel.expense_id == expense_id,
            ExpenseRefundModel.voided_at.is_(None),
        )).scalar_one()
        return _context(row, int(refunds))

    def expense_contexts(self, connection: Any, expense_ids: list[str]) -> dict[str, dict[str, object]]:
        if not expense_ids:
            return {}
        identifiers = set(expense_ids)
        refund_totals = {
            row["expense_id"]: int(row["refund_total"])
            for row in connection.execute(
                select(ExpenseRefundModel.expense_id, func.coalesce(func.sum(ExpenseRefundModel.amount_minor), 0).label("refund_total"))
                .where(ExpenseRefundModel.expense_id.in_(identifiers), ExpenseRefundModel.voided_at.is_(None))
                .group_by(ExpenseRefundModel.expense_id)
            ).mappings()
        }
        return {
            row["id"]: _context(row, refund_totals.get(row["id"], 0))
            for row in connection.execute(
                ExpenseModel.__table__.select().where(ExpenseModel.id.in_(identifiers))
            ).mappings()
        }


def _context(row: Any, active_refund_minor: int) -> dict[str, object]:
    return {
        "id": row["id"],
        "property_id": row["property_id"],
        "space_id": row["space_id"],
        "voided_at": row["voided_at"],
        "lifecycle_status": "voided" if row["voided_at"] else "active",
        "net_amount_minor": int(row["amount_minor"]) - active_refund_minor,
        "currency_code": row["currency_code"],
        "occurred_on": row["paid_on"],
        "payee_snapshot": row["payee_name"],
    }

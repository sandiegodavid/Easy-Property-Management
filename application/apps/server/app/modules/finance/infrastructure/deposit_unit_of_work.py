"""SQLite FIN-008 transaction adapter."""
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.modules.finance.domain.models import FinanceConflictError
from app.modules.finance.infrastructure.sqlalchemy_models import (
    SecurityDepositAccountModel, SecurityDepositReceiptModel, SecurityDepositSettlementModel,
    SecurityDepositSettlementReceiptModel, SecurityDepositDeductionModel,
    SecurityDepositDeductionSourceModel, SecurityDepositCreditModel, SecurityDepositRefundModel,
)
from app.modules.finance.infrastructure.sqlalchemy_models import ExpenseModel, RentExpectationModel, RentReceiptAllocationModel, RentReceiptModel
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

_MODELS = {"account": SecurityDepositAccountModel, "receipt": SecurityDepositReceiptModel,
           "settlement": SecurityDepositSettlementModel, "deduction": SecurityDepositDeductionModel,
           "credit": SecurityDepositCreditModel, "refund": SecurityDepositRefundModel}


class SQLiteDepositUnitOfWork:
    def __init__(self, database, recorder, leases, parties, inspections, files):
        self.engine = create_sqlite_engine(database); self.recorder = recorder; self.leases = leases; self.parties = parties; self.inspections = inspections; self.files = files
    def write(self, operation):
        try:
            with immediate_transaction(self.engine) as connection:
                return operation(_Transaction(connection, self.recorder, self.leases, self.parties, self.inspections, self.files))
        except (IntegrityError, OperationalError) as error:
            raise FinanceConflictError("The security-deposit record changed concurrently or conflicts with an existing record.") from error
    def read(self, operation):
        with self.engine.connect() as connection:
            return operation(_Transaction(connection, self.recorder, self.leases, self.parties, self.inspections, self.files))


class _Transaction:
    def __init__(self, connection, recorder, leases, parties, inspections, files): self.connection = connection; self.recorder = recorder; self.leases = leases; self.parties = parties; self.inspections = inspections; self.files = files
    def lease_context(self, lease_id, lease_term_id): return self.leases.deposit_context(self.connection, lease_id, lease_term_id)
    def participants(self, lease_id): return self.leases.deposit_participants(self.connection, lease_id)
    def party(self, party_id):
        item = self.parties.party(self.connection, party_id)
        return None if item is None else {"id": item.id, "display_name": item.display_name, "archived_at": item.archived_at}
    def account(self, record_id): return _one(self.connection, SecurityDepositAccountModel, record_id)
    def account_for_lease(self, lease_id): return self.connection.execute(select(SecurityDepositAccountModel.__table__).where(SecurityDepositAccountModel.lease_id == lease_id)).mappings().first()
    def accounts(self, **filters):
        query = select(SecurityDepositAccountModel.__table__)
        for name, value in filters.items():
            if value is not None: query = query.where(getattr(SecurityDepositAccountModel, name) == value)
        return [dict(row) for row in self.connection.execute(query.order_by(SecurityDepositAccountModel.created_at.desc())).mappings()]
    def receipt(self, record_id): return _one(self.connection, SecurityDepositReceiptModel, record_id)
    def receipt_by_key(self, key): return self.connection.execute(select(SecurityDepositReceiptModel.__table__).where(SecurityDepositReceiptModel.idempotency_key == key)).mappings().first()
    def receipt_replacement_exists(self, receipt_id): return self.connection.execute(select(SecurityDepositReceiptModel.id).where(SecurityDepositReceiptModel.replaces_receipt_id == receipt_id)).first() is not None
    def receipt_replacement(self, receipt_id): return self.connection.execute(select(SecurityDepositReceiptModel.id).where(SecurityDepositReceiptModel.replaces_receipt_id == receipt_id)).scalar_one_or_none()
    def receipts(self, account_id, *, active_only=False):
        query = select(SecurityDepositReceiptModel.__table__).where(SecurityDepositReceiptModel.account_id == account_id)
        if active_only: query = query.where(SecurityDepositReceiptModel.voided_at.is_(None))
        return [dict(row) for row in self.connection.execute(query.order_by(SecurityDepositReceiptModel.received_on, SecurityDepositReceiptModel.id)).mappings()]
    def settlement(self, record_id): return _one(self.connection, SecurityDepositSettlementModel, record_id)
    def settlements(self, account_id): return [dict(row) for row in self.connection.execute(select(SecurityDepositSettlementModel.__table__).where(SecurityDepositSettlementModel.account_id == account_id)).mappings()]
    def settlement_replacement_exists(self, settlement_id): return self.connection.execute(select(SecurityDepositSettlementModel.id).where(SecurityDepositSettlementModel.replaces_settlement_id == settlement_id)).first() is not None
    def settlement_replacement(self, settlement_id): return self.connection.execute(select(SecurityDepositSettlementModel.id).where(SecurityDepositSettlementModel.replaces_settlement_id == settlement_id)).scalar_one_or_none()
    def settlement_receipt_ids(self, settlement_id): return set(self.connection.execute(select(SecurityDepositSettlementReceiptModel.receipt_id).where(SecurityDepositSettlementReceiptModel.settlement_id == settlement_id)).scalars())
    def capture_settlement_receipt(self, settlement_id, receipt_id, stamp): self.connection.execute(SecurityDepositSettlementReceiptModel.__table__.insert().values(settlement_id=settlement_id, receipt_id=receipt_id, created_at=stamp))
    def deductions(self, settlement_id): return [dict(row) for row in self.connection.execute(select(SecurityDepositDeductionModel.__table__).where(SecurityDepositDeductionModel.settlement_id == settlement_id)).mappings()]
    def deduction(self, record_id): return _one(self.connection, SecurityDepositDeductionModel, record_id)
    def credit(self, record_id): return _one(self.connection, SecurityDepositCreditModel, record_id)
    def deduction_sources(self, deduction_id): return [dict(row) for row in self.connection.execute(select(SecurityDepositDeductionSourceModel.__table__).where(SecurityDepositDeductionSourceModel.deduction_id == deduction_id)).mappings()]
    def deduction_source(self, record_id): return _one(self.connection, SecurityDepositDeductionSourceModel, record_id)
    def insert_source(self, item): self.connection.execute(SecurityDepositDeductionSourceModel.__table__.insert().values(**item))
    def replace_source(self, item): self.connection.execute(SecurityDepositDeductionSourceModel.__table__.update().where(SecurityDepositDeductionSourceModel.id == item["id"]).values(**item))
    def source_context(self, source_kind, source_id):
        if source_kind == "rent_expectation":
            row = self.connection.execute(select(RentExpectationModel.__table__).where(RentExpectationModel.id == source_id)).mappings().first()
            if row is None:
                return None
            received = self.connection.execute(
                select(func.coalesce(func.sum(RentReceiptAllocationModel.amount_minor), 0))
                .join(RentReceiptModel, RentReceiptModel.id == RentReceiptAllocationModel.receipt_id)
                .where(
                    RentReceiptAllocationModel.expectation_id == source_id,
                    RentReceiptModel.voided_at.is_(None),
                )
            ).scalar_one()
            return {"leaseId": row["lease_id"], "summary": f"Rent expectation due {row['due_on']}", "outstandingAmountMinor": max(0, row["expected_amount_minor"] - received), "active": row["voided_at"] is None}
        if source_kind == "expense":
            row = self.connection.execute(select(ExpenseModel.__table__).where(ExpenseModel.id == source_id)).mappings().first()
            return None if row is None else {"propertyId": row["property_id"], "spaceId": row["space_id"], "summary": f"Expense {row['paid_on']}", "active": row["voided_at"] is None}
        return self.inspections.source_context(self.connection, source_kind, source_id)
    def expense_source_used_elsewhere(self, expense_id, deduction_id):
        return self.connection.execute(
            select(SecurityDepositDeductionSourceModel.id)
            .where(
                SecurityDepositDeductionSourceModel.source_kind == "expense",
                SecurityDepositDeductionSourceModel.source_id == expense_id,
                SecurityDepositDeductionSourceModel.deduction_id != deduction_id,
            )
        ).first() is not None
    def deduction_has_file_evidence(self, deduction_id): return self.files.active_deduction_evidence(self.connection, deduction_id)
    def evidence(self, entity_type, entity_id):
        return self.files.evidence(self.connection, entity_type, entity_id)
    def inspection_warnings(self, lease_id): return self.inspections.deposit_warnings(self.connection, lease_id)
    def credits(self, settlement_id): return [dict(row) for row in self.connection.execute(select(SecurityDepositCreditModel.__table__).where(SecurityDepositCreditModel.settlement_id == settlement_id)).mappings()]
    def refund(self, record_id): return _one(self.connection, SecurityDepositRefundModel, record_id)
    def refund_by_key(self, key): return self.connection.execute(select(SecurityDepositRefundModel.__table__).where(SecurityDepositRefundModel.idempotency_key == key)).mappings().first()
    def refund_replacement_exists(self, refund_id): return self.connection.execute(select(SecurityDepositRefundModel.id).where(SecurityDepositRefundModel.replaces_refund_id == refund_id)).first() is not None
    def refund_replacement(self, refund_id): return self.connection.execute(select(SecurityDepositRefundModel.id).where(SecurityDepositRefundModel.replaces_refund_id == refund_id)).scalar_one_or_none()
    def refunds(self, account_id, *, active_only=False):
        query = select(SecurityDepositRefundModel.__table__).where(SecurityDepositRefundModel.account_id == account_id)
        if active_only: query = query.where(SecurityDepositRefundModel.voided_at.is_(None))
        return [dict(row) for row in self.connection.execute(query.order_by(SecurityDepositRefundModel.paid_on, SecurityDepositRefundModel.id)).mappings()]
    def insert(self, kind, item): self.connection.execute(_MODELS[kind].__table__.insert().values(**item))
    def replace(self, kind, item): self.connection.execute(_MODELS[kind].__table__.update().where(_MODELS[kind].id == item["id"]).values(**item))
    def delete(self, kind, record_id):
        model = _MODELS.get(kind, SecurityDepositDeductionSourceModel if kind == "source" else None)
        self.connection.execute(model.__table__.delete().where(model.id == record_id))
    def record_change(self, **kwargs): self.recorder.record_change(self.connection.connection.driver_connection, **kwargs)


def _one(connection, model, record_id):
    row = connection.execute(select(model.__table__).where(model.id == record_id)).mappings().first()
    return dict(row) if row else None

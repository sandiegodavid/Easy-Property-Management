"""SQLite implementation of FIN-001's transaction port."""
from __future__ import annotations
from collections.abc import Callable
from typing import Any, TypeVar
from sqlalchemy import and_, func, or_, select, text
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.finance.application.ports import FinanceTransaction, LeaseFinanceOperations, PartyFinanceOperations
from app.modules.finance.domain.models import RentExpectation, RentReceipt
from app.modules.finance.infrastructure.sqlalchemy_models import RentExpectationModel, RentExpectationTimelinessReviewModel, RentReceiptModel, RentReceiptAllocationModel
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction
Result = TypeVar("Result")
class SQLiteFinanceUnitOfWork:
    def __init__(self, database, recorder: AuditRecorder, lease_operations: LeaseFinanceOperations, party_operations: PartyFinanceOperations): self.engine=create_sqlite_engine(database); self.recorder=recorder; self.lease_operations=lease_operations; self.party_operations=party_operations
    def write(self, operation: Callable[[FinanceTransaction], Result]) -> Result:
        with immediate_transaction(self.engine) as connection: return operation(_Tx(connection, self.recorder, self.lease_operations, self.party_operations))
    def read(self, operation: Callable[[FinanceTransaction], Result]) -> Result:
        # Listing and presentation never write.  Keep them out of SQLite's
        # immediate writer transaction so ordinary GET requests retain WAL's
        # concurrent-read behaviour.
        with self.engine.connect() as connection:
            return operation(_Tx(connection, self.recorder, self.lease_operations, self.party_operations))
class _Tx:
    def __init__(self, connection, recorder, lease_operations, party_operations): self.connection=connection; self.recorder=recorder; self.lease_operations=lease_operations; self.party_operations=party_operations
    def lease_term_snapshot(self, lease_id, term_id): return self.lease_operations.term_snapshot(self.connection, lease_id, term_id)
    def historical_term_snapshot(self, lease_id, term_id): return self.lease_operations.historical_term_snapshot(self.connection, lease_id, term_id)
    def historical_term_snapshots(self, pairs): return self.lease_operations.historical_term_snapshots(self.connection, pairs)
    def party_exists(self, party_id): return self.party_operations.exists(self.connection, party_id)
    def lease_time_zone(self, lease_id): return self.lease_operations.lease_time_zone(self.connection, lease_id)
    def expectation(self, record_id):
        row=self.connection.execute(RentExpectationModel.__table__.select().where(RentExpectationModel.id==record_id)).mappings().first(); return RentExpectation(**dict(row)) if row else None
    def expectations_for_term(self, term_id): return self.expectations(lease_term_id=term_id)
    def expectations(self, **filters):
        query=RentExpectationModel.__table__.select()
        for key,value in filters.items():
            if value is not None: query=query.where(getattr(RentExpectationModel,key)==value)
        return [RentExpectation(**dict(row)) for row in self.connection.execute(query.order_by(RentExpectationModel.due_on,RentExpectationModel.id)).mappings()]
    def expectation_page(self, *, lease_id, due_from, due_to, include_voided, cursor, limit):
        query = RentExpectationModel.__table__.select()
        if lease_id is not None:
            query = query.where(RentExpectationModel.lease_id == lease_id)
        if due_from is not None:
            query = query.where(RentExpectationModel.due_on >= due_from)
        if due_to is not None:
            query = query.where(RentExpectationModel.due_on <= due_to)
        if not include_voided:
            query = query.where(RentExpectationModel.voided_at.is_(None))
        if cursor is not None:
            query = query.where(or_(RentExpectationModel.due_on > cursor[0], and_(RentExpectationModel.due_on == cursor[0], RentExpectationModel.id > cursor[1])))
        query = query.order_by(RentExpectationModel.due_on, RentExpectationModel.id).limit(limit)
        return [RentExpectation(**dict(row)) for row in self.connection.execute(query).mappings()]
    def receipt(self, record_id):
        row=self.connection.execute(RentReceiptModel.__table__.select().where(RentReceiptModel.id==record_id)).mappings().first(); return RentReceipt(**dict(row)) if row else None
    def receipt_by_key(self,key):
        row=self.connection.execute(RentReceiptModel.__table__.select().where(RentReceiptModel.idempotency_key==key)).mappings().first(); return RentReceipt(**dict(row)) if row else None
    def receipt_page(self, *, lease_id, received_from, received_to, received_by_party_id, include_voided, cursor, limit):
        query = RentReceiptModel.__table__.select()
        if lease_id is not None:
            query = query.where(RentReceiptModel.lease_id == lease_id)
        if received_from is not None:
            query = query.where(RentReceiptModel.received_on >= received_from)
        if received_to is not None:
            query = query.where(RentReceiptModel.received_on <= received_to)
        if received_by_party_id is not None:
            query = query.where(RentReceiptModel.received_by_party_id == received_by_party_id)
        if not include_voided:
            query = query.where(RentReceiptModel.voided_at.is_(None))
        if cursor is not None:
            query = query.where(or_(RentReceiptModel.received_on > cursor[0], and_(RentReceiptModel.received_on == cursor[0], RentReceiptModel.id > cursor[1])))
        query = query.order_by(RentReceiptModel.received_on, RentReceiptModel.id).limit(limit)
        return [RentReceipt(**dict(row)) for row in self.connection.execute(query).mappings()]
    def receipt_chain_page(self, *, receipt_id, lease_id, received_from, received_to, received_by_party_id, include_voided, cursor, limit):
        selected = self.receipt(receipt_id)
        if selected is None:
            raise LookupError(receipt_id)
        root = selected
        seen = set()
        while root.replaces_receipt_id:
            if root.id in seen:
                raise ValueError("Receipt replacement chain is cyclic.")
            seen.add(root.id)
            parent = self.receipt(root.replaces_receipt_id)
            if parent is None:
                raise ValueError("Receipt replacement chain is incomplete.")
            root = parent
        clauses = ["r.id IN (SELECT id FROM chain)"]
        params = {"root_id": root.id, "limit": limit}
        if lease_id is not None:
            clauses.append("r.lease_id = :lease_id"); params["lease_id"] = lease_id
        if received_from is not None:
            clauses.append("r.received_on >= :received_from"); params["received_from"] = received_from
        if received_to is not None:
            clauses.append("r.received_on <= :received_to"); params["received_to"] = received_to
        if received_by_party_id is not None:
            clauses.append("r.received_by_party_id = :received_by_party_id"); params["received_by_party_id"] = received_by_party_id
        if not include_voided:
            clauses.append("r.voided_at IS NULL")
        if cursor is not None:
            clauses.append("(r.received_on > :cursor_date OR (r.received_on = :cursor_date AND r.id > :cursor_id))")
            params["cursor_date"], params["cursor_id"] = cursor
        statement = text(f"""
            WITH RECURSIVE chain(id) AS (
                SELECT :root_id
                UNION ALL
                SELECT child.id
                FROM rent_receipts AS child
                JOIN chain ON child.replaces_receipt_id = chain.id
            )
            SELECT r.* FROM rent_receipts AS r
            WHERE {' AND '.join(clauses)}
            ORDER BY r.received_on, r.id
            LIMIT :limit
        """)
        return [RentReceipt(**dict(row)) for row in self.connection.execute(statement, params).mappings()]
    def receipt_allocations(self, receipt_id): return [dict(r) for r in self.connection.execute(RentReceiptAllocationModel.__table__.select().where(RentReceiptAllocationModel.receipt_id==receipt_id)).mappings()]
    def receipt_projection(self, receipt_ids):
        projection = {record_id: [] for record_id in receipt_ids}
        if not projection:
            return projection
        statement = select(
            RentReceiptAllocationModel.id.label("id"),
            RentReceiptAllocationModel.receipt_id.label("receipt_id"),
            RentReceiptAllocationModel.expectation_id.label("expectation_id"),
            RentReceiptAllocationModel.amount_minor.label("amount_minor"),
            RentReceiptAllocationModel.created_at.label("created_at"),
            RentExpectationModel.due_on.label("expectation_due_on"),
            RentExpectationModel.period_starts_on.label("expectation_period_starts_on"),
            RentExpectationModel.period_ends_on.label("expectation_period_ends_on"),
        ).select_from(
            RentReceiptAllocationModel.__table__.outerjoin(
                RentExpectationModel.__table__,
                RentReceiptAllocationModel.expectation_id == RentExpectationModel.id,
            )
        ).where(RentReceiptAllocationModel.receipt_id.in_(projection)).order_by(
            RentReceiptAllocationModel.receipt_id,
            RentReceiptAllocationModel.created_at,
            RentReceiptAllocationModel.id,
        )
        for row in self.connection.execute(statement).mappings():
            value = dict(row)
            projection[value["receipt_id"]].append({
                "id": value["id"],
                "receiptId": value["receipt_id"],
                "expectationId": value["expectation_id"],
                "amountMinor": value["amount_minor"],
                "createdAt": value["created_at"],
                "expectationDueOn": value["expectation_due_on"],
                "expectationPeriodStartsOn": value["expectation_period_starts_on"],
                "expectationPeriodEndsOn": value["expectation_period_ends_on"],
            })
        return projection
    def expectation_projection(self, expectation_ids):
        projection = {
            record_id: {"summaries": [], "timeline": [], "reviews": [], "activity": []}
            for record_id in expectation_ids
        }
        if not projection:
            return projection
        allocations = select(
            RentReceiptAllocationModel.id.label("allocationId"),
            RentReceiptAllocationModel.expectation_id.label("expectationId"),
            RentReceiptAllocationModel.receipt_id.label("receiptId"),
            RentReceiptAllocationModel.amount_minor.label("amountMinor"),
            RentReceiptModel.received_on.label("receivedOn"),
            RentReceiptModel.created_at.label("createdAt"),
            RentReceiptModel.voided_at.label("voidedAt"),
        ).select_from(
            RentReceiptAllocationModel.__table__.join(RentReceiptModel.__table__)
        ).where(
            RentReceiptAllocationModel.expectation_id.in_(projection)
        ).order_by(RentReceiptModel.received_on, RentReceiptModel.created_at, RentReceiptAllocationModel.id)
        for row in self.connection.execute(allocations).mappings():
            value = dict(row)
            record = projection[value["expectationId"]]
            record["summaries"].append({
                "allocationId": value["allocationId"],
                "receiptId": value["receiptId"],
                "receivedOn": value["receivedOn"],
                "amountMinor": value["amountMinor"],
                "receiptLifecycleStatus": "voided" if value["voidedAt"] else "active",
            })
            record["activity"].append(value["createdAt"])
            if value["voidedAt"] is None:
                record["timeline"].append({
                    "amount_minor": value["amountMinor"],
                    "received_on": value["receivedOn"],
                    "created_at": value["createdAt"],
                })
        reviews = RentExpectationTimelinessReviewModel.__table__.select().where(
            RentExpectationTimelinessReviewModel.expectation_id.in_(projection)
        ).order_by(
            RentExpectationTimelinessReviewModel.expectation_id,
            RentExpectationTimelinessReviewModel.created_at,
            RentExpectationTimelinessReviewModel.id,
        )
        for row in self.connection.execute(reviews).mappings():
            value = dict(row)
            projection[value["expectation_id"]]["reviews"].append(value)
        return projection
    def allocated_amount(self, expectation_id):
        statement=select(func.coalesce(func.sum(RentReceiptAllocationModel.amount_minor),0)).select_from(RentReceiptAllocationModel.__table__.join(RentReceiptModel.__table__)).where(RentReceiptAllocationModel.expectation_id==expectation_id,RentReceiptModel.voided_at.is_(None)); return int(self.connection.execute(statement).scalar_one())
    def receipt_activity_after(self, expectation_id, occurred_at):
        statement = select(RentReceiptAllocationModel.id).select_from(RentReceiptAllocationModel.__table__.join(RentReceiptModel.__table__)).where(RentReceiptAllocationModel.expectation_id == expectation_id, RentReceiptModel.created_at > occurred_at).limit(1)
        return self.connection.execute(statement).first() is not None
    def replacement_exists(self, receipt_id):
        return self.connection.execute(RentReceiptModel.__table__.select().where(RentReceiptModel.replaces_receipt_id == receipt_id)).first() is not None
    def reviews(self, expectation_id): return [dict(r) for r in self.connection.execute(RentExpectationTimelinessReviewModel.__table__.select().where(RentExpectationTimelinessReviewModel.expectation_id==expectation_id).order_by(RentExpectationTimelinessReviewModel.created_at,RentExpectationTimelinessReviewModel.id)).mappings()]
    def insert_expectation(self,item): self.connection.execute(RentExpectationModel.__table__.insert().values(**item.__dict__))
    def replace_expectation(self,item): self.connection.execute(RentExpectationModel.__table__.update().where(RentExpectationModel.id==item.id).values(**item.__dict__))
    def insert_receipt(self,item): self.connection.execute(RentReceiptModel.__table__.insert().values(**item.__dict__))
    def replace_receipt(self,item): self.connection.execute(RentReceiptModel.__table__.update().where(RentReceiptModel.id==item.id).values(**item.__dict__))
    def insert_allocation(self,item): self.connection.execute(RentReceiptAllocationModel.__table__.insert().values(**item))
    def insert_review(self,item): self.connection.execute(RentExpectationTimelinessReviewModel.__table__.insert().values(**item))
    def record_change(self,**change): self.recorder.record_change(self.connection.connection.driver_connection,**change)

"""SQLite implementation of FIN-001's transaction port."""
from __future__ import annotations
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import uuid4
from sqlalchemy import and_, func, or_, select, text
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.finance.application.ports import FinanceTransaction, LeaseTermFinanceSnapshot, PartyFinanceOperations
from app.modules.finance.domain.models import PrepaidCheck, RentExpectation, RentReceipt
from app.modules.finance.infrastructure.sqlalchemy_models import PrepaidCheckModel, PrepaidCheckOperationModel, RentExpectationModel, RentExpectationTimelinessReviewModel, RentReceiptModel, RentReceiptAllocationModel
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction
from app.modules.tasks.application.ports import TaskTransactionOperations
from app.modules.tasks.domain.models import Task, TaskReminder, dismiss
from app.modules.leases.application.ports import LeaseContextReader
from app.modules.portfolio.application.ports import PortfolioContextReader
Result = TypeVar("Result")
_PORTFOLIO_CONTEXT_UNSET = object()
class SQLiteFinanceUnitOfWork:
    def __init__(self, database, recorder: AuditRecorder, lease_operations: LeaseContextReader, portfolio_operations: PortfolioContextReader, party_operations: PartyFinanceOperations, task_operations: TaskTransactionOperations | None = None): self.engine=create_sqlite_engine(database); self.recorder=recorder; self.lease_operations=lease_operations; self.portfolio_operations=portfolio_operations; self.party_operations=party_operations; self.task_operations=task_operations
    def write(self, operation: Callable[[FinanceTransaction], Result]) -> Result:
        with immediate_transaction(self.engine) as connection: return operation(_Tx(connection, self.recorder, self.lease_operations, self.portfolio_operations, self.party_operations, self.task_operations))
    def read(self, operation: Callable[[FinanceTransaction], Result]) -> Result:
        # Listing and presentation never write.  Keep them out of SQLite's
        # immediate writer transaction so ordinary GET requests retain WAL's
        # concurrent-read behaviour.
        with self.engine.connect() as connection:
            return operation(_Tx(connection, self.recorder, self.lease_operations, self.portfolio_operations, self.party_operations, self.task_operations))
class _Tx:
    def __init__(self, connection, recorder, lease_operations, portfolio_operations, party_operations, task_operations): self.connection=connection; self.recorder=recorder; self.lease_operations=lease_operations; self.portfolio_operations=portfolio_operations; self.party_operations=party_operations; self.task_operations=task_operations
    def lease_term_snapshot(self, lease_id, term_id):
        context = self.lease_operations.term_context(self.connection, lease_id, term_id)
        return self._finance_snapshot(context, current_only=True)
    def historical_term_snapshot(self, lease_id, term_id):
        context = self.lease_operations.term_context(self.connection, lease_id, term_id)
        return self._finance_snapshot(context, current_only=False)
    def historical_term_snapshots(self, pairs):
        contexts = self.lease_operations.term_contexts(self.connection, pairs)
        spaces = {context["lease"]["space_id"] for context in contexts.values()}
        portfolio_contexts = self.portfolio_operations.contexts_for_spaces(self.connection, spaces)
        return {
            pair: snapshot
            for pair, context in contexts.items()
            if (snapshot := self._finance_snapshot(context, current_only=False, portfolio_context=portfolio_contexts.get(context["lease"]["space_id"]))) is not None
        }
    def party_exists(self, party_id): return self.party_operations.exists(self.connection, party_id)
    def lease_time_zone(self, lease_id):
        space_id = self.lease_operations.lease_space_id(self.connection, lease_id)
        context = None if space_id is None else self.portfolio_operations.context_for_space(self.connection, space_id)
        return None if context is None else context["time_zone"]
    def participant_active(self, lease_id, party_id, on): return self.lease_operations.participant_active(self.connection, lease_id, party_id, on)
    def _finance_snapshot(self, context, *, current_only, portfolio_context=_PORTFOLIO_CONTEXT_UNSET):
        if context is None:
            return None
        lease = context["lease"]
        if current_only and lease["status"] not in {"executed", "ended", "terminated"}:
            return None
        if portfolio_context is _PORTFOLIO_CONTEXT_UNSET:
            portfolio_context = self.portfolio_operations.context_for_space(self.connection, lease["space_id"])
        if portfolio_context is None:
            return None
        term = context["term"]
        return LeaseTermFinanceSnapshot(
            term["id"], lease["id"], lease["status"], portfolio_context["property_id"],
            portfolio_context["space_id"], portfolio_context["time_zone"], term["effective_on"],
            term["ends_on"], term["base_rent_minor"], term["currency_code"],
            term["payment_frequency"], term["payment_due_day"], lease["actual_move_out_on"],
            context.get("rent_responsibility_ends_on") if "rent_responsibility_ends_on" in context else self.lease_operations.rent_responsibility_ends_on(self.connection, lease["id"]),
        )
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
    def latest_non_voided_receipt(self, lease_id):
        row = self.connection.execute(
            RentReceiptModel.__table__.select().where(
                RentReceiptModel.lease_id == lease_id,
                RentReceiptModel.voided_at.is_(None),
            ).order_by(
                RentReceiptModel.received_on.desc(),
                RentReceiptModel.created_at.desc(),
                RentReceiptModel.id.desc(),
            ).limit(1)
        ).mappings().first()
        return RentReceipt(**dict(row)) if row else None
    def likely_duplicate_receipts(self, *, lease_id, received_on, amount_minor, received_by_party_id):
        query = RentReceiptModel.__table__.select().where(
            RentReceiptModel.lease_id == lease_id,
            RentReceiptModel.received_on == received_on,
            RentReceiptModel.amount_minor == amount_minor,
            RentReceiptModel.voided_at.is_(None),
        )
        if received_by_party_id is None:
            query = query.where(RentReceiptModel.received_by_party_id.is_(None))
        else:
            query = query.where(RentReceiptModel.received_by_party_id == received_by_party_id)
        return [
            RentReceipt(**dict(row))
            for row in self.connection.execute(
                query.order_by(RentReceiptModel.created_at, RentReceiptModel.id)
            ).mappings()
        ]
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
    def prepaid_check(self, check_id):
        row = self.connection.execute(PrepaidCheckModel.__table__.select().where(PrepaidCheckModel.id == check_id)).mappings().first()
        return PrepaidCheck(**dict(row)) if row else None
    def prepaid_checks(self, *, lease_id=None, status=None):
        query = PrepaidCheckModel.__table__.select()
        if lease_id is not None: query = query.where(PrepaidCheckModel.lease_id == lease_id)
        if status is not None: query = query.where(PrepaidCheckModel.status == status)
        return [PrepaidCheck(**dict(row)) for row in self.connection.execute(query.order_by(PrepaidCheckModel.check_dated_on, PrepaidCheckModel.id)).mappings()]
    def prepaid_check_page(self, *, lease_id=None, payer_party_id=None, expectation_id=None, status=None, cursor=None, limit=101):
        query = PrepaidCheckModel.__table__.select()
        if lease_id is not None: query = query.where(PrepaidCheckModel.lease_id == lease_id)
        if payer_party_id is not None: query = query.where(PrepaidCheckModel.payer_party_id == payer_party_id)
        if expectation_id is not None: query = query.where(PrepaidCheckModel.expectation_id == expectation_id)
        if status is not None: query = query.where(PrepaidCheckModel.status == status)
        if cursor is not None:
            query = query.where((PrepaidCheckModel.check_dated_on > cursor[0]) | ((PrepaidCheckModel.check_dated_on == cursor[0]) & (PrepaidCheckModel.id > cursor[1])))
        return [PrepaidCheck(**dict(row)) for row in self.connection.execute(query.order_by(PrepaidCheckModel.check_dated_on, PrepaidCheckModel.id).limit(limit)).mappings()]
    def prepaid_check_by_operation_key(self, key):
        row = self.connection.execute(PrepaidCheckOperationModel.__table__.select().where(PrepaidCheckOperationModel.idempotency_key == key)).mappings().first()
        return dict(row) if row else None
    def prepaid_check_by_receipt(self, receipt_id):
        row = self.connection.execute(PrepaidCheckModel.__table__.select().where(PrepaidCheckModel.receipt_id == receipt_id)).mappings().first()
        return PrepaidCheck(**dict(row)) if row else None
    def insert_prepaid_check(self, item): self.connection.execute(PrepaidCheckModel.__table__.insert().values(**item.__dict__))
    def replace_prepaid_check(self, item): self.connection.execute(PrepaidCheckModel.__table__.update().where(PrepaidCheckModel.id == item.id).values(**item.__dict__))
    def insert_prepaid_check_operation(self, item): self.connection.execute(PrepaidCheckOperationModel.__table__.insert().values(**item))
    def create_prepaid_check_reminder(self, *, check_id, due_at_utc, due_timezone, correlation_id):
        if self.task_operations is None: raise RuntimeError("TASK-001 operations are not configured.")
        now = datetime.now(UTC).isoformat()
        task = Task(
            str(uuid4()), "Deposit prepaid check", None, "open", "normal",
            due_at_utc, due_timezone, True, None, None, None,
            "prepaid_check", check_id, "Prepaid check", now, now,
        )
        reminder = TaskReminder(str(uuid4()), task.id, due_at_utc, "pending", None, None, now)
        self.task_operations.insert_task(self.connection, task)
        self.task_operations.insert_reminder(self.connection, reminder)
        self.record_change(entity_type="task", entity_id=task.id, action="created", before=None,
                           after=task.to_dict(), reason="prepaid_check_reminder_created", correlation_id=correlation_id)
        self.record_change(entity_type="task_reminder", entity_id=reminder.id, action="created", before=None,
                           after=reminder.to_dict(), reason="prepaid_check_reminder_created", correlation_id=correlation_id)
        return task.id
    def dismiss_prepaid_check_reminder(self, task_id, *, correlation_id):
        if self.task_operations is None: raise RuntimeError("TASK-001 operations are not configured.")
        if task_id is None:
            return
        now = datetime.now(UTC).isoformat()
        for reminder in self.task_operations.pending_reminders(self.connection, task_id):
            dismissed = dismiss(reminder, now)
            self.task_operations.replace_reminder(self.connection, dismissed)
            self.record_change(entity_type="task_reminder", entity_id=dismissed.id, action="dismissed",
                               before=reminder.to_dict(), after=dismissed.to_dict(),
                               reason="prepaid_check_lifecycle_changed", correlation_id=correlation_id)
    def prepaid_check_reminder_status(self, task_id):
        if self.task_operations is None: raise RuntimeError("TASK-001 operations are not configured.")
        return None if task_id is None else self.task_operations.latest_reminder_status(self.connection, task_id)
    def record_change(self,**change): self.recorder.record_change(self.connection.connection.driver_connection,**change)

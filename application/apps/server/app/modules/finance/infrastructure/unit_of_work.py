"""SQLite implementation of FIN-001's transaction port."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, text

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.finance.application.late_fee_ports import (
    NoOpPendingPaymentReader,
    PendingPaymentReader,
)
from app.modules.finance.application.ports import (
    FinanceTransaction,
    LeaseTermFinanceSnapshot,
    PartyFinanceOperations,
)
from app.modules.finance.domain.late_fee_calculator import (
    PriorAssessmentFact,
    ScheduledPrepaidCheckWarning,
)
from app.modules.finance.domain.late_fee_models import (
    LateFeeAssessment,
    LateFeeLeaseWaiver,
    LateFeePolicyVersion,
    LateFeeReceipt,
    LateFeeWaiver,
)
from app.modules.finance.domain.models import PrepaidCheck, RentExpectation, RentReceipt
from app.modules.finance.infrastructure.command_operations import SQLiteFinanceCommandTransaction
from app.modules.finance.infrastructure.sqlalchemy_models import (
    LateFeeAssessmentModel,
    LateFeeLeaseWaiverModel,
    LateFeePolicyVersionModel,
    LateFeeReceiptAllocationModel,
    LateFeeReceiptModel,
    LateFeeWaiverModel,
    PrepaidCheckModel,
    PrepaidCheckOperationModel,
    RentExpectationModel,
    RentExpectationTimelinessReviewModel,
    RentReceiptAllocationModel,
    RentReceiptModel,
)
from app.modules.leases.application.ports import LeaseContextReader
from app.modules.portfolio.application.ports import PortfolioContextReader
from app.modules.tasks.application.ports import TaskTransactionOperations
from app.modules.tasks.domain.models import Task, TaskReminder, dismiss
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

Result = TypeVar("Result")
_PORTFOLIO_CONTEXT_UNSET = object()


class SQLiteFinanceUnitOfWork:
    def __init__(
        self,
        database,
        recorder: AuditRecorder,
        lease_operations: LeaseContextReader,
        portfolio_operations: PortfolioContextReader,
        party_operations: PartyFinanceOperations,
        task_operations: TaskTransactionOperations | None = None,
        pending_payment_reader: PendingPaymentReader | None = None,
    ):
        self.engine = create_sqlite_engine(database)
        self.recorder = recorder
        self.lease_operations = lease_operations
        self.portfolio_operations = portfolio_operations
        self.party_operations = party_operations
        self.task_operations = task_operations
        self.pending_payment_reader = pending_payment_reader or NoOpPendingPaymentReader()

    def write(self, operation: Callable[[FinanceTransaction], Result]) -> Result:
        with immediate_transaction(self.engine) as connection:
            return operation(
                _Tx(
                    connection,
                    self.recorder,
                    self.lease_operations,
                    self.portfolio_operations,
                    self.party_operations,
                    self.task_operations,
                    self.pending_payment_reader,
                )
            )

    def read(self, operation: Callable[[FinanceTransaction], Result]) -> Result:
        # Listing and presentation never write.  Keep them out of SQLite's
        # immediate writer transaction so ordinary GET requests retain WAL's
        # concurrent-read behaviour.
        with self.engine.connect() as connection:
            return operation(
                _Tx(
                    connection,
                    self.recorder,
                    self.lease_operations,
                    self.portfolio_operations,
                    self.party_operations,
                    self.task_operations,
                    self.pending_payment_reader,
                )
            )


class _Tx:
    def __init__(
        self,
        connection,
        recorder,
        lease_operations,
        portfolio_operations,
        party_operations,
        task_operations,
        pending_payment_reader=None,
    ):
        self.connection = connection
        self.commands = SQLiteFinanceCommandTransaction(connection, recorder)
        self.recorder = recorder
        self.lease_operations = lease_operations
        self.portfolio_operations = portfolio_operations
        self.party_operations = party_operations
        self.task_operations = task_operations
        self.pending_payment_reader = pending_payment_reader or NoOpPendingPaymentReader()

    def money_property_contexts(self, property_ids, lease_ids):
        spaces = self.lease_operations.lease_space_ids(self.connection, lease_ids)
        contexts = self.portfolio_operations.contexts_for_spaces(
            self.connection, set(spaces.values())
        )
        lease_properties = {
            lease_id: str(contexts[space_id]["property_id"])
            for lease_id, space_id in spaces.items()
            if space_id in contexts
        }
        names = self.portfolio_operations.property_names(
            self.connection, property_ids | set(lease_properties.values())
        )
        return names, lease_properties

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
            if (
                snapshot := self._finance_snapshot(
                    context,
                    current_only=False,
                    portfolio_context=portfolio_contexts.get(context["lease"]["space_id"]),
                )
            )
            is not None
        }

    def party_exists(self, party_id):
        return self.party_operations.exists(self.connection, party_id)

    def lease_time_zone(self, lease_id):
        space_id = self.lease_operations.lease_space_id(self.connection, lease_id)
        context = (
            None
            if space_id is None
            else self.portfolio_operations.context_for_space(self.connection, space_id)
        )
        return None if context is None else context["time_zone"]

    def participant_active(self, lease_id, party_id, on):
        return self.lease_operations.participant_active(self.connection, lease_id, party_id, on)

    def _finance_snapshot(
        self, context, *, current_only, portfolio_context=_PORTFOLIO_CONTEXT_UNSET
    ):
        if context is None:
            return None
        lease = context["lease"]
        if current_only and lease["status"] not in {"executed", "ended", "terminated"}:
            return None
        if portfolio_context is _PORTFOLIO_CONTEXT_UNSET:
            portfolio_context = self.portfolio_operations.context_for_space(
                self.connection, lease["space_id"]
            )
        if portfolio_context is None:
            return None
        term = context["term"]
        return LeaseTermFinanceSnapshot(
            term["id"],
            lease["id"],
            lease["status"],
            portfolio_context["property_id"],
            portfolio_context["space_id"],
            portfolio_context["time_zone"],
            term["effective_on"],
            term["ends_on"],
            term["base_rent_minor"],
            term["currency_code"],
            term["payment_frequency"],
            term["payment_due_day"],
            lease["actual_move_out_on"],
            context.get("rent_responsibility_ends_on")
            if "rent_responsibility_ends_on" in context
            else self.lease_operations.rent_responsibility_ends_on(self.connection, lease["id"]),
        )

    def expectation(self, record_id):
        row = (
            self.connection.execute(
                RentExpectationModel.__table__.select().where(RentExpectationModel.id == record_id)
            )
            .mappings()
            .first()
        )
        return RentExpectation(**dict(row)) if row else None

    def expectations_by_ids(self, record_ids):
        ids = set(record_ids)
        if not ids:
            return {}
        rows = (
            self.connection.execute(
                RentExpectationModel.__table__.select().where(RentExpectationModel.id.in_(ids))
            )
            .mappings()
            .all()
        )
        return {row["id"]: RentExpectation(**dict(row)) for row in rows}

    def expectations_for_term(self, term_id):
        return self.expectations(lease_term_id=term_id)

    def expectations(self, **filters):
        query = RentExpectationModel.__table__.select()
        for key, value in filters.items():
            if value is not None:
                query = query.where(getattr(RentExpectationModel, key) == value)
        return [
            RentExpectation(**dict(row))
            for row in self.connection.execute(
                query.order_by(RentExpectationModel.due_on, RentExpectationModel.id)
            ).mappings()
        ]

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
            query = query.where(
                or_(
                    RentExpectationModel.due_on > cursor[0],
                    and_(
                        RentExpectationModel.due_on == cursor[0],
                        RentExpectationModel.id > cursor[1],
                    ),
                )
            )
        query = query.order_by(RentExpectationModel.due_on, RentExpectationModel.id).limit(limit)
        return [RentExpectation(**dict(row)) for row in self.connection.execute(query).mappings()]

    def receipt(self, record_id):
        row = (
            self.connection.execute(
                RentReceiptModel.__table__.select().where(RentReceiptModel.id == record_id)
            )
            .mappings()
            .first()
        )
        return RentReceipt(**dict(row)) if row else None

    def latest_non_voided_receipt(self, lease_id):
        row = (
            self.connection.execute(
                RentReceiptModel.__table__.select()
                .where(
                    RentReceiptModel.lease_id == lease_id,
                    RentReceiptModel.voided_at.is_(None),
                )
                .order_by(
                    RentReceiptModel.received_on.desc(),
                    RentReceiptModel.created_at.desc(),
                    RentReceiptModel.id.desc(),
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        return RentReceipt(**dict(row)) if row else None

    def likely_duplicate_receipts(
        self, *, lease_id, received_on, amount_minor, received_by_party_id, limit=20
    ):
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
                query.order_by(RentReceiptModel.created_at, RentReceiptModel.id).limit(limit)
            ).mappings()
        ]

    def receipt_by_key(self, key):
        row = (
            self.connection.execute(
                RentReceiptModel.__table__.select().where(RentReceiptModel.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        return RentReceipt(**dict(row)) if row else None

    def receipt_page(
        self,
        *,
        lease_id,
        received_from,
        received_to,
        received_by_party_id,
        include_voided,
        cursor,
        limit,
    ):
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
            query = query.where(
                or_(
                    RentReceiptModel.received_on > cursor[0],
                    and_(
                        RentReceiptModel.received_on == cursor[0], RentReceiptModel.id > cursor[1]
                    ),
                )
            )
        query = query.order_by(RentReceiptModel.received_on, RentReceiptModel.id).limit(limit)
        return [RentReceipt(**dict(row)) for row in self.connection.execute(query).mappings()]

    def receipt_chain_page(
        self,
        *,
        receipt_id,
        lease_id,
        received_from,
        received_to,
        received_by_party_id,
        include_voided,
        cursor,
        limit,
    ):
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
            clauses.append("r.lease_id = :lease_id")
            params["lease_id"] = lease_id
        if received_from is not None:
            clauses.append("r.received_on >= :received_from")
            params["received_from"] = received_from
        if received_to is not None:
            clauses.append("r.received_on <= :received_to")
            params["received_to"] = received_to
        if received_by_party_id is not None:
            clauses.append("r.received_by_party_id = :received_by_party_id")
            params["received_by_party_id"] = received_by_party_id
        if not include_voided:
            clauses.append("r.voided_at IS NULL")
        if cursor is not None:
            clauses.append(
                "(r.received_on > :cursor_date OR (r.received_on = :cursor_date AND r.id > :cursor_id))"
            )
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
            WHERE {" AND ".join(clauses)}
            ORDER BY r.received_on, r.id
            LIMIT :limit
        """)
        return [
            RentReceipt(**dict(row))
            for row in self.connection.execute(statement, params).mappings()
        ]

    def receipt_allocations(self, receipt_id):
        return [
            dict(r)
            for r in self.connection.execute(
                RentReceiptAllocationModel.__table__.select().where(
                    RentReceiptAllocationModel.receipt_id == receipt_id
                )
            ).mappings()
        ]

    def receipt_projection(self, receipt_ids):
        projection = {record_id: [] for record_id in receipt_ids}
        if not projection:
            return projection
        statement = (
            select(
                RentReceiptAllocationModel.id.label("id"),
                RentReceiptAllocationModel.receipt_id.label("receipt_id"),
                RentReceiptAllocationModel.expectation_id.label("expectation_id"),
                RentReceiptAllocationModel.amount_minor.label("amount_minor"),
                RentReceiptAllocationModel.created_at.label("created_at"),
                RentExpectationModel.due_on.label("expectation_due_on"),
                RentExpectationModel.period_starts_on.label("expectation_period_starts_on"),
                RentExpectationModel.period_ends_on.label("expectation_period_ends_on"),
            )
            .select_from(
                RentReceiptAllocationModel.__table__.outerjoin(
                    RentExpectationModel.__table__,
                    RentReceiptAllocationModel.expectation_id == RentExpectationModel.id,
                )
            )
            .where(RentReceiptAllocationModel.receipt_id.in_(projection))
            .order_by(
                RentReceiptAllocationModel.receipt_id,
                RentReceiptAllocationModel.created_at,
                RentReceiptAllocationModel.id,
            )
        )
        for row in self.connection.execute(statement).mappings():
            value = dict(row)
            projection[value["receipt_id"]].append(
                {
                    "id": value["id"],
                    "receiptId": value["receipt_id"],
                    "expectationId": value["expectation_id"],
                    "amountMinor": value["amount_minor"],
                    "createdAt": value["created_at"],
                    "expectationDueOn": value["expectation_due_on"],
                    "expectationPeriodStartsOn": value["expectation_period_starts_on"],
                    "expectationPeriodEndsOn": value["expectation_period_ends_on"],
                }
            )
        return projection

    def receipt_period_outcomes(self, receipt_id):
        # One set-based projection inside the committing transaction: these
        # balances belong to the immutable receipt, not a later mutable read.
        return [
            dict(row)
            for row in self.connection.execute(
                text("""
            SELECT e.id AS expectationId, e.period_starts_on AS periodStartsOn,
                   e.period_ends_on AS periodEndsOn,
                   e.expected_amount_minor - COALESCE(SUM(
                       CASE WHEN r.voided_at IS NULL THEN a.amount_minor ELSE 0 END
                   ), 0) AS outstandingAmountMinor
            FROM rent_expectations e
            LEFT JOIN rent_receipt_allocations a ON a.expectation_id = e.id
            LEFT JOIN rent_receipts r ON r.id = a.receipt_id
            WHERE e.id IN (
                SELECT expectation_id FROM rent_receipt_allocations WHERE receipt_id = :receipt_id
            )
            GROUP BY e.id
            ORDER BY e.period_starts_on, e.id
        """),
                {"receipt_id": receipt_id},
            ).mappings()
        ]

    def expectation_projection(self, expectation_ids):
        projection = {
            record_id: {"summaries": [], "timeline": [], "reviews": [], "activity": []}
            for record_id in expectation_ids
        }
        if not projection:
            return projection
        allocations = (
            select(
                RentReceiptAllocationModel.id.label("allocationId"),
                RentReceiptAllocationModel.expectation_id.label("expectationId"),
                RentReceiptAllocationModel.receipt_id.label("receiptId"),
                RentReceiptAllocationModel.amount_minor.label("amountMinor"),
                RentReceiptModel.received_on.label("receivedOn"),
                RentReceiptModel.created_at.label("createdAt"),
                RentReceiptModel.voided_at.label("voidedAt"),
            )
            .select_from(RentReceiptAllocationModel.__table__.join(RentReceiptModel.__table__))
            .where(RentReceiptAllocationModel.expectation_id.in_(projection))
            .order_by(
                RentReceiptModel.received_on,
                RentReceiptModel.created_at,
                RentReceiptAllocationModel.id,
            )
        )
        for row in self.connection.execute(allocations).mappings():
            value = dict(row)
            record = projection[value["expectationId"]]
            record["summaries"].append(
                {
                    "allocationId": value["allocationId"],
                    "receiptId": value["receiptId"],
                    "receivedOn": value["receivedOn"],
                    "amountMinor": value["amountMinor"],
                    "receiptLifecycleStatus": "voided" if value["voidedAt"] else "active",
                }
            )
            record["activity"].append(value["createdAt"])
            if value["voidedAt"] is None:
                record["timeline"].append(
                    {
                        "amount_minor": value["amountMinor"],
                        "received_on": value["receivedOn"],
                        "created_at": value["createdAt"],
                    }
                )
        reviews = (
            RentExpectationTimelinessReviewModel.__table__.select()
            .where(RentExpectationTimelinessReviewModel.expectation_id.in_(projection))
            .order_by(
                RentExpectationTimelinessReviewModel.expectation_id,
                RentExpectationTimelinessReviewModel.created_at,
                RentExpectationTimelinessReviewModel.id,
            )
        )
        for row in self.connection.execute(reviews).mappings():
            value = dict(row)
            projection[value["expectation_id"]]["reviews"].append(value)
        return projection

    def allocated_amount(self, expectation_id):
        statement = (
            select(func.coalesce(func.sum(RentReceiptAllocationModel.amount_minor), 0))
            .select_from(RentReceiptAllocationModel.__table__.join(RentReceiptModel.__table__))
            .where(
                RentReceiptAllocationModel.expectation_id == expectation_id,
                RentReceiptModel.voided_at.is_(None),
            )
        )
        return int(self.connection.execute(statement).scalar_one())

    def receipt_activity_after(self, expectation_id, occurred_at):
        statement = (
            select(RentReceiptAllocationModel.id)
            .select_from(RentReceiptAllocationModel.__table__.join(RentReceiptModel.__table__))
            .where(
                RentReceiptAllocationModel.expectation_id == expectation_id,
                RentReceiptModel.created_at > occurred_at,
            )
            .limit(1)
        )
        return self.connection.execute(statement).first() is not None

    def replacement_exists(self, receipt_id):
        return (
            self.connection.execute(
                RentReceiptModel.__table__.select().where(
                    RentReceiptModel.replaces_receipt_id == receipt_id
                )
            ).first()
            is not None
        )

    def reviews(self, expectation_id):
        return [
            dict(r)
            for r in self.connection.execute(
                RentExpectationTimelinessReviewModel.__table__.select()
                .where(RentExpectationTimelinessReviewModel.expectation_id == expectation_id)
                .order_by(
                    RentExpectationTimelinessReviewModel.created_at,
                    RentExpectationTimelinessReviewModel.id,
                )
            ).mappings()
        ]

    def insert_expectation(self, item):
        self.connection.execute(RentExpectationModel.__table__.insert().values(**item.__dict__))

    def replace_expectation(self, item):
        self.connection.execute(
            RentExpectationModel.__table__.update()
            .where(RentExpectationModel.id == item.id)
            .values(**item.__dict__)
        )

    def insert_receipt(self, item):
        self.connection.execute(RentReceiptModel.__table__.insert().values(**item.__dict__))

    def replace_receipt(self, item):
        self.connection.execute(
            RentReceiptModel.__table__.update()
            .where(RentReceiptModel.id == item.id)
            .values(**item.__dict__)
        )

    def insert_allocation(self, item):
        self.connection.execute(RentReceiptAllocationModel.__table__.insert().values(**item))

    def insert_review(self, item):
        self.connection.execute(
            RentExpectationTimelinessReviewModel.__table__.insert().values(**item)
        )

    def prepaid_check(self, check_id):
        row = (
            self.connection.execute(
                PrepaidCheckModel.__table__.select().where(PrepaidCheckModel.id == check_id)
            )
            .mappings()
            .first()
        )
        return PrepaidCheck(**dict(row)) if row else None

    def prepaid_checks(self, *, lease_id=None, status=None):
        query = PrepaidCheckModel.__table__.select()
        if lease_id is not None:
            query = query.where(PrepaidCheckModel.lease_id == lease_id)
        if status is not None:
            query = query.where(PrepaidCheckModel.status == status)
        return [
            PrepaidCheck(**dict(row))
            for row in self.connection.execute(
                query.order_by(PrepaidCheckModel.check_dated_on, PrepaidCheckModel.id)
            ).mappings()
        ]

    def prepaid_check_page(
        self,
        *,
        lease_id=None,
        payer_party_id=None,
        expectation_id=None,
        status=None,
        cursor=None,
        limit=101,
    ):
        query = PrepaidCheckModel.__table__.select()
        if lease_id is not None:
            query = query.where(PrepaidCheckModel.lease_id == lease_id)
        if payer_party_id is not None:
            query = query.where(PrepaidCheckModel.payer_party_id == payer_party_id)
        if expectation_id is not None:
            query = query.where(PrepaidCheckModel.expectation_id == expectation_id)
        if status is not None:
            query = query.where(PrepaidCheckModel.status == status)
        if cursor is not None:
            query = query.where(
                (PrepaidCheckModel.check_dated_on > cursor[0])
                | (
                    (PrepaidCheckModel.check_dated_on == cursor[0])
                    & (PrepaidCheckModel.id > cursor[1])
                )
            )
        return [
            PrepaidCheck(**dict(row))
            for row in self.connection.execute(
                query.order_by(PrepaidCheckModel.check_dated_on, PrepaidCheckModel.id).limit(limit)
            ).mappings()
        ]

    def prepaid_check_by_operation_key(self, key):
        row = (
            self.connection.execute(
                PrepaidCheckOperationModel.__table__.select().where(
                    PrepaidCheckOperationModel.idempotency_key == key
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def prepaid_check_by_receipt(self, receipt_id):
        row = (
            self.connection.execute(
                PrepaidCheckModel.__table__.select().where(
                    PrepaidCheckModel.receipt_id == receipt_id
                )
            )
            .mappings()
            .first()
        )
        return PrepaidCheck(**dict(row)) if row else None

    def insert_prepaid_check(self, item):
        self.connection.execute(PrepaidCheckModel.__table__.insert().values(**item.__dict__))

    def replace_prepaid_check(self, item):
        self.connection.execute(
            PrepaidCheckModel.__table__.update()
            .where(PrepaidCheckModel.id == item.id)
            .values(**item.__dict__)
        )

    def insert_prepaid_check_operation(self, item):
        self.connection.execute(PrepaidCheckOperationModel.__table__.insert().values(**item))

    def create_prepaid_check_reminder(
        self, *, check_id, due_at_utc, due_timezone, correlation_id, committed_at
    ):
        if self.task_operations is None:
            raise RuntimeError("TASK-001 operations are not configured.")
        now = committed_at
        task = Task(
            str(uuid4()),
            "Deposit prepaid check",
            None,
            "open",
            "normal",
            due_at_utc,
            due_timezone,
            True,
            None,
            None,
            None,
            "prepaid_check",
            check_id,
            "Prepaid check",
            now,
            now,
        )
        reminder = TaskReminder(str(uuid4()), task.id, due_at_utc, "pending", None, None, now)
        self.task_operations.insert_task(self.connection, task)
        self.task_operations.insert_reminder(self.connection, reminder)
        self.record_change(
            entity_type="task",
            entity_id=task.id,
            action="created",
            before=None,
            after=task.to_dict(),
            reason="prepaid_check_reminder_created",
            correlation_id=correlation_id,
        )
        self.record_change(
            entity_type="task_reminder",
            entity_id=reminder.id,
            action="created",
            before=None,
            after=reminder.to_dict(),
            reason="prepaid_check_reminder_created",
            correlation_id=correlation_id,
        )
        return task.id

    def dismiss_prepaid_check_reminder(self, task_id, *, correlation_id, committed_at):
        if self.task_operations is None:
            raise RuntimeError("TASK-001 operations are not configured.")
        if task_id is None:
            return
        now = committed_at
        for reminder in self.task_operations.pending_reminders(self.connection, task_id):
            dismissed = dismiss(reminder, now)
            self.task_operations.replace_reminder(self.connection, dismissed)
            self.record_change(
                entity_type="task_reminder",
                entity_id=dismissed.id,
                action="dismissed",
                before=reminder.to_dict(),
                after=dismissed.to_dict(),
                reason="prepaid_check_lifecycle_changed",
                correlation_id=correlation_id,
            )
        self.task_operations.cancel_task_if_open(
            self.connection,
            task_id,
            committed_at=now,
            reason="prepaid_check_lifecycle_changed",
            correlation_id=correlation_id,
            record_change=self.record_change,
        )

    def prepaid_check_reminder_status(self, task_id):
        if self.task_operations is None:
            raise RuntimeError("TASK-001 operations are not configured.")
        return (
            None
            if task_id is None
            else self.task_operations.latest_reminder_status(self.connection, task_id)
        )

    def prepaid_check_reminder_statuses(self, task_ids):
        if self.task_operations is None:
            raise RuntimeError("TASK-001 operations are not configured.")
        ids = {task_id for task_id in task_ids if task_id is not None}
        if not ids:
            return {}
        batch = getattr(self.task_operations, "latest_reminder_statuses", None)
        if batch is not None:
            return batch(self.connection, ids)
        return {
            task_id: self.task_operations.latest_reminder_status(self.connection, task_id)
            for task_id in ids
        }

    def receipts_by_ids(self, record_ids):
        ids = {record_id for record_id in record_ids if record_id is not None}
        if not ids:
            return {}
        rows = (
            self.connection.execute(
                RentReceiptModel.__table__.select().where(RentReceiptModel.id.in_(ids))
            )
            .mappings()
            .all()
        )
        return {row["id"]: RentReceipt(**dict(row)) for row in rows}

    def lease_status(self, lease_id):
        return self.lease_operations.lease_status(self.connection, lease_id)

    def lease_preview_context(self, lease_id):
        lease = self.lease_operations.lease_row(self.connection, lease_id)
        if lease is None:
            return None
        portfolio = self.portfolio_operations.context_for_space(self.connection, lease["space_id"])
        if portfolio is None:
            return None
        return {
            "lease_id": lease["id"],
            "status": lease["status"],
            "time_zone": portfolio["time_zone"],
        }

    def preview_rent_expectations(
        self, lease_id, *, rent_expectation_id=None, cursor=None, limit=24
    ):
        query = RentExpectationModel.__table__.select().where(
            RentExpectationModel.lease_id == lease_id
        )
        if rent_expectation_id is not None:
            row = (
                self.connection.execute(query.where(RentExpectationModel.id == rent_expectation_id))
                .mappings()
                .first()
            )
            return None if row is None else [RentExpectation(**dict(row))]
        paid_subq = (
            select(
                RentReceiptAllocationModel.expectation_id.label("expectation_id"),
                func.sum(RentReceiptAllocationModel.amount_minor).label("paid_minor"),
                func.max(RentReceiptModel.received_on).label("max_received_on"),
            )
            .join(RentReceiptModel, RentReceiptModel.id == RentReceiptAllocationModel.receipt_id)
            .where(RentReceiptModel.voided_at.is_(None))
            .group_by(RentReceiptAllocationModel.expectation_id)
            .subquery()
        )
        bulk_query = (
            select(RentExpectationModel.__table__)
            .outerjoin(paid_subq, paid_subq.c.expectation_id == RentExpectationModel.id)
            .where(
                RentExpectationModel.lease_id == lease_id,
                RentExpectationModel.voided_at.is_(None),
                or_(
                    func.coalesce(paid_subq.c.paid_minor, 0)
                    < RentExpectationModel.expected_amount_minor,
                    paid_subq.c.max_received_on > RentExpectationModel.due_on,
                ),
            )
        )
        if cursor is not None:
            bulk_query = bulk_query.where(
                or_(
                    RentExpectationModel.due_on > cursor[0],
                    and_(
                        RentExpectationModel.due_on == cursor[0],
                        RentExpectationModel.id > cursor[1],
                    ),
                )
            )
        rows = (
            self.connection.execute(
                bulk_query.order_by(RentExpectationModel.due_on, RentExpectationModel.id).limit(
                    limit
                )
            )
            .mappings()
            .all()
        )
        return [RentExpectation(**dict(row)) for row in rows]

    def active_rent_allocations_by_date(self, expectation_ids, *, through_on):
        ids = set(expectation_ids)
        if not ids:
            return {}
        rows = self.connection.execute(
            select(
                RentReceiptAllocationModel.expectation_id,
                RentReceiptModel.received_on,
                func.sum(RentReceiptAllocationModel.amount_minor).label("total_minor"),
            )
            .join(RentReceiptModel, RentReceiptModel.id == RentReceiptAllocationModel.receipt_id)
            .where(
                RentReceiptAllocationModel.expectation_id.in_(ids),
                RentReceiptModel.voided_at.is_(None),
                RentReceiptModel.received_on <= through_on,
            )
            .group_by(RentReceiptAllocationModel.expectation_id, RentReceiptModel.received_on)
        ).all()
        grouped: dict[str, list[tuple[str, int]]] = {}
        for expectation_id, received_on, total_minor in rows:
            grouped.setdefault(expectation_id, []).append((received_on, int(total_minor)))
        return grouped

    def active_late_fee_assessments_for_expectations(self, expectation_ids):
        ids = set(expectation_ids)
        if not ids:
            return {}
        rows = (
            self.connection.execute(
                select(
                    LateFeeAssessmentModel.rent_expectation_id,
                    LateFeeAssessmentModel.occurrence_number,
                    LateFeeAssessmentModel.accrual_starts_on,
                    LateFeeAssessmentModel.accrual_ends_on,
                    LateFeeAssessmentModel.accrual_days,
                    LateFeeAssessmentModel.assessed_amount_minor,
                )
                .where(
                    LateFeeAssessmentModel.rent_expectation_id.in_(ids),
                    LateFeeAssessmentModel.voided_at.is_(None),
                )
                .order_by(
                    LateFeeAssessmentModel.rent_expectation_id,
                    LateFeeAssessmentModel.occurrence_number,
                )
            )
            .mappings()
            .all()
        )
        grouped: dict[str, list[PriorAssessmentFact]] = {}
        for row in rows:
            grouped.setdefault(row["rent_expectation_id"], []).append(
                PriorAssessmentFact(
                    occurrence_number=row["occurrence_number"],
                    accrual_starts_on=row["accrual_starts_on"],
                    accrual_ends_on=row["accrual_ends_on"],
                    accrual_days=row["accrual_days"],
                    assessed_amount_minor=row["assessed_amount_minor"],
                )
            )
        return {key: tuple(value) for key, value in grouped.items()}

    def scheduled_prepaid_checks_for_expectations(self, expectation_ids):
        ids = set(expectation_ids)
        if not ids:
            return {}
        rows = (
            self.connection.execute(
                select(
                    PrepaidCheckModel.id,
                    PrepaidCheckModel.expectation_id,
                    PrepaidCheckModel.check_dated_on,
                    PrepaidCheckModel.amount_minor,
                )
                .where(
                    PrepaidCheckModel.expectation_id.in_(ids),
                    PrepaidCheckModel.status == "scheduled",
                )
                .order_by(
                    PrepaidCheckModel.expectation_id,
                    PrepaidCheckModel.check_dated_on,
                    PrepaidCheckModel.id,
                )
            )
            .mappings()
            .all()
        )
        grouped: dict[str, list[ScheduledPrepaidCheckWarning]] = {}
        for row in rows:
            grouped.setdefault(row["expectation_id"], []).append(
                ScheduledPrepaidCheckWarning(
                    check_id=row["id"],
                    check_dated_on=row["check_dated_on"],
                    amount_minor=row["amount_minor"],
                )
            )
        return {key: tuple(value) for key, value in grouped.items()}

    def pending_payments_for_expectations(self, expectation_ids):
        ids = set(expectation_ids)
        if not ids:
            return {}
        return self.pending_payment_reader.processing_for_expectations(self.connection, ids)

    def late_fee_policies(self, lease_id):
        rows = (
            self.connection.execute(
                LateFeePolicyVersionModel.__table__.select()
                .where(LateFeePolicyVersionModel.lease_id == lease_id)
                .order_by(LateFeePolicyVersionModel.version_number.desc())
            )
            .mappings()
            .all()
        )
        return [LateFeePolicyVersion(**dict(row)) for row in rows]

    def late_fee_policy(self, lease_id, policy_version_id):
        row = (
            self.connection.execute(
                LateFeePolicyVersionModel.__table__.select().where(
                    LateFeePolicyVersionModel.lease_id == lease_id,
                    LateFeePolicyVersionModel.id == policy_version_id,
                )
            )
            .mappings()
            .first()
        )
        return LateFeePolicyVersion(**dict(row)) if row else None

    def insert_late_fee_policy(self, policy: LateFeePolicyVersion):
        self.connection.execute(
            LateFeePolicyVersionModel.__table__.insert().values(
                id=policy.id,
                lease_id=policy.lease_id,
                lease_term_id=policy.lease_term_id,
                version_number=policy.version_number,
                effective_on=policy.effective_on,
                ends_on=policy.ends_on,
                rule_basis=policy.rule_basis,
                grace_period_days=policy.grace_period_days,
                calculation_basis=policy.calculation_basis,
                formula_kind=policy.formula_kind,
                flat_amount_minor=policy.flat_amount_minor,
                percentage_bps=policy.percentage_bps,
                daily_amount_minor=policy.daily_amount_minor,
                max_accrual_days=policy.max_accrual_days,
                per_period_cap_minor=policy.per_period_cap_minor,
                per_period_min_minor=policy.per_period_min_minor,
                minimum_unpaid_threshold_minor=policy.minimum_unpaid_threshold_minor,
                rounding_mode=policy.rounding_mode,
                applies_to_prorated_periods=int(policy.applies_to_prorated_periods),
                status=policy.status,
                supersedes_policy_version_id=policy.supersedes_policy_version_id,
                notes=policy.notes,
                operator_confirmed_at=policy.operator_confirmed_at,
                operator_confirmed_by_actor=policy.operator_confirmed_by_actor,
                voided_at=policy.voided_at,
                void_reason=policy.void_reason,
                created_at=policy.created_at,
            )
        )

    def supersede_late_fee_policy(self, policy: LateFeePolicyVersion):
        self.connection.execute(
            LateFeePolicyVersionModel.__table__.update()
            .where(LateFeePolicyVersionModel.id == policy.id)
            .values(status=policy.status, ends_on=policy.ends_on)
        )

    def void_late_fee_policy(self, policy: LateFeePolicyVersion):
        self.connection.execute(
            LateFeePolicyVersionModel.__table__.update()
            .where(LateFeePolicyVersionModel.id == policy.id)
            .values(
                status=policy.status,
                voided_at=policy.voided_at,
                void_reason=policy.void_reason,
            )
        )

    def late_fee_policy_has_active_assessments(self, policy_version_id: str) -> bool:
        return (
            self.connection.execute(
                select(LateFeeAssessmentModel.id)
                .where(
                    LateFeeAssessmentModel.policy_version_id == policy_version_id,
                    LateFeeAssessmentModel.voided_at.is_(None),
                )
                .limit(1)
            ).first()
            is not None
        )

    def expectation_has_active_late_fees(self, expectation_id: str) -> bool:
        return (
            self.connection.execute(
                select(LateFeeAssessmentModel.id)
                .where(
                    LateFeeAssessmentModel.rent_expectation_id == expectation_id,
                    LateFeeAssessmentModel.voided_at.is_(None),
                )
                .limit(1)
            ).first()
            is not None
        )

    def late_fee_assessment(self, assessment_id: str) -> LateFeeAssessment | None:
        row = (
            self.connection.execute(
                LateFeeAssessmentModel.__table__.select().where(
                    LateFeeAssessmentModel.id == assessment_id
                )
            )
            .mappings()
            .first()
        )
        return LateFeeAssessment(**dict(row)) if row else None

    def late_fee_assessment_replaced_by(self, assessment_id: str) -> str | None:
        return self.connection.execute(
            select(LateFeeAssessmentModel.id)
            .where(LateFeeAssessmentModel.replaces_assessment_id == assessment_id)
            .limit(1)
        ).scalar_one_or_none()

    def late_fee_assessments_replaced_by_map(self, assessment_ids) -> dict[str, str]:
        ids = set(assessment_ids)
        if not ids:
            return {}
        rows = self.connection.execute(
            select(
                LateFeeAssessmentModel.replaces_assessment_id,
                LateFeeAssessmentModel.id,
            ).where(LateFeeAssessmentModel.replaces_assessment_id.in_(ids))
        ).all()
        return {old_id: new_id for old_id, new_id in rows if old_id is not None}

    def insert_late_fee_assessment(self, item: LateFeeAssessment) -> None:
        self.connection.execute(
            LateFeeAssessmentModel.__table__.insert().values(
                id=item.id,
                lease_id=item.lease_id,
                rent_expectation_id=item.rent_expectation_id,
                policy_version_id=item.policy_version_id,
                occurrence_number=item.occurrence_number,
                as_of_date=item.as_of_date,
                accrual_starts_on=item.accrual_starts_on,
                accrual_ends_on=item.accrual_ends_on,
                accrual_days=item.accrual_days,
                assessed_amount_minor=item.assessed_amount_minor,
                currency_code=item.currency_code,
                time_zone=item.time_zone,
                rule_basis_snapshot=item.rule_basis_snapshot,
                calculation_snapshot_json=item.calculation_snapshot_json,
                calculation_snapshot_hash=item.calculation_snapshot_hash,
                processing_acknowledged=int(item.processing_acknowledged),
                processing_acknowledgment_reason=item.processing_acknowledgment_reason,
                internal_notes=item.internal_notes,
                replaces_assessment_id=item.replaces_assessment_id,
                voided_at=item.voided_at,
                void_reason=item.void_reason,
                assessed_at=item.assessed_at,
                assessed_by_actor=item.assessed_by_actor,
            )
        )

    def void_late_fee_assessment(self, item: LateFeeAssessment) -> None:
        self.connection.execute(
            LateFeeAssessmentModel.__table__.update()
            .where(LateFeeAssessmentModel.id == item.id)
            .values(voided_at=item.voided_at, void_reason=item.void_reason)
        )

    def insert_late_fee_waiver(self, waiver: LateFeeWaiver) -> None:
        self.connection.execute(
            LateFeeWaiverModel.__table__.insert().values(
                id=waiver.id,
                assessment_id=waiver.assessment_id,
                lease_id=waiver.lease_id,
                waived_amount_minor=waiver.waived_amount_minor,
                currency_code=waiver.currency_code,
                reason=waiver.reason,
                internal_notes=waiver.internal_notes,
                waived_on=waiver.waived_on,
                waived_at=waiver.waived_at,
                waived_by_actor=waiver.waived_by_actor,
            )
        )

    def late_fee_waivers_for_assessment(self, assessment_id: str) -> list[LateFeeWaiver]:
        rows = (
            self.connection.execute(
                LateFeeWaiverModel.__table__.select()
                .where(LateFeeWaiverModel.assessment_id == assessment_id)
                .order_by(LateFeeWaiverModel.waived_at, LateFeeWaiverModel.id)
            )
            .mappings()
            .all()
        )
        return [LateFeeWaiver(**dict(row)) for row in rows]

    def late_fee_waiver_totals(self, assessment_ids) -> dict[str, int]:
        ids = set(assessment_ids)
        if not ids:
            return {}
        rows = self.connection.execute(
            select(
                LateFeeWaiverModel.assessment_id,
                func.sum(LateFeeWaiverModel.waived_amount_minor),
            )
            .where(LateFeeWaiverModel.assessment_id.in_(ids))
            .group_by(LateFeeWaiverModel.assessment_id)
        ).all()
        return {assessment_id: int(total) for assessment_id, total in rows}

    def late_fee_paid_totals(self, assessment_ids) -> dict[str, int]:
        ids = set(assessment_ids)
        if not ids:
            return {}
        rows = self.connection.execute(
            select(
                LateFeeReceiptAllocationModel.assessment_id,
                func.sum(LateFeeReceiptAllocationModel.amount_minor),
            )
            .join(
                LateFeeReceiptModel,
                LateFeeReceiptModel.id == LateFeeReceiptAllocationModel.receipt_id,
            )
            .where(
                LateFeeReceiptAllocationModel.assessment_id.in_(ids),
                LateFeeReceiptModel.voided_at.is_(None),
            )
            .group_by(LateFeeReceiptAllocationModel.assessment_id)
        ).all()
        return {assessment_id: int(total) for assessment_id, total in rows}

    def late_fee_allocations_for_assessment(self, assessment_id: str) -> list[dict[str, object]]:
        rows = (
            self.connection.execute(
                select(
                    LateFeeReceiptAllocationModel.id.label("allocationId"),
                    LateFeeReceiptAllocationModel.receipt_id.label("receiptId"),
                    LateFeeReceiptModel.received_on.label("receivedOn"),
                    LateFeeReceiptAllocationModel.amount_minor.label("amountMinor"),
                    LateFeeReceiptModel.voided_at.label("voidedAt"),
                )
                .join(
                    LateFeeReceiptModel,
                    LateFeeReceiptModel.id == LateFeeReceiptAllocationModel.receipt_id,
                )
                .where(LateFeeReceiptAllocationModel.assessment_id == assessment_id)
                .order_by(LateFeeReceiptModel.received_on, LateFeeReceiptAllocationModel.id)
            )
            .mappings()
            .all()
        )
        return [
            {
                "allocationId": row["allocationId"],
                "receiptId": row["receiptId"],
                "receivedOn": row["receivedOn"],
                "amountMinor": int(row["amountMinor"]),
                "receiptLifecycleStatus": "voided" if row["voidedAt"] is not None else "active",
            }
            for row in rows
        ]

    def pending_payments_for_assessments(self, assessment_ids):
        ids = set(assessment_ids)
        if not ids:
            return {}
        return self.pending_payment_reader.processing_for_assessments(self.connection, ids)

    def lease_ids_for_property(self, property_id: str) -> list[str]:
        space_ids = self.portfolio_operations.space_ids_for_property(self.connection, property_id)
        if not space_ids:
            return []
        from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel

        return list(
            self.connection.execute(
                select(LeaseModel.id).where(LeaseModel.space_id.in_(space_ids))
            ).scalars()
        )

    def expectation_lease_id(self, expectation_id: str) -> str | None:
        return self.connection.execute(
            select(RentExpectationModel.lease_id).where(RentExpectationModel.id == expectation_id)
        ).scalar_one_or_none()

    def rent_receipt_lineage_allocations_by_expectation(
        self, lease_id: str, expectation_ids: list[str]
    ) -> dict[str, list[tuple[str, str, int, bool]]]:
        ids = set(expectation_ids)
        if not ids:
            return {}
        receipt_rows = self.connection.execute(
            select(RentReceiptModel.id, RentReceiptModel.replaces_receipt_id).where(
                RentReceiptModel.lease_id == lease_id
            )
        ).all()
        parent_by_receipt = {receipt_id: parent_id for receipt_id, parent_id in receipt_rows}

        def _chain_root(receipt_id: str) -> str:
            current = receipt_id
            seen: set[str] = set()
            while current not in seen:
                seen.add(current)
                parent = parent_by_receipt.get(current)
                if parent is None:
                    return current
                current = parent
            return current

        rows = self.connection.execute(
            select(
                RentReceiptAllocationModel.expectation_id,
                RentReceiptModel.id,
                RentReceiptModel.received_on,
                RentReceiptAllocationModel.amount_minor,
                RentReceiptModel.voided_at,
            )
            .join(RentReceiptModel, RentReceiptModel.id == RentReceiptAllocationModel.receipt_id)
            .where(RentReceiptAllocationModel.expectation_id.in_(ids))
        ).all()
        grouped: dict[str, list[tuple[str, str, int, bool]]] = {}
        for exp_id, receipt_id, received_on, amount_minor, voided_at in rows:
            grouped.setdefault(exp_id, []).append(
                (_chain_root(receipt_id), received_on, int(amount_minor), voided_at is not None)
            )
        return grouped

    def active_lease_late_fee_waiver(self, lease_id: str) -> LateFeeLeaseWaiver | None:
        row = (
            self.connection.execute(
                LateFeeLeaseWaiverModel.__table__.select().where(
                    LateFeeLeaseWaiverModel.lease_id == lease_id,
                    LateFeeLeaseWaiverModel.status == "active",
                )
            )
            .mappings()
            .first()
        )
        return LateFeeLeaseWaiver(**dict(row)) if row else None

    def lease_late_fee_waivers(self, lease_id: str) -> list[LateFeeLeaseWaiver]:
        rows = (
            self.connection.execute(
                LateFeeLeaseWaiverModel.__table__.select()
                .where(LateFeeLeaseWaiverModel.lease_id == lease_id)
                .order_by(
                    LateFeeLeaseWaiverModel.waived_at.desc(), LateFeeLeaseWaiverModel.id.desc()
                )
            )
            .mappings()
            .all()
        )
        return [LateFeeLeaseWaiver(**dict(row)) for row in rows]

    def insert_lease_late_fee_waiver(self, item: LateFeeLeaseWaiver) -> None:
        self.connection.execute(
            LateFeeLeaseWaiverModel.__table__.insert().values(
                id=item.id,
                lease_id=item.lease_id,
                status=item.status,
                reason=item.reason,
                internal_notes=item.internal_notes,
                waived_at=item.waived_at,
                waived_by_actor=item.waived_by_actor,
                waived_open_assessments_count=item.waived_open_assessments_count,
                revoked_at=item.revoked_at,
                revoked_by_actor=item.revoked_by_actor,
                revoke_reason=item.revoke_reason,
            )
        )

    def revoke_lease_late_fee_waiver(self, item: LateFeeLeaseWaiver) -> None:
        self.connection.execute(
            LateFeeLeaseWaiverModel.__table__.update()
            .where(LateFeeLeaseWaiverModel.id == item.id)
            .values(
                status=item.status,
                revoked_at=item.revoked_at,
                revoked_by_actor=item.revoked_by_actor,
                revoke_reason=item.revoke_reason,
            )
        )

    def leases_with_active_late_fee_policies(
        self, *, lease_id: str | None = None, property_id: str | None = None
    ) -> list[str]:
        active_waiver_leases = select(LateFeeLeaseWaiverModel.lease_id).where(
            LateFeeLeaseWaiverModel.status == "active"
        )
        query = (
            select(LateFeePolicyVersionModel.lease_id)
            .distinct()
            .where(
                LateFeePolicyVersionModel.status == "active",
                LateFeePolicyVersionModel.lease_id.not_in(active_waiver_leases),
            )
        )
        if lease_id is not None:
            query = query.where(LateFeePolicyVersionModel.lease_id == lease_id)
        elif property_id is not None:
            prop_leases = self.lease_ids_for_property(property_id)
            if not prop_leases:
                return []
            query = query.where(LateFeePolicyVersionModel.lease_id.in_(prop_leases))
        return list(self.connection.execute(query).scalars().all())

    def active_late_fee_assessments_for_lease(self, lease_id: str) -> list[LateFeeAssessment]:
        rows = (
            self.connection.execute(
                LateFeeAssessmentModel.__table__.select()
                .where(
                    LateFeeAssessmentModel.lease_id == lease_id,
                    LateFeeAssessmentModel.voided_at.is_(None),
                )
                .order_by(
                    LateFeeAssessmentModel.as_of_date,
                    LateFeeAssessmentModel.occurrence_number,
                    LateFeeAssessmentModel.id,
                )
            )
            .mappings()
            .all()
        )
        return [LateFeeAssessment(**dict(row)) for row in rows]

    def late_fee_assessments_for_expectations_all(
        self, expectation_ids: list[str]
    ) -> dict[str, list[LateFeeAssessment]]:
        ids = set(expectation_ids)
        if not ids:
            return {}
        rows = (
            self.connection.execute(
                LateFeeAssessmentModel.__table__.select()
                .where(LateFeeAssessmentModel.rent_expectation_id.in_(ids))
                .order_by(
                    LateFeeAssessmentModel.rent_expectation_id,
                    LateFeeAssessmentModel.occurrence_number,
                    LateFeeAssessmentModel.assessed_at,
                )
            )
            .mappings()
            .all()
        )
        grouped: dict[str, list[LateFeeAssessment]] = {}
        for row in rows:
            item = LateFeeAssessment(**dict(row))
            grouped.setdefault(item.rent_expectation_id, []).append(item)
        return grouped

    def late_fee_assessment_page(
        self,
        *,
        lease_id: str | None,
        lease_ids: list[str] | None,
        rent_expectation_id: str | None = None,
        settlement_status: str | None = None,
        include_voided: bool,
        cursor: tuple[str, str] | None,
        limit: int,
    ) -> list[LateFeeAssessment]:
        query = select(LateFeeAssessmentModel.__table__)
        if lease_id is not None:
            query = query.where(LateFeeAssessmentModel.lease_id == lease_id)
        if lease_ids is not None:
            if not lease_ids:
                return []
            query = query.where(LateFeeAssessmentModel.lease_id.in_(lease_ids))
        if rent_expectation_id is not None:
            query = query.where(LateFeeAssessmentModel.rent_expectation_id == rent_expectation_id)
        if settlement_status == "voided":
            query = query.where(LateFeeAssessmentModel.voided_at.is_not(None))
        elif settlement_status is not None:
            waived_subq = (
                select(
                    LateFeeWaiverModel.assessment_id.label("assessment_id"),
                    func.sum(LateFeeWaiverModel.waived_amount_minor).label("waived_minor"),
                )
                .group_by(LateFeeWaiverModel.assessment_id)
                .subquery()
            )
            paid_subq = (
                select(
                    LateFeeReceiptAllocationModel.assessment_id.label("assessment_id"),
                    func.sum(LateFeeReceiptAllocationModel.amount_minor).label("paid_minor"),
                )
                .join(
                    LateFeeReceiptModel,
                    LateFeeReceiptModel.id == LateFeeReceiptAllocationModel.receipt_id,
                )
                .where(LateFeeReceiptModel.voided_at.is_(None))
                .group_by(LateFeeReceiptAllocationModel.assessment_id)
                .subquery()
            )
            waived_expr = func.coalesce(waived_subq.c.waived_minor, 0)
            paid_expr = func.coalesce(paid_subq.c.paid_minor, 0)
            remaining_expr = LateFeeAssessmentModel.assessed_amount_minor - waived_expr - paid_expr
            query = (
                query.outerjoin(
                    waived_subq, waived_subq.c.assessment_id == LateFeeAssessmentModel.id
                )
                .outerjoin(paid_subq, paid_subq.c.assessment_id == LateFeeAssessmentModel.id)
                .where(LateFeeAssessmentModel.voided_at.is_(None))
            )
            if settlement_status == "waived":
                query = query.where(remaining_expr <= 0, paid_expr == 0, waived_expr > 0)
            elif settlement_status == "paid":
                query = query.where(remaining_expr <= 0, paid_expr > 0)
            elif settlement_status == "partially_paid":
                query = query.where(remaining_expr > 0, or_(paid_expr > 0, waived_expr > 0))
            elif settlement_status == "unpaid":
                query = query.where(remaining_expr > 0, paid_expr == 0, waived_expr == 0)
        elif not include_voided:
            query = query.where(LateFeeAssessmentModel.voided_at.is_(None))
        if cursor is not None:
            query = query.where(
                or_(
                    LateFeeAssessmentModel.as_of_date < cursor[0],
                    and_(
                        LateFeeAssessmentModel.as_of_date == cursor[0],
                        LateFeeAssessmentModel.id < cursor[1],
                    ),
                )
            )
        query = query.order_by(
            LateFeeAssessmentModel.as_of_date.desc(), LateFeeAssessmentModel.id.desc()
        ).limit(limit)
        return [
            LateFeeAssessment(**dict(row))
            for row in self.connection.execute(query).mappings().all()
        ]

    def late_fee_receipt(self, receipt_id: str) -> LateFeeReceipt | None:
        row = (
            self.connection.execute(
                LateFeeReceiptModel.__table__.select().where(LateFeeReceiptModel.id == receipt_id)
            )
            .mappings()
            .first()
        )
        return LateFeeReceipt(**dict(row)) if row else None

    def late_fee_receipt_replacement_exists(self, receipt_id: str) -> bool:
        return self.late_fee_receipt_replaced_by(receipt_id) is not None

    def late_fee_receipt_replaced_by(self, receipt_id: str) -> str | None:
        return self.connection.execute(
            select(LateFeeReceiptModel.id)
            .where(LateFeeReceiptModel.replaces_receipt_id == receipt_id)
            .limit(1)
        ).scalar_one_or_none()

    def insert_late_fee_receipt(self, receipt: LateFeeReceipt) -> None:
        self.connection.execute(LateFeeReceiptModel.__table__.insert().values(**receipt.__dict__))

    def void_late_fee_receipt(self, receipt: LateFeeReceipt) -> None:
        self.connection.execute(
            LateFeeReceiptModel.__table__.update()
            .where(LateFeeReceiptModel.id == receipt.id)
            .values(voided_at=receipt.voided_at, void_reason=receipt.void_reason)
        )

    def insert_late_fee_receipt_allocation(self, row: dict[str, object]) -> None:
        self.connection.execute(LateFeeReceiptAllocationModel.__table__.insert().values(**row))

    def late_fee_receipt_allocations_for_receipt(self, receipt_id: str) -> list[dict[str, object]]:
        rows = (
            self.connection.execute(
                LateFeeReceiptAllocationModel.__table__.select()
                .where(LateFeeReceiptAllocationModel.receipt_id == receipt_id)
                .order_by(
                    LateFeeReceiptAllocationModel.created_at, LateFeeReceiptAllocationModel.id
                )
            )
            .mappings()
            .all()
        )
        return [
            {
                "id": row["id"],
                "receiptId": row["receipt_id"],
                "assessmentId": row["assessment_id"],
                "amountMinor": int(row["amount_minor"]),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def record_change(self, **change):
        self.recorder.record_change(self.connection.connection.driver_connection, **change)

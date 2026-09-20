"""SQLite implementation of FIN-002's transaction boundary."""

from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.finance.application.expense_ports import (
    ExpenseTransaction,
    PartyExpenseOperations,
    ProviderExpenseOperations,
)
from app.modules.files.application.ports import FileLinkReader, FileLinkWithFile
from app.modules.portfolio.application.ports import PortfolioContextReader
from app.modules.finance.domain.expense_models import Expense, ExpenseCategory, ExpenseRefund
from app.modules.finance.domain.models import FinanceConflictError
from app.modules.finance.infrastructure.sqlalchemy_models import (
    ExpenseCategoryModel,
    ExpenseModel,
    ExpenseRefundModel,
)
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction


class SQLiteExpenseUnitOfWork:
    def __init__(self, database, recorder: AuditRecorder, portfolio: PortfolioContextReader,
                 providers: ProviderExpenseOperations, parties: PartyExpenseOperations,
                 files: FileLinkReader) -> None:
        self.engine = create_sqlite_engine(database)
        self.recorder = recorder
        self.portfolio = portfolio
        self.providers = providers
        self.parties = parties
        self.files = files

    def write(self, operation):
        try:
            with immediate_transaction(self.engine) as connection:
                return operation(_Transaction(
                    connection, self.recorder, self.portfolio,
                    self.providers, self.parties, self.files,
                ))
        except (IntegrityError, OperationalError) as error:
            raise FinanceConflictError(
                "The expense changed concurrently or conflicts with an existing record."
            ) from error

    def read(self, operation):
        with self.engine.connect() as connection:
            return operation(_Transaction(
                connection, self.recorder, self.portfolio,
                self.providers, self.parties, self.files,
            ))


class _Transaction:
    def __init__(self, connection, recorder, portfolio, providers, parties, files) -> None:
        self.connection = connection
        self.recorder = recorder
        self.portfolio = portfolio
        self.providers = providers
        self.parties = parties
        self.files = files

    def category(self, record_id):
        return _one(self.connection, ExpenseCategoryModel, record_id, ExpenseCategory)

    def categories(self, include_archived):
        query = ExpenseCategoryModel.__table__.select()
        if not include_archived:
            query = query.where(ExpenseCategoryModel.archived_at.is_(None))
        rows = self.connection.execute(query.order_by(
            ExpenseCategoryModel.display_order, ExpenseCategoryModel.display_name,
        )).mappings()
        return [ExpenseCategory(**dict(row)) for row in rows]

    def category_by_name(self, normalized_name):
        row = self.connection.execute(
            ExpenseCategoryModel.__table__.select().where(
                ExpenseCategoryModel.normalized_name == normalized_name,
                ExpenseCategoryModel.archived_at.is_(None),
            )
        ).mappings().first()
        return ExpenseCategory(**dict(row)) if row else None

    def insert_category(self, item):
        self.connection.execute(ExpenseCategoryModel.__table__.insert().values(**item.__dict__))

    def replace_category(self, item):
        self.connection.execute(ExpenseCategoryModel.__table__.update().where(
            ExpenseCategoryModel.id == item.id
        ).values(**item.__dict__))

    def expense(self, record_id):
        return _one(self.connection, ExpenseModel, record_id, Expense)

    def expense_by_key(self, key):
        row = self.connection.execute(ExpenseModel.__table__.select().where(
            ExpenseModel.idempotency_key == key
        )).mappings().first()
        return Expense(**dict(row)) if row else None

    def expenses(self, **filters):
        query = ExpenseModel.__table__.select()
        for key in ("property_id", "space_id", "category_id", "provider_party_id", "paid_by_kind", "paid_by_party_id"):
            if filters.get(key) is not None:
                query = query.where(getattr(ExpenseModel, key) == filters[key])
        if filters.get("paid_from") is not None:
            query = query.where(ExpenseModel.paid_on >= filters["paid_from"])
        if filters.get("paid_to") is not None:
            query = query.where(ExpenseModel.paid_on <= filters["paid_to"])
        if not filters.get("include_voided", False):
            query = query.where(ExpenseModel.voided_at.is_(None))
        has_evidence = filters.get("has_evidence")
        if has_evidence is not None:
            evidence_ids = self.files.entity_ids_with_active_links(self.connection, "expense")
            query = query.where(
                ExpenseModel.id.in_(evidence_ids) if has_evidence
                else ExpenseModel.id.not_in(evidence_ids)
            )
        cursor = filters.get("cursor")
        if cursor:
            query = query.where(or_(
                ExpenseModel.paid_on < cursor[0],
                and_(ExpenseModel.paid_on == cursor[0], ExpenseModel.id < cursor[1]),
            ))
        query = query.order_by(ExpenseModel.paid_on.desc(), ExpenseModel.id.desc()).limit(filters.get("limit", 101))
        return [Expense(**dict(row)) for row in self.connection.execute(query).mappings()]

    def duplicate_expenses(self, item):
        query = ExpenseModel.__table__.select().where(
            ExpenseModel.property_id == item.property_id,
            ExpenseModel.paid_on == item.paid_on,
            ExpenseModel.amount_minor == item.amount_minor,
            ExpenseModel.currency_code == item.currency_code,
            ExpenseModel.voided_at.is_(None),
        ).order_by(ExpenseModel.created_at, ExpenseModel.id)
        return [Expense(**dict(row)) for row in self.connection.execute(query).mappings()]

    def expense_projection(self, expenses):
        if not expenses:
            return {
                "categories": {},
                "contexts": {},
                "providers": {},
                "refunds": {},
                "evidence": {},
                "correction_chains": {},
            }
        expense_ids = [item.id for item in expenses]
        category_ids = {item.category_id for item in expenses}
        provider_ids = {
            item.provider_party_id
            for item in expenses
            if item.provider_party_id is not None
        }
        categories = {
            row["id"]: ExpenseCategory(**dict(row))
            for row in self.connection.execute(
                ExpenseCategoryModel.__table__.select().where(
                    ExpenseCategoryModel.id.in_(category_ids)
                )
            ).mappings()
        }
        refunds = {expense_id: [] for expense_id in expense_ids}
        for row in self.connection.execute(
            ExpenseRefundModel.__table__.select().where(
                ExpenseRefundModel.expense_id.in_(expense_ids)
            ).order_by(
                ExpenseRefundModel.expense_id,
                ExpenseRefundModel.received_on,
                ExpenseRefundModel.id,
            )
        ).mappings():
            item = ExpenseRefund(**dict(row))
            refunds[item.expense_id].append(item)
        correction_rows = self._connected_correction_rows(expenses)
        portfolio_contexts = self.portfolio.contexts_for_property_spaces(
            self.connection, {(item.property_id, item.space_id) for item in expenses}
        )
        return {
            "categories": categories,
            "contexts": {
                item.id: _expense_context_view(context)
                for item in expenses
                if (context := portfolio_contexts.get((item.property_id, item.space_id))) is not None
            },
            "providers": self.providers.expense_providers(
                self.connection, list(provider_ids)
            ),
            "refunds": refunds,
            "evidence": {
                expense_id: [_expense_evidence_view(link) for link in links]
                for expense_id, links in self.files.links_for_entities(
                    self.connection, "expense", expense_ids
                ).items()
            },
            "correction_chains": {
                expense_id: _correction_chain(
                    correction_rows, expense_id, "replaces_expense_id"
                )
                for expense_id in expense_ids
            },
        }

    def _connected_correction_rows(self, expenses):
        """Load only the ancestor/descendant components for this result page."""
        rows_by_id = {item.id: item for item in expenses}
        parent_frontier = {
            item.replaces_expense_id
            for item in expenses
            if item.replaces_expense_id is not None
        }
        while parent_frontier:
            next_frontier = set()
            for ids in _chunks(parent_frontier):
                for row in self.connection.execute(
                    ExpenseModel.__table__.select().where(ExpenseModel.id.in_(ids))
                ).mappings():
                    item = Expense(**dict(row))
                    if item.id in rows_by_id:
                        continue
                    rows_by_id[item.id] = item
                    if item.replaces_expense_id is not None:
                        next_frontier.add(item.replaces_expense_id)
            parent_frontier = next_frontier - rows_by_id.keys()

        child_frontier = set(rows_by_id)
        while child_frontier:
            next_frontier = set()
            for ids in _chunks(child_frontier):
                for row in self.connection.execute(
                    ExpenseModel.__table__.select().where(
                        ExpenseModel.replaces_expense_id.in_(ids)
                    )
                ).mappings():
                    item = Expense(**dict(row))
                    if item.id in rows_by_id:
                        continue
                    rows_by_id[item.id] = item
                    next_frontier.add(item.id)
            child_frontier = next_frontier
        return list(rows_by_id.values())

    def replacement_expense_exists(self, record_id):
        return self.connection.execute(select(ExpenseModel.id).where(
            ExpenseModel.replaces_expense_id == record_id
        ).limit(1)).first() is not None

    def insert_expense(self, item):
        self.connection.execute(ExpenseModel.__table__.insert().values(**item.__dict__))

    def replace_expense(self, item):
        self.connection.execute(ExpenseModel.__table__.update().where(
            ExpenseModel.id == item.id
        ).values(**item.__dict__))

    def refund(self, record_id):
        return _one(self.connection, ExpenseRefundModel, record_id, ExpenseRefund)

    def refund_by_key(self, key):
        row = self.connection.execute(ExpenseRefundModel.__table__.select().where(
            ExpenseRefundModel.idempotency_key == key
        )).mappings().first()
        return ExpenseRefund(**dict(row)) if row else None

    def refunds(self, expense_id):
        rows = self.connection.execute(ExpenseRefundModel.__table__.select().where(
            ExpenseRefundModel.expense_id == expense_id
        ).order_by(ExpenseRefundModel.received_on, ExpenseRefundModel.id)).mappings()
        return [ExpenseRefund(**dict(row)) for row in rows]

    def replacement_refund_exists(self, record_id):
        return self.connection.execute(select(ExpenseRefundModel.id).where(
            ExpenseRefundModel.replaces_refund_id == record_id
        ).limit(1)).first() is not None

    def insert_refund(self, item):
        self.connection.execute(ExpenseRefundModel.__table__.insert().values(**item.__dict__))

    def replace_refund(self, item):
        self.connection.execute(ExpenseRefundModel.__table__.update().where(
            ExpenseRefundModel.id == item.id
        ).values(**item.__dict__))

    def portfolio_context(self, property_id, space_id, paid_on):
        context = self.portfolio.context_for_property_space(self.connection, property_id, space_id)
        return None if context is None else _expense_context_view(context)

    def provider_context(self, party_id):
        return self.providers.expense_provider(self.connection, party_id)

    def party_exists(self, party_id):
        return self.parties.exists(self.connection, party_id)

    def party_owned_property_on(self, property_id, party_id, paid_on):
        return self.portfolio.party_owned_property_on(
            self.connection, property_id, party_id, paid_on
        )

    def record_change(self, **change):
        self.recorder.record_change(self.connection.connection.driver_connection, **change)


def _one(connection, model, record_id, domain):
    row = connection.execute(model.__table__.select().where(model.id == record_id)).mappings().first()
    return domain(**dict(row)) if row else None


def _expense_evidence_view(link: FileLinkWithFile) -> dict[str, object]:
    return {
        "linkId": link.id,
        "fileId": link.file_id,
        "originalName": link.original_name,
        "mediaType": link.media_type,
        "sizeBytes": link.size_bytes,
        "contentSha256": link.content_sha256,
        "purpose": link.purpose,
        "createdAt": link.created_at,
        "archivedAt": link.archived_at,
        "archiveReason": link.archive_reason,
    }


def _expense_context_view(context: dict[str, object]) -> dict[str, object]:
    return {
        "propertyId": context["property_id"],
        "propertyName": context["property_display_name"],
        "propertyArchived": context["property_status"] == "archived",
        "timeZone": context["time_zone"],
        "spaceId": context["space_id"],
        "spaceName": context["space_display_name"],
        "spaceArchived": False if context["space_status"] is None else context["space_status"] == "archived",
    }


def _chunks(values, size=500):
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _correction_chain(rows, record_id, replacement_field):
    by_id = {row.id: row for row in rows}
    current = by_id.get(record_id)
    if current is None:
        return []
    seen = {current.id}
    before = []
    while (parent_id := getattr(current, replacement_field)) is not None:
        current = by_id.get(parent_id)
        if current is None or current.id in seen:
            break
        seen.add(current.id)
        before.append(current)
    chain = list(reversed(before))
    current = by_id[record_id]
    chain.append(current)
    while True:
        replacement = next(
            (row for row in rows if getattr(row, replacement_field) == current.id),
            None,
        )
        if replacement is None or replacement.id in seen:
            break
        seen.add(replacement.id)
        chain.append(replacement)
        current = replacement
    return chain

"""Set-based FIN-003 projections on one deferred SQLite snapshot.

All financial tables are owned here. Location joins are supplied through
source-owned relations; child totals are aggregated before joining accounts.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, event, func, literal, or_, select, union_all
from sqlalchemy.exc import DBAPIError

from app.modules.audit.application.read_marker import AuditReadMarker
from app.modules.finance.application.money_models import (
    AmountCount,
    Metric,
    MoneyBusy,
    MoneyNotFound,
    MoneyUnavailable,
    Scope,
)
from app.modules.finance.infrastructure.sqlalchemy_models import (
    ExpenseModel,
    ExpenseRefundModel,
    RentReceiptModel,
    SecurityDepositAccountModel,
    SecurityDepositReceiptModel,
    SecurityDepositRefundModel,
    SecurityDepositSettlementModel,
    SecurityDepositSettlementReceiptModel,
)
from app.modules.leases.application.location_ports import LeaseLocationRelation
from app.modules.portfolio.application.location_ports import PortfolioLocationRelations
from app.platform.sqlite_engine import create_sqlite_engine


class SQLiteMoneySummaryUnitOfWork:
    def __init__(
        self,
        database: Path,
        portfolio: PortfolioLocationRelations,
        leases: LeaseLocationRelation,
        marker: AuditReadMarker,
    ):
        self.engine = create_sqlite_engine(database)
        self.portfolio, self.leases, self.marker = portfolio, leases, marker

        @event.listens_for(self.engine, "connect")
        def local_dates(dbapi, _):
            dbapi.create_function("property_local_date", 2, _local_date, deterministic=True)

    def read(self, operation):
        try:
            with self.engine.connect() as connection, connection.begin():
                return operation(
                    SQLiteMoneyReadTransaction(
                        connection,
                        self.portfolio,
                        self.leases,
                        self.marker,
                    )
                )
        except DBAPIError as error:
            # No raw SQL, monetary facts, paths, or driver messages at the API.
            if "locked" in str(error.orig).lower() or "busy" in str(error.orig).lower():
                raise MoneyBusy("The workspace is busy. Retry the money view.") from error
            raise MoneyUnavailable("Recorded money could not be read safely.") from error


class SQLiteMoneyReadTransaction:
    def __init__(self, connection, portfolio, leases, marker, property_scope=None):
        self.connection, self.marker = connection, marker
        self.properties = portfolio.properties()
        self.locations = leases.locations()
        self.property_scope = property_scope

    def source_marker(self):
        return self.marker.marker(self.connection)

    def _scope(self, query):
        p = self.properties.c
        return and_(
            p.property_state == query.property_state
            if query.property_state != "all"
            else literal(True),
            p.property_id.in_(query.property_ids) if query.property_ids else literal(True),
            p.property_id.in_(select(self.property_scope.c.property_id))
            if self.property_scope is not None
            else literal(True),
        )

    def scope(self, query):
        p = self.properties.c
        row = (
            self.connection.execute(
                select(
                    func.count().label("all_count"),
                    func.coalesce(func.sum(case((self._scope(query), 1), else_=0)), 0).label(
                        "selected"
                    ),
                    func.coalesce(
                        func.sum(case((p.property_id.in_(query.property_ids), 1), else_=0)), 0
                    ).label("found"),
                ).select_from(self.properties)
            )
            .mappings()
            .one()
        )
        if query.property_ids and row["found"] != len(query.property_ids):
            raise MoneyNotFound("A selected property was not found.")
        return Scope(row["selected"], row["all_count"] - row["selected"])

    def validate_integrity(self):
        """Guard unresolved relationships and currency even in corrupted sources."""
        p, locations = self.properties, self.locations
        r, e, f = RentReceiptModel.__table__, ExpenseModel.__table__, ExpenseRefundModel.__table__
        a = SecurityDepositAccountModel.__table__
        dr, df, s = (
            SecurityDepositReceiptModel.__table__,
            SecurityDepositRefundModel.__table__,
            SecurityDepositSettlementModel.__table__,
        )
        tests = [
            select(r.c.id)
            .select_from(r.outerjoin(locations, r.c.lease_id == locations.c.lease_id))
            .where(or_(locations.c.property_id.is_(None), r.c.currency_code != "USD")),
            select(e.c.id)
            .select_from(e.outerjoin(p, e.c.property_id == p.c.property_id))
            .where(or_(p.c.property_id.is_(None), e.c.currency_code != "USD")),
            select(f.c.id)
            .select_from(f.outerjoin(e, f.c.expense_id == e.c.id))
            .where(or_(e.c.id.is_(None), f.c.currency_code != "USD")),
            select(a.c.id)
            .select_from(a.outerjoin(locations, a.c.lease_id == locations.c.lease_id))
            .where(
                or_(
                    locations.c.property_id.is_(None),
                    a.c.property_id != locations.c.property_id,
                    a.c.space_id != locations.c.space_id,
                    a.c.currency_code != "USD",
                )
            ),
            select(dr.c.id)
            .select_from(dr.outerjoin(a, dr.c.account_id == a.c.id))
            .where(or_(a.c.id.is_(None), dr.c.currency_code != "USD")),
            select(df.c.id)
            .select_from(
                df.outerjoin(a, df.c.account_id == a.c.id).outerjoin(
                    s,
                    df.c.authorized_by_settlement_id == s.c.id,
                )
            )
            .where(
                or_(
                    a.c.id.is_(None),
                    s.c.id.is_(None),
                    s.c.account_id != df.c.account_id,
                    df.c.currency_code != "USD",
                )
            ),
            select(s.c.id)
            .select_from(s.outerjoin(a, s.c.account_id == a.c.id))
            .where(a.c.id.is_(None)),
        ]
        if self.connection.execute(select(union_all(*tests).subquery().c.id).limit(1)).first():
            raise MoneyUnavailable("Recorded money has an invalid currency or retained location.")

    def _events(self):
        """One row per contribution, never per receipt allocation or line item."""
        p, locations = self.properties, self.locations
        r, e, f = RentReceiptModel.__table__, ExpenseModel.__table__, ExpenseRefundModel.__table__
        a, dr, df, s = (
            SecurityDepositAccountModel.__table__,
            SecurityDepositReceiptModel.__table__,
            SecurityDepositRefundModel.__table__,
            SecurityDepositSettlementModel.__table__,
        )

        def projection(kind, source, business_on, amount, location, **context):
            state = context.get("state", "active")
            return select(
                literal(kind).label("source_kind"),
                source.c.id.label("source_id"),
                location.c.property_id,
                business_on.label("business_on"),
                amount.label("amount_minor"),
                *(
                    (context[name] if context.get(name) is not None else literal(None)).label(
                        name + "_id"
                    )
                    for name in ("lease", "space", "account", "parent", "authorization", "party")
                ),
                (literal(state) if isinstance(state, str) else state).label("lifecycle"),
            )

        queries = [
            projection(
                "rent_receipt",
                r,
                r.c.received_on,
                r.c.amount_minor,
                locations,
                lease=r.c.lease_id,
                space=locations.c.space_id,
                party=r.c.received_by_party_id,
            )
            .select_from(r.join(locations, r.c.lease_id == locations.c.lease_id))
            .where(r.c.voided_at.is_(None)),
            projection(
                "expense",
                e,
                e.c.paid_on,
                e.c.amount_minor,
                p,
                space=e.c.space_id,
                party=e.c.paid_by_party_id,
            )
            .select_from(e.join(p, e.c.property_id == p.c.property_id))
            .where(e.c.voided_at.is_(None)),
            projection(
                "expense_refund",
                f,
                f.c.received_on,
                f.c.amount_minor,
                p,
                space=e.c.space_id,
                parent=f.c.expense_id,
            )
            .select_from(
                f.join(e, f.c.expense_id == e.c.id).join(p, e.c.property_id == p.c.property_id)
            )
            .where(f.c.voided_at.is_(None), e.c.voided_at.is_(None)),
            projection(
                "deposit_receipt",
                dr,
                dr.c.received_on,
                dr.c.amount_minor,
                p,
                lease=a.c.lease_id,
                space=a.c.space_id,
                account=a.c.id,
                party=dr.c.received_by_party_id,
            )
            .select_from(
                dr.join(a, dr.c.account_id == a.c.id).join(p, a.c.property_id == p.c.property_id)
            )
            .where(dr.c.voided_at.is_(None)),
            projection(
                "deposit_refund",
                df,
                df.c.paid_on,
                df.c.amount_minor,
                p,
                lease=a.c.lease_id,
                space=a.c.space_id,
                account=a.c.id,
                authorization=df.c.authorized_by_settlement_id,
                party=df.c.recipient_party_id,
            )
            .select_from(
                df.join(a, df.c.account_id == a.c.id).join(p, a.c.property_id == p.c.property_id)
            )
            .where(df.c.voided_at.is_(None)),
        ]
        for kind, timestamp, amount in (
            ("settlement_credit", s.c.approved_at, s.c.credit_total_minor),
            ("settlement_deduction", s.c.approved_at, s.c.deduction_total_minor),
            ("settlement_completed", s.c.completed_at, literal(0)),
        ):
            queries.append(
                projection(
                    kind,
                    s,
                    func.property_local_date(timestamp, p.c.time_zone),
                    amount,
                    p,
                    lease=a.c.lease_id,
                    space=a.c.space_id,
                    account=a.c.id,
                    state=s.c.status,
                )
                .select_from(
                    s.join(a, s.c.account_id == a.c.id).join(p, a.c.property_id == p.c.property_id)
                )
                .where(s.c.status.in_(("approved", "completed")), timestamp.is_not(None))
            )
        return union_all(*queries).cte("money_events")

    def _period(self, query):
        events = self._events()
        return (
            select(events)
            .select_from(
                events.join(
                    self.properties,
                    events.c.property_id == self.properties.c.property_id,
                )
            )
            .where(
                self._scope(query), events.c.business_on.between(query.from_on, query.through_on)
            )
            .cte("period_events")
        )

    def _period_group(self, query, *, by_property=False):
        events = self._period(query)
        columns = (
            [events.c.source_kind]
            if not by_property
            else [events.c.property_id, events.c.source_kind]
        )
        return select(
            *columns,
            func.sum(events.c.amount_minor).label("amount_minor"),
            func.count().label("record_count"),
        ).group_by(*columns)

    def period_totals(self, query):
        return {
            row["source_kind"]: AmountCount(row["amount_minor"], row["record_count"])
            for row in self.connection.execute(self._period_group(query)).mappings()
        }

    def _accounts(self, query):
        a, r, f, s, captured = (
            SecurityDepositAccountModel.__table__,
            SecurityDepositReceiptModel.__table__,
            SecurityDepositRefundModel.__table__,
            SecurityDepositSettlementModel.__table__,
            SecurityDepositSettlementReceiptModel.__table__,
        )
        receipts = (
            select(
                r.c.account_id,
                func.sum(r.c.amount_minor).label("receipts"),
                func.count().label("receipt_count"),
            )
            .where(r.c.voided_at.is_(None))
            .group_by(r.c.account_id)
            .subquery()
        )
        refunds = (
            select(
                f.c.account_id,
                func.sum(f.c.amount_minor).label("refunds"),
                func.count().label("refund_count"),
            )
            .where(f.c.voided_at.is_(None))
            .group_by(f.c.account_id)
            .subquery()
        )
        # Capture only active receipts belonging to the current approved decision.
        included = (
            select(s.c.account_id, func.sum(r.c.amount_minor).label("captured"))
            .select_from(
                s.join(captured, captured.c.settlement_id == s.c.id).join(
                    r, captured.c.receipt_id == r.c.id
                )
            )
            .where(s.c.status.in_(("approved", "completed")), r.c.voided_at.is_(None))
            .group_by(s.c.account_id)
            .subquery()
        )
        current = select(s).where(s.c.status != "voided").subquery()
        received, refunded = (
            func.coalesce(receipts.c.receipts, 0),
            func.coalesce(refunds.c.refunds, 0),
        )
        credit = func.coalesce(current.c.credit_total_minor, 0)
        deduction = func.coalesce(current.c.deduction_total_minor, 0)
        unsettled = received - func.coalesce(included.c.captured, 0)
        obligation = received + credit - deduction - refunded
        unresolved = case(
            (current.c.id.is_(None), or_(received != 0, refunded != 0)),
            (unsettled != 0, literal(True)),
            (current.c.status == "completed", refunded != current.c.refund_due_minor),
            else_=literal(True),
        )
        return (
            select(
                a.c.id.label("account_id"),
                a.c.property_id,
                a.c.lease_id,
                a.c.space_id,
                a.c.agreed_amount_minor,
                received.label("receipts"),
                refunded.label("refunds"),
                credit.label("credits"),
                deduction.label("deductions"),
                obligation.label("obligation"),
                unsettled.label("unsettled"),
                current.c.id.label("settlement_id"),
                current.c.status.label("settlement_status"),
                current.c.refund_due_minor,
                unresolved.label("unresolved"),
            )
            .select_from(
                a.join(self.properties, a.c.property_id == self.properties.c.property_id)
                .outerjoin(receipts, receipts.c.account_id == a.c.id)
                .outerjoin(refunds, refunds.c.account_id == a.c.id)
                .outerjoin(current, current.c.account_id == a.c.id)
                .outerjoin(included, included.c.account_id == a.c.id)
            )
            .where(self._scope(query))
            .cte("account_components")
        )

    def _obligation_group(self, query, *, by_property=False):
        a = self._accounts(query)
        columns = [a.c.property_id] if by_property else []
        return select(
            *columns,
            func.coalesce(func.sum(case((a.c.obligation > 0, a.c.obligation), else_=0)), 0).label(
                "positive"
            ),
            func.coalesce(func.sum(case((a.c.obligation < 0, a.c.obligation), else_=0)), 0).label(
                "negative"
            ),
            func.coalesce(func.sum(a.c.obligation), 0).label("net"),
            func.count().label("accounts"),
            func.coalesce(func.sum(case((a.c.obligation < 0, 1), else_=0)), 0).label(
                "negative_accounts"
            ),
            func.coalesce(func.sum(case((a.c.unresolved, 1), else_=0)), 0).label(
                "unresolved_accounts"
            ),
            *(
                func.coalesce(func.sum(a.c[name]), 0).label(name)
                for name in ("receipts", "refunds", "credits", "deductions")
            ),
        ).group_by(*columns)

    def obligation_totals(self, query):
        return self.connection.execute(self._obligation_group(query)).mappings().one()

    def property_page(self, query, after):
        p = self.properties.c
        sort_key = func.unicode_casefold(p.property_name)
        predicates = [self._scope(query)]
        if after:
            predicates.append(
                or_(sort_key > after[0], and_(sort_key == after[0], p.property_id > after[1]))
            )
        selected = (
            select(self.properties, sort_key.label("sort_key"))
            .where(*predicates)
            .order_by(sort_key, p.property_id)
            .limit(query.page_size + 1)
            .cte("selected_properties")
        )
        # Monetary grouping stays in SQL. Only bounded selected rows are returned.
        totals = self._period_group(query, by_property=True).subquery()
        period_columns = []
        for kind in EVENT_KINDS:
            period_columns.extend(
                (
                    func.coalesce(
                        func.max(case((totals.c.source_kind == kind, totals.c.amount_minor))), 0
                    ).label(kind),
                    func.coalesce(
                        func.max(case((totals.c.source_kind == kind, totals.c.record_count))), 0
                    ).label(kind + "_count"),
                )
            )
        period = (
            select(totals.c.property_id, *period_columns).group_by(totals.c.property_id).subquery()
        )
        obligations = self._obligation_group(query, by_property=True).subquery()
        statement = (
            select(
                selected,
                *(period.c[name] for name in period.c.keys() if name != "property_id"),
                *(obligations.c[name] for name in obligations.c.keys() if name != "property_id"),
            )
            .select_from(
                selected.outerjoin(
                    period, period.c.property_id == selected.c.property_id
                ).outerjoin(obligations, obligations.c.property_id == selected.c.property_id)
            )
            .order_by(selected.c.sort_key, selected.c.property_id)
        )
        return list(self.connection.execute(statement).mappings())

    def source_page(self, query, metric, after):
        events = self._events()
        signs = METRIC_SIGNS[metric]
        signed = case(
            *(
                (events.c.source_kind == kind, sign * events.c.amount_minor)
                for kind, sign in signs.items()
            ),
            else_=0,
        )
        predicates = [self._scope(query), events.c.source_kind.in_(signs)]
        if metric not in CURRENT_METRICS:
            predicates.append(events.c.business_on.between(query.from_on, query.through_on))
        selected = (
            select(events, signed.label("contribution_minor"))
            .select_from(
                events.join(
                    self.properties,
                    events.c.property_id == self.properties.c.property_id,
                )
            )
            .where(*predicates)
            .cte("metric_sources")
        )
        total = self.connection.execute(
            select(
                func.coalesce(func.sum(selected.c.contribution_minor), 0), func.count()
            ).select_from(selected)
        ).one()
        statement = select(selected)
        if after:
            day, kind, identity = after
            statement = statement.where(
                or_(
                    selected.c.business_on < day,
                    and_(selected.c.business_on == day, selected.c.source_kind > kind),
                    and_(
                        selected.c.business_on == day,
                        selected.c.source_kind == kind,
                        selected.c.source_id > identity,
                    ),
                )
            )
        rows = self.connection.execute(
            statement.order_by(
                selected.c.business_on.desc(), selected.c.source_kind, selected.c.source_id
            ).limit(query.page_size + 1)
        ).mappings()
        return AmountCount(*total), list(rows)

    def account_page(self, query, after):
        accounts = self._accounts(query)
        statement = select(accounts)
        if after:
            statement = statement.where(accounts.c.account_id > after)
        return list(
            self.connection.execute(
                statement.order_by(accounts.c.account_id).limit(query.page_size + 1)
            ).mappings()
        )


EVENT_KINDS = (
    "rent_receipt",
    "expense",
    "expense_refund",
    "deposit_receipt",
    "deposit_refund",
    "settlement_credit",
    "settlement_deduction",
    "settlement_completed",
)
METRIC_SIGNS = {
    Metric.RENT: {"rent_receipt": 1},
    Metric.EXPENSES: {"expense": 1},
    Metric.REFUNDS: {"expense_refund": 1},
    Metric.NET_EXPENSES: {"expense": 1, "expense_refund": -1},
    Metric.REMAINDER: {"rent_receipt": 1, "expense": -1, "expense_refund": 1},
    Metric.DEPOSIT_RECEIPTS: {"deposit_receipt": 1},
    Metric.DEPOSIT_REFUNDS: {"deposit_refund": 1},
    Metric.CREDITS: {"settlement_credit": 1},
    Metric.DEDUCTIONS: {"settlement_deduction": 1},
    Metric.OBLIGATION: {
        "deposit_receipt": 1,
        "deposit_refund": -1,
        "settlement_credit": 1,
        "settlement_deduction": -1,
    },
    Metric.CURRENT_RECEIPTS: {"deposit_receipt": 1},
    Metric.CURRENT_REFUNDS: {"deposit_refund": 1},
    Metric.CURRENT_CREDITS: {"settlement_credit": 1},
    Metric.CURRENT_DEDUCTIONS: {"settlement_deduction": 1},
}
CURRENT_METRICS = {
    Metric.OBLIGATION,
    Metric.CURRENT_RECEIPTS,
    Metric.CURRENT_REFUNDS,
    Metric.CURRENT_CREDITS,
    Metric.CURRENT_DEDUCTIONS,
}


def _local_date(value, zone):
    if value is None:
        return None
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Settlement timestamp must be aware.")
    return instant.astimezone(ZoneInfo(zone)).date().isoformat()

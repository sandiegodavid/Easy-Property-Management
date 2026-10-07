"""FIN-003 calculations, freshness, and bounded read coordination."""

import base64
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from uuid import UUID

from app.modules.finance.application.money_models import (
    AmountCount,
    Contribution,
    DepositAccountMoney,
    DepositAccountPage,
    DepositActivity,
    DepositObligations,
    Filters,
    Metric,
    MetricDescriptor,
    MoneyError,
    MoneyQuery,
    MoneySummary,
    MoneyUnavailable,
    MoneyViewChanged,
    Operating,
    PropertyMoney,
    PropertyMoneyPage,
    SourcePage,
    money,
)
from app.modules.finance.application.money_ports import MoneySummaryUnitOfWork


class MoneySummaryService:
    def __init__(
        self,
        unit_of_work: MoneySummaryUnitOfWork,
        *,
        read_identity: Callable[[], tuple[str, str]],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.unit_of_work, self.read_identity, self.now = unit_of_work, read_identity, now

    def _read(self, query, kind, operation):
        if not isinstance(query, MoneyQuery):
            raise MoneyError("A validated money query is required.")
        instant = self.now()
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise MoneyUnavailable("Money read clock is unavailable.")
        as_of = instant.astimezone(UTC).isoformat()
        identity = self.read_identity()
        try:
            if len(identity) != 2 or any(str(UUID(value)) != value for value in identity):
                raise ValueError()
        except (ValueError, TypeError, AttributeError) as error:
            raise MoneyUnavailable("Workspace read identity is unavailable.") from error
        fingerprint = _hash({"kind": kind, "filters": _filters_dict(query)})
        cursor = _decode_cursor(query.cursor, kind) if query.cursor else None

        def read(tx):
            revision = _hash({"identity": identity, "marker": tx.source_marker()})
            if query.source_revision is not None and query.source_revision != revision:
                raise MoneyViewChanged("Recorded sources changed. Refresh the money view.")
            if cursor and (
                cursor["revision"] != revision
                or cursor["fingerprint"] != fingerprint
                or cursor["identity"] != list(identity)
            ):
                raise MoneyViewChanged("This continuation no longer matches the money view.")
            scope = tx.scope(query)
            tx.validate_integrity()

            def next_cursor(last):
                return _encode_cursor(
                    {
                        "version": 1,
                        "kind": kind,
                        "identity": identity,
                        "revision": revision,
                        "fingerprint": fingerprint,
                        "last": last,
                    }
                )

            return operation(
                tx, as_of, revision, scope, cursor["last"] if cursor else None, next_cursor
            )

        return self.unit_of_work.read(read)

    def summary(self, query: MoneyQuery) -> MoneySummary:
        if not isinstance(query, MoneyQuery):
            raise MoneyError("A validated money query is required.")
        if query.cursor is not None:
            raise MoneyError("Summary reads do not accept pagination cursors.")
        return self._read(
            query,
            "summary",
            lambda tx, as_of, revision, scope, *_: _summary(
                query, as_of, revision, scope, tx.period_totals(query), tx.obligation_totals(query)
            ),
        )

    def properties(self, query: MoneyQuery) -> PropertyMoneyPage:
        def read(tx, as_of, revision, scope, after, cursor):
            summary = _summary(
                query, as_of, revision, scope, tx.period_totals(query), tx.obligation_totals(query)
            )
            rows = tx.property_page(query, tuple(after) if after else None)
            selected = rows[: query.page_size]
            items = []
            for row in selected:
                totals = {
                    name: AmountCount(row.get(name) or 0, row.get(name + "_count") or 0)
                    for name in PERIOD_KINDS
                }
                items.append(
                    PropertyMoney(
                        row["property_id"],
                        row["property_name"],
                        row["property_state"],
                        _operating(totals),
                        _activity(totals),
                        _obligations(row),
                    )
                )
            continuation = (
                cursor((selected[-1]["sort_key"], selected[-1]["property_id"]))
                if len(rows) > query.page_size
                else None
            )
            return PropertyMoneyPage(summary, tuple(items), scope.property_count, continuation)

        return self._read(query, "properties", read)

    def sources(self, query: MoneyQuery, metric: Metric) -> SourcePage:
        try:
            metric = Metric(metric)
        except (ValueError, TypeError) as error:
            raise MoneyError("The money metric is invalid.") from error

        def read(tx, as_of, revision, scope, after, cursor):
            total, rows = tx.source_page(query, metric, tuple(after) if after else None)
            selected = rows[: query.page_size]
            items = tuple(_contribution(row, metric) for row in selected)
            continuation = (
                cursor(
                    (
                        selected[-1]["business_on"],
                        selected[-1]["source_kind"],
                        selected[-1]["source_id"],
                    )
                )
                if len(rows) > query.page_size
                else None
            )
            return SourcePage(
                as_of,
                revision,
                _filters(query),
                metric,
                money(total.amount_minor),
                total.record_count,
                items,
                continuation,
            )

        return self._read(query, "sources:" + metric.value, read)

    def deposit_accounts(self, query: MoneyQuery) -> DepositAccountPage:
        def read(tx, as_of, revision, scope, after, cursor):
            totals = tx.obligation_totals(query)
            rows = tx.account_page(query, after)
            selected = rows[: query.page_size]
            items = tuple(_account(row) for row in selected)
            continuation = (
                cursor(selected[-1]["account_id"]) if len(rows) > query.page_size else None
            )
            return DepositAccountPage(
                as_of,
                revision,
                _filters(query),
                _obligations(totals),
                items,
                totals["accounts"],
                continuation,
            )

        return self._read(query, "accounts", read)


PERIOD_KINDS = (
    "rent_receipt",
    "expense",
    "expense_refund",
    "deposit_receipt",
    "deposit_refund",
    "settlement_credit",
    "settlement_deduction",
    "settlement_completed",
)


def _operating(totals):
    rent, expense, refund = (
        totals.get(name, AmountCount()) for name in ("rent_receipt", "expense", "expense_refund")
    )
    return Operating(
        money(rent.amount_minor),
        money(expense.amount_minor),
        money(refund.amount_minor),
        money(expense.amount_minor - refund.amount_minor),
        money(rent.amount_minor - expense.amount_minor + refund.amount_minor),
        rent.record_count,
        expense.record_count,
        refund.record_count,
    )


def _activity(totals):
    receipt, refund, credit, deduction, complete = (
        totals.get(name, AmountCount())
        for name in (
            "deposit_receipt",
            "deposit_refund",
            "settlement_credit",
            "settlement_deduction",
            "settlement_completed",
        )
    )
    return DepositActivity(
        money(receipt.amount_minor),
        money(refund.amount_minor),
        money(credit.amount_minor),
        money(deduction.amount_minor),
        receipt.record_count,
        refund.record_count,
        credit.record_count,
        complete.record_count,
    )


def _obligations(row):
    return DepositObligations(
        money(row.get("positive") or 0),
        money(row.get("negative") or 0),
        money(row.get("net") or 0),
        row.get("accounts") or 0,
        row.get("negative_accounts") or 0,
        row.get("unresolved_accounts") or 0,
    )


def _summary(query, as_of, revision, scope, totals, obligations):
    operating, activity, balances = _operating(totals), _activity(totals), _obligations(obligations)
    values = {
        Metric.RENT: operating.rent_received,
        Metric.EXPENSES: operating.expenses_paid,
        Metric.REFUNDS: operating.expense_refunds_received,
        Metric.NET_EXPENSES: operating.net_recorded_expenses,
        Metric.REMAINDER: operating.operating_remainder,
        Metric.DEPOSIT_RECEIPTS: activity.deposit_receipts,
        Metric.DEPOSIT_REFUNDS: activity.deposit_refunds,
        Metric.CREDITS: activity.settlement_credits,
        Metric.DEDUCTIONS: activity.settlement_deductions,
        Metric.OBLIGATION: balances.net_recorded_obligation,
        Metric.CURRENT_RECEIPTS: money(obligations["receipts"]),
        Metric.CURRENT_REFUNDS: money(obligations["refunds"]),
        Metric.CURRENT_CREDITS: money(obligations["credits"]),
        Metric.CURRENT_DEDUCTIONS: money(obligations["deductions"]),
    }
    return MoneySummary(
        as_of=as_of,
        source_revision=revision,
        filters=_filters(query),
        scope=scope,
        operating=operating,
        deposit_activity=activity,
        deposit_obligations=balances,
        metrics=tuple(MetricDescriptor(metric, value) for metric, value in values.items()),
    )


def _contribution(row, metric):
    kind, identity, account = row["source_kind"], row["source_id"], row["account_id"]
    if kind in {"settlement_credit", "settlement_deduction"}:
        route = f"/api/security-deposit-settlements/{identity}"
    elif kind.startswith("deposit_"):
        route = f"/api/leases/{row['lease_id']}/security-deposit"
    elif kind == "expense_refund":
        route = f"/api/expenses/{row['parent_id']}"
    elif kind == "expense":
        route = f"/api/expenses/{identity}"
    else:
        route = f"/api/rent-receipts/{identity}"
    return Contribution(
        kind,
        identity,
        row["property_id"],
        row["business_on"],
        money(row["contribution_minor"]),
        row["lifecycle"],
        metric.value,
        route,
        row["lease_id"],
        row["space_id"],
        account,
        row["parent_id"],
        row["authorization_id"],
        row["party_id"],
    )


def _account(row):
    return DepositAccountMoney(
        row["account_id"],
        row["property_id"],
        row["lease_id"],
        row["space_id"],
        money(row["receipts"]),
        money(row["refunds"]),
        money(row["credits"]),
        money(row["deductions"]),
        money(row["obligation"]),
        money(row["agreed_amount_minor"]),
        money(row["receipts"] - row["agreed_amount_minor"]),
        money(row["unsettled"]),
        row["settlement_id"],
        row["settlement_status"],
        money(row["refund_due_minor"]) if row["refund_due_minor"] is not None else None,
        bool(row["unresolved"]),
        row["obligation"] < 0 or bool(row["unresolved"]),
        f"/api/leases/{row['lease_id']}/security-deposit",
    )


def _filters(query):
    return Filters(query.from_on, query.through_on, query.property_state, query.property_ids)


def _filters_dict(query):
    return {
        "fromOn": query.from_on,
        "throughOn": query.through_on,
        "propertyState": query.property_state,
        "propertyIds": query.property_ids,
    }


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _encode_cursor(value):
    return base64.urlsafe_b64encode(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).decode()


def _decode_cursor(value, kind):
    try:
        payload = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if not isinstance(payload, dict) or set(payload) != {
            "version",
            "kind",
            "identity",
            "revision",
            "fingerprint",
            "last",
        }:
            raise ValueError()
        if type(payload["version"]) is not int or payload["version"] != 1:
            raise ValueError()
        if payload["kind"] != kind:
            raise MoneyViewChanged("This continuation belongs to another money view.")
        if not isinstance(payload["identity"], list) or len(payload["identity"]) != 2:
            raise ValueError()
        for identity in payload["identity"]:
            if str(UUID(identity)) != identity:
                raise ValueError()
        for name in ("revision", "fingerprint"):
            if (
                not isinstance(payload[name], str)
                or len(payload[name]) != 64
                or any(c not in "0123456789abcdef" for c in payload[name])
            ):
                raise ValueError()
        last = payload["last"]
        if kind == "accounts":
            if str(UUID(last)) != last:
                raise ValueError()
        else:
            expected = 3 if kind.startswith("sources:") else 2
            if (
                not isinstance(last, list)
                or len(last) != expected
                or any(not isinstance(v, str) or len(v) > 1000 for v in last)
            ):
                raise ValueError()
            if str(UUID(last[-1])) != last[-1]:
                raise ValueError()
            if expected == 3 and (
                date.fromisoformat(last[0]).isoformat() != last[0] or last[1] not in PERIOD_KINDS
            ):
                raise ValueError()
        return payload
    except MoneyError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as error:
        raise MoneyError("The money cursor is malformed.") from error

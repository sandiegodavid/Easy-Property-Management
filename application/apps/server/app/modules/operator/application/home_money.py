"""Home uses FIN-003's recorded-money snapshot and metric meanings unchanged."""

from datetime import datetime
from decimal import Decimal

from app.modules.finance.application.money_models import MoneyQuery, Metric, MoneyUnavailable
from app.modules.finance.application.money_ports import MoneyContextReader
from app.modules.operator.application.home_contracts import (
    HomeQuery,
    AvailableMoney,
    Capture,
    MoneyMetric,
    MoneyTarget,
)

OPERATING_METRICS = (
    Metric.RENT,
    Metric.EXPENSES,
    Metric.REFUNDS,
    Metric.NET_EXPENSES,
    Metric.REMAINDER,
)


def money_on_home_snapshot(
    reader: MoneyContextReader,
    connection: object,
    query: HomeQuery,
    *,
    as_of: datetime,
    identity: tuple[str, str],
) -> AvailableMoney:
    source = reader.summary(
        connection,
        MoneyQuery(
            query.from_on.isoformat(),
            query.through_on.isoformat(),
            property_state="all",
            property_ids=(str(query.scope.property_id),) if query.scope.property_id else (),
        ),
        as_of=as_of,
        identity=identity,
    )
    if (
        not source.operating.available
        or source.currency_code != "USD"
        or datetime.fromisoformat(source.as_of) != as_of
        or (source.filters.from_on, source.filters.through_on, source.filters.property_state)
        != (query.from_on.isoformat(), query.through_on.isoformat(), "all")
        or source.filters.property_ids
        != ((str(query.scope.property_id),) if query.scope.property_id else ())
    ):
        raise MoneyUnavailable("Recorded money source capture or scope is unavailable.")
    descriptors = {descriptor.metric: descriptor.amount for descriptor in source.metrics}
    metrics = tuple(
        MoneyMetric(
            amount_minor=_minor(descriptors[metric]),
            amount=descriptors[metric],
            target=MoneyTarget(
                scope=query.scope,
                metric=metric.value,
                from_on=query.from_on,
                through_on=query.through_on,
            ),
        )
        for metric in OPERATING_METRICS
    )
    return AvailableMoney(
        capture=Capture(
            as_of=datetime.fromisoformat(source.as_of),
            source_revision=source.source_revision,
            read_mode="live",
            freshness="checked",
            checked_at=datetime.fromisoformat(source.as_of),
        ),
        from_on=query.from_on,
        through_on=query.through_on,
        metrics=metrics,
    )


def _minor(amount):
    cents = Decimal(amount) * 100
    if not cents.is_finite() or cents != cents.to_integral_value():
        raise ValueError("Finance metrics require exact USD cents.")
    return int(cents)

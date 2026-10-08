"""FIN-003 summary semantics on a composing caller's read snapshot."""

from datetime import UTC, datetime
from uuid import UUID

from app.modules.finance.application.money_models import (
    MoneyError,
    MoneyQuery,
    MoneySummary,
    MoneyUnavailable,
    MoneyViewChanged,
)
from app.modules.finance.application.money_ports import MoneyReadTransaction
from app.modules.finance.application.money_service import _hash, _summary

IDENTITY_PARTS = 2


def summary_on_snapshot(
    tx: MoneyReadTransaction, query: MoneyQuery, *, as_of: datetime, identity: tuple[str, str]
) -> MoneySummary:
    if not isinstance(query, MoneyQuery) or query.cursor is not None:
        raise MoneyError("A validated, non-paginated money query is required.")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise MoneyUnavailable("Money read clock is unavailable.")
    try:
        if len(identity) != IDENTITY_PARTS or any(str(UUID(value)) != value for value in identity):
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as error:
        raise MoneyUnavailable("Workspace read identity is unavailable.") from error
    revision = _hash({"identity": identity, "marker": tx.source_marker()})
    if query.source_revision is not None and query.source_revision != revision:
        raise MoneyViewChanged("Recorded sources changed. Refresh the money view.")
    scope = tx.scope(query)
    tx.validate_integrity()
    return _summary(
        query,
        as_of.astimezone(UTC).isoformat(),
        revision,
        scope,
        tx.period_totals(query),
        tx.obligation_totals(query),
    )

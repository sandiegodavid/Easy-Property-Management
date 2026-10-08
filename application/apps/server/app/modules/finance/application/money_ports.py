"""Read-only FIN-003 ports; no sessions escape the snapshot callback."""

from collections.abc import Callable, Mapping
from typing import Protocol, TypeVar
from datetime import datetime
from typing import Any
from sqlalchemy.sql.selectable import FromClause

from app.modules.finance.application.money_models import (
    AmountCount,
    DepositAccountPage,
    MoneyQuery,
    MoneySummary,
    Metric,
    PropertyMoneyPage,
    Scope,
    SourcePage,
)

Result = TypeVar("Result")


class MoneyReadTransaction(Protocol):
    def source_marker(self) -> str: ...
    def scope(self, query: MoneyQuery) -> Scope: ...
    def validate_integrity(self) -> None: ...
    def period_totals(self, query: MoneyQuery) -> Mapping[str, AmountCount]: ...
    def obligation_totals(self, query: MoneyQuery) -> Mapping[str, int]: ...
    def property_page(
        self, query: MoneyQuery, after: tuple[str, str] | None
    ) -> list[Mapping[str, object]]: ...
    def source_page(
        self, query: MoneyQuery, metric: Metric, after: tuple[str, str, str] | None
    ) -> tuple[AmountCount, list[Mapping[str, object]]]: ...
    def account_page(self, query: MoneyQuery, after: str | None) -> list[Mapping[str, object]]: ...


class MoneySummaryUnitOfWork(Protocol):
    def read(self, operation: Callable[[MoneyReadTransaction], Result]) -> Result: ...


class MoneySummaryReader(Protocol):
    def summary(self, query: MoneyQuery) -> MoneySummary: ...
    def properties(self, query: MoneyQuery) -> PropertyMoneyPage: ...
    def sources(self, query: MoneyQuery, metric: Metric) -> SourcePage: ...
    def deposit_accounts(self, query: MoneyQuery) -> DepositAccountPage: ...


class MoneyContextReader(Protocol):
    """FIN-003 semantics on the composing caller's connection and instant."""

    def summary(
        self,
        connection: Any,
        query: MoneyQuery,
        *,
        as_of: datetime,
        identity: tuple[str, str],
        property_scope: FromClause | None = None,
    ) -> MoneySummary:
        """Optional source-owned scope relation has a property_id column.

        Large scopes remain inside SQL; never expand them to an unbounded ID
        collection or call the independently transactional public service.
        """
        ...

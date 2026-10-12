"""Finance-owned rent/deposit completeness, not OPS acknowledgment policy."""

from typing import Protocol
from collections.abc import Collection, Mapping
from app.platform.coverage import CoverageArea, CoverageFacts
from sqlalchemy.sql.selectable import FromClause


class FinanceCoverageReader(Protocol):
    def fact_relation(self, connection, contexts: FromClause) -> FromClause: ...
    def facts_for_contexts(
        self,
        connection,
        contexts: Mapping[str, tuple[Mapping, str, str]],
        areas: Collection[tuple[str, CoverageArea]],
    ) -> Mapping[tuple[str, str], CoverageFacts]: ...
    def facts(
        self, connection, area: str, lease_context, time_zone: str, on: str
    ) -> CoverageFacts: ...

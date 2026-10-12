"""Current lease/term metadata needed to assess recorded context."""

from collections.abc import Mapping
from typing import Protocol
from sqlalchemy.sql.selectable import FromClause


class LeaseCoverageReader(Protocol):
    def context_relation(self, connection, locations: FromClause) -> FromClause: ...
    def relevant_contexts(self, connection, dates: Mapping[str, str]) -> Mapping[str, Mapping]: ...
    def relevant_context(self, connection, space_id: str, on: str) -> Mapping | None: ...

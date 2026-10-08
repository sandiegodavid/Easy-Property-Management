"""Bounded issue metadata and issue locations, without sensitive attribution."""

from typing import Any, Protocol
from sqlalchemy.sql.selectable import FromClause
from app.platform.context_reads import ContextScope, ReadPage, ReadWindow


class IssueSummaryReader(Protocol):
    def page(self, connection: Any, scope: ContextScope, window: ReadWindow) -> ReadPage: ...
    def locations(self) -> FromClause: ...

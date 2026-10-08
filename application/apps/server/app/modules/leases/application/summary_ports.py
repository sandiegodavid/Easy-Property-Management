"""Lease-owned current/historical metadata on a caller-owned snapshot."""

from typing import Any, Protocol
from sqlalchemy.sql.selectable import FromClause
from app.platform.context_reads import ContextScope, ReadPage, ReadWindow


class LeaseSummaryReader(Protocol):
    def page(self, connection: Any, scope: ContextScope, window: ReadWindow) -> ReadPage: ...
    def references(self, properties: FromClause) -> FromClause: ...

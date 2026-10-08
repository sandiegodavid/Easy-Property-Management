"""Contextual communication metadata, never body or participant addresses."""

from typing import Any, Protocol
from sqlalchemy.sql.selectable import FromClause
from app.platform.context_reads import ContextScope, ReadPage, ReadWindow


class CommunicationSummaryReader(Protocol):
    def page(self, connection: Any, scope: ContextScope, window: ReadWindow) -> ReadPage: ...
    def references(self, scope: ContextScope) -> FromClause: ...

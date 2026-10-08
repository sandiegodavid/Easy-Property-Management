"""Source-owned bounded Task facts for arbitrary related-entity scopes."""

from typing import Any, Protocol
from sqlalchemy.sql.selectable import FromClause
from app.platform.context_reads import ContextScope, ReadPage, ReadWindow


class TaskSummaryReader(Protocol):
    def page(self, connection: Any, scope: ContextScope, window: ReadWindow) -> ReadPage: ...
    def references(self, scope: ContextScope) -> FromClause: ...

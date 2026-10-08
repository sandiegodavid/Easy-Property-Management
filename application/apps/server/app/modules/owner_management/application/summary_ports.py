"""Owner-concern facts for context collections on the caller snapshot."""

from typing import Any, Protocol
from sqlalchemy.sql.selectable import FromClause
from app.platform.context_reads import ContextScope, ReadPage, ReadWindow


class OwnerConcernSummaryReader(Protocol):
    def page(self, connection: Any, scope: ContextScope, window: ReadWindow) -> ReadPage: ...
    def locations(self) -> FromClause: ...

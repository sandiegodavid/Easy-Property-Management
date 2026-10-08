"""Finance-owned metadata identities for location-scoped context reads."""

from typing import Protocol
from sqlalchemy.sql.selectable import FromClause


class FinanceContextRelations(Protocol):
    def references(self, properties: FromClause) -> FromClause: ...

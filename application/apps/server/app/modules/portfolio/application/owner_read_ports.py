"""Portfolio-owned owner membership and contextual metadata, never balances."""

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol

from sqlalchemy.sql.selectable import FromClause

from app.modules.portfolio.application.directory_ports import (
    MAX_DIRECTORY_ITEMS,
    MAX_DIRECTORY_TEXT,
)
from app.modules.portfolio.application.service import PortfolioError
from app.platform.context_reads import ReadPage, ReadWindow

RELATIONSHIP_SCOPES = {"current", "former", "all"}


@dataclass(frozen=True)
class OwnerDirectoryQuery:
    text: str = ""
    archive_state: str = "active"
    relationship_scope: str = "current"
    property_state: str = "active"
    limit: int = 50

    def __post_init__(self):
        if not isinstance(self.text, str) or len(self.text) > MAX_DIRECTORY_TEXT:
            raise PortfolioError("Owner search must contain at most 240 characters.")
        if (
            self.archive_state not in {"active", "archived", "all"}
            or self.property_state not in {"active", "archived", "all"}
            or self.relationship_scope not in RELATIONSHIP_SCOPES
            or type(self.limit) is not int
            or not 1 <= self.limit <= MAX_DIRECTORY_ITEMS
        ):
            raise PortfolioError("Owner directory filters or bounds are invalid.")
        object.__setattr__(
            self, "text", unicodedata.normalize("NFKC", self.text.strip()).casefold()
        )


@dataclass(frozen=True)
class PortfolioSubject:
    kind: str
    id: str
    relationship_scope: str = "current"

    def __post_init__(self):
        if (
            self.kind not in {"property", "owner"}
            or self.relationship_scope not in RELATIONSHIP_SCOPES
        ):
            raise PortfolioError("Context subject or relationship scope is invalid.")


class OwnerContextReader(Protocol):
    def coverage_preview_groups(
        self, connection: Any, kind: str, ids: list[str], query, *, as_of: datetime
    ) -> FromClause: ...
    def owners(
        self,
        connection: Any,
        query: OwnerDirectoryQuery,
        *,
        as_of: datetime,
        after: tuple[str, str] | None,
    ) -> ReadPage: ...
    def identity(
        self, connection: Any, subject: PortfolioSubject
    ) -> Mapping[str, object] | None: ...
    def property_scope(
        self, connection: Any, subject: PortfolioSubject, *, as_of: datetime
    ) -> FromClause: ...
    def properties(
        self, connection: Any, subject: PortfolioSubject, window: ReadWindow
    ) -> ReadPage: ...
    def relationships(
        self, connection: Any, subject: PortfolioSubject, window: ReadWindow
    ) -> ReadPage: ...
    def spaces(
        self, connection: Any, subject: PortfolioSubject, window: ReadWindow
    ) -> ReadPage: ...

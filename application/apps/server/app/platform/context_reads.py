"""Neutral bounds for transaction-aware metadata collections (not evidence)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy.sql.selectable import FromClause

MAX_CONTEXT_ITEMS = 50


@dataclass(frozen=True)
class ContextScope:
    properties: FromClause
    references: FromClause
    party_id: str | None = None


@dataclass(frozen=True)
class ReadWindow:
    as_of: datetime
    limit: int = 10
    after: tuple[str, str] | None = None
    include_history: bool = False

    def __post_init__(self):
        if type(self.limit) is not int or not 1 <= self.limit <= MAX_CONTEXT_ITEMS:
            raise ValueError("Context reads allow 1–50 items.")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("Context reads require an aware instant.")


@dataclass(frozen=True)
class ReadPage:
    total: int
    items: Sequence[Mapping[str, object]]
    next_key: tuple[str, str] | None

"""Neutral, bounded metadata search contract for source-owned readers."""

import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol

from app.platform.context_reads import ReadPage, ReadWindow

MAX_SEARCH_TEXT = 240
MIN_SEARCH_CHARACTERS = 2


@dataclass(frozen=True)
class SearchTerm:
    text: str
    include_archived: bool = False

    def __post_init__(self):
        if not isinstance(self.text, str) or len(self.text) > MAX_SEARCH_TEXT:
            raise ValueError("Search text must contain at most 240 characters.")
        normalized = unicodedata.normalize("NFKC", self.text).strip()
        if (
            len(normalized.casefold()) > MAX_SEARCH_TEXT
            or sum(not character.isspace() for character in normalized) < MIN_SEARCH_CHARACTERS
            or type(self.include_archived) is not bool
        ):
            raise ValueError("Search requires at least two non-whitespace characters.")
        object.__setattr__(self, "text", normalized.casefold())


class MetadataSearchReader(Protocol):
    def search(self, connection: Any, term: SearchTerm, window: ReadWindow) -> ReadPage:
        """Rows: id, label, context, archived, entity_type, sort_key; no evidence."""
        ...

"""Explicit metadata source registry: only completed source read contracts."""

from dataclasses import dataclass
from app.platform.metadata_search import MetadataSearchReader

SEARCH_KINDS = (
    "properties",
    "spaces",
    "owners",
    "tenants",
    "leases",
    "communications",
    "maintenance",
    "tasks",
)


@dataclass(frozen=True)
class SearchDefinition:
    kind: str
    source_kind: str
    entity_type: str


@dataclass(frozen=True)
class SearchRegistration:
    definition: SearchDefinition
    reader: MetadataSearchReader


class MetadataSearchRegistry:
    def __init__(self, entries: tuple[SearchRegistration, ...]):
        kinds = [entry.definition.kind for entry in entries]
        if not kinds or len(set(kinds)) != len(kinds) or set(kinds) - set(SEARCH_KINDS):
            raise ValueError(
                "Search sources must be explicitly registered with unique supported kinds."
            )
        self._entries = {entry.definition.kind: entry for entry in entries}

    @property
    def definitions(self) -> tuple[SearchDefinition, ...]:
        return tuple(entry.definition for entry in self._entries.values())

    def reader(self, kind: str) -> MetadataSearchReader:
        return self._entries[kind].reader

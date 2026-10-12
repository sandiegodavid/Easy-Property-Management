"""Portfolio owns Home scope membership, local boundaries and active inventory."""

from datetime import datetime
from typing import Protocol
from uuid import UUID
from sqlalchemy.sql.selectable import FromClause
from dataclasses import dataclass
from typing import Literal
from collections.abc import Mapping

from app.platform.attention_reads import InventoryFacts, PropertyCalendar

MAX_CALENDAR_PROPERTIES = 100


@dataclass(frozen=True)
class InventorySpace:
    property_id: UUID
    property_name: str
    space_id: UUID
    space_name: str
    occupancy: Literal["vacant", "unknown"]
    time_zone: str


@dataclass(frozen=True)
class InventorySpacePage:
    matching_total: int
    items: tuple[InventorySpace, ...]
    next_key: tuple[str, str] | None


@dataclass(frozen=True)
class AttentionLocationLabels:
    property_names: Mapping[UUID, str]
    space_names: Mapping[UUID, str]


class PortfolioAttentionError(ValueError):
    code = "portfolio_attention_invalid"
    status_code = 422


class PortfolioAttentionNotFound(PortfolioAttentionError):
    code = "portfolio_property_not_found"
    status_code = 404


class PortfolioAttentionReader(Protocol):
    def properties(
        self, property_id: UUID | None = None, *, inventory_only: bool = False
    ) -> FromClause:
        """SQL scope relation; retain archived obligations unless inventory_only."""
        ...

    def spaces(
        self, property_id: UUID | None = None, *, inventory_only: bool = False
    ) -> FromClause:
        """SQL space-to-property relation, with matching retained/active semantics."""
        ...

    def validate_scope(self, connection: object, property_id: UUID | None) -> None:
        """Raise not-found for an absent explicit property, including archived scope."""
        ...

    def calendars(
        self, connection: object, property_ids: tuple[UUID, ...], as_of: datetime, horizon_days: int
    ) -> tuple[PropertyCalendar, ...]:
        """Hydrate only bounded selected identities, never the entire portfolio."""
        ...

    def attention_labels(
        self, connection: object, property_ids: tuple[UUID, ...], space_ids: tuple[UUID, ...]
    ) -> AttentionLocationLabels:
        """Hydrate at most 100 selected properties and spaces in one set-based query."""
        ...

    def inventory(
        self, connection: object, property_id: UUID | None, as_of: datetime
    ) -> InventoryFacts:
        """Count active inventory set-wise; unknown never contributes to vacancy."""
        ...

    def inventory_spaces(
        self,
        connection: object,
        property_id: UUID | None,
        as_of: datetime,
        occupancy: Literal["vacant", "unknown"],
        *,
        limit: int = 50,
        after: tuple[str, str] | None = None,
    ) -> InventorySpacePage:
        """Bounded contributing spaces using the exact inventory count predicate."""
        ...

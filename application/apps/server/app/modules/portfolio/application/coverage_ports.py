"""Portfolio-owned identity and temporal status facts for coverage consumers."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from collections.abc import Collection, Mapping
from app.platform.context_reads import ReadPage, ReadWindow
from sqlalchemy.sql.selectable import FromClause

from app.platform.coverage import CoverageSubject


@dataclass(frozen=True)
class CoverageLocation:
    property_id: str
    time_zone: str
    occupancy: str | None
    availability: str | None
    occupancy_source: str | None
    occupancy_source_id: str | None
    revision: str


class PortfolioCoverageReader(Protocol):
    def locations(
        self, connection, subjects: Collection[CoverageSubject], *, as_of: datetime
    ) -> Mapping[CoverageSubject, CoverageLocation]: ...
    def page_for_properties(
        self, connection, properties: FromClause, window: ReadWindow
    ) -> ReadPage: ...
    def previews_for_groups(
        self, connection, groups: FromClause, *, as_of: datetime, include_history: bool
    ) -> Mapping[str, ReadPage]: ...
    def location(
        self, connection, subject: CoverageSubject, *, as_of: datetime
    ) -> CoverageLocation | None: ...

"""Composable retained lease locations, without finance eligibility rules."""

from typing import Protocol

from sqlalchemy.sql.selectable import FromClause


class LeaseLocationRelation(Protocol):
    def locations(self) -> FromClause:
        """One row/lease: lease_id, space_id, property_id/name/state, time_zone.

        Missing locations remain null for consumer integrity checks. Read-only,
        using the caller's connection; no lifecycle filtering or history ID lists.
        """
        ...

"""Neutral lease-participant and occupancy facts for shared read snapshots."""

from typing import Protocol

from sqlalchemy.sql.selectable import FromClause


class LeaseParticipantRelations(Protocol):
    def participants(self) -> FromClause:
        """Lease/space/party IDs, lease status and occupancy/participant intervals.

        Includes all retained states. Consumers apply eligibility to raw facts.
        """
        ...

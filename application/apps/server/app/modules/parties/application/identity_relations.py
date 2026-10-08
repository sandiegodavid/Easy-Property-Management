"""Composable identity metadata, excluding contacts and sensitive narratives."""

from typing import Protocol

from sqlalchemy.sql.selectable import FromClause


class PartyIdentityRelations(Protocol):
    def identities(self) -> FromClause:
        """Columns: party_id, display_name, party_kind, archived_at."""
        ...

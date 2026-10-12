"""Source-owned DASH-001 attention projection contract."""

from typing import Protocol
from sqlalchemy.sql.selectable import FromClause

from app.platform.attention_reads import AttentionReader
from app.platform.attention_reads import AttentionWindow


class MaintenanceAttentionReader(AttentionReader, Protocol):
    """Use window.source_kind to separate issue and appointment counts/candidates.

    Filter and group before bounded selection; do not return both source streams
    for a request bound to one discriminator.
    """

    def facts(self, connection: object, window: AttentionWindow) -> FromClause:
        """Source-classified SQL facts for composition before pagination."""
        ...

    def follow_up_relations(self) -> FromClause:
        """Explicit active issue/task pairs, including source lifecycle eligibility."""
        ...

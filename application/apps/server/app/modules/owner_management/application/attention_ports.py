"""Source-owned DASH-001 attention projection contract."""

from typing import Protocol
from sqlalchemy.sql.selectable import FromClause

from app.platform.attention_reads import AttentionReader, AttentionWindow


class OwnerConcernAttentionReader(AttentionReader, Protocol):
    """Filter and group source facts before bounded candidate selection."""

    def facts(self, connection: object, window: AttentionWindow) -> FromClause:
        """Unresolved concerns and explicit active follow-up classifications."""
        ...

    def follow_up_relations(self) -> FromClause:
        """Distinct concern_id/task_id pairs from owning follow-up operations.

        Composition must check active parent/child facts, not infer grouping
        from generic Task context or shared property/lease identity.
        """
        ...

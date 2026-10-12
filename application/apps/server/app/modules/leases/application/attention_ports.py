"""Source-owned DASH-001 attention projection contract."""

from typing import Protocol
from sqlalchemy.sql.selectable import FromClause

from app.platform.attention_reads import AttentionReader, AttentionWindow


class LeaseAttentionReader(AttentionReader, Protocol):
    """Filter and group source facts before bounded candidate selection."""

    def facts(self, connection: object, window: AttentionWindow) -> FromClause:
        """Lease-owned review/closure facts before bounded merged selection."""
        ...

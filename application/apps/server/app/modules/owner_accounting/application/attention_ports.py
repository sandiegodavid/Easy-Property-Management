"""Source-owned DASH-001 attention projection contract."""

from typing import Protocol
from sqlalchemy.sql.selectable import FromClause

from app.platform.attention_reads import AttentionReader, AttentionWindow


class OwnerReportAttentionReader(AttentionReader, Protocol):
    """Filter and group source facts before bounded candidate selection."""

    def facts(self, connection: object, window: AttentionWindow) -> FromClause:
        """Pending report metadata, retaining historical owner and lease identity."""
        ...

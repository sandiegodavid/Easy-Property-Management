"""Insertion order is monotonic within the append-only ledger's runtime."""

from sqlalchemy import text


class SQLiteAuditReadMarker:
    def marker(self, connection) -> str:
        return str(
            connection.execute(
                text("SELECT coalesce(max(rowid), 0) FROM audit_events")
            ).scalar_one()
        )

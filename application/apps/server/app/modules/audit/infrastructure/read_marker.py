"""Insertion order is monotonic within the append-only ledger's runtime."""

from sqlalchemy import text, select, func, literal_column, table, column


class SQLiteAuditReadMarker:
    def grouped_markers(self, references):
        events = table("audit_events", column("entity_type"), column("entity_id"))
        return (
            select(
                references.c.group_id,
                func.max(literal_column("audit_events.rowid")).label("marker"),
            )
            .select_from(
                events.join(
                    references,
                    (events.c.entity_type == references.c.entity_type)
                    & (events.c.entity_id == references.c.entity_id),
                )
            )
            .group_by(references.c.group_id)
            .subquery()
        )

    def markers_for_groups(self, connection, references):
        rows = connection.execute(select(self.grouped_markers(references)))
        return {key: str(marker) for key, marker in rows}

    def marker_for_references(self, connection, references):
        events = table("audit_events", column("entity_type"), column("entity_id"))
        return str(
            connection.execute(
                select(
                    func.coalesce(func.max(literal_column("audit_events.rowid")), 0)
                ).select_from(
                    events.join(
                        references,
                        (events.c.entity_type == references.c.entity_type)
                        & (events.c.entity_id == references.c.entity_id),
                    )
                )
            ).scalar_one()
        )

    def marker(self, connection) -> str:
        return str(
            connection.execute(
                text("SELECT coalesce(max(rowid), 0) FROM audit_events")
            ).scalar_one()
        )

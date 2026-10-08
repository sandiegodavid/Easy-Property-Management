"""Metadata-only concern projection; description and disposition notes stay private."""

from sqlalchemy import select
from app.modules.owner_management.infrastructure.sqlalchemy_models import OwnerConcernModel
from app.platform.sql_context_reads import bounded_page


class SQLiteOwnerConcernSummaryReader:
    def locations(self):
        c = OwnerConcernModel.__table__
        return select(c.c.id.label("concern_id"), c.c.property_id, c.c.owner_party_id).subquery(
            "concern_locations"
        )

    def page(self, connection, scope, window):
        c = OwnerConcernModel.__table__
        selection = select(
            c.c.id,
            c.c.owner_party_id,
            c.c.property_id,
            c.c.summary,
            c.c.status,
            c.c.priority,
            c.c.concern_type,
            c.c.raised_at_utc.label("sort_key"),
        ).where(c.c.property_id.in_(select(scope.properties.c.property_id)))
        if scope.party_id:
            selection = selection.where(c.c.owner_party_id == scope.party_id)
        if not window.include_history:
            selection = selection.where(c.c.status.in_(("open", "in_progress")))
        return bounded_page(connection, selection, window, descending=True)

"""Recorded conversation metadata; excludes body and participant addresses."""

from sqlalchemy import literal, select
from app.modules.communications.infrastructure.sqlalchemy_models import CommunicationModel
from app.platform.sql_metadata_search import metadata_page


class SQLiteCommunicationSearchReader:
    def search(self, connection, term, window):
        c = CommunicationModel.__table__
        selection = select(
            c.c.id,
            c.c.subject.label("label"),
            (c.c.channel + literal(" · ") + c.c.direction).label("context"),
            literal(False).label("archived"),
            literal("communication").label("entity_type"),
        ).where(c.c.status.in_(("recorded", "superseded")))
        return metadata_page(connection, selection, term, window)

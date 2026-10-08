"""Task labels and stored contextual label, never notes or outcome text."""

from sqlalchemy import literal, select, func
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel
from app.platform.sql_metadata_search import metadata_page


class SQLiteTaskSearchReader:
    def search(self, connection, term, window):
        t = TaskModel.__table__
        selection = select(
            t.c.id,
            t.c.title.label("label"),
            (
                t.c.status
                + literal(" · ")
                + func.substr(func.coalesce(t.c.related_label, "Task"), 1, 240)
            ).label("context"),
            literal(False).label("archived"),
            literal("task").label("entity_type"),
        ).where(t.c.deleted_at_utc.is_(None))
        return metadata_page(connection, selection, term, window)

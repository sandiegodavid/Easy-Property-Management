"""Issue-owned bounded summaries and metadata-only context references."""

from sqlalchemy import select
from app.modules.maintenance.infrastructure.sqlalchemy_models import MaintenanceIssueModel
from app.platform.sql_context_reads import bounded_page


class SQLiteIssueSummaryReader:
    def locations(self):
        issue = MaintenanceIssueModel.__table__
        return select(issue.c.id.label("issue_id"), issue.c.property_id).subquery("issue_locations")

    def page(self, connection, scope, window):
        issue = MaintenanceIssueModel.__table__
        selection = select(
            issue.c.id,
            issue.c.property_id,
            issue.c.space_id,
            issue.c.summary,
            issue.c.status,
            issue.c.priority,
            issue.c.category,
            issue.c.reported_at_utc.label("sort_key"),
        ).where(issue.c.property_id.in_(select(scope.properties.c.property_id)))
        if not window.include_history:
            selection = selection.where(issue.c.status.in_(("open", "in_progress")))
        return bounded_page(connection, selection, window, descending=True)

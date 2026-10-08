"""Issue labels and Portfolio context; excludes reporter attribution and narratives."""

from sqlalchemy import literal, select
from app.modules.maintenance.infrastructure.sqlalchemy_models import MaintenanceIssueModel
from app.modules.portfolio.application.location_ports import PortfolioLocationRelations
from app.platform.sql_metadata_search import metadata_page


class SQLiteIssueSearchReader:
    def __init__(self, locations: PortfolioLocationRelations):
        self.locations = locations

    def search(self, connection, term, window):
        issue, p = MaintenanceIssueModel.__table__, self.locations.properties()
        selection = select(
            issue.c.id,
            issue.c.summary.label("label"),
            (p.c.property_name + literal(" · ") + issue.c.status).label("context"),
            (p.c.property_state == "archived").label("archived"),
            literal("maintenance_issue").label("entity_type"),
        ).join(p, issue.c.property_id == p.c.property_id)
        return metadata_page(connection, selection, term, window)

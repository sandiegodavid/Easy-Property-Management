"""Narrow, composable portfolio-owned location projections."""

from sqlalchemy import select

from app.modules.portfolio.infrastructure.sqlalchemy_models import PropertyModel, SpaceModel


class SQLitePortfolioLocationRelations:
    def properties(self):
        return select(
            PropertyModel.id.label("property_id"),
            PropertyModel.display_name.label("property_name"),
            PropertyModel.status.label("property_state"),
            PropertyModel.time_zone,
        ).subquery("retained_properties")

    def spaces(self):
        return select(SpaceModel.id.label("space_id"), SpaceModel.property_id).subquery(
            "retained_spaces"
        )

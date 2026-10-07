"""Lease-owned location join composed with portfolio-owned relations."""

from sqlalchemy import select

from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel
from app.modules.portfolio.application.location_ports import PortfolioLocationRelations


class SQLiteLeaseLocationRelation:
    def __init__(self, portfolio: PortfolioLocationRelations):
        self.portfolio = portfolio

    def locations(self):
        spaces, properties = self.portfolio.spaces(), self.portfolio.properties()
        return (
            select(
                LeaseModel.id.label("lease_id"),
                LeaseModel.space_id,
                properties.c.property_id,
                properties.c.property_name,
                properties.c.property_state,
                properties.c.time_zone,
            )
            .select_from(
                LeaseModel.__table__.outerjoin(
                    spaces,
                    LeaseModel.space_id == spaces.c.space_id,
                ).outerjoin(properties, spaces.c.property_id == properties.c.property_id)
            )
            .subquery("lease_locations")
        )

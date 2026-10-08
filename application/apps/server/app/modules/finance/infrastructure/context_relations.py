"""Narrow rent-record identity selection; never expose amounts or source notes."""

from sqlalchemy import literal, select, union_all
from app.modules.finance.infrastructure.sqlalchemy_models import (
    RentExpectationModel,
    RentReceiptModel,
)
from app.modules.leases.application.location_ports import LeaseLocationRelation


class SQLiteFinanceContextRelations:
    def __init__(self, leases: LeaseLocationRelation):
        self.leases = leases

    def references(self, properties):
        locations = self.leases.locations()
        selections = []
        for kind, model in (
            ("rent_expectation", RentExpectationModel),
            ("rent_receipt", RentReceiptModel),
        ):
            table = model.__table__
            selections.append(
                select(literal(kind).label("entity_type"), table.c.id.label("entity_id"))
                .join(locations, table.c.lease_id == locations.c.lease_id)
                .where(locations.c.property_id.in_(select(properties.c.property_id)))
            )
        return union_all(*selections).subquery("rent_context_references")

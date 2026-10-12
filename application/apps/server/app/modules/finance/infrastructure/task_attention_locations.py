"""Finance-owned record locations for independent Task attention."""

from sqlalchemy import select, literal, union_all

from app.modules.finance.infrastructure.sqlalchemy_models import (
    RentExpectationModel,
    RentReceiptModel,
    PrepaidCheckModel,
)
from app.modules.leases.application.location_ports import LeaseLocationRelation


class SQLiteFinanceTaskLocations:
    def __init__(self, leases: LeaseLocationRelation):
        self.leases = leases

    def task_locations(self):
        locations = self.leases.locations()
        queries = []
        for kind, model in (
            ("rent_expectation", RentExpectationModel),
            ("rent_receipt", RentReceiptModel),
            ("prepaid_check", PrepaidCheckModel),
        ):
            source = model.__table__
            queries.append(
                select(
                    literal(kind).label("entity_type"),
                    source.c.id.label("entity_id"),
                    locations.c.property_id,
                    locations.c.space_id,
                    (locations.c.property_state == "archived").label("property_archived"),
                    literal(None).label("group_kind"),
                    literal(False).label("parent_active"),
                ).select_from(source.join(locations, source.c.lease_id == locations.c.lease_id))
            )
        return union_all(*queries).subquery("finance_task_locations")

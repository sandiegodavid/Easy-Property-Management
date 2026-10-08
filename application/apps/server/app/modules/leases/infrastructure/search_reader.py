"""Lease identity and location metadata; never lease notes or financial terms."""

from sqlalchemy import literal, select, func

from app.modules.leases.application.location_ports import LeaseLocationRelation
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel
from app.platform.sql_metadata_search import metadata_page


class SQLiteLeaseSearchReader:
    def __init__(self, locations: LeaseLocationRelation):
        self.locations = locations

    def search(self, connection, term, window):
        lease, location = LeaseModel.__table__, self.locations.locations()
        label = (
            func.coalesce(location.c.property_name, "Lease")
            + literal(" · ")
            + lease.c.contract_starts_on
        )
        selection = select(
            lease.c.id,
            label.label("label"),
            (lease.c.lease_kind + literal(" · ") + lease.c.status).label("context"),
            (location.c.property_state == "archived").label("archived"),
            literal("lease").label("entity_type"),
        ).join(location, lease.c.id == location.c.lease_id)
        return metadata_page(connection, selection, term, window)

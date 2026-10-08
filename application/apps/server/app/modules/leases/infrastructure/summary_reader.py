"""Bounded lease facts, without notes, reports, or full lease hydration."""

from datetime import UTC
from sqlalchemy import and_, func, or_, select, literal

from app.modules.leases.application.location_ports import LeaseLocationRelation
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseRenewalOptionModel
from app.platform.sql_context_reads import bounded_page


class SQLiteLeaseSummaryReader:
    def __init__(self, locations: LeaseLocationRelation):
        self.locations = locations

    def references(self, properties):
        locations = self.locations.locations()
        renewal = LeaseRenewalOptionModel.__table__
        return (
            select(literal("renewal_option").label("entity_type"), renewal.c.id.label("entity_id"))
            .join(locations, renewal.c.lease_id == locations.c.lease_id)
            .where(locations.c.property_id.in_(select(properties.c.property_id)))
            .subquery("lease_context_references")
        )

    def page(self, connection, scope, window):
        lease, locations = LeaseModel.__table__, self.locations.locations()
        day = func.portfolio_local_day(
            locations.c.time_zone, window.as_of.astimezone(UTC).isoformat()
        )
        current = and_(
            lease.c.status.in_(("executed", "ended", "terminated")),
            lease.c.occupancy_starts_on <= day,
            or_(lease.c.actual_move_out_on.is_(None), lease.c.actual_move_out_on > day),
        )
        selection = (
            select(
                lease.c.id,
                lease.c.space_id,
                locations.c.property_id,
                lease.c.lease_kind,
                lease.c.status,
                lease.c.contract_starts_on,
                lease.c.contract_ends_on,
                lease.c.occupancy_starts_on,
                lease.c.actual_move_out_on,
                current.label("is_current"),
                lease.c.created_at.label("sort_key"),
            )
            .join(locations, lease.c.id == locations.c.lease_id)
            .where(locations.c.property_id.in_(select(scope.properties.c.property_id)))
        )
        if not window.include_history:
            selection = selection.where(current)
        return bounded_page(connection, selection, window, descending=True)

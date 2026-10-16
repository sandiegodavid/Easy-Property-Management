"""Bounded lease facts, without notes, reports, or full lease hydration."""

from datetime import UTC
from sqlalchemy import and_, func, or_, select, literal

from app.modules.leases.application.location_ports import LeaseLocationRelation
from app.modules.leases.application.summary_ports import LEASE_TENANT_PREVIEW_LIMIT
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseRenewalOptionModel
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseParticipantModel
from app.modules.parties.application.identity_relations import PartyIdentityRelations
from app.platform.context_reads import ReadPage
from app.platform.sql_context_reads import bounded_page


class SQLiteLeaseSummaryReader:
    def __init__(self, locations: LeaseLocationRelation, parties: PartyIdentityRelations):
        self.locations = locations
        self.parties = parties

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
        page = bounded_page(connection, selection, window, descending=True)
        tenants = self._tenant_previews(connection, [row["id"] for row in page.items])
        return ReadPage(
            page.total,
            [
                {
                    **row,
                    "tenants": tenants.get(row["id"], []),
                    "tenant_count": tenants[row["id"]][0]["total"] if row["id"] in tenants else 0,
                }
                for row in page.items
            ],
            page.next_key,
        )

    def _tenant_previews(self, connection, lease_ids):
        if not lease_ids:
            return {}
        participant, parties = LeaseParticipantModel.__table__, self.parties.identities()
        ranked = (
            select(
                participant.c.lease_id,
                participant.c.tenant_party_id.label("party_id"),
                parties.c.display_name,
                participant.c.participant_role,
                participant.c.starts_on,
                participant.c.ends_on,
                func.count().over(partition_by=participant.c.lease_id).label("total"),
                func.row_number()
                .over(
                    partition_by=participant.c.lease_id,
                    order_by=(participant.c.starts_on, participant.c.id),
                )
                .label("position"),
            )
            .join(parties, parties.c.party_id == participant.c.tenant_party_id)
            .where(
                participant.c.lease_id.in_(lease_ids),
                participant.c.participant_role != "guarantor",
            )
            .subquery()
        )
        rows = connection.execute(
            select(ranked)
            .where(ranked.c.position <= LEASE_TENANT_PREVIEW_LIMIT)
            .order_by(ranked.c.lease_id, ranked.c.position)
        ).mappings()
        result = {}
        for row in rows:
            result.setdefault(row["lease_id"], []).append(row)
        return result

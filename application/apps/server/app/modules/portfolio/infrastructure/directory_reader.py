"""Bounded property selection and recognition previews on a caller snapshot.

External identities/participants are composed solely through source-owned
relations. No foreign persistence model, session, or full-history hydration.
"""

from collections import defaultdict
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, exists, func, literal, or_, select

from app.modules.leases.application.participant_relations import LeaseParticipantRelations
from app.modules.parties.application.identity_relations import PartyIdentityRelations
from app.modules.portfolio.application.service import PortfolioError
from app.modules.portfolio.application.directory_ports import RECOGNITION_PREVIEW_LIMIT
from app.modules.portfolio.infrastructure.sqlalchemy_models import (
    PropertyModel,
    PropertyOwnershipModel,
    SpaceModel,
    SpaceAvailabilityModel,
    SpaceOccupancyPeriodModel,
)


class SQLitePortfolioDirectoryReader:
    def __init__(self, parties: PartyIdentityRelations, leases: LeaseParticipantRelations):
        self.parties, self.leases = parties, leases

    @staticmethod
    def calendar_signature(connection, as_of):
        zones = connection.execute(select(PropertyModel.time_zone).distinct()).scalars()
        return "|".join(
            sorted(
                f"{zone}:{as_of.astimezone(ZoneInfo(zone)).date().isoformat()}" for zone in zones
            )
        )

    def properties(self, connection, query, *, as_of, after):
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise PortfolioError("Property directory requires an aware captured instant.")
        captured = as_of.astimezone(UTC).isoformat()
        connection.connection.driver_connection.create_function(
            "portfolio_local_day", 2, _local_day, deterministic=True
        )
        p, o, s = PropertyModel.__table__, PropertyOwnershipModel.__table__, SpaceModel.__table__
        identities = self.parties.identities()
        local_day = func.portfolio_local_day(p.c.time_zone, captured)
        ownership = and_(
            o.c.property_id == p.c.id,
            o.c.starts_on <= local_day,
            or_(o.c.ends_on.is_(None), o.c.ends_on > local_day),
        )
        local = exists(select(1).where(ownership, o.c.owner_kind == "local_operator"))
        client = exists(select(1).where(ownership, o.c.owner_kind == "client_owner"))
        context = case(
            (and_(local, client), "mixed"),
            (client, "managed_for_owner"),
            (local, "self_owned"),
            else_="unknown",
        )
        space_facts = self._space_facts(captured)
        sf = space_facts.c
        attention = exists(select(1).where(sf.property_id == p.c.id, sf.needs_attention == 1))
        predicates = []
        if query.status != "all":
            predicates.append(p.c.status == query.status)
        if query.ownership_context:
            predicates.append(context == query.ownership_context)
        for field, value in (("occupancy", query.occupancy), ("availability", query.availability)):
            if value:
                predicates.append(
                    exists(select(1).where(sf.property_id == p.c.id, sf[field] == value))
                )
        if query.needs_attention is not None:
            predicates.append(attention if query.needs_attention else ~attention)
        if query.text:
            participant = self.leases.participants()
            lp = participant.c
            owner_match = exists(
                select(1)
                .select_from(o.join(identities, o.c.party_id == identities.c.party_id))
                .where(ownership, _matches(identities.c.display_name, query.text))
            )
            tenant_match = exists(
                select(1)
                .select_from(
                    s.join(participant, s.c.id == lp.space_id).join(
                        identities, lp.party_id == identities.c.party_id
                    )
                )
                .where(
                    s.c.property_id == p.c.id,
                    s.c.status == "active",
                    lp.lease_status.in_(("executed", "ended", "terminated")),
                    lp.occupancy_starts_on <= local_day,
                    or_(lp.actual_move_out_on.is_(None), lp.actual_move_out_on > local_day),
                    lp.starts_on <= local_day,
                    or_(lp.ends_on.is_(None), lp.ends_on > local_day),
                    lp.participant_role != "guarantor",
                    _matches(identities.c.display_name, query.text),
                )
            )
            address = (
                p.c.address_line_1
                + literal(" ")
                + func.coalesce(p.c.address_line_2, "")
                + literal(" ")
                + p.c.city
                + literal(" ")
                + func.coalesce(p.c.region, "")
                + literal(" ")
                + func.coalesce(p.c.postal_code, "")
            )
            predicates.append(
                or_(
                    _matches(p.c.display_name, query.text),
                    _matches(address, query.text),
                    owner_match,
                    tenant_match,
                )
            )
        total = connection.execute(
            select(func.count()).select_from(p).where(*predicates)
        ).scalar_one()
        sort_key = func.unicode_casefold(p.c.display_name)
        if after:
            predicates.append(
                or_(sort_key > after[0], and_(sort_key == after[0], p.c.id > after[1]))
            )
        rows = [
            dict(row)
            for row in connection.execute(
                select(
                    p.c.id,
                    p.c.display_name,
                    p.c.address_line_1,
                    p.c.address_line_2,
                    p.c.city,
                    p.c.region,
                    p.c.postal_code,
                    p.c.country_code,
                    p.c.time_zone,
                    p.c.status,
                    p.c.property_type,
                    p.c.inventory_layout,
                    sort_key.label("sort_key"),
                    context.label("ownership_context"),
                    attention.label("needs_attention"),
                    local_day.label("effective_local_date"),
                )
                .where(*predicates)
                .order_by(sort_key, p.c.id)
                .limit(query.limit + 1)
            ).mappings()
        ]
        ids = [row["id"] for row in rows[: query.limit]]
        owners = self._owners(connection, ids, identities, captured)
        spaces = _previews(connection, self._space_facts(captured, ids), ids, "display_name")
        for row in rows[: query.limit]:
            row["owners"], row["owner_count"] = owners.get(row["id"], ([], 0))
            row["spaces"], row["space_count"] = spaces.get(row["id"], ([], 0))
        return total, rows

    @staticmethod
    def _space_facts(captured, property_ids=None):
        s, p = SpaceModel.__table__, PropertyModel.__table__
        period, a = SpaceOccupancyPeriodModel.__table__, SpaceAvailabilityModel.__table__
        local_day = func.portfolio_local_day(p.c.time_zone, captured)
        selected = literal(True) if property_ids is None else s.c.property_id.in_(property_ids)
        current = (
            select(
                period.c.space_id,
                period.c.occupancy_status,
                func.count().over(partition_by=period.c.space_id).label("current_count"),
                func.row_number()
                .over(partition_by=period.c.space_id, order_by=period.c.starts_on.desc())
                .label("position"),
            )
            .select_from(
                period.join(s, period.c.space_id == s.c.id).join(p, s.c.property_id == p.c.id)
            )
            .where(
                selected,
                period.c.record_state == "valid",
                period.c.starts_on <= local_day,
                or_(period.c.ends_on.is_(None), period.c.ends_on > local_day),
            )
            .subquery()
        )
        occupancy = func.coalesce(current.c.occupancy_status, "unknown")
        availability = case(
            (
                and_(a.c.availability_status == "available_on", a.c.available_on <= local_day),
                "available_now",
            ),
            else_=func.coalesce(a.c.availability_status, "unknown"),
        )
        return (
            select(
                s.c.id,
                s.c.property_id,
                s.c.display_name,
                s.c.status_revision.label("revision"),
                occupancy.label("occupancy"),
                availability.label("availability"),
                or_(
                    occupancy == "unknown", availability == "unknown", current.c.current_count > 1
                ).label("needs_attention"),
            )
            .select_from(
                s.join(p, s.c.property_id == p.c.id)
                .outerjoin(current, and_(current.c.space_id == s.c.id, current.c.position == 1))
                .outerjoin(a, a.c.space_id == s.c.id)
            )
            .where(s.c.status == "active", selected)
            .subquery("current_space_facts")
        )

    @staticmethod
    def _owners(connection, ids, identities, captured):
        if not ids:
            return {}
        o, p = PropertyOwnershipModel.__table__, PropertyModel.__table__
        local_day = func.portfolio_local_day(p.c.time_zone, captured)
        facts = (
            select(o.c.property_id, o.c.party_id, identities.c.display_name)
            .select_from(
                o.join(p, o.c.property_id == p.c.id).join(
                    identities, o.c.party_id == identities.c.party_id
                )
            )
            .where(
                o.c.property_id.in_(ids),
                o.c.owner_kind == "client_owner",
                o.c.starts_on <= local_day,
                or_(o.c.ends_on.is_(None), o.c.ends_on > local_day),
            )
            .distinct()
            .subquery()
        )
        return _previews(connection, facts, ids, "display_name")


def _previews(connection, facts, ids, label):
    if not ids:
        return {}
    identity = facts.c.id if "id" in facts.c else facts.c.party_id
    ranked = (
        select(
            *facts.c,
            func.count().over(partition_by=facts.c.property_id).label("total"),
            func.row_number()
            .over(
                partition_by=facts.c.property_id,
                order_by=(func.unicode_casefold(facts.c[label]), identity),
            )
            .label("position"),
        )
        .where(facts.c.property_id.in_(ids))
        .subquery()
    )
    items, totals = defaultdict(list), {}
    for row in connection.execute(
        select(ranked)
        .where(ranked.c.position <= RECOGNITION_PREVIEW_LIMIT)
        .order_by(ranked.c.property_id, ranked.c.position)
    ).mappings():
        totals[row["property_id"]] = row["total"]
        items[row["property_id"]].append(
            {
                key: value
                for key, value in row.items()
                if key not in {"property_id", "total", "position"}
            }
        )
    return {key: (value, totals[key]) for key, value in items.items()}


def _local_day(zone, instant):
    return datetime.fromisoformat(instant).astimezone(ZoneInfo(zone)).date().isoformat()


def _matches(column, query):
    # Literal substring matching: '%' and '_' do not become SQL wildcards.
    return func.instr(func.unicode_casefold(column), query) > 0

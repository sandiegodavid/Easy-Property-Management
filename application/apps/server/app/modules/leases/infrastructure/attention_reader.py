"""Lease review SQL facts using retained owner calendars and occupancy relations."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, exists, func, literal, or_, select

from app.modules.leases.application.location_ports import LeaseLocationRelation
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseRenewalOptionModel
from app.modules.portfolio.application.location_ports import PortfolioOccupancyRelations
from app.platform.attention_reads import (
    AttentionFact,
    AttentionPage,
    AttentionWindow,
    AttentionKey,
    AttentionReasonFact,
    AttentionDate,
)

REVIEW_LEAD_DAYS = 30


class SQLiteLeaseAttentionReader:
    def __init__(self, locations: LeaseLocationRelation, occupancy: PortfolioOccupancyRelations):
        self.locations, self.occupancy = locations, occupancy

    def facts(self, connection, window: AttentionWindow):
        if window.source_kind not in (None, "lease") or window.collection not in (
            "needs_action",
            "upcoming",
        ):
            raise ValueError(
                "Lease attention requires its source and a supported review collection."
            )
        database = connection.connection.driver_connection
        database.create_function("lease_attention_day", 2, _local_day, deterministic=True)
        database.create_function("lease_attention_offset", 3, _offset_day, deterministic=True)
        database.create_function("lease_attention_boundary", 2, _boundary, deterministic=True)
        lease = LeaseModel.__table__
        location, periods = self.locations.locations(), self.occupancy.occupancy_periods()
        day = func.lease_attention_day(location.c.time_zone, window.as_of.isoformat())
        current_period = and_(
            periods.c.space_id == lease.c.space_id,
            periods.c.record_state == "valid",
            periods.c.starts_on <= day,
            or_(periods.c.ends_on.is_(None), periods.c.ends_on > day),
        )
        own_occupancy = exists(
            select(1)
            .select_from(periods)
            .where(
                current_period,
                periods.c.occupancy_status == "occupied",
                periods.c.source_kind == "lease",
                periods.c.source_id == lease.c.id,
            )
        )
        closed = and_(lease.c.actual_move_out_on.is_not(None), lease.c.actual_move_out_on <= day)
        continued = and_(lease.c.contract_ends_on < day, ~closed, own_occupancy)
        near_end = lease.c.contract_ends_on <= func.lease_attention_offset(
            location.c.time_zone, window.as_of.isoformat(), REVIEW_LEAD_DAYS
        )
        future_end = lease.c.contract_ends_on <= func.lease_attention_offset(
            location.c.time_zone, window.as_of.isoformat(), window.horizon_days
        )
        # An exercised option or another contract on this Space does not create
        # an explicit successor link. Keep the original review until closure.
        renewal = LeaseRenewalOptionModel.__table__
        exercised = exists(
            select(1).where(
                renewal.c.lease_id == lease.c.id,
                renewal.c.status == "exercised",
                renewal.c.proposed_starts_on == lease.c.contract_ends_on,
            )
        )
        selection = (
            select(
                lease.c.id,
                lease.c.lease_revision,
                lease.c.status,
                lease.c.space_id,
                lease.c.contract_starts_on,
                lease.c.contract_ends_on,
                lease.c.actual_move_out_on,
                lease.c.updated_at,
                location.c.property_id,
                location.c.property_name,
                location.c.property_state,
                location.c.time_zone,
                own_occupancy.label("own_occupancy"),
                continued.label("continued_occupancy"),
                exercised.label("exercised_renewal"),
                case((near_end, "needs_action"), (future_end, "upcoming")).label("collection"),
                literal(3 if window.collection == "needs_action" else 0).label("sort_priority"),
                case((near_end, "review"), else_="future").label("priority_band"),
                func.lease_attention_boundary(location.c.time_zone, lease.c.contract_ends_on).label(
                    "sort_at"
                ),
                func.lease_attention_boundary(
                    location.c.time_zone,
                    func.lease_attention_offset(location.c.time_zone, window.as_of.isoformat(), 1),
                ).label("next_transition"),
            )
            .select_from(lease.join(location, lease.c.id == location.c.lease_id))
            .where(
                lease.c.status.in_(("executed", "ended", "terminated")),
                lease.c.contract_ends_on.is_not(None),
                ~closed,
            )
        )
        if window.property_id is not None:
            selection = selection.where(location.c.property_id == str(window.property_id))
        return selection.subquery("lease_attention_facts")

    def attention(self, connection, window):
        facts = self.facts(connection, window)
        f = facts.c
        matching = f.collection == window.collection
        counts = (
            connection.execute(
                select(
                    func.coalesce(func.sum(case((matching, 1), else_=0)), 0).label("total"),
                    func.coalesce(
                        func.sum(case((and_(matching, f.continued_occupancy), 1), else_=0)), 0
                    ).label("continued"),
                    func.min(f.next_transition).label("next_transition"),
                ).select_from(facts)
            )
            .mappings()
            .one()
        )
        statement = select(facts).where(matching)
        if window.after is not None:
            key = window.after
            statement = statement.where(
                or_(
                    f.sort_priority > key.priority,
                    and_(f.sort_priority == key.priority, f.sort_at > key.at.isoformat()),
                    and_(
                        f.sort_priority == key.priority,
                        f.sort_at == key.at.isoformat(),
                        literal("lease") > key.source_kind,
                    ),
                    and_(
                        f.sort_priority == key.priority,
                        f.sort_at == key.at.isoformat(),
                        literal("lease") == key.source_kind,
                        f.id > key.source_id,
                    ),
                )
            )
        rows = (
            connection.execute(
                statement.order_by(f.sort_priority, f.sort_at, f.id).limit(window.limit + 1)
            )
            .mappings()
            .all()
        )
        reason_counts = [("lease_review", counts["total"])] if counts["total"] else []
        if counts["continued"]:
            reason_counts.append(("continued_occupancy", counts["continued"]))
        result = AttentionPage(
            counts["total"],
            tuple(_fact(row) for row in rows),
            datetime.fromisoformat(counts["next_transition"])
            if counts["next_transition"]
            else None,
            (("review" if window.collection == "needs_action" else "future", counts["total"]),)
            if counts["total"]
            else (),
            tuple(reason_counts),
        )
        result.validate_window(window)
        return result


def _local_day(zone, captured):
    return datetime.fromisoformat(captured).astimezone(ZoneInfo(zone)).date().isoformat()


def _offset_day(zone, captured, days):
    return (date.fromisoformat(_local_day(zone, captured)) + timedelta(days=days)).isoformat()


def _boundary(zone, day):
    return (
        datetime.combine(date.fromisoformat(day), time.min, ZoneInfo(zone))
        .astimezone(UTC)
        .isoformat()
    )


def _fact(row):
    due = AttentionDate(row["time_zone"], on=date.fromisoformat(row["contract_ends_on"]))
    reasons = [
        AttentionReasonFact("lease_review", row["priority_band"], "lease", UUID(row["id"]), due)
    ]
    if row["continued_occupancy"]:
        reasons.append(
            AttentionReasonFact("continued_occupancy", "review", "lease", UUID(row["id"]), due)
        )
    return AttentionFact(
        AttentionKey(
            row["sort_priority"], datetime.fromisoformat(row["sort_at"]), "lease", row["id"]
        ),
        str(row["lease_revision"]),
        row["status"],
        f"Lease ending {row['contract_ends_on']}",
        tuple(reasons),
        property_id=UUID(row["property_id"]),
        space_id=UUID(row["space_id"]),
        time_zone=row["time_zone"],
        property_archived=row["property_state"] == "archived",
        source_deadline=due,
        lease_id=UUID(row["id"]),
        recorded_at=datetime.fromisoformat(row["updated_at"]),
    )

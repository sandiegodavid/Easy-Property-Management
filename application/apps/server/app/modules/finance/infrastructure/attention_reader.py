"""Bounded rent attention from current corrected Finance facts, not cash totals."""

import hashlib
import json
from datetime import date, datetime, timedelta, time, UTC
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, literal, or_, select

from app.modules.finance.application.money_models import MoneyUnavailable
from app.modules.finance.infrastructure.sqlalchemy_models import (
    RentExpectationModel,
    RentReceiptModel,
    RentReceiptAllocationModel,
    RentExpectationTimelinessReviewModel,
)
from app.modules.leases.application.location_ports import LeaseLocationRelation
from app.platform.attention_reads import (
    AttentionFact,
    AttentionPage,
    AttentionKey,
    AttentionDate,
    AttentionReasonFact,
    AttentionWindow,
)


class SQLiteRentAttentionReader:
    def __init__(self, leases: LeaseLocationRelation):
        self.leases = leases

    def facts(self, connection, window: AttentionWindow):
        if window.source_kind not in (None, "rent_expectation") or window.collection not in (
            "needs_action",
            "upcoming",
        ):
            raise ValueError(
                "Rent attention requires its source and a supported primary collection."
            )
        database = connection.connection.driver_connection
        database.create_function("rent_attention_day", 2, _local_day, deterministic=True)
        database.create_function("rent_attention_horizon", 3, _horizon_day, deterministic=True)
        database.create_function("rent_attention_boundary", 2, _boundary, deterministic=True)
        e, r, a, review = (
            model.__table__
            for model in (
                RentExpectationModel,
                RentReceiptModel,
                RentReceiptAllocationModel,
                RentExpectationTimelinessReviewModel,
            )
        )
        locations = self.leases.locations()
        allocation = (
            select(
                a.c.expectation_id,
                func.sum(case((r.c.voided_at.is_(None), a.c.amount_minor), else_=0)).label(
                    "received_minor"
                ),
                func.count().label("allocation_count"),
                func.max(r.c.created_at).label("last_activity"),
                func.max(r.c.voided_at).label("last_void"),
                func.max(
                    case((and_(r.c.voided_at.is_(None), r.c.lease_id != e.c.lease_id), 1), else_=0)
                ).label("invalid_lease"),
            )
            .select_from(a.join(r, a.c.receipt_id == r.c.id).join(e, a.c.expectation_id == e.c.id))
            .group_by(a.c.expectation_id)
            .subquery("rent_attention_allocations")
        )
        reviews = select(
            review.c.id,
            review.c.expectation_id,
            review.c.decision,
            review.c.created_at,
            func.row_number()
            .over(
                partition_by=review.c.expectation_id,
                order_by=(review.c.created_at.desc(), review.c.id.desc()),
            )
            .label("position"),
        ).subquery("rent_attention_reviews")
        received = func.coalesce(allocation.c.received_minor, 0)
        outstanding = e.c.expected_amount_minor - received
        day = func.rent_attention_day(locations.c.time_zone, window.as_of.isoformat())
        late, today = e.c.due_on < day, e.c.due_on == day
        missed = and_(
            late,
            received == 0,
            day > e.c.period_ends_on,
            reviews.c.decision == "mark_missed",
            or_(
                allocation.c.last_activity.is_(None),
                allocation.c.last_activity <= reviews.c.created_at,
            ),
        )
        upcoming = and_(
            e.c.due_on > day,
            e.c.due_on
            <= func.rent_attention_horizon(
                locations.c.time_zone, window.as_of.isoformat(), window.horizon_days
            ),
        )
        statement = (
            select(
                e.c.id,
                e.c.lease_id,
                e.c.lease_term_id,
                e.c.period_starts_on,
                e.c.period_ends_on,
                e.c.due_on,
                e.c.expected_amount_minor,
                e.c.currency_code,
                e.c.created_at,
                locations.c.property_id,
                locations.c.property_name,
                locations.c.property_state,
                locations.c.space_id,
                locations.c.time_zone,
                received.label("received_minor"),
                outstanding.label("outstanding_minor"),
                func.coalesce(allocation.c.allocation_count, 0).label("allocation_count"),
                allocation.c.last_activity,
                allocation.c.last_void,
                func.coalesce(allocation.c.invalid_lease, 0).label("invalid_lease"),
                reviews.c.id.label("review_id"),
                reviews.c.decision.label("review_decision"),
                reviews.c.created_at.label("reviewed_at"),
                case((late, "needs_action"), (today, "needs_action"), (upcoming, "upcoming")).label(
                    "collection"
                ),
                case((late, 1), (today, 2), else_=0).label("sort_priority"),
                case((late, "overdue"), (today, "today"), else_="future").label("priority_band"),
                case((late, "overdue"), (today, "due_today"), else_="scheduled").label("reason"),
                case((missed, "missed"), (late, "late"), (today, "due"), else_="upcoming").label(
                    "timeliness"
                ),
                case((received > 0, "partial"), else_="unpaid").label("settlement"),
                func.rent_attention_boundary(locations.c.time_zone, e.c.due_on).label("sort_at"),
                func.rent_attention_boundary(
                    locations.c.time_zone,
                    func.rent_attention_horizon(locations.c.time_zone, window.as_of.isoformat(), 1),
                ).label("next_transition"),
            )
            .select_from(
                e.outerjoin(locations, e.c.lease_id == locations.c.lease_id)
                .outerjoin(allocation, allocation.c.expectation_id == e.c.id)
                .outerjoin(
                    reviews, and_(reviews.c.expectation_id == e.c.id, reviews.c.position == 1)
                )
            )
            .where(e.c.voided_at.is_(None))
        )
        if window.property_id is not None:
            statement = statement.where(locations.c.property_id == str(window.property_id))
        return statement.subquery("rent_attention_facts")

    def attention(self, connection, window):
        facts = self.facts(connection, window)
        f = facts.c
        eligible = and_(f.outstanding_minor > 0, f.collection == window.collection)
        invalid = or_(
            f.property_id.is_(None),
            f.space_id.is_(None),
            f.time_zone.is_(None),
            f.currency_code != "USD",
            f.outstanding_minor < 0,
            f.invalid_lease != 0,
        )
        totals = (
            connection.execute(
                select(
                    func.coalesce(func.sum(case((eligible, 1), else_=0)), 0).label("total"),
                    func.coalesce(func.sum(case((invalid, 1), else_=0)), 0).label("invalid"),
                    func.min(case((f.outstanding_minor > 0, f.next_transition))).label(
                        "next_transition"
                    ),
                    *(
                        func.coalesce(
                            func.sum(case((and_(eligible, f.priority_band == band), 1), else_=0)), 0
                        ).label(band)
                        for band in ("overdue", "today", "future")
                    ),
                ).select_from(facts)
            )
            .mappings()
            .one()
        )
        if totals["invalid"]:
            raise MoneyUnavailable("Rent attention source integrity could not be established.")
        selection = select(facts).where(eligible)
        if window.after is not None:
            key = window.after
            selection = selection.where(
                or_(
                    f.sort_priority > key.priority,
                    and_(f.sort_priority == key.priority, f.sort_at > key.at.isoformat()),
                    and_(
                        f.sort_priority == key.priority,
                        f.sort_at == key.at.isoformat(),
                        literal("rent_expectation") > key.source_kind,
                    ),
                    and_(
                        f.sort_priority == key.priority,
                        f.sort_at == key.at.isoformat(),
                        literal("rent_expectation") == key.source_kind,
                        f.id > key.source_id,
                    ),
                )
            )
        rows = (
            connection.execute(
                selection.order_by(f.sort_priority, f.sort_at, f.id).limit(window.limit + 1)
            )
            .mappings()
            .all()
        )
        page = AttentionPage(
            totals["total"],
            tuple(_fact(row) for row in rows),
            datetime.fromisoformat(totals["next_transition"])
            if totals["next_transition"]
            else None,
            tuple((band, totals[band]) for band in ("overdue", "today", "future") if totals[band]),
            tuple(
                (code, totals[band])
                for code, band in (
                    ("overdue", "overdue"),
                    ("due_today", "today"),
                    ("scheduled", "future"),
                )
                if totals[band]
            ),
        )
        page.validate_window(window)
        return page


def _local_day(zone, captured):
    return (
        datetime.fromisoformat(captured).astimezone(ZoneInfo(zone)).date().isoformat()
        if zone
        else None
    )


def _horizon_day(zone, captured, horizon):
    return (
        (date.fromisoformat(_local_day(zone, captured)) + timedelta(days=horizon)).isoformat()
        if zone
        else None
    )


def _boundary(zone, on):
    return (
        datetime.combine(date.fromisoformat(on), time.min, ZoneInfo(zone))
        .astimezone(UTC)
        .isoformat()
        if zone
        else None
    )


def _fact(row):
    revision = hashlib.sha256(
        json.dumps(
            {
                name: row[name]
                for name in (
                    "id",
                    "received_minor",
                    "allocation_count",
                    "last_activity",
                    "last_void",
                    "review_id",
                    "timeliness",
                )
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    due = AttentionDate(row["time_zone"], on=date.fromisoformat(row["due_on"]))
    return AttentionFact(
        AttentionKey(
            row["sort_priority"],
            datetime.fromisoformat(row["sort_at"]),
            "rent_expectation",
            row["id"],
        ),
        revision,
        row["timeliness"],
        f"Rent {row['period_starts_on']} – {row['period_ends_on']}",
        (
            AttentionReasonFact(
                row["reason"], row["priority_band"], "rent_expectation", UUID(row["id"]), due
            ),
        ),
        property_id=UUID(row["property_id"]),
        space_id=UUID(row["space_id"]),
        time_zone=row["time_zone"],
        property_archived=row["property_state"] == "archived",
        source_deadline=due,
        recorded_at=datetime.fromisoformat(row["created_at"]),
        outstanding_minor=row["outstanding_minor"],
        currency="USD",
        lease_id=UUID(row["lease_id"]),
        expected_minor=row["expected_amount_minor"],
        received_minor=row["received_minor"],
        period_starts_on=date.fromisoformat(row["period_starts_on"]),
        period_ends_on=date.fromisoformat(row["period_ends_on"]),
    )

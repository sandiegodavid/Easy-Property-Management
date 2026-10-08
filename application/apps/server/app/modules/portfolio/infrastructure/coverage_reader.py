"""Bounded Portfolio coverage selection and set-based temporal fact hydration."""

from collections import defaultdict
from zoneinfo import ZoneInfo

from sqlalchemy import select, or_, literal, union_all, func, case

from app.modules.portfolio.application.coverage_ports import CoverageLocation
from app.modules.portfolio.infrastructure.sqlalchemy_models import (
    PropertyModel,
    SpaceModel,
    SpaceOccupancyPeriodModel,
    SpaceAvailabilityModel,
)
from app.platform.coverage import (
    CoverageSubject,
    bounded_subjects,
    COVERAGE_PREVIEW_LIMIT,
    evidence_revision,
)
from app.platform.context_reads import ReadPage
from app.platform.sql_context_reads import bounded_page


class SQLitePortfolioCoverageReader:
    def location(self, connection, subject, *, as_of):
        return self.locations(connection, [subject], as_of=as_of).get(subject)

    def locations(self, connection, subjects, *, as_of):
        subjects = bounded_subjects(subjects)
        if not subjects:
            return {}
        p, s = PropertyModel.__table__, SpaceModel.__table__
        properties = [item.id for item in subjects if item.kind == "property"]
        spaces = [item.id for item in subjects if item.kind == "space"]
        selection = union_all(
            select(
                literal("property").label("kind"),
                p.c.id.label("subject_id"),
                p.c.id.label("property_id"),
                p.c.time_zone,
            ).where(p.c.id.in_(properties)),
            select(literal("space"), s.c.id, p.c.id, p.c.time_zone)
            .join(p, s.c.property_id == p.c.id)
            .where(s.c.id.in_(spaces)),
        )
        rows = connection.execute(selection).mappings().all()
        dates = {
            row["subject_id"]: as_of.astimezone(ZoneInfo(row["time_zone"])).date().isoformat()
            for row in rows
            if row["kind"] == "space"
        }
        periods, availability = defaultdict(list), {}
        if dates:
            o, a = SpaceOccupancyPeriodModel.__table__, SpaceAvailabilityModel.__table__
            day = case(dates, value=o.c.space_id)
            ranked = (
                select(
                    o.c.space_id,
                    o.c.id,
                    o.c.occupancy_status,
                    o.c.source_kind,
                    o.c.source_id,
                    o.c.starts_on,
                    o.c.ends_on,
                    func.row_number()
                    .over(partition_by=o.c.space_id, order_by=o.c.id)
                    .label("position"),
                )
                .where(
                    o.c.space_id.in_(dates),
                    o.c.record_state == "valid",
                    o.c.starts_on <= day,
                    or_(o.c.ends_on.is_(None), o.c.ends_on > day),
                )
                .subquery()
            )
            for item in connection.execute(
                select(ranked)
                .where(ranked.c.position <= 2)
                .order_by(ranked.c.space_id, ranked.c.position)
            ).mappings():
                periods[item["space_id"]].append(
                    {
                        key: item[key]
                        for key in (
                            "id",
                            "occupancy_status",
                            "source_kind",
                            "source_id",
                            "starts_on",
                            "ends_on",
                        )
                    }
                )
            for item in connection.execute(
                select(
                    a.c.space_id,
                    a.c.availability_status,
                    a.c.available_on,
                    a.c.source_kind,
                    a.c.source_id,
                ).where(a.c.space_id.in_(dates))
            ).mappings():
                availability[item["space_id"]] = {
                    key: item[key]
                    for key in ("availability_status", "available_on", "source_kind", "source_id")
                }
        return {
            CoverageSubject(row["kind"], row["subject_id"]): _location(
                row,
                periods[row["subject_id"]],
                availability.get(row["subject_id"]),
                dates.get(row["subject_id"]),
            )
            for row in rows
        }

    def page_for_properties(self, connection, properties, window):
        selection = _subjects(properties, window.include_history)
        return bounded_page(connection, selection, window)

    def previews_for_groups(self, connection, groups, *, as_of, include_history):
        selection = _subjects(groups, include_history, grouped=True).subquery()
        ranked = select(
            *selection.c,
            func.count().over(partition_by=selection.c.group_id).label("total"),
            func.row_number()
            .over(
                partition_by=selection.c.group_id, order_by=(selection.c.sort_key, selection.c.id)
            )
            .label("position"),
        ).subquery()
        rows = connection.execute(
            select(ranked)
            .where(ranked.c.position <= COVERAGE_PREVIEW_LIMIT)
            .order_by(ranked.c.group_id, ranked.c.position)
        ).mappings()
        result = {}
        for row in rows:
            total, items = result.setdefault(row["group_id"], (row["total"], []))
            items.append(row)
        return {key: ReadPage(total, items, None) for key, (total, items) in result.items()}


def _subjects(properties, include_history, grouped=False):
    p, s = PropertyModel.__table__, SpaceModel.__table__
    prefix = func.unicode_casefold(p.c.display_name) + literal(":") + p.c.id + literal(":")
    extra = [properties.c.group_id] if grouped else []
    maintenance = select(
        *extra,
        p.c.id,
        literal("property").label("subject_kind"),
        literal("maintenance").label("area"),
        p.c.id.label("property_id"),
        (prefix + literal("0")).label("sort_key"),
    ).select_from(p.join(properties, properties.c.property_id == p.c.id))
    selections = [maintenance]
    for position, area in enumerate(("occupancy", "lease", "rent", "deposit")):
        selection = select(
            *extra,
            s.c.id,
            literal("space").label("subject_kind"),
            literal(area).label("area"),
            p.c.id.label("property_id"),
            (
                prefix
                + literal("1:")
                + func.unicode_casefold(s.c.display_name)
                + literal(":")
                + s.c.id
                + literal(f":{position}")
            ).label("sort_key"),
        ).select_from(
            s.join(p, s.c.property_id == p.c.id).join(
                properties, properties.c.property_id == p.c.id
            )
        )
        if not include_history:
            selection = selection.where(or_(s.c.status == "active", p.c.status == "archived"))
        selections.append(selection)
    return select(*union_all(*selections).subquery().c)


def _location(row, periods, available, day):
    if row["kind"] == "property":
        return CoverageLocation(
            row["property_id"],
            row["time_zone"],
            None,
            None,
            None,
            None,
            evidence_revision({"id": row["property_id"], "time_zone": row["time_zone"]}),
        )
    current = periods[0] if len(periods) == 1 else None
    status = available["availability_status"] if available else "unknown"
    if status == "available_on" and available["available_on"] <= day:
        status = "available_now"
    revision = evidence_revision(
        {
            "periods": periods,
            "availability": available,
            "effective_availability": status,
            "time_zone": row["time_zone"],
        }
    )
    return CoverageLocation(
        row["property_id"],
        row["time_zone"],
        current["occupancy_status"] if current else "conflicting",
        status,
        current["source_kind"] if current else None,
        current["source_id"] if current else None,
        revision,
    )

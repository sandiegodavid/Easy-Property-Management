"""Set-based DASH portfolio facts on the composing caller's connection."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select, literal, union_all

from app.modules.portfolio.application.attention_calendar import (
    attention_instant,
    calendar_boundaries,
    local_day,
    next_midnight,
)
from app.modules.portfolio.application.attention_ports import (
    MAX_CALENDAR_PROPERTIES,
    PortfolioAttentionError,
    PortfolioAttentionNotFound,
    InventorySpace,
    InventorySpacePage,
    AttentionLocationLabels,
)
from app.modules.portfolio.infrastructure.sqlalchemy_models import (
    PropertyModel,
    SpaceModel,
    SpaceOccupancyPeriodModel,
)
from app.platform.attention_reads import InventoryFacts, PropertyCalendar


class SQLitePortfolioAttentionReader:
    def occupancy_periods(self):
        period = SpaceOccupancyPeriodModel.__table__
        return select(
            period.c.space_id,
            period.c.occupancy_status,
            period.c.starts_on,
            period.c.ends_on,
            period.c.record_state,
            period.c.source_kind,
            period.c.source_id,
        ).subquery("retained_occupancy_periods")

    def properties(self, property_id=None, *, inventory_only=False):
        p = PropertyModel.__table__
        statement = select(
            p.c.id.label("property_id"),
            p.c.display_name.label("property_name"),
            p.c.status.label("property_state"),
            p.c.time_zone,
        )
        if property_id is not None:
            statement = statement.where(p.c.id == str(property_id))
        if inventory_only:
            statement = statement.where(p.c.status == "active")
        return statement.subquery("attention_properties")

    def spaces(self, property_id=None, *, inventory_only=False):
        s = SpaceModel.__table__
        properties = self.properties(property_id, inventory_only=inventory_only)
        statement = select(
            s.c.id.label("space_id"),
            s.c.display_name.label("space_name"),
            s.c.status.label("space_state"),
            properties,
        ).select_from(s.join(properties, s.c.property_id == properties.c.property_id))
        if inventory_only:
            statement = statement.where(s.c.status == "active")
        return statement.subquery("attention_spaces")

    def validate_scope(self, connection, property_id):
        if property_id is None:
            return
        found = connection.execute(
            select(PropertyModel.id).where(PropertyModel.id == str(property_id)).limit(1)
        ).first()
        if found is None:
            raise PortfolioAttentionNotFound("The selected property does not exist.")

    def calendars(self, connection, property_ids, as_of, horizon_days):
        attention_instant(as_of)
        if type(horizon_days) is not int or horizon_days not in (7, 30, 90):
            raise PortfolioAttentionError("Portfolio attention horizon must be 7, 30 or 90 days.")
        identities = tuple(dict.fromkeys(str(UUID(str(identity))) for identity in property_ids))
        if len(identities) > MAX_CALENDAR_PROPERTIES:
            raise PortfolioAttentionError("Calendar hydration permits at most 100 properties.")
        if not identities:
            return ()
        p = PropertyModel.__table__
        rows = connection.execute(
            select(p.c.id, p.c.display_name, p.c.time_zone, p.c.status)
            .where(p.c.id.in_(identities))
            .order_by(p.c.id)
        ).mappings()
        return tuple(
            PropertyCalendar(
                UUID(row["id"]),
                row["time_zone"],
                *calendar_boundaries(row["time_zone"], as_of, horizon_days),
                row["status"] == "archived",
                row["display_name"],
            )
            for row in rows
        )

    def attention_labels(self, connection, property_ids, space_ids):
        statements, result = [], {"property": {}, "space": {}}
        for kind, model, ids in (
            ("property", PropertyModel, property_ids),
            ("space", SpaceModel, space_ids),
        ):
            identities = tuple(dict.fromkeys(str(UUID(str(identity))) for identity in ids))
            if len(identities) > MAX_CALENDAR_PROPERTIES:
                raise PortfolioAttentionError(
                    "Location hydration permits at most 100 identities per kind."
                )
            if identities:
                statements.append(
                    select(literal(kind), model.id, model.display_name).where(
                        model.id.in_(identities)
                    )
                )
        if statements:
            for kind, identity, name in connection.execute(union_all(*statements)):
                result[kind][UUID(identity)] = name
        return AttentionLocationLabels(result["property"], result["space"])

    def inventory(self, connection, property_id, as_of):
        captured, properties, current = self._inventory_scope(connection, property_id, as_of)
        counts = (
            select(
                func.count().label("spaces"),
                func.coalesce(
                    func.sum(case((current.c.occupancy == "vacant", 1), else_=0)), 0
                ).label("vacant"),
                func.coalesce(
                    func.sum(case((current.c.occupancy == "unknown", 1), else_=0)), 0
                ).label("unknown"),
            )
            .select_from(current)
            .subquery("attention_inventory_counts")
        )
        property_counts = (
            select(
                func.count().label("properties"),
                func.min(func.attention_next_midnight(properties.c.time_zone, captured)).label(
                    "next_transition"
                ),
            )
            .select_from(properties)
            .subquery("attention_property_counts")
        )
        found = (
            literal(True)
            if property_id is None
            else select(PropertyModel.id).where(PropertyModel.id == str(property_id)).exists()
        )
        row = (
            connection.execute(
                select(counts, property_counts, found.label("scope_exists")).select_from(
                    counts.join(property_counts, and_(True))
                )
            )
            .mappings()
            .one()
        )
        if not row["scope_exists"]:
            raise PortfolioAttentionNotFound("The selected property does not exist.")
        return InventoryFacts(
            row["vacant"],
            row["unknown"],
            row["properties"],
            row["spaces"],
            datetime.fromisoformat(row["next_transition"]) if row["next_transition"] else None,
        )

    def inventory_spaces(self, connection, property_id, as_of, occupancy, *, limit=50, after=None):
        if (
            occupancy not in ("vacant", "unknown")
            or type(limit) is not int
            or not 1 <= limit <= MAX_CALENDAR_PROPERTIES
        ):
            raise PortfolioAttentionError("Inventory selection or page bounds are invalid.")
        if after is not None:
            try:
                if not isinstance(after, tuple) or len(after) != 2:
                    raise ValueError()
                property_key, space_key = (str(UUID(value)) for value in after)
            except (TypeError, ValueError, AttributeError) as error:
                raise PortfolioAttentionError(
                    "Inventory continuation requires property and space identities."
                ) from error
        _, _, current = self._inventory_scope(connection, property_id, as_of)
        predicate = current.c.occupancy == occupancy
        found = (
            literal(True)
            if property_id is None
            else select(PropertyModel.id).where(PropertyModel.id == str(property_id)).exists()
        )
        counts = (
            connection.execute(
                select(func.count().label("total"), found.label("scope_exists"))
                .select_from(current)
                .where(predicate)
            )
            .mappings()
            .one()
        )
        if not counts["scope_exists"]:
            raise PortfolioAttentionNotFound("The selected property does not exist.")
        total = counts["total"]
        selected = select(current).where(predicate)
        if after is not None:
            selected = selected.where(
                or_(
                    current.c.property_id > property_key,
                    and_(current.c.property_id == property_key, current.c.space_id > space_key),
                )
            )
        rows = (
            connection.execute(
                selected.order_by(current.c.property_id, current.c.space_id).limit(limit + 1)
            )
            .mappings()
            .all()
        )
        items = tuple(
            InventorySpace(
                UUID(row["property_id"]),
                row["property_name"],
                UUID(row["space_id"]),
                row["space_name"],
                row["occupancy"],
                row["time_zone"],
            )
            for row in rows[:limit]
        )
        next_key = (
            (str(items[-1].property_id), str(items[-1].space_id)) if len(rows) > limit else None
        )
        return InventorySpacePage(total, items, next_key)

    def _inventory_scope(self, connection, property_id, as_of):
        captured = attention_instant(as_of).isoformat()
        database = connection.connection.driver_connection
        database.create_function("attention_local_day", 2, local_day, deterministic=True)
        database.create_function("attention_next_midnight", 2, next_midnight, deterministic=True)
        properties = self.properties(property_id, inventory_only=True)
        spaces = self.spaces(property_id, inventory_only=True)
        periods = SpaceOccupancyPeriodModel.__table__
        day = func.attention_local_day(spaces.c.time_zone, captured)
        current = (
            select(
                spaces.c.space_id,
                spaces.c.space_name,
                spaces.c.property_id,
                spaces.c.property_name,
                spaces.c.time_zone,
                case(
                    (func.count(periods.c.id) == 1, func.min(periods.c.occupancy_status)),
                    else_="unknown",
                ).label("occupancy"),
            )
            .select_from(
                spaces.outerjoin(
                    periods,
                    and_(
                        periods.c.space_id == spaces.c.space_id,
                        periods.c.record_state == "valid",
                        periods.c.starts_on <= day,
                        or_(periods.c.ends_on.is_(None), periods.c.ends_on > day),
                    ),
                )
            )
            .group_by(spaces.c.space_id)
            .subquery("attention_current_occupancy")
        )
        return captured, properties, current

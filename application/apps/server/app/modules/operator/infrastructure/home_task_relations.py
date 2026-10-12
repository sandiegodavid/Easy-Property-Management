"""Compose source-owned Task locations without querying foreign persistence."""

from sqlalchemy import select, literal, union_all

from app.modules.portfolio.application.location_ports import PortfolioLocationRelations
from app.modules.leases.application.location_ports import LeaseLocationRelation
from app.modules.tasks.application.attention_ports import TaskAttentionLocationSource


class HomeTaskRelations:
    def __init__(
        self,
        portfolio: PortfolioLocationRelations,
        leases: LeaseLocationRelation,
        issues: TaskAttentionLocationSource,
        concerns: TaskAttentionLocationSource,
        *,
        additional: tuple[TaskAttentionLocationSource, ...] = (),
    ):
        self.portfolio, self.leases, self.issues, self.concerns = (
            portfolio,
            leases,
            issues,
            concerns,
        )
        self.additional = additional

    def locations(self, property_id):
        properties, spaces, leases = (
            self.portfolio.properties(),
            self.portfolio.spaces(),
            self.leases.locations(),
        )
        selections = []
        for kind, source, identity, space in (
            ("property", properties, properties.c.property_id, literal(None)),
            (
                "space",
                spaces.join(properties, spaces.c.property_id == properties.c.property_id),
                spaces.c.space_id,
                spaces.c.space_id,
            ),
            ("lease", leases, leases.c.lease_id, leases.c.space_id),
        ):
            prop = leases if kind == "lease" else properties
            selections.append(
                select(
                    literal(kind).label("entity_type"),
                    identity.label("entity_id"),
                    prop.c.property_id,
                    space.label("space_id"),
                    (prop.c.property_state == "archived").label("property_archived"),
                    literal(None).label("group_kind"),
                    literal(False).label("parent_active"),
                ).select_from(source)
            )
        selections.extend(
            (select(self.issues.task_locations()), select(self.concerns.task_locations()))
        )
        selections.extend(select(source.task_locations()) for source in self.additional)
        relation = union_all(*selections).subquery("home_task_locations")
        if property_id is not None:
            relation = select(relation).where(relation.c.property_id == str(property_id)).subquery()
        return relation

"""Owner concern attention through explicit owning follow-ups, not context guesses."""

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, case, func, literal, select

from app.modules.owner_management.infrastructure.sqlalchemy_models import (
    OwnerConcernModel,
    OwnerConcernFollowUpOperationModel,
)
from app.modules.portfolio.application.location_ports import PortfolioLocationRelations
from app.modules.tasks.application.attention_ports import TaskAttentionReader
from app.platform.attention_reads import (
    AttentionChild,
    AttentionFact,
    AttentionKey,
    AttentionPage,
    AttentionReasonFact,
    AttentionRelation,
)
from app.platform.sql_attention_reads import attention_rows, PRIORITY_BANDS

TASK_CODES = ("overdue", "due_today", "follow_up_due", "reminder_due", "undated")
REASON_CODES = ("unresolved", "waiting", *TASK_CODES)
REVIEW_BOUNDARY = "9999-12-31T00:00:00+00:00"


class SQLiteConcernTaskLocations:
    def __init__(self, locations: PortfolioLocationRelations):
        self.locations = locations

    def task_locations(self):
        concerns, properties = OwnerConcernModel.__table__, self.locations.properties()
        return (
            select(
                literal("owner_concern").label("entity_type"),
                concerns.c.id.label("entity_id"),
                concerns.c.property_id,
                concerns.c.space_id,
                (properties.c.property_state == "archived").label("property_archived"),
                literal("concern_follow_up").label("group_kind"),
                concerns.c.status.in_(("open", "in_progress")).label("parent_active"),
            )
            .join(properties, properties.c.property_id == concerns.c.property_id)
            .subquery()
        )


class SQLiteOwnerConcernAttentionReader:
    def __init__(self, locations: PortfolioLocationRelations, tasks: TaskAttentionReader):
        self.locations, self.tasks = locations, tasks

    def follow_up_relations(self):
        links = OwnerConcernFollowUpOperationModel.__table__
        concerns = OwnerConcernModel.__table__
        return (
            select(links.c.concern_id, links.c.task_id)
            .join(concerns, concerns.c.id == links.c.concern_id)
            .where(concerns.c.status.in_(("open", "in_progress")))
            .distinct()
            .subquery("concern_follow_ups")
        )

    def _linked_tasks(self, connection, window):
        tasks = self.tasks.facts(
            connection, replace(window, source_kind="task", collection="needs_action")
        )
        links = self.follow_up_relations()
        return (
            select(tasks, links.c.concern_id)
            .select_from(links.join(tasks, links.c.task_id == tasks.c.id))
            .where(
                tasks.c.related_entity_type == "owner_concern",
                tasks.c.related_entity_id == links.c.concern_id,
            )
            .subquery("concern_explicit_task_facts")
        )

    def facts(self, connection, window):
        if window.source_kind not in (None, "owner_concern") or window.collection not in (
            "needs_action",
            "waiting",
            "upcoming",
        ):
            raise ValueError("Owner concerns require a supported primary collection.")
        c, p = OwnerConcernModel.__table__, self.locations.properties()
        linked = self._linked_tasks(connection, window)
        ranked = select(
            linked,
            func.row_number()
            .over(
                partition_by=linked.c.concern_id,
                order_by=(
                    (linked.c.collection == "needs_action").desc(),
                    linked.c.sort_priority,
                    linked.c.sort_at,
                    linked.c.id,
                ),
            )
            .label("position"),
        ).subquery("ranked_concern_tasks")
        t = ranked.c
        children = (
            select(
                t.concern_id,
                func.count().label("child_count"),
                func.max(t.collection == "waiting").label("has_waiting"),
                func.max(t.collection == "needs_action").label("has_action"),
                func.min(case((t.collection == "needs_action", t.sort_priority))).label(
                    "action_priority"
                ),
                func.min(
                    case((and_(t.collection == "needs_action", t.position == 1), t.sort_at))
                ).label("action_at"),
                func.min(case((t.collection == "waiting", t.sort_at))).label("waiting_at"),
                func.min(case((t.collection == "waiting", t.sort_priority))).label(
                    "waiting_priority"
                ),
                func.min(t.next_transition).label("next_transition"),
                *(func.max(t[code]).label(code) for code in TASK_CODES),
            )
            .group_by(t.concern_id)
            .subquery("concern_children")
        )
        b = children.c
        waiting = and_(
            c.c.priority != "urgent",
            func.coalesce(b.has_waiting, False),
            ~func.coalesce(b.has_action, False),
        )
        priority = case(
            (c.c.priority == "urgent", 0),
            (waiting, b.waiting_priority),
            else_=func.coalesce(b.action_priority, 3),
        )
        statement = (
            select(
                c.c.id,
                c.c.revision,
                c.c.status,
                c.c.summary.label("title"),
                c.c.owner_party_id,
                c.c.owner_display_name_snapshot,
                c.c.property_id,
                c.c.space_id,
                c.c.lease_id,
                p.c.time_zone,
                p.c.property_state,
                c.c.recorded_at_utc.label("recorded_at"),
                case((waiting, "waiting"), else_="needs_action").label("collection"),
                priority.label("sort_priority"),
                case(
                    (priority == 0, "urgent"),
                    (priority == 1, "overdue"),
                    (priority == 2, "today"),
                    (waiting, "waiting"),
                    else_="review",
                ).label("priority_band"),
                case(
                    (c.c.priority == "urgent", c.c.raised_at_utc),
                    (waiting, b.waiting_at),
                    else_=func.coalesce(b.action_at, REVIEW_BOUNDARY),
                ).label("sort_at"),
                (~waiting).label("unresolved"),
                waiting.label("waiting"),
                *(func.coalesce(b[code], False).label(code) for code in TASK_CODES),
                func.coalesce(b.child_count, 0).label("child_count"),
                b.next_transition,
            )
            .select_from(
                c.join(p, c.c.property_id == p.c.property_id).outerjoin(
                    children, b.concern_id == c.c.id
                )
            )
            .where(c.c.status.in_(("open", "in_progress")))
        )
        if window.property_id is not None:
            statement = statement.where(c.c.property_id == str(window.property_id))
        return statement.subquery("owner_concern_attention")

    def attention(self, connection, window):
        counts, rows = attention_rows(
            connection, self.facts(connection, window), window, "owner_concern", REASON_CODES
        )
        children = self._children(connection, rows, window)
        result = AttentionPage(
            counts["total"],
            tuple(_fact(row, children.get(row["id"], ())) for row in rows),
            datetime.fromisoformat(counts["next_transition"])
            if counts["next_transition"]
            else None,
            tuple(
                (band, counts[f"band_{band}"]) for band in PRIORITY_BANDS if counts[f"band_{band}"]
            ),
            tuple(
                (code, counts[f"reason_{code}"])
                for code in REASON_CODES
                if counts[f"reason_{code}"]
            ),
        )
        result.validate_window(window)
        return result

    def _children(self, connection, rows, window):
        if not rows:
            return {}
        linked = self._linked_tasks(connection, window)
        ranked = (
            select(
                linked.c.concern_id,
                linked.c.id,
                func.row_number()
                .over(
                    partition_by=linked.c.concern_id,
                    order_by=(
                        (linked.c.collection == "needs_action").desc(),
                        linked.c.sort_priority,
                        linked.c.sort_at,
                        linked.c.id,
                    ),
                )
                .label("position"),
            )
            .where(linked.c.concern_id.in_(tuple(row["id"] for row in rows)))
            .subquery()
        )
        pairs = (
            connection.execute(
                select(ranked)
                .where(ranked.c.position <= 3)
                .order_by(ranked.c.concern_id, ranked.c.position)
            )
            .mappings()
            .all()
        )
        tasks = self.tasks.hydrate(
            connection,
            tuple(UUID(pair["id"]) for pair in pairs),
            replace(window, source_kind="task", collection="needs_action"),
        )
        by_id = {task.key.source_id: task for task in tasks}
        children = {}
        for pair in pairs:
            task = by_id[pair["id"]]
            children.setdefault(pair["concern_id"], []).append(
                AttentionChild(
                    AttentionRelation(
                        "concern_follow_up",
                        "owner_concern",
                        UUID(pair["concern_id"]),
                        "task",
                        UUID(pair["id"]),
                    ),
                    task.reasons,
                    task.source_revision,
                    task.status,
                    children=task.children,
                    child_count=task.child_count,
                )
            )
        return children


def _fact(row, children):
    priorities = {
        "unresolved": "review",
        "waiting": "waiting",
        "overdue": "overdue",
        "due_today": "today",
        "follow_up_due": "today",
        "reminder_due": "today",
        "undated": "review",
    }
    return AttentionFact(
        AttentionKey(
            row["sort_priority"], datetime.fromisoformat(row["sort_at"]), "owner_concern", row["id"]
        ),
        str(row["revision"]),
        row["status"],
        row["title"],
        tuple(
            AttentionReasonFact(code, priorities[code], "owner_concern", UUID(row["id"]))
            for code in REASON_CODES
            if row[code]
        ),
        property_id=UUID(row["property_id"]),
        space_id=UUID(row["space_id"]) if row["space_id"] else None,
        lease_id=UUID(row["lease_id"]) if row["lease_id"] else None,
        time_zone=row["time_zone"],
        property_archived=row["property_state"] == "archived",
        children=tuple(children),
        child_count=row["child_count"],
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
        owner_party_id=UUID(row["owner_party_id"]),
        owner_display_name_snapshot=row["owner_display_name_snapshot"],
    )

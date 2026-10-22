"""DASH Maintenance eligibility and exact set-based attention on caller snapshots."""

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, case, func, literal, or_, select

from app.modules.maintenance.infrastructure.sqlalchemy_models import (
    MaintenanceIssueModel,
    MaintenanceAppointmentModel,
    MaintenanceFollowUpOperationModel,
)
from app.modules.portfolio.application.attention_calendar import calendar_boundaries
from app.modules.portfolio.application.location_ports import PortfolioLocationRelations
from app.modules.tasks.application.attention_ports import TaskAttentionReader
from app.platform.attention_reads import (
    AttentionFact,
    AttentionPage,
    AttentionWindow,
    AttentionKey,
    AttentionReasonFact,
    AttentionDate,
    AttentionChild,
    AttentionRelation,
    AttentionSourceContext,
)

TASK_CODES = ("overdue", "due_today", "follow_up_due", "reminder_due", "undated")
PRIORITIES = {
    "overdue": "overdue",
    "due_today": "today",
    "follow_up_due": "today",
    "reminder_due": "today",
    "undated": "review",
}
REVIEW_BOUNDARY = "9999-12-31T00:00:00+00:00"
WAITING_BOUNDARY = "0001-01-01T00:00:00+00:00"


class SQLiteIssueTaskLocations:
    def __init__(self, locations: PortfolioLocationRelations):
        self.locations = locations

    def task_locations(self):
        issues, properties = MaintenanceIssueModel.__table__, self.locations.properties()
        return (
            select(
                literal("maintenance_issue").label("entity_type"),
                issues.c.id.label("entity_id"),
                issues.c.property_id,
                issues.c.space_id,
                (properties.c.property_state == "archived").label("property_archived"),
                literal("issue_follow_up").label("group_kind"),
                issues.c.status.in_(("open", "in_progress")).label("parent_active"),
            )
            .join(properties, properties.c.property_id == issues.c.property_id)
            .subquery()
        )


class SQLiteMaintenanceAttentionReader:
    def __init__(self, locations: PortfolioLocationRelations, tasks: TaskAttentionReader):
        self.locations, self.tasks = locations, tasks

    def follow_up_relations(self):
        links, issues = MaintenanceFollowUpOperationModel.__table__, MaintenanceIssueModel.__table__
        return (
            select(links.c.issue_id, links.c.task_id)
            .join(issues, issues.c.id == links.c.issue_id)
            .where(issues.c.status.in_(("open", "in_progress")))
            .distinct()
            .subquery("active_issue_follow_ups")
        )

    def facts(self, connection, window):
        if window.source_kind == "maintenance_issue" and window.collection in (
            "needs_action",
            "waiting",
            "upcoming",
        ):
            return self._issue_facts(connection, window)
        if window.source_kind == "maintenance_appointment" and window.collection in (
            "needs_action",
            "upcoming",
            "appointments",
        ):
            return self._appointment_facts(connection, window)
        raise ValueError(
            "Maintenance attention requires an issue or appointment discriminator and supported collection."
        )

    def attention(self, connection, window: AttentionWindow):
        facts = self.facts(connection, window)
        f = facts.c
        matches = f.collection == window.collection
        # Agenda has independent interval membership, not primary-collection arithmetic.
        if window.collection == "appointments":
            matches = f.in_agenda
        codes = (
            ("urgent", "unresolved", "waiting", *TASK_CODES)
            if window.source_kind == "maintenance_issue"
            else ("outcome_review", "scheduled")
        )
        counts = (
            connection.execute(
                select(
                    func.coalesce(func.sum(case((matches, 1), else_=0)), 0).label("total"),
                    func.min(f.next_transition).label("next_transition"),
                    *(
                        func.coalesce(
                            func.sum(case((and_(matches, f.priority_band == band), 1), else_=0)), 0
                        ).label(f"band_{band}")
                        for band in ("urgent", "overdue", "today", "review", "waiting", "future")
                    ),
                    *(
                        func.coalesce(
                            func.sum(case((and_(matches, f[code]), 1), else_=0)), 0
                        ).label(f"reason_{code}")
                        for code in codes
                    ),
                ).select_from(facts)
            )
            .mappings()
            .one()
        )
        selection = select(facts).where(matches)
        if window.after is not None:
            key = window.after
            selection = selection.where(
                or_(
                    f.sort_priority > key.priority,
                    and_(f.sort_priority == key.priority, f.sort_at > key.at.isoformat()),
                    and_(
                        f.sort_priority == key.priority,
                        f.sort_at == key.at.isoformat(),
                        literal(window.source_kind) > key.source_kind,
                    ),
                    and_(
                        f.sort_priority == key.priority,
                        f.sort_at == key.at.isoformat(),
                        literal(window.source_kind) == key.source_kind,
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
        children = (
            self._children(connection, rows, window)
            if window.source_kind == "maintenance_issue"
            else {}
        )
        items = tuple(_fact(row, children.get(row["id"], ()), window) for row in rows)
        result = AttentionPage(
            counts["total"],
            items,
            datetime.fromisoformat(counts["next_transition"])
            if counts["next_transition"]
            else None,
            tuple(
                (band, counts[f"band_{band}"])
                for band in ("urgent", "overdue", "today", "review", "waiting", "future")
                if counts[f"band_{band}"]
            ),
            tuple((code, counts[f"reason_{code}"]) for code in codes if counts[f"reason_{code}"]),
        )
        result.validate_window(window)
        return result

    def _issue_facts(self, connection, window):
        issue = MaintenanceIssueModel.__table__
        properties = self.locations.properties()
        linked = self._linked_tasks(connection, window)
        linked_columns = linked.c
        children = (
            select(
                linked_columns.issue_id,
                func.count().label("child_count"),
                func.max(linked_columns.collection == "waiting").label("has_waiting"),
                func.max(linked_columns.collection == "needs_action").label("has_action"),
                func.min(
                    case(
                        (linked_columns.collection == "needs_action", linked_columns.sort_priority)
                    )
                ).label("action_priority"),
                func.min(
                    case((linked_columns.collection == "needs_action", linked_columns.sort_at))
                ).label("action_at"),
                func.min(
                    case((linked_columns.collection == "waiting", linked_columns.sort_priority))
                ).label("waiting_priority"),
                func.min(
                    case((linked_columns.collection == "waiting", linked_columns.sort_at))
                ).label("waiting_at"),
                func.min(linked_columns.next_transition).label("next_transition"),
                *(func.max(linked_columns[code]).label(code) for code in TASK_CODES),
            )
            .group_by(linked_columns.issue_id)
            .subquery("issue_follow_up_facts")
        )
        urgent = issue.c.priority == "urgent"
        waiting = and_(
            ~urgent,
            func.coalesce(children.c.has_waiting, False),
            ~func.coalesce(children.c.has_action, False),
        )
        priority = case(
            (urgent, 0),
            (waiting, children.c.waiting_priority),
            else_=func.coalesce(children.c.action_priority, 3),
        )
        band = case(
            (urgent, "urgent"),
            (waiting, "waiting"),
            (priority == 1, "overdue"),
            (priority == 2, "today"),
            else_="review",
        )
        boundary = case(
            (urgent, issue.c.reported_at_utc),
            (waiting, children.c.waiting_at),
            else_=func.coalesce(children.c.action_at, REVIEW_BOUNDARY),
        )
        selection = (
            select(
                issue.c.id,
                issue.c.summary.label("title"),
                issue.c.status,
                issue.c.revision,
                issue.c.property_id,
                issue.c.space_id,
                properties.c.time_zone,
                properties.c.property_state,
                issue.c.updated_at.label("recorded_at"),
                case((waiting, "waiting"), else_="needs_action").label("collection"),
                urgent.label("urgent"),
                (~waiting).label("unresolved"),
                waiting.label("waiting"),
                *(func.coalesce(children.c[code], False).label(code) for code in TASK_CODES),
                func.coalesce(children.c.child_count, 0).label("child_count"),
                priority.label("sort_priority"),
                band.label("priority_band"),
                boundary.label("sort_at"),
                children.c.next_transition,
            )
            .select_from(
                issue.join(properties, issue.c.property_id == properties.c.property_id).outerjoin(
                    children, children.c.issue_id == issue.c.id
                )
            )
            .where(issue.c.status.in_(("open", "in_progress")))
        )
        if window.property_id is not None:
            selection = selection.where(issue.c.property_id == str(window.property_id))
        return selection.subquery("maintenance_issue_attention")

    def _linked_tasks(self, connection, window):
        tasks = self.tasks.facts(
            connection, replace(window, source_kind="task", collection="needs_action")
        )
        links = MaintenanceFollowUpOperationModel.__table__
        return (
            select(tasks, links.c.issue_id)
            .select_from(links.join(tasks, links.c.task_id == tasks.c.id))
            .where(
                tasks.c.related_entity_type == "maintenance_issue",
                tasks.c.related_entity_id == links.c.issue_id,
            )
            .distinct()
            .subquery("maintenance_explicit_follow_ups")
        )

    def _children(self, connection, rows, window):
        if not rows:
            return {}
        linked = self._linked_tasks(connection, window)
        ranked = (
            select(
                linked.c.issue_id,
                linked.c.id,
                func.row_number()
                .over(
                    partition_by=linked.c.issue_id,
                    order_by=(
                        (linked.c.collection == "needs_action").desc(),
                        linked.c.sort_priority,
                        linked.c.sort_at,
                        linked.c.id,
                    ),
                )
                .label("position"),
            )
            .where(linked.c.issue_id.in_(tuple(row["id"] for row in rows)))
            .subquery()
        )
        pairs = (
            connection.execute(
                select(ranked)
                .where(ranked.c.position <= 3)
                .order_by(ranked.c.issue_id, ranked.c.position)
            )
            .mappings()
            .all()
        )
        facts = self.tasks.hydrate(
            connection,
            tuple(UUID(pair["id"]) for pair in pairs),
            replace(window, source_kind="task", collection="needs_action"),
        )
        by_id = {fact.key.source_id: fact for fact in facts}
        result = {}
        for pair in pairs:
            task = by_id[pair["id"]]
            child = AttentionChild(
                AttentionRelation(
                    "issue_follow_up",
                    "maintenance_issue",
                    UUID(pair["issue_id"]),
                    "task",
                    UUID(pair["id"]),
                ),
                task.reasons,
                task.source_revision,
                task.status,
                children=task.children,
                child_count=task.child_count,
            )
            result.setdefault(pair["issue_id"], []).append(child)
        return result

    def _appointment_facts(self, connection, window):
        database = connection.connection.driver_connection
        database.create_function("maintenance_horizon_end", 3, _horizon_end, deterministic=True)
        database.create_function("maintenance_next_midnight", 2, _next_midnight, deterministic=True)
        database.create_function(
            "maintenance_instant_compare", 2, _instant_compare, deterministic=True
        )
        a, i = MaintenanceAppointmentModel.__table__, MaintenanceIssueModel.__table__
        p = self.locations.properties()
        captured = window.as_of.isoformat()
        end_boundary = func.coalesce(a.c.ends_at_utc, a.c.starts_at_utc)
        elapsed = func.maintenance_instant_compare(end_boundary, captured) <= 0
        future = func.maintenance_instant_compare(a.c.starts_at_utc, captured) >= 0
        within_horizon = (
            func.maintenance_instant_compare(
                a.c.starts_at_utc,
                func.maintenance_horizon_end(p.c.time_zone, captured, window.horizon_days),
            )
            < 0
        )
        ongoing_or_future = and_(~elapsed, within_horizon)
        next_change = func.min(
            func.coalesce(case((future, a.c.starts_at_utc)), REVIEW_BOUNDARY),
            func.coalesce(case((~elapsed, end_boundary)), REVIEW_BOUNDARY),
            func.maintenance_next_midnight(p.c.time_zone, captured),
        )
        # At the start itself, the next membership change is its end, not an
        # already reached transition. All agenda order remains actual UTC start.
        next_change = case(
            (
                func.maintenance_instant_compare(a.c.starts_at_utc, captured) == 0,
                func.min(
                    func.coalesce(
                        a.c.ends_at_utc, func.maintenance_next_midnight(p.c.time_zone, captured)
                    ),
                    func.maintenance_next_midnight(p.c.time_zone, captured),
                ),
            ),
            else_=next_change,
        )
        selection = (
            select(
                a.c.id,
                a.c.issue_id,
                i.c.status.label("issue_status"),
                i.c.summary.label("title"),
                a.c.status,
                i.c.revision,
                i.c.property_id,
                i.c.space_id,
                p.c.time_zone,
                p.c.property_state,
                a.c.scheduled_timezone,
                a.c.starts_at_utc,
                a.c.ends_at_utc,
                a.c.updated_at.label("recorded_at"),
                case((elapsed, "needs_action"), (and_(future, within_horizon), "upcoming")).label(
                    "collection"
                ),
                elapsed.label("outcome_review"),
                (~elapsed).label("scheduled"),
                ongoing_or_future.label("in_agenda"),
                literal(3 if window.collection == "needs_action" else 0).label("sort_priority"),
                case((elapsed, "review"), else_="future").label("priority_band"),
                case((elapsed, end_boundary), else_=a.c.starts_at_utc).label("sort_at"),
                next_change.label("next_transition"),
            )
            .select_from(
                a.join(i, a.c.issue_id == i.c.id).join(p, i.c.property_id == p.c.property_id)
            )
            .where(a.c.status == "scheduled")
        )
        if window.property_id is not None:
            selection = selection.where(i.c.property_id == str(window.property_id))
        return selection.subquery("maintenance_appointment_attention")


def _horizon_end(zone, captured, days):
    return calendar_boundaries(zone, datetime.fromisoformat(captured), days)[3].isoformat()


def _next_midnight(zone, captured):
    return calendar_boundaries(zone, datetime.fromisoformat(captured), 7)[2].isoformat()


def _instant_compare(left, right):
    left, right = datetime.fromisoformat(left), datetime.fromisoformat(right)
    return (left > right) - (left < right)


def _fact(row, children, window):
    source = window.source_kind
    issue = source == "maintenance_issue"
    codes = (
        ("urgent", "unresolved", "waiting", *TASK_CODES)
        if issue
        else ("outcome_review", "scheduled")
    )
    priorities = {
        "urgent": "urgent",
        "unresolved": "review",
        "waiting": "waiting",
        "outcome_review": "review",
        "scheduled": "future",
        **PRIORITIES,
    }
    reasons = tuple(
        AttentionReasonFact(
            code,
            priorities[code],
            source,
            UUID(row["id"]),
            None
            if issue
            else AttentionDate(
                row["scheduled_timezone"],
                at=datetime.fromisoformat(
                    (row["ends_at_utc"] or row["starts_at_utc"])
                    if code == "outcome_review"
                    else row["starts_at_utc"]
                ),
            ),
        )
        for code in codes
        if row[code]
    )
    deadline = (
        None
        if issue
        else AttentionDate(
            row["scheduled_timezone"], at=datetime.fromisoformat(row["starts_at_utc"])
        )
    )
    return AttentionFact(
        AttentionKey(
            row["sort_priority"], datetime.fromisoformat(row["sort_at"]), source, row["id"]
        ),
        str(row["revision"]),
        row["status"],
        row["title"],
        reasons,
        property_id=UUID(row["property_id"]),
        space_id=UUID(row["space_id"]) if row["space_id"] else None,
        time_zone=row["time_zone"] if issue else row["scheduled_timezone"],
        property_archived=row["property_state"] == "archived",
        children=tuple(children),
        child_count=row["child_count"] if issue else 0,
        source_deadline=deadline,
        appointment_end=None
        if issue or row["ends_at_utc"] is None
        else datetime.fromisoformat(row["ends_at_utc"]),
        related_source=None
        if issue
        else AttentionSourceContext(
            "maintenance_issue",
            UUID(row["issue_id"]),
            row["issue_status"] in ("open", "in_progress"),
        ),
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
    )

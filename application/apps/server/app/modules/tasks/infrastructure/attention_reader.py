"""SQL-filtered Task/reminder attention on one caller-owned snapshot."""

from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, literal, or_, select

from app.modules.tasks.application.attention_ports import TaskAttentionRelations
from app.modules.tasks.domain.attention import (
    deadline_bucket,
    deadline_boundary,
    in_horizon,
    at_or_before,
    next_transition,
)
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel, TaskReminderModel
from app.platform.attention_reads import (
    AttentionWindow,
    AttentionPage,
    AttentionFact,
    AttentionKey,
    AttentionDate,
    AttentionReasonFact,
    AttentionChild,
    AttentionRelation,
    AttentionSourceContext,
)

REVIEW_BOUNDARY = "9999-12-31T00:00:00+00:00"
WAITING_BOUNDARY = "0001-01-01T00:00:00+00:00"


class SQLiteTaskAttentionReader:
    def __init__(self, relations: TaskAttentionRelations):
        self.relations = relations

    def hydrate(self, connection, identities, window):
        identities = tuple(dict.fromkeys(str(identity) for identity in identities))
        if len(identities) > 303:
            raise ValueError("Selected follow-up hydration permits at most 303 Tasks.")
        if not identities:
            return ()
        facts = self.facts(connection, window)
        rows = connection.execute(select(facts).where(facts.c.id.in_(identities))).mappings().all()
        reminders = self._reminders(connection, tuple(row["id"] for row in rows), window)
        return tuple(_fact(row, reminders.get(row["id"], ()), window) for row in rows)

    def standalone_attention(self, connection, window, grouped_tasks):
        return self.attention(connection, window, grouped_tasks=grouped_tasks)

    def attention(
        self, connection, window: AttentionWindow, *, grouped_tasks=None
    ) -> AttentionPage:
        if window.source_kind not in (None, "task") or window.collection not in (
            "needs_action",
            "waiting",
            "upcoming",
        ):
            raise ValueError("Task attention requires a Task primary collection.")
        base = self.facts(connection, window)
        if grouped_tasks is not None:
            base = (
                select(base)
                .where(~base.c.id.in_(select(grouped_tasks.c.task_id)))
                .subquery("standalone_task_attention")
            )
        c = base.c
        selected = c.collection == window.collection
        counts = (
            connection.execute(
                select(
                    func.coalesce(func.sum(case((selected, 1), else_=0)), 0).label("total"),
                    func.min(c.next_transition).label("next_transition"),
                    *(
                        func.coalesce(
                            func.sum(case((and_(selected, c.priority_band == band), 1), else_=0)), 0
                        ).label(f"priority_{band}")
                        for band in ("overdue", "today", "review", "waiting", "future")
                    ),
                    *(
                        func.coalesce(
                            func.sum(case((and_(selected, c[code]), 1), else_=0)), 0
                        ).label(f"reason_{code}")
                        for code in (
                            "overdue",
                            "due_today",
                            "follow_up_due",
                            "reminder_due",
                            "undated",
                            "waiting",
                            "follow_up_unscheduled",
                            "scheduled",
                        )
                    ),
                ).select_from(base)
            )
            .mappings()
            .one()
        )
        statement = select(base).where(selected)
        if window.after is not None:
            key = window.after
            # All readers use the same global (band, instant, kind, ID) boundary.
            statement = statement.where(
                or_(
                    c.sort_priority > key.priority,
                    and_(c.sort_priority == key.priority, c.sort_at > key.at.isoformat()),
                    and_(
                        c.sort_priority == key.priority,
                        c.sort_at == key.at.isoformat(),
                        literal("task") > key.source_kind,
                    ),
                    and_(
                        c.sort_priority == key.priority,
                        c.sort_at == key.at.isoformat(),
                        literal("task") == key.source_kind,
                        c.id > key.source_id,
                    ),
                )
            )
        rows = (
            connection.execute(
                statement.order_by(c.sort_priority, c.sort_at, c.id).limit(window.limit + 1)
            )
            .mappings()
            .all()
        )
        reminders = self._reminders(connection, tuple(row["id"] for row in rows), window)
        candidates = tuple(_fact(row, reminders.get(row["id"], ()), window) for row in rows)
        page = AttentionPage(
            counts["total"],
            candidates,
            datetime.fromisoformat(counts["next_transition"])
            if counts["next_transition"]
            else None,
            tuple(
                (band, counts[f"priority_{band}"])
                for band in ("overdue", "today", "review", "waiting", "future")
                if counts[f"priority_{band}"]
            ),
            tuple(
                (code, counts[f"reason_{code}"])
                for code in (
                    "overdue",
                    "due_today",
                    "follow_up_due",
                    "reminder_due",
                    "undated",
                    "waiting",
                    "follow_up_unscheduled",
                    "scheduled",
                )
                if counts[f"reason_{code}"]
            ),
        )
        page.validate_window(window)
        return page

    def facts(self, connection, window):
        if window.source_kind not in (None, "task") or window.collection not in (
            "needs_action",
            "waiting",
            "upcoming",
        ):
            raise ValueError("Task facts require a Task primary collection.")
        _register(connection)
        t, r = TaskModel.__table__, TaskReminderModel.__table__
        captured = window.as_of.isoformat()
        refs = self.relations.locations(window.property_id)
        # Context can mention the same Task through several properties. It still
        # counts once; only unambiguous identities are exposed for All properties.
        locations = (
            select(
                refs.c.entity_type,
                refs.c.entity_id,
                case(
                    (
                        func.count(func.distinct(refs.c.property_id)) == 1,
                        func.min(refs.c.property_id),
                    )
                ).label("property_id"),
                case(
                    (func.count(func.distinct(refs.c.space_id)) == 1, func.min(refs.c.space_id))
                ).label("space_id"),
                func.max(refs.c.property_archived).label("property_archived"),
                func.min(refs.c.group_kind).label("group_kind"),
                func.min(refs.c.parent_active).label("parent_active"),
            )
            .group_by(refs.c.entity_type, refs.c.entity_id)
            .subquery("task_attention_locations")
        )
        due = func.task_attention_due(r.c.remind_at_utc, captured)
        reminders = (
            select(
                r.c.task_id,
                func.sum(case((due, 1), else_=0)).label("due_count"),
                func.min(case((due, r.c.remind_at_utc))).label("first_due"),
                func.min(case((~due, r.c.remind_at_utc))).label("next_reminder"),
            )
            .where(r.c.status.in_(("pending", "acknowledged")))
            .group_by(r.c.task_id)
            .subquery("task_attention_reminders")
        )
        bucket = func.task_attention_bucket(
            t.c.due_at_utc, t.c.due_timezone, t.c.is_all_day, captured
        )
        overdue, today = (
            func.coalesce(bucket == "overdue", False),
            func.coalesce(bucket == "today", False),
        )
        waiting = t.c.waiting_for_kind.is_not(None)
        follow_due = and_(waiting, func.task_attention_due(t.c.follow_up_at_utc, captured))
        reminder_due = func.coalesce(reminders.c.due_count, 0) > 0
        undated = and_(t.c.due_at_utc.is_(None), ~waiting)
        actionable = or_(overdue, today, follow_due, reminder_due, undated)
        future = func.task_attention_horizon(
            t.c.due_at_utc, t.c.due_timezone, captured, window.horizon_days
        )
        collection = case((actionable, "needs_action"), (waiting, "waiting"), (future, "upcoming"))
        priority_band = case(
            (overdue, "overdue"),
            (or_(today, follow_due, reminder_due), "today"),
            (undated, "review"),
            (waiting, "waiting"),
            else_="future",
        )
        sort_priority = case(
            (overdue, 1), (or_(today, follow_due, reminder_due), 2), (undated, 3), else_=0
        )
        boundary = func.task_attention_boundary(t.c.due_at_utc, t.c.due_timezone, t.c.is_all_day)
        sort_at = func.min(
            func.coalesce(case((or_(overdue, today, future), boundary)), REVIEW_BOUNDARY),
            func.coalesce(case((follow_due, t.c.follow_up_at_utc)), REVIEW_BOUNDARY),
            func.coalesce(reminders.c.first_due, REVIEW_BOUNDARY),
        )
        sort_at = case(
            (and_(~actionable, waiting), func.coalesce(t.c.follow_up_at_utc, WAITING_BOUNDARY)),
            else_=sort_at,
        )
        sort_priority = case(
            (and_(~actionable, waiting), case((t.c.follow_up_at_utc.is_(None), 0), else_=1)),
            else_=sort_priority,
        )
        columns = (
            t.c.id,
            t.c.title,
            t.c.status,
            t.c.revision,
            t.c.updated_at_utc,
            t.c.due_at_utc,
            t.c.due_timezone,
            t.c.is_all_day,
            t.c.follow_up_at_utc,
            t.c.follow_up_timezone,
            t.c.related_entity_type,
            t.c.related_entity_id,
            locations.c.property_id,
            locations.c.space_id,
            locations.c.property_archived,
            locations.c.group_kind,
            locations.c.parent_active,
            func.coalesce(reminders.c.due_count, 0).label("child_count"),
            collection.label("collection"),
            priority_band.label("priority_band"),
            sort_priority.label("sort_priority"),
            sort_at.label("sort_at"),
            overdue.label("overdue"),
            today.label("due_today"),
            follow_due.label("follow_up_due"),
            reminder_due.label("reminder_due"),
            undated.label("undated"),
            waiting.label("waiting"),
            and_(waiting, t.c.follow_up_at_utc.is_(None)).label("follow_up_unscheduled"),
            future.label("scheduled"),
            func.task_attention_next(
                t.c.due_at_utc,
                t.c.due_timezone,
                t.c.is_all_day,
                t.c.follow_up_at_utc,
                t.c.follow_up_timezone,
                reminders.c.next_reminder,
                captured,
            ).label("next_transition"),
        )
        statement = (
            select(*columns)
            .select_from(
                t.outerjoin(
                    locations,
                    and_(
                        t.c.related_entity_type == locations.c.entity_type,
                        t.c.related_entity_id == locations.c.entity_id,
                    ),
                ).outerjoin(reminders, t.c.id == reminders.c.task_id)
            )
            .where(t.c.status.in_(("open", "in_progress")), t.c.deleted_at_utc.is_(None))
        )
        if window.property_id is not None:
            statement = statement.where(locations.c.property_id == str(window.property_id))
        return statement.subquery("task_attention_facts")

    @staticmethod
    def _reminders(connection, identities, window):
        if not identities:
            return {}
        r = TaskReminderModel.__table__
        ranked = (
            select(
                r.c.id,
                r.c.task_id,
                r.c.remind_at_utc,
                r.c.status,
                func.row_number()
                .over(partition_by=r.c.task_id, order_by=(r.c.remind_at_utc, r.c.id))
                .label("position"),
            )
            .where(
                r.c.task_id.in_(identities),
                r.c.status.in_(("pending", "acknowledged")),
                func.task_attention_due(r.c.remind_at_utc, window.as_of.isoformat()),
            )
            .subquery()
        )
        result = {}
        for row in connection.execute(
            select(ranked)
            .where(ranked.c.position <= 3)
            .order_by(ranked.c.task_id, ranked.c.position)
        ).mappings():
            result.setdefault(row["task_id"], []).append(row)
        return result


def _register(connection):
    database = connection.connection.driver_connection
    for name, count, function in (
        ("task_attention_bucket", 4, deadline_bucket),
        ("task_attention_boundary", 3, deadline_boundary),
        ("task_attention_horizon", 4, in_horizon),
        ("task_attention_due", 2, at_or_before),
        ("task_attention_next", 7, next_transition),
    ):
        database.create_function(name, count, function, deterministic=True)


def _temporal(value, zone, all_day=False):
    if value is None:
        return None
    instant = datetime.fromisoformat(value).astimezone(UTC)
    if all_day:
        return AttentionDate(zone, on=instant.astimezone(ZoneInfo(zone)).date())
    return AttentionDate(zone, at=instant)


def _fact(row, reminders, window):
    task_id = UUID(row["id"])
    reasons = []
    for code, priority in (
        ("overdue", "overdue"),
        ("due_today", "today"),
        ("follow_up_due", "today"),
        ("reminder_due", "today"),
        ("undated", "review"),
        ("waiting", "waiting"),
        ("follow_up_unscheduled", "waiting"),
        ("scheduled", "future"),
    ):
        if row[code]:
            temporal = (
                _temporal(row["follow_up_at_utc"], row["follow_up_timezone"])
                if code == "follow_up_due"
                else (
                    _temporal(row["due_at_utc"], row["due_timezone"], row["is_all_day"])
                    if code in ("overdue", "due_today", "scheduled")
                    else None
                )
            )
            reasons.append(AttentionReasonFact(code, priority, "task", task_id, temporal))
    children = tuple(
        AttentionChild(
            AttentionRelation("task_reminder", "task", task_id, "reminder", UUID(reminder["id"])),
            (
                AttentionReasonFact(
                    "reminder_due",
                    "today",
                    "task",
                    task_id,
                    _temporal(reminder["remind_at_utc"], "UTC"),
                ),
            ),
            str(row["revision"]),
            reminder["status"],
        )
        for reminder in reminders
    )
    relation = None
    if row["group_kind"] in ("issue_follow_up", "concern_follow_up") and row["parent_active"]:
        parent = "maintenance_issue" if row["group_kind"] == "issue_follow_up" else "owner_concern"
        if row["related_entity_type"] != parent:
            raise ValueError("Task grouping relation does not match its declared source identity.")
        relation = AttentionRelation(
            row["group_kind"], parent, UUID(row["related_entity_id"]), "task", task_id
        )
    return AttentionFact(
        AttentionKey(
            row["sort_priority"], datetime.fromisoformat(row["sort_at"]), "task", row["id"]
        ),
        str(row["revision"]),
        row["status"],
        row["title"],
        tuple(reasons),
        property_id=UUID(row["property_id"]) if row["property_id"] else None,
        space_id=UUID(row["space_id"]) if row["space_id"] else None,
        property_archived=bool(row["property_archived"]),
        relation=relation,
        children=children,
        child_count=row["child_count"],
        task_deadline=_temporal(row["due_at_utc"], row["due_timezone"], row["is_all_day"]),
        follow_up=_temporal(row["follow_up_at_utc"], row["follow_up_timezone"]),
        recorded_at=datetime.fromisoformat(row["updated_at_utc"]),
        related_source=AttentionSourceContext(
            row["related_entity_type"], UUID(row["related_entity_id"]), bool(row["parent_active"])
        )
        if row["group_kind"] in ("issue_follow_up", "concern_follow_up")
        else None,
    )

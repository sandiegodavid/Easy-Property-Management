"""DASH Task attention: exact source-owned timing and SQL-bounded selection."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import event, literal, select, union_all, update

from app.modules.tasks.infrastructure.attention_reader import SQLiteTaskAttentionReader
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel, TaskReminderModel
from app.platform.attention_reads import AttentionWindow
from app.platform.sqlite_engine import create_sqlite_engine

NOW = datetime(2026, 10, 12, 18, tzinfo=UTC)


def identity(number):
    return str(UUID(int=number))


class Relations:
    """Source port fixture: retained property, issue and concern locations."""

    def locations(self, property_id):
        entries = (
            ("property", 100, 100, False, None, True),
            ("maintenance_issue", 200, 100, False, "issue_follow_up", True),
            ("owner_concern", 201, 100, False, "concern_follow_up", False),
            ("property", 101, 101, True, None, True),
        )
        statements = [
            select(
                literal(kind).label("entity_type"),
                literal(identity(entity)).label("entity_id"),
                literal(identity(prop)).label("property_id"),
                literal(None).label("space_id"),
                literal(archived).label("property_archived"),
                literal(group).label("group_kind"),
                literal(active).label("parent_active"),
            )
            for kind, entity, prop, archived, group, active in entries
        ]
        relation = union_all(*statements).subquery()
        if property_id is not None:
            relation = select(relation).where(relation.c.property_id == str(property_id)).subquery()
        return relation


@pytest.fixture
def database(tmp_path):
    engine = create_sqlite_engine(tmp_path / "tasks.sqlite")
    TaskModel.__table__.create(engine)
    TaskReminderModel.__table__.create(engine)
    with engine.connect() as connection:
        connection.connection.driver_connection.execute("PRAGMA journal_mode=WAL").fetchall()
    yield engine, SQLiteTaskAttentionReader(Relations())
    engine.dispose()


def task(number, **fields):
    return {
        **dict(
            id=identity(number),
            title=f"Task {number}",
            notes="PRIVATE NOTES",
            status="open",
            priority="normal",
            is_all_day=0,
            created_at_utc=NOW.isoformat(),
            updated_at_utc=NOW.isoformat(),
        ),
        **fields,
    }


def reminder(number, task_number, at, status="pending"):
    return dict(
        id=identity(number),
        task_id=identity(task_number),
        remind_at_utc=at.isoformat(),
        status=status,
        created_at_utc=NOW.isoformat(),
    )


def window(collection="needs_action", **fields):
    return AttentionWindow(NOW, collection, source_kind="task", **fields)


def insert(engine, tasks, reminders=()):
    with engine.begin() as connection:
        for row in tasks:
            connection.execute(TaskModel.__table__.insert(), row)
        for row in reminders:
            connection.execute(TaskReminderModel.__table__.insert(), row)


def waiting_fields(follow=None):
    return dict(
        waiting_for_kind="person",
        waiting_for_label="Contractor",
        waiting_set_at_utc=NOW.isoformat(),
        follow_up_at_utc=follow.isoformat() if follow else None,
        follow_up_timezone="America/Los_Angeles" if follow else None,
    )


def test_future_today_deadline_is_actionable_but_future_today_followup_waits(database):
    engine, reader = database
    future = NOW + timedelta(hours=4)
    insert(
        engine,
        [
            task(1, due_at_utc=future.isoformat(), due_timezone="America/Los_Angeles"),
            task(2, **waiting_fields(future)),
            task(3, **waiting_fields(NOW)),
        ],
    )
    with engine.begin() as connection:
        action = reader.attention(connection, window())
        waiting = reader.attention(connection, window("waiting"))
    assert action.matching_total == 2
    assert waiting.matching_total == 1
    assert waiting.candidates[0].key.source_id == identity(2)
    assert {reason.code for reason in action.candidates[0].reasons} == {"follow_up_due", "waiting"}
    assert {reason.code for reason in action.candidates[1].reasons} == {"due_today"}
    assert dict(action.priority_counts) == {"today": 2}
    assert action.next_transition_at == future


def test_waiting_cannot_hide_overdue_task_or_due_reminder(database):
    engine, reader = database
    insert(
        engine,
        [
            task(
                1,
                due_at_utc=(NOW - timedelta(hours=1)).isoformat(),
                due_timezone="UTC",
                **waiting_fields(NOW + timedelta(days=3)),
            ),
            task(2, **waiting_fields()),
            task(3, **waiting_fields()),
        ],
        [
            reminder(1001, 2, NOW),
            reminder(1002, 2, NOW - timedelta(hours=1), "acknowledged"),
            reminder(1003, 3, NOW, "dismissed"),
        ],
    )
    with engine.begin() as connection:
        action = reader.attention(connection, window())
        waiting = reader.attention(connection, window("waiting"))
    assert action.matching_total == 2
    assert action.candidates[0].key.source_id == identity(1)
    assert action.candidates[1].child_count == 2
    assert len(action.candidates[1].children) == 2
    assert waiting.matching_total == 1
    assert waiting.candidates[0].key.source_id == identity(3)


def test_all_day_deadlines_and_selected_horizon_use_task_local_dates(database):
    engine, reader = database
    # LA is Oct 12; Tokyo is Oct 13 at capture.
    insert(
        engine,
        [
            task(
                1,
                due_at_utc="2026-10-12T07:00:00+00:00",
                due_timezone="America/Los_Angeles",
                is_all_day=1,
            ),
            task(
                2, due_at_utc="2026-10-11T15:00:00+00:00", due_timezone="Asia/Tokyo", is_all_day=1
            ),
            task(
                3,
                due_at_utc="2026-10-20T07:00:00+00:00",
                due_timezone="America/Los_Angeles",
                is_all_day=1,
            ),
        ],
    )
    with engine.begin() as connection:
        action = reader.attention(connection, window())
        short = reader.attention(connection, window("upcoming"))
        extended = reader.attention(connection, window("upcoming", horizon_days=30))
    assert action.matching_total == 2
    assert action.candidates[0].reasons[0].code == "overdue"
    assert action.candidates[1].task_deadline.on.isoformat() == "2026-10-12"
    assert short.matching_total == 0
    assert extended.matching_total == 1


def test_property_scope_archived_obligations_and_explicit_parent_relations(database):
    engine, reader = database
    insert(
        engine,
        [
            task(1),
            task(2, related_entity_type="property", related_entity_id=identity(100)),
            task(3, related_entity_type="property", related_entity_id=identity(101)),
            task(4, related_entity_type="maintenance_issue", related_entity_id=identity(200)),
            task(5, related_entity_type="owner_concern", related_entity_id=identity(201)),
        ],
    )
    with engine.begin() as connection:
        all_tasks = reader.attention(connection, window(limit=10))
        selected = reader.attention(connection, window(property_id=UUID(identity(100)), limit=10))
    assert all_tasks.matching_total == 5
    assert selected.matching_total == 3
    by_id = {fact.key.source_id: fact for fact in all_tasks.candidates}
    assert by_id[identity(1)].property_id is None
    assert by_id[identity(3)].property_archived
    assert by_id[identity(4)].relation.kind == "issue_follow_up"
    assert by_id[identity(5)].relation is None  # Active child survives terminal parent.
    assert by_id[identity(2)].relation is None  # Property context is not grouping.


def test_terminal_deleted_tasks_are_excluded_even_with_due_reminders(database):
    engine, reader = database
    insert(
        engine,
        [
            task(1, status="completed"),
            task(2, status="cancelled"),
            task(3, deleted_at_utc=NOW.isoformat()),
        ],
        [reminder(100 + n, n, NOW) for n in (1, 2, 3)],
    )
    with engine.begin() as connection:
        result = reader.attention(connection, window())
    assert result.matching_total == 0
    assert not result.candidates and result.next_transition_at is None


@pytest.mark.parametrize("count", [1, 10, 1000])
def test_counts_candidates_reminder_previews_and_queries_stay_bounded(database, count):
    engine, reader = database
    insert(
        engine,
        [task(n) for n in range(1, count + 1)],
        [reminder(10000 + n, 1, NOW - timedelta(minutes=n)) for n in range(1, 11)],
    )
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with engine.begin() as connection:
            page = reader.attention(connection, window(limit=5))
            assert page.matching_total == count
            assert len(page.candidates) <= 6
            assert len(statements) <= 3
            assert page.candidates[0].child_count == 10
            assert len(page.candidates[0].children) == 3
            assert "notes" not in str(statements)
            if count > 5:
                continuation = reader.attention(
                    connection, window(limit=5, after=page.candidates[4].key)
                )
                assert continuation.matching_total == count
                assert not {fact.key for fact in page.candidates[:5]} & {
                    fact.key for fact in continuation.candidates
                }
    finally:
        event.remove(engine, "before_cursor_execute", capture)


@pytest.mark.parametrize("follow_up_zone", ["UTC", "America/Los_Angeles", "Asia/Tokyo"])
def test_waiting_order_unscheduled_then_exact_followup_transition(database, follow_up_zone):
    engine, reader = database
    future = NOW + timedelta(seconds=1)
    fields = {**waiting_fields(future), "follow_up_timezone": follow_up_zone}
    insert(engine, [task(1, **fields), task(2, **waiting_fields())])
    with engine.begin() as connection:
        waiting = reader.attention(connection, window("waiting"))
        assert [fact.key.source_id for fact in waiting.candidates] == [identity(2), identity(1)]
        assert waiting.next_transition_at == future
        assert waiting.candidates[1].follow_up.at == future
        assert waiting.candidates[1].follow_up.time_zone == follow_up_zone
        facts = reader.facts(connection, window())
        assert "notes" not in facts.c and "outcome_note" not in facts.c
        exact = reader.attention(
            connection, AttentionWindow(future, "needs_action", source_kind="task")
        )
        assert exact.matching_total == 1
        assert exact.candidates[0].key.source_id == identity(1)


def test_timed_deadline_transitions_only_after_exact_due_instant(database):
    engine, reader = database
    insert(engine, [task(1, due_at_utc=NOW.isoformat(), due_timezone="UTC")])
    with engine.begin() as connection:
        exact = reader.attention(connection, window())
        assert exact.candidates[0].reasons[0].code == "due_today"
        assert exact.next_transition_at == NOW + timedelta(microseconds=1)
        later = reader.attention(
            connection,
            AttentionWindow(NOW + timedelta(microseconds=1), "needs_action", source_kind="task"),
        )
        assert later.candidates[0].reasons[0].code == "overdue"


def test_read_only_projection_sees_caller_changes_and_leaves_rollback_to_caller(database):
    engine, reader = database
    insert(engine, [task(1, **waiting_fields())])
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(TaskReminderModel.__table__.insert(), reminder(1001, 1, NOW))
        assert reader.attention(connection, window()).matching_total == 1
        transaction.rollback()
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA query_only=ON")
        assert reader.attention(connection, window()).matching_total == 0
        assert reader.attention(connection, window("waiting")).matching_total == 1
        connection.exec_driver_sql("PRAGMA query_only=OFF")


def test_counts_and_candidates_share_snapshot_during_concurrent_write(database):
    engine, reader = database
    insert(engine, [task(1)])
    changed = []

    def after_count(connection, cursor, statement, parameters, context, executemany):
        if not changed and statement.lstrip().upper().startswith("SELECT"):
            changed.append(True)
            with engine.begin() as writer:
                writer.execute(
                    update(TaskModel).where(TaskModel.id == identity(1)).values(status="cancelled")
                )

    event.listen(engine, "after_cursor_execute", after_count)
    try:
        with engine.begin() as connection:
            first = reader.attention(connection, window())
            assert first.matching_total == len(first.candidates) == 1
            assert first.candidates[0].status == "open"
    finally:
        event.remove(engine, "after_cursor_execute", after_count)
    with engine.begin() as connection:
        assert reader.attention(connection, window()).matching_total == 0


def test_horizon_boundary_and_future_reminder_transition(database):
    engine, reader = database
    insert(
        engine,
        [
            task(1, due_at_utc="2026-10-19T23:59:59+00:00", due_timezone="UTC"),
            task(2, due_at_utc="2026-10-20T00:00:00+00:00", due_timezone="UTC"),
            task(3, **waiting_fields()),
        ],
        [reminder(1001, 3, NOW + timedelta(seconds=1))],
    )
    with engine.begin() as connection:
        upcoming = reader.attention(connection, window("upcoming"))
        assert upcoming.matching_total == 1
        assert upcoming.candidates[0].key.source_id == identity(1)
        assert upcoming.next_transition_at == NOW + timedelta(seconds=1)
        exact = reader.attention(
            connection,
            AttentionWindow(NOW + timedelta(seconds=1), "needs_action", source_kind="task"),
        )
        assert exact.matching_total == 1
        assert exact.candidates[0].key.source_id == identity(3)

"""DASH Maintenance projections on real SQLite, sharing Task and Portfolio ports."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import event, literal, select, update

from app.modules.maintenance.infrastructure.attention_reader import SQLiteMaintenanceAttentionReader
from app.modules.maintenance.infrastructure.sqlalchemy_models import (
    MaintenanceIssueModel,
    MaintenanceAppointmentModel,
    MaintenanceFollowUpOperationModel,
)
from app.modules.parties.infrastructure.sqlalchemy_models import PartyModel
from app.modules.portfolio.infrastructure.sqlalchemy_models import PropertyModel, SpaceModel
from app.modules.portfolio.infrastructure.location_relations import SQLitePortfolioLocationRelations
from app.modules.tasks.infrastructure.attention_reader import SQLiteTaskAttentionReader
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel, TaskReminderModel
from app.platform.attention_reads import AttentionWindow
from app.platform.sqlite_engine import create_sqlite_engine

NOW = datetime(2026, 10, 12, 18, tzinfo=UTC)


def identity(number):
    return str(UUID(int=number))


class Relations:
    def locations(self, property_id):
        i, p = MaintenanceIssueModel.__table__, PropertyModel.__table__
        statement = select(
            literal("maintenance_issue").label("entity_type"),
            i.c.id.label("entity_id"),
            i.c.property_id,
            i.c.space_id,
            (p.c.status == "archived").label("property_archived"),
            literal("issue_follow_up").label("group_kind"),
            i.c.status.in_(("open", "in_progress")).label("parent_active"),
        ).select_from(i.join(p, i.c.property_id == p.c.id))
        if property_id:
            statement = statement.where(i.c.property_id == str(property_id))
        return statement.subquery()


@pytest.fixture
def database(tmp_path):
    engine = create_sqlite_engine(tmp_path / "maintenance.sqlite")
    for model in (
        PropertyModel,
        SpaceModel,
        PartyModel,
        TaskModel,
        TaskReminderModel,
        MaintenanceIssueModel,
        MaintenanceAppointmentModel,
        MaintenanceFollowUpOperationModel,
    ):
        model.__table__.create(engine)
    with engine.connect() as connection:
        connection.connection.driver_connection.execute("PRAGMA journal_mode=WAL").fetchall()
    with engine.begin() as connection:
        connection.execute(
            PropertyModel.__table__.insert(),
            [
                dict(
                    id=identity(100),
                    display_name="LA",
                    address_line_1="1 Main",
                    city="LA",
                    country_code="US",
                    time_zone="America/Los_Angeles",
                    status="active",
                    property_type="office",
                    inventory_layout="office_suites",
                    created_at=NOW.isoformat(),
                    updated_at=NOW.isoformat(),
                ),
                dict(
                    id=identity(101),
                    display_name="Tokyo",
                    address_line_1="2 Main",
                    city="Tokyo",
                    country_code="US",
                    time_zone="Asia/Tokyo",
                    status="archived",
                    property_type="office",
                    inventory_layout="office_suites",
                    created_at=NOW.isoformat(),
                    updated_at=NOW.isoformat(),
                ),
            ],
        )
    tasks = SQLiteTaskAttentionReader(Relations())
    yield engine, SQLiteMaintenanceAttentionReader(SQLitePortfolioLocationRelations(), tasks), tasks
    engine.dispose()


def issue(number, **changes):
    result = dict(
        id=identity(number),
        revision=1,
        property_id=identity(100),
        summary=f"Issue {number}",
        description="PRIVATE DESCRIPTION",
        category="plumbing",
        priority="normal",
        status="open",
        reported_at_utc=(NOW - timedelta(days=number)).isoformat(),
        reported_timezone="America/Los_Angeles",
        reporter_role="manager",
        reporter_subject_kind="local_operator",
        reporter_display_name_snapshot="Operator",
        idempotency_key=identity(10000 + number),
        request_fingerprint="a" * 64,
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
    )
    result.update(changes)
    return result


def appointment(number, issue_number, start, end, **changes):
    result = dict(
        id=identity(number),
        issue_id=identity(issue_number),
        starts_at_utc=start.isoformat(),
        ends_at_utc=end.isoformat() if end is not None else None,
        scheduled_timezone="America/Los_Angeles",
        purpose="PRIVATE PURPOSE",
        instructions="PRIVATE INSTRUCTIONS",
        status="scheduled",
        idempotency_key=identity(20000 + number),
        request_fingerprint="a" * 64,
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
    )
    result.update(changes)
    return result


def task(number, issue_number, *, waiting=False, due=None, follow=None):
    result = dict(
        id=identity(number),
        title=f"Follow-up {number}",
        status="open",
        priority="normal",
        is_all_day=0,
        related_entity_type="maintenance_issue",
        related_entity_id=identity(issue_number),
        notes="PRIVATE TASK NOTES",
        created_at_utc=NOW.isoformat(),
        updated_at_utc=NOW.isoformat(),
    )
    if waiting:
        result.update(
            waiting_for_kind="person",
            waiting_for_label="Contractor",
            waiting_set_at_utc=NOW.isoformat(),
        )
    if due:
        result.update(due_at_utc=due.isoformat(), due_timezone="UTC")
    if follow:
        result.update(follow_up_at_utc=follow.isoformat(), follow_up_timezone="UTC")
    return result


def seed(engine, issues, appointments=(), tasks=(), links=True):
    with engine.begin() as connection:
        for row in issues:
            connection.execute(MaintenanceIssueModel.__table__.insert(), row)
        for row in appointments:
            connection.execute(MaintenanceAppointmentModel.__table__.insert(), row)
        for row in tasks:
            connection.execute(TaskModel.__table__.insert(), row)
            if links:
                connection.execute(
                    MaintenanceFollowUpOperationModel.__table__.insert(),
                    dict(
                        idempotency_key=identity(30000 + UUID(row["id"]).int),
                        request_fingerprint="a" * 64,
                        issue_id=row["related_entity_id"],
                        task_id=row["id"],
                        correlation_id=identity(90000),
                        created_at=NOW.isoformat(),
                    ),
                )


def window(source="maintenance_issue", collection="needs_action", **fields):
    return AttentionWindow(NOW, collection, source_kind=source, **fields)


@pytest.mark.parametrize("hours", [-1, 0, 1])
def test_start_only_appointments_remain_readable_and_use_start_for_outcome_review(database, hours):
    engine, reader, _ = database
    seed(engine, [issue(1)], appointments=[appointment(101, 1, NOW + timedelta(hours=hours), None)])
    with engine.connect() as connection:
        result = reader.attention(
            connection,
            window("maintenance_appointment", "needs_action" if hours <= 0 else "upcoming"),
        )
        assert result.matching_total == 1
        item = result.candidates[0]
        assert item.appointment_end is None
        assert item.reasons[0].code == ("outcome_review" if hours <= 0 else "scheduled")


def test_urgent_and_ordinary_issues_wait_only_through_explicit_active_followups(database):
    engine, reader, _ = database
    seed(
        engine,
        [issue(1, priority="urgent"), issue(2), issue(3)],
        tasks=[task(201, 1, waiting=True), task(202, 2, waiting=True)],
    )
    with engine.begin() as connection:
        action = reader.attention(connection, window())
        waiting = reader.attention(connection, window(collection="waiting"))
    assert action.matching_total == 2 and waiting.matching_total == 1
    assert action.candidates[0].key.source_id == identity(1)
    assert "urgent" in {reason.code for reason in action.candidates[0].reasons}
    assert waiting.candidates[0].key.source_id == identity(2)
    assert waiting.candidates[0].children[0].relation.kind == "issue_follow_up"


def test_generic_related_task_and_appointment_do_not_prove_waiting_or_completion(database):
    engine, reader, _ = database
    seed(
        engine,
        [issue(1)],
        appointments=[appointment(101, 1, NOW + timedelta(hours=1), NOW + timedelta(hours=2))],
        tasks=[task(201, 1, waiting=True)],
        links=False,
    )
    with engine.begin() as connection:
        action = reader.attention(connection, window())
        assert action.matching_total == 1 and action.candidates[0].child_count == 0
        assert reader.attention(connection, window(collection="waiting")).matching_total == 0


def test_actionable_followups_override_waiting_and_retain_nested_due_reminders(database):
    engine, reader, _ = database
    seed(engine, [issue(1)], tasks=[task(201, 1, waiting=True, due=NOW - timedelta(hours=1))])
    with engine.begin() as connection:
        connection.execute(
            TaskReminderModel.__table__.insert(),
            dict(
                id=identity(901),
                task_id=identity(201),
                remind_at_utc=NOW.isoformat(),
                status="pending",
                created_at_utc=NOW.isoformat(),
            ),
        )
        result = reader.attention(connection, window())
    assert result.matching_total == 1
    assert result.candidates[0].key.priority == 1
    assert result.candidates[0].children[0].child_count == 1
    assert result.candidates[0].children[0].children[0].relation.child_id == UUID(identity(901))


def test_terminal_issue_excluded_but_its_active_task_and_scheduled_appointment_survive(database):
    engine, reader, tasks = database
    seed(
        engine,
        [issue(1, status="resolved", resolution_summary="Done", resolved_at=NOW.isoformat())],
        appointments=[appointment(101, 1, NOW - timedelta(hours=2), NOW - timedelta(hours=1))],
        tasks=[task(201, 1)],
    )
    with engine.begin() as connection:
        assert reader.attention(connection, window()).matching_total == 0
        assert tasks.attention(connection, window("task")).matching_total == 1
        appointment_result = reader.attention(connection, window("maintenance_appointment"))
        assert appointment_result.matching_total == 1
        assert appointment_result.candidates[0].reasons[0].code == "outcome_review"
        parent = appointment_result.candidates[0].related_source
        assert parent.kind == "maintenance_issue" and parent.id == UUID(identity(1))
        assert parent.active is False


def test_agenda_overlap_cross_midnight_future_and_elapsed_outcome_membership(database):
    engine, reader, _ = database
    seed(
        engine,
        [issue(1)],
        appointments=[
            appointment(101, 1, NOW - timedelta(hours=20), NOW + timedelta(hours=1)),
            appointment(102, 1, NOW + timedelta(hours=2), NOW + timedelta(hours=3)),
            appointment(103, 1, NOW - timedelta(hours=2), NOW),
        ],
    )
    with engine.begin() as connection:
        agenda = reader.attention(connection, window("maintenance_appointment", "appointments"))
        upcoming = reader.attention(connection, window("maintenance_appointment", "upcoming"))
        missed = reader.attention(connection, window("maintenance_appointment"))
    assert (
        agenda.matching_total == 2 and upcoming.matching_total == 1 and missed.matching_total == 1
    )
    assert [item.key.source_id for item in agenda.candidates] == [identity(101), identity(102)]
    assert agenda.next_transition_at == NOW + timedelta(hours=1)
    assert missed.candidates[0].key.source_id == identity(103)


def test_terminal_appointments_are_excluded_without_resolving_the_issue(database):
    engine, reader, _ = database
    seed(
        engine,
        [issue(1)],
        appointments=[
            appointment(
                101,
                1,
                NOW - timedelta(hours=2),
                NOW - timedelta(hours=1),
                status="completed",
                completed_at=NOW.isoformat(),
            ),
            appointment(
                102,
                1,
                NOW + timedelta(hours=1),
                NOW + timedelta(hours=2),
                status="cancelled",
                cancelled_at=NOW.isoformat(),
                cancellation_reason="Cancelled",
            ),
        ],
    )
    with engine.begin() as connection:
        assert reader.attention(connection, window()).matching_total == 1
        assert (
            reader.attention(
                connection, window("maintenance_appointment", "appointments")
            ).matching_total
            == 0
        )
        assert reader.attention(connection, window("maintenance_appointment")).matching_total == 0


def test_property_scope_archived_context_and_zone_horizon(database):
    engine, reader, _ = database
    seed(
        engine,
        [issue(1), issue(2, property_id=identity(101))],
        appointments=[
            appointment(
                101, 1, datetime(2026, 10, 20, 6, tzinfo=UTC), datetime(2026, 10, 20, 7, tzinfo=UTC)
            ),
            appointment(
                102,
                2,
                datetime(2026, 10, 20, 6, tzinfo=UTC),
                datetime(2026, 10, 20, 7, tzinfo=UTC),
                scheduled_timezone="Asia/Tokyo",
            ),
        ],
    )
    with engine.begin() as connection:
        issues = reader.attention(connection, window(property_id=UUID(identity(101))))
        agenda = reader.attention(connection, window("maintenance_appointment", "appointments"))
    assert issues.matching_total == 1 and issues.candidates[0].property_archived
    # LA Oct 19 23:00 is in its seven-day horizon; Tokyo Oct 20 15:00
    # is also in its Oct 13 through Oct 20 horizon.
    assert agenda.matching_total == 2
    assert {item.time_zone for item in agenda.candidates} == {"Asia/Tokyo", "America/Los_Angeles"}


@pytest.mark.parametrize("count", [1, 10, 1000])
def test_counts_and_child_hydration_stay_bounded_and_continuations_preserve_total(database, count):
    engine, reader, _ = database
    seed(
        engine,
        [issue(n) for n in range(1, count + 1)],
        tasks=[task(2001 + n, 1) for n in range(10)],
    )
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with engine.begin() as connection:
            first = reader.attention(connection, window(limit=5))
            assert first.matching_total == count and len(first.candidates) <= 6
            assert len(statements) <= 5
            assert first.candidates[0].child_count == 10 and len(first.candidates[0].children) == 3
            assert "description" not in str(statements) and "instructions" not in str(statements)
            if count > 5:
                following = reader.attention(
                    connection, window(limit=5, after=first.candidates[4].key)
                )
                assert following.matching_total == count
                assert not {item.key for item in first.candidates[:5]} & {
                    item.key for item in following.candidates
                }
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def test_exact_appointment_end_transition_and_read_only_queries(database):
    engine, reader, _ = database
    ending = NOW + timedelta(microseconds=1)
    seed(engine, [issue(1)], appointments=[appointment(101, 1, NOW - timedelta(hours=1), ending)])
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA query_only=ON")
        agenda = reader.attention(connection, window("maintenance_appointment", "appointments"))
        assert agenda.matching_total == 1 and agenda.next_transition_at == ending
        elapsed = reader.attention(
            connection,
            AttentionWindow(ending, "needs_action", source_kind="maintenance_appointment"),
        )
        assert elapsed.matching_total == 1 and elapsed.candidates[0].reasons[0].date.at == ending
        assert reader.attention(connection, window()).matching_total == 1
        connection.exec_driver_sql("PRAGMA query_only=OFF")


def test_count_candidates_and_followup_hydration_share_snapshot(database):
    engine, reader, _ = database
    seed(engine, [issue(1)], tasks=[task(201, 1)])
    changed = []

    def after_count(connection, cursor, statement, parameters, context, executemany):
        if not changed and statement.lstrip().upper().startswith("SELECT"):
            changed.append(True)
            with engine.begin() as writer:
                writer.execute(
                    update(MaintenanceIssueModel)
                    .where(MaintenanceIssueModel.id == identity(1))
                    .values(
                        status="resolved",
                        revision=2,
                        resolution_summary="Done",
                        resolved_at=NOW.isoformat(),
                    )
                )

    event.listen(engine, "after_cursor_execute", after_count)
    try:
        with engine.begin() as snapshot:
            first = reader.attention(snapshot, window())
            assert first.matching_total == len(first.candidates) == 1
            assert (
                first.candidates[0].status == "open" and first.candidates[0].source_revision == "1"
            )
            assert first.candidates[0].children
    finally:
        event.remove(engine, "after_cursor_execute", after_count)
    with engine.begin() as snapshot:
        assert reader.attention(snapshot, window()).matching_total == 0


def test_urgent_count_is_not_capped_to_preview_and_invalid_discriminator_fails(database):
    engine, reader, _ = database
    seed(engine, [issue(n, priority="urgent") for n in range(1, 9)])
    with engine.begin() as connection:
        page = reader.attention(connection, window(limit=5))
        assert page.matching_total == 8 and dict(page.priority_counts)["urgent"] == 8
        assert len(page.candidates) == 6
        with pytest.raises(ValueError):
            reader.attention(connection, window("maintenance_issue", "appointments"))


@pytest.mark.parametrize("count", [1, 10, 1000])
def test_appointment_counts_and_selection_use_two_queries_with_sql_limit(database, count):
    engine, reader, _ = database
    seed(
        engine,
        [issue(1)],
        appointments=[
            appointment(1000 + n, 1, NOW + timedelta(minutes=n), NOW + timedelta(minutes=n + 1))
            for n in range(count)
        ],
    )
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with engine.begin() as connection:
            page = reader.attention(
                connection, window("maintenance_appointment", "appointments", limit=5)
            )
        assert page.matching_total == count and len(page.candidates) <= 6
        assert len(statements) <= 2 and "LIMIT" in statements[-1]
        assert "instructions" not in str(statements) and "purpose" not in str(statements)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

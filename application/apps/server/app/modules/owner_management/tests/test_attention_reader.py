"""DASH owner-source SQLite projections and explicit concern follow-up boundaries."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import event, literal, select, update

from app.modules.communications.infrastructure.sqlalchemy_models import CommunicationModel
from app.modules.finance.infrastructure.sqlalchemy_models import RentReceiptModel
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel
from app.modules.owner_accounting.infrastructure.attention_reader import (
    SQLiteOwnerReportAttentionReader,
)
from app.modules.owner_accounting.infrastructure.sqlalchemy_models import OwnerRentReportModel
from app.modules.owner_management.infrastructure.attention_reader import (
    SQLiteOwnerConcernAttentionReader,
)
from app.modules.owner_management.infrastructure.sqlalchemy_models import (
    OwnerConcernModel,
    OwnerConcernFollowUpOperationModel,
)
from app.modules.parties.infrastructure.sqlalchemy_models import PartyModel
from app.modules.portfolio.infrastructure.location_relations import SQLitePortfolioLocationRelations
from app.modules.portfolio.infrastructure.sqlalchemy_models import PropertyModel, SpaceModel
from app.modules.tasks.infrastructure.attention_reader import SQLiteTaskAttentionReader
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel, TaskReminderModel
from app.platform.attention_reads import AttentionWindow
from app.platform.sqlite_engine import create_sqlite_engine

NOW = datetime(2026, 10, 12, 18, tzinfo=UTC)


def identity(number):
    return str(UUID(int=number))


class TaskLocations:
    """Context alone cannot declare a grouping relation; operations do that."""

    def locations(self, property_id):
        c, p = OwnerConcernModel.__table__, PropertyModel.__table__
        statement = select(
            literal("owner_concern").label("entity_type"),
            c.c.id.label("entity_id"),
            c.c.property_id,
            c.c.space_id,
            (p.c.status == "archived").label("property_archived"),
            literal(None).label("group_kind"),
            c.c.status.in_(("open", "in_progress")).label("parent_active"),
        ).select_from(c.join(p, c.c.property_id == p.c.id))
        if property_id:
            statement = statement.where(c.c.property_id == str(property_id))
        return statement.subquery()


@pytest.fixture
def database(tmp_path):
    engine = create_sqlite_engine(tmp_path / "owners.sqlite")
    for model in (
        PropertyModel,
        SpaceModel,
        PartyModel,
        LeaseModel,
        CommunicationModel,
        RentReceiptModel,
        TaskModel,
        TaskReminderModel,
        OwnerRentReportModel,
        OwnerConcernModel,
        OwnerConcernFollowUpOperationModel,
    ):
        model.__table__.create(engine)
    with engine.connect() as connection:
        connection.connection.driver_connection.execute("PRAGMA journal_mode=WAL").fetchall()
    with engine.begin() as connection:
        for number, state, zone in (
            (100, "active", "America/Los_Angeles"),
            (101, "archived", "Asia/Tokyo"),
        ):
            connection.execute(
                PropertyModel.__table__.insert(),
                dict(
                    id=identity(number),
                    display_name=f"Property {number}",
                    address_line_1="1 Main",
                    city="City",
                    country_code="US",
                    time_zone=zone,
                    status=state,
                    property_type="office",
                    inventory_layout="office_suites",
                    created_at=NOW.isoformat(),
                    updated_at=NOW.isoformat(),
                ),
            )
            connection.execute(
                SpaceModel.__table__.insert(),
                dict(
                    id=identity(number + 100),
                    property_id=identity(number),
                    space_kind="office_suite",
                    display_name="Suite",
                    normalized_name="suite",
                    status="active",
                    created_at=NOW.isoformat(),
                    updated_at=NOW.isoformat(),
                ),
            )
        connection.execute(
            PartyModel.__table__.insert(),
            dict(
                id=identity(300),
                party_kind="individual",
                display_name="Changed current name",
                archived_at=NOW.isoformat(),
                created_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            ),
        )
        connection.execute(
            LeaseModel.__table__.insert(),
            dict(
                id=identity(400),
                space_id=identity(200),
                lease_kind="commercial",
                status="executed",
                lease_revision=1,
                contract_starts_on="2020-01-01",
                occupancy_starts_on="2020-01-01",
                executed_on="2020-01-01",
                created_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            ),
        )
        connection.execute(
            LeaseModel.__table__.insert(),
            dict(
                id=identity(401),
                space_id=identity(201),
                lease_kind="commercial",
                status="executed",
                lease_revision=1,
                contract_starts_on="2020-01-01",
                occupancy_starts_on="2020-01-01",
                executed_on="2020-01-01",
                created_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            ),
        )
    locations = SQLitePortfolioLocationRelations()
    tasks = SQLiteTaskAttentionReader(TaskLocations())
    yield (
        engine,
        SQLiteOwnerReportAttentionReader(locations),
        SQLiteOwnerConcernAttentionReader(locations, tasks),
        tasks,
    )
    engine.dispose()


def report(number, **changes):
    row = dict(
        id=identity(number),
        lease_id=identity(400),
        property_id=identity(100),
        space_id=identity(200),
        property_timezone_snapshot="America/Los_Angeles",
        owner_party_id=identity(300),
        owner_display_name_snapshot="Historical Owner",
        received_on="2026-10-10",
        amount_minor=500,
        currency_code="USD",
        payment_method_kind="cash",
        reported_at_utc=(NOW - timedelta(days=1)).isoformat(),
        status="pending",
        report_revision=1,
        source_note="PRIVATE SOURCE NOTE",
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
    )
    row.update(changes)
    return row


def concern(number, **changes):
    row = dict(
        id=identity(number),
        owner_party_id=identity(300),
        owner_display_name_snapshot="Historical Owner",
        property_id=identity(100),
        property_display_name_snapshot="Historical Property",
        concern_type="general_rental",
        summary=f"Concern {number}",
        description="PRIVATE DESCRIPTION",
        priority="normal",
        status="open",
        raised_at_utc=(NOW - timedelta(days=1)).isoformat(),
        property_timezone_snapshot="America/Los_Angeles",
        recorded_at_utc=NOW.isoformat(),
        updated_at_utc=NOW.isoformat(),
        idempotency_key=identity(10000 + number),
        request_fingerprint="a" * 64,
        revision=1,
    )
    row.update(changes)
    return row


def task(number, parent=1, **changes):
    row = dict(
        id=identity(number),
        title=f"Task {number}",
        notes="PRIVATE TASK NOTES",
        status="open",
        priority="normal",
        is_all_day=0,
        related_entity_type="owner_concern",
        related_entity_id=identity(parent),
        created_at_utc=NOW.isoformat(),
        updated_at_utc=NOW.isoformat(),
    )
    row.update(changes)
    return row


def wait(at=None):
    return dict(
        waiting_for_kind="person",
        waiting_for_label="Owner",
        waiting_set_at_utc=NOW.isoformat(),
        follow_up_at_utc=at.isoformat() if at else None,
        follow_up_timezone="UTC" if at else None,
    )


def seed(engine, concerns=(), tasks=(), links=(), reports=(), reminders=()):
    with engine.begin() as connection:
        for model, rows in (
            (OwnerConcernModel, concerns),
            (TaskModel, tasks),
            (OwnerRentReportModel, reports),
            (TaskReminderModel, reminders),
        ):
            for row in rows:
                connection.execute(model.__table__.insert(), row)
        for number, (parent, child) in enumerate(links):
            connection.execute(
                OwnerConcernFollowUpOperationModel.__table__.insert(),
                dict(
                    id=identity(50000 + number),
                    idempotency_key=identity(60000 + number),
                    request_fingerprint="b" * 64,
                    concern_id=identity(parent),
                    task_id=identity(child),
                    correlation_id=identity(70000 + number),
                    created_at_utc=NOW.isoformat(),
                ),
            )


def window(kind="owner_concern", collection="needs_action", **fields):
    return AttentionWindow(NOW, collection, source_kind=kind, **fields)


def test_pending_reports_retain_historical_identity_but_never_income(database):
    engine, reports, _, _ = database
    seed(engine, reports=[report(1)])
    with engine.begin() as connection:
        page = reports.attention(connection, window("owner_rent_report"))
    item = page.candidates[0]
    assert item.owner_display_name_snapshot == "Historical Owner"
    assert item.owner_party_id == UUID(identity(300)) and item.lease_id == UUID(identity(400))
    assert item.source_revision == "1" and item.status == "pending"
    assert item.outstanding_minor is None and item.received_minor is None
    assert [reason.code for reason in item.reasons] == ["pending_verification"]
    assert page.next_transition_at is None


@pytest.mark.parametrize("status", ["verified", "rejected"])
def test_terminal_reports_leave_queue(database, status):
    engine, reports, _, _ = database
    seed(engine, reports=[report(1)])
    with engine.begin() as connection:
        fields = dict(
            status=status, reviewed_at=NOW.isoformat(), review_note="Reviewed", report_revision=2
        )
        if status == "verified":
            connection.execute(
                RentReceiptModel.__table__.insert(),
                dict(
                    id=identity(500),
                    lease_id=identity(400),
                    idempotency_key=identity(501),
                    received_on="2026-10-10",
                    amount_minor=500,
                    currency_code="USD",
                    payment_method_kind="cash",
                    created_at=NOW.isoformat(),
                ),
            )
            fields["verified_receipt_id"] = identity(500)
        connection.execute(update(OwnerRentReportModel).values(**fields))
        assert reports.attention(connection, window("owner_rent_report")).matching_total == 0


def test_only_explicit_followups_can_move_concern_to_waiting(database):
    engine, _, concerns, _ = database
    seed(
        engine,
        [concern(1), concern(2)],
        [task(10, **wait()), task(11, parent=2, **wait())],
        [(1, 10)],
    )
    with engine.begin() as connection:
        action = concerns.attention(connection, window())
        waiting = concerns.attention(connection, window(collection="waiting"))
    assert [item.key.source_id for item in action.candidates] == [identity(2)]
    assert [item.key.source_id for item in waiting.candidates] == [identity(1)]
    assert waiting.candidates[0].child_count == 1
    assert waiting.candidates[0].children[0].relation.child_id == UUID(identity(10))
    assert waiting.candidates[0].children[0].reasons[-1].code == "follow_up_unscheduled"


def test_actionable_child_and_urgent_parent_override_waiting(database):
    engine, _, concerns, _ = database
    seed(
        engine,
        [concern(1), concern(2, priority="urgent")],
        [task(10, **wait(NOW + timedelta(days=1))), task(11, parent=2, **wait())],
        [(1, 10), (2, 11)],
        reminders=[
            dict(
                id=identity(20),
                task_id=identity(10),
                remind_at_utc=NOW.isoformat(),
                status="pending",
                created_at_utc=NOW.isoformat(),
            )
        ],
    )
    with engine.begin() as connection:
        action = concerns.attention(connection, window())
        waiting = concerns.attention(connection, window(collection="waiting"))
    assert action.matching_total == 2 and waiting.matching_total == 0
    assert action.candidates[0].key.source_id == identity(2)
    item = action.candidates[1]
    assert {reason.code for reason in item.reasons} == {"unresolved", "reminder_due"}
    assert item.children[0].children[0].relation.child_id == UUID(identity(20))
    assert action.next_transition_at == NOW + timedelta(days=1)


@pytest.mark.parametrize("status", ["resolved", "dismissed"])
def test_terminal_concern_does_not_hide_active_child(database, status):
    engine, _, concerns, tasks = database
    fields = dict(status=status)
    if status == "resolved":
        fields.update(resolved_at_utc=NOW.isoformat(), resolution_summary="Done")
    else:
        fields.update(dismissed_at_utc=NOW.isoformat(), dismissal_reason="Not needed")
    seed(engine, [concern(1, **fields)], [task(10)], [(1, 10)])
    with engine.begin() as connection:
        assert concerns.attention(connection, window()).matching_total == 0
        page = tasks.attention(connection, window("task"))
    assert page.matching_total == 1 and page.candidates[0].relation is None


def test_bounded_child_preview_keeps_exact_count_and_future_followup_transition(database):
    engine, _, concerns, _ = database
    follow = NOW + timedelta(hours=1)
    seed(
        engine,
        [concern(1)],
        [task(n, **wait(follow)) for n in range(10, 20)],
        [(1, n) for n in range(10, 20)],
    )
    with engine.begin() as connection:
        page = concerns.attention(connection, window(collection="waiting"))
        due = concerns.attention(connection, replace(window(), as_of=follow))
    assert page.candidates[0].child_count == 10 and len(page.candidates[0].children) == 3
    assert page.next_transition_at == follow and due.matching_total == 1
    assert "follow_up_due" in {reason.code for reason in due.candidates[0].reasons}


def test_archived_scope_and_completed_followups_preserve_unresolved_concern(database):
    engine, reports, concerns, _ = database
    seed(
        engine,
        [concern(1, property_id=identity(101))],
        [task(10, status="completed", completed_at_utc=NOW.isoformat())],
        [(1, 10)],
        reports=[
            report(
                2,
                property_id=identity(101),
                space_id=identity(201),
                lease_id=identity(401),
                property_timezone_snapshot="Asia/Tokyo",
            )
        ],
    )
    with engine.begin() as connection:
        for kind, reader in (("owner_concern", concerns), ("owner_rent_report", reports)):
            page = reader.attention(connection, window(kind, property_id=UUID(identity(101))))
            assert page.matching_total == 1 and page.candidates[0].property_archived
            assert page.candidates[0].time_zone == "Asia/Tokyo"
            assert (
                reader.attention(
                    connection, window(kind, property_id=UUID(identity(100)))
                ).matching_total
                == 0
            )


@pytest.mark.parametrize("size", [1, 10, 1000])
def test_query_budget_and_continuations_are_independent_of_source_count(database, size):
    engine, reports, concerns, _ = database
    seed(
        engine,
        [concern(n) for n in range(1, size + 1)],
        tasks=[task(100000 + n, parent=n) for n in range(1, size + 1)],
        links=[(n, 100000 + n) for n in range(1, size + 1)],
        reports=[report(n) for n in range(1, size + 1)],
    )
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with engine.begin() as connection:
            for kind, reader, bound in (
                ("owner_rent_report", reports, 2),
                ("owner_concern", concerns, 5),
            ):
                statements.clear()
                page = reader.attention(connection, window(kind, limit=5))
                assert page.matching_total == size and len(page.candidates) <= 6
                assert len(statements) <= bound and any("LIMIT" in sql for sql in statements)
                assert not any(
                    field in sql
                    for sql in statements
                    for field in ("source_note", "description", "payment_method", "amount_minor")
                )
                if size > 5:
                    next_page = reader.attention(
                        connection, window(kind, limit=5, after=page.candidates[4].key)
                    )
                    assert next_page.matching_total == size
                    assert next_page.candidates[0].key > page.candidates[4].key
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def test_report_read_keeps_one_snapshot_across_concurrent_review_and_rollback(database):
    engine, reports, _, _ = database
    seed(engine, reports=[report(1)])
    changed = False

    def review(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal changed
        if not changed and statement.lstrip().upper().startswith("SELECT"):
            changed = True
            with engine.begin() as writer:
                writer.execute(
                    update(OwnerRentReportModel).values(
                        status="rejected",
                        reviewed_at=NOW.isoformat(),
                        review_note="Rejected",
                        report_revision=2,
                    )
                )

    event.listen(engine, "after_cursor_execute", review)
    try:
        with engine.begin() as connection:
            page = reports.attention(connection, window("owner_rent_report"))
            assert page.matching_total == 1 and page.candidates[0].source_revision == "1"
    finally:
        event.remove(engine, "after_cursor_execute", review)
    with engine.connect() as connection:
        transaction = connection.begin()
        assert reports.attention(connection, window("owner_rent_report")).matching_total == 0
        connection.execute(
            update(OwnerRentReportModel).values(
                status="pending", reviewed_at=None, review_note=None
            )
        )
        assert reports.attention(connection, window("owner_rent_report")).matching_total == 1
        transaction.rollback()
        assert reports.attention(connection, window("owner_rent_report")).matching_total == 0


def test_empty_and_unsupported_reads_fail_closed_without_mutations(database):
    engine, reports, concerns, _ = database
    with engine.begin() as connection:
        connection.connection.driver_connection.execute("PRAGMA query_only=ON")
        assert reports.attention(connection, window("owner_rent_report")).matching_total == 0
        assert concerns.attention(connection, window()).matching_total == 0
        with pytest.raises(ValueError):
            reports.attention(connection, window("owner_rent_report", "waiting"))
        with pytest.raises(ValueError):
            concerns.attention(connection, window("owner_concern", "appointments"))
        connection.connection.driver_connection.execute("PRAGMA query_only=OFF")


def test_overdue_child_survives_waiting_and_duplicate_operations_do_not_duplicate_it(database):
    engine, _, concerns, _ = database
    seed(
        engine,
        [concern(1)],
        [
            task(
                10,
                due_at_utc=(NOW - timedelta(days=1)).isoformat(),
                due_timezone="UTC",
                **wait(NOW + timedelta(days=1)),
            )
        ],
        [(1, 10), (1, 10)],
    )
    with engine.begin() as connection:
        page = concerns.attention(connection, window())
        assert concerns.attention(connection, window(collection="waiting")).matching_total == 0
    item = page.candidates[0]
    assert item.key.priority == 1 and item.child_count == 1
    assert {reason.code for reason in item.reasons} == {"unresolved", "overdue"}
    assert item.children[0].revision == "1"


def test_mismatched_or_deleted_child_cannot_change_parent_classification(database):
    engine, _, concerns, _ = database
    seed(
        engine,
        [concern(1), concern(2)],
        [task(10, parent=2, **wait()), task(11, deleted_at_utc=NOW.isoformat())],
        [(1, 10), (1, 11)],
    )
    with engine.begin() as connection:
        page = concerns.attention(connection, window())
    assert page.matching_total == 2
    assert all(item.child_count == 0 for item in page.candidates)


def test_concern_snapshot_keeps_pre_resolution_children_and_revision(database):
    engine, _, concerns, _ = database
    seed(engine, [concern(1)], [task(10, **wait())], [(1, 10)])
    changed = False

    def resolve(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal changed
        if not changed and statement.lstrip().upper().startswith("SELECT"):
            changed = True
            with engine.begin() as writer:
                writer.execute(
                    update(OwnerConcernModel).values(
                        status="resolved",
                        resolved_at_utc=NOW.isoformat(),
                        resolution_summary="Done",
                        revision=2,
                    )
                )

    event.listen(engine, "after_cursor_execute", resolve)
    try:
        with engine.begin() as connection:
            page = concerns.attention(connection, window(collection="waiting"))
            assert page.matching_total == 1 and page.candidates[0].source_revision == "1"
            assert page.candidates[0].child_count == 1
    finally:
        event.remove(engine, "after_cursor_execute", resolve)
    with engine.begin() as connection:
        assert concerns.attention(connection, window(collection="waiting")).matching_total == 0

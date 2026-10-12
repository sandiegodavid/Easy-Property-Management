"""DASH Slice 2: real SQLite scope, inventory, calendar and fixed read budgets."""

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, select, update

from app.modules.portfolio.application.attention_ports import (
    PortfolioAttentionError,
    PortfolioAttentionNotFound,
    MAX_CALENDAR_PROPERTIES,
)
from app.modules.portfolio.infrastructure.attention_reader import SQLitePortfolioAttentionReader
from app.modules.portfolio.infrastructure.sqlalchemy_models import (
    PropertyModel,
    SpaceModel,
    SpaceOccupancyPeriodModel,
)
from app.platform.sqlite_engine import create_sqlite_engine

NOW = datetime(2026, 10, 12, 3, tzinfo=UTC)


def identity(number):
    return str(UUID(int=number))


@pytest.fixture
def database(tmp_path):
    engine = create_sqlite_engine(tmp_path / "attention.sqlite")
    for model in (PropertyModel, SpaceModel, SpaceOccupancyPeriodModel):
        model.__table__.create(engine)
    with engine.connect() as connection:
        connection.connection.driver_connection.execute("PRAGMA journal_mode=WAL").fetchall()
    yield engine, SQLitePortfolioAttentionReader()
    engine.dispose()


def property_row(number, zone="America/Los_Angeles", status="active"):
    return dict(
        id=identity(number),
        display_name=f"Property {number}",
        address_line_1="1 Main St",
        city="City",
        country_code="US",
        time_zone=zone,
        status=status,
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
        property_type="office",
        inventory_layout="office_suites",
    )


def space_row(number, property_number, status="active"):
    return dict(
        id=identity(number),
        property_id=identity(property_number),
        space_kind="office_suite",
        display_name=f"Space {number}",
        normalized_name=f"space {number}",
        status=status,
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
    )


def period_row(number, space_number, status, starts="2020-01-01", ends=None, state="valid"):
    return dict(
        id=identity(number),
        space_id=identity(space_number),
        occupancy_status=status,
        starts_on=starts,
        ends_on=ends,
        record_state=state,
        source_kind="manual",
        created_at=NOW.isoformat(),
    )


def count_reads(engine):
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    return statements, capture


def test_retained_obligation_relations_include_archived_but_inventory_excludes_them(database):
    engine, reader = database
    with engine.begin() as connection:
        connection.execute(
            PropertyModel.__table__.insert(), [property_row(1), property_row(2, status="archived")]
        )
        connection.execute(
            SpaceModel.__table__.insert(),
            [space_row(11, 1), space_row(12, 1, "archived"), space_row(21, 2)],
        )
        connection.execute(
            SpaceOccupancyPeriodModel.__table__.insert(),
            [
                period_row(101, 11, "unknown"),
                period_row(102, 12, "vacant"),
                period_row(103, 21, "vacant"),
            ],
        )
    with engine.begin() as connection:
        reader.validate_scope(connection, None)
        reader.validate_scope(connection, UUID(identity(2)))
        properties, spaces = reader.properties(), reader.spaces()
        assert len(connection.execute(select(properties)).all()) == 2
        assert len(connection.execute(select(spaces)).all()) == 3
        facts = reader.inventory(connection, None, NOW)
        assert (
            facts.active_property_count,
            facts.active_space_count,
            facts.vacant_count,
            facts.unknown_count,
        ) == (1, 1, 0, 1)
        assert reader.inventory(connection, UUID(identity(2)), NOW).active_space_count == 0
        with pytest.raises(PortfolioAttentionNotFound) as error:
            reader.validate_scope(connection, UUID(identity(999)))
        assert error.value.status_code == 404
        with pytest.raises(PortfolioAttentionNotFound):
            reader.inventory(connection, UUID(identity(999)), NOW)
        with pytest.raises(PortfolioAttentionNotFound):
            reader.inventory_spaces(connection, UUID(identity(999)), NOW, "vacant")


def test_inventory_is_local_end_exclusive_and_does_not_infer_from_lease_absence(database):
    engine, reader = database
    with engine.begin() as connection:
        connection.execute(
            PropertyModel.__table__.insert(), [property_row(1), property_row(2, "Asia/Tokyo")]
        )
        connection.execute(
            SpaceModel.__table__.insert(), [space_row(11, 1), space_row(21, 2), space_row(22, 2)]
        )
        connection.execute(
            SpaceOccupancyPeriodModel.__table__.insert(),
            [
                period_row(101, 11, "occupied", ends="2026-10-12"),
                period_row(102, 11, "vacant", starts="2026-10-12"),
                period_row(103, 21, "occupied", ends="2026-10-12"),
                period_row(104, 21, "vacant", starts="2026-10-12"),
                period_row(105, 22, "vacant", starts="2026-10-12", state="cancelled"),
            ],
        )
    with engine.begin() as connection:
        facts = reader.inventory(connection, None, NOW)
        assert (facts.vacant_count, facts.unknown_count) == (1, 1)
        assert facts.next_transition_at == datetime(2026, 10, 12, 7, tzinfo=UTC)
        vacant = reader.inventory_spaces(connection, None, NOW, "vacant")
        unknown = reader.inventory_spaces(connection, None, NOW, "unknown")
        assert vacant.matching_total == facts.vacant_count
        assert unknown.matching_total == facts.unknown_count
        assert vacant.items[0].space_id == UUID(identity(21))
        assert unknown.items[0].space_id == UUID(identity(22))


def test_ambiguous_current_periods_are_unknown_not_vacant(database):
    engine, reader = database
    with engine.begin() as connection:
        connection.execute(PropertyModel.__table__.insert(), property_row(1))
        connection.execute(SpaceModel.__table__.insert(), space_row(11, 1))
        connection.execute(
            SpaceOccupancyPeriodModel.__table__.insert(),
            [
                period_row(101, 11, "vacant", ends="2030-01-01"),
                period_row(102, 11, "occupied", starts="2026-01-01", ends="2027-01-01"),
            ],
        )
    with engine.begin() as connection:
        facts = reader.inventory(connection, None, NOW)
        assert (facts.vacant_count, facts.unknown_count) == (0, 1)


@pytest.mark.parametrize(
    "captured,hours",
    [
        (datetime(2026, 3, 8, 12, tzinfo=UTC), 23),
        (datetime(2026, 11, 1, 12, tzinfo=UTC), 25),
    ],
)
def test_calendar_boundaries_respect_dst_and_bounded_batched_hydration(database, captured, hours):
    engine, reader = database
    with engine.begin() as connection:
        connection.execute(PropertyModel.__table__.insert(), property_row(1, status="archived"))
    statements, callback = count_reads(engine)
    try:
        with engine.begin() as connection:
            assert reader.calendars(connection, (), captured, 7) == ()
            assert not statements
            (calendar,) = reader.calendars(
                connection, (UUID(identity(1)), UUID(identity(1))), captured, 7
            )
            assert len(statements) == 1
            assert calendar.archived and calendar.property_name == "Property 1"
            assert calendar.tomorrow_start - calendar.today_start == timedelta(hours=hours)
            assert calendar.horizon_end.astimezone(
                ZoneInfo(calendar.time_zone)
            ).date() == calendar.local_date + timedelta(days=8)
            with pytest.raises(PortfolioAttentionError):
                reader.calendars(
                    connection,
                    tuple(UUID(int=n) for n in range(MAX_CALENDAR_PROPERTIES + 1)),
                    captured,
                    7,
                )
            assert len(statements) == 1
    finally:
        event.remove(engine, "before_cursor_execute", callback)


@pytest.mark.parametrize("property_count", [1, 10, 50])
def test_inventory_budget_is_one_aggregate_at_representative_portfolio_sizes(
    database, property_count
):
    engine, reader = database
    spaces = [
        space_row(1000 + p * 20 + s, p) for p in range(1, property_count + 1) for s in range(20)
    ]
    with engine.begin() as connection:
        connection.execute(
            PropertyModel.__table__.insert(),
            [property_row(p) for p in range(1, property_count + 1)],
        )
        connection.execute(SpaceModel.__table__.insert(), spaces)
    statements, callback = count_reads(engine)
    try:
        with engine.begin() as connection:
            facts = reader.inventory(connection, None, NOW)
            assert facts.active_property_count == property_count
            assert facts.unknown_count == property_count * 20
            assert len(statements) == 1
            page = reader.inventory_spaces(connection, None, NOW, "unknown", limit=5)
            assert page.matching_total == facts.unknown_count
            assert len(page.items) == 5
            assert len(statements) == 3
            assert "LIMIT" in statements[-1]
            following = reader.inventory_spaces(
                connection, None, NOW, "unknown", limit=5, after=page.next_key
            )
            assert following.matching_total == facts.unknown_count
            assert not {item.space_id for item in page.items} & {
                item.space_id for item in following.items
            }
    finally:
        event.remove(engine, "before_cursor_execute", callback)


def test_same_caller_transaction_preserves_scope_and_counts_across_concurrent_write(database):
    engine, reader = database
    with engine.begin() as connection:
        connection.execute(PropertyModel.__table__.insert(), property_row(1))
        connection.execute(SpaceModel.__table__.insert(), space_row(11, 1))
    with engine.begin() as snapshot:
        reader.validate_scope(snapshot, UUID(identity(1)))
        with engine.begin() as writer:
            writer.execute(
                update(PropertyModel)
                .where(PropertyModel.id == identity(1))
                .values(status="archived")
            )
        assert reader.inventory(snapshot, None, NOW).active_property_count == 1
        assert reader.calendars(snapshot, (UUID(identity(1)),), NOW, 7)[0].archived is False
    with engine.begin() as snapshot:
        assert reader.inventory(snapshot, None, NOW).active_property_count == 0


def test_empty_inventory_and_invalid_requests(database):
    engine, reader = database
    with engine.begin() as connection:
        facts = reader.inventory(connection, None, NOW)
        assert (
            facts.active_space_count
            == facts.active_property_count
            == facts.vacant_count
            == facts.unknown_count
            == 0
        )
        assert facts.next_transition_at is None
        with pytest.raises(PortfolioAttentionError):
            reader.inventory(connection, None, NOW.replace(tzinfo=None))
        with pytest.raises(PortfolioAttentionError):
            reader.inventory_spaces(connection, None, NOW, "vacant", limit=True)
        with pytest.raises(PortfolioAttentionError):
            reader.inventory_spaces(connection, None, NOW, "unknown", after=("bad", "bad"))


def test_calendar_batch_accepts_maximum_and_preserves_local_dates_and_identity(database):
    engine, reader = database
    with engine.begin() as connection:
        connection.execute(
            PropertyModel.__table__.insert(),
            [
                property_row(number, "Asia/Tokyo" if number == 2 else "America/Los_Angeles")
                for number in range(1, MAX_CALENDAR_PROPERTIES + 1)
            ],
        )
    statements, callback = count_reads(engine)
    try:
        with engine.begin() as connection:
            rows = reader.calendars(
                connection,
                tuple(UUID(int=n) for n in range(1, MAX_CALENDAR_PROPERTIES + 1)),
                NOW,
                90,
            )
            assert len(rows) == MAX_CALENDAR_PROPERTIES
            assert len(statements) == 1
            assert rows[0].local_date.isoformat() == "2026-10-11"
            assert rows[1].local_date.isoformat() == "2026-10-12"
            assert rows[1].horizon_end.astimezone(ZoneInfo("Asia/Tokyo")).date() == rows[
                1
            ].local_date + timedelta(days=91)
            assert rows[1].property_id == UUID(identity(2))
    finally:
        event.remove(engine, "before_cursor_execute", callback)


def test_inventory_reads_see_uncommitted_caller_changes_and_leave_rollback_to_caller(database):
    engine, reader = database
    with engine.begin() as connection:
        connection.execute(PropertyModel.__table__.insert(), property_row(1))
        connection.execute(SpaceModel.__table__.insert(), space_row(11, 1))
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            SpaceOccupancyPeriodModel.__table__.insert(), period_row(101, 11, "vacant")
        )
        assert reader.inventory(connection, None, NOW).vacant_count == 1
        transaction.rollback()
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA query_only=ON")
        facts = reader.inventory(connection, None, NOW)
        assert (facts.vacant_count, facts.unknown_count) == (0, 1)
        assert reader.inventory_spaces(connection, None, NOW, "unknown").matching_total == 1
        assert len(reader.calendars(connection, (UUID(identity(1)),), NOW, 30)) == 1
        connection.exec_driver_sql("PRAGMA query_only=OFF")

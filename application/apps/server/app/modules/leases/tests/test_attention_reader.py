"""DASH lease review boundaries, conservative continuation and set-based reads."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import event, select, update

from app.modules.leases.infrastructure.attention_reader import SQLiteLeaseAttentionReader
from app.modules.leases.infrastructure.location_relation import SQLiteLeaseLocationRelation
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseRenewalOptionModel
from app.modules.portfolio.infrastructure.attention_reader import SQLitePortfolioAttentionReader
from app.modules.portfolio.infrastructure.location_relations import SQLitePortfolioLocationRelations
from app.modules.portfolio.infrastructure.sqlalchemy_models import (
    PropertyModel,
    SpaceModel,
    SpaceOccupancyPeriodModel,
)
from app.platform.attention_reads import AttentionWindow
from app.platform.sqlite_engine import create_sqlite_engine

NOW = datetime(2026, 10, 12, 3, tzinfo=UTC)


def identity(number):
    return str(UUID(int=number))


@pytest.fixture
def database(tmp_path):
    engine = create_sqlite_engine(tmp_path / "leases.sqlite")
    for model in (
        PropertyModel,
        SpaceModel,
        SpaceOccupancyPeriodModel,
        LeaseModel,
        LeaseRenewalOptionModel,
    ):
        model.__table__.create(engine)
    with engine.connect() as connection:
        connection.connection.driver_connection.execute("PRAGMA journal_mode=WAL").fetchall()
    with engine.begin() as connection:
        for number, zone, state in (
            (100, "America/Los_Angeles", "active"),
            (101, "Asia/Tokyo", "archived"),
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
    reader = SQLiteLeaseAttentionReader(
        SQLiteLeaseLocationRelation(SQLitePortfolioLocationRelations()),
        SQLitePortfolioAttentionReader(),
    )
    yield engine, reader
    engine.dispose()


def lease(number, end="2026-10-31", *, space=200, **changes):
    row = dict(
        id=identity(number),
        space_id=identity(space),
        lease_kind="commercial",
        status="executed",
        lease_revision=1,
        contract_starts_on="2020-01-01",
        contract_ends_on=end,
        occupancy_starts_on="2020-01-01",
        executed_on="2020-01-01",
        notes="PRIVATE LEASE NOTES",
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
    )
    row.update(changes)
    return row


def seed(engine, leases):
    with engine.begin() as connection:
        for row in leases:
            connection.execute(LeaseModel.__table__.insert(), row)


def window(collection="needs_action", **fields):
    return AttentionWindow(NOW, collection, source_kind="lease", **fields)


def test_thirty_day_review_and_extended_upcoming_boundaries(database):
    engine, reader = database
    today = date(2026, 10, 11)
    seed(
        engine,
        [
            lease(number, (today + timedelta(days=days)).isoformat())
            for number, days in ((1, 0), (2, 30), (3, 31), (4, 90), (5, 91))
        ],
    )
    with engine.begin() as connection:
        action = reader.attention(connection, window(limit=10))
        short = reader.attention(connection, window("upcoming", horizon_days=30))
        long = reader.attention(connection, window("upcoming", horizon_days=90))
    assert action.matching_total == 2 and short.matching_total == 0 and long.matching_total == 2
    assert [item.key.source_id for item in long.candidates] == [identity(3), identity(4)]
    assert action.next_transition_at == datetime(2026, 10, 12, 7, tzinfo=UTC)


def test_local_midnight_transition_crosses_daylight_saving_boundary(database):
    engine, reader = database
    seed(engine, [lease(1, "2026-11-15")])
    with engine.begin() as connection:
        result = reader.attention(
            connection,
            AttentionWindow(
                datetime(2026, 11, 1, 8, tzinfo=UTC), "needs_action", source_kind="lease"
            ),
        )
    assert result.next_transition_at == datetime(2026, 11, 2, 8, tzinfo=UTC)
    assert result.candidates[0].key.at == datetime(2026, 11, 15, 8, tzinfo=UTC)


def test_open_ended_draft_void_and_recorded_moveout_closures_are_excluded(database):
    engine, reader = database
    seed(
        engine,
        [
            lease(1, None),
            lease(2, status="draft", executed_on=None),
            lease(3, status="void"),
            lease(
                4,
                "2026-10-10",
                status="ended",
                actual_move_out_on="2026-10-11",
                end_reason="contract_completed",
            ),
            lease(
                5,
                status="terminated",
                actual_move_out_on="2026-10-11",
                end_reason="early_termination",
            ),
        ],
    )
    with engine.begin() as connection:
        result = reader.attention(connection, window())
    assert (
        result.matching_total == 0 and not result.candidates and result.next_transition_at is None
    )


def test_continued_occupancy_requires_exact_portfolio_source_ownership(database):
    engine, reader = database
    seed(engine, [lease(1, "2026-10-10"), lease(2, "2026-10-10")])
    with engine.begin() as connection:
        connection.execute(
            SpaceOccupancyPeriodModel.__table__.insert(),
            dict(
                id=identity(501),
                space_id=identity(200),
                occupancy_status="occupied",
                starts_on="2020-01-01",
                record_state="valid",
                source_kind="lease",
                source_id=identity(1),
                created_at=NOW.isoformat(),
            ),
        )
        result = reader.attention(connection, window())
    by_id = {item.key.source_id: item for item in result.candidates}
    assert {reason.code for reason in by_id[identity(1)].reasons} == {
        "lease_review",
        "continued_occupancy",
    }
    assert {reason.code for reason in by_id[identity(2)].reasons} == {"lease_review"}
    assert dict(result.reason_counts)["continued_occupancy"] == 1


def test_cancelled_ended_or_manual_occupancy_does_not_establish_continuation(database):
    engine, reader = database
    seed(engine, [lease(1, "2026-10-10")])
    with engine.begin() as connection:
        connection.execute(
            SpaceOccupancyPeriodModel.__table__.insert(),
            dict(
                id=identity(501),
                space_id=identity(200),
                occupancy_status="occupied",
                starts_on="2020-01-01",
                ends_on="2026-10-11",
                record_state="valid",
                source_kind="lease",
                source_id=identity(1),
                created_at=NOW.isoformat(),
            ),
        )
        connection.execute(
            SpaceOccupancyPeriodModel.__table__.insert(),
            dict(
                id=identity(502),
                space_id=identity(200),
                occupancy_status="occupied",
                starts_on="2026-10-11",
                record_state="valid",
                source_kind="manual",
                created_at=NOW.isoformat(),
            ),
        )
        result = reader.attention(connection, window())
        assert [reason.code for reason in result.candidates[0].reasons] == ["lease_review"]
        connection.execute(
            update(SpaceOccupancyPeriodModel)
            .where(SpaceOccupancyPeriodModel.id == identity(501))
            .values(ends_on=None, record_state="cancelled")
        )
        assert [
            reason.code for reason in reader.attention(connection, window()).candidates[0].reasons
        ] == ["lease_review"]


def test_exercised_renewal_and_unlinked_executed_contract_do_not_silently_confirm_successor(
    database,
):
    engine, reader = database
    seed(
        engine,
        [
            lease(1, "2026-10-31"),
            lease(
                2,
                "2027-10-31",
                contract_starts_on="2026-10-31",
                occupancy_starts_on="2026-10-31",
                executed_on="2026-10-01",
            ),
        ],
    )
    with engine.begin() as connection:
        connection.execute(
            LeaseRenewalOptionModel.__table__.insert(),
            dict(
                id=identity(601),
                lease_id=identity(1),
                status="exercised",
                proposed_starts_on="2026-10-31",
                proposed_ends_on="2027-10-31",
                decided_on="2026-10-01",
                notes="PRIVATE RENEWAL NOTES",
                created_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            ),
        )
        result = reader.attention(connection, window())
        facts = reader.facts(connection, window())
        original = (
            connection.execute(select(facts).where(facts.c.id == identity(1))).mappings().one()
        )
    assert original["exercised_renewal"] and result.matching_total == 1
    assert result.candidates[0].key.source_id == identity(1)


def test_zones_archived_scope_and_future_closure_dates(database):
    engine, reader = database
    seed(
        engine,
        [
            lease(1, "2026-11-11"),
            lease(2, "2026-11-11", space=201),
            lease(
                3,
                "2026-10-10",
                space=201,
                status="ended",
                actual_move_out_on="2026-10-13",
                end_reason="contract_completed",
            ),
        ],
    )
    with engine.begin() as connection:
        all_rows = reader.attention(connection, window())
        scoped = reader.attention(connection, window(property_id=UUID(identity(101))))
    # LA Oct 11 sees Nov 11 at 31 days; Tokyo Oct 12 sees it at 30.
    assert all_rows.matching_total == scoped.matching_total == 2
    assert all(item.property_archived for item in scoped.candidates)
    assert all(item.source_revision == "1" for item in scoped.candidates)


@pytest.mark.parametrize("count", [1, 10, 1000])
def test_counts_candidates_and_queries_remain_bounded(database, count):
    engine, reader = database
    seed(engine, [lease(number) for number in range(1, count + 1)])
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with engine.begin() as connection:
            first = reader.attention(connection, window(limit=5))
            assert first.matching_total == count and len(first.candidates) <= 6
            assert len(statements) <= 2 and "LIMIT" in statements[-1]
            assert "notes" not in str(statements)
            if count > 5:
                next_page = reader.attention(
                    connection, window(limit=5, after=first.candidates[4].key)
                )
                assert next_page.matching_total == count
                assert not {item.key for item in first.candidates[:5]} & {
                    item.key for item in next_page.candidates
                }
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def test_caller_snapshot_and_rollback_keep_review_results_consistent(database):
    engine, reader = database
    seed(engine, [lease(1)])
    changed = []

    def after_count(connection, cursor, statement, parameters, context, executemany):
        if not changed and statement.lstrip().upper().startswith("SELECT"):
            changed.append(True)
            with engine.begin() as writer:
                writer.execute(
                    update(LeaseModel)
                    .where(LeaseModel.id == identity(1))
                    .values(
                        status="ended",
                        actual_move_out_on="2026-10-11",
                        end_reason="contract_completed",
                        lease_revision=2,
                    )
                )

    event.listen(engine, "after_cursor_execute", after_count)
    try:
        with engine.begin() as connection:
            result = reader.attention(connection, window())
            assert result.matching_total == 1 and result.candidates[0].source_revision == "1"
    finally:
        event.remove(engine, "after_cursor_execute", after_count)
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            update(LeaseModel).values(status="executed", actual_move_out_on=None, end_reason=None)
        )
        assert reader.attention(connection, window()).matching_total == 1
        transaction.rollback()
        connection.exec_driver_sql("PRAGMA query_only=ON")
        assert reader.attention(connection, window()).matching_total == 0
        connection.exec_driver_sql("PRAGMA query_only=OFF")

"""DASH rent selection from actual corrected SQLite receipt/allocation records."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import event, update

from app.modules.finance.application.money_models import MoneyUnavailable
from app.modules.finance.infrastructure.attention_reader import SQLiteRentAttentionReader
from app.modules.finance.infrastructure.sqlalchemy_models import (
    RentExpectationModel,
    RentReceiptModel,
    RentReceiptAllocationModel,
    RentExpectationTimelinessReviewModel,
)
from app.modules.leases.infrastructure.location_relation import SQLiteLeaseLocationRelation
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseTermModel
from app.modules.parties.infrastructure.sqlalchemy_models import PartyModel
from app.modules.portfolio.infrastructure.location_relations import SQLitePortfolioLocationRelations
from app.modules.portfolio.infrastructure.sqlalchemy_models import PropertyModel, SpaceModel
from app.platform.attention_reads import AttentionWindow
from app.platform.sqlite_engine import create_sqlite_engine

NOW = datetime(2026, 10, 12, 3, tzinfo=UTC)


def identity(number):
    return str(UUID(int=number))


@pytest.fixture
def database(tmp_path):
    engine = create_sqlite_engine(tmp_path / "rent.sqlite")
    for model in (
        PropertyModel,
        SpaceModel,
        PartyModel,
        LeaseModel,
        LeaseTermModel,
        RentExpectationModel,
        RentReceiptModel,
        RentReceiptAllocationModel,
        RentExpectationTimelinessReviewModel,
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
            connection.execute(
                LeaseModel.__table__.insert(),
                dict(
                    id=identity(number + 200),
                    space_id=identity(number + 100),
                    lease_kind="commercial",
                    status="executed",
                    contract_starts_on="2020-01-01",
                    contract_ends_on="2030-01-01",
                    occupancy_starts_on="2020-01-01",
                    executed_on="2020-01-01",
                    created_at=NOW.isoformat(),
                    updated_at=NOW.isoformat(),
                    lease_revision=1,
                ),
            )
            connection.execute(
                LeaseTermModel.__table__.insert(),
                dict(
                    id=identity(number + 300),
                    lease_id=identity(number + 200),
                    effective_on="2020-01-01",
                    base_rent_minor=10000,
                    currency_code="USD",
                    payment_frequency="monthly",
                    payment_due_day=1,
                    agreed_security_deposit_minor=0,
                    created_at=NOW.isoformat(),
                ),
            )
    reader = SQLiteRentAttentionReader(
        SQLiteLeaseLocationRelation(SQLitePortfolioLocationRelations())
    )
    yield engine, reader
    engine.dispose()


def expectation(number, due="2026-10-11", *, lease=300, starts=None, **changes):
    starts = starts or due
    result = dict(
        id=identity(number),
        lease_id=identity(lease),
        lease_term_id=identity(lease + 100),
        period_starts_on=starts,
        period_ends_on=(date.fromisoformat(starts) + timedelta(days=1)).isoformat(),
        due_on=due,
        expected_amount_minor=10000,
        currency_code="USD",
        payment_frequency="monthly",
        schedule_anchor_on=starts,
        is_prorated=0,
        created_at=NOW.isoformat(),
    )
    result.update(changes)
    return result


def receipt(number, expectation_number, amount=4000, *, lease=300, voided=False, replaces=None):
    return dict(
        id=identity(number),
        lease_id=identity(lease),
        idempotency_key=identity(10000 + number),
        received_on="2026-10-10",
        amount_minor=amount,
        currency_code="USD",
        payment_method_kind="cash",
        created_at="2026-10-10T12:00:00+00:00",
        voided_at=NOW.isoformat() if voided else None,
        void_reason="Corrected" if voided else None,
        replaces_receipt_id=identity(replaces) if replaces else None,
    ), dict(
        id=identity(20000 + number),
        receipt_id=identity(number),
        expectation_id=identity(expectation_number),
        amount_minor=amount,
        created_at=NOW.isoformat(),
    )


def seed(engine, expectations, receipts=()):
    with engine.begin() as connection:
        for row in expectations:
            connection.execute(RentExpectationModel.__table__.insert(), row)
        for record, allocation in receipts:
            connection.execute(RentReceiptModel.__table__.insert(), record)
            connection.execute(RentReceiptAllocationModel.__table__.insert(), allocation)


def window(collection="needs_action", **fields):
    return AttentionWindow(NOW, collection, source_kind="rent_expectation", **fields)


def test_partial_allocations_voids_and_replacement_receipts_use_current_outstanding(database):
    engine, reader = database
    seed(
        engine,
        [
            expectation(1),
            expectation(2, due="2026-10-10"),
            expectation(3, due="2026-10-09"),
            expectation(4, due="2026-10-08", voided_at=NOW.isoformat(), void_reason="Superseded"),
        ],
        [
            receipt(501, 1),
            receipt(502, 2, amount=10000),
            receipt(503, 3, amount=10000, voided=True),
            receipt(504, 3, amount=3000, replaces=503),
        ],
    )
    with engine.begin() as connection:
        result = reader.attention(connection, window())
    assert result.matching_total == 2
    by_id = {fact.key.source_id: fact for fact in result.candidates}
    assert by_id[identity(1)].outstanding_minor == 6000
    assert by_id[identity(3)].outstanding_minor == 7000
    assert by_id[identity(1)].currency == "USD"
    assert by_id[identity(1)].expected_minor == 10000 and by_id[identity(1)].received_minor == 4000


def test_property_local_due_dates_horizon_and_archived_obligations(database):
    engine, reader = database
    seed(
        engine,
        [
            expectation(1, due="2026-10-12"),
            expectation(2, due="2026-10-12", lease=301),
            expectation(3, due="2026-10-18"),
            expectation(4, due="2026-10-19"),
        ],
    )
    with engine.begin() as connection:
        action = reader.attention(connection, window())
        upcoming = reader.attention(connection, window("upcoming"))
        selected = reader.attention(connection, window(property_id=UUID(identity(101))))
        longer = reader.attention(connection, window("upcoming", horizon_days=30))
    assert action.matching_total == selected.matching_total == 1
    assert selected.candidates[0].property_archived
    assert selected.candidates[0].status == "due"
    assert upcoming.matching_total == 2 and longer.matching_total == 3
    assert action.next_transition_at == datetime(2026, 10, 12, 7, tzinfo=UTC)


def test_effective_missed_review_and_later_receipt_activity_match_finance_policy(database):
    engine, reader = database
    seed(engine, [expectation(1, due="2026-09-01")])
    with engine.begin() as connection:
        connection.execute(
            RentExpectationTimelinessReviewModel.__table__.insert(),
            dict(
                id=identity(601),
                expectation_id=identity(1),
                decision="mark_missed",
                reason="PRIVATE REASON",
                created_at="2026-10-09T00:00:00+00:00",
            ),
        )
        first = reader.attention(connection, window())
    assert first.candidates[0].status == "missed"
    seed(engine, [], [receipt(501, 1, voided=True)])
    with engine.begin() as connection:
        next_result = reader.attention(connection, window())
    assert next_result.candidates[0].status == "late"
    assert next_result.candidates[0].source_revision != first.candidates[0].source_revision


@pytest.mark.parametrize("count", [1, 10, 1000])
def test_expectation_counts_order_and_queries_are_bounded_without_merging_periods(database, count):
    engine, reader = database
    origin = date(2020, 1, 1)
    seed(
        engine,
        [expectation(n, due=(origin + timedelta(days=n)).isoformat()) for n in range(1, count + 1)],
    )
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with engine.begin() as connection:
            page = reader.attention(connection, window(limit=5))
            assert page.matching_total == count and len(page.candidates) <= 6
            assert len(statements) <= 2 and "LIMIT" in statements[-1]
            assert "masked_reference" not in str(statements) and "notes" not in str(statements)
            if count > 5:
                following = reader.attention(
                    connection, window(limit=5, after=page.candidates[4].key)
                )
                assert following.matching_total == count
                assert not {item.key for item in page.candidates[:5]} & {
                    item.key for item in following.candidates
                }
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def test_invalid_overallocation_and_cross_lease_allocations_fail_closed(database):
    engine, reader = database
    seed(engine, [expectation(1)], [receipt(501, 1, amount=11000)])
    with engine.begin() as connection:
        with pytest.raises(MoneyUnavailable):
            reader.attention(connection, window())
        connection.execute(RentReceiptAllocationModel.__table__.update().values(amount_minor=100))
        connection.execute(RentReceiptModel.__table__.update().values(lease_id=identity(301)))
        with pytest.raises(MoneyUnavailable):
            reader.attention(connection, window())


def test_one_snapshot_and_caller_rollback_prevent_mixed_allocation_counts(database):
    engine, reader = database
    seed(engine, [expectation(1)])
    changed = []

    def after_count(connection, cursor, statement, parameters, context, executemany):
        if not changed and statement.lstrip().upper().startswith("SELECT"):
            changed.append(True)
            seed(engine, [], [receipt(501, 1, amount=10000)])

    event.listen(engine, "after_cursor_execute", after_count)
    try:
        with engine.begin() as connection:
            first = reader.attention(connection, window())
            assert first.matching_total == 1 and first.candidates[0].outstanding_minor == 10000
    finally:
        event.remove(engine, "after_cursor_execute", after_count)
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            update(RentReceiptModel).values(voided_at=NOW.isoformat(), void_reason="Void")
        )
        assert reader.attention(connection, window()).matching_total == 1
        transaction.rollback()
        connection.exec_driver_sql("PRAGMA query_only=ON")
        assert reader.attention(connection, window()).matching_total == 0
        connection.exec_driver_sql("PRAGMA query_only=OFF")

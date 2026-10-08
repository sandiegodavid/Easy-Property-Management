"""FIN-003 projections reuse the composing caller's snapshot and scope."""

from app.modules.portfolio.tests.commands import inventory_command

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import event, select, text

from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.finance.application.money_models import MoneyError, MoneyQuery, MoneyUnavailable
from app.modules.finance.infrastructure.money_context_reader import SQLiteMoneyContextReader
from app.modules.finance.tests import test_money_summary as fixtures
from app.modules.leases.infrastructure.location_relation import SQLiteLeaseLocationRelation
from app.modules.portfolio.application.service import PropertyCreateCommand, OwnershipInput
from app.modules.portfolio.infrastructure.location_relations import SQLitePortfolioLocationRelations
from app.platform.sqlite_engine import create_sqlite_engine


@pytest.fixture
def sources():
    fixture = fixtures.MoneySummaryTests()
    fixture.setUp()
    fixture.record_sources(deposits=False)
    portfolio = SQLitePortfolioLocationRelations()
    context = SQLiteMoneyContextReader(
        portfolio, SQLiteLeaseLocationRelation(portfolio), SQLiteAuditReadMarker()
    )
    engine = create_sqlite_engine(fixture.db)
    yield fixture, context, engine
    engine.dispose()
    fixture.doCleanups()


AS_OF = datetime(2026, 10, 6, 12, tzinfo=UTC)
LARGE_SCOPE_COUNT = 102
SUMMARY_QUERY_BUDGET = 15


def test_composed_summary_matches_public_finance_projection(sources):
    fixture, context, engine = sources
    expected = fixture.reader.summary(fixture.query)
    with engine.connect() as connection, connection.begin():
        result = context.summary(connection, fixture.query, as_of=AS_OF, identity=fixture.identity)
        assert connection.in_transaction()
    assert result == expected


def test_finance_respects_existing_read_snapshot_during_concurrent_change(sources):
    fixture, context, engine = sources
    expected = fixture.reader.summary(fixture.query)
    with engine.connect() as connection, connection.begin():
        SQLiteAuditReadMarker().marker(connection)  # Establish the caller's snapshot.
        inventory_command(
            fixture.portfolio,
            "create_property",
            PropertyCreateCommand(
                "Concurrent home",
                "2 Main Street",
                "Portland",
                "US",
                "single_family_home",
                (OwnershipInput("local_operator"),),
                region="OR",
            ),
        )
        result = context.summary(connection, fixture.query, as_of=AS_OF, identity=fixture.identity)
    assert result == expected
    assert (
        fixture.reader.summary(fixture.query).scope.property_count
        == expected.scope.property_count + 1
    )


def test_finance_scope_is_set_based_for_more_than_100_properties(sources):
    fixture, context, engine = sources
    for index in range(101):
        inventory_command(
            fixture.portfolio,
            "create_property",
            PropertyCreateCommand(
                f"Scoped {index}",
                "2 Main Street",
                "Portland",
                "US",
                "single_family_home",
                (OwnershipInput("local_operator"),),
                region="OR",
            ),
        )
    portfolio = SQLitePortfolioLocationRelations().properties()
    scope = select(portfolio.c.property_id).subquery()
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement)

    with engine.connect() as connection, connection.begin():
        result = context.summary(
            connection, fixture.query, as_of=AS_OF, identity=fixture.identity, property_scope=scope
        )
    assert result.scope.property_count == LARGE_SCOPE_COUNT
    assert result.operating == fixture.reader.summary(fixture.query).operating
    assert all(
        statement.lstrip().upper().startswith(("SELECT", "WITH", "BEGIN"))
        for statement in statements
    )
    assert any("IN (SELECT" in statement for statement in statements)
    assert len(statements) <= SUMMARY_QUERY_BUDGET


def test_context_observes_uncommitted_caller_state_without_committing(sources):
    fixture, context, engine = sources
    with engine.connect() as connection, connection.begin():
        connection.execute(
            text("UPDATE properties SET status = 'archived' WHERE id = :id"),
            {"id": fixture.property_id},
        )
        result = context.summary(
            connection,
            MoneyQuery("2026-01-01", "2026-01-31", property_state="active"),
            as_of=AS_OF,
            identity=fixture.identity,
        )
        assert result.scope.property_count == 0
        connection.rollback()
    assert fixture.reader.summary(fixture.query).scope.property_count == 1


def test_context_does_not_open_connections_and_rejects_invalid_capture(sources):
    fixture, context, engine = sources
    with (
        engine.connect() as connection,
        connection.begin(),
        patch("sqlalchemy.engine.Engine.connect", side_effect=AssertionError("Nested connection")),
    ):
        context.summary(connection, fixture.query, as_of=AS_OF, identity=fixture.identity)
        with pytest.raises(MoneyUnavailable):
            context.summary(
                connection,
                fixture.query,
                as_of=AS_OF.replace(tzinfo=None),
                identity=fixture.identity,
            )
        with pytest.raises(MoneyError):
            context.summary(
                connection,
                MoneyQuery("2026-01-01", "2026-01-31", cursor="invalid"),
                as_of=AS_OF,
                identity=fixture.identity,
            )

"""Home recorded money uses the actual FIN-003 caller-snapshot adapter."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import event, text

from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.finance.infrastructure.money_context_reader import SQLiteMoneyContextReader
from app.modules.finance.tests import test_money_summary as fixtures
from app.modules.leases.infrastructure.location_relation import SQLiteLeaseLocationRelation
from app.modules.operator.application.home_contracts import HomeQuery, HomeScope
from app.modules.operator.application.home_money import money_on_home_snapshot
from app.modules.portfolio.infrastructure.location_relations import SQLitePortfolioLocationRelations
from app.platform.sqlite_engine import create_sqlite_engine
from app.modules.finance.infrastructure.attention_reader import SQLiteRentAttentionReader
from app.modules.finance.application.prepaid_check_service import PrepaidCheckService
from app.modules.finance.domain.models import PrepaidCheckCommand, SynchronizeExpectationsCommand
from app.modules.finance.infrastructure.unit_of_work import SQLiteFinanceUnitOfWork
from app.modules.finance.tests.commands import prepaid_command, rent_command
from app.platform.attention_reads import AttentionWindow
from app.modules.tasks.infrastructure.transaction_operations import SQLiteTaskTransactionOperations
from uuid import uuid4
from dataclasses import replace
from app.modules.finance.application.money_models import Metric

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


def test_scheduled_prepaid_check_creates_no_received_rent_or_allocation(sources):
    fixture, reader, engine = sources
    rent_command(
        fixture.finance,
        "synchronize",
        fixture.lease["id"],
        SynchronizeExpectationsCommand(fixture.lease["terms"][0]["id"], "2026-04-01", "2026-01-01"),
    )
    query = HomeQuery(from_on=fixture.query.from_on, through_on=fixture.query.through_on)
    rent = SQLiteRentAttentionReader(
        SQLiteLeaseLocationRelation(SQLitePortfolioLocationRelations())
    )
    with engine.begin() as connection:
        before = money_on_home_snapshot(
            reader, connection, query, as_of=NOW, identity=fixture.identity
        )
        before_attention = rent.attention(
            connection, AttentionWindow(NOW, "needs_action", source_kind="rent_expectation")
        )
    expectation = next(
        row
        for row in fixture.finance.list_expectations(lease_id=fixture.lease["id"])["items"]
        if row["receivedAmountMinor"] == 0 and not row["isProrated"]
    )
    original = fixture.finance.unit_of_work
    checks = PrepaidCheckService(
        SQLiteFinanceUnitOfWork(
            fixture.db,
            original.recorder,
            original.lease_operations,
            original.portfolio_operations,
            original.party_operations,
            SQLiteTaskTransactionOperations(),
        ),
        now=lambda: NOW,
    )
    check = prepaid_command(
        checks,
        "create",
        PrepaidCheckCommand(
            expectation["id"], fixture.tenant["id"], "2026-01-15", "2026-01-20", None, str(uuid4())
        ),
    )
    assert check["status"] == "scheduled" and check["receiptId"] is None
    with engine.begin() as connection:
        after = money_on_home_snapshot(
            reader, connection, query, as_of=NOW, identity=fixture.identity
        )
        after_attention = rent.attention(
            connection, AttentionWindow(NOW, "needs_action", source_kind="rent_expectation")
        )
    assert before.metrics == after.metrics
    assert before_attention.matching_total == after_attention.matching_total
    assert [
        (fact.key.source_id, fact.outstanding_minor) for fact in before_attention.candidates
    ] == [(fact.key.source_id, fact.outstanding_minor) for fact in after_attention.candidates]


@pytest.fixture
def sources():
    fixture = fixtures.MoneySummaryTests()
    fixture.setUp()
    fixture.record_sources(deposits=True)
    locations = SQLitePortfolioLocationRelations()
    reader = SQLiteMoneyContextReader(
        locations, SQLiteLeaseLocationRelation(locations), SQLiteAuditReadMarker()
    )
    engine = create_sqlite_engine(fixture.db)
    yield fixture, reader, engine
    engine.dispose()
    fixture.doCleanups()


def test_home_reuses_exact_finance_metrics_drilldowns_and_caller_transaction(sources):
    fixture, reader, engine = sources
    query = HomeQuery(from_on=fixture.query.from_on, through_on=fixture.query.through_on)
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with (
            engine.begin() as connection,
            patch.object(engine, "connect", side_effect=AssertionError("new connection")),
        ):
            result = money_on_home_snapshot(
                reader, connection, query, as_of=NOW, identity=fixture.identity
            )
            assert connection.in_transaction()
        assert {metric.target.metric: metric.amount for metric in result.metrics} == {
            "rentReceived": "1200.00",
            "expensesPaid": "400.00",
            "expenseRefundsReceived": "0.00",
            "netRecordedExpenses": "400.00",
            "operatingRemainder": "800.00",
        }
        assert len(statements) <= 15
        assert result.capture.as_of == result.capture.checked_at == NOW
        assert all(metric.target.property_state == "all" for metric in result.metrics)
        assert all(
            metric.target.from_on == query.from_on and metric.target.through_on == query.through_on
            for metric in result.metrics
        )
        for metric in result.metrics:
            page = fixture.reader.sources(
                replace(fixture.query, source_revision=result.capture.source_revision),
                Metric(metric.target.metric),
            )
            assert page.total == metric.amount
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    with engine.begin() as connection:
        february = money_on_home_snapshot(
            reader,
            connection,
            HomeQuery(from_on="2026-02-01", through_on="2026-02-28"),
            as_of=NOW,
            identity=fixture.identity,
        )
    assert {metric.target.metric: metric.amount for metric in february.metrics} == {
        "rentReceived": "0.00",
        "expensesPaid": "0.00",
        "expenseRefundsReceived": "100.00",
        "netRecordedExpenses": "-100.00",
        "operatingRemainder": "100.00",
    }


def test_home_money_includes_archived_scoped_history_and_reflects_uncommitted_corrections(sources):
    fixture, reader, engine = sources
    query = HomeQuery(
        scope=HomeScope(kind="property", property_id=fixture.property_id),
        from_on=fixture.query.from_on,
        through_on=fixture.query.through_on,
    )
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            text("UPDATE properties SET status='archived' WHERE id=:id"),
            {"id": fixture.property_id},
        )
        before = money_on_home_snapshot(
            reader, connection, query, as_of=NOW, identity=fixture.identity
        )
        connection.execute(
            text("UPDATE rent_receipts SET voided_at=:at, void_reason='Corrected' WHERE id=:id"),
            {"id": fixture.receipt["id"], "at": NOW.isoformat()},
        )
        after = money_on_home_snapshot(
            reader, connection, query, as_of=NOW, identity=fixture.identity
        )
        assert before.metrics[0].amount == "1200.00" and after.metrics[0].amount == "0.00"
        assert all(metric.target.scope == query.scope for metric in after.metrics)
        transaction.rollback()
    with engine.begin() as connection:
        assert (
            money_on_home_snapshot(reader, connection, query, as_of=NOW, identity=fixture.identity)
            .metrics[0]
            .amount
            == "1200.00"
        )

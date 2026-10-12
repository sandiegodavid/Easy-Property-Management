"""Exact portfolio coverage counts and bounded review selection on one snapshot."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import event, select, update, text

from app.bootstrap.operator_coverage import compose_coverage_sources
from app.modules.operator.application.coverage_sources import CoverageSources
from app.modules.operator.application.coverage_models import coverage_view
from app.modules.operator.infrastructure.coverage_attention_reader import (
    SQLiteCoverageAttentionReader,
)
from app.modules.operator.infrastructure.sqlalchemy_models import OperatorCoverageReviewModel
from app.modules.operator.tests import test_coverage_integration as fixtures
from app.modules.operator.tests.test_coverage import review
from app.modules.operator.application.coverage_service import OperatorCoverageService
from app.platform.attention_reads import AttentionWindow
from app.platform.coverage import CoverageSubject
from app.modules.portfolio.tests.commands import inventory_command
from app.modules.portfolio.infrastructure.sqlalchemy_models import SpaceAvailabilityModel
from app.modules.finance.infrastructure.sqlalchemy_models import RentExpectationModel
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspacePaths
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.platform.sqlite_engine import create_sqlite_engine
from app.platform.product_migrations import validate_latest_schema
from app.modules.finance.tests import test_money_summary as finance_fixtures


@pytest.fixture
def context(tmp_path):
    yield from fixtures.context.__wrapped__(tmp_path)


@pytest.fixture
def populated():
    yield from fixtures.populated.__wrapped__()


def window(**values):
    return AttentionWindow(datetime(2026, 10, 7, 19, tzinfo=UTC), "information_review", **values)


def read(support, **values):
    reader = SQLiteCoverageAttentionReader(support.unit_of_work.sources.coverage)
    return support.unit_of_work.read(lambda tx: reader.attention(tx.connection, window(**values)))


def test_empty_and_other_collections(context):
    _, _, _, support, _, _, _ = context
    assert read(support).matching_total == 0
    assert read(support).applicable_count == read(support).not_applicable_count == 0
    reader = SQLiteCoverageAttentionReader(support.unit_of_work.sources.coverage)
    with support.unit_of_work.engine.connect() as connection:
        assert (
            reader.attention(
                connection, replace(window(), collection="needs_action")
            ).matching_total
            == 0
        )


def test_counts_precedence_targets_and_manual_provenance(context):
    _, portfolio, _, support, _, _, service = context
    p = fixtures.fixtures.fixtures.property_record(portfolio)
    page = read(support)
    assert page.matching_total == 2
    assert page.applicable_count == 2 and page.not_applicable_count == 3
    assert [item.status for item in page.candidates] == [
        "missing_required_information",
        "needs_review",
    ]
    for item in page.candidates:
        result = service.read(
            item.subject_kind, str(item.coverage_resolution.subject_id), item.coverage_area
        )
        assert item.source_revision == result["evidenceRevision"], item.coverage_area
        assert item.coverage_causes == tuple(result["causes"])
        assert str(item.coverage_resolution.subject_id) == result["resolutionRoute"]["entityId"]
    review(service, "property", p.id, "maintenance", next_review_on="2026-10-08")
    assert read(support).matching_total == 1
    reader = SQLiteCoverageAttentionReader(support.unit_of_work.sources.coverage)
    with support.unit_of_work.engine.connect() as connection:
        due = reader.attention(
            connection, replace(window(), as_of=datetime(2026, 10, 8, 18, tzinfo=UTC))
        )
    assert due.matching_total == 2
    assert "review_date_reached" in due.candidates[-1].coverage_causes


def test_large_scope_constant_queries_and_gapless_continuation(context):
    _, portfolio, _, support, _, _, _ = context
    statements = []
    engine = support.unit_of_work.engine

    def collect(*args):
        statements.append(args[2])

    fixtures.fixtures.fixtures.property_record(portfolio, "First")
    event.listen(engine, "before_cursor_execute", collect)
    first = read(support, limit=5)
    first_count = len(statements)
    event.remove(engine, "before_cursor_execute", collect)
    for index in range(60):
        fixtures.fixtures.fixtures.property_record(portfolio, f"House {index}")
    event.listen(engine, "before_cursor_execute", collect)
    statements.clear()
    page = read(support, limit=5)
    assert len(statements) == first_count <= 3
    event.remove(engine, "before_cursor_execute", collect)
    assert first.matching_total == 2 and page.matching_total == 122
    assert page.applicable_count == 122 and page.not_applicable_count == 183
    seen, after = [], None
    while True:
        page = read(support, limit=100, after=after)
        seen.extend(item.key for item in page.candidates[:100])
        assert page.matching_total == 122
        if len(page.candidates) <= 100:
            break
        after = page.candidates[99].key
    assert len(seen) == len(set(seen)) == 122


def test_financial_and_maintenance_parity(populated):
    fixture, overview, _, _, *_ = populated
    uow = overview.unit_of_work
    sources = compose_coverage_sources()
    uow.sources = replace(uow.sources, coverage=sources)
    reader = SQLiteCoverageAttentionReader(sources)
    service = OperatorCoverageService(uow, runtime=overview.runtime, now=overview.now)
    captured = replace(window(), as_of=overview.now())
    review(service, "space", fixture.lease["spaceId"], "rent")
    with uow.engine.connect() as connection:
        rows = connection.execute(select(reader.facts(connection, captured))).mappings().all()
        references = [
            (CoverageSubject(row["subject_kind"], row["id"]), row["area"]) for row in rows
        ]
        facts = sources.facts_for_subjects(connection, references, as_of=captured.as_of)
        reviews = connection.execute(select(OperatorCoverageReviewModel)).mappings().all()

        for row, reference in zip(rows, references, strict=True):
            manual = next(
                (
                    r
                    for r in reviews
                    if r["subject_id"] == reference[0].id and r["area"] == reference[1]
                ),
                None,
            )
            assert json.loads(row["view"]) == coverage_view(
                reference[0], facts[reference], manual, captured.as_of
            ), reference


def test_recorded_deposit_graph_matches_existing_facts():
    fixture = finance_fixtures.MoneySummaryTests()
    fixture.setUp()
    engine = None
    try:
        fixture.record_sources(deposits=True)
        engine = create_sqlite_engine(fixture.db)
        sources = compose_coverage_sources()
        reader = SQLiteCoverageAttentionReader(sources)
        captured = replace(window(), as_of=datetime(2026, 10, 6, 12, tzinfo=UTC))
        with engine.connect() as connection, connection.begin():
            rows = connection.execute(select(reader.facts(connection, captured))).mappings().all()
            refs = [(CoverageSubject(row["subject_kind"], row["id"]), row["area"]) for row in rows]
            facts = sources.facts_for_subjects(connection, refs, as_of=captured.as_of)
            assert any(row["area"] == "deposit" and row["state"] == "recorded" for row in rows)
            for row, reference in zip(rows, refs, strict=True):
                assert json.loads(row["view"]) == coverage_view(
                    reference[0], facts[reference], None, captured.as_of
                )
    finally:
        if engine is not None:
            engine.dispose()
        fixture.tearDown()


def test_no_single_reads_and_source_failure_propagates(context):
    _, portfolio, _, support, _, _, _ = context
    fixtures.fixtures.fixtures.property_record(portfolio)
    with patch.object(
        CoverageSources, "facts_for_subjects", side_effect=AssertionError("hydrating all subjects")
    ):
        assert read(support).matching_total == 2
    with patch.object(
        support.unit_of_work.sources.coverage.maintenance,
        "revision_relation",
        side_effect=RuntimeError("source unavailable"),
    ):
        with pytest.raises(RuntimeError, match="source unavailable"):
            read(support)


def test_archived_and_property_scope(context):
    _, portfolio, _, support, _, _, _ = context
    p = fixtures.fixtures.fixtures.property_record(portfolio, "Archived")
    fixtures.fixtures.fixtures.property_record(portfolio, "Other")
    inventory_command(portfolio, "archive_property", p.id, confirmed=True)
    page = read(support, property_id=UUID(p.id))
    assert page.matching_total == 2
    assert page.applicable_count == 2 and page.not_applicable_count == 3
    assert all(
        item.property_id == UUID(p.id) and item.property_archived for item in page.candidates
    )
    assert read(support).matching_total == 4


def test_counts_and_rows_share_caller_snapshot(context):
    _, portfolio, _, support, _, _, _ = context
    fixtures.fixtures.fixtures.property_record(portfolio, "Before")
    changed = False

    def interleave(_connection, _cursor, statement, *_):
        nonlocal changed
        if "classified_coverage" in statement and not changed:
            changed = True
            fixtures.fixtures.fixtures.property_record(portfolio, "After")

    event.listen(support.unit_of_work.engine, "after_cursor_execute", interleave)
    try:
        page = read(support)
    finally:
        event.remove(support.unit_of_work.engine, "after_cursor_execute", interleave)
    assert changed and page.matching_total == len(page.candidates) == 2
    assert read(support).matching_total == 4


def test_caller_uncommitted_source_changes_and_rollback(context):
    _, portfolio, _, support, _, _, _ = context
    fixtures.fixtures.fixtures.property_record(portfolio)
    before = read(support).candidates[0]
    reader = SQLiteCoverageAttentionReader(support.unit_of_work.sources.coverage)
    with support.unit_of_work.engine.connect() as connection:
        with connection.begin() as transaction:
            connection.execute(
                update(SpaceAvailabilityModel)
                .where(SpaceAvailabilityModel.space_id == str(before.space_id))
                .values(availability_status="available_now")
            )
            during = reader.attention(connection, window()).candidates[0]
            assert during.source_revision != before.source_revision
            assert "availability_unknown" not in during.coverage_causes
            transaction.rollback()
    assert read(support).candidates[0] == before


def test_source_revision_change_invalidates_manual_review(populated):
    fixture, overview, _, _, *_ = populated
    uow = overview.unit_of_work
    sources = compose_coverage_sources()
    service = OperatorCoverageService(uow, runtime=overview.runtime, now=overview.now)
    uow.sources = replace(uow.sources, coverage=sources)
    review(service, "space", fixture.lease["spaceId"], "rent")
    reader = SQLiteCoverageAttentionReader(sources)
    captured = replace(window(), as_of=overview.now())
    with uow.engine.connect() as connection:
        with connection.begin() as transaction:
            before = reader.attention(connection, captured)
            previous = next(
                item
                for item in before.candidates
                if item.coverage_area == "rent" and str(item.space_id) == fixture.lease["spaceId"]
            )
            assert "source_changed" not in previous.coverage_causes
            connection.execute(
                update(RentExpectationModel)
                .where(RentExpectationModel.lease_id == fixture.lease["id"])
                .values(expected_amount_minor=RentExpectationModel.expected_amount_minor + 1)
            )
            after = reader.attention(connection, captured)
            rent = next(
                item
                for item in after.candidates
                if item.coverage_area == "rent" and str(item.space_id) == fixture.lease["spaceId"]
            )
            assert rent.status == "needs_review" and "source_changed" in rent.coverage_causes
            assert rent.source_revision != previous.source_revision
            transaction.rollback()


def test_property_local_review_boundary_and_latest_decision(context):
    _, portfolio, _, support, _, _, service = context
    p = fixtures.fixtures.fixtures.property_record(portfolio)
    review(service, "property", p.id, "maintenance", next_review_on="2026-10-08")
    reader = SQLiteCoverageAttentionReader(support.unit_of_work.sources.coverage)
    with support.unit_of_work.engine.connect() as connection, connection.begin():
        before = reader.attention(
            connection, replace(window(), as_of=datetime(2026, 10, 8, 6, 59, 59, tzinfo=UTC))
        )
        at = reader.attention(
            connection, replace(window(), as_of=datetime(2026, 10, 8, 7, tzinfo=UTC))
        )
    assert before.matching_total == 1 and at.matching_total == 2
    assert before.next_transition_at == datetime(2026, 10, 8, 7, tzinfo=UTC)
    review(service, "property", p.id, "maintenance", next_review_on="2026-10-10")
    with support.unit_of_work.engine.connect() as connection:
        assert (
            reader.attention(
                connection, replace(window(), as_of=datetime(2026, 10, 8, 7, tzinfo=UTC))
            ).matching_total
            == 1
        )


def test_read_only_and_encrypted_restore_rebuild_same_projection(context):
    workspace, portfolio, _, support, _, _, service = context
    p = fixtures.fixtures.fixtures.property_record(portfolio)
    review(service, "property", p.id, "maintenance", next_review_on="2026-10-09")
    reader = SQLiteCoverageAttentionReader(support.unit_of_work.sources.coverage)
    with support.unit_of_work.engine.connect() as connection:
        connection.execute(text("PRAGMA query_only=ON"))
        before = reader.attention(connection, window())
    validate_latest_schema(workspace.paths.database)
    backup = BackupService(
        workspace,
        support.unit_of_work.recorder,
        lambda database: AuditRecorder(SQLiteAuditRepository(database)),
    )
    target = workspace.paths.root.parent / "restored-attention"
    with fast_backup_encryption():
        archive = backup.create_backup(
            "coverage attention passphrase",
            output_path=workspace.paths.root.parent / "coverage-attention.epmbackup",
        )
        backup.restore(archive.archive_path, "coverage attention passphrase", target)
    engine = create_sqlite_engine(WorkspacePaths(target).database)
    try:
        validate_latest_schema(WorkspacePaths(target).database)
        with engine.connect() as connection, connection.begin():
            assert reader.attention(connection, window()) == before
    finally:
        engine.dispose()

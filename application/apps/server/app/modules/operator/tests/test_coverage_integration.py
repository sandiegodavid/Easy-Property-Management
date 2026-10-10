"""Bounded coverage compositions use the same facts, snapshot and review policy."""

from app.modules.portfolio.tests.commands import inventory_command

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from app.platform.testing_client import LocalApiClient as TestClient
from http import HTTPStatus
from sqlalchemy import event
from sqlalchemy.exc import DBAPIError

from app.bootstrap.operator_coverage import compose_coverage_sources
from app.modules.operator.application.coverage_service import OperatorCoverageService
from app.modules.operator.api.directory_contracts import PropertyDirectoryPage, OwnerDirectoryPage
from app.modules.operator.api.overview_contracts import OverviewResponse
from app.modules.operator.api.router import build_router
from app.modules.operator.tests import test_overviews as fixtures
from app.modules.operator.tests.test_coverage import review
from app.modules.portfolio.application.service import (
    SpaceCreateCommand,
    PartyCreateCommand,
    OwnershipInput,
)
from app.platform.coverage import CoverageSubject, MAX_COVERAGE_SUBJECTS
from app.modules.operator.tests import test_context_sources as populated_fixtures


@pytest.fixture
def context(tmp_path):
    base = fixtures.context.__wrapped__(tmp_path)
    values = next(base)
    _, _, directories, support, _, _ = values
    support.unit_of_work.sources = replace(
        support.unit_of_work.sources, coverage=compose_coverage_sources()
    )
    yield (
        *values,
        OperatorCoverageService(support.unit_of_work, runtime=support.runtime, now=directories.now),
    )
    next(base, None)


def test_directory_previews_count_full_scope_and_match_standalone(context):
    _, portfolio, directories, _, overviews, _, coverage = context
    owner = portfolio.create_party(PartyCreateCommand("individual", "Owner"))
    property_record = fixtures.fixtures.property_record(
        portfolio, "Office", [OwnershipInput("client_owner", owner.id)], office=True
    )
    for index in range(7):
        inventory_command(
            portfolio, "add_space", property_record.id, SpaceCreateCommand(f"Unit {index}")
        )
    properties = directories.properties()
    owners = directories.owners()
    PropertyDirectoryPage.model_validate(properties)
    OwnerDirectoryPage.model_validate(owners)
    preview = properties["items"][0]["coverage"]
    assert preview == owners["items"][0]["coverage"] | {"viewAll": preview["viewAll"]}
    assert preview["matchingTotal"] == 33
    assert len(preview["items"]) == 5 and preview["hasMore"]
    assert preview["asOf"] == properties["asOf"]
    for item in preview["items"]:
        assert item == coverage.read(item["subjectKind"], item["subjectId"], item["area"])
    review(coverage, "property", property_record.id, "maintenance")
    response = overviews.overview("owner", owner.id, section="coverage")
    OverviewResponse.model_validate(response)
    assert response["sections"]["coverage"]["items"][0]["state"] == "recorded"


def test_coverage_continuation_has_no_gaps_and_stable_totals(context):
    _, portfolio, _, _, overviews, _, _ = context
    owner, _ = fixtures.owner_property(portfolio, property_name="Éclair A")
    fixtures.fixtures.property_record(
        portfolio, "Éclair B", [fixtures.OwnershipInput("client_owner", owner.id)]
    )
    cursor, seen = None, []
    while True:
        response = overviews.overview("owner", owner.id, section="coverage", limit=1, cursor=cursor)
        OverviewResponse.model_validate(response)
        section = response["sections"]["coverage"]
        assert section["matchingTotal"] == 10
        seen.extend(
            (item["subjectKind"], item["subjectId"], item["area"]) for item in section["items"]
        )
        cursor = section["nextCursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 10


def test_batch_paths_never_call_single_fact_or_review_readers(context):
    _, portfolio, directories, support, overviews, _, _ = context
    owner, property_record = fixtures.owner_property(portfolio)
    sources = support.unit_of_work.sources.coverage
    with (
        patch.object(sources.portfolio, "location", side_effect=AssertionError("single location")),
        patch.object(
            sources.leases, "relevant_context", side_effect=AssertionError("single lease")
        ),
        patch.object(sources.finance, "facts", side_effect=AssertionError("single finance")),
        patch.object(
            sources.maintenance,
            "evidence_revision",
            side_effect=AssertionError("single maintenance"),
        ),
        patch(
            "app.modules.operator.infrastructure.unit_of_work.SQLiteOperatorTransaction.coverage_review",
            side_effect=AssertionError("single review"),
        ),
    ):
        assert directories.properties()["items"][0]["coverage"]["availability"] == "available"
        assert directories.owners()["items"][0]["coverage"]["availability"] == "available"
        assert (
            overviews.overview("property", property_record.id)["sections"]["coverage"][
                "availability"
            ]
            == "available"
        )
        assert (
            overviews.overview("owner", owner.id)["sections"]["coverage"]["availability"]
            == "available"
        )


def test_coverage_failure_does_not_change_membership_or_other_sections(context):
    _, portfolio, directories, support, overviews, _, _ = context
    _, property_record = fixtures.owner_property(portfolio)
    source = support.unit_of_work.sources.coverage.maintenance
    with patch.object(
        source,
        "evidence_revisions",
        side_effect=DBAPIError("query", {}, sqlite3.OperationalError("unavailable")),
    ):
        response = overviews.overview("property", property_record.id)
        OverviewResponse.model_validate(response)
        assert response["sections"]["coverage"]["availability"] == "unavailable"
        assert response["sections"]["spaces"]["availability"] == "available"
        page = directories.properties()
        PropertyDirectoryPage.model_validate(page)
        assert page["matchingTotal"] == 1
        assert page["items"][0]["coverage"]["items"] is None
    with patch.object(source, "evidence_revisions", side_effect=TypeError("implementation bug")):
        with pytest.raises(TypeError):
            directories.properties()


def test_directory_query_cost_is_bounded_and_reads_share_one_connection(context):
    _, portfolio, directories, support, overviews, _, _ = context
    owner, property_record = fixtures.owner_property(portfolio)
    statements, connections = [], []
    event.listen(
        support.unit_of_work.engine,
        "before_cursor_execute",
        lambda *args: statements.append(args[2]),
    )
    event.listen(
        support.unit_of_work.engine,
        "engine_connect",
        lambda connection: connections.append(connection),
    )

    def measure(operation, bound):
        statements.clear()
        connections.clear()
        result = operation()
        assert len(connections) == 1
        assert not any(
            sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements
        )
        count = len(statements)
        assert count <= bound
        return result, count

    _, initial = measure(lambda: directories.properties(limit=100), 30)
    for index in range(99):
        fixtures.fixtures.property_record(portfolio, f"House {index}")
    page, many = measure(lambda: directories.properties(limit=100), 30)
    assert many == initial and len(page["items"]) == 100
    measure(lambda: directories.owners(limit=100), 30)
    measure(lambda: overviews.overview("property", property_record.id), 50)
    measure(lambda: overviews.overview("owner", owner.id), 50)


def test_former_owner_and_empty_current_scope_are_not_unavailable(context):
    _, portfolio, directories, _, overviews, _, _ = context
    portfolio._clock = lambda: datetime(2026, 1, 1, 19, tzinfo=UTC)
    owner, property_record = fixtures.owner_property(portfolio)
    inventory_command(
        portfolio,
        "replace_ownerships",
        property_record.id,
        (OwnershipInput("local_operator"),),
        "2026-01-02",
    )
    portfolio.archive_party(owner.id, confirmed=True)
    page = directories.owners(
        relationship_scope="former", archive_state="archived", property_state="all"
    )
    OwnerDirectoryPage.model_validate(page)
    assert page["items"][0]["coverage"]["matchingTotal"] == 5
    empty = overviews.overview("owner", owner.id, section="coverage")["sections"]["coverage"]
    assert (
        empty["availability"] == "available"
        and empty["matchingTotal"] == 0
        and empty["items"] == []
    )
    historical = overviews.overview(
        "owner", owner.id, relationship_scope="former", section="coverage"
    )
    assert historical["sections"]["coverage"]["matchingTotal"] == 5
    OverviewResponse.model_validate(historical)


def test_coverage_uses_same_snapshot_as_earlier_overview_sections(context):
    _, portfolio, _, _, overviews, sources, _ = context
    owner, _ = fixtures.owner_property(portfolio)
    original = sources.portfolio.relationships

    def interleave(connection, subject, window):
        page = original(connection, subject, window)
        fixtures.fixtures.property_record(
            portfolio, "New ownership", [OwnershipInput("client_owner", owner.id)]
        )
        return page

    with patch.object(sources.portfolio, "relationships", side_effect=interleave):
        response = overviews.overview("owner", owner.id)
    assert response["sections"]["properties"]["matchingTotal"] == 1
    coverage = response["sections"]["coverage"]
    assert coverage["matchingTotal"] == 5
    assert all(item["asOf"] == response["asOf"] for item in coverage["items"])
    assert (
        overviews.overview("owner", owner.id, section="coverage")["sections"]["coverage"][
            "matchingTotal"
        ]
        == 10
    )


def test_empty_and_over_limit_batches_issue_no_queries(context):
    _, _, _, support, _, _, _ = context
    sources = support.unit_of_work.sources.coverage
    with support.unit_of_work.engine.connect() as connection:
        statements = []
        event.listen(connection, "before_cursor_execute", lambda *args: statements.append(args[2]))
        assert sources.facts_for_subjects(connection, [], as_of=support.now()) == {}
        with pytest.raises(ValueError):
            sources.facts_for_subjects(
                connection,
                [
                    (CoverageSubject("property", str(index)), "maintenance")
                    for index in range(MAX_COVERAGE_SUBJECTS + 1)
                ],
                as_of=support.now(),
            )
        assert statements == []


@pytest.fixture
def populated():
    yield from populated_fixtures.populated.__wrapped__()


def test_populated_finance_and_review_evidence_match_single_reads(populated):
    fixture, overview, directories, owner, *_ = populated
    uow = overview.unit_of_work
    uow.sources = replace(uow.sources, coverage=compose_coverage_sources())
    coverage = OperatorCoverageService(uow, runtime=overview.runtime, now=overview.now)
    review(coverage, "space", fixture.lease["spaceId"], "rent")
    statements = []
    event.listen(uow.engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    response = overview.overview(
        "owner", owner.id, from_on="2026-10-01", through_on="2026-10-06", limit=50
    )
    assert len(statements) <= 50
    OverviewResponse.model_validate(response)
    for item in response["sections"]["coverage"]["items"]:
        assert item == coverage.read(item["subjectKind"], item["subjectId"], item["area"])
    PropertyDirectoryPage.model_validate(directories.properties())


def test_large_owner_scope_is_counted_before_bounded_hydration(context):
    _, portfolio, directories, support, overviews, _, _ = context
    owner, _ = fixtures.owner_property(portfolio)
    for index in range(100):
        fixtures.fixtures.property_record(
            portfolio, f"Property {index}", [OwnershipInput("client_owner", owner.id)]
        )
    sources = support.unit_of_work.sources.coverage
    original = sources.portfolio.locations
    statements, batches = [], []
    event.listen(
        support.unit_of_work.engine,
        "before_cursor_execute",
        lambda *args: statements.append(args[2]),
    )

    def hydrate(connection, subjects, *, as_of):
        batches.append(tuple(subjects))
        return original(connection, subjects, as_of=as_of)

    with patch.object(sources.portfolio, "locations", side_effect=hydrate):
        page = directories.owners()
        assert page["items"][0]["coverage"]["matchingTotal"] == 505
        assert len(batches[-1]) <= 5
        assert len(statements) <= 30
        statements.clear()
        response = overviews.overview(
            "owner", owner.id, limit=50, from_on="2026-10-01", through_on="2026-10-07"
        )
        section = response["sections"]["coverage"]
        assert section["matchingTotal"] == 505
        assert len(section["items"]) == 50 and section["nextCursor"]
        assert len(batches[-1]) <= 50
        assert len(statements) <= 50


def test_live_api_exposes_typed_previews_and_coverage_continuations(context):
    _, portfolio, directories, support, overviews, _, _ = context
    owner, property_record = fixtures.owner_property(portfolio)
    app = FastAPI()
    app.include_router(build_router(support, directories, overviews))
    with TestClient(app) as client:
        for route in ("properties", "owners"):
            response = client.get(f"/api/operator/{route}")
            assert response.status_code == HTTPStatus.OK, response.text
            assert response.json()["items"][0]["coverage"]["availability"] == "available"
        for kind, subject_id in (("properties", property_record.id), ("owners", owner.id)):
            route = f"/api/operator/{kind}/{subject_id}/overview"
            first = client.get(route, params={"section": "coverage", "sectionLimit": 1})
            assert first.status_code == HTTPStatus.OK, first.text
            cursor = first.json()["sections"]["coverage"]["nextCursor"]
            second = client.get(
                route, params={"section": "coverage", "sectionLimit": 1, "cursor": cursor}
            )
            assert second.status_code == HTTPStatus.OK, second.text
            assert (
                first.json()["sections"]["coverage"]["items"]
                != second.json()["sections"]["coverage"]["items"]
            )

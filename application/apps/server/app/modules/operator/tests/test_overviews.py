"""Actual source tables prove owner membership and independent bounded sections."""

from app.modules.portfolio.tests.commands import inventory_command

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from app.platform.testing_client import LocalApiClient as TestClient
from sqlalchemy import event
from sqlalchemy.exc import DBAPIError
import sqlite3

from app.modules.operator.tests import test_directories as fixtures
from app.modules.operator.application.overview_service import OperatorOverviewService
from app.modules.operator.infrastructure.overview_sources import OverviewSources
from app.modules.operator.api.overview_contracts import OverviewResponse
from app.modules.operator.api.router import build_router
from app.modules.operator.domain.models import (
    OperatorConflict,
    OperatorError,
    OperatorNotFound,
    OperatorStorageFailure,
    OperatorUnavailable,
)
from app.modules.portfolio.infrastructure.owner_context_reader import SQLiteOwnerContextReader
from app.modules.portfolio.infrastructure.location_relations import SQLitePortfolioLocationRelations
from app.modules.parties.infrastructure.identity_relations import SQLitePartyIdentityRelations
from app.modules.leases.infrastructure.location_relation import SQLiteLeaseLocationRelation
from app.modules.leases.infrastructure.summary_reader import SQLiteLeaseSummaryReader
from app.modules.maintenance.infrastructure.summary_reader import SQLiteIssueSummaryReader
from app.modules.communications.infrastructure.summary_reader import (
    SQLiteCommunicationSummaryReader,
)
from app.modules.owner_management.infrastructure.summary_reader import (
    SQLiteOwnerConcernSummaryReader,
)
from app.modules.tasks.infrastructure.summary_reader import SQLiteTaskSummaryReader
from app.modules.tasks.application.service import TaskService
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork
from app.modules.portfolio.application.service import OwnershipInput, PartyCreateCommand
from app.platform.product_migrations import validate_latest_schema
from app.modules.finance.infrastructure.context_relations import SQLiteFinanceContextRelations

DIRECTORY_BUDGET = 30
OVERVIEW_BUDGET = 50
PREVIEW_LIMIT = 3
PAGE_LIMIT = 50
MANY_PROPERTIES = 101


@pytest.fixture
def context(tmp_path):
    base = fixtures.directory.__wrapped__(tmp_path)
    workspace, portfolio, directories, support, _ = next(base)
    locations = SQLitePortfolioLocationRelations()
    leases = SQLiteLeaseLocationRelation(locations)
    sources = OverviewSources(
        SQLiteOwnerContextReader(SQLitePartyIdentityRelations()),
        locations,
        leases,
        SQLiteLeaseSummaryReader(leases),
        SQLiteIssueSummaryReader(),
        SQLiteCommunicationSummaryReader(),
        SQLiteTaskSummaryReader(),
        SQLiteOwnerConcernSummaryReader(),
        SQLiteFinanceContextRelations(leases),
    )
    support.unit_of_work.sources = replace(support.unit_of_work.sources, overview=sources)
    overviews = OperatorOverviewService(
        support.unit_of_work, runtime=support.runtime, now=directories.now
    )
    yield workspace, portfolio, directories, support, overviews, sources
    next(base, None)


def owner_property(portfolio, name="Owner", property_name="Home"):
    party = portfolio.create_party(PartyCreateCommand("individual", name))
    property = fixtures.property_record(
        portfolio, property_name, [OwnershipInput("client_owner", party.id)]
    )
    return party, property


def test_owner_directory_unicode_paging_and_address_membership(context):
    _, portfolio, directories, _, _, _ = context
    expected = [
        owner_property(portfolio, name)[0].id
        for name in ("Éclair A", "Éclair B", "Straße", "STRASSE")
    ]
    portfolio.create_party(PartyCreateCommand("individual", "Not an owner"))
    fixtures.property_record(portfolio, "Local-only home")
    cursor, seen = None, []
    while True:
        page = directories.owners(limit=1, cursor=cursor)
        seen.extend(item["partyId"] for item in page["items"])
        assert page["matchingTotal"] == len(expected)
        cursor = page["nextCursor"]
        if not cursor:
            break
    assert set(seen) == set(expected) and len(seen) == len(expected)
    assert directories.owners(text="Maple Street")["matchingTotal"] == len(expected)
    assert directories.owners(text="%_")["matchingTotal"] == 0


def test_former_archived_owner_remains_accessible_with_relationship_intervals(context):
    workspace, portfolio, directories, _, overviews, _ = context
    portfolio._clock = lambda: datetime(2026, 1, 1, 19, tzinfo=UTC)
    party, property = owner_property(portfolio)
    inventory_command(
        portfolio,
        "replace_ownerships",
        property.id,
        (OwnershipInput("local_operator"),),
        "2026-01-02",
    )
    portfolio.archive_party(party.id, confirmed=True)
    assert directories.owners()["matchingTotal"] == 0
    page = directories.owners(
        relationship_scope="former", archive_state="archived", property_state="all"
    )
    assert page["matchingTotal"] == 1
    assert page["items"][0]["partyId"] == party.id
    current = overviews.overview("owner", party.id)
    assert current["subject"]["archived"] is True
    assert current["sections"]["properties"]["matchingTotal"] == 0
    historical = overviews.overview("owner", party.id, relationship_scope="all")
    relationship = historical["sections"]["relationships"]["items"][0]
    assert relationship["startsOn"] == "2026-01-01"
    assert relationship["endsOn"] == "2026-01-02"
    assert relationship["relationshipState"] == "former"
    assert historical["sections"]["properties"]["matchingTotal"] == 1
    OverviewResponse.model_validate(historical)
    validate_latest_schema(workspace.paths.database)


def test_bounded_overview_sections_and_independent_continuation(context):
    workspace, portfolio, _, support, overviews, _ = context
    party, property = owner_property(portfolio)
    tasks = TaskService(
        SQLiteTaskUnitOfWork(workspace.paths.database, support.unit_of_work.recorder),
        now=overviews.now,
    )
    try:
        expected = {
            tasks.create(
                {
                    "title": f"Call {index}",
                    "relatedEntityType": "property",
                    "relatedEntityId": property.id,
                    "notes": "Never disclose this note",
                }
            ).id
            for index in range(13)
        }
        response = overviews.overview("property", property.id, limit=3)
        section = response["sections"]["tasks"]
        assert section["matchingTotal"] == len(expected)
        assert len(section["items"]) == PREVIEW_LIMIT
        assert all(item["asOf"] == response["asOf"] for item in section["items"])
        assert response["sections"]["money"]["reasonCode"] == "money_period_required"
        assert response["sections"]["coverage"]["availability"] == "unavailable"
        OverviewResponse.model_validate(response)
        seen = [item["id"] for item in section["items"]]
        cursor = section["nextCursor"]
        while cursor:
            following = overviews.overview(
                "property", property.id, limit=3, section="tasks", cursor=cursor
            )
            assert set(following["sections"]) == {"tasks"}
            section = following["sections"]["tasks"]
            seen.extend(item["id"] for item in section["items"])
            cursor = section["nextCursor"]
        assert set(seen) == expected and len(seen) == len(expected)
        owner = overviews.overview("owner", party.id, section="tasks")
        assert owner["sections"]["tasks"]["matchingTotal"] == len(expected)
        assert "Never disclose" not in str(response)
    finally:
        tasks.unit_of_work.engine.dispose()


def test_known_section_failure_does_not_erase_other_sources_or_claim_zero(context):
    _, portfolio, _, _, overviews, sources = context
    _, property = owner_property(portfolio)
    failure = DBAPIError("private SQL", {}, sqlite3.OperationalError("private path"))
    with patch.object(sources.communications, "page", side_effect=failure):
        response = overviews.overview("property", property.id)
    assert response["sections"]["communications"]["availability"] == "unavailable"
    assert "items" not in response["sections"]["communications"]
    assert response["sections"]["relationships"]["availability"] == "available"
    assert "private" not in str(response)
    OverviewResponse.model_validate(response)
    with (
        patch.object(sources.communications, "page", side_effect=TypeError("Programming defect")),
        pytest.raises(TypeError),
    ):
        overviews.overview("property", property.id)


def test_owner_membership_source_failure_fails_collection(context):
    _, portfolio, directories, _, _, sources = context
    owner_property(portfolio)
    failure = DBAPIError("private SQL", {}, sqlite3.OperationalError("private path"))
    with (
        patch.object(sources.portfolio, "owners", side_effect=failure),
        pytest.raises(OperatorStorageFailure),
    ):
        directories.owners()


def test_same_snapshot_survives_write_between_sections(context):
    _, portfolio, _, _, overviews, sources = context
    party, property = owner_property(portfolio)
    original = sources.portfolio.relationships

    def interleave(connection, subject, window):
        page = original(connection, subject, window)
        fixtures.property_record(
            portfolio, "Newly owned", [OwnershipInput("client_owner", party.id)]
        )
        return page

    with patch.object(sources.portfolio, "relationships", side_effect=interleave):
        response = overviews.overview(
            "owner", party.id, from_on="2026-10-01", through_on="2026-10-07"
        )
    assert response["sections"]["properties"]["matchingTotal"] == 1
    assert response["sections"]["money"]["summary"]["scope"]["property_count"] == 1
    assert overviews.overview("owner", party.id)["sections"]["properties"]["matchingTotal"] > 1


def test_large_owner_scope_and_query_budgets_are_independent_of_page_size(context):
    _, portfolio, directories, support, overviews, _ = context
    party, _ = owner_property(portfolio)
    for index in range(MANY_PROPERTIES):
        fixtures.property_record(
            portfolio, f"Property {index}", [OwnershipInput("client_owner", party.id)]
        )
    statements = []
    event.listen(
        support.unit_of_work.engine,
        "before_cursor_execute",
        lambda _conn, _cur, sql, *_args: statements.append(sql),
    )
    directory = directories.owners(limit=100)
    assert len(statements) <= DIRECTORY_BUDGET
    assert directory["items"][0]["propertyCount"] == MANY_PROPERTIES + 1
    assert len(directory["items"][0]["properties"]) == PREVIEW_LIMIT
    statements.clear()
    small = overviews.overview(
        "owner", party.id, limit=1, from_on="2026-10-01", through_on="2026-10-07"
    )
    small_count = len(statements)
    statements.clear()
    large = overviews.overview(
        "owner", party.id, limit=PAGE_LIMIT, from_on="2026-10-01", through_on="2026-10-07"
    )
    assert len(statements) == small_count <= OVERVIEW_BUDGET
    assert len(large["sections"]["properties"]["items"]) == PAGE_LIMIT
    assert large["sections"]["money"]["summary"]["scope"]["property_count"] == MANY_PROPERTIES + 1
    assert (
        large["sections"]["money"]["scopeMeaning"]
        == "whole_property_activity_not_owner_entitlement"
    )
    assert small["sections"]["properties"]["matchingTotal"] == MANY_PROPERTIES + 1
    assert any("LIMIT" in statement for statement in statements)


def test_typed_api_unknown_owner_and_malformed_filters(context):
    _, portfolio, directories, support, overviews, _ = context
    party, property = owner_property(portfolio)
    app = FastAPI()
    app.include_router(build_router(support, directories, overviews))
    with TestClient(app) as client:
        assert client.get("/api/operator/owners").status_code == HTTPStatus.OK
        response = client.get(f"/api/operator/properties/{property.id}/overview")
        assert response.status_code == HTTPStatus.OK, response.text
        assert (
            client.get(
                f"/api/operator/owners/{party.id}/overview?fromOn=2026-10-01&throughOn=2026-10-07"
            ).status_code
            == HTTPStatus.OK
        )
        assert (
            client.get("/api/operator/owners?relationshipScope=fictional").status_code
            == HTTPStatus.UNPROCESSABLE_ENTITY
        )
        assert (
            client.get(f"/api/operator/owners/{party.id}/overview?fromOn=bad").status_code
            == HTTPStatus.UNPROCESSABLE_ENTITY
        )
        assert (
            client.get(f"/api/operator/owners/{uuid4()}/overview").status_code
            == HTTPStatus.NOT_FOUND
        )
        assert (
            client.get(f"/api/operator/owners/{party.id}/overview?sectionLimit=51").status_code
            == HTTPStatus.UNPROCESSABLE_ENTITY
        )
        schema = client.get("/openapi.json").json()
        assert (
            schema["paths"]["/api/operator/owners/{subject_id}/overview"]["get"]["operationId"]
            == "getOperatorOwnerOverview"
        )


def test_continuation_requires_subject_section_period_and_fresh_sources(context):
    _, portfolio, _, support, overviews, _ = context
    party, property = owner_property(portfolio)
    fixtures.property_record(portfolio, "Second", [OwnershipInput("client_owner", party.id)])
    page = overviews.overview("owner", party.id, limit=1, section="properties")
    cursor = page["sections"]["properties"]["nextCursor"]
    with pytest.raises(OperatorConflict):
        overviews.overview("owner", party.id, limit=1, section="relationships", cursor=cursor)
    with pytest.raises(OperatorError):
        overviews.overview("owner", party.id, cursor=cursor)
    overviews.now = lambda: datetime(2026, 10, 7, 19, tzinfo=UTC) + timedelta(minutes=15)
    with pytest.raises(OperatorConflict):
        overviews.overview("owner", party.id, limit=1, section="properties", cursor=cursor)
    with pytest.raises(OperatorNotFound):
        overviews.overview("owner", str(uuid4()))


def test_owner_membership_uses_property_local_end_exclusive_dates(context):
    _, portfolio, directories, _, _, _ = context
    former, property = owner_property(portfolio, "First owner")
    upcoming = portfolio.create_party(PartyCreateCommand("individual", "Next owner"))
    inventory_command(
        portfolio,
        "replace_ownerships",
        property.id,
        (OwnershipInput("client_owner", upcoming.id),),
        "2026-10-08",
    )
    owner_property(portfolio, "Unchanged owner")
    directories.now = lambda: datetime(2026, 10, 8, 6, 59, tzinfo=UTC)
    before = directories.owners(limit=1)
    assert directories.owners(text="First owner")["matchingTotal"] == 1
    assert directories.owners(text="Next owner")["matchingTotal"] == 0
    directories.now = lambda: datetime(2026, 10, 8, 7, tzinfo=UTC)
    assert directories.owners(text="First owner")["matchingTotal"] == 0
    assert directories.owners(text="Next owner")["matchingTotal"] == 1
    assert (
        directories.owners(text="First owner", relationship_scope="former")["items"][0]["partyId"]
        == former.id
    )
    with pytest.raises(OperatorConflict):
        directories.owners(limit=1, cursor=before["nextCursor"])


def test_owner_directory_page_budget_with_distinct_owners(context):
    _, portfolio, directories, support, _, _ = context
    expected = {owner_property(portfolio, f"Owner {index:03d}")[0].id for index in range(100)}
    statements = []
    event.listen(
        support.unit_of_work.engine,
        "before_cursor_execute",
        lambda _conn, _cur, sql, *_args: statements.append(sql),
    )
    directories.owners(limit=1)
    small_count = len(statements)
    statements.clear()
    page = directories.owners(limit=100)
    assert {item["partyId"] for item in page["items"]} == expected
    assert page["matchingTotal"] == len(expected)
    assert len(statements) == small_count <= DIRECTORY_BUDGET
    assert all(len(item["properties"]) <= PREVIEW_LIMIT for item in page["items"])


def test_not_ready_context_reads_never_open_database(context):
    _, _, directories, support, overviews, _ = context
    identity = replace(support.runtime(), state="unavailable", can_write=False)
    directories.runtime = overviews.runtime = lambda: identity
    with patch.object(support.unit_of_work, "read", side_effect=AssertionError("Database opened")):
        with pytest.raises(OperatorUnavailable):
            directories.owners()
        with pytest.raises(OperatorUnavailable):
            overviews.overview("property", str(uuid4()))

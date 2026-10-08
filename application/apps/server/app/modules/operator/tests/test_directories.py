"""Bounded OPS property composition through actual source tables and APIs."""

from app.modules.portfolio.tests.commands import inventory_command

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4
from http import HTTPStatus

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.read_marker import SQLiteAuditReadMarker
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.leases.infrastructure.participant_relations import SQLiteLeaseParticipantRelations
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseParticipantModel
from app.modules.operator.api.router import build_router
from app.modules.operator.application.directory_service import OperatorDirectoryService
from app.modules.operator.application.ports import RuntimeIdentity
from app.modules.operator.application.service import OperatorService
from app.modules.operator.domain.models import OperatorConflict, OperatorError, OperatorUnavailable
from app.modules.operator.infrastructure.unit_of_work import (
    SQLiteOperatorUnitOfWork,
    SQLiteOperatorTransaction,
    OperatorReadSources,
)
from app.modules.parties.infrastructure.identity_relations import SQLitePartyIdentityRelations
from app.modules.portfolio.application.service import (
    PortfolioService,
    PropertyCreateCommand,
    OwnershipInput,
    PartyCreateCommand,
    SpaceCreateCommand,
)
from app.modules.portfolio.infrastructure.directory_reader import SQLitePortfolioDirectoryReader
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioUnitOfWork
from app.modules.tenants.infrastructure.sqlalchemy_models import TenantProfileModel
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig
from app.platform.sqlite_engine import create_sqlite_engine
from app.modules.finance.application.money_models import MoneyQuery
from app.modules.finance.infrastructure.money_context_reader import SQLiteMoneyContextReader
from app.modules.portfolio.infrastructure.location_relations import SQLitePortfolioLocationRelations
from app.modules.leases.infrastructure.location_relation import SQLiteLeaseLocationRelation
from app.modules.tasks.application.service import TaskService
from app.modules.tasks.infrastructure.context_reader import SQLiteTaskContextReader
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork

PREVIEW_LIMIT = 3
TASK_COUNT = 15
UNICODE_PROPERTIES = 4
PAIR_COUNT = 2
OWNER_COUNT = 8
SPACE_COUNT = 13
DIRECTORY_PAGE_SIZE = 100
DIRECTORY_QUERY_BUDGET = 30


class NoReferences:
    def validate(self, connection, value):
        return "available"


@pytest.fixture
def directory(tmp_path):
    workspace = WorkspaceService(LocalConfig(tmp_path / "config.json", tmp_path / "workspace"))
    manifest = workspace.initialize()
    recorder = AuditRecorder(SQLiteAuditRepository(workspace.paths.database))
    captured = datetime(2026, 10, 7, 19, tzinfo=UTC)
    portfolio = PortfolioService(
        SQLitePortfolioUnitOfWork(workspace.paths.database, recorder),
        time_zone_resolver=BundledAddressTimeZoneResolver(),
        now=lambda: captured,
    )
    reader = SQLitePortfolioDirectoryReader(
        SQLitePartyIdentityRelations(), SQLiteLeaseParticipantRelations()
    )
    locations = SQLitePortfolioLocationRelations()
    marker = SQLiteAuditReadMarker()
    uow = SQLiteOperatorUnitOfWork(
        workspace.paths.database,
        recorder,
        NoReferences(),
        marker,
        sources=OperatorReadSources(
            directory=reader,
            money=SQLiteMoneyContextReader(
                locations, SQLiteLeaseLocationRelation(locations), marker
            ),
            tasks=SQLiteTaskContextReader(),
        ),
    )
    identity = RuntimeIdentity("ready", manifest.workspace_id, str(uuid4()), True)
    directories = OperatorDirectoryService(uow, runtime=lambda: identity, now=lambda: captured)
    support = OperatorService(uow, runtime=lambda: identity, now=lambda: captured)
    yield workspace, portfolio, directories, support, reader
    uow.engine.dispose()
    portfolio.unit_of_work.engine.dispose()


def test_ops_sources_share_connection_instant_and_bounded_task_previews(directory):
    workspace, portfolio, directories, support, _ = directory
    property_id = property_record(portfolio).id
    recorder = AuditRecorder(SQLiteAuditRepository(workspace.paths.database))
    tasks = TaskService(SQLiteTaskUnitOfWork(workspace.paths.database, recorder))
    try:
        for index in range(15):
            tasks.create(
                {
                    "title": f"Follow up {index}",
                    "relatedEntityType": "property",
                    "relatedEntityId": property_id,
                }
            )
        instant = directories.now()
        identity = support.runtime()
        with (
            support.unit_of_work.engine.connect() as connection,
            connection.begin(),
            patch(
                "sqlalchemy.engine.Engine.connect", side_effect=AssertionError("Nested connection")
            ),
        ):
            uow = support.unit_of_work
            tx = SQLiteOperatorTransaction(
                connection,
                uow.recorder,
                uow.references,
                uow.marker,
                uow.sources,
            )
            tx.source_marker()
            money = tx.money_summary(
                MoneyQuery("2026-10-01", "2026-10-07", property_ids=(property_id,)),
                as_of=instant,
                identity=(identity.workspace_id, identity.epoch),
            )
            previews = tx.task_previews("property", [property_id], as_of=instant, limit=3)
            assert money.scope.property_count == 1
            assert money.as_of == instant.isoformat()
            assert previews[property_id].total == TASK_COUNT
            assert len(previews[property_id].items) == PREVIEW_LIMIT
            assert all(item.as_of == money.as_of for item in previews[property_id].items)
            assert connection.in_transaction()
    finally:
        tasks.unit_of_work.engine.dispose()


def property_record(portfolio, name="Maple", ownerships=None, office=False):
    return inventory_command(
        portfolio,
        "create_property",
        PropertyCreateCommand(
            name,
            "10 Maple Street",
            "Portland",
            "US",
            "office" if office else "single_family_home",
            tuple(ownerships or [OwnershipInput("local_operator")]),
            region="OR",
            postal_code="97201",
            inventory_layout="office_suites" if office else None,
            spaces=(SpaceCreateCommand("Initial suite"),) if office else None,
        ),
    )


def test_unicode_cursor_pages_have_no_gaps_and_matching_totals(directory):
    _, portfolio, directories, _, _ = directory
    for name in ("Éclair A", "Éclair B", "Straße", "STRASSE"):
        property_record(portfolio, name)
    seen, cursor = [], None
    while True:
        page = directories.properties(limit=1, cursor=cursor)
        assert page["matchingTotal"] == UNICODE_PROPERTIES
        seen.extend(row["id"] for row in page["items"])
        cursor = page["nextCursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == UNICODE_PROPERTIES


def test_membership_filters_apply_before_limit_and_count(directory):
    _, portfolio, directories, _, _ = directory
    property_record(portfolio, "First")
    owner = portfolio.create_party(PartyCreateCommand("individual", "Émily Owner"))
    match = property_record(portfolio, "Last", [OwnershipInput("client_owner", owner.id)])
    page = directories.properties(
        text="ÉMILY", limit=1, ownership_context="managed_for_owner", needs_attention=True
    )
    assert page["matchingTotal"] == 1
    assert page["items"][0]["id"] == match.id
    assert page["items"][0]["owners"][0]["displayName"] == "Émily Owner"
    assert page["items"][0]["effectiveLocalDate"] == "2026-10-07"
    assert page["items"][0]["coverage"]["availability"] == "unavailable"
    assert directories.properties(text="Maple Street")["matchingTotal"] == PAIR_COUNT
    assert (
        directories.properties(occupancy="unknown", availability="unknown")["matchingTotal"]
        == PAIR_COUNT
    )
    assert directories.properties(text="%_")["matchingTotal"] == 0


def test_child_previews_are_bounded_but_counts_are_complete(directory):
    _, portfolio, directories, _, _ = directory
    owners = [
        portfolio.create_party(PartyCreateCommand("individual", f"Owner {index}"))
        for index in range(8)
    ]
    item = property_record(
        portfolio, ownerships=[OwnershipInput("client_owner", x.id) for x in owners], office=True
    )
    for index in range(12):
        inventory_command(portfolio, "add_space", item.id, SpaceCreateCommand(f"Suite {index}"))
    card = directories.properties()["items"][0]
    assert card["ownerCount"] == OWNER_COUNT
    assert len(card["owners"]) == PREVIEW_LIMIT
    assert card["spaceCount"] == SPACE_COUNT
    assert len(card["spaces"]) == PREVIEW_LIMIT


def test_queries_and_hydration_stay_bounded_for_one_and_one_hundred(directory):
    _, portfolio, directories, _, _ = directory
    for index in range(102):
        property_record(portfolio, f"Property {index:03}")
    statements = []
    event.listen(
        directories.unit_of_work.engine,
        "before_cursor_execute",
        lambda *args: statements.append(args[2]),
    )
    directories.properties(limit=1)
    small = len([sql for sql in statements if sql.lstrip().upper().startswith("SELECT")])
    statements.clear()
    page = directories.properties(limit=100)
    large = len([sql for sql in statements if sql.lstrip().upper().startswith("SELECT")])
    assert len(page["items"]) == DIRECTORY_PAGE_SIZE
    assert large == small <= DIRECTORY_QUERY_BUDGET
    # Selection is SQL-bounded; neither ownership history nor all spaces are hydrated.
    assert sum("LIMIT" in sql.upper() for sql in statements) >= 1
    assert sum("ROW_NUMBER()" in sql.upper() for sql in statements) >= PAIR_COUNT


def test_read_count_and_page_share_snapshot_despite_concurrent_write(directory):
    workspace, portfolio, directories, _, _ = directory
    original = property_record(portfolio, "Original")
    original_method = directories.unit_of_work.sources.directory.properties
    inserted = False

    def interleave(connection, query, **kwargs):
        nonlocal inserted
        if not inserted:
            inserted = True
            # Source marker has already established the deferred read snapshot.
            inventory_command(
                portfolio,
                "create_property",
                PropertyCreateCommand(
                    "New",
                    "11 Maple Street",
                    "Portland",
                    "US",
                    "single_family_home",
                    (OwnershipInput("local_operator"),),
                    region="OR",
                    postal_code="97201",
                ),
            )
        return original_method(connection, query, **kwargs)

    with patch.object(
        directories.unit_of_work.sources.directory, "properties", side_effect=interleave
    ):
        page = directories.properties()
    assert page["matchingTotal"] == 1
    assert [row["id"] for row in page["items"]] == [original.id]
    assert directories.properties()["matchingTotal"] == PAIR_COUNT


def test_cursor_rejects_source_changes_expiry_and_local_midnight(directory):
    _, portfolio, directories, _, _ = directory
    for name in ("A", "B"):
        property_record(portfolio, name)
    first = directories.properties(limit=1)
    with pytest.raises(OperatorConflict):
        directories.properties(limit=2, cursor=first["nextCursor"])
    directories.now = lambda: datetime(2026, 10, 7, 19, 15, tzinfo=UTC)
    with pytest.raises(OperatorConflict):
        directories.properties(limit=1, cursor=first["nextCursor"])
    directories.now = lambda: datetime(2026, 10, 8, 6, 59, tzinfo=UTC)
    first = directories.properties(limit=1)
    directories.now = lambda: datetime(2026, 10, 8, 7, 1, tzinfo=UTC)
    with pytest.raises(OperatorConflict):
        directories.properties(limit=1, cursor=first["nextCursor"])
    property_record(portfolio, "C")
    with pytest.raises(OperatorConflict):
        directories.properties(limit=1, cursor=first["nextCursor"])


def test_api_has_typed_filters_and_named_contract(directory):
    _, portfolio, directories, support, _ = directory
    property_record(portfolio)
    app = FastAPI()
    app.include_router(build_router(support, directories))
    with TestClient(app) as client:
        assert client.get("/api/operator/properties").status_code == HTTPStatus.OK
        assert (
            client.get("/api/operator/properties?limit=101").status_code
            == HTTPStatus.UNPROCESSABLE_ENTITY
        )
        assert (
            client.get("/api/operator/properties?occupancy=empty").status_code
            == HTTPStatus.UNPROCESSABLE_ENTITY
        )
        assert (
            client.get("/api/operator/properties?cursor=bad").status_code
            == HTTPStatus.UNPROCESSABLE_ENTITY
        )
        operation = client.get("/openapi.json").json()["paths"]["/api/operator/properties"]["get"]
        assert operation["operationId"] == "getOperatorProperties"
    with pytest.raises(OperatorError):
        directories.properties(limit=True)
    directories.runtime = lambda: RuntimeIdentity("busy", None, str(uuid4()), False)
    with patch.object(
        directories.unit_of_work, "read", side_effect=AssertionError("read while gated")
    ):
        with pytest.raises(OperatorUnavailable):
            directories.properties()


@pytest.mark.parametrize(
    "scenario",
    [
        ("draft", "2026-10-01", None, None, 0),
        ("void", "2026-10-01", None, None, 0),
        ("executed", "2026-10-08", None, None, 0),
        ("executed", "2026-10-01", None, "2026-10-07", 0),
        ("ended", "2026-10-01", "2026-10-07", None, 0),
        ("terminated", "2026-10-01", "2026-10-08", None, 1),
        ("executed", "2026-10-01", None, None, 1),
    ],
)
def test_tenant_search_uses_effective_occupancy_and_participant_intervals(directory, scenario):
    lease_status, starts, move_out, participant_end, expected = scenario
    workspace, portfolio, directories, _, _ = directory
    item = property_record(portfolio)
    party = portfolio.create_party(PartyCreateCommand("individual", "Éclair Tenant"))
    space = portfolio.unit_of_work.spaces(item.id)[0]
    lease_id, stamp = str(uuid4()), datetime(2026, 10, 7, 19, tzinfo=UTC).isoformat()
    # Raw source facts vary independently for the search adapter's eligibility proof.
    engine = create_sqlite_engine(workspace.paths.database)
    with engine.begin() as connection:
        connection.execute(
            TenantProfileModel.__table__.insert().values(
                party_id=party.id,
                do_not_contact=0,
                created_at=stamp,
                updated_at=stamp,
            )
        )
        connection.execute(
            LeaseModel.__table__.insert().values(
                id=lease_id,
                lease_revision=1,
                space_id=space.id,
                lease_kind="residential",
                status=lease_status,
                contract_starts_on="2026-10-01",
                occupancy_starts_on=starts,
                executed_on=None if lease_status == "draft" else "2026-10-01",
                actual_move_out_on=move_out,
                end_reason="contract_completed"
                if lease_status == "ended"
                else "early_termination"
                if lease_status == "terminated"
                else None,
                created_at=stamp,
                updated_at=stamp,
            )
        )
        connection.execute(
            LeaseParticipantModel.__table__.insert().values(
                id=str(uuid4()),
                lease_id=lease_id,
                tenant_party_id=party.id,
                participant_role="primary_tenant",
                starts_on="2026-10-01",
                ends_on=participant_end,
                created_at=stamp,
                updated_at=stamp,
            )
        )
    assert directories.properties(text="ÉCLAIR TENANT")["matchingTotal"] == expected
    engine.dispose()

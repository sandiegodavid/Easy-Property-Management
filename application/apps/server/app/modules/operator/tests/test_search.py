"""Registered metadata only: real sources, bounded SQL and one read snapshot."""

from app.modules.portfolio.tests.commands import inventory_command

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from app.platform.testing_client import LocalApiClient as TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from app.bootstrap.operator_search import compose_metadata_search
from app.modules.operator.application.search_service import OperatorSearchService
from app.modules.operator.application.search_ports import (
    MetadataSearchRegistry,
    SearchRegistration,
    SEARCH_KINDS,
)
from app.modules.operator.api.router import build_router
from app.modules.operator.api.search_router import SearchResponse
from app.modules.operator.domain.models import OperatorConflict, OperatorError, OperatorUnavailable
from app.modules.operator.tests import test_overviews as overview_fixtures
from app.modules.operator.tests import test_context_sources as source_fixtures
from app.modules.operator.tests.test_overviews import owner_property
from app.modules.operator.tests.test_directories import property_record
from app.modules.portfolio.application.service import OwnershipInput, PartyCreateCommand
from app.modules.tasks.application.service import TaskService
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork
from app.platform.product_migrations import validate_latest_schema
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.operator.infrastructure.unit_of_work import SQLiteOperatorUnitOfWork
from app.modules.operator.application.ports import RuntimeIdentity

PAGE_LIMIT = 50
MANY_RECORDS = 100
SHARED_SELECTS = 2
PER_GROUP_BUDGET = 4


@pytest.fixture
def context(tmp_path):
    yield from overview_fixtures.context.__wrapped__(tmp_path)


@pytest.fixture
def populated():
    yield from source_fixtures.populated.__wrapped__()


def search_service(uow, runtime, now):
    uow.sources = replace(uow.sources, search=compose_metadata_search())
    return OperatorSearchService(uow, runtime=runtime, now=now)


@pytest.fixture
def searching(context):
    _, _, directories, support, _, _ = context
    return search_service(support.unit_of_work, support.runtime, directories.now)


def test_registered_real_source_metadata_and_privacy(populated):
    fixture, overview, _, party, issue, communication, _, task = populated
    search = search_service(overview.unit_of_work, overview.runtime, overview.now)
    expected = (
        ("properties", "Rent home", fixture.property_id),
        ("spaces", "Rent home", fixture.leases.get(fixture.lease["id"])["spaceId"]),
        ("owners", "Client owner", party.id),
        ("tenants", "Tenant", fixture.tenant["id"]),
        ("leases", "Rent home", fixture.lease["id"]),
        ("communications", "Owner update", communication["id"]),
        ("maintenance", "Repair", issue["id"]),
        ("tasks", "Follow up", task.id),
    )
    for kind, text, identifier in expected:
        result = search.search(text, group=kind)
        group = result["groups"][kind]
        assert identifier in {row["sourceId"] for row in group["items"]}
        assert group["matchingTotal"] >= len(group["items"])
        assert group["sourceRevision"] == result["sourceRevision"]
        SearchResponse.model_validate(result)
    result = search.search("Private")
    assert set(result["groups"]) == set(SEARCH_KINDS)
    assert all(group["matchingTotal"] == 0 for group in result["groups"].values())
    assert "Private" not in str(result["groups"])
    validate_latest_schema(fixture.db)


def test_unicode_literal_search_and_independent_no_gap_group_pages(context, searching):
    workspace, portfolio, _, support, _, _ = context
    property_ids = {
        owner_property(portfolio, f"Éclair {letter}", f"Éclair {letter}")[1].id for letter in "ABC"
    }
    tasks = TaskService(
        SQLiteTaskUnitOfWork(workspace.paths.database, support.unit_of_work.recorder)
    )
    try:
        for letter in "ABC":
            tasks.create({"title": f"Éclair {letter}"})
        initial = searching.search("  E\u0301CLAIR  ", limit=1)
        assert initial["query"]["q"] == "  E\u0301CLAIR  "
        assert initial["query"]["normalizedQ"] == "éclair"
        assert initial["groups"]["tasks"]["nextCursor"]
        assert initial["groups"]["properties"]["nextCursor"]
        seen, cursor = [], None
        while True:
            response = searching.search("Éclair", group="properties", limit=1, cursor=cursor)
            assert set(response["groups"]) == {"properties"}
            section = response["groups"]["properties"]
            assert section["matchingTotal"] == len(property_ids)
            seen.extend(row["sourceId"] for row in section["items"])
            cursor = section["nextCursor"]
            if not cursor:
                break
        assert len(seen) == len(set(seen)) and set(seen) == property_ids
        property_record(portfolio, "Literal %_ home")
        assert (
            searching.search("%_", group="properties")["groups"]["properties"]["matchingTotal"] == 1
        )
        assert searching.search("%_", group="tasks")["groups"]["tasks"]["matchingTotal"] == 0
    finally:
        tasks.unit_of_work.engine.dispose()


def test_archived_records_are_opt_in_and_nonowners_are_excluded(context, searching):
    _, portfolio, _, _, _, _ = context
    property = property_record(portfolio, "Archived home")
    inventory_command(portfolio, "archive_property", property.id, confirmed=True)
    assert (
        searching.search("Archived home", group="properties")["groups"]["properties"][
            "matchingTotal"
        ]
        == 0
    )
    retained = searching.search("Archived home", group="properties", include_archived=True)
    assert retained["groups"]["properties"]["items"][0]["archived"] is True
    portfolio._clock = lambda: datetime(2026, 1, 1, 19, tzinfo=UTC)
    party, property = owner_property(portfolio, "Historical owner")
    inventory_command(
        portfolio,
        "replace_ownerships",
        property.id,
        (OwnershipInput("local_operator"),),
        "2026-01-02",
    )
    portfolio.archive_party(party.id, confirmed=True)
    portfolio.create_party(PartyCreateCommand("individual", "Unrelated identity"))
    assert searching.search("Historical", group="owners")["groups"]["owners"]["matchingTotal"] == 0
    assert (
        searching.search("Historical", group="owners", include_archived=True)["groups"]["owners"][
            "items"
        ][0]["sourceId"]
        == party.id
    )
    assert (
        searching.search("Unrelated", group="owners", include_archived=True)["groups"]["owners"][
            "matchingTotal"
        ]
        == 0
    )


def test_group_failure_is_unavailable_not_zero_and_bugs_propagate(searching):
    registry = searching.unit_of_work.sources.search
    failure = DBAPIError("sensitive SQL", {}, sqlite3.OperationalError("private storage path"))
    with patch.object(registry.reader("communications"), "search", side_effect=failure):
        response = searching.search("Example")
    assert response["groups"]["communications"]["availability"] == "unavailable"
    assert response["groups"]["communications"]["matchingTotal"] is None
    assert response["groups"]["tasks"]["availability"] == "available"
    assert "private" not in str(response)
    SearchResponse.model_validate(response)
    with (
        patch.object(registry.reader("communications"), "search", side_effect=TypeError("Bug")),
        pytest.raises(TypeError),
    ):
        searching.search("Example")


def test_cursor_binds_group_query_archives_bounds_and_runtime(context, searching):
    _, portfolio, _, _, _, _ = context
    for label in ("Home A", "Home B"):
        property_record(portfolio, label)
    response = searching.search("Home", group="properties", limit=1)
    cursor = response["groups"]["properties"]["nextCursor"]
    for changed in (
        {"group": "spaces"},
        {"text": "Another"},
        {"include_archived": True},
        {"limit": 10},
    ):
        arguments = {"text": "Home", "group": "properties", "limit": 1, "cursor": cursor, **changed}
        with pytest.raises(OperatorConflict):
            searching.search(**arguments)
    original_runtime = searching.runtime()
    searching.runtime = lambda: replace(original_runtime, epoch=str(uuid4()))
    with pytest.raises(OperatorConflict):
        searching.search("Home", group="properties", limit=1, cursor=cursor)
    searching.runtime = lambda: original_runtime
    instant = searching.now()
    searching.now = lambda: instant + timedelta(minutes=15)
    with pytest.raises(OperatorConflict):
        searching.search("Home", group="properties", limit=1, cursor=cursor)
    searching.now = lambda: instant
    property_record(portfolio, "Home C")
    with pytest.raises(OperatorConflict):
        searching.search("Home", group="properties", limit=1, cursor=cursor)


def test_membership_clock_boundary_invalidates_owner_search_cursor(context, searching):
    _, portfolio, _, _, _, _ = context
    owner, property = owner_property(portfolio, "Owner A")
    owner_property(portfolio, "Owner B")
    successor = portfolio.create_party(PartyCreateCommand("individual", "Owner C"))
    inventory_command(
        portfolio,
        "replace_ownerships",
        property.id,
        (OwnershipInput("client_owner", successor.id),),
        "2026-10-08",
    )
    searching.now = lambda: datetime(2026, 10, 8, 6, 59, tzinfo=UTC)
    page = searching.search("Owner", group="owners", limit=1)
    cursor = page["groups"]["owners"]["nextCursor"]
    assert page["groups"]["owners"]["items"][0]["sourceId"] == owner.id
    searching.now = lambda: datetime(2026, 10, 8, 7, tzinfo=UTC)
    with pytest.raises(OperatorConflict):
        searching.search("Owner", group="owners", limit=1, cursor=cursor)
    assert searching.search("Owner C", group="owners")["groups"]["owners"]["matchingTotal"] == 1


def test_search_snapshot_and_read_only_single_connection(context, searching):
    _, portfolio, _, support, _, _ = context
    owner_property(portfolio, "Snapshot owner", "Snapshot home")
    registry = searching.unit_of_work.sources.search
    original = registry.reader("properties").search

    def interleave(connection, term, window):
        page = original(connection, term, window)
        owner_property(portfolio, "Snapshot later", "Snapshot later")
        return page

    with patch.object(registry.reader("properties"), "search", side_effect=interleave):
        response = searching.search("Snapshot")
    assert response["groups"]["owners"]["matchingTotal"] == 1
    assert searching.search("Snapshot")["groups"]["owners"]["matchingTotal"] > 1
    statements, connections = [], []

    def opened(connection):
        connections.append(connection)

    def executed(_connection, _cursor, sql, *_args):
        statements.append(sql)

    event.listen(Engine, "engine_connect", opened)
    event.listen(support.unit_of_work.engine, "before_cursor_execute", executed)
    try:
        response = searching.search("Snapshot")
    finally:
        event.remove(Engine, "engine_connect", opened)
        event.remove(support.unit_of_work.engine, "before_cursor_execute", executed)
    assert len(connections) == 1
    assert all(sql.lstrip().upper().startswith(("BEGIN", "SELECT", "PRAGMA")) for sql in statements)
    assert all(group["asOf"] == response["asOf"] for group in response["groups"].values())


def test_search_bounded_sql_counts_and_plans_with_many_distinct_results(context, searching):
    _, portfolio, _, support, _, _ = context
    for index in range(MANY_RECORDS):
        owner_property(portfolio, f"Metadata {index:03d}", f"Metadata {index:03d}")
    statements = []

    def executed(_conn, _cur, sql, parameters, *_args):
        if sql.lstrip().upper().startswith("SELECT"):
            statements.append((sql, parameters))

    event.listen(support.unit_of_work.engine, "before_cursor_execute", executed)
    try:
        small = searching.search("Metadata", limit=1)
        count = len(statements)
        statements.clear()
        large = searching.search("Metadata", limit=PAGE_LIMIT)
    finally:
        event.remove(support.unit_of_work.engine, "before_cursor_execute", executed)
    assert len(statements) == count <= len(SEARCH_KINDS) * PER_GROUP_BUDGET + SHARED_SELECTS
    for kind in ("properties", "owners"):
        assert small["groups"][kind]["matchingTotal"] == MANY_RECORDS
        assert large["groups"][kind]["matchingTotal"] == MANY_RECORDS
        assert len(large["groups"][kind]["items"]) == PAGE_LIMIT
    limited = [(sql, parameters) for sql, parameters in statements if "LIMIT" in sql]
    assert len(limited) >= len(SEARCH_KINDS)
    with support.unit_of_work.engine.connect() as connection:
        plans = [
            row[3]
            for sql, parameters in limited
            for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + sql, parameters)
        ]
    assert any("property_ownerships_party_active" in detail for detail in plans)


def test_http_contract_and_invalid_inputs(context, searching):
    _, portfolio, directories, support, overviews, _ = context
    owner_property(portfolio)
    app = FastAPI()
    app.include_router(build_router(support, directories, overviews, searching))
    with TestClient(app) as client:
        response = client.get("/api/operator/search?q=Home")
        assert response.status_code == HTTPStatus.OK, response.text
        assert set(response.json()["groups"]) == set(SEARCH_KINDS)
        for query in (
            "q=x",
            "q=++",
            "q=a+",
            "q=Home&group=providers",
            "q=Home&limit=51",
            "q=Home&cursor=bad",
            "q=Home&unexpected=true",
            "q=" + "x" * 241,
        ):
            assert (
                client.get("/api/operator/search?" + query).status_code
                == HTTPStatus.UNPROCESSABLE_ENTITY
            )
        assert (
            client.get("/api/operator/search?q=Home&group=properties&cursor=bad").status_code
            == HTTPStatus.UNPROCESSABLE_ENTITY
        )
        assert (
            client.get("/openapi.json").json()["paths"]["/api/operator/search"]["get"][
                "operationId"
            ]
            == "searchOperatorMetadata"
        )


def test_non_http_validation_readiness_and_registry_are_fail_closed(searching):
    for text in ("", " ", "a ", "ß", "e\u0301", "x" * 241):
        with pytest.raises(OperatorError):
            searching.search(text)
    with pytest.raises(OperatorError):
        searching.search("Home", group="unregistered")
    with pytest.raises(OperatorError):
        searching.search("Home", limit=True)
    with pytest.raises(OperatorError):
        searching.search("Home", group=[])
    entry = searching.unit_of_work.sources.search.definitions[0]
    reader = searching.unit_of_work.sources.search.reader(entry.kind)
    with pytest.raises(ValueError):
        MetadataSearchRegistry(
            (SearchRegistration(entry, reader), SearchRegistration(entry, reader))
        )
    identity = replace(searching.runtime(), state="unavailable", can_write=False)
    searching.runtime = lambda: identity
    with (
        patch.object(searching.unit_of_work, "read", side_effect=AssertionError("Database opened")),
        pytest.raises(OperatorUnavailable),
    ):
        searching.search("Home")


def test_hidden_destination_results_remain_eligible(context, searching):
    _, portfolio, _, support, _, _ = context
    current = support.preferences()
    support.update_preferences(
        appearance=current["appearance"],
        destination_order=current["destinationOrder"],
        hidden_destination_ids=("properties",),
        expected_revision=current["revision"],
        idempotency_key=str(uuid4()),
    )
    property = property_record(portfolio, "Hidden destination property")
    result = searching.search("Hidden", group="properties")
    assert result["groups"]["properties"]["items"][0]["sourceId"] == property.id


def test_every_registered_group_has_constant_bounded_query_cost(populated):
    _, overview, _, _, _, _, _, _ = populated
    service = search_service(overview.unit_of_work, overview.runtime, overview.now)
    statements = []

    def executed(_conn, _cursor, sql, *_args):
        if sql.lstrip().upper().startswith("SELECT"):
            statements.append(sql)

    event.listen(service.unit_of_work.engine, "before_cursor_execute", executed)
    try:
        for kind in SEARCH_KINDS:
            statements.clear()
            service.search("en", group=kind, limit=1)
            small = len(statements)
            statements.clear()
            service.search("en", group=kind, limit=PAGE_LIMIT)
            assert len(statements) == small <= PER_GROUP_BUDGET + SHARED_SELECTS
            sql = "\n".join(statements)
            assert "LIMIT" in sql
            for private_column in (
                "communications.body",
                "tasks.notes",
                "maintenance_issues.description",
                "tenant_profiles.notes",
                "leases.notes",
            ):
                assert private_column not in sql
    finally:
        event.remove(service.unit_of_work.engine, "before_cursor_execute", executed)


@fast_backup_encryption()
def test_encrypted_restore_preserves_metadata_results_and_invalidates_cursor(populated, tmp_path):
    fixture, overview, _, _, _, _, _, _ = populated
    search = search_service(overview.unit_of_work, overview.runtime, overview.now)
    before = search.search("update", limit=1)
    cursor = before["groups"]["communications"]["nextCursor"]
    assert cursor is not None
    recorder = AuditRecorder(SQLiteAuditRepository(fixture.db))
    backup = BackupService(
        fixture.workspace, recorder, lambda db: AuditRecorder(SQLiteAuditRepository(db))
    )
    passphrase = "a long metadata search backup passphrase"
    archive = backup.create_backup(passphrase, output_path=tmp_path / "search.epm-backup")
    target = tmp_path / "restored"
    backup.restore(archive.archive_path, passphrase, target)
    database = target / "database" / "property-management.sqlite"
    identity = RuntimeIdentity("ready", fixture.identity[0], str(uuid4()), True)
    uow = SQLiteOperatorUnitOfWork(
        database,
        AuditRecorder(SQLiteAuditRepository(database)),
        None,
        overview.unit_of_work.marker,
        sources=overview.unit_of_work.sources,
    )
    try:
        restored = OperatorSearchService(uow, runtime=lambda: identity, now=overview.now)
        after = restored.search("update", limit=1)
        for name, group in before["groups"].items():
            assert after["groups"][name]["items"] == group["items"]
            assert after["groups"][name]["matchingTotal"] == group["matchingTotal"]
        with pytest.raises(OperatorConflict):
            restored.search("update", limit=1, group="communications", cursor=cursor)
        validate_latest_schema(database)
    finally:
        uow.engine.dispose()

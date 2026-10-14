"""Bounded contributing inventory shares Home's source snapshot and cursor scope."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import event

from app.modules.operator.tests import test_home_api as http_fixtures
from app.modules.operator.tests import test_home_composition as fixtures
from app.modules.operator.application.home_contracts import HomeInventoryResponse
from app.modules.portfolio.infrastructure.sqlalchemy_models import PropertyModel, SpaceModel
from app.modules.portfolio.tests.test_attention_reader import property_row, space_row
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.tasks.application.service import TaskService
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork

HOME, PERIOD = http_fixtures.HOME, http_fixtures.PERIOD
INVENTORY = HOME + "/inventory"


@pytest.fixture
def context(tmp_path):
    yield from http_fixtures.context.__wrapped__(tmp_path)


@pytest.fixture
def api(context):
    yield from http_fixtures.api.__wrapped__(context)


def test_inventory_preview_first_page_exact_count_capture_and_read_only(api):
    client, context, _ = api
    service, _, property = context
    home = client.get(HOME, params=PERIOD).json()
    count = home["inventory"]["unknown"]
    with service.unit_of_work.engine.connect() as connection:
        before = connection.exec_driver_sql("SELECT count(*) FROM audit_events").scalar_one()
    with patch.object(service, "now", return_value=fixtures.NOW + timedelta(minutes=3)):
        result = client.get(
            INVENTORY, params={"occupancy": "unknown", "cursor": count["viewAllCursor"]}
        )
    assert result.status_code == 200, result.text
    page = HomeInventoryResponse.model_validate(result.json())
    assert page.matching_total == count["count"] == 1
    assert page.as_of.isoformat().replace("+00:00", "Z") == home["asOf"]
    assert page.items[0].property_id == UUID(property.id)
    assert page.property_state == "active" and page.items[0].occupancy == "unknown"
    assert page.items[0].time_zone == "America/Los_Angeles"
    assert client.get(INVENTORY, params={"occupancy": "vacant"}).json()["matchingTotal"] == 0
    with service.unit_of_work.engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT count(*) FROM audit_events").scalar_one() == before
        )


def test_inventory_pages_have_fixed_budget_and_no_gaps(api):
    client, context, _ = api
    service, _, _ = context
    statements = []

    def capture(connection, cursor, statement, parameters, ctx, executemany):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            statements.append(statement)

    event.listen(service.unit_of_work.engine, "before_cursor_execute", capture)
    try:
        assert client.get(INVENTORY, params={"occupancy": "unknown"}).status_code == 200
        baseline = len(statements)
        with service.unit_of_work.engine.begin() as connection:
            connection.execute(
                PropertyModel.__table__.insert(), [property_row(i) for i in range(1000, 1100)]
            )
            connection.execute(
                SpaceModel.__table__.insert(), [space_row(i + 1000, i) for i in range(1000, 1100)]
            )
        statements.clear()
        first = client.get(INVENTORY, params={"occupancy": "unknown", "limit": 100}).json()
        assert len(statements) == baseline <= 6
        assert first["matchingTotal"] == 101 and len(first["items"]) == 100
        assert any("LIMIT" in statement.upper() for statement in statements)
        second = client.get(
            INVENTORY, params={"occupancy": "unknown", "limit": 100, "cursor": first["nextCursor"]}
        ).json()
        assert second["matchingTotal"] == 101 and len(second["items"]) == 1
        assert second["nextCursor"] is None and second["asOf"] == first["asOf"]
        assert len({item["spaceId"] for item in first["items"] + second["items"]}) == 101
    finally:
        event.remove(service.unit_of_work.engine, "before_cursor_execute", capture)


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"occupancy": "occupied"},
        {"occupancy": "unknown", "limit": 101},
        {"occupancy": "unknown", "propertyId": "invalid"},
        {"occupancy": "unknown", "unexpected": "value"},
    ],
)
def test_inventory_typed_query_rejection(api, query):
    client, _, _ = api
    assert client.get(INVENTORY, params=query).status_code == 422


@pytest.mark.parametrize("cursor", ["x" * 4097, "é" * 2049], ids=["characters", "utf8-bytes"])
def test_inventory_oversized_cursor(api, cursor):
    client, _, _ = api
    assert (
        client.get(INVENTORY, params={"occupancy": "unknown", "cursor": cursor}).status_code == 413
    )


def test_inventory_missing_scope_cursor_bindings_and_source_change(api):
    client, context, _ = api
    home = client.get(HOME, params=PERIOD).json()
    token = home["inventory"]["unknown"]["viewAllCursor"]
    assert (
        client.get(
            INVENTORY, params={"occupancy": "unknown", "propertyId": str(UUID(int=99))}
        ).status_code
        == 404
    )
    assert client.get(INVENTORY, params={"occupancy": "vacant", "cursor": token}).status_code == 409
    assert (
        client.get(INVENTORY, params={"occupancy": "unknown", "cursor": "invalid"}).status_code
        == 422
    )
    database = Path(context[0].unit_of_work.engine.url.database)
    task_uow = SQLiteTaskUnitOfWork(database, AuditRecorder(SQLiteAuditRepository(database)))
    try:
        TaskService(task_uow).create({"title": "Audited source mutation"})
    finally:
        task_uow.engine.dispose()
    assert (
        client.get(INVENTORY, params={"occupancy": "unknown", "cursor": token}).status_code == 409
    )


def test_inventory_source_unavailable_is_not_empty(api):
    client, context, _ = api
    with patch.object(
        context[1].portfolio,
        "inventory_spaces",
        side_effect=fixtures.OperatorSectionUnavailable("Unavailable"),
    ):
        response = client.get(INVENTORY, params={"occupancy": "unknown"})
    assert response.status_code == 503
    assert "matchingTotal" not in response.json()

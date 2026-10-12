"""DASH HTTP delivery, snapshot-bound continuations and production readiness."""

import base64
import json
import threading
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import FastAPI
from sqlalchemy import event, text
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.operator.api.router import build_router
from app.modules.operator.application.home_contracts import (
    HomeResponse,
    AttentionResponse,
    CollectionResponse,
)
from app.modules.operator.domain.models import OperatorSectionUnavailable
from app.modules.operator.tests import test_home_composition as fixtures
from app.modules.operator.tests import test_endpoint_contracts as contract_fixtures
from app.modules.workspace.application.service import WorkspaceService
from app.platform.api_errors import register_api_error_handlers
from app.platform.config import LocalConfig
from app.platform.testing_client import LocalApiClient
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel

HOME = "/api/operator/home"
PERIOD = {"fromOn": "2026-10-01", "throughOn": "2026-10-31"}


@pytest.fixture
def context(tmp_path):
    yield from fixtures.context.__wrapped__(tmp_path)


@pytest.fixture
def api(context):
    app = FastAPI()
    app.state.loop_threads = []

    @app.middleware("http")
    async def observe_loop(request, call_next):
        app.state.loop_threads.append(threading.get_ident())
        return await call_next(request)

    register_api_error_handlers(app)
    app.include_router(build_router(object(), home=context[0]))
    with LocalApiClient(app) as client:
        yield client, context, app


@pytest.fixture
def contract_app(tmp_path):
    yield from contract_fixtures.contract_app.__wrapped__(tmp_path)


def items(client, **parameters):
    return client.get(HOME + "/items", params={"collection": "needs_action", **parameters})


def cursor_payload(cursor):
    return json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))


def encode_cursor(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def test_home_attention_and_all_collection_contracts(api):
    client, context, _ = api
    fixtures.populate(context, 8)
    full = client.get(HOME, params={**PERIOD, "horizonDays": 7})
    live = client.get(HOME + "/attention")
    assert full.status_code == live.status_code == 200
    home = HomeResponse.model_validate(full.json())
    attention = AttentionResponse.model_validate(live.json())
    assert home.needs_action == attention.needs_action
    assert home.needs_action.matching_total == 8 and len(home.needs_action.items) == 5
    assert home.needs_action.next_cursor is not None
    for collection in fixtures.Collection:
        response = client.get(HOME + "/items", params={"collection": collection.value, "limit": 2})
        assert response.status_code == 200, response.text
        result = CollectionResponse.model_validate(response.json())
        assert result.as_of == result.result.capture.as_of
    assert client.get(HOME, params={**PERIOD, "horizonDays": 30}).status_code == 200
    assert client.get(HOME, params={**PERIOD, "horizonDays": 90}).status_code == 200


def test_frozen_preview_to_collection_pagination_has_no_gaps(api):
    client, context, _ = api
    fixtures.populate(context, 8)
    first = client.get(HOME + "/attention", params={"limit": 1}).json()
    seen = [first["needsAction"]["items"][0]["key"]]
    cursor = first["needsAction"]["nextCursor"]
    context[0].now = lambda: fixtures.NOW + timedelta(minutes=3)
    while cursor:
        response = items(client, limit=2, cursor=cursor)
        assert response.status_code == 200, response.text
        page = CollectionResponse.model_validate(response.json())
        assert page.as_of == fixtures.NOW
        assert page.result.matching_total == 8
        seen.extend(item.key for item in page.result.items)
        cursor = page.result.next_cursor
    assert len(seen) == len(set(seen)) == 8


def test_coverage_composite_cursor_pages_the_same_captured_information(api):
    client, _, _ = api
    response = client.get(HOME + "/items", params={"collection": "information_review", "limit": 1})
    first = response.json()
    cursor = first["result"]["nextCursor"]
    assert cursor_payload(cursor)["last"][2] == "coverage"
    assert len(cursor_payload(cursor)["last"][3].split(":")) == 4
    following = client.get(
        HOME + "/items", params={"collection": "information_review", "limit": 1, "cursor": cursor}
    )
    assert following.status_code == 200, following.text
    assert following.json()["asOf"] == first["asOf"]
    assert first["result"]["items"][0]["key"] != following.json()["result"]["items"][0]["key"]
    assert following.json()["result"]["nextCursor"] is None


@pytest.mark.parametrize(
    "path,parameters",
    [
        (HOME, {}),
        (HOME, {**PERIOD, "fromOn": "not-a-date"}),
        (HOME, {**PERIOD, "throughOn": "2026-09-01"}),
        (HOME, {**PERIOD, "propertyId": "bad"}),
        (HOME, {**PERIOD, "horizonDays": 8}),
        (HOME, {**PERIOD, "limitPerSection": 11}),
        (HOME, {**PERIOD, "unknown": "field"}),
        (HOME + "/attention", {"limit": 0}),
        (HOME + "/attention", {"limit": 11}),
        (HOME + "/attention", {"horizonDays": 30}),
        (HOME + "/items", {"collection": "unknown"}),
        (HOME + "/items", {"collection": "waiting", "limit": 101}),
        (HOME + "/items", {"collection": "waiting", "cursor": ""}),
    ],
)
def test_malformed_query_uses_the_shared_422_envelope(api, path, parameters):
    client, _, _ = api
    result = client.get(path, params=parameters)
    assert result.status_code == 422
    assert result.json()["detail"]["code"] == "request_validation"


@pytest.mark.parametrize("cursor", ["!not-base64", "e30", "x" * 4097, "é" * 3000])
def test_malformed_or_oversized_cursors_fail_safely(api, cursor):
    result = items(api[0], cursor=cursor)
    assert result.status_code == (413 if len(cursor.encode()) > 4096 else 422)
    assert set(result.json()["detail"]) == {"code", "message"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("version", 2),
        ("orderingVersion", 2),
        ("last", [True, fixtures.NOW.isoformat(), "task", fixtures.tasks.identity(1)]),
        ("last", [3, fixtures.NOW.isoformat(), "unknown", fixtures.tasks.identity(1)]),
        ("last", [3, fixtures.NOW.isoformat(), "maintenance_issue", "not-uuid"]),
        ("last", [3, "2026-10-12T18:00:00", "maintenance_issue", fixtures.tasks.identity(1)]),
        ("last", [3, fixtures.NOW.isoformat(), "maintenance_issue", 123]),
        ("last", [3, fixtures.NOW.isoformat()]),
        ("sourceRevision", 1),
        ("identity", ["not-uuid", "also-not-uuid"]),
        ("filters", []),
    ],
)
def test_composite_key_and_contract_versions_are_validated(api, field, value):
    client, context, _ = api
    fixtures.populate(context, 3)
    payload = cursor_payload(items(client, limit=1).json()["result"]["nextCursor"])
    payload[field] = value
    assert items(client, cursor=encode_cursor(payload)).status_code == 422


@pytest.mark.parametrize(
    "changed", ["property", "horizon", "collection", "runtime", "source", "expired", "future"]
)
def test_cursor_binding_changes_return_refresh_conflicts(api, changed):
    client, context, _ = api
    service, _, prop = context
    fixtures.populate(context, 3)
    cursor = items(client, limit=1).json()["result"]["nextCursor"]
    parameters = {"cursor": cursor}
    if changed == "property":
        parameters["propertyId"] = prop.id
    elif changed == "horizon":
        parameters["horizonDays"] = 30
    elif changed == "collection":
        parameters["collection"] = "waiting"
    elif changed == "runtime":
        identity = replace(service.runtime(), epoch=fixtures.tasks.identity(4444))
        service.runtime = lambda: identity
    elif changed == "source":
        with service.unit_of_work.engine.begin() as connection:
            AuditRecorder(
                SQLiteAuditRepository(service.unit_of_work.engine.url.database)
            ).record_change(
                connection.connection.driver_connection,
                entity_type="workspace",
                entity_id=service.runtime().workspace_id,
                action="updated",
                before=None,
                after={"changed": True},
            )
    elif changed == "expired":
        service.now = lambda: fixtures.NOW + timedelta(minutes=15)
    else:
        service.now = lambda: fixtures.NOW - timedelta(seconds=1)
    response = items(client, **parameters)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "operator_conflict"


def test_missing_property_and_whole_transaction_failure_are_controlled(api):
    client, context, _ = api
    missing = client.get(HOME + "/attention", params={"propertyId": str(UUID(int=9999))})
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "portfolio_property_not_found"
    with patch.object(
        context[1].tasks,
        "standalone_attention",
        side_effect=DBAPIError("select", {}, Exception("broken")),
    ):
        failure = client.get(HOME + "/attention")
    assert failure.status_code == 503
    assert failure.json()["detail"]["code"] == "operator_storage_failure"
    assert "select" not in failure.text and "broken" not in failure.text


def test_writer_after_cursor_validation_cannot_mix_the_page_snapshot(api):
    client, context, _ = api
    fixtures.populate(context, 3)
    service = context[0]
    cursor = items(client, limit=1).json()["result"]["nextCursor"]
    marker = service.unit_of_work.marker
    original = marker.marker

    def mutate_after_capture(connection):
        previous = original(connection)
        with service.unit_of_work.engine.begin() as writer:
            writer.execute(
                update(TaskModel)
                .where(TaskModel.id == fixtures.tasks.identity(1002))
                .values(status="completed", completed_at_utc=fixtures.NOW.isoformat())
            )
            AuditRecorder(
                SQLiteAuditRepository(service.unit_of_work.engine.url.database)
            ).record_change(
                writer.connection.driver_connection,
                entity_type="workspace",
                entity_id=service.runtime().workspace_id,
                action="updated",
                before=None,
                after={"changed": True},
            )
        return previous

    with patch.object(marker, "marker", side_effect=mutate_after_capture):
        response = items(client, limit=1, cursor=cursor)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["matchingTotal"] == 3
    assert result["items"][0]["children"][0]["sourceStatus"] == "open"
    assert items(client, cursor=result["nextCursor"]).status_code == 409


def test_unavailable_collection_never_substitutes_zero_or_a_cursor(api):
    client, context, _ = api
    service, sources, _ = context
    assert client.get(HOME + "/attention").json()["needsAction"]["matchingTotal"] == 0
    with patch.object(sources.rent, "attention", side_effect=OperatorSectionUnavailable("offline")):
        result = client.get(HOME, params=PERIOD).json()
    assert result["needsAction"]["status"] == "unavailable"
    assert "matchingTotal" not in result["needsAction"]
    assert "nextCursor" not in result["needsAction"]
    assert result["waiting"]["status"] == result["money"]["status"] == "available"
    service.unit_of_work.sources = replace(sources, rent=None)
    assert client.get(HOME + "/attention").json()["needsAction"]["reasonCode"] == "adapter_missing"


def test_missing_independent_money_adapter_is_explicit_and_missing_scope_is_unavailable(api):
    client, context, _ = api
    service, sources, _ = context
    service.unit_of_work.sources = replace(sources, money=None)
    result = client.get(HOME, params=PERIOD)
    assert result.status_code == 200
    assert result.json()["money"]["reasonCode"] == "adapter_missing"
    assert result.json()["needsAction"]["status"] == "available"
    service.unit_of_work.sources = replace(sources, portfolio=None)
    assert client.get(HOME, params=PERIOD).status_code == 503


def test_endpoints_are_worker_reads_and_do_not_write(api):
    client, context, app = api
    engine = context[0].unit_of_work.engine
    sql_threads = []

    def observe_sql(*_args):
        sql_threads.append(threading.get_ident())

    with engine.connect() as connection:
        before = connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one()
    event.listen(engine, "before_cursor_execute", observe_sql)
    try:
        for _ in range(2):
            assert client.get(HOME, params=PERIOD).status_code == 200
            assert client.get(HOME + "/attention").status_code == 200
            assert items(client).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", observe_sql)
    assert app.state.loop_threads
    assert sql_threads and set(sql_threads).isdisjoint(app.state.loop_threads)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == before


def test_openapi_routes_are_deterministic_and_do_not_open_a_workspace(contract_app):
    schema = contract_app.openapi()
    for path, operation, response in (
        (HOME, "getOperatorHome", "HomeResponse"),
        (HOME + "/attention", "getOperatorHomeAttention", "AttentionResponse"),
        (HOME + "/items", "getOperatorHomeItems", "CollectionResponse"),
    ):
        contract = schema["paths"][path]["get"]
        assert contract["operationId"] == operation
        assert contract["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith(response)
        assert {"404", "409", "413", "422", "503"} <= set(contract["responses"])
    result = LocalApiClient(contract_app).get(HOME, params=PERIOD)
    assert result.status_code == 503


def test_production_bootstrap_gates_home_on_the_current_adapter_bundle(tmp_path):
    workspace_path = tmp_path / "workspace"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"localWorkspacePath": str(workspace_path)}), encoding="utf-8")
    WorkspaceService(LocalConfig(config, workspace_path)).initialize()
    app = create_app(config)
    with LocalApiClient(app) as client:
        assert "operator.home" in client.get("/api/operator/bootstrap").json()["capabilities"]
        assert client.get(HOME, params=PERIOD).status_code == 200
        home = app.state.operator_home_service
        home.unit_of_work.sources = replace(home.unit_of_work.sources, rent=None)
        assert "operator.home" not in client.get("/api/operator/bootstrap").json()["capabilities"]
        response = client.get(HOME, params=PERIOD)
        assert response.status_code == 200
        assert response.json()["needsAction"]["reasonCode"] == "adapter_missing"

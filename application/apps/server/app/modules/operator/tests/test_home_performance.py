"""DASH-001 Slice 11: complete HTTP cost, bounded output and worker measurements."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from math import ceil
from time import perf_counter
from threading import Barrier
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.routing import run_in_threadpool
from sqlalchemy import event, select, update

from app.modules.finance.infrastructure.sqlalchemy_models import RentExpectationModel
from app.modules.finance.tests import test_attention_reader as rent
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseTermModel
from app.modules.operator.api.router import build_router
from app.modules.operator.application.home_contracts import HomeResponse
from app.modules.operator.infrastructure.home_unit_of_work import SQLiteHomeReadTransaction
from app.modules.operator.tests import test_home_composition as fixtures
from app.modules.portfolio.infrastructure.sqlalchemy_models import PropertyModel, SpaceModel
from app.modules.tasks.infrastructure.sqlalchemy_models import TaskModel
from app.platform.api_errors import register_api_error_handlers
from app.platform.testing_client import LocalApiClient

SAMPLES = 10
HOME = "/api/operator/home"
PERIOD = {"fromOn": "2026-10-01", "throughOn": "2026-10-31"}


@pytest.fixture
def context(tmp_path):
    yield from fixtures.context.__wrapped__(tmp_path)


def seed_portfolio(context, count):
    """Large read fixture on the real baseline; source write acceptance is tested separately."""
    service, _, prop = context
    engine = service.unit_of_work.engine
    zones = ("America/Los_Angeles", "Asia/Tokyo", "UTC")
    with engine.begin() as connection:
        template = dict(
            connection.execute(select(PropertyModel.__table__).where(PropertyModel.id == prop.id))
            .mappings()
            .one()
        )
        space = dict(
            connection.execute(
                select(SpaceModel.__table__).where(SpaceModel.property_id == prop.id)
            )
            .mappings()
            .one()
        )
        existing = set(connection.execute(select(PropertyModel.id)).scalars())
        connection.execute(RentExpectationModel.__table__.delete())
        connection.execute(LeaseTermModel.__table__.delete())
        connection.execute(LeaseModel.__table__.delete())
        connection.execute(TaskModel.__table__.delete())
        for index in range(count):
            property_id = prop.id if index == 0 else fixtures.tasks.identity(100000 + index)
            if index and property_id not in existing:
                connection.execute(
                    PropertyModel.__table__.insert(),
                    {
                        **template,
                        "id": property_id,
                        "display_name": f"Property {index}",
                        "time_zone": zones[index % len(zones)],
                    },
                )
            space_id = space["id"] if index == 0 else fixtures.tasks.identity(110000 + index)
            if index and property_id not in existing:
                connection.execute(
                    SpaceModel.__table__.insert(),
                    {**space, "id": space_id, "property_id": property_id},
                )
            lease_id, term_id = rent.identity(120000 + index), rent.identity(120100 + index)
            connection.execute(
                LeaseModel.__table__.insert(),
                dict(
                    id=lease_id,
                    space_id=space_id,
                    lease_kind="residential",
                    status="executed",
                    contract_starts_on="2000-01-01",
                    contract_ends_on="2030-01-01",
                    occupancy_starts_on="2000-01-01",
                    executed_on="2000-01-01",
                    created_at=fixtures.NOW.isoformat(),
                    updated_at=fixtures.NOW.isoformat(),
                    lease_revision=1,
                ),
            )
            connection.execute(
                LeaseTermModel.__table__.insert(),
                dict(
                    id=term_id,
                    lease_id=lease_id,
                    effective_on="2000-01-01",
                    base_rent_minor=10000,
                    currency_code="USD",
                    payment_frequency="weekly",
                    payment_due_day=None,
                    agreed_security_deposit_minor=0,
                    created_at=fixtures.NOW.isoformat(),
                ),
            )
        connection.execute(
            TaskModel.__table__.insert(),
            [
                fixtures.tasks.task(
                    200000 + i,
                    related_entity_type="property",
                    related_entity_id=prop.id
                    if i % count == 0
                    else rent.identity(100000 + i % count),
                )
                for i in range(1000)
            ],
        )
        connection.execute(
            RentExpectationModel.__table__.insert(),
            [
                rent.expectation(
                    300000 + i,
                    due=(fixtures.NOW.date() - timedelta(weeks=1000 - i)).isoformat(),
                    period_ends_on=(fixtures.NOW.date() - timedelta(weeks=999 - i)).isoformat(),
                    lease_id=rent.identity(120000 + i % count),
                    lease_term_id=rent.identity(120100 + i % count),
                    payment_frequency="weekly",
                )
                for i in range(1000)
            ],
        )


def percentile(samples):
    return round(sorted(samples)[ceil(len(samples) * 0.95) - 1] * 1000, 3)


def test_complete_http_budgets_and_latency_at_one_ten_fifty_properties(context, record_property):
    service = context[0]
    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_router(object(), home=service))
    counts, observations, candidates = [], [], []
    original_read, original_attention = (
        service.unit_of_work.read,
        SQLiteHomeReadTransaction.attention,
    )

    def sql(_connection, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            counts.append(statement)

    def read(operation):
        start = perf_counter()
        try:
            return original_read(operation)
        finally:
            observations[-1]["snapshot"].append(perf_counter() - start)

    def bounded(tx, source, window):
        page = original_attention(tx, source, window)
        assert len(page.candidates) <= window.limit + 1
        assert all(len(item.children) <= 3 for item in page.candidates)
        candidates.append(len(page.candidates))
        return page

    async def dispatch(function, /, *args, **kwargs):
        endpoint = kwargs.get("function", function)
        if endpoint.__name__ not in ("home", "attention", "items"):
            return await run_in_threadpool(function, *args, **kwargs)
        queued = perf_counter()

        def work():
            observations[-1]["worker_wait"].append(perf_counter() - queued)
            return function(*args, **kwargs)

        return await run_in_threadpool(work)

    budgets = []
    with LocalApiClient(app) as client:
        for property_count in (1, 10, 50):
            # Each size gets its own retained read fixture on the same baseline.
            seed_portfolio(context, property_count)
            measurements, size_budgets = {}, []
            event.listen(service.unit_of_work.engine, "before_cursor_execute", sql)
            try:
                with (
                    patch.object(service.unit_of_work, "read", side_effect=read),
                    patch.object(SQLiteHomeReadTransaction, "attention", bounded),
                    patch("fastapi.routing.run_in_threadpool", side_effect=dispatch),
                ):
                    for name, path, parameters, ceiling in (
                        ("initial", HOME, PERIOD, 64),
                        ("attention", HOME + "/attention", {}, 24),
                        ("page", HOME + "/items", {"collection": "needs_action", "limit": 100}, 24),
                    ):
                        observed = {"http": [], "worker_wait": [], "snapshot": []}
                        observations.append(observed)
                        for _ in range(SAMPLES):
                            counts.clear()
                            candidates.clear()
                            start = perf_counter()
                            response = client.get(path, params=parameters)
                            observed["http"].append(perf_counter() - start)
                            assert response.status_code == 200, response.text
                            payload = response.json()
                            section = payload["result" if name == "page" else "needsAction"]
                            assert section["status"] == "available"
                            assert section["matchingTotal"] == 2000
                            assert len(section["items"]) <= (100 if name == "page" else 5)
                            assert candidates and len(counts) <= ceiling
                            if name == "initial":
                                assert payload["money"]["status"] == "available"
                                home = HomeResponse.model_validate(payload)
                                for collection in fixtures.Collection:
                                    result = getattr(home, collection.value)
                                    assert result.status == "available"
                                    assert len(result.items) <= 5
                        size_budgets.append(len(counts))
                        measurements[name] = {
                            "selects": len(counts),
                            "cold_http_ms": round(observed["http"][0] * 1000, 3),
                            **{
                                key + "_p95_ms": percentile(values)
                                for key, values in observed.items()
                            },
                        }
                        if name == "page":
                            counts.clear()
                            following = client.get(
                                path, params={**parameters, "cursor": section["nextCursor"]}
                            )
                            assert following.status_code == 200, following.text
                            result = following.json()["result"]
                            assert result["matchingTotal"] == 2000
                            assert len(result["items"]) <= 100 and len(counts) <= 24
                            assert {item["key"] for item in section["items"]}.isdisjoint(
                                item["key"] for item in result["items"]
                            )
                            measurements[name]["continuation_selects"] = len(counts)
                    collection_counts = {}
                    for collection in fixtures.Collection:
                        counts.clear()
                        response = client.get(
                            HOME + "/items", params={"collection": collection.value, "limit": 100}
                        )
                        assert response.status_code == 200, response.text
                        result = response.json()["result"]
                        assert result["status"] == "available"
                        assert len(result["items"]) <= 100 and len(counts) <= 24
                        collection_counts[collection.value] = len(counts)
                    measurements["collection_selects"] = collection_counts
            finally:
                event.remove(service.unit_of_work.engine, "before_cursor_execute", sql)
            assert size_budgets[0] + size_budgets[1] <= 88
            budgets.append(size_budgets)
            record_property(
                f"home_performance_{property_count}_properties", json.dumps(measurements)
            )
    assert budgets[0] == budgets[1] == budgets[2]


def test_property_local_midnight_reclassifies_http_counts_and_rows_together(context):
    seed_portfolio(context, 2)
    service = context[0]
    with service.unit_of_work.engine.begin() as connection:
        connection.execute(TaskModel.__table__.delete())
        connection.execute(
            RentExpectationModel.__table__.delete().where(
                RentExpectationModel.id.not_in((rent.identity(300000), rent.identity(300001)))
            )
        )
        connection.execute(
            update(RentExpectationModel).values(
                period_starts_on="2026-10-12",
                period_ends_on="2026-10-19",
                due_on="2026-10-12",
                schedule_anchor_on="2026-10-12",
            )
        )
    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_router(object(), home=service))
    service.now = lambda: fixtures.NOW.replace(hour=3)
    with LocalApiClient(app) as client:
        before = client.get(HOME, params=PERIOD).json()
        assert before["needsAction"]["matchingTotal"] == 1
        assert before["upcoming"]["matchingTotal"] == 1
        assert before["needsAction"]["items"][0]["propertyName"] == "Property 1"
        assert before["nextTransitionAt"] == "2026-10-12T07:00:00Z"
        service.now = lambda: fixtures.NOW.replace(hour=7)
        after = client.get(HOME, params=PERIOD).json()
        assert after["needsAction"]["matchingTotal"] == 2
        assert after["upcoming"]["matchingTotal"] == 0
        assert all(
            any(reason["code"] == "due_today" for reason in item["reasons"])
            for item in after["needsAction"]["items"]
        )


def test_parallel_initial_and_live_requests_respect_the_combined_budget(context, record_property):
    seed_portfolio(context, 50)
    service = context[0]
    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_router(object(), home=service))
    marker, barrier, statements = service.unit_of_work.marker.marker, Barrier(2), []

    def capture(connection):
        result = marker(connection)
        barrier.wait(timeout=10)
        return result

    def sql(_connection, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            statements.append(statement)

    event.listen(service.unit_of_work.engine, "before_cursor_execute", sql)
    try:
        with (
            LocalApiClient(app) as client,
            patch.object(service.unit_of_work.marker, "marker", side_effect=capture),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            start = perf_counter()
            home = pool.submit(client.get, HOME, params=PERIOD)
            attention = pool.submit(client.get, HOME + "/attention")
            initial, live = home.result(timeout=20), attention.result(timeout=20)
            elapsed = perf_counter() - start
        assert initial.status_code == live.status_code == 200
        assert initial.json()["needsAction"] == live.json()["needsAction"]
        assert len(statements) <= 88
        record_property("parallel_initial_attention_selects", len(statements))
        record_property("parallel_initial_attention_ms", round(elapsed * 1000, 3))
    finally:
        event.remove(service.unit_of_work.engine, "before_cursor_execute", sql)

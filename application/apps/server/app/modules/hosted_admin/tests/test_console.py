"""Read-only console boundaries, bounded queries and independently stale observations."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from app.modules.hosted_admin.api.application import create_admin_app
from app.modules.hosted_admin.application.contracts import BrokerRequest, AdminError
from app.modules.hosted_admin.infrastructure.console import ConsoleReads
from app.modules.hosted_admin.infrastructure.project_quota import QuotaUnavailable
from app.modules.hosted_admin.tests.test_authority import (
    authority as authority,
    login,
    command,
    request,
)
from scripts.admin_browser_server import FixtureInventory

ORIGIN = "http://epm-admin.localhost:8765"


@pytest.fixture
def console(authority):
    store, clock = authority
    inventory = FixtureInventory(clock)
    reads = ConsoleReads(store, inventory)
    reads.executor.shutdown()
    jobs = []
    reads.executor = SimpleNamespace(
        submit=lambda task, key: jobs.append((task, key)), shutdown=lambda **_: None
    )
    return reads, inventory, jobs


def drain(jobs):
    while jobs:
        task, key = jobs.pop(0)
        task(key)


def test_failed_quota_preflight_reuses_the_independent_unavailable_section(console):
    reads, inventory, jobs = console
    observe = inventory.observe

    def preflight(section, instance):
        if section == "runtime":
            raise QuotaUnavailable("admin_project_enforcement_unavailable")
        return observe(section, instance)

    inventory.observe = preflight
    reads.observation("runtime", "a")
    reads.observation("access", "a")
    drain(jobs)
    unavailable = reads.observation("runtime", "a")
    assert unavailable["failed"] and unavailable["data"] is None
    assert reads.observation("access", "a")["state"] == "available"
    assert "enforcement" not in json.dumps(unavailable)  # No private exception content.


@pytest.mark.parametrize("count", [1, 100, 200])
def test_directory_query_budget_is_constant(console, authority, count, monkeypatch):
    reads, inventory, _ = console
    store, _ = authority
    item = inventory.records()[0]
    inventory.records = lambda: [item.model_copy(update={"key": f"x{i:03}"}) for i in range(count)]
    credentials, statements = login(store), []
    original = store.transaction

    @contextmanager
    def counted():
        with original() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(store, "transaction", counted)
    result = store.handle(BrokerRequest(method="console_directory", **credentials), None, reads)
    assert result["total"] == count
    assert len(statements) <= 5


def test_directory_is_bounded_and_never_runs_per_row_observers(console, authority):
    reads, inventory, jobs = console
    store, _ = authority
    original = inventory.records()
    inventory.records = lambda: [
        original[0].model_copy(update={"key": f"x{i:03}"}) for i in range(200)
    ]
    inventory.observe = lambda *_: pytest.fail("Directory cannot fan out")
    credentials = login(store)
    for offset in (0, 50, 100, 150):
        result = store.handle(
            BrokerRequest(method="console_directory", offset=offset, **credentials), None, reads
        )
        assert len(result["items"]) == 50 and result["total"] == 200
        assert result["items"][0]["key"] == f"x{offset:03}"
        assert result["next"] == (offset + 50 if offset < 150 else None)
        assert result["items"][0]["access"]["state"] == "unknown"
    assert jobs == []


def test_observations_are_async_bounded_independent_and_retain_stale_data(console, authority):
    reads, inventory, jobs = console
    _, clock = authority
    first = reads.observation("access", "a")
    assert first["state"] == "unknown" and first["refreshing"]
    reads.observation("access", "a")
    reads.observation("recovery", "a")
    assert len(jobs) == 2
    drain(jobs)
    good = reads.observation("access", "a")
    assert good["state"] == "available" and good["data"]["active"]
    assert reads.observation("recovery", "a")["state"] == "unknown"
    inventory.failed = True
    clock[0] += 31
    reads.observation("access", "a")
    drain(jobs)
    stale = reads.observation("access", "a")
    assert stale["state"] == "stale"
    assert stale["data"] == good["data"] and stale["observed"] == good["observed"]
    assert "private provider" not in json.dumps(stale)


def test_unexpected_fields_and_stale_signed_capacity_fail_closed(console, authority):
    reads, inventory, jobs = console
    _, clock = authority
    snapshot = inventory.observe("capacity", None)
    inventory.observe = lambda *_: snapshot.model_copy(update={"observed": clock[0] - 61})
    reads.observation("capacity", None)
    drain(jobs)
    assert reads.observation("capacity", None)["state"] == "unknown"
    inventory.observe = lambda *_: {"active": True, "private_path": "/secret"}
    reads.observation("access", "a")
    drain(jobs)
    assert reads.observation("access", "a")["data"] is None


def test_observation_queue_has_a_hard_bound(console):
    reads, _, jobs = console
    for i in range(100):
        reads.observation("access", f"x{i}")
    assert len(jobs) == 8
    drain(jobs)


def test_console_requires_admin_session_csrf_and_registered_selectors(console, authority):
    reads, _, jobs = console
    store, _ = authority
    with pytest.raises(AdminError, match="session_expired"):
        store.handle(BrokerRequest(method="console_directory"), None, reads)
    credentials = login(store)
    with pytest.raises(AdminError, match="csrf_invalid"):
        store.handle(
            BrokerRequest(method="console_directory", token=credentials["token"]), None, reads
        )
    with pytest.raises(AdminError, match="not_found"):
        store.handle(
            BrokerRequest(method="console_record", instance="unregistered", **credentials),
            None,
            reads,
        )
    assert jobs == []


def test_operation_projection_is_safe_and_cannot_change_access(console, authority):
    reads, _, _ = console
    store, _ = authority
    credentials = login(store)
    cmd = command(reason="Private maintenance review")
    admission = store.admit(request(credentials, cmd))
    result = store.handle(
        BrokerRequest(method="console_operation", operation_id=admission["id"], **credentials),
        None,
        reads,
    )
    assert result["state"] == "queued" and result["reason"] == cmd.reason
    assert result["events"][0]["action"] == "admitted"
    assert "source_reference" not in json.dumps(result) and "request_hash" not in result
    assert result["actor"]
    with store.transaction() as connection:
        assert connection.execute("SELECT state FROM operation").fetchone()[0] == "queued"


def test_http_console_keeps_safe_return_route_and_assets_private(console, authority, tmp_path):
    reads, _, _ = console
    store, _ = authority
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "admin.js").write_text("// private UI")

    def call(payload):
        return store.handle(BrokerRequest.model_validate(payload), None, reads)

    with TestClient(create_admin_app(ORIGIN, call, assets), base_url=ORIGIN) as client:
        assert client.get("/admin-assets/admin.js").status_code == 401
        form = client.get("/operators/b")
        assert 'name="return_to" value="/operators/b"' in form.text
        response = client.post(
            "/sign-in",
            data={"credential": store.issue(), "return_to": "/operators/b"},
            headers={"Origin": ORIGIN},
        )
        assert response.url.path == "/operators/b" and "admin-root" in response.text
        assert client.get("/admin-assets/admin.js").text == "// private UI"
        assert client.get("/admin-api/operators/page/0").json()["total"] == 2
        assert client.get("/admin-api/operators/b").json()["items"][0]["key"] == "b"
        assert client.get("/admin-api/operators/page/1").status_code == 422
        assert client.get("/admin-api/observations/arbitrary").status_code == 422
        assert client.get("/admin-assets/authority.sqlite").status_code == 404
        assert client.get("/operators?token=secret").status_code == 403
        assert "'unsafe-inline'" not in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "no-store"
        assert (
            client.post(
                "/sign-in",
                data={"credential": store.issue(), "return_to": "https://evil.example"},
                headers={"Origin": ORIGIN},
            ).status_code
            == 400
        )

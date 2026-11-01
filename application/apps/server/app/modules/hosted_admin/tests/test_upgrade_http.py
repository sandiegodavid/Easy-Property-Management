"""Real private sessions/CSRF and durable upgrade admission, with bounded fake host effects."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.modules.hosted_admin.tests.test_upgrades import (
    upgrade as upgrade,
    request,
    await_acceptance,
)
from app.modules.hosted_admin.api.application import create_admin_app, COOKIE, CSRF_COOKIE
from app.modules.hosted_admin.application.contracts import BrokerRequest
from app.modules.hosted_admin.application.upgrades import InstalledRelease
from app.modules.hosted_admin.infrastructure.private_operations import PrivateOperations


def test_http_admission_is_async_action_bound_and_lost_response_lookup_is_read_only(upgrade):
    service, host, identity, _clock = upgrade
    host.options = lambda _: [
        InstalledRelease.model_validate(host.prepare("a", "release-20261101-01")["target"])
    ]
    dispatch = SimpleNamespace(upgrades=service)

    def call(raw):
        return service.store.handle(BrokerRequest.model_validate(raw), dispatch)

    app = create_admin_app("http://epm-admin.localhost:8765", call)
    credentials = service.store.login(service.store.issue())
    private = PrivateOperations(service.store, None, dispatch)
    with TestClient(app, base_url="http://epm-admin.localhost:8765") as client:
        client.cookies.set(COOKIE, credentials["token"])
        client.cookies.set(CSRF_COOKIE, credentials["csrf"])
        client.headers.update(
            {"Origin": "http://epm-admin.localhost:8765", "X-Epm-Admin-Csrf": credentials["csrf"]}
        )
        assert client.get("/admin-api/operators/a/upgrade-options").json()["items"][0]["eligible"]
        check = request()
        admitted = client.post("/upgrade-command", json={"upgrade": check.model_dump()})
        assert admitted.status_code == 202 and not host.applied
        service.tick()
        status = service.engine.get(check.id)
        start = request(
            "start",
            operation=check.id,
            expected_revision=status["revision"],
            session_handling="preserve",
        )
        rejected = client.post("/upgrade-command", json={"upgrade": start.model_dump()})
        assert rejected.status_code == 401
        credential = private.handle({"action": "upgrade-grant", "upgrade": start.model_dump()})[
            "credential"
        ]
        admitted = client.post(
            "/upgrade-command", json={"upgrade": start.model_dump(), "credential": credential}
        )
        assert admitted.status_code == 202
        assert client.get(f"/admin-api/upgrade-commands/{start.id}").json()["found"]
        assert not host.applied  # Neither admission nor status performs host work.
        status = await_acceptance(service, start)
        accept = request(
            "accept", operation=start.id, expected_revision=status["revision"], restore_access=False
        )
        credential = private.handle({"action": "upgrade-grant", "upgrade": accept.model_dump()})[
            "credential"
        ]
        assert (
            client.post(
                "/upgrade-command", json={"upgrade": accept.model_dump(), "credential": credential}
            ).status_code
            == 202
        )
        service.tick()
        # An acceptance key resolves to its original upgrade after browser reload.
        assert (
            client.get(f"/admin-api/upgrades/{accept.id}").json()["operation"]["state"]
            == "succeeded"
        )
        assert (
            client.post("/upgrade-command", json={"upgrade": accept.model_dump()}).status_code
            == 202
        )
        assert host.applied.count("accept") == 1

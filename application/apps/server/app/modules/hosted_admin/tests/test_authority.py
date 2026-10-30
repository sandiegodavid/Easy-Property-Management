"""Private authority, transport, and source audit/receipt boundary proof."""

import socket
import sqlite3
import threading
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.modules.hosted_admin.api.application import COOKIE, create_admin_app
from app.modules.hosted_admin.application.contracts import AdminError, BrokerRequest, CommandRequest
from app.modules.hosted_admin.infrastructure.authority import (
    ABSOLUTE_SECONDS,
    AuthorityStore,
    GRANT_SECONDS,
    IDLE_SECONDS,
    digest,
)
from app.modules.hosted_admin.infrastructure.broker import Broker, MAX_FRAME, receive, send


@pytest.fixture
def authority(tmp_path):
    store = AuthorityStore.initialize(tmp_path / "private" / "authority.sqlite", "deployment-owner")
    clock = [1000.0]
    store.clock = lambda: clock[0]
    return store, clock


def command(**changes):
    return CommandRequest.model_validate(
        {
            "operation_id": str(uuid4()),
            "instance": "c",
            "action": "disable",
            "expected_revision": 0,
            "expected_binding_revision": 0,
            "fence": 0,
            "reason": "Contain access",
            "confirmed": True,
        }
        | changes
    )


def login(store):
    return store.login(store.issue())


def request(credentials, cmd, **changes):
    return BrokerRequest(method="command", command=cmd, **credentials).model_copy(update=changes)


def test_single_use_hash_only_bootstrap_and_expiry(authority):
    store, clock = authority
    grant = store.issue()
    with store.transaction() as connection:
        assert connection.execute("SELECT hash FROM grant").fetchone()[0] == digest(grant)
    credentials = store.login(grant)
    assert grant not in store.path.read_bytes().decode(errors="replace")
    with pytest.raises(AdminError, match="grant_invalid"):
        store.login(grant)
    expired = store.issue()
    clock[0] += GRANT_SECONDS
    with pytest.raises(AdminError, match="grant_invalid"):
        store.login(expired)
    with store.transaction() as connection:
        assert connection.execute("SELECT hash FROM session").fetchone()[0] == digest(
            credentials["token"]
        )


@pytest.mark.parametrize("duration", [IDLE_SECONDS, ABSOLUTE_SECONDS])
def test_session_expiry_does_not_revoke_admitted_work(authority, duration):
    store, clock = authority
    credentials = login(store)
    admission = store.admit(request(credentials, command()))
    clock[0] += duration
    with pytest.raises(AdminError, match="session_expired"):
        with store.transaction() as connection:
            store.session(connection, credentials["token"])
    assert store.execute(admission, lambda _: {"done": True}) == {"done": True}
    assert store.handle(
        BrokerRequest(method="lookup", operation_id=admission["id"], **login(store)), None
    )["found"]


def test_logout_keeps_committed_work_but_revocation_fences_it(authority):
    store, _ = authority
    credentials = login(store)
    admission = store.admit(request(credentials, command()))
    store.handle(BrokerRequest(method="logout", **credentials), None)
    assert store.execute(admission, lambda _: {"done": True})["done"]
    pending = store.admit(request(login(store), command()))
    store.revoke_identity()
    with pytest.raises(AdminError, match="revoked|fenced"):
        store.execute(pending, lambda _: pytest.fail("Must not dispatch revoked work"))
    with pytest.raises(AdminError, match="revoked"):
        store.login(store.issue())


def test_action_grant_exact_session_action_revision_and_atomic_admission(authority):
    store, _ = authority
    credentials, other = login(store), login(store)
    cmd = command(action="approve", subject="verified", enrollment_received_at=1000.0)
    original = request(credentials, cmd)
    with pytest.raises(AdminError, match="reauthentication_required"):
        store.admit(original)
    grant = store.issue(cmd.fingerprint())
    with pytest.raises(AdminError, match="grant_invalid"):
        store.reauthenticate(
            request(
                credentials,
                cmd.model_copy(update={"expected_revision": 1}),
                method="reauthenticate",
                credential=grant,
            )
        )
    store.reauthenticate(request(credentials, cmd, method="reauthenticate", credential=grant))
    with pytest.raises(AdminError, match="reauthentication_required"):
        store.admit(request(other, cmd))
    admission = store.admit(original)
    assert store.admit(original) == admission  # lost response, no second grant
    with pytest.raises(AdminError, match="command_conflict"):
        store.admit(request(credentials, cmd.model_copy(update={"reason": "Changed intent"})))
    with store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM authorization").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM admission").fetchone()[0] == 1


def test_csrf_rate_limit_and_request_vocabulary(authority):
    store, _ = authority
    credentials = login(store)
    with pytest.raises(AdminError, match="csrf_invalid"):
        store.admit(request(credentials, command(), csrf="wrong"))
    for _ in range(9):
        with pytest.raises(AdminError, match="grant_invalid"):
            store.login("wrong")
    with pytest.raises(AdminError, match="attempt_limit"):
        store.login("wrong")
    with pytest.raises(ValueError):
        CommandRequest.model_validate(command().model_dump() | {"path": "/etc/passwd"})


def test_source_committed_control_commit_lost_reconciles_same_receipt(authority):
    store, clock = authority
    original = request(login(store), command())
    admission = store.admit(original)
    results = {}
    calls = []

    def source(payload):
        calls.append(payload["operation_id"])
        results.setdefault(payload["operation_id"], {"generation": 1})
        return results[payload["operation_id"]]

    with store.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER fail_result BEFORE UPDATE ON admission BEGIN SELECT RAISE(ABORT,'lost'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="lost"):
        store.execute(admission, source)
    with store.transaction() as connection:
        connection.execute("DROP TRIGGER fail_result")
    # A crashed worker claim must expire; then reconciliation checks the owning
    # receipt instead of admitting a different command.
    clock[0] += 61
    assert store.execute(store.admit(original), source) == {"generation": 1}
    assert len(results) == 1 and len(calls) == 2


def test_exact_authority_schema_rejects_tampered_store(authority):
    store, _ = authority
    with store.transaction() as connection:
        connection.execute("DROP TRIGGER audit_no_update")
    with pytest.raises(AdminError, match="schema_invalid"):
        AuthorityStore(store.path)


def test_peer_denial_happens_before_receiving_credentials(authority):
    store, _ = authority
    left, right = socket.socketpair()
    try:
        Broker(store, 12345, lambda _: pytest.fail(), peer=lambda _: 88888).handle(left)
        assert receive(right) == {"error": "admin_peer_denied", "status": 403}
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize(
    "peer,method,accepted",
    [(12345, "bootstrap", False), (0, "bootstrap", True), (12345, "revoke_identity", False)],
)
def test_root_only_launcher_grants(authority, peer, method, accepted):
    store, _ = authority
    left, right = socket.socketpair()
    worker = threading.Thread(
        target=Broker(store, 12345, None, peer=lambda _: peer).handle, args=(left,)
    )
    worker.start()
    try:
        send(right, {"method": method})
        response = receive(right)
        assert ("result" in response) == accepted
    finally:
        worker.join(timeout=5)
        left.close()
        right.close()


@pytest.fixture
def client(authority):
    store, _ = authority
    app = create_admin_app(
        "http://epm-admin.localhost:8765",
        lambda value: store.handle(BrokerRequest.model_validate(value), lambda _: {"done": True}),
    )
    return TestClient(app, base_url="http://epm-admin.localhost:8765"), store


def test_http_cookie_origin_csrf_and_no_secret_response(client):
    browser, store = client
    origin = {"Origin": "http://epm-admin.localhost:8765"}
    response = browser.post("/login", json={"credential": store.issue()}, headers=origin)
    assert response.status_code == 200 and "token" not in response.json()
    assert (
        "HttpOnly" in response.headers["set-cookie"]
        and "SameSite=strict" in response.headers["set-cookie"]
    )
    assert "Domain=" not in response.headers["set-cookie"]
    assert browser.cookies.get(COOKIE)
    cmd = command().model_dump()
    assert browser.post("/commands", json={"command": cmd}, headers=origin).status_code == 403
    headers = origin | {"X-Epm-Admin-Csrf": response.json()["csrf"]}
    assert browser.post("/commands", json={"command": cmd}, headers=headers).status_code == 200
    assert browser.post("/logout", json={}, headers=headers).status_code == 200
    assert browser.get("/session").status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://evil.example"},
        {"Origin": "http://epm-admin.localhost:8765", "Sec-Fetch-Site": "cross-site"},
        {"Origin": "http://epm-admin.localhost:8765", "X-Forwarded-Host": "trusted"},
        {"Origin": "http://epm-admin.localhost:8765", "Host": "localhost:8765"},
    ],
)
def test_http_denies_operator_or_other_origin_before_broker(client, headers):
    browser, _ = client
    assert (
        browser.post("/login", json={"credential": "not-a-grant"}, headers=headers).status_code
        == 403
    )


def test_request_bound_and_unknown_routes(client):
    browser, _ = client
    headers = {"Origin": "http://epm-admin.localhost:8765", "Content-Type": "application/json"}
    assert (
        browser.post("/login", content=b"x" * (MAX_FRAME + 1), headers=headers).status_code == 413
    )
    assert browser.post("/exec", json={}, headers=headers).status_code == 400
    assert browser.get("/docs").status_code == 405
    assert (
        browser.options("/commands", headers={"Origin": "https://operator.example"}).status_code
        == 403
    )
    response = browser.get("/session")
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "access-control-allow-origin" not in response.headers


def test_native_sign_in_preserves_session_on_reload_and_signs_out(client):
    browser, store = client
    origin = {"Origin": "http://epm-admin.localhost:8765"}
    assert 'for="credential"' in browser.get("/").text
    grant = store.issue()
    response = browser.post("/sign-in", data={"credential": grant}, headers=origin)
    assert response.status_code == 200 and "Signed in as deployment-owner" in response.text
    assert grant not in response.text
    assert "Signed in as deployment-owner" in browser.get("/").text
    from app.modules.hosted_admin.api.sign_in import CSRF_COOKIE

    csrf = browser.cookies.get(CSRF_COOKIE)
    response = browser.post("/sign-out", data={"csrf": csrf}, headers=origin)
    assert response.status_code == 200 and "One-use sign-in credential" in response.text
    assert browser.get("/session").status_code == 401


def test_private_authority_restoration_cannot_revive_old_work(authority):
    store, _ = authority
    old = login(store)
    pending = store.admit(request(old, command()))
    store.revoke_identity()
    store.restore_identity()
    assert login(store)["token"] != old["token"]
    with pytest.raises(AdminError, match="fenced"):
        store.execute(pending, lambda _: pytest.fail())
    with pytest.raises(AdminError, match="expired"):
        with store.transaction() as connection:
            store.session(connection, old["token"])


@pytest.mark.parametrize("method", ["restore_identity", "revoke_identity"])
def test_root_authority_control_rpc_cannot_be_borrowed_by_http(authority, method):
    store, _ = authority
    for peer, expected in ((12345, False), (0, True)):
        left, right = socket.socketpair()
        worker = threading.Thread(
            target=Broker(store, 12345, None, peer=lambda _: peer).handle, args=(left,)
        )
        worker.start()
        try:
            send(right, {"method": method})
            assert ("result" in receive(right)) == expected
        finally:
            worker.join(timeout=5)
            left.close()
            right.close()


def test_real_kernel_peer_credentials_deny_an_unregistered_uid(authority):
    from app.modules.hosted_admin.infrastructure.broker import peer_uid

    store, _ = authority
    left, right = socket.socketpair()
    try:
        import os

        if not hasattr(socket, "SO_PEERCRED"):
            with pytest.raises(AdminError, match="platform_unqualified"):
                peer_uid(left)
            return
        assert peer_uid(left) == os.getuid()
        if os.getuid() == 0:
            pytest.skip("Root is the private administrator, not an operator peer")
        Broker(store, os.getuid() + 1, lambda _: pytest.fail()).handle(left)
        assert receive(right)["error"] == "admin_peer_denied"
    finally:
        left.close()
        right.close()


def test_source_status_requires_session_csrf_and_fixed_instance(authority):
    from unittest.mock import Mock

    store, _ = authority
    credentials = login(store)
    dispatch = Mock()
    dispatch.status.return_value = {"admin_revision": 1}
    status = BrokerRequest(method="source_status", instance="c", **credentials)
    assert store.handle(status, dispatch) == {"admin_revision": 1}
    dispatch.status.assert_called_once_with("c")
    with pytest.raises(AdminError):
        store.handle(status.model_copy(update={"csrf": "wrong"}), dispatch)
    with pytest.raises(ValueError):
        BrokerRequest(method="source_status", instance="../../a", **credentials)


def test_admitted_intent_and_result_are_immutable(authority):
    store, _ = authority
    original = request(login(store), command())
    admission = store.admit(original)
    with pytest.raises(sqlite3.IntegrityError, match="immutable intent"):
        with store.transaction() as connection:
            connection.execute("UPDATE admission SET payload='{}'")
    store.execute(admission, lambda _: {"done": True})
    with pytest.raises(sqlite3.IntegrityError, match="immutable result"):
        with store.transaction() as connection:
            connection.execute("UPDATE admission SET result='{}'")


def test_failed_admission_rolls_back_action_authorization_consumption(authority):
    store, _ = authority
    credentials = login(store)
    cmd = command(action="approve", subject="verified", enrollment_received_at=1000.0)
    store.reauthenticate(
        request(
            credentials, cmd, method="reauthenticate", credential=store.issue(cmd.fingerprint())
        )
    )
    with store.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER fail_admission_audit BEFORE INSERT ON audit WHEN NEW.action='command_admitted' BEGIN SELECT RAISE(ABORT,'audit unavailable'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="audit unavailable"):
        store.admit(request(credentials, cmd))
    with store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM authorization").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM admission").fetchone()[0] == 0
        connection.execute("DROP TRIGGER fail_admission_audit")
    assert store.admit(request(credentials, cmd))["id"] == cmd.operation_id


def test_operator_cookie_and_browser_private_methods_never_become_authority(client):
    browser, _ = client
    browser.cookies.set("epm_hosted_session", "operator-cookie")
    assert browser.get("/session").status_code == 401
    headers = {"Origin": "http://epm-admin.localhost:8765"}
    assert browser.post("/bootstrap", headers=headers, json={}).status_code == 400
    assert browser.post("/restore-identity", headers=headers, json={}).status_code == 400
    assert (
        browser.post(
            "/commands", headers=headers, json={"command": command().model_dump()}
        ).status_code
        == 401
    )


def test_schema_and_permissions_are_fail_closed_before_authority_is_used(authority, tmp_path):
    store, _ = authority
    store.path.chmod(0o644)
    with pytest.raises(AdminError, match="unsafe"):
        AuthorityStore(store.path)
    store.path.chmod(0o600)
    link = tmp_path / "link.sqlite"
    link.symlink_to(store.path)
    with pytest.raises(AdminError, match="unsafe"):
        AuthorityStore(link)


def test_native_rate_limit_and_broker_outage_are_visible_without_private_details(client):
    browser, _ = client
    headers = {"Origin": "http://epm-admin.localhost:8765"}
    for _ in range(10):
        assert (
            browser.post("/sign-in", data={"credential": "invalid"}, headers=headers).status_code
            == 401
        )
    limited = browser.post("/sign-in", data={"credential": "invalid"}, headers=headers)
    assert limited.status_code == 429 and "Try again in five minutes" in limited.text

    def unavailable(_payload):
        raise OSError("private socket path must not be returned")

    offline = TestClient(
        create_admin_app("http://epm-admin.localhost:8765", unavailable),
        base_url="http://epm-admin.localhost:8765",
    )
    response = offline.post("/sign-in", data={"credential": "not-logged"}, headers=headers)
    assert response.status_code == 503 and "Private administration is unavailable" in response.text
    assert "private socket path" not in response.text and "not-logged" not in response.text


def test_root_assisted_command_admission_requires_exact_grant_and_preserves_retry(authority):
    store, _ = authority
    cmd = command()
    with pytest.raises(AdminError, match="grant_invalid"):
        store.private_admit(cmd, "not-a-grant", lambda _key: {})
    original = store.private_admit(cmd, store.issue(cmd.fingerprint()), lambda _key: {})
    assert store.private_admit(cmd, "consumed", lambda _key: {}) == original
    with pytest.raises(AdminError, match="command_conflict"):
        store.private_admit(cmd.model_copy(update={"reason": "changed"}), "", lambda _key: {})

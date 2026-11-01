"""Batch journal and serial child ownership over the real upgrade engine."""

from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.upgrade_batches import BatchCommand
from app.modules.hosted_admin.infrastructure.authority import AuthorityStore
from app.modules.hosted_admin.infrastructure.control_recovery import (
    snapshot_control,
    restore_control,
)
from app.modules.hosted_admin.infrastructure.upgrade_batches import (
    UpgradeBatchService,
    child_identity,
)
from app.modules.hosted_admin.tests.test_upgrades import upgrade as upgrade, request, submit


@pytest.fixture
def batches(upgrade):
    service, host, identity, now = upgrade
    original = host.prepare

    def prepare(instance, release):
        plan = original(instance, release)
        plan["instance"]["key"] = instance
        return plan

    host.prepare = prepare
    host.contain_for_skip = Mock(return_value=True)
    return UpgradeBatchService(service), host, identity, now


def create(batches, count=2, prefix="operator"):
    service, _host, identity, _now = batches
    command = BatchCommand(
        id=str(uuid4()),
        action="check",
        members=[{"instance": f"{prefix}-{i}", "expected_revision": 1} for i in range(count)],
        release="release-20261101-01",
        reason="Reviewed selection",
    )
    service.command(command, identity)
    for _ in range(count + 1):
        service.tick()
    return command, service.view(command.id, identity, limit=50)


def decide(batches, view, action, **changes):
    service, _host, identity, now = batches
    values = dict(
        id=str(uuid4()),
        action=action,
        batch=view["id"],
        expected_revision=view["revision"],
        reason="Reviewed batch",
        confirmed=True,
    )
    if action in {"start", "resume"}:
        values.update(
            window_start=now[0] - 1.0,
            window_end=now[0] + 3600.0,
            sessions=[
                {"instance": row["instance"], "handling": "preserve"} for row in view["items"]
            ],
        )
    command = BatchCommand(**(values | changes))
    result = service.command(command, identity, service.store.issue(command.fingerprint()))
    return command, result


def accept(batches, child):
    batches_service, _host, identity, _now = batches
    service = batches_service.upgrades
    for _ in range(10):
        service.tick()
    operation = service.engine.get(child)
    assert operation["state"] == "waiting"
    submit(
        service,
        identity,
        request(
            "accept",
            instance=operation["target"],
            operation=child,
            expected_revision=operation["revision"],
            restore_access=True,
        ),
    )
    service.tick()


def test_batch_serial_acceptance_original_replay_and_control_restore(batches, tmp_path):
    service, host, identity, _now = batches
    check, view = create(batches)
    assert view["state"] == "ready" and not host.applied
    command, result = decide(batches, view, "start")
    assert service.command(command, identity) == result
    service.tick()
    first = child_identity(check.id, "operator-0")
    assert service.view(check.id, identity)["items"][0]["operation"] == first
    service.tick()
    assert service.view(check.id, identity)["items"][1]["operation"] is None
    accept(batches, first)
    service.tick()
    second = child_identity(check.id, "operator-1")
    assert service.view(check.id, identity)["items"][1]["operation"] == second
    accept(batches, second)
    service.tick()
    assert service.view(check.id, identity)["state"] == "completed"
    encoded = snapshot_control(service.store)
    restored = AuthorityStore.initialize(tmp_path / "restored" / "authority.sqlite", "owner")
    restore_control(restored, encoded)
    assert UpgradeBatchService(type(service.upgrades)(restored, host)).view(check.id, identity)[
        "counts"
    ] == {"accepted_restored": 2}
    assert service.lookup(command.id, identity)["batch"]["id"] == check.id


def test_pause_cancel_and_window_close_never_dispatch_an_extra_child(batches):
    service, host, identity, now = batches
    check, view = create(batches)
    decide(batches, view, "start")
    service.tick()
    decide(batches, service.view(check.id, identity), "pause")
    service.tick()
    assert service.view(check.id, identity)["state"] == "paused"
    assert service.view(check.id, identity)["items"][1]["operation"] is None
    decide(batches, service.view(check.id, identity), "cancel")
    assert service.view(check.id, identity)["items"][1]["status"] == "skipped"
    assert not host.applied
    # A second batch can be reviewed, but an expired window cannot start it.
    _check2, view = create(batches, 1, prefix="spare")
    with pytest.raises(AdminError, match="window_closed"):
        decide(batches, view, "start", window_start=now[0] - 10, window_end=now[0] - 1)


@pytest.mark.parametrize("count", [1, 10, 50])
def test_bounded_status_queries_have_no_private_host_fanout(batches, monkeypatch, count):
    service, host, identity, _now = batches
    check, _view = create(batches, count)
    transaction = service.store.transaction
    statements = []

    @contextmanager
    def traced():
        with transaction() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(service.store, "transaction", traced)
    host.prepare = Mock(side_effect=AssertionError("GET called the host"))
    view = service.view(check.id, identity, limit=count)
    assert len(view["items"]) == count
    assert len([sql for sql in statements if sql.startswith("SELECT")]) == 3
    assert "plan" not in view["items"][0]


def test_revoked_generation_and_stale_readiness_block_dispatch(batches):
    service, host, identity, _now = batches
    check, view = create(batches)
    decide(batches, view, "start")
    original = host.prepare

    def revoke(*args):
        plan = original(*args)
        service.store.revoke_identity()
        return plan

    host.prepare = revoke
    service.tick()
    view = service.view(check.id, identity)
    assert view["state"] == "blocked"
    assert all(item["operation"] is None for item in view["items"])
    service.store.restore_identity()
    service.tick()
    assert service.view(check.id, identity)["state"] == "blocked"


@pytest.mark.parametrize("count", [0, 51])
def test_membership_bounds(count):
    with pytest.raises(ValidationError):
        BatchCommand(
            id=str(uuid4()),
            action="check",
            reason="Review",
            release="release-20261101-01",
            members=[{"instance": f"operator-{i}", "expected_revision": 1} for i in range(count)],
        )


def test_batch_http_and_private_grants_share_the_original_receipt(batches):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app.modules.hosted_admin.api.application import create_admin_app, COOKIE, CSRF_COOKIE
    from app.modules.hosted_admin.application.contracts import BrokerRequest
    from app.modules.hosted_admin.infrastructure.private_operations import PrivateOperations

    service, host, identity, now = batches
    dispatch = SimpleNamespace(upgrades=service.upgrades)
    private = PrivateOperations(service.store, None, dispatch)
    credentials = service.store.login(service.store.issue())
    app = create_admin_app(
        "http://epm-admin.localhost:8765",
        lambda raw: service.store.handle(BrokerRequest.model_validate(raw), dispatch),
    )
    with TestClient(app, base_url="http://epm-admin.localhost:8765") as client:
        client.cookies.set(COOKIE, credentials["token"])
        client.cookies.set(CSRF_COOKIE, credentials["csrf"])
        client.headers.update(
            {"Origin": "http://epm-admin.localhost:8765", "X-Epm-Admin-Csrf": credentials["csrf"]}
        )
        check = BatchCommand(
            id=str(uuid4()),
            action="check",
            members=[{"instance": "operator-0", "expected_revision": 1}],
            release="release-20261101-01",
            reason="Reviewed target",
        )
        result = client.post("/upgrade-batch-command", json={"batch": check.model_dump()})
        assert result.status_code == 202 and not host.applied
        service.tick()
        service.tick()
        view = client.get(f"/admin-api/upgrade-batches/{check.id}/page/0/50").json()
        start = BatchCommand(
            id=str(uuid4()),
            action="start",
            batch=check.id,
            expected_revision=view["revision"],
            sessions=[{"instance": "operator-0", "handling": "preserve"}],
            window_start=now[0] - 1,
            window_end=now[0] + 100,
            confirmed=True,
            reason="Agreed interruption",
        )
        assert (
            client.post("/upgrade-batch-command", json={"batch": start.model_dump()}).status_code
            == 401
        )
        grant = private.handle({"action": "batch-grant", "batch": start.model_dump()})["credential"]
        result = client.post(
            "/upgrade-batch-command", json={"batch": start.model_dump(), "credential": grant}
        )
        assert result.status_code == 202
        assert (
            private.handle({"action": "batch-admit", "batch": start.model_dump()}) == result.json()
        )
        assert (
            client.get(f"/admin-api/upgrade-batches/{start.id}/page/0/50").json()["id"] == check.id
        )
        assert client.get(f"/admin-api/upgrade-batch-commands/{start.id}").json()["found"]
        assert not host.applied


def test_failed_child_stops_queue_and_changed_key_conflicts(batches):
    service, host, identity, _now = batches
    check, view = create(batches)
    command, _ = decide(batches, view, "start")
    with pytest.raises(AdminError, match="command_conflict"):
        service.command(command.model_copy(update={"reason": "Changed request"}), identity)
    service.tick()
    host.failure = "recovery"
    for _ in range(6):
        service.upgrades.tick()
    view = service.view(check.id, identity)
    assert view["state"] == "blocked"
    assert view["items"][0]["status"] == "failed"
    assert view["items"][1]["operation"] is None
    child = view["items"][0]["operation"]
    original_error = service.upgrades.engine.get(child)["error"]
    with service.upgrades.engine.worker_lock(child), pytest.raises(AdminError, match="busy"):
        decide(batches, view, "skip", instance="operator-0")
    decide(batches, view, "skip", instance="operator-0")
    assert service.view(check.id, identity)["items"][0]["status"] == "containing"
    host.contain_for_skip.side_effect = [OSError("private cleanup unavailable"), True]
    service.tick()
    assert service.view(check.id, identity)["items"][1]["operation"] is None
    assert service.view(check.id, identity)["items"][0]["status"] == "failed"
    decide(batches, service.view(check.id, identity), "skip", instance="operator-0")
    service.tick()
    assert service.view(check.id, identity)["items"][0]["status"] == "skipped"
    assert service.upgrades.engine.get(child)["error"] == original_error
    assert service.upgrades.engine.get(child)["state"] == "paused"
    decide(batches, service.view(check.id, identity), "recheck")
    service.tick()
    service.tick()
    decide(batches, service.view(check.id, identity), "resume")
    service.tick()
    second = child_identity(check.id, "operator-1")
    accept(batches, second)
    service.tick()
    assert service.view(check.id, identity)["state"] == "mixed"
    assert service.view(check.id, identity)["counts"] == {"skipped": 1, "accepted_restored": 1}


def test_waiting_batch_does_not_starve_readiness_and_directory_is_read_only(batches):
    service, host, identity, _now = batches
    first, view = create(batches, 1)
    decide(batches, view, "start")
    service.tick(first.id)
    other = BatchCommand(
        id=str(uuid4()),
        action="check",
        members=[{"instance": "other", "expected_revision": 1}],
        release="release-20261101-01",
        reason="Another readiness",
    )
    service.command(other, identity)
    for _ in range(6):
        service.tick()
    assert service.view(other.id, identity)["state"] == "ready"
    assert service.directory(identity)["total"] == 2
    host.prepare = Mock(side_effect=AssertionError("directory opened a workspace"))
    assert len(service.directory(identity)["items"]) == 2
    assert not host.applied


@pytest.mark.parametrize(
    "tamper", ["membership", "target", "session", "receipt", "state", "admission", "event"]
)
def test_retained_batch_tampering_is_rejected_on_restore(batches, tmp_path, tamper):
    import json
    from app.modules.hosted_admin.application.operations import canonical

    service, _host, identity, _now = batches
    check, view = create(batches, 1)
    decide(batches, view, "start")
    service.tick()
    value = json.loads(snapshot_control(service.store))
    tables = value["tables"]
    if tamper == "membership":
        tables["upgrade_batch_member"][0]["instance"] = "fabricated"
    elif tamper in {"target", "session"}:
        row = next(
            row
            for row in tables["operation"]
            if row["id"] == child_identity(check.id, "operator-0")
        )
        payload = json.loads(row["payload"])
        if tamper == "target":
            payload["plan"]["target"]["digest"] = "f" * 64
        else:
            payload["session_handling"] = "revoke"
        row["payload"] = canonical(payload)
        from app.modules.hosted_admin.application.operations import fingerprint

        row["request_hash"] = fingerprint(payload)
        for plan in tables["upgrade_plan"]:
            if plan["operation_id"] == row["id"]:
                plan["payload"] = canonical(payload["plan"])
    elif tamper == "receipt":
        row = tables["upgrade_batch_command"][-1]
        result = json.loads(row["result"])
        result["state"] = "completed"
        row["result"] = canonical(result)
    elif tamper == "state":
        tables["upgrade_batch"][0]["state"] = "completed"
    elif tamper == "admission":
        tables["upgrade_batch_child"][0]["admitted"] = 0.0
    else:
        tables["upgrade_batch_event"][1]["action"] = "finished"
    restored = AuthorityStore.initialize(tmp_path / tamper / "authority.sqlite", "owner")
    with pytest.raises((AdminError, ValueError)):
        restore_control(restored, canonical(value).encode())


def test_window_is_rechecked_at_actual_pause_and_cancel_wins_a_slow_dispatch(batches):
    service, host, identity, now = batches
    check, view = create(batches, 1)
    decide(batches, view, "start", window_end=now[0] + 2)
    service.tick()
    child = child_identity(check.id, "operator-0")
    with service.store.transaction() as connection:
        connection.execute("UPDATE operation SET state='running' WHERE id=?", (child,))
    now[0] += 3
    with pytest.raises(AdminError, match="window_closed"):
        service.upgrades.engine.require_authority(child, phase="pause")
    # A separate batch's admission must lose to a durable cancel recorded during
    # a slow host check. No transaction or host lock prevents that decision.
    second, view = create(batches, 1, prefix="spare")
    decide(batches, view, "start")
    original = host.prepare

    def cancel_then_return(*args):
        result = original(*args)
        decide(batches, service.view(second.id, identity), "cancel")
        return result

    host.prepare = cancel_then_return
    service.tick(second.id)
    assert service.view(second.id, identity)["state"] == "cancelled"
    assert service.view(second.id, identity)["items"][0]["operation"] is None


def test_child_admission_link_rolls_back_and_retries_with_the_same_identity(batches):
    service, _host, identity, _now = batches
    check, view = create(batches, 1)
    decide(batches, view, "start")
    with service.store.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER interrupt_batch_link BEFORE INSERT ON upgrade_batch_child BEGIN SELECT RAISE(ABORT,'interrupt after child link'); END"
        )
    service.tick()
    with service.store.transaction() as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM operation WHERE id=?", (child_identity(check.id, "operator-0"),)
            ).fetchone()
            is None
        )
        assert (
            connection.execute(
                "SELECT child_id FROM upgrade_batch_member WHERE batch_id=?", (check.id,)
            ).fetchone()[0]
            is None
        )
        connection.execute("DROP TRIGGER interrupt_batch_link")
    decide(batches, service.view(check.id, identity), "recheck")
    service.tick()
    service.tick()
    decide(batches, service.view(check.id, identity), "resume")
    service.tick()
    assert service.view(check.id, identity)["items"][0]["operation"] == child_identity(
        check.id, "operator-0"
    )
    snapshot_control(service.store)


def test_two_coordinators_and_pause_during_readiness_cannot_double_dispatch(batches):
    import threading

    service, host, identity, _now = batches
    check, view = create(batches, 1)
    decide(batches, view, "start")
    entered, release = threading.Event(), threading.Event()
    original = host.prepare

    def slow(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    host.prepare = slow
    worker = threading.Thread(target=service.tick)
    worker.start()
    try:
        assert entered.wait(5)
        service.tick()  # Same parent's nonblocking worker claim is already held.
        decide(batches, service.view(check.id, identity), "pause")
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    view = service.view(check.id, identity)
    assert view["state"] == "paused" and view["items"][0]["operation"] is None
    snapshot_control(service.store)


def test_skip_authority_loss_keeps_slot_blocked_until_fresh_explicit_retry(batches):
    service, host, identity, _now = batches
    check, view = create(batches, 1)
    decide(batches, view, "start")
    service.tick()
    host.failure = "recovery"
    for _ in range(6):
        service.upgrades.tick()
    decide(batches, service.view(check.id, identity), "skip", instance="operator-0")

    def revoked(_payload):
        service.store.revoke_identity()
        return True

    host.contain_for_skip = revoked
    service.tick()
    view = service.view(check.id, identity)
    assert view["items"][0]["status"] == "failed"
    assert view["items"][0]["can_skip"]
    service.store.restore_identity()
    with service.store.transaction() as connection:
        current = dict(service.store._identity(connection))
    host.contain_for_skip = Mock(return_value=True)
    fresh = (service, host, current, _now)
    decide(fresh, view, "skip", instance="operator-0")
    service.tick()
    assert service.view(check.id, current)["items"][0]["status"] == "skipped"
    snapshot_control(service.store)


def test_cancel_during_failed_containment_can_be_retried_without_restarting_queue(batches):
    service, host, identity, _now = batches
    check, view = create(batches, 1)
    decide(batches, view, "start")
    service.tick()
    host.failure = "recovery"
    for _ in range(6):
        service.upgrades.tick()
    decide(batches, service.view(check.id, identity), "skip", instance="operator-0")
    decide(batches, service.view(check.id, identity), "cancel")
    host.contain_for_skip = Mock(side_effect=[OSError("unavailable"), True])
    service.tick()
    decide(batches, service.view(check.id, identity), "skip", instance="operator-0")
    service.tick()
    view = service.view(check.id, identity)
    assert view["state"] == "cancelled" and view["counts"] == {"skipped": 1}
    snapshot_control(service.store)


def test_50_member_wire_bounds_and_read_only_private_history(batches):
    import json
    from types import SimpleNamespace
    from app.modules.hosted_admin.infrastructure.broker import MAX_FRAME, MAX_RESPONSE_FRAME
    from app.modules.hosted_admin.infrastructure.private_operations import PrivateOperations

    service, host, identity, _now = batches
    check, view = create(batches, 50)
    assert (
        len(json.dumps({"batch": check.model_dump(), "method": "batch_command"}).encode())
        < MAX_FRAME
    )
    assert len(json.dumps(view).encode()) < MAX_RESPONSE_FRAME
    private = PrivateOperations(service.store, None, SimpleNamespace(upgrades=service.upgrades))
    assert private.handle({"action": "batch-status", "identifier": check.id})["total"] == 50
    assert private.handle({"action": "batch-list"})["total"] == 1
    assert not host.applied


def test_disabled_member_keeps_its_access_choice_and_required_session_revocation(batches):
    service, host, identity, _now = batches
    original = host.prepare

    def prepare(instance, release):
        plan = original(instance, release)
        if instance == "operator-1":
            plan["active"] = False
            plan["target"]["preserve_sessions"] = False
        return plan

    host.prepare = prepare
    check, view = create(batches)
    assert view["items"][1]["access_active"] is False
    with pytest.raises(AdminError, match="session_handling_required"):
        decide(batches, view, "start")
    decide(
        batches,
        view,
        "start",
        sessions=[
            {"instance": "operator-0", "handling": "preserve"},
            {"instance": "operator-1", "handling": "revoke"},
        ],
    )
    service.tick()
    accept(batches, child_identity(check.id, "operator-0"))
    service.tick()
    child = child_identity(check.id, "operator-1")
    for _ in range(10):
        service.upgrades.tick()
    operation = service.upgrades.engine.get(child)
    submit(
        service.upgrades,
        identity,
        request(
            "accept",
            instance="operator-1",
            operation=child,
            expected_revision=operation["revision"],
            restore_access=False,
        ),
    )
    service.upgrades.tick()
    service.tick()
    assert service.view(check.id, identity)["counts"] == {
        "accepted_restored": 1,
        "accepted_disabled": 1,
    }
    assert service.view(check.id, identity)["state"] == "completed"
    snapshot_control(service.store)


def test_accepted_child_rollback_requires_review_before_advancing_the_batch(batches):
    service, host, identity, _now = batches
    check, view = create(batches)
    decide(batches, view, "start")
    service.tick()
    child = child_identity(check.id, "operator-0")
    host.failure = "switch"
    for _ in range(7):
        service.upgrades.tick()
    forward = service.upgrades.engine.get(child)
    rollback = request(
        "rollback", instance="operator-0", operation=child, expected_revision=forward["revision"]
    )
    submit(service.upgrades, identity, rollback)
    for _ in range(8):
        service.upgrades.tick()
    operation = service.upgrades.engine.get(rollback.id)
    assert operation["state"] == "waiting"
    submit(
        service.upgrades,
        identity,
        request(
            "accept",
            instance="operator-0",
            operation=rollback.id,
            expected_revision=operation["revision"],
            restore_access=True,
        ),
    )
    service.upgrades.tick()
    service.tick()
    view = service.view(check.id, identity)
    assert view["state"] == "blocked"
    assert view["items"][0]["status"] == "rolled_back"
    assert view["items"][1]["operation"] is None
    decide(batches, view, "skip", instance="operator-0")
    decide(batches, service.view(check.id, identity), "recheck")
    service.tick()
    service.tick()
    decide(batches, service.view(check.id, identity), "resume")
    service.tick()
    accept(batches, child_identity(check.id, "operator-1"))
    service.tick()
    assert service.view(check.id, identity)["state"] == "mixed"
    snapshot_control(service.store)

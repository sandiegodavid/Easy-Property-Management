"""Focused durable upgrades: decisions, receipts, restart and recovery fencing."""

from contextlib import contextmanager
from unittest.mock import Mock
from uuid import uuid4
import pytest
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import Observation
from app.modules.hosted_admin.application.upgrades import UpgradeCommand
from app.modules.hosted_admin.infrastructure.authority import AuthorityStore
from app.modules.hosted_admin.infrastructure.control_recovery import (
    snapshot_control,
    restore_control,
)
from app.modules.hosted_admin.infrastructure.upgrades import UpgradeService
from app.modules.hosted_admin.infrastructure.operations import OperationEngine


class Host:
    def __init__(self):
        self.applied, self.effects = [], set()
        self.failure = None
        self.preserve, self.revision = True, 1

    def prepare(self, _instance, release):
        return {
            "instance": {
                "key": "a",
                "revision": self.revision,
                "instance_id": "00000000-0000-4000-8000-000000000001",
                "allocation_id": "00000000-0000-4000-8000-000000000002",
                "workspace_id": "00000000-0000-4000-8000-000000000003",
                "operator_id": "00000000-0000-4000-8000-000000000004",
                "release": "release-20261030-01",
                "profile": "qualified-two",
            },
            "target": {
                "release": release,
                "eligible": True,
                "preserve_sessions": self.preserve,
                "digest": "a" * 64,
                "installed": 1.0,
                "blockers": [],
                "compatibility_digest": "b" * 64,
            },
            "original_digest": "c" * 64,
            "configuration_digest": "d" * 64,
            "environment_digest": "e" * 64,
            "recovery_configuration_digest": "f" * 64,
            "binding_revision": 1,
            "admin_revision": 2,
            "fence": 0,
            "generation": 0,
            "active": True,
        }

    def inspect(self, payload, step):
        return (
            Observation("verified", {"verified": True})
            if (payload["operation_id"], step) in self.effects
            else Observation("absent")
        )

    def apply(self, payload, step):
        self.applied.append(step)
        self.effects.add((payload["operation_id"], step))
        if self.failure == step:
            self.failure = None
            raise OSError("response lost after effect")

    def contain(self, _payload):
        return True


@pytest.fixture
def upgrade(tmp_path):
    store = AuthorityStore.initialize(tmp_path / "control" / "authority.sqlite", "owner")
    now = [store.clock()]
    store.clock = lambda: now[0]
    with store.transaction() as connection:
        identity = dict(store._identity(connection))
    host = Host()
    return UpgradeService(store, host), host, identity, now


def request(action="check", **changes):
    values = {
        "id": str(uuid4()),
        "instance": "a",
        "action": action,
        "expected_revision": 1,
        "reason": "Agreed upgrade",
    }
    if action == "check":
        values["release"] = "release-20261031-01"
    else:
        values["confirmed"] = True
    return UpgradeCommand(**(values | changes))


def submit(service, identity, command):
    credential = service.store.issue(command.fingerprint()) if command.action != "check" else ""
    return service.command(command, identity, credential)


def started(upgrade):
    service, host, identity, now = upgrade
    check = request()
    submit(service, identity, check)
    service.tick()
    prepared = service.engine.get(check.id)
    start = request(
        "start",
        operation=check.id,
        expected_revision=prepared["revision"],
        session_handling="preserve",
    )
    submit(service, identity, start)
    return service, host, identity, now, start


def await_acceptance(service, start):
    for _ in range(10):
        service.tick()
    status = service.engine.get(start.id)
    assert status["state"] == "waiting"
    assert status["steps"][-2]["state"] == "verified"
    return status


@pytest.mark.parametrize("unrelated_operations", [1, 100])
def test_upgrade_status_has_a_fixed_query_budget_and_never_calls_the_host(
    upgrade, monkeypatch, unrelated_operations
):
    service, host, identity, _now, start = started(upgrade)
    for index in range(unrelated_operations):
        submit(service, identity, request(instance=f"other-{index}"))
    original = service.store.transaction
    statements = []

    @contextmanager
    def traced():
        with original() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(service.store, "transaction", traced)
    monkeypatch.setattr(host, "prepare", Mock(side_effect=AssertionError("status called host")))
    monkeypatch.setattr(host, "inspect", Mock(side_effect=AssertionError("status ran effect")))
    view = service.view(start.id, identity)
    queries = [sql for sql in statements if sql.startswith("SELECT")]
    assert len(queries) == 5
    assert any("LIMIT 3" in sql for sql in queries)
    assert len(view["operation"]["steps"]) == 9
    assert view["operation"]["target"] == "a"
    assert "payload" not in view["operation"]
    with pytest.raises(AdminError, match="not_found"):
        service.view(start.id, identity | {"id": "another-administrator"})


def test_revocation_during_an_effect_is_contained_and_needs_fresh_review(upgrade, monkeypatch):
    service, host, identity, _now, start = started(upgrade)
    status = await_acceptance(service, start)
    submit(
        service,
        identity,
        request(
            "accept", operation=start.id, expected_revision=status["revision"], restore_access=True
        ),
    )
    original = host.apply

    def revoked(payload, step):
        original(payload, step)
        service.store.revoke_identity()
        service.engine.require_authority(payload["operation_id"])

    monkeypatch.setattr(host, "apply", revoked)
    contained = Mock(return_value=True)
    monkeypatch.setattr(host, "contain", contained)
    service.tick()
    operation = service.engine.get(start.id)
    assert operation["state"] == "paused"
    assert operation["error"] == "admin_authority_fenced"
    assert operation["steps"][-1]["state"] != "verified"
    contained.assert_called_once()
    service.store.restore_identity()
    service.tick()
    assert host.applied.count("accept") == 1
    assert service.engine.get(start.id)["state"] == "paused"


def test_ready_start_accept_exact_replay_and_fenced_restore(upgrade, tmp_path):
    service, host, identity, _now, start = started(upgrade)
    status = await_acceptance(service, start)
    assert host.applied == [
        "revalidate",
        "pause",
        "stop",
        "recovery",
        "validate",
        "switch",
        "start",
        "verify",
    ]
    assert service.command(start, identity) == {"id": start.id, "state": "queued", "revision": 1}
    accept = request(
        "accept", operation=start.id, expected_revision=status["revision"], restore_access=True
    )
    result = submit(service, identity, accept)
    service.tick()
    assert service.engine.get(start.id)["state"] == "succeeded"
    assert service.command(accept, identity) == result
    assert host.applied.count("accept") == 1
    restored = AuthorityStore.initialize(tmp_path / "restored" / "authority.sqlite", "owner")
    restore_control(restored, snapshot_control(service.store))
    assert OperationEngine(restored).get(start.id)["state"] == "succeeded"
    with restored.transaction() as connection:
        assert connection.execute("SELECT enabled FROM administrator").fetchone()[0] == 0


def test_unknown_effect_reconciles_after_explicit_resume(upgrade):
    service, host, identity, now, start = started(upgrade)
    host.failure = "switch"
    for _ in range(6):
        service.tick()
    status = service.engine.get(start.id)
    assert status["state"] == "unknown"
    with service.store.transaction() as connection:
        operation = service.engine._get(connection, start.id)
    service.engine.resume(
        start.id,
        status["revision"],
        identity,
        service.store.issue(service.engine.resume_hash(operation)),
    )
    now[0] += 61
    service.tick()
    assert host.applied.count("switch") == 1
    await_acceptance(service, start)


def test_post_pause_cancel_requires_controlled_recovery(upgrade):
    service, _host, identity, _now, start = started(upgrade)
    service.tick()
    service.tick()
    status = service.engine.get(start.id)
    with pytest.raises(AdminError) as error:
        service.engine.cancel(start.id, status["revision"], identity)
    assert error.value.code == "admin_upgrade_recovery_required"


def test_rollback_preserves_forward_history_and_requires_separate_acceptance(upgrade):
    service, host, identity, _now, start = started(upgrade)
    status = await_acceptance(service, start)
    rollback = request("rollback", operation=start.id, expected_revision=status["revision"])
    submit(service, identity, rollback)
    status = await_acceptance(service, rollback)
    assert service.engine.get(start.id)["cancel_requested"] == 1
    assert host.applied[-5:] == [
        "stop",
        "validate_previous",
        "switch_previous",
        "start_previous",
        "verify_previous",
    ]
    submit(
        service,
        identity,
        request(
            "accept",
            operation=rollback.id,
            expected_revision=status["revision"],
            restore_access=False,
        ),
    )
    service.tick()
    assert service.engine.get(rollback.id)["state"] == "succeeded"
    snapshot_control(service.store)


@pytest.mark.parametrize("problem", ["stale", "preservation", "changed_revision"])
def test_invalid_readiness_cannot_start(upgrade, problem):
    service, host, identity, now = upgrade
    check = request()
    submit(service, identity, check)
    if problem == "preservation":
        host.preserve = False
    if problem == "changed_revision":
        host.revision = 2
    service.tick()
    prepared = service.engine.get(check.id)
    if problem == "stale":
        now[0] += 301
    start = request(
        "start",
        operation=check.id,
        expected_revision=prepared["revision"],
        session_handling="preserve",
    )
    with pytest.raises(AdminError):
        submit(service, identity, start)
    assert not host.applied


def test_acceptance_requires_verification_and_exact_authorization(upgrade):
    service, _host, identity, _now, start = started(upgrade)
    with pytest.raises(AdminError):
        submit(service, identity, request("accept", operation=start.id, restore_access=True))
    status = await_acceptance(service, start)
    accept = request(
        "accept", operation=start.id, expected_revision=status["revision"], restore_access=True
    )
    with pytest.raises(AdminError):
        service.command(accept, identity, service.store.issue(start.fingerprint()))
    submit(service, identity, accept)
    with pytest.raises(AdminError):
        service.command(accept.model_copy(update={"restore_access": False}), identity)


def test_failed_acceptance_allows_new_explicit_keep_disabled_decision(upgrade):
    service, host, identity, _clock, start = started(upgrade)
    status = await_acceptance(service, start)
    first = request(
        "accept", operation=start.id, expected_revision=status["revision"], restore_access=True
    )
    submit(service, identity, first)
    original_apply = host.apply

    def reject(payload, step):
        if step == "accept":
            raise ValueError("Source access was disabled meanwhile")
        return original_apply(payload, step)

    host.apply = reject
    service.tick()
    assert service.engine.get(start.id)["state"] == "unknown"
    host.apply = original_apply
    status = service.engine.get(start.id)
    second = request(
        "accept", operation=start.id, expected_revision=status["revision"], restore_access=False
    )
    submit(service, identity, second)
    service.tick()
    assert service.engine.get(start.id)["state"] == "succeeded"
    with service.store.transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM upgrade_decision WHERE operation_id=?", (start.id,)
            ).fetchone()[0]
            == 2
        )
    snapshot_control(service.store)


@pytest.mark.parametrize(
    "step",
    ["revalidate", "pause", "stop", "recovery", "validate", "switch", "start", "verify", "accept"],
)
def test_restart_after_each_effect_before_checkpoint_never_repeats_it(upgrade, step):
    service, host, identity, clock, start = started(upgrade)
    while True:
        current = service.engine.get(start.id)
        pending = next(item for item in current["steps"] if item["state"] != "verified")
        if pending["kind"] == step:
            break
        service.tick()
    if step == "accept":
        service.tick()  # Explicit acceptance wait; no source effect yet.
        current = service.engine.get(start.id)
        submit(
            service,
            identity,
            request(
                "accept",
                operation=start.id,
                expected_revision=current["revision"],
                restore_access=True,
            ),
        )
    with service.store.transaction() as connection:
        connection.execute(
            f"CREATE TRIGGER lost_upgrade_checkpoint BEFORE UPDATE ON operation_step WHEN NEW.state='verified' AND OLD.kind='{step}' BEGIN SELECT RAISE(ABORT,'lost checkpoint'); END"
        )
    # The worker retains its intent/claim when the post-effect DB write fails.
    service.tick()
    assert host.applied.count(step) == 1
    with service.store.transaction() as connection:
        connection.execute("DROP TRIGGER lost_upgrade_checkpoint")
    reopened = AuthorityStore(service.store.path, clock=lambda: clock[0])
    clock[0] += 61
    service.store = reopened
    service.engine = OperationEngine(reopened)
    service.tick()
    assert host.applied.count(step) == 1
    snapshot_control(reopened)

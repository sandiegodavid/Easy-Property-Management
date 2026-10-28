"""Durable steps, concurrent authority fences and exact original-effect recovery."""

import sqlite3
from uuid import uuid4

import pytest

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import (
    Observation,
    OperationIntent,
    Reservation,
)
from app.modules.hosted_admin.infrastructure.operations import OperationEngine
from app.modules.hosted_admin.tests.test_authority import authority as authority
from app.modules.hosted_admin.tests.test_authority import command, login, request


@pytest.fixture
def engine(authority):
    store, clock = authority
    return OperationEngine(store), store, clock


def identity(store):
    with store.transaction() as connection:
        return dict(store._identity(connection))


def admitted(store, **changes):
    cmd = command(**changes)
    credentials = login(store)
    if cmd.action not in {"disable", "revoke"}:
        store.reauthenticate(
            request(
                credentials, cmd, method="reauthenticate", credential=store.issue(cmd.fingerprint())
            )
        )
    store.admit(request(credentials, cmd))
    return cmd.operation_id


class Effects:
    def __init__(self):
        self.observed = {}
        self.calls = []
        self.contained = False
        self.before_apply = lambda: None
        self.after_apply = lambda: None

    def inspect(self, payload, step):
        return self.observed.get(step, Observation("absent"))

    def apply(self, payload, step):
        self.before_apply()
        self.calls.append(step)
        self.observed[step] = Observation(
            "verified", {"done": True}, payload.get("operation_id", "owned-resource")
        )
        self.after_apply()

    def contain(self, _payload):
        self.contained = True
        return True


def test_intent_precedes_external_effect_and_no_transaction_spans_it(engine):
    runner, store, _ = engine
    identifier = admitted(store)
    effects = Effects()

    def outside_transaction():
        # A separate connection can write while the provider is executing.
        with store.transaction() as connection:
            step = connection.execute(
                "SELECT state FROM operation_step WHERE operation_id=?", (identifier,)
            ).fetchone()
            assert step[0] == "intent"
            store._audit(connection, "provider_probe", identifier)

    effects.before_apply = outside_transaction
    assert runner.run(identifier, effects) == {"done": True}
    assert runner.run(identifier, effects) == {"done": True}
    assert effects.calls == ["source_command"]
    status = runner.get(identifier)
    assert status["state"] == "succeeded" and status["steps"][0]["state"] == "verified"
    assert "payload" not in status and "generation" not in status


def test_crash_after_effect_reconciles_without_second_publication(engine):
    runner, store, clock = engine
    identifier = admitted(store)
    effects = Effects()
    with store.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER checkpoint_failure BEFORE UPDATE OF result ON admission BEGIN SELECT RAISE(ABORT,'checkpoint lost'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        runner.run(identifier, effects)
    assert runner.get(identifier)["state"] == "running"
    with pytest.raises(AdminError, match="busy"):
        runner.run(identifier, effects)
    with store.transaction() as connection:
        connection.execute("DROP TRIGGER checkpoint_failure")
    clock[0] += 61
    reopened = OperationEngine(type(store)(store.path, clock=store.clock))
    assert reopened.run(identifier, effects) == {"done": True}
    assert len(effects.calls) == 1


def test_unknown_outcome_requires_explicit_resume_and_never_implies_absence(engine):
    runner, store, _ = engine
    identifier = admitted(store)
    effects = Effects()
    effects.observed["source_command"] = Observation("unknown")
    with pytest.raises(AdminError, match="reconciliation_required"):
        runner.run(identifier, effects)
    state = runner.get(identifier)
    assert state["state"] == "unknown" and not effects.calls
    with pytest.raises(AdminError, match="resume_required"):
        runner.run(identifier, effects)
    runner.resume(identifier, state["revision"], identity(store))
    effects.observed["source_command"] = Observation(
        "verified", {"done": True}, "exact-provider-id"
    )
    assert runner.run(identifier, effects) == {"done": True}
    assert not effects.calls


@pytest.mark.parametrize("fence", ["revoke", "disable", "cancel"])
def test_inflight_effect_rechecks_fences_and_contains_before_checkpoint(engine, fence):
    runner, store, _ = engine
    identifier = admitted(
        store, action="approve", subject="verified", enrollment_received_at=1000.0
    )
    effects = Effects()

    def intervene():
        if fence == "revoke":
            store.revoke_identity()
        elif fence == "disable":
            admitted(store)
        else:
            runner.cancel(identifier, runner.get(identifier)["revision"], identity(store))

    effects.after_apply = intervene
    with pytest.raises(AdminError, match="fenced"):
        runner.run(identifier, effects)
    assert effects.contained
    assert runner.get(identifier)["state"] == "paused"
    with store.transaction() as connection:
        assert (
            connection.execute(
                "SELECT state FROM operation_step WHERE operation_id=?", (identifier,)
            ).fetchone()[0]
            == "intent"
        )


def test_instance_exclusion_and_priority_disable_retains_original_intent(engine):
    runner, store, _ = engine
    identifier = admitted(
        store, action="approve", subject="verified", enrollment_received_at=1000.0
    )
    with pytest.raises(AdminError, match="operation_pending"):
        admitted(store, action="approve", subject="other", enrollment_received_at=1000.0)
    disabling = admitted(store)
    assert disabling != identifier
    assert runner.get(identifier)["cancel_requested"]
    with pytest.raises(AdminError, match="not_resumable"):
        runner.resume(identifier, runner.get(identifier)["revision"], identity(store))


def test_cancel_is_safe_stop_not_deletion_and_cannot_resume(engine):
    runner, store, _ = engine
    identifier = admitted(store)
    current = runner.get(identifier)
    runner.cancel(identifier, current["revision"], identity(store))
    effects = Effects()
    runner.finish_cancel(identifier, effects)
    runner.finish_cancel(identifier, effects)
    assert runner.get(identifier)["state"] == "cancelled" and not effects.calls
    with pytest.raises(AdminError, match="operation_cancelled"):
        runner.run(identifier, effects)
    with pytest.raises(AdminError, match="not_resumable"):
        runner.resume(identifier, runner.get(identifier)["revision"], identity(store))


def test_fresh_authority_required_after_revocation_but_session_loss_is_independent(engine):
    runner, store, _ = engine
    identifier = admitted(
        store, action="approve", subject="verified", enrollment_received_at=1000.0
    )
    store.revoke_identity()
    store.restore_identity()
    state = runner.get(identifier)
    with pytest.raises(AdminError, match="grant_invalid"):
        runner.resume(identifier, state["revision"], identity(store))
    with store.transaction() as connection:
        operation = runner._get(connection, identifier)
    credential = store.issue(runner.resume_hash(operation))
    runner.resume(identifier, state["revision"], identity(store), credential)
    assert runner.run(identifier, Effects()) == {"done": True}


def test_reservation_and_operation_admission_roll_back_together(engine):
    runner, store, _ = engine
    first = OperationIntent(
        operation_id=str(uuid4()),
        kind="provision",
        target="test-one",
        expected_revision=0,
        reason="Fresh synthetic test",
    )
    one = Reservation(kind="port", identity="8101")

    def check(*_):
        return None

    runner.reserve(first, [one], identity(store), admit_check=check)
    other = first.model_copy(update={"operation_id": str(uuid4()), "target": "test-two"})
    with pytest.raises(AdminError, match="allocation_conflict"):
        runner.reserve(other, [one], identity(store), admit_check=check)
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM operation").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM operation_target").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM reservation").fetchone()[0] == 1
    assert (
        runner.reserve(first, [one], identity(store), admit_check=check)["id"] == first.operation_id
    )
    with pytest.raises(AdminError, match="command_conflict"):
        runner.reserve(
            first.model_copy(update={"reason": "Different"}),
            [one],
            identity(store),
            admit_check=check,
        )


def test_multiple_steps_checkpoint_independently_and_keep_reservations(engine):
    runner, store, _ = engine
    intent = OperationIntent(
        operation_id=str(uuid4()),
        kind="provision",
        target="test-one",
        expected_revision=0,
        reason="Fresh synthetic test",
    )
    runner.reserve(
        intent,
        [Reservation(kind="port", identity="8101")],
        identity(store),
        admit_check=lambda *_: None,
    )
    effects = Effects()
    for step in ("allocate", "workspace", "provider_setup", "readiness"):
        runner.run(intent.operation_id, effects)
        assert effects.calls[-1] == step
    assert runner.get(intent.operation_id)["state"] == "succeeded"
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM reservation").fetchone()[0] == 1


def test_worker_lock_blocks_overlapping_worker_even_when_lease_has_expired(engine):
    runner, store, clock = engine
    identifier = admitted(store)
    with runner.worker_lock(identifier):
        clock[0] += 120
        with pytest.raises(AdminError, match="busy"):
            runner.run(identifier, Effects())


def test_operation_intent_step_result_and_audit_are_immutable(engine):
    runner, store, _ = engine
    identifier = admitted(store)
    runner.run(identifier, Effects())
    for sql in (
        "UPDATE operation SET payload='{}'",
        "DELETE FROM operation",
        "UPDATE operation_step SET state='pending'",
        "DELETE FROM operation_audit",
        "UPDATE operation SET result='{}'",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            with store.transaction() as connection:
                connection.execute(sql)


def test_control_snapshot_excludes_authorization_and_restore_never_restarts_work(engine, tmp_path):
    from app.modules.hosted_admin.infrastructure.authority import AuthorityStore
    from app.modules.hosted_admin.infrastructure.control_recovery import (
        snapshot_control,
        restore_control,
    )

    runner, store, _ = engine
    identifier = admitted(store)
    token = login(store)["token"]
    encoded = snapshot_control(store)
    assert token.encode() not in encoded
    for secret_table in (b'"grant":', b'"session":', b'"authorization":'):
        assert secret_table not in encoded
    restored = AuthorityStore.initialize(
        tmp_path / "restored" / "authority.sqlite", identity(store)["id"]
    )
    restore_control(restored, encoded)
    reopened = AuthorityStore(restored.path)
    assert OperationEngine(reopened).get(identifier)["state"] == "paused"
    with pytest.raises(AdminError, match="revoked"):
        reopened.issue()
    reopened.restore_identity()
    with pytest.raises(AdminError, match="fenced"):
        OperationEngine(reopened).run(identifier, Effects())
    with pytest.raises(AdminError, match="not_empty"):
        restore_control(reopened, encoded)


def test_retained_control_validation_rejects_missing_steps(engine):
    from app.modules.hosted_admin.infrastructure.authority import AuthorityStore

    _, store, _ = engine
    admitted(store)
    with store.transaction() as connection:
        connection.execute("DELETE FROM operation_step")
    with pytest.raises(AdminError, match="control_data_invalid"):
        AuthorityStore(store.path)


def test_operation_read_is_bounded_and_never_calls_provider(engine):
    runner, store, _ = engine
    identifier = admitted(store)
    with pytest.raises(AdminError, match="not_found"):
        runner.get(identifier, "another-administrator")
    assert runner.get(identifier)["state"] == "queued"


def test_authenticated_operation_http_lookup_resume_and_cancel(engine):
    from fastapi.testclient import TestClient
    from app.modules.hosted_admin.api.application import create_admin_app
    from app.modules.hosted_admin.application.contracts import BrokerRequest

    runner, store, _ = engine
    identifier = admitted(store)
    browser = TestClient(
        create_admin_app(
            "http://epm-admin.localhost:8765",
            lambda value: store.handle(BrokerRequest.model_validate(value), None),
        ),
        base_url="http://epm-admin.localhost:8765",
    )
    origin = {"Origin": "http://epm-admin.localhost:8765"}
    assert browser.get(f"/admin-api/operations/{identifier}").status_code == 401
    signed_in = browser.post("/login", json={"credential": store.issue()}, headers=origin)
    headers = origin | {"X-Epm-Admin-Csrf": signed_in.json()["csrf"]}
    current = browser.get(f"/admin-api/operations/by-key/{identifier}", headers=headers)
    assert current.status_code == 200 and current.json()["state"] == "queued"
    assert "request_hash" not in current.json()
    assert (
        browser.post(
            "/cancel", json={"operation_id": identifier, "expected_revision": 999}, headers=headers
        ).status_code
        == 409
    )
    assert browser.post(
        "/cancel",
        json={"operation_id": identifier, "expected_revision": current.json()["revision"]},
        headers=headers,
    ).json()["cancel_requested"]
    assert (
        browser.post(
            "/resume",
            json={
                "operation_id": identifier,
                "expected_revision": runner.get(identifier)["revision"],
            },
            headers=headers,
        ).status_code
        == 409
    )


def test_changed_allocation_spec_cannot_reuse_an_operation_key(engine):
    runner, store, _ = engine
    intent = OperationIntent(
        operation_id=str(uuid4()),
        kind="provision",
        target="test-one",
        expected_revision=0,
        reason="Fresh synthetic test",
    )
    runner.reserve(
        intent,
        [Reservation(kind="port", identity="8101")],
        identity(store),
        admit_check=lambda *_: None,
    )
    with pytest.raises(AdminError, match="command_conflict"):
        runner.reserve(
            intent,
            [Reservation(kind="port", identity="8102")],
            identity(store),
            admit_check=lambda *_: None,
        )


def test_safe_checkpoint_projection_refuses_provider_payload_and_keeps_private_error_out(engine):
    runner, store, _ = engine
    identifier = admitted(store)
    effects = Effects()
    effects.observed["source_command"] = Observation(
        "verified", {"private_sdk_response": "secret/provider/path"}
    )
    with pytest.raises(AdminError, match="result_invalid"):
        runner.run(identifier, effects)
    status = runner.get(identifier)
    assert status["state"] == "failed"
    assert "secret/provider/path" not in str(status)


def test_recent_operations_have_a_fixed_bounded_projection(engine):
    runner, store, _ = engine
    for index in range(5):
        admitted(store, instance=f"test-{index}")
    assert len(runner.recent(identity(store)["id"], 2)["items"]) == 2
    with pytest.raises(AdminError, match="limit_invalid"):
        runner.recent(identity(store)["id"], 101)


def test_private_safe_stop_requires_reviewed_revision_and_verifies_containment(engine):
    from app.modules.hosted_admin.infrastructure.private_operations import PrivateOperations

    runner, store, _ = engine
    identifier = admitted(store)
    effects = Effects()
    private = PrivateOperations(store, None, effects)
    with pytest.raises(ValueError):
        private.handle({"action": "operation-stop", "identifier": identifier})
    result = private.handle(
        {
            "action": "operation-stop",
            "identifier": identifier,
            "expected_revision": runner.get(identifier)["revision"],
        }
    )
    assert result["state"] == "cancelled" and effects.contained


def test_external_manual_handoff_waits_without_replaying_or_mutating(engine):
    runner, store, _ = engine
    identifier = admitted(store)
    effects = Effects()
    effects.observed["source_command"] = Observation("waiting")
    with pytest.raises(AdminError, match="reconciliation_required"):
        runner.run(identifier, effects)
    assert not effects.calls
    status = runner.get(identifier)
    assert status["state"] == "waiting" and status["error"] == "admin_external_setup_required"

"""Storage effects are internal, explicitly authorized and source/operation bound."""

import json
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.modules.hosted_admin.tests.test_storage_allocations import storage as storage, admit
from app.modules.hosted_admin.tests.test_authority import authority as authority, login
from app.modules.hosted_admin.application.contracts import AdminError, BrokerRequest
from app.modules.hosted_admin.application.storage import (
    StorageCommand,
    StorageProof,
    ProjectUsage,
    canonical_storage,
    storage_fingerprint,
)
from app.modules.hosted_admin.infrastructure.storage_lifecycle import StorageLifecycle
from app.modules.hosted_admin.infrastructure.control_recovery import (
    validate_control,
    snapshot_control,
    restore_control,
)
from app.modules.hosted_admin.infrastructure.authority import AuthorityStore
from app.modules.hosted_admin.infrastructure.storage_queries import PENDING_STORAGE


def command(operation, action, revision):
    return StorageCommand(
        id=str(uuid4()),
        operation_id=operation,
        action=action,
        expected_revision=revision,
        reason="Explicit test review",
    )


def proof(service, cmd, request):
    policy = request["policy"]
    cleanup = cmd.action == "finish_retirement"
    return StorageProof(
        operation_id=cmd.operation_id,
        policy_digest=storage_fingerprint(policy),
        observed=service.store.clock(),
        projects=tuple(
            ProjectUsage(
                project_id=p["project_id"],
                directory_inode=p["directory_inode"],
                hard_bytes=p["hard_bytes"],
                hard_inodes=p["hard_inodes"],
                allocated_bytes=0 if cleanup else 4096,
                allocated_inodes=0 if cleanup else 1,
                enforcement=not cleanup,
            )
            for p in policy["projects"]
        ),
        cleanup_verified=cleanup,
        no_open_files=cleanup,
        directories_absent=cleanup,
    )


def run(lifecycle, cmd, identity):
    return lifecycle.command(cmd, identity, lifecycle.store.issue(cmd.fingerprint()))


def test_complete_lifecycle_original_receipts_and_restored_reservations(storage, tmp_path):
    store, service, identity, request, _ = storage
    reservation = request()
    original = admit(service, reservation, identity)
    assert service.inspect("a", identity)["allocated_bytes"] is None
    effects = Mock(side_effect=lambda cmd, req: proof(service, cmd, req))
    lifecycle = StorageLifecycle(service, effects)
    apply = command(reservation.id, "apply", 1)
    active = run(lifecycle, apply, identity)
    assert active["state"] == "active" and active["revision"] == 2
    assert service.inspect("a", identity)["allocated_bytes"] == 12288
    run(lifecycle, command(reservation.id, "retire", 2), identity)
    retired = run(lifecycle, command(reservation.id, "finish_retirement", 3), identity)
    assert retired["state"] == "retired" and retired["revision"] == 4
    assert lifecycle.command(apply, identity, "") == active
    service.collect.side_effect = OSError("offline")
    assert admit(service, reservation, identity) == original
    with store.transaction() as connection:
        validate_control(connection)
        assert connection.execute("SELECT count(*) FROM storage_project").fetchone()[0] == 3
    restored = AuthorityStore.initialize(tmp_path / "restored" / "control.sqlite", identity["id"])
    restore_control(restored, snapshot_control(store))
    with restored.transaction() as connection:
        validate_control(connection)
        assert connection.execute("SELECT state FROM storage_allocation").fetchone()[0] == "retired"
        assert not connection.execute("SELECT enabled FROM administrator").fetchone()[0]


def test_uncertain_effect_retries_original_authorization_once(storage):
    store, service, identity, request, _ = storage
    reservation = request()
    admit(service, reservation, identity)
    effects = Mock(
        side_effect=[
            OSError("lost reply"),
            proof(
                service, command(reservation.id, "apply", 1), reservation.model_dump(mode="json")
            ),
        ]
    )
    lifecycle = StorageLifecycle(service, effects)
    cmd = command(reservation.id, "apply", 1)
    with pytest.raises(OSError):
        run(lifecycle, cmd, identity)
    with store.transaction() as connection:
        assert (
            connection.execute("SELECT count(*) FROM (" + PENDING_STORAGE + ")").fetchone()[0] == 1
        )
        validate_control(connection)
    result = lifecycle.command(cmd, identity, "")
    assert result["state"] == "active"
    assert lifecycle.command(cmd, identity, "") == result
    assert effects.call_count == 2
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM storage_attempt").fetchone()[0] == 1
        validate_control(connection)


def test_fresh_reconciliation_resolves_uncertain_effect_without_erasing_attempt(storage):
    store, service, identity, request, _ = storage
    reservation = request()
    admit(service, reservation, identity)
    effects = Mock(side_effect=OSError("uncertain"))
    lifecycle = StorageLifecycle(service, effects)
    with pytest.raises(OSError):
        run(lifecycle, command(reservation.id, "apply", 1), identity)
    with pytest.raises(AdminError, match="reconciliation_required"):
        run(lifecycle, command(reservation.id, "retire", 1), identity)
    effects.side_effect = lambda cmd, req: proof(service, cmd, req)
    run(lifecycle, command(reservation.id, "reconcile", 1), identity)
    run(lifecycle, command(reservation.id, "retire", 2), identity)
    with store.transaction() as connection:
        assert not connection.execute("SELECT * FROM (" + PENDING_STORAGE + ")").fetchall()
        assert connection.execute("SELECT count(*) FROM storage_attempt").fetchone()[0] == 3
        validate_control(connection)


def test_cleanup_needs_zero_usage_and_verified_absence(storage):
    store, service, identity, request, _ = storage
    reservation = request()
    admit(service, reservation, identity)
    effects = Mock(side_effect=lambda cmd, req: proof(service, cmd, req))
    lifecycle = StorageLifecycle(service, effects)
    run(lifecycle, command(reservation.id, "retire", 1), identity)
    cmd = command(reservation.id, "finish_retirement", 2)
    effects.side_effect = lambda c, r: proof(service, c, r).model_copy(
        update={"no_open_files": False}
    )
    with pytest.raises(AdminError, match="proof_invalid"):
        run(lifecycle, cmd, identity)
    with store.transaction() as connection:
        assert (
            connection.execute("SELECT state FROM storage_allocation").fetchone()[0] == "retiring"
        )
    effects.side_effect = lambda c, r: proof(service, c, r)
    assert lifecycle.command(cmd, identity, "")["state"] == "retired"


def test_revocation_during_effect_keeps_original_attempt_and_does_not_commit(storage):
    store, service, identity, request, _ = storage
    reservation = request()
    admit(service, reservation, identity)

    def effect(cmd, req):
        store.revoke_identity()
        return proof(service, cmd, req)

    lifecycle = StorageLifecycle(service, effect)
    with pytest.raises(AdminError, match="revoked"):
        run(lifecycle, command(reservation.id, "apply", 1), identity)
    with store.transaction() as connection:
        assert (
            connection.execute("SELECT state FROM storage_allocation").fetchone()[0] == "reserved"
        )
        validate_control(connection)


@pytest.mark.parametrize("bad", ["request", "result", "proof"])
def test_rewritten_lifecycle_is_rejected_on_restore(storage, tmp_path, bad):
    store, service, identity, request, _ = storage
    reservation = request()
    admit(service, reservation, identity)
    lifecycle = StorageLifecycle(service, lambda c, r: proof(service, c, r))
    run(lifecycle, command(reservation.id, "apply", 1), identity)
    snapshot = json.loads(snapshot_control(store))
    snapshot["tables"]["storage_command"][0][bad] = "{}"
    restored = AuthorityStore.initialize(tmp_path / "bad" / "control.sqlite", identity["id"])
    with pytest.raises(AdminError, match="storage_data_invalid"):
        restore_control(restored, canonical_storage(snapshot).encode())
    with restored.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM storage_allocation").fetchone()[0] == 0


def test_broker_requires_session_csrf_and_action_bound_credential(storage):
    store, service, identity, request, _ = storage
    reservation = request()
    admit(service, reservation, identity)
    effects = Mock()
    lifecycle = StorageLifecycle(service, effects)
    dispatch = Mock()
    dispatch.storage.command = lifecycle.command
    cmd = command(reservation.id, "apply", 1)
    with pytest.raises(AdminError, match="session_expired"):
        store.handle(BrokerRequest(method="storage_apply", storage=cmd), dispatch)
    credentials = login(store)
    with pytest.raises(AdminError, match="csrf_invalid"):
        store.handle(
            BrokerRequest(method="storage_apply", storage=cmd, token=credentials["token"]), dispatch
        )
    with pytest.raises(AdminError, match="grant"):
        store.handle(BrokerRequest(method="storage_apply", storage=cmd, **credentials), dispatch)
    effects.assert_not_called()
    with pytest.raises(ValueError):
        BrokerRequest.model_validate(
            dict(
                method="storage_apply", storage=cmd.model_dump() | {"project_id": 1}, **credentials
            )
        )


def test_uncertain_storage_effect_blocks_release_admission(storage):
    from app.modules.hosted_admin.infrastructure.operations import enqueue

    store, service, identity, request, _ = storage
    reservation = request()
    admit(service, reservation, identity)
    lifecycle = StorageLifecycle(service, Mock(side_effect=OSError("uncertain effect")))
    with pytest.raises(OSError):
        run(lifecycle, command(reservation.id, "apply", 1), identity)
    with store.transaction() as connection:
        with pytest.raises(AdminError, match="storage_upgrade_conflict"):
            enqueue(
                connection,
                store,
                identifier=str(uuid4()),
                identity=identity,
                kind="upgrade",
                target="a",
                payload={"release_id": "next"},
            )
        assert connection.execute("SELECT count(*) FROM operation").fetchone()[0] == 0


def test_queued_release_blocks_quota_effect_without_spending_grant(storage):
    from app.modules.hosted_admin.infrastructure.operations import enqueue

    store, service, identity, request, _ = storage
    reservation = request()
    admit(service, reservation, identity)
    with store.transaction() as connection:
        enqueue(
            connection,
            store,
            identifier=str(uuid4()),
            identity=identity,
            kind="upgrade",
            target="a",
            payload={"release_id": "next"},
        )
    effects = Mock()
    lifecycle = StorageLifecycle(service, effects)
    with pytest.raises(AdminError, match="storage_upgrade_conflict"):
        run(lifecycle, command(reservation.id, "apply", 1), identity)
    effects.assert_not_called()
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM storage_attempt").fetchone()[0] == 0

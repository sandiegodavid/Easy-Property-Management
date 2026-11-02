"""Protected reservation foundations; test profiles are not deployment grants."""

from uuid import uuid4
from unittest.mock import Mock

import pytest

from app.modules.hosted_access.application.storage_policy import (
    ProjectCeiling,
    ProjectIdentity,
    StoragePolicy,
    TierProfile,
)
from app.modules.hosted_admin.application.storage import (
    HostStorageFacts,
    StorageReservation,
    BindingCheck,
    ProfileEvidence,
    StorageAuthority,
    storage_fingerprint,
)
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.infrastructure.storage_allocations import StorageAllocations
from app.modules.hosted_admin.infrastructure.control_recovery import validate_control
from app.modules.hosted_admin.infrastructure.control_recovery import (
    snapshot_control,
    restore_control,
)
from app.modules.hosted_admin.infrastructure.authority import AuthorityStore
from app.modules.hosted_admin.tests.test_authority import authority as authority


def admit(service, command, identity):
    return service.reserve(command, identity, service.store.issue(command.fingerprint()))


@pytest.fixture
def storage(authority):
    store, clock = authority
    filesystem = str(uuid4())
    facts = HostStorageFacts(
        filesystem_uuid=filesystem,
        observed=clock[0],
        total_bytes=1024**3,
        free_bytes=900 * 1024**2,
        free_inodes=100000,
        recovery_required=64 * 1024**2,
        shared_overhead=1024**2,
        retained_image_growth=0,
        administrative_growth=1024**2,
        enforcement=True,
        environment_hash="f" * 64,
    )
    evidence = Mock()
    binding = Mock(
        side_effect=lambda command: BindingCheck(
            policy_digest=storage_fingerprint(command.policy.model_dump(mode="json")),
            authority=command.authority,
            release_digest="a" * 64,
            sandbox_digest="b" * 64,
        )
    )
    service = StorageAllocations(store, Mock(return_value=facts), binding, evidence)
    profile = TierProfile(
        id="test-only",
        revision=1,
        tier="50mb",
        release_digest="a" * 64,
        sandbox_digest="b" * 64,
        qualified=True,
        workspace=ProjectCeiling(hard_bytes=64 * 1024**2, hard_inodes=1000),
        scratch=ProjectCeiling(hard_bytes=16 * 1024**2, hard_inodes=1000),
        control=ProjectCeiling(hard_bytes=4 * 1024**2, hard_inodes=1000),
        max_transaction_bytes=1024**2,
        max_concurrency=1,
        measurement_digest="c" * 64,
        qualification_digest="d" * 64,
    )
    evidence.return_value = ProfileEvidence(
        artifact_id=str(uuid4()),
        profile_digest=storage_fingerprint(profile.model_dump(mode="json")),
        environment_hash="f" * 64,
        observed=clock[0],
        expires=clock[0] + 1000,
    )
    digest = service.register_profile(profile)
    with store.transaction() as connection:
        identity = dict(store._identity(connection))

    def request(instance="a", start=1001):
        operation = str(uuid4())
        projects = tuple(
            ProjectIdentity(
                role=role,
                directory=f"/var/lib/data/{instance}-{role}",
                directory_inode=start + i,
                project_id=start + i,
                uid=1000,
                **getattr(profile, role).model_dump(),
            )
            for i, role in enumerate(("workspace", "scratch", "control"))
        )
        policy = StoragePolicy(
            backend="project_quota",
            instance=instance,
            workspace_id=str(uuid4()),
            operator_id=str(uuid4()),
            filesystem_uuid=filesystem,
            policy_revision=1,
            tier="50mb",
            allowance_bytes=50_000_000,
            profile_id=profile.id,
            profile_digest=digest,
            projects=projects,
            operation_id=operation,
        )
        return StorageReservation(
            id=operation,
            expected_revision=0,
            policy=policy,
            reason="Test admission",
            recovery_reference="e" * 64,
            authority=StorageAuthority(
                inventory_revision=1, binding_revision=1, admin_revision=1, fence=0
            ),
        )

    return store, service, identity, request, facts


def test_reservation_atomicity_safe_view_and_replay_without_collector(storage):
    store, service, identity, request, _ = storage
    command = request()
    result = admit(service, command, identity)
    assert result["allowance_bytes"] == 50_000_000 and result["state"] == "reserved"
    assert not {"projects", "filesystem_uuid", "directory", "uid"} & result.keys()
    service.collect.side_effect = OSError("offline")
    assert admit(service, command, identity) == result
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM storage_project").fetchone()[0] == 3
        validate_control(connection)


def test_duplicate_project_rollback_leaves_no_partial_allocation(storage):
    store, service, identity, request, _ = storage
    admit(service, request(), identity)
    with pytest.raises(AdminError, match="identity_conflict"):
        admit(service, request("b"), identity)
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM storage_allocation").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM storage_event").fetchone()[0] == 1
        validate_control(connection)


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"free_bytes": 10 * 1024**2}, "capacity_exhausted"),
        ({"free_inodes": 1}, "capacity_exhausted"),
        ({"enforcement": False}, "observation_unavailable"),
        ({"observed": 0.0}, "observation_unavailable"),
    ],
)
def test_unknown_or_exhausted_capacity_cannot_reserve(storage, changes, code):
    store, service, identity, request, facts = storage
    service.collect.return_value = facts.model_copy(update=changes)
    with pytest.raises(AdminError, match=code):
        admit(service, request(), identity)
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM storage_project").fetchone()[0] == 0


def test_changed_retry_and_revoked_authority_fail_closed(storage):
    store, service, identity, request, _ = storage
    command = request()
    admit(service, command, identity)
    with pytest.raises(AdminError, match="intent_conflict"):
        admit(service, command.model_copy(update={"reason": "Changed"}), identity)
    store.revoke_identity()
    with pytest.raises(AdminError, match="revoked"):
        admit(service, request("b", 2001), identity)


def test_unmeasured_tier_profiles_have_no_invented_ceilings():
    candidate = TierProfile(
        id="pending", revision=1, tier="50mb", release_digest="a" * 64, sandbox_digest="b" * 64
    )
    assert not candidate.qualified and candidate.workspace is None and candidate.scratch is None
    with pytest.raises(ValueError):
        TierProfile(**(candidate.model_dump() | {"qualified": True}))


@pytest.mark.parametrize("tamper", [False, True])
def test_reserved_identities_roundtrip_or_reject_changed_mapping(storage, tmp_path, tamper):
    import json

    store, service, identity, request, _ = storage
    admit(service, request(), identity)
    encoded = snapshot_control(store)
    restored = AuthorityStore.initialize(tmp_path / "restored" / "authority.sqlite", identity["id"])
    if tamper:
        value = json.loads(encoded)
        value["tables"]["storage_project"][0]["hard_bytes"] += 1024
        with pytest.raises(AdminError, match="storage_data_invalid"):
            restore_control(restored, json.dumps(value).encode())
        with restored.transaction() as connection:
            assert connection.execute("SELECT count(*) FROM storage_project").fetchone()[0] == 0
    else:
        restore_control(restored, encoded)
        with restored.transaction() as connection:
            assert connection.execute("SELECT count(*) FROM storage_project").fetchone()[0] == 3
            assert connection.execute("SELECT enabled FROM administrator").fetchone()[0] == 0
            validate_control(connection)


def test_concurrent_duplicate_admission_has_one_complete_reservation(storage):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    store, service, identity, request, facts = storage
    barrier = Barrier(2)

    def collect(_):
        barrier.wait(timeout=5)
        return facts

    service.collect.side_effect = collect
    commands = [request(), request()]
    grants = [store.issue(c.fingerprint()) for c in commands]

    def reserve(index):
        try:
            return service.reserve(commands[index], identity, grants[index])["state"]
        except AdminError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, range(2)))
    assert sorted(results) == ["admin_storage_identity_conflict", "reserved"]
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM storage_project").fetchone()[0] == 3
        validate_control(connection)


def test_failed_insert_rolls_back_ids_capacity_audit_and_grant(storage):
    store, service, identity, request, _ = storage
    cmd = request()
    grant = store.issue(cmd.fingerprint())
    with store.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER abort_storage_test BEFORE INSERT ON storage_project WHEN NEW.role='scratch' BEGIN SELECT RAISE(ABORT,'injected'); END"
        )
    with pytest.raises(AdminError, match="identity_conflict"):
        service.reserve(cmd, identity, grant)
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM storage_project").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT count(*) FROM audit WHERE action='storage_reserved'"
            ).fetchone()[0]
            == 0
        )
        connection.execute("DROP TRIGGER abort_storage_test")
    assert service.reserve(cmd, identity, grant)["state"] == "reserved"


def test_cross_allocation_nested_paths_and_changed_binding_fail(storage):
    store, service, identity, request, _ = storage
    admit(service, request(), identity)
    cmd = request("b", 2001)
    data = cmd.policy.model_dump(mode="json")
    data["projects"][0]["directory"] = "/var/lib/data/a-workspace/nested"
    cmd = cmd.model_copy(
        update={"policy": StoragePolicy.model_validate_json(__import__("json").dumps(data))}
    )
    with pytest.raises(AdminError, match="identity_conflict"):
        admit(service, cmd, identity)
    fresh = request("b", 2001)
    original = service.bindings.side_effect
    service.bindings.side_effect = lambda c: original(c).model_copy(
        update={"policy_digest": "0" * 64}
    )
    with pytest.raises(AdminError, match="binding_changed"):
        admit(service, fresh, identity)


def test_aggregate_growth_does_not_double_count_occupied_bytes(storage):
    from app.modules.hosted_admin.application.storage import ProjectUsage

    store, service, identity, request, facts = storage
    first = request()
    admit(service, first, identity)
    usage = tuple(
        ProjectUsage(
            project_id=p.project_id,
            directory_inode=p.directory_inode,
            hard_bytes=p.hard_bytes,
            hard_inodes=p.hard_inodes,
            allocated_bytes=p.hard_bytes,
            allocated_inodes=p.hard_inodes,
            enforcement=True,
        )
        for p in first.policy.projects
    )
    # Existing occupied bytes are already absent from free_bytes. Only the NEW
    # allocation's ceilings are subtracted; equality at host headroom is valid.
    ceiling = sum(p.hard_bytes for p in first.policy.projects)
    reserve = (facts.total_bytes + 4) // 5
    service.collect.return_value = facts.model_copy(
        update={
            "projects": usage,
            "free_bytes": reserve + ceiling + facts.shared_overhead + facts.administrative_growth,
        }
    )
    assert admit(service, request("b", 2001), identity)["state"] == "reserved"


@pytest.mark.parametrize("count", [1, 10, 50])
def test_safe_inspection_has_constant_queries_and_no_collector_calls(storage, count, monkeypatch):
    from contextlib import contextmanager

    store, service, identity, request, facts = storage
    service.collect.return_value = facts.model_copy(
        update={"total_bytes": 64 * 1024**3, "free_bytes": 60 * 1024**3, "free_inodes": 1000000}
    )
    for index in range(count):
        admit(service, request(f"x{index}", 1001 + index * 3), identity)
    statements = []
    transaction = store.transaction

    @contextmanager
    def counted():
        with transaction() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(store, "transaction", counted)
    service.collect.side_effect = AssertionError("Inspection must not collect")
    result = service.inspect("x0", identity)
    assert result["state"] == "unknown" and result["allocated_bytes"] is None
    assert len([s for s in statements if s.startswith("SELECT")]) == 3

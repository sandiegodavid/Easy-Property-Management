"""Source/configuration and protected host storage proof integration."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.modules.hosted_access.application.configuration import (
    HostedDeployment,
    HostedConfigurationError,
)
from app.modules.hosted_access.application.storage_policy import TierProfile
from app.modules.hosted_access.infrastructure.storage_budget import validate_storage_volume
from app.modules.hosted_admin.tests.test_storage_allocations import storage as storage, admit
from app.modules.hosted_admin.tests.test_authority import authority as authority
from app.modules.hosted_access.tests.conftest import deployment_values as deployment_values
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.storage import (
    ProfileReport,
    canonical_storage,
    StorageCommand,
)
from app.modules.hosted_admin.infrastructure.storage_host import StorageHost
from scripts.tests.test_host_inventory import instance, inventory as inventory


def project_instance(policy):
    projects = {p.role: p for p in policy.projects}
    return replace(
        instance(policy.instance),
        workspace_id=policy.workspace_id,
        operator_id=policy.operator_id,
        mount="/var/lib/data",
        image=None,
        workspace=projects["workspace"].directory,
        access_database=projects["control"].directory + "/access.sqlite",
        storage_backend="project_quota",
        storage_policy=canonical_storage(policy.model_dump(mode="json")),
    )


def test_project_policy_matches_inventory_and_source_but_cannot_enable_growth(
    storage, inventory, deployment_values
):
    _, _, _, request, _ = storage
    policy = request().policy
    item = project_instance(policy)
    inventory.register(item)
    assert inventory.get(item.key) == item
    projects = {p.role: p for p in policy.projects}
    values = deployment_values | dict(
        workspace_id=policy.workspace_id,
        operator_id=policy.operator_id,
        storage_backend="project_quota",
        storage_image=None,
        storage_volume=Path(item.mount),
        storage_policy=policy,
        administration_database=Path(item.access_database),
    )
    deployment = HostedDeployment.model_validate(values)
    with pytest.raises(HostedConfigurationError, match="source-accounting"):
        validate_storage_volume(deployment, Path(item.workspace))
    with pytest.raises(ValueError):
        HostedDeployment.model_validate(
            values
            | {"administration_database": Path(projects["workspace"].directory) / "access.sqlite"}
        )
    with pytest.raises(ValueError):
        HostedDeployment.model_validate(values | {"workspace_id": str(uuid4())})
    with pytest.raises(ValueError):
        HostedDeployment.model_validate(values | {"storage_image": Path("/var/lib/old.img")})


def test_shared_mount_supports_distinct_registered_project_trees(storage, inventory):
    _, _, _, request, _ = storage
    one = project_instance(request().policy)
    two = project_instance(request("b", 2001).policy)
    inventory.register(one)
    inventory.register(two)
    assert len(inventory.list()) == 2
    assert all(item.storage_backend == "project_quota" for item in inventory.list())


def test_signed_profile_lookup_checks_identity_environment_and_freshness(storage):
    store, service, _, _, _ = storage
    with store.transaction() as connection:
        profile = TierProfile.model_validate_json(
            connection.execute("SELECT payload FROM storage_profile").fetchone()[0]
        )
    evidence = service.profile_evidence.return_value
    report = ProfileReport(kind="storage_profile", profile=profile, **evidence.model_dump())
    reports = Mock()
    reports.report.return_value = report.model_dump(mode="json")
    reports.snapshot.return_value = SimpleNamespace(environment_hash="f" * 64)
    host = StorageHost(store, Mock(), reports)
    host.settings = Mock(return_value=SimpleNamespace(profiles={profile.id: evidence.artifact_id}))
    assert host.evidence(profile, None) == evidence.model_dump()
    reports.snapshot.return_value = SimpleNamespace(environment_hash="0" * 64)
    with pytest.raises(AdminError, match="profile_unavailable"):
        host.evidence(profile, None)
    reports.snapshot.return_value = SimpleNamespace(environment_hash="f" * 64)
    reports.report.return_value = report.model_dump(mode="json") | {"profile_digest": "0" * 64}
    with pytest.raises(ValueError):
        host.evidence(profile, None)


def test_no_owned_source_gate_means_no_kernel_mutation(storage):
    store, service, identity, request, _ = storage
    reservation = request()
    admit(service, reservation, identity)
    platform = Mock()
    platform.h.source._transport.return_value = {"owner": str(uuid4())}
    host = StorageHost(store, platform, Mock())
    host.registered = Mock(return_value=project_instance(reservation.policy))
    host.binding = Mock()
    host.profile = Mock()
    host.probe = Mock()
    cmd = StorageCommand(
        id=str(uuid4()),
        operation_id=reservation.id,
        expected_revision=1,
        action="apply",
        reason="Owned effect only",
    )
    with pytest.raises(AdminError, match="owned_gate_required"):
        host.effects(cmd, reservation.model_dump(mode="json"))
    host.probe.assert_not_called()


@pytest.mark.parametrize("conflict", ["nested", "project_id", "filesystem"])
def test_inventory_rejects_conflicting_storage_before_committing(storage, inventory, conflict):
    from scripts.host_inventory import InventoryError

    _, _, _, request, _ = storage
    first = request().policy
    second = request("b", 2001).policy
    if conflict == "nested":
        second = second.model_copy(
            update={
                "projects": tuple(
                    p.model_copy(update={"directory": first.projects[0].directory + "/" + p.role})
                    for p in second.projects
                )
            }
        )
    elif conflict == "project_id":
        second = second.model_copy(
            update={
                "projects": tuple(
                    p.model_copy(update={"project_id": first.projects[i].project_id})
                    for i, p in enumerate(second.projects)
                )
            }
        )
    else:
        second = second.model_copy(update={"filesystem_uuid": str(uuid4())})
    inventory.register(project_instance(first))
    with pytest.raises(InventoryError):
        inventory.register(project_instance(second))
    assert len(inventory.list()) == 1


def test_retained_inventory_rejects_cross_allocation_nested_directories(storage, inventory):
    from scripts.host_inventory import InventoryError

    _, _, _, request, _ = storage
    first = request().policy
    second = request("b", 2001).policy
    inventory.register(project_instance(first))
    inventory.register(project_instance(second))
    second = second.model_copy(
        update={
            "projects": tuple(
                p.model_copy(update={"directory": first.projects[0].directory + "/" + p.role})
                for p in second.projects
            )
        }
    )
    replacement = project_instance(second)
    with inventory.connection(writable=True) as connection:
        connection.execute(
            "UPDATE instances SET storage_policy=?,workspace=?,access_database=? WHERE key='b'",
            (replacement.storage_policy, replacement.workspace, replacement.access_database),
        )
    with pytest.raises(InventoryError, match="overlap"):
        inventory.list()


def test_root_adapter_applies_and_retires_exact_admitted_policy(storage, monkeypatch):
    from contextlib import nullcontext
    from app.modules.hosted_admin.application.storage import CleanupReport, storage_fingerprint
    from app.modules.hosted_admin.infrastructure.project_quota import DiskQuota
    from app.modules.hosted_admin.infrastructure.storage_lifecycle import StorageLifecycle
    from app.modules.hosted_admin.tests.test_storage_lifecycle import command, proof, run
    from app.modules.hosted_admin.infrastructure.control_recovery import validate_control

    store, allocations, identity, request, _ = storage
    reservation = request()
    admit(allocations, reservation, identity)
    item = project_instance(reservation.policy)
    platform, reports = Mock(), Mock()
    platform.h.inventory.get.return_value = item
    platform.h.source._transport.return_value = {"owner": reservation.id}
    host = StorageHost(store, platform, reports)
    host.registered = Mock(return_value=item)
    host.binding = Mock()
    host.profile = Mock()
    host.effect_lock = lambda: nullcontext()
    probes = {p.project_id: Mock() for p in reservation.policy.projects}
    host.probe = lambda policy, project: probes[project.project_id]
    original = reservation.model_dump(mode="json")
    apply = command(reservation.id, "apply", 1)
    observations = proof(allocations, apply, original)
    host.usage = Mock(
        side_effect=lambda policy, p: next(
            usage for usage in observations.projects if usage.project_id == p.project_id
        )
    )
    host.initial_usage = host.usage
    lifecycle = StorageLifecycle(allocations, host.effects)
    assert run(lifecycle, apply, identity)["state"] == "active"
    for project in reservation.policy.projects:
        probes[project.project_id].set_limits.assert_called_once_with(
            project.hard_bytes, project.hard_inodes
        )
    assert lifecycle.command(apply, identity, "")["state"] == "active"
    run(lifecycle, command(reservation.id, "retire", 2), identity)
    cleanup = command(reservation.id, "finish_retirement", 3)
    report = CleanupReport(
        kind="storage_cleanup",
        command_fingerprint=cleanup.fingerprint(),
        inventory_revision=item.revision,
        expires=store.clock() + 100,
        **proof(allocations, cleanup, original).model_dump(),
    )
    assert report.policy_digest == storage_fingerprint(original["policy"])
    reports.report.return_value = report.model_dump(mode="json")
    for probe in probes.values():
        probe._control.return_value = DiskQuota()
    monkeypatch.setattr("os.path.lexists", lambda path: False)
    assert run(lifecycle, cleanup, identity)["state"] == "retired"
    with store.transaction() as connection:
        validate_control(connection)
        assert connection.execute("SELECT count(*) FROM storage_project").fetchone()[0] == 3
    reports.report.assert_called_once_with(cleanup.id)


def test_root_adapter_rejects_cleanup_report_that_expires_during_observation(storage, monkeypatch):
    from app.modules.hosted_admin.application.storage import CleanupReport
    from app.modules.hosted_admin.infrastructure.project_quota import DiskQuota
    from app.modules.hosted_admin.tests.test_storage_lifecycle import command, proof

    store, allocations, _, request, _ = storage
    reservation = request()
    cleanup = command(reservation.id, "finish_retirement", 3)
    item = project_instance(reservation.policy)
    host = StorageHost(store, Mock(), Mock())
    host.registered = Mock(return_value=item)
    host.reports.report.return_value = CleanupReport(
        kind="storage_cleanup",
        command_fingerprint=cleanup.fingerprint(),
        inventory_revision=item.revision,
        expires=store.clock() + 1,
        **proof(allocations, cleanup, reservation.model_dump(mode="json")).model_dump(),
    ).model_dump(mode="json")
    probe = Mock()

    def observe(*args):
        store.clock = lambda: 2000.0
        return DiskQuota()

    probe._control.side_effect = observe
    host.probe = Mock(return_value=probe)
    monkeypatch.setattr("os.path.lexists", lambda path: False)
    with pytest.raises(AdminError, match="cleanup_unverified"):
        host.effects(cleanup, reservation.model_dump(mode="json"))


def test_private_json_commands_consume_exact_storage_grants(storage):
    from app.modules.hosted_admin.infrastructure.private_operations import PrivateOperations
    from app.modules.hosted_admin.infrastructure.storage_service import StorageService
    from app.modules.hosted_admin.tests.test_storage_lifecycle import command, proof

    store, allocations, identity, request, _ = storage
    host = Mock()
    host.collect = allocations.collect
    host.binding = allocations.bindings
    host.evidence = allocations.profile_evidence
    host.effects.side_effect = lambda cmd, req: proof(allocations, cmd, req)
    service = StorageService(store, host)
    private = PrivateOperations(store, None, SimpleNamespace(storage=service))
    reservation = request()
    body = {"storage_reservation": reservation.model_dump(mode="json")}
    credential = private.handle({"action": "storage-grant", **body})["credential"]
    assert (
        private.handle({"action": "storage-reserve", **body, "credential": credential})["state"]
        == "reserved"
    )
    apply = command(reservation.id, "apply", 1)
    body = {"storage": apply.model_dump(mode="json")}
    credential = private.handle({"action": "storage-grant", **body})["credential"]
    assert (
        private.handle({"action": "storage-command", **body, "credential": credential})["state"]
        == "active"
    )
    assert service.inspect("a", identity)["state"] == "available"


@pytest.mark.parametrize("root_mount", [False, True])
def test_project_root_filesystem_contracts_round_trip(
    storage, inventory, deployment_values, root_mount
):
    from app.modules.hosted_admin.application.storage import FilesystemBudget
    from app.modules.hosted_access.application.storage_policy import ProjectIdentity

    _, _, _, request, _ = storage
    policy = request().policy
    item = replace(project_instance(policy), mount="/" if root_mount else "/var/lib/data")
    inventory.register(item)
    assert inventory.get("a") == item
    values = deployment_values | dict(
        workspace_id=policy.workspace_id,
        operator_id=policy.operator_id,
        storage_backend="project_quota",
        storage_image=None,
        storage_volume=Path(item.mount),
        storage_policy=policy,
        administration_database=Path(item.access_database),
    )
    deployment = HostedDeployment.model_validate_json(
        HostedDeployment.model_validate(values).model_dump_json()
    )
    assert str(deployment.storage_volume) == item.mount
    assert (
        FilesystemBudget(
            filesystem_uuid=policy.filesystem_uuid,
            mount=item.mount,
            recovery_required=0,
            shared_overhead=0,
            retained_image_growth=0,
            administrative_growth=0,
            administrative_inodes=0,
        ).mount
        == item.mount
    )
    with pytest.raises(ValueError):
        ProjectIdentity.model_validate(policy.projects[0].model_dump() | {"directory": "/"})
    with pytest.raises(ValueError):
        replace(instance("b"), mount="/", workspace="/business").validate()
    for field in ("workspace", "local_config", "access_database"):
        with pytest.raises(ValueError):
            replace(item, **{field: "/"}).validate()
    with pytest.raises(ValueError):
        HostedDeployment.model_validate(deployment_values | {"storage_volume": Path("/")})


@pytest.mark.parametrize("resource", ["bytes", "inodes"])
def test_reclamation_between_quota_and_free_space_cannot_spend_reserves(
    storage, monkeypatch, resource
):
    from app.modules.hosted_admin.application.storage import FilesystemBudget, ProjectUsage

    store, allocations, identity, request, facts = storage
    first = request()
    admit(allocations, first, identity)
    budget = FilesystemBudget(
        **facts.model_dump(
            include={
                "filesystem_uuid",
                "recovery_required",
                "shared_overhead",
                "retained_image_growth",
                "administrative_growth",
                "administrative_inodes",
            }
        ),
        mount="/var/lib/data",
    )
    host = StorageHost(store, Mock(), Mock())
    host.budget = Mock(return_value=budget)
    host.reports.snapshot.return_value = SimpleNamespace(environment_hash=facts.environment_hash)
    monkeypatch.setattr("app.modules.hosted_admin.infrastructure.storage_host.ProjectQuota", Mock())
    observed = []

    def usage(policy, project):
        observed.append(project.project_id)
        return ProjectUsage(
            project_id=project.project_id,
            directory_inode=project.directory_inode,
            hard_bytes=0,
            hard_inodes=0,
            enforcement=True,
            allocated_bytes=60 * 1024**2 if project.role == "workspace" else 0,
            allocated_inodes=900 if project.role == "workspace" else 0,
        )

    host.initial_usage = usage
    hard = sum(p.hard_bytes for p in first.policy.projects)
    reserve = (facts.total_bytes + 4) // 5

    def after_cleanup(path):
        assert len(observed) == 3
        # Workspace now occupies only 20 MiB / 100 inodes. statvfs already sees
        # the freed 40 MiB / 800 inodes, but the earlier quota samples do not.
        return SimpleNamespace(
            f_blocks=facts.total_bytes,
            f_frsize=1,
            f_bavail=(
                reserve
                + hard * 2
                - 40 * 1024**2
                + facts.shared_overhead
                + facts.administrative_growth
            )
            if resource == "bytes"
            else facts.free_bytes,
            f_favail=5500 if resource == "inodes" else facts.free_inodes,
        )

    monkeypatch.setattr("os.statvfs", after_cleanup)
    allocations.collect = host.collect
    with pytest.raises(AdminError, match="capacity_exhausted"):
        admit(allocations, request("b", 2001), identity)
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM storage_allocation").fetchone()[0] == 1


def test_first_limits_and_partial_apply_retry_use_real_quota_observer(
    storage, tmp_path, monkeypatch
):
    import os
    from contextlib import contextmanager, nullcontext
    from app.modules.hosted_admin.infrastructure import project_quota as kernel
    from app.modules.hosted_admin.infrastructure.storage_lifecycle import StorageLifecycle
    from app.modules.hosted_admin.tests.test_storage_lifecycle import command, run

    store, allocations, identity, request, _ = storage
    reservation = request()
    root = tmp_path / "projects"
    root.mkdir()
    projects = []
    for original in reservation.policy.projects:
        directory = root / original.role
        directory.mkdir()
        projects.append(
            original.model_copy(
                update={
                    "directory": str(directory),
                    "directory_inode": directory.stat().st_ino,
                    "uid": os.getuid(),
                }
            )
        )
    reservation = reservation.model_copy(
        update={"policy": reservation.policy.model_copy(update={"projects": tuple(projects)})}
    )
    admit(allocations, reservation, identity)
    item = replace(project_instance(reservation.policy), mount=str(root))
    host = StorageHost(store, Mock(), Mock())
    host.registered = Mock(return_value=item)
    host.platform.h.inventory.get.return_value = item
    host.platform.h.source._transport.return_value = {"owner": reservation.id}
    host.binding = Mock()
    host.profile = Mock()
    host.effect_lock = lambda: nullcontext()
    state = {p.project_id: kernel.DiskQuota() for p in projects}
    writes = []
    interrupt = [True]

    @contextmanager
    def protected(path, *args):
        descriptor = os.open(path, os.O_RDONLY)
        try:
            yield descriptor
        finally:
            os.close(descriptor)

    monkeypatch.setattr(kernel, "protected_directory", protected)
    by_inode = {p.directory_inode: p.project_id for p in projects}
    monkeypatch.setattr(
        kernel,
        "attributes",
        lambda fd: (kernel.INHERIT, 0, 0, by_inode[os.fstat(fd).st_ino], 0, b""),
    )

    def probe(policy, project):
        result = kernel.ProjectQuota(
            kernel.ProjectBinding(
                root,
                Path(project.directory),
                policy.filesystem_uuid,
                project.project_id,
                project.uid,
            )
        )
        result.filesystem = Mock(return_value=Path("/dev/qualified-test"))

        def control(device, action, quota):
            if action == 0x800008:
                state[project.project_id] = quota
                writes.append(project.project_id)
                if interrupt[0]:
                    interrupt[0] = False
                    raise OSError("interrupted after first installed project limit")
            return state[project.project_id]

        result._control = control
        return result

    host.probe = probe
    with pytest.raises(kernel.QuotaUnavailable, match="limits_missing"):
        host.usage(reservation.policy, projects[0])
    assert host.initial_usage(reservation.policy, projects[0]).hard_bytes == 0
    apply = command(reservation.id, "apply", 1)
    lifecycle = StorageLifecycle(allocations, host.effects)
    with pytest.raises(OSError):
        run(lifecycle, apply, identity)
    assert writes == [projects[0].project_id]
    assert lifecycle.command(apply, identity, "")["state"] == "active"
    for project in projects:
        assert host.usage(reservation.policy, project).hard_bytes == project.hard_bytes
    assert set(writes) == set(state)

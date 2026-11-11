"""Guarded effects and policy checks; mock effects are not native qualification."""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import os

import pytest

from app.modules.host_agent.application.contracts import (
    InitializeContainer,
    RepairRuntime,
    StartContainer,
)
from app.modules.host_agent.application.dispatch import (
    Allocation,
    HostEffect,
    HostAgentDenied,
    HostAgentUnavailable,
    ResourceLimits,
)
from app.modules.host_agent.infrastructure.container_policy import (
    RuntimeProfile,
    container_spec,
    policy_hash,
    seccomp,
)
from app.modules.host_agent.infrastructure.quota_targets import QuotaTargets
from app.modules.host_agent.infrastructure.runtime_effects import NativeEffects
from app.modules.host_agent.infrastructure.runtime_authority import (
    RuntimeAuthority,
    UnavailableRuntimePrerequisite,
)
from app.modules.host_agent.tests.test_agent import prepare, resource_plan, BINDING
from app.platform.hosted_writer_lock import HostedWriterLock
from app.platform.locking import WorkspaceOperationInProgressError


@pytest.fixture
def runtime():
    command, plan = prepare(), resource_plan()
    allocation = Allocation(
        binding_id=BINDING,
        resource_generation=1,
        host_uid=42001,
        host_gid=42002,
        workspace_project=101,
        control_project=102,
        scratch_project=103,
        filesystem_identity="synthetic-ext4",
        image_digest="b" * 64,
        container_ref="a" * 64,
        limits=ResourceLimits(workspace=plan.workspace, control=plan.control, scratch=plan.scratch),
    )
    mount = Path("/var/lib/epm/data")
    targets = QuotaTargets(
        mount,
        "synthetic-ext4",
        "00000000-0000-4000-8000-000000000001",
        mount / "workspace",
        mount / "control",
        mount / "scratch",
    )
    profile = RuntimeProfile(
        architecture="amd64",
        apparmor_sha256="c" * 64,
        memory_bytes=128 * 1024 * 1024,
        cpu_millicores=500,
        pids=32,
        file_descriptors=128,
        log_bytes=1024 * 1024,
        log_files=2,
    )
    events, fail = [], set()
    spec = container_spec(command, allocation, targets, profile)
    actual = {
        "Id": "a" * 64,
        "Config": deepcopy(spec),
        "HostConfig": deepcopy(spec["HostConfig"]),
        "State": {"Running": False},
        "Mounts": [
            {
                "Type": "bind",
                "Source": m["Source"],
                "Destination": m["Target"],
                "RW": not m["ReadOnly"],
            }
            for m in spec["HostConfig"]["Mounts"]
        ],
    }

    def check(*args):
        events.append("guard")
        if "guard" in fail:
            raise HostAgentUnavailable()

    def verify(*args):
        events.append("storage")
        if "storage" in fail:
            raise HostAgentDenied()
        return {}

    def start(identity):
        events.append("start")
        actual["State"]["Running"] = True
        if "post_start" in fail:
            fail.add("guard")

    def stop(identity):
        events.append("stop")
        actual["State"]["Running"] = False

    engine = SimpleNamespace(
        inspect=lambda identity: deepcopy(actual),
        name=lambda cmd: "epm-original",
        start=start,
        stop=stop,
        create=lambda *args: events.append("create"),
        remove_stopped=lambda identity: events.append("remove"),
    )
    storage = SimpleNamespace(
        targets=targets, verify=verify, prepare=lambda a: events.append("prepare")
    )
    evidence = SimpleNamespace(record=lambda *args: events.append("evidence") or "synthetic-proof")

    @contextmanager
    def starting(*args):
        events.append("stop_projection")
        yield

    target = SimpleNamespace(command=command, container_id="a" * 64)
    registry = SimpleNamespace(
        starting=starting,
        targets=lambda: ("original",),
        target=lambda name: target,
        contain=lambda engine, target: engine.stop(target.container_id),
    )
    driver = NativeEffects(
        storage,
        engine,
        profile,
        SimpleNamespace(verify=check, verify_runtime=check),
        evidence,
        stops=registry,
    )
    return SimpleNamespace(
        command=command,
        allocation=allocation,
        driver=driver,
        actual=actual,
        events=events,
        fail=fail,
        spec=spec,
        profile=profile,
    )


def action(runtime, kind):
    original = runtime.command
    base = {"binding_id": runtime.allocation.binding_id}
    if kind in {"initialize_container", "repair_runtime"}:
        base.update(image_id=original.payload.image_id, release_id=original.payload.release_id)
    if kind == "repair_runtime":
        base["expected_resource_generation"] = runtime.allocation.resource_generation
    payload = {
        "initialize_container": InitializeContainer,
        "repair_runtime": RepairRuntime,
        "start_container": StartContainer,
    }[kind](**base)
    return HostEffect(
        effect=original.effect.model_copy(update={"kind": kind}),
        payload=payload,
        access_epoch=1,
        expected_revision=1,
        inputs_hash=original.inputs_hash if kind != "start_container" else None,
    )


def test_policy_closes_writable_paths_and_independent_restart(runtime):
    config = runtime.spec["HostConfig"]
    assert config["ReadonlyRootfs"] and config["RestartPolicy"]["Name"] == "no"
    assert config["UsernsMode"] == "host" and config["CapDrop"] == ["ALL"]
    assert config["NetworkMode"] == "none" and not config["PortBindings"]
    assert config["Memory"] == config["MemorySwap"]
    assert config["PidsLimit"] == runtime.profile.pids
    mounts = {m["Target"]: m for m in config["Mounts"]}
    assert mounts["/control"]["ReadOnly"] and not mounts["/control/data"]["ReadOnly"]
    assert mounts["/tmp"]["Source"] == mounts["/scratch"]["Source"] == mounts["/var/tmp"]["Source"]
    assert "ro," in config["Tmpfs"]["/dev/shm"]


@pytest.mark.parametrize("architecture", ["amd64", "arm64"])
def test_seccomp_denies_unfiltered_escape_syscalls_and_compat(architecture):
    policy = seccomp(architecture)
    assert policy["defaultAction"] == "SCMP_ACT_ERRNO" and len(policy["architectures"]) == 1
    unrestricted = {
        n
        for r in policy["syscalls"]
        if r["action"] == "SCMP_ACT_ALLOW" and not r.get("args")
        for n in r["names"]
    }
    assert {"chmod", "fchmod", "fchmodat"} <= unrestricted
    assert not unrestricted & {
        "ioctl",
        "clone",
        "clone3",
        "unshare",
        "setns",
        "mount",
        "quotactl",
        "quotactl_fd",
        "socketcall",
        "io_uring_setup",
    }
    rules = [r for r in policy["syscalls"] if r["names"] == ["ioctl"]]
    assert {r["args"][0]["value"] for r in rules} == {0x5451, 0x5401, 0x5421}


@pytest.mark.parametrize("failure", ["guard", "storage"])
def test_unknown_prerequisite_never_starts(runtime, failure):
    runtime.fail.add(failure)
    with pytest.raises((HostAgentDenied, HostAgentUnavailable)):
        runtime.driver.apply(action(runtime, "start_container"), runtime.allocation)
    assert "start" not in runtime.events


def test_post_start_failure_stops(runtime):
    runtime.fail.add("post_start")
    with pytest.raises(HostAgentUnavailable):
        runtime.driver.apply(action(runtime, "start_container"), runtime.allocation)
    assert runtime.events.index("start") < runtime.events.index("stop")
    assert not runtime.actual["State"]["Running"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("ReadonlyRootfs", False),
        ("Privileged", True),
        ("RestartPolicy", {"Name": "always"}),
        ("UsernsMode", ""),
        ("NetworkMode", "host"),
        ("Memory", 0),
        ("CapAdd", ["SYS_ADMIN"]),
    ],
)
def test_inspected_tampering_blocks_start(runtime, key, value):
    runtime.actual["HostConfig"][key] = value
    with pytest.raises(HostAgentDenied):
        runtime.driver.apply(action(runtime, "start_container"), runtime.allocation)
    assert "start" not in runtime.events


@pytest.mark.parametrize("failure", ["quota", "health"])
def test_supervisor_stops_and_never_restarts(runtime, failure):
    runtime.actual["State"]["Running"] = True
    if failure == "quota":
        runtime.fail.add("storage")
    else:
        runtime.actual["State"]["Health"] = {"Status": "unhealthy"}
    assert runtime.driver.supervise(runtime.command, runtime.allocation) == "needs_attention"
    assert runtime.events[-2:] == ["stop", "evidence"]
    assert "start" not in runtime.events and "create" not in runtime.events
    assert runtime.driver.supervise(runtime.command, runtime.allocation) == "stopped"


def test_repair_does_not_remove_live_writer(runtime):
    runtime.actual["State"]["Running"] = True
    with pytest.raises(HostAgentDenied):
        runtime.driver.apply(action(runtime, "repair_runtime"), runtime.allocation)
    assert "remove" not in runtime.events and "create" not in runtime.events


def test_unknown_inspection_never_reapplies(runtime):
    with pytest.raises(HostAgentDenied):
        runtime.driver.inspect(action(runtime, "initialize_container"), runtime.allocation)
    assert "create" not in runtime.events


def test_inventory_alone_cannot_grant_permission(runtime):
    inventory = SimpleNamespace(
        retained=lambda c: (SimpleNamespace(state="pending"), runtime.allocation, True)
    )
    unavailable = UnavailableRuntimePrerequisite()
    with pytest.raises(HostAgentUnavailable):
        RuntimeAuthority(inventory, unavailable, unavailable).verify(
            runtime.command, runtime.allocation, policy_hash(runtime.profile)
        )


def test_stable_lock_excludes_second_writer_across_business_replacement(tmp_path):
    control = tmp_path / "control"
    control.mkdir()
    path = control / "writer.lock"
    path.touch(mode=0o600)
    first, second = HostedWriterLock(path), HostedWriterLock(path)
    with first:
        business = tmp_path / "workspace"
        business.mkdir()
        business.rename(tmp_path / "old-workspace")
        business.mkdir()
        with pytest.raises(WorkspaceOperationInProgressError):
            second.__enter__()
    with second:
        pass
    path.rename(control / "old.lock")
    path.touch(mode=0o600)
    with pytest.raises(WorkspaceOperationInProgressError):
        first.__enter__()


@pytest.mark.parametrize("invalid", ["missing", "symlink", "hardlink", "permissions"])
def test_stable_lock_rejects_unsafe_identity(tmp_path, invalid):
    path = tmp_path / "writer.lock"
    if invalid != "missing":
        path.touch(mode=0o600)
        if invalid == "symlink":
            target = tmp_path / "target"
            path.rename(target)
            path.symlink_to(target)
        elif invalid == "hardlink":
            os.link(path, tmp_path / "linked")
        else:
            path.chmod(0o666)
    with pytest.raises(WorkspaceOperationInProgressError):
        HostedWriterLock(path).__enter__()


@pytest.mark.parametrize("kind", ["initialize_container", "repair_runtime"])
def test_create_and_stopped_repair_return_verified_identity_without_start(runtime, kind):
    command = action(runtime, kind)
    allocation = runtime.allocation
    if kind == "initialize_container":
        allocation = allocation.model_copy(update={"container_ref": None})

    def create(cmd, spec):
        runtime.events.append("create")
        runtime.actual["Id"] = "d" * 64
        runtime.actual["Config"] = deepcopy(spec)
        runtime.actual["HostConfig"] = deepcopy(spec["HostConfig"])
        runtime.actual["Mounts"] = [
            {
                "Type": "bind",
                "Source": m["Source"],
                "Destination": m["Target"],
                "RW": not m["ReadOnly"],
            }
            for m in spec["HostConfig"]["Mounts"]
        ]

    runtime.driver.engine.create = create
    result = runtime.driver.apply(command, allocation)
    assert result.status == "applied" and result.resource_state == "stopped"
    assert result.container_ref == "d" * 64
    assert "start" not in runtime.events
    assert ("remove" in runtime.events) == (kind == "repair_runtime")


def test_initialize_cannot_allocate_a_competing_container(runtime):
    with pytest.raises(HostAgentDenied):
        runtime.driver.apply(action(runtime, "initialize_container"), runtime.allocation)
    assert "create" not in runtime.events


def test_apparmor_permits_only_required_named_runtime_stop_signals():
    application = Path(__file__).resolve().parents[6]
    policy = (application / "deploy/hosted-mvp/sandbox/epm-h02-operator-v1").read_text()
    # A host runc profile is distinct from unconfined. Neither a broad signal
    # grant nor unconfined mode is needed for Docker's normal stop/force-stop.
    assert "signal (receive) set=(term,kill) peer=runc," in policy
    assert "signal (receive) peer=runc," not in policy
    assert "deny mount," in policy and "deny ptrace," in policy

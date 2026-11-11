"""Actual NativeEffects with owning SQLite receipts and explicit synthetic OS adapters."""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.modules.host_agent.application.contracts import (
    ApplyLimits,
    InitializeContainer,
    RepairRuntime,
    StartContainer,
)
from app.modules.host_agent.application.dispatch import HostEffect, ResourceInputs, TreeLimits
from app.modules.host_agent.application.effect_contracts import EffectIdentity
from app.modules.host_agent.infrastructure.runtime_authority import RuntimeAuthority
from app.modules.host_agent.infrastructure.runtime_effects import NativeEffects
from app.modules.host_agent.infrastructure.stop_registry import StopRegistry
from app.modules.host_agent.tests.test_agent import (
    setup as setup,
    ready,
    prepare,
    rows,
    follow,
    resource_plan,
    BINDING,
    ID,
    OTHER,
)
from app.modules.host_agent.tests.test_runtime_effects import runtime as runtime
from app.platform.hosted_contracts.semantic import semantic_hash


class Engine:
    def __init__(self):
        self.items = {}
        self.names = {}
        self.starts = []
        self.creates = []
        self.fail_start = False

    @staticmethod
    def name(command):
        return command.effect.child_id()

    def inspect(self, identity):
        return deepcopy(self.items.get(self.names.get(identity, identity)))

    def create(self, command, spec):
        self.creates.append(command.effect.child_id())
        identity = sha256(str(len(self.creates)).encode()).hexdigest()
        self.names[self.name(command)] = identity
        self.items[identity] = {
            "Id": identity,
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
        return identity

    def start(self, identity):
        self.starts.append(identity)
        self.items[identity]["State"]["Running"] = True
        if self.fail_start:
            raise TimeoutError("lost start reply")

    def stop(self, identity):
        self.items[identity]["State"]["Running"] = False

    def remove_stopped(self, identity):
        assert not self.items[identity]["State"]["Running"]
        del self.items[identity]


@pytest.fixture
def native(setup, runtime, tmp_path):
    ready(setup)
    directory = tmp_path / "guardian"
    directory.mkdir(mode=0o700)
    registry = StopRegistry(directory)
    state = SimpleNamespace(
        limits=setup.inventory.runtime_allocation(prepare()).limits, fail_role=None
    )

    def verify(allocation):
        if allocation.limits != state.limits:
            raise ValueError("Physical limit mismatch")
        return {}

    def set_limit(role, bytes, inodes):
        if role == state.fail_role:
            raise OSError("synthetic quota failure")
        state.limits = state.limits.model_copy(
            update={role: TreeLimits(byte_ceiling=bytes, inode_ceiling=inodes)}
        )

    projects = tuple(
        SimpleNamespace(set_limits=lambda b, i, r=role: set_limit(r, b, i))
        for role in ("workspace", "control", "scratch")
    )
    storage = SimpleNamespace(
        targets=runtime.driver.storage.targets, verify=verify, projects=lambda a: projects
    )
    engine = Engine()
    prerequisite = SimpleNamespace(verify=lambda *args: None)
    driver = NativeEffects(
        storage,
        engine,
        runtime.profile,
        RuntimeAuthority(setup.inventory, prerequisite, prerequisite),
        SimpleNamespace(record=lambda *args: "synthetic-native-proof"),
        stops=registry,
    )
    setup.agent.driver = driver
    with registry.owner_lease() as live:
        live()
        yield SimpleNamespace(setup=setup, engine=engine, state=state, registry=registry)
    registry.contain_all(engine)


def resource_command(native, kind, *, slot=None, plan=None):
    fixture = native.setup
    old = prepare()
    binding = rows(fixture, "resource_bindings")[0]
    fields = dict(binding_id=BINDING, image_id=ID, release_id=OTHER)
    if kind == "repair_runtime":
        fields["expected_resource_generation"] = binding["resource_generation"]
    payload = {"initialize_container": InitializeContainer, "repair_runtime": RepairRuntime}[kind](
        **fields
    )
    plan = plan or resource_plan()
    command = HostEffect(
        effect=EffectIdentity(
            parent=old.effect.parent,
            binding_id=BINDING,
            resource_generation=1,
            kind=kind,
            slot=slot or kind,
        ),
        access_epoch=1,
        expected_revision=binding["revision"],
        inputs_hash=semantic_hash(ResourceInputs(plan=plan)),
        payload=payload,
    )
    return fixture.admission.add(command, plan=plan)


def initialize(native):
    command = resource_command(native, "initialize_container")
    assert native.setup.agent.execute(command).state == "applied"
    return command


def test_original_create_and_repair_are_inspected_not_duplicated(native):
    command = initialize(native)
    original = native.setup.agent.execute(command)
    assert original.state == "applied" and len(native.engine.creates) == 1
    repair = resource_command(native, "repair_runtime")
    assert native.setup.agent.execute(repair).state == "applied"
    assert native.setup.agent.execute(repair).state == "applied"
    assert len(native.engine.creates) == 2 and len(native.engine.items) == 1
    assert native.engine.starts == []


@pytest.mark.parametrize("kind", ["initialize_container", "repair_runtime"])
def test_create_commit_failure_retains_original_effect_for_inspection(native, monkeypatch, kind):
    if kind == "repair_runtime":
        initialize(native)
    command = resource_command(native, kind)
    original = native.setup.inventory.finish

    def fail(*args):
        raise RuntimeError("result commit failed")

    monkeypatch.setattr(native.setup.inventory, "finish", fail)
    with pytest.raises(RuntimeError):
        native.setup.agent.execute(command)
    count = len(native.engine.creates)
    monkeypatch.setattr(native.setup.inventory, "finish", original)
    assert native.setup.agent.execute(command).state == "applied"
    assert len(native.engine.creates) == count


def test_successful_start_commit_failure_reconciles_without_second_start(native, monkeypatch):
    initialize(native)
    command = follow(native.setup, StartContainer(binding_id=BINDING))
    original = native.setup.inventory.finish
    monkeypatch.setattr(
        native.setup.inventory,
        "finish",
        lambda *args: (_ for _ in ()).throw(RuntimeError("commit fault")),
    )
    with pytest.raises(RuntimeError):
        native.setup.agent.execute(command)
    monkeypatch.setattr(native.setup.inventory, "finish", original)
    assert native.setup.agent.execute(command).state == "applied"
    assert len(native.engine.starts) == 1 and len(native.registry.targets()) == 1


def test_lost_start_reply_contains_and_unknown_retry_never_replays(native):
    initialize(native)
    command = follow(native.setup, StartContainer(binding_id=BINDING))
    native.engine.fail_start = True
    assert native.setup.agent.execute(command).state == "unknown"
    assert native.setup.agent.execute(command).state == "unknown"
    assert len(native.engine.starts) == 1
    assert not next(iter(native.engine.items.values()))["State"]["Running"]


def limits_command(native):
    plan = resource_plan().model_copy(
        update={
            "limit_profile_id": ID,
            "workspace": TreeLimits(byte_ceiling=2000000, inode_ceiling=200),
            "control": TreeLimits(byte_ceiling=1500000, inode_ceiling=150),
        }
    )
    command = HostEffect(
        effect=EffectIdentity(
            parent=prepare().effect.parent,
            binding_id=BINDING,
            resource_generation=1,
            kind="apply_limits",
            slot="change_limits",
        ),
        access_epoch=1,
        expected_revision=rows(native.setup, "resource_bindings")[0]["revision"],
        inputs_hash=semantic_hash(ResourceInputs(plan=plan)),
        payload=ApplyLimits(binding_id=BINDING, qualified_limit_profile_id=ID),
    )
    return native.setup.admission.add(command, plan=plan)


def test_stopped_limit_change_verifies_then_commits_and_retries_read_only(native):
    initialize(native)
    command = limits_command(native)
    assert native.setup.agent.execute(command).state == "applied"
    assert native.setup.agent.execute(command).state == "applied"
    assert rows(native.setup, "resource_bindings")[0]["workspace_byte_ceiling"] == 2000000


def test_partial_limit_failure_stays_unknown_and_never_claims_desired_profile(native):
    initialize(native)
    command = limits_command(native)
    native.state.fail_role = "control"
    assert native.setup.agent.execute(command).state == "unknown"
    native.state.fail_role = None
    assert native.setup.agent.execute(command).state == "unknown"
    assert rows(native.setup, "resource_bindings")[0]["workspace_byte_ceiling"] == 1000000


def test_running_writer_cannot_have_limits_changed(native):
    initialize(native)
    assert (
        native.setup.agent.execute(follow(native.setup, StartContainer(binding_id=BINDING))).state
        == "applied"
    )
    command = limits_command(native)
    original = native.state.limits
    assert native.setup.agent.execute(command).state == "unknown"
    assert native.state.limits == original


@pytest.mark.parametrize("damage", ["missing", "changed_bytes"])
def test_inventory_failure_stops_from_independent_projection(native, damage):
    initialize(native)
    command = follow(native.setup, StartContainer(binding_id=BINDING))
    assert native.setup.agent.execute(command).state == "applied"
    # Preserve fixture DB bytes to allow scoped fixture cleanup/inspection afterward.
    path = native.setup.path
    original = path.read_bytes()
    if damage == "missing":
        path.rename(path.with_suffix(".retained"))
    else:
        path.write_bytes(b"not a database")
    try:
        with pytest.raises(Exception):
            native.setup.agent.supervise(command)
        assert not next(iter(native.engine.items.values()))["State"]["Running"]
    finally:
        if damage == "missing":
            path.with_suffix(".retained").rename(path)
        else:
            path.write_bytes(original)


def test_guard_and_attention_commit_failures_preserve_both_errors(native, monkeypatch):
    initialize(native)
    command = follow(native.setup, StartContainer(binding_id=BINDING))
    assert native.setup.agent.execute(command).state == "applied"

    def unavailable(*args):
        raise OSError("original verification failed")

    def persistence(*args):
        raise RuntimeError("attention commit failed")

    monkeypatch.setattr(native.setup.agent.driver, "supervise", unavailable)
    monkeypatch.setattr(native.setup.inventory, "mark_attention", persistence)
    with pytest.raises(ExceptionGroup) as captured:
        native.setup.agent.supervise(command)
    assert any("attention commit failed" in str(item) for item in captured.value.exceptions)
    assert any("original verification failed" in str(item) for item in captured.value.exceptions)
    assert not next(iter(native.engine.items.values()))["State"]["Running"]


def fenced_native_gateway(native):
    from app.modules.host_agent.infrastructure.gateway import (
        Gateway,
        GatewaySettings,
        HostEffects,
        IngressContainment,
    )
    from pathlib import Path

    active = {}

    def load(config):
        active.clear()
        active.update(deepcopy(config))

    driver = native.setup.agent.driver
    gateway = Gateway(
        native.setup.inventory,
        SimpleNamespace(load=load, inspect=lambda: deepcopy(active)),
        GatewaySettings(Path("/run/epm-caddy/admin.sock"), 1001),
        IngressContainment(native.registry, native.engine),
    )
    driver.authority.external_deny = gateway
    native.setup.agent.driver = HostEffects(driver, gateway)
    gateway.reload_closed()
    return active


@pytest.mark.parametrize("epoch", [1, 2])
def test_verified_stop_supersedes_unknown_start_without_replay(native, epoch):
    from app.modules.host_agent.application.contracts import StopContainer
    from app.modules.host_agent.application.dispatch import IngressPolicy
    import json

    fenced_native_gateway(native)
    initialize(native)
    old = follow(native.setup, StartContainer(binding_id=BINDING))
    native.engine.fail_start = True
    assert native.setup.agent.execute(old).state == "unknown"
    retained = next(
        r for r in rows(native.setup, "host_receipts") if r["operation_id"] == old.effect.child_id()
    )
    if epoch > 1:
        held = follow(
            native.setup,
            IngressPolicy(desired_state="held", expected_ingress_revision=1),
            epoch=epoch,
        )
        assert native.setup.agent.execute(held).state == "applied"
    stop = follow(native.setup, StopContainer(binding_id=BINDING), epoch=epoch)
    assert native.setup.agent.execute(stop).state == "applied"
    original = native.setup.agent.execute(old)
    assert original.state == "superseded"
    assert original.superseded_by_operation_id == stop.effect.child_id()
    assert original.containment_evidence_ref == "synthetic-native-proof"
    saved = next(
        r for r in rows(native.setup, "host_receipts") if r["operation_id"] == old.effect.child_id()
    )
    assert saved["request_json"] == retained["request_json"]
    assert json.loads(saved["observed_json"])["status"] == "unknown"
    assert len(native.engine.starts) == 1
    native.engine.fail_start = False
    new = follow(
        native.setup, StartContainer(binding_id=BINDING), epoch=epoch, slot="after_verified_stop"
    )
    assert native.setup.agent.execute(new).state == "applied"
    assert len(native.engine.starts) == 2
    assert native.setup.agent.execute(old) == original
    assert len(native.engine.starts) == 2


def test_current_applied_start_supervises_old_stop_identity_after_new_fence(native):
    from app.modules.host_agent.application.contracts import StopContainer
    from app.modules.host_agent.application.dispatch import IngressPolicy
    from app.modules.host_agent.infrastructure.supervisor import Supervisor

    active = fenced_native_gateway(native)
    initialize(native)
    first = follow(native.setup, StartContainer(binding_id=BINDING))
    assert native.setup.agent.execute(first).state == "applied"
    name = native.registry.targets()[0]
    immutable = native.registry.read(name)
    assert (
        native.setup.agent.execute(follow(native.setup, StopContainer(binding_id=BINDING))).state
        == "applied"
    )
    held = follow(
        native.setup, IngressPolicy(desired_state="held", expected_ingress_revision=1), epoch=2
    )
    assert native.setup.agent.execute(held).state == "applied"
    latest = follow(native.setup, StartContainer(binding_id=BINDING), epoch=2, slot="second_start")
    assert native.setup.agent.execute(latest).state == "applied"
    assert native.registry.read(name) == immutable
    guardian = Supervisor(native.registry, native.engine, native.setup.agent)
    assert guardian.poll() == []
    assert next(iter(native.engine.items.values()))["State"]["Running"]
    assert (
        native.setup.inventory.supervision_command(first, next(iter(native.engine.items))) == latest
    )
    active.clear()  # Current external authority, not the immutable old command, is decisive.
    guardian.poll()
    assert not next(iter(native.engine.items.values()))["State"]["Running"]
    assert rows(native.setup, "resource_bindings")[0]["state"] == "needs_attention"


def test_stop_and_supersession_rollback_and_retry_are_atomic(native, monkeypatch):
    from app.modules.host_agent.application.contracts import StopContainer

    initialize(native)
    old = follow(native.setup, StartContainer(binding_id=BINDING))
    native.engine.fail_start = True
    assert native.setup.agent.execute(old).state == "unknown"
    stop = follow(native.setup, StopContainer(binding_id=BINDING))
    original = native.setup.inventory._supersede_contained_starts

    def fail(*args):
        original(*args)
        raise RuntimeError("receipt transaction failed")

    monkeypatch.setattr(native.setup.inventory, "_supersede_contained_starts", fail)
    with pytest.raises(RuntimeError, match="receipt transaction failed"):
        native.setup.agent.execute(stop)
    assert native.setup.agent.original(old).state == "unknown"
    assert native.setup.agent.original(stop).state == "pending"
    monkeypatch.setattr(native.setup.inventory, "_supersede_contained_starts", original)
    assert native.setup.agent.execute(stop).state == "applied"
    assert native.setup.agent.original(old).state == "superseded"
    assert len(native.engine.starts) == 1


def test_superseded_start_is_terminal_and_requires_containment_identity(native):
    from app.modules.host_agent.application.contracts import StopContainer
    from app.modules.host_agent.application.dispatch import EffectReceipt
    from pydantic import ValidationError
    from sqlalchemy.exc import IntegrityError

    initialize(native)
    start = follow(native.setup, StartContainer(binding_id=BINDING))
    native.engine.fail_start = True
    assert native.setup.agent.execute(start).state == "unknown"
    stop = follow(native.setup, StopContainer(binding_id=BINDING))
    assert native.setup.agent.execute(stop).state == "applied"
    superseded = native.setup.agent.original(start)
    with pytest.raises(ValidationError):
        EffectReceipt.model_validate(superseded.model_dump() | {"containment_evidence_ref": None})
    with pytest.raises(IntegrityError):
        with native.setup.inventory.transaction() as connection:
            table = native.setup.inventory.table(connection, "host_receipts")
            connection.execute(
                table.update()
                .where(table.c.operation_id == start.effect.child_id())
                .values(state="unknown")
            )
    assert native.setup.agent.original(start) == superseded


def test_unknown_stop_does_not_clear_start_uncertainty(native):
    from app.modules.host_agent.application.contracts import StopContainer

    initialize(native)
    start = follow(native.setup, StartContainer(binding_id=BINDING))
    native.engine.fail_start = True
    assert native.setup.agent.execute(start).state == "unknown"
    stop = follow(native.setup, StopContainer(binding_id=BINDING))
    native.engine.stop = lambda *args: (_ for _ in ()).throw(
        TimeoutError("no containment evidence")
    )
    assert native.setup.agent.execute(stop).state == "unknown"
    assert native.setup.agent.original(start).state == "unknown"

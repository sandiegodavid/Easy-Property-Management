"""Stop-only recovery does not grant runtime start or inventory authority."""

from threading import Event
from types import SimpleNamespace
import json
import os

import pytest

from app.modules.host_agent.application.dispatch import HostAgentDenied, HostAgentUnavailable
from app.modules.host_agent.infrastructure.stop_registry import StopRegistry, StopTarget
from app.modules.host_agent.infrastructure.supervisor import Supervisor
from app.modules.host_agent.tests.test_runtime_effects import action, runtime as runtime


@pytest.fixture
def registry(tmp_path):
    directory = tmp_path / "stop-targets"
    directory.mkdir(mode=0o700)
    return StopRegistry(directory)


def target_for(runtime):
    return StopTarget(
        command=action(runtime, "start_container"),
        container_id="a" * 64,
        image_digest=runtime.allocation.image_digest,
        host_uid=runtime.allocation.host_uid,
        host_gid=runtime.allocation.host_gid,
    )


def arm(registry, runtime):
    registry.register(target_for(runtime))


def test_no_guardian_lease_or_readiness_means_no_start(registry, runtime):
    runtime.driver.stops = registry
    with pytest.raises((HostAgentUnavailable, ExceptionGroup, FileNotFoundError)):
        runtime.driver.apply(action(runtime, "start_container"), runtime.allocation)
    assert "start" not in runtime.events


def test_durable_projection_before_start_and_stale_ready_cannot_authorize(registry, runtime):
    runtime.driver.stops = registry
    with registry.owner_lease() as ready:
        with pytest.raises(HostAgentUnavailable):
            with registry.starting(
                action(runtime, "start_container"), runtime.allocation, runtime.actual
            ):
                pytest.fail("Unready owner admitted a start")
        ready()
        result = runtime.driver.apply(action(runtime, "start_container"), runtime.allocation)
        assert result.resource_state == "running"
        record = registry.target("a" * 64 + ".target")
        assert record == target_for(runtime)
        registry.register(record)
        assert registry.targets() == ("a" * 64 + ".target",)
        with pytest.raises(HostAgentUnavailable):
            with registry.owner_lease():
                pytest.fail("Second supervisor acquired ownership")
    assert not (registry.directory / "ready").exists()
    registry.publish("ready", b"stale")
    with pytest.raises(HostAgentUnavailable):
        with registry.starting(
            action(runtime, "start_container"), runtime.allocation, runtime.actual
        ):
            pytest.fail("Stale owner admitted a start")


def test_owner_death_during_start_contained(registry, runtime):
    runtime.driver.stops = registry
    owner = registry.owner_lease()
    ready = owner.__enter__()
    ready()
    original = runtime.driver.engine.start

    def start(identity):
        original(identity)
        owner.__exit__(None, None, None)

    runtime.driver.engine.start = start
    with pytest.raises(HostAgentUnavailable):
        runtime.driver.apply(action(runtime, "start_container"), runtime.allocation)
    assert "start" in runtime.events and "stop" in runtime.events
    assert not runtime.actual["State"]["Running"]


def test_contain_exact_id_without_inventory_or_label_trust(registry, runtime):
    arm(registry, runtime)
    runtime.actual["State"]["Running"] = True
    runtime.actual["Config"]["Labels"] = {"changed": "not-authority"}
    registry.contain_all(runtime.driver.engine)
    assert not runtime.actual["State"]["Running"]
    assert runtime.events == ["stop"]
    assert json.loads(registry.read("a" * 64 + ".attention"))["stop_verified"] is True


def test_unknown_stop_never_reports_success_or_skips_siblings(registry, runtime):
    first = target_for(runtime)
    registry.register(first)
    registry.register(first.model_copy(update={"container_id": "b" * 64}))
    calls = []

    def stop(identity):
        calls.append(identity)
        raise TimeoutError("lost response")

    engine = SimpleNamespace(
        inspect=lambda identity: {"State": {"Running": identity == "a" * 64}}, stop=stop
    )
    with pytest.raises(ExceptionGroup):
        registry.contain_all(engine)
    assert calls == ["a" * 64]
    assert json.loads(registry.read("a" * 64 + ".attention"))["stop_verified"] is False
    assert json.loads(registry.read("b" * 64 + ".attention"))["stop_verified"] is True


def test_lost_response_uses_independent_stop_inspection(registry, runtime):
    arm(registry, runtime)
    runtime.actual["State"]["Running"] = True

    def stop(identity):
        runtime.actual["State"]["Running"] = False
        raise TimeoutError("lost response")

    runtime.driver.engine.stop = stop
    registry.contain_all(runtime.driver.engine)
    assert json.loads(registry.read("a" * 64 + ".attention"))["stop_verified"]


def test_new_owner_contains_before_ready_never_restarts(registry, runtime):
    arm(registry, runtime)
    runtime.actual["State"]["Running"] = True
    stopped = Event()
    stopped.set()
    agent = SimpleNamespace(supervise=lambda *args, **kwargs: pytest.fail("Unexpected check"))
    Supervisor(registry, runtime.driver.engine, agent).run(stopped)
    assert runtime.events == ["stop"]
    assert not (registry.directory / "ready").exists()


def test_missing_inventory_poll_contains_and_retains_safe_attention(registry, runtime):
    arm(registry, runtime)
    runtime.actual["State"]["Running"] = True

    def missing(*args, **kwargs):
        raise FileNotFoundError("private inventory missing")

    failures = Supervisor(
        registry, runtime.driver.engine, SimpleNamespace(supervise=missing)
    ).poll()
    assert len(failures) == 1 and runtime.events == ["stop"]
    assert b"private" not in registry.read("a" * 64 + ".attention")


def test_malformed_record_does_not_skip_other_owned_targets(registry, runtime):
    registry.publish("0" * 64 + ".target", b"not JSON")
    arm(registry, runtime)
    runtime.actual["State"]["Running"] = True
    with pytest.raises(ExceptionGroup):
        registry.contain_all(runtime.driver.engine)
    assert runtime.events == ["stop"]


@pytest.mark.parametrize("change", ["symlink", "hardlink", "permission", "oversize"])
def test_tampered_record_rejects(registry, runtime, tmp_path, change):
    arm(registry, runtime)
    path = registry.directory / ("a" * 64 + ".target")
    if change == "symlink":
        original = tmp_path / "original"
        path.rename(original)
        path.symlink_to(original)
    elif change == "hardlink":
        os.link(path, tmp_path / "alias")
    elif change == "permission":
        path.chmod(0o666)
    else:
        path.write_bytes(b"x" * 32769)
    with pytest.raises((HostAgentDenied, OSError)):
        registry.target(path.name)


def test_projection_failure_prevents_start(registry, runtime, monkeypatch):
    runtime.driver.stops = registry

    def fail(*args, **kwargs):
        raise OSError("projection full")

    with registry.owner_lease() as ready:
        ready()
        monkeypatch.setattr(registry, "register", fail)
        with pytest.raises((OSError, ExceptionGroup)):
            runtime.driver.apply(action(runtime, "start_container"), runtime.allocation)
    assert "start" not in runtime.events


def test_missing_docker_observation_retains_unknown_attention(registry, runtime):
    arm(registry, runtime)

    def unavailable(*args):
        raise TimeoutError("engine unreachable")

    engine = SimpleNamespace(inspect=unavailable)
    with pytest.raises(ExceptionGroup):
        registry.contain_all(engine)
    assert json.loads(registry.read("a" * 64 + ".attention"))["stop_verified"] is False


def test_standalone_guardian_never_publishes_start_permission(registry, runtime):
    stopped = Event()

    def stop_wait(interval):
        assert not (registry.directory / "ready").exists()
        stopped.set()
        return True

    stopped.wait = stop_wait
    Supervisor(registry, runtime.driver.engine).run(stopped)
    assert not (registry.directory / "ready").exists()


def test_stop_all_waits_for_inflight_start_barrier(registry, runtime):
    # The same gate orders an in-flight start with ExecStopPost in a new process.
    # Kernel cross-process exclusion is additionally exercised in native systemd proof.
    with registry.lock("gate.lock"):
        with pytest.raises(HostAgentUnavailable):
            with registry.lock("gate.lock"):
                pytest.fail("Concurrent start/stop obtained the same barrier")


def test_bound_rejects_new_stop_targets_before_any_start(registry, runtime, monkeypatch):
    import app.modules.host_agent.infrastructure.stop_registry as module

    monkeypatch.setattr(module, "MAX_TARGETS", 1)
    first = target_for(runtime)
    registry.register(first)
    with pytest.raises(HostAgentUnavailable):
        registry.register(first.model_copy(update={"container_id": "b" * 64}))
    assert registry.targets() == ("a" * 64 + ".target",)


def test_stale_scope_cannot_rebind_existing_stop_target(registry, runtime):
    first = target_for(runtime)
    registry.register(first)
    with pytest.raises(HostAgentDenied):
        registry.register(first.model_copy(update={"image_digest": "c" * 64}))
    assert registry.target("a" * 64 + ".target") == first

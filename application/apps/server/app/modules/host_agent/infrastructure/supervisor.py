"""Single bounded runtime guardian; stop-only recovery never reconstructs inventory."""

import argparse
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import platform
import signal
from threading import Event
from time import time_ns

from app.modules.host_agent.application.dispatch import HostAgentUnavailable
from app.modules.host_agent.application.service import HostAgent
from app.modules.host_agent.infrastructure.container_policy import RuntimeProfile
from app.modules.host_agent.infrastructure.docker_engine import DockerEngine
from app.modules.host_agent.infrastructure.gateway import CaddyAdmin, Gateway, GatewaySettings
from app.modules.host_agent.infrastructure.private_storage import PrivateStorage
from app.modules.host_agent.infrastructure.quota_targets import QuotaTargets
from app.modules.host_agent.infrastructure.runtime_authority import RuntimeAuthority
from app.modules.host_agent.infrastructure.runtime_effects import NativeEffects
from app.modules.host_agent.infrastructure.service_config import ServiceInputs
from app.modules.host_agent.infrastructure.service_runtime import ServiceRuntime
from app.modules.host_agent.infrastructure.stop_registry import StopRegistry
from app.modules.host_agent.infrastructure.tunnel_credentials import protected_bytes
from app.platform.hosted_logging import emit_structured_event

logger = logging.getLogger("epm.host_guardian")


class _SupervisionOnlyAdmission:
    """Supervision guardian never admits mutating commands."""

    def resolve(self, _command):
        raise HostAgentUnavailable()


class _StopDirEvidence:
    """Bounded, non-secret supervision evidence recorder under the stop registry directory."""

    def __init__(self, registry: StopRegistry):
        self.registry = registry

    def record(self, command, allocation, facts) -> str:
        payload = json.dumps(
            {
                "binding_id": allocation.binding_id,
                "resource_generation": allocation.resource_generation,
                "state": facts.get("state"),
                "runtime_stopped": bool(facts.get("runtime_stopped", False)),
                "recorded_at_ms": time_ns() // 1_000_000,
            },
            sort_keys=True,
        ).encode("utf-8")
        digest = sha256(payload).hexdigest()
        self.registry.publish(f"{allocation.binding_id}.supervision", payload)
        return f"supervision:{digest[:16]}"


class _InstalledQualificationPort:
    """Verifies that the supervised allocation matches the pinned runtime policy."""

    def __init__(self, expected_policy_hash: str | None = None):
        self.expected_policy_hash = expected_policy_hash

    def verify(self, _command, allocation, policy_hash: str) -> None:
        if not allocation.image_digest:
            raise HostAgentUnavailable()
        if self.expected_policy_hash is not None and policy_hash != self.expected_policy_hash:
            raise HostAgentUnavailable()


def _emit_containment_alert() -> str:
    return emit_structured_event(
        logger,
        "epm-host-guardian",
        "runtime_containment_attention",
        severity="CRITICAL",
        message="Runtime containment requires attention.",
    )


def build_supervision_agent(
    config_path: Path,
    *,
    registry: StopRegistry,
    engine: DockerEngine,
    profile_path: Path | None = None,
    owner: int = 0,
) -> HostAgent:
    """Compose a production HostAgent for standalone guardian supervision."""
    inputs = ServiceInputs.model_validate_json(protected_bytes(config_path, owner=owner))
    runtime = ServiceRuntime(inputs)
    inventory = runtime.inventory()
    admin_socket = Path(inputs.layout.gateway_runtime) / "admin.sock"
    gateway = Gateway(
        inventory,
        CaddyAdmin(admin_socket),
        GatewaySettings(admin_socket, inputs.network.gateway_port),
        lambda: registry.contain_all(engine),
        auth_endpoints=runtime.registered_sources(inventory),
    )
    data_root = Path(inputs.layout.data)
    fs_uuid = inputs.metadata.filesystem_identity.removeprefix("gcp-data:")
    targets = QuotaTargets(
        data_root,
        inputs.metadata.filesystem_identity,
        fs_uuid,
        data_root / "workspace",
        data_root / "control",
        data_root / "scratch",
    )
    storage = PrivateStorage(targets)
    if profile_path is not None:
        profile = RuntimeProfile.model_validate_json(protected_bytes(profile_path, owner=owner))
    else:
        arch = "arm64" if platform.machine().lower() in {"aarch64", "arm64"} else "amd64"
        profile = RuntimeProfile(
            architecture=arch,
            apparmor_sha256="0" * 64,
            memory_bytes=512 * 1024 * 1024,
            cpu_millicores=1000,
            pids=128,
            file_descriptors=1024,
            log_bytes=8 * 1024 * 1024,
            log_files=3,
        )
    authority = RuntimeAuthority(inventory, _InstalledQualificationPort(), gateway)
    effects = NativeEffects(
        storage,
        engine,
        profile,
        authority,
        _StopDirEvidence(registry),
        stops=registry,
    )
    return HostAgent(
        inventory,
        _SupervisionOnlyAdmission(),
        effects,
        clock=lambda: time_ns() // 1_000_000,
    )


class Supervisor:
    def __init__(self, registry, engine, agent=None):
        self.registry, self.engine, self.agent = registry, engine, agent

    def poll(self):
        failures = []
        for name in self.registry.targets():
            try:
                target = self.registry.target(name)
                actual = self.engine.inspect(target.container_id)
                if actual is None or not actual["State"]["Running"]:
                    continue
                if self.agent is None:
                    raise HostAgentUnavailable()
                self.agent.supervise(target.command, container_id=target.container_id)
            except Exception as original:
                failures.append(original)
                try:
                    # Re-read the exact protected projection; do not use the last
                    # iteration's target if this record was malformed.
                    self.registry.contain(self.engine, self.registry.target(name))
                except Exception as containment:
                    failures.append(containment)
        return failures

    def run(self, stop: Event, *, interval=5, notify=lambda: None):
        if not 1 <= interval <= 30:
            raise ValueError("A bounded supervisor interval is required.")
        with self.registry.owner_lease() as ready:
            try:
                # After process death/restart always contain first. Never auto-start.
                self.registry.contain_all(self.engine)
                if self.agent is not None:
                    ready()
                while not stop.is_set():
                    if self.poll():
                        notify()  # Sanitized attention, never OS/provider payloads.
                    stop.wait(interval)
            finally:
                self.registry.contain_all(self.engine)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--contain-all", action="store_true")
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.exit(3, "The protected runtime guardian is unavailable.\n")
    try:
        registry, engine = StopRegistry(args.registry), DockerEngine()
        if args.contain_all:
            registry.contain_all(engine)
            return
        stopped = Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_args: stopped.set())
        agent = (
            build_supervision_agent(
                args.config,
                registry=registry,
                engine=engine,
                profile_path=args.profile,
            )
            if args.config is not None
            else None
        )
        Supervisor(registry, engine, agent=agent).run(stopped, notify=_emit_containment_alert)
    except Exception:
        parser.exit(3, "Runtime containment requires attention.\n")


if __name__ == "__main__":
    main()

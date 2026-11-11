"""Private disposable root-Linux systemd fixture, never production admission."""

import argparse
import json
from pathlib import Path
import signal
import time
from threading import Event
from types import SimpleNamespace

from app.modules.host_agent.application.dispatch import Allocation, HostEffect, HostAgentUnavailable
from app.modules.host_agent.infrastructure.container_policy import RuntimeProfile
from app.modules.host_agent.infrastructure.docker_engine import DockerEngine
from app.modules.host_agent.infrastructure.private_storage import PrivateStorage
from app.modules.host_agent.infrastructure.quota_targets import QuotaTargets
from app.modules.host_agent.infrastructure.runtime_effects import NativeEffects
from app.modules.host_agent.infrastructure.stop_registry import StopRegistry
from app.modules.host_agent.infrastructure.supervisor import Supervisor
from app.modules.hosted_admin.infrastructure.project_quota_qualification import Laboratory


class DiagnosticEngine(DockerEngine):
    """Private fixture timings only; production guardian output stays sanitized."""

    def _request(self, method, endpoint, data=None, *, missing=False):
        started = time.monotonic()
        print(
            json.dumps({"event": "engine_begin", "method": method, "endpoint": endpoint}),
            flush=True,
        )
        try:
            return super()._request(method, endpoint, data, missing=missing)
        finally:
            print(
                json.dumps(
                    {
                        "event": "engine_end",
                        "method": method,
                        "elapsed": round(time.monotonic() - started, 3),
                    }
                ),
                flush=True,
            )


class DiagnosticSupervisor(Supervisor):
    def poll(self):
        print(
            json.dumps({"event": "poll_begin", "targets": len(self.registry.targets())}), flush=True
        )
        failures = super().poll()
        print(
            json.dumps(
                {"event": "poll_end", "errors": [type(error).__name__ for error in failures]}
            ),
            flush=True,
        )
        return failures


def run(root):
    lab = Laboratory(root)  # Requires explicit opt-in, root Linux and guarded lab root.
    config = json.loads((root / "guardian-fixture.json").read_text())
    allocation = Allocation.model_validate_json(json.dumps(config["allocation"]))
    command = HostEffect.model_validate_json(json.dumps(config["command"]))
    profile = RuntimeProfile.model_validate_json(json.dumps(config["profile"]))
    targets = QuotaTargets(
        lab.mount,
        "isolated-native-fixture",
        lab.state["uuid"],
        lab.mount / "workspace",
        lab.mount / "control",
        lab.mount / "scratch",
    )
    engine = DiagnosticEngine()
    registry = StopRegistry(root / "service-stop-targets")
    driver = NativeEffects(
        PrivateStorage(targets),
        engine,
        profile,
        SimpleNamespace(verify_runtime=lambda *args: None),
        SimpleNamespace(record=lambda *args: "native-service-proof"),
        stops=registry,
    )

    def supervise(incoming, *, container_id):
        unavailable = (root / "inventory-unavailable").exists()
        print(json.dumps({"event": "verify", "inventory_unavailable": unavailable}), flush=True)
        if unavailable:
            raise HostAgentUnavailable()
        if incoming != command or container_id != allocation.container_ref:
            raise HostAgentUnavailable()
        return driver.supervise(incoming, allocation)

    stop = Event()
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, lambda *args: stop.set())
    DiagnosticSupervisor(registry, engine, SimpleNamespace(supervise=supervise)).run(
        stop, interval=1, notify=lambda: print("Runtime needs attention.", flush=True)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    run(parser.parse_args().root)

"""Single bounded runtime guardian; stop-only recovery never reconstructs inventory."""

import argparse
import os
from pathlib import Path
import signal
from threading import Event

from app.modules.host_agent.application.dispatch import HostAgentUnavailable
from app.modules.host_agent.infrastructure.docker_engine import DockerEngine
from app.modules.host_agent.infrastructure.stop_registry import StopRegistry


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--contain-all", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.exit(3, "The protected runtime guardian is unavailable.\n")
    try:
        registry, engine = StopRegistry(args.registry), DockerEngine()
        if args.contain_all:
            registry.contain_all(engine)
            return
        stopped = Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *args: stopped.set())
        # Safe standalone default until H02.7 composes the authenticated owning
        # agent/qualification/deny ports. This mode never publishes start readiness.
        Supervisor(registry, engine).run(
            stopped, notify=lambda: print("Runtime needs attention.", flush=True)
        )
    except Exception:
        parser.exit(3, "Runtime containment requires attention.\n")


if __name__ == "__main__":
    main()

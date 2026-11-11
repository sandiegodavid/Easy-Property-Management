"""Combined connected bridge + current quota/AppArmor sandbox fixture, not live admission."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import pwd
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sandbox"))

from qualify_runtime import Qualification, command
from app.modules.host_agent.application.network import NetworkRecord, NetworkProjection
from app.modules.host_agent.infrastructure.container_policy import container_spec, policy_hash
from app.modules.host_agent.infrastructure.network_policy import NetworkSettings, bridge
from app.modules.host_agent.infrastructure.network_firewall import NetworkFirewall
from app.modules.host_agent.infrastructure.operator_networks import OperatorNetworks
from app.modules.host_agent.infrastructure.runtime_effects import NativeEffects
from app.modules.host_agent.infrastructure.stop_registry import StopRegistry


class ConnectedQualification(Qualification):
    def __init__(self):
        super().__init__()
        self.settings = NetworkSettings(
            ipv4_pool="10.246.0.0/16",
            ipv6_pool="fd47:6570:7000::/48",
            first_project=1,
            gateway_uid=pwd.getpwnam("epm-caddy").pw_uid,
            tunnel_uid=pwd.getpwnam("epm-tunnel").pw_uid,
            proxy_uid=pwd.getpwnam("epm-proxy").pw_uid,
        )
        self.firewall = NetworkFirewall(self.settings)
        self.records = {}
        self.commands = {}
        self.networks = OperatorNetworks(
            SimpleNamespace(
                network_projection=lambda: NetworkProjection(records=tuple(self.records.values()))
            ),
            self.engine,
            self.firewall,
            self.settings,
        )

    def allocate(self, owner):
        allocation = super().allocate(owner)
        cmd = command(allocation)
        self.commands[allocation.binding_id] = cmd
        scope = cmd.effect.parent.scope
        self.records[allocation.binding_id] = NetworkRecord(
            binding_id=allocation.binding_id,
            operator_id=scope.operator_id,
            workspace_id=scope.workspace_id,
            resource_generation=allocation.resource_generation,
            workspace_project=allocation.workspace_project,
        )
        self.networks.prepare(cmd, allocation)
        return allocation

    def actor(self, allocation, mode, tree="/workspace"):
        cmd = self.commands[allocation.binding_id]
        target = self.networks.verify(cmd, allocation)
        spec = container_spec(cmd, allocation, self.targets, self.profile, network=target)
        spec["Cmd"] = ["python", "-B", "/actor.py", mode, tree]
        identity = self.engine.create(cmd, spec)
        try:
            self.networks.verify_container(target, self.engine.inspect(identity))
            result = subprocess.run(
                ["/usr/bin/docker", "start", "-a", identity],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            return json.loads(result.stdout.splitlines()[-1])
        finally:
            self.engine.stop(identity)
            self.engine.remove_stopped(identity)

    def lifecycle(self, allocation):
        cmd = self.commands[allocation.binding_id]
        directory = self.lab.root / "connected-stops"
        directory.mkdir(mode=0o700)
        stops = StopRegistry(directory)
        observations = []
        # Explicit synthetic native authority checks *this* connected policy hash.
        # H04 admission is deliberately not substituted into production composition.
        expected = self.networks.qualification_hash(policy_hash(self.profile))

        def verified(command, target, policy_hash):
            assert command == cmd and policy_hash == expected

        driver = NativeEffects(
            self.storage,
            self.engine,
            self.profile,
            SimpleNamespace(verify=verified, verify_runtime=verified),
            SimpleNamespace(record=lambda *a: observations.append(True) or "native-connected"),
            stops=stops,
            networks=self.networks,
        )
        spec = driver._spec(cmd, allocation)
        spec["Cmd"] = ["python", "-B", "/actor.py", "hold"]
        identity = self.engine.create(cmd, spec)
        current = allocation.model_copy(update={"container_ref": identity})
        try:
            with stops.owner_lease() as ready:
                ready()
                assert driver.apply(cmd, current).resource_state == "running"
                assert driver.supervise(cmd, current) == "running"
                self.firewall._run(["delete", "table", "inet", "epm_h02"])
                assert driver.supervise(cmd, current) == "needs_attention"
                assert not self.engine.inspect(identity)["State"]["Running"]
        finally:
            stops.contain_all(self.engine)
            self.engine.remove_stopped(identity)
        return {
            "new_qualification_hash": expected,
            "connected_start_and_inspection": True,
            "firewall_loss_stops_runtime": True,
        }

    def run_connected(self):
        first, second = self.allocate(0), self.allocate(1)
        cases = self.results["cases"]
        try:
            cases["connected_security_and_wal"] = self.actor(first, "security")
            for role in ("workspace", "control", "scratch"):
                path = "/control/data" if role == "control" else "/" + role
                for mode in ("bytes", "inodes", "deleted"):
                    cases[role + "_" + mode] = self.actor(first, mode, path)
                    self.clear_fill(first, role)
            cases["connected_wal_full"] = self.actor(second, "wal")
            cases["cross_uid"] = self.cross_uid(first, second)
            cases["connected_guarded_lifecycle"] = self.lifecycle(first)
            self.results["status"] = "connected_sandbox_pass"
        except Exception:
            self.results["status"] = "failed"
            raise
        finally:
            for row in self.records.values():
                target = bridge(row, self.settings)
                self.engine.remove_empty_network(target.name)
            self.results["source_sha256"] = sha256(Path(__file__).read_bytes()).hexdigest()
            (self.lab.root / "h02-connected-result.json").write_text(
                json.dumps(self.results, indent=2) + "\n"
            )
        print(self.lab.root / "h02-connected-result.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, action="store_true")
    parser.parse_args()
    value = ConnectedQualification()
    print(value.lab.root, flush=True)
    value.run_connected()

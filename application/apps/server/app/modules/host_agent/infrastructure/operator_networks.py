"""Inventory-derived bridge setup and reinspection at every guarded runtime boundary."""

from dataclasses import asdict
from hashlib import sha256
import json

from app.modules.host_agent.application.dispatch import HostAgentDenied, HostAgentUnavailable
from app.modules.host_agent.infrastructure.network_policy import bridge
from app.modules.host_agent.infrastructure.network_prerequisites import HostNetworkPrerequisites


class OperatorNetworks:
    def __init__(self, inventory, engine, firewall, settings, *, prerequisites=None):
        self.inventory, self.engine, self.firewall, self.settings = (
            inventory,
            engine,
            firewall,
            settings,
        )
        self.prerequisites = prerequisites or HostNetworkPrerequisites(engine, settings)

    def qualification_hash(self, runtime_hash):
        # A network-none H02.5 native proof cannot qualify a new connected policy.
        document = {
            "version": "operator-network-v1",
            "runtime": runtime_hash,
            "settings": asdict(self.settings),
        }
        return sha256(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _current(self, command, allocation):
        projection = self.inventory.network_projection()
        matches = [row for row in projection.records if row.binding_id == allocation.binding_id]
        if len(matches) != 1:
            raise HostAgentDenied()
        row = matches[0]
        scope = command.effect.parent.scope
        if (
            row.operator_id != scope.operator_id
            or row.workspace_id != scope.workspace_id
            or row.resource_generation != allocation.resource_generation
            or row.workspace_project != allocation.workspace_project
            or command.effect.binding_id != row.binding_id
            or command.effect.resource_generation != row.resource_generation
        ):
            raise HostAgentDenied()
        targets = tuple(bridge(item, self.settings) for item in projection.records)
        return bridge(row, self.settings), targets

    def prepare(self, command, allocation):
        target, all_targets = self._current(command, allocation)
        # Deny reserved bridges before creating one. Caller holds inventory singleton.
        self.prerequisites.verify(all_targets)
        self.firewall.apply(all_targets)
        existing = self.engine.inspect_network(target.name)
        if existing is None:
            self.engine.create_network(target)
        else:
            # Never adopt a mismatched preexisting network or mutate it into compliance.
            target.verify(existing)
        return self.verify(command, allocation)

    def verify(self, command, allocation):
        target, all_targets = self._current(command, allocation)
        self.prerequisites.verify(all_targets)
        self.firewall.verify(all_targets)
        target.verify(self.engine.inspect_network(target.name))
        return target

    @staticmethod
    def verify_container(target, actual):
        peers = actual.get("NetworkSettings", {}).get("Networks", {})
        if set(peers) != {target.name}:
            raise HostAgentDenied()
        peer = peers[target.name]
        config = peer.get("IPAMConfig") or {}
        if (
            config.get("IPv4Address") != target.address4
            or config.get("IPv6Address") != target.address6
        ):
            raise HostAgentDenied()
        if not actual["State"]["Running"]:
            # Docker leaves assigned addresses blank until start. The stopped
            # create/pre-start check must still verify the explicit static request.
            return
        if (
            peer.get("IPAddress") != target.address4
            or peer.get("GlobalIPv6Address") != target.address6
        ):
            raise HostAgentUnavailable()

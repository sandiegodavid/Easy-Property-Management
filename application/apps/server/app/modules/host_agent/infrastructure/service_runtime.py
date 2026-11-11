"""Root-only host ingress services. No provisioning, admission, start or public HTTP API."""

import argparse
import os
from pathlib import Path
import pwd


from app.modules.host_agent.application.dispatch import HostAgentUnavailable, HostAgentDenied
from app.modules.host_agent.infrastructure.docker_engine import DockerEngine
from app.modules.host_agent.infrastructure.gateway import GatewaySettings, CaddyAdmin, closed_config
from app.modules.host_agent.infrastructure.ingress_bootstrap import (
    IngressBootstrap,
    ProjectionPublisher,
)
from app.modules.host_agent.infrastructure.inventory import Inventory
from app.modules.host_agent.infrastructure.network_firewall import NetworkFirewall
from app.modules.host_agent.infrastructure.network_policy import bridge
from app.modules.host_agent.infrastructure.network_prerequisites import HostNetworkPrerequisites
from app.modules.host_agent.infrastructure.stop_registry import StopRegistry
from app.modules.host_agent.infrastructure.tunnel_credentials import (
    protected_bytes,
    validate_tunnel_credential,
)

from app.modules.host_agent.infrastructure.service_config import ServiceInputs


def no_allocations():
    # This composition is read-only inventory authority, not the allocator/dispatcher.
    raise HostAgentUnavailable()


class ServiceRuntime:
    def __init__(self, inputs):
        self.inputs, self.layout = inputs, inputs.layout
        self.engine = DockerEngine()
        self.stops = StopRegistry(Path(self.layout.stops))
        self.firewall = NetworkFirewall(inputs.network)

    def inventory(self):
        return Inventory(
            Path(self.layout.inventory),
            application_directory=Path(self.layout.application),
            identity=self.inputs.metadata,
            uids=self.inputs.uids,
            gids=self.inputs.gids,
            projects=self.inputs.projects,
            public_domain=self.inputs.public_domain,
            system_ids=no_allocations,
        )

    def contain(self):
        self.stops.contain_all(self.engine)

    def run(self, action):
        try:
            if action == "contain":
                self.contain()
                return
            inventory = self.inventory()
            if action == "network":
                with inventory.exclusive():
                    targets = tuple(
                        bridge(row, self.inputs.network)
                        for row in inventory.network_projection().records
                    )
                    HostNetworkPrerequisites(self.engine, self.inputs.network).verify(targets)
                    self.firewall.apply(targets)
                return
            gateway = GatewaySettings(
                Path(self.layout.gateway_runtime) / "admin.sock",
                self.inputs.network.gateway_uid,
                self.inputs.network.gateway_port,
            )
            if action == "verify":
                with inventory.exclusive():
                    targets = tuple(
                        bridge(row, self.inputs.network)
                        for row in inventory.network_projection().records
                    )
                    self.firewall.verify(targets)
                    if CaddyAdmin(gateway).inspect() != closed_config(
                        inventory.ingress_projection(), gateway
                    ):
                        raise HostAgentUnavailable()
                return
            if action != "refresh":
                raise HostAgentDenied()
            gateway_identity = pwd.getpwnam("epm-caddy")
            tunnel_identity = pwd.getpwnam("epm-tunnel")
            proxy_identity = pwd.getpwnam("epm-proxy")
            if (
                gateway_identity.pw_uid != self.inputs.network.gateway_uid
                or tunnel_identity.pw_uid != self.inputs.network.tunnel_uid
                or proxy_identity.pw_uid != self.inputs.network.proxy_uid
            ):
                raise HostAgentDenied()
            validate_tunnel_credential(
                Path(self.layout.tunnel_secret), self.inputs.tunnel.tunnel_id
            )
            IngressBootstrap(
                inventory,
                gateway,
                self.inputs.tunnel,
                ProjectionPublisher(
                    Path(self.layout.gateway_projection), reader_gid=gateway_identity.pw_gid
                ),
                ProjectionPublisher(
                    Path(self.layout.tunnel_projection), reader_gid=tunnel_identity.pw_gid
                ),
                contain_all=self.contain,
            ).refresh()
            ProjectionPublisher(
                Path(self.layout.proxy_projection), reader_gid=proxy_identity.pw_gid
            ).publish(
                {
                    "hosts": self.inputs.outbound_hosts,
                    "port": self.inputs.network.proxy_port,
                    "uid": self.inputs.network.proxy_uid,
                }
            )
        except Exception as original:
            try:
                self.contain()
            except Exception as failure:
                raise ExceptionGroup(
                    "Host ingress requires attention.", [original, failure]
                ) from None
            raise


def load_inputs(path):
    # Protected non-secret setup inputs have an independent 32-KiB bound.
    return ServiceInputs.model_validate_json(protected_bytes(path, limit=32768))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("network", "refresh", "verify", "contain"))
    parser.add_argument("--config", type=Path, default=Path("/etc/epm/host-services.json"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.exit(3, "The protected host service is unavailable.\n")
    try:
        inputs = load_inputs(args.config)
        if Path(inputs.layout.config) != args.config:
            raise HostAgentDenied()
        ServiceRuntime(inputs).run(args.action)
    except Exception:
        parser.exit(3, "Host ingress requires attention.\n")


if __name__ == "__main__":
    main()

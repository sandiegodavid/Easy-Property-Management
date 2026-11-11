"""Protected root service inputs, never a public provisioning or Operator contract."""

from pathlib import Path
from typing import Annotated
from pydantic import Field, model_validator, StrictStr
from app.modules.host_agent.application.build_inputs import PrincipalRange
from app.modules.host_agent.infrastructure.host_services import TunnelSettings
from app.modules.host_agent.infrastructure.network_policy import NetworkSettings
from app.modules.host_agent.infrastructure.schema_store import HostMetadata
from app.platform.hosted_contracts.values import Contract

Absolute = Annotated[str, Field(pattern=r"^/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+$")]


class ServiceLayout(Contract):
    inventory: Absolute
    application: Absolute
    stops: Absolute
    data: Absolute
    gateway_runtime: Absolute = "/run/epm-caddy"
    gateway_projection: Absolute = "/run/epm-projections/caddy"
    proxy_runtime: Absolute = "/run/epm-proxy"
    proxy_projection: Absolute = "/run/epm-projections/proxy"
    tunnel_runtime: Absolute = "/run/epm-tunnel"
    tunnel_projection: Absolute = "/run/epm-projections/tunnel"
    tunnel_secret: Absolute = "/etc/epm/secrets/tunnel.json"
    installation: Absolute = "/opt/epm/host-agent"
    tools: Absolute = "/opt/epm/tools"
    config: Absolute = "/etc/epm/host-services.json"

    @model_validator(mode="after")
    def canonical_paths(self):
        for name in type(self).model_fields:
            value = getattr(self, name)
            if str(Path(value)) != value or ".." in Path(value).parts:
                raise ValueError("Protected canonical absolute paths are required.")
        return self


class ServiceInputs(Contract):
    version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    layout: ServiceLayout
    metadata: HostMetadata
    uids: PrincipalRange
    gids: PrincipalRange
    projects: PrincipalRange
    public_domain: Annotated[str, Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)+$")]
    network: NetworkSettings
    tunnel: TunnelSettings
    outbound_hosts: Annotated[tuple[StrictStr, ...], Field(max_length=64)] = ()

    @model_validator(mode="after")
    def separated_authorities(self):
        from app.modules.host_agent.infrastructure.endpoint_policy import EndpointPolicy

        EndpointPolicy(self.outbound_hosts)
        if self.network.gateway_port != self.tunnel.gateway_port:
            raise ValueError("Gateway and Tunnel ports must match.")
        for uid in self.network.uids:
            if self.uids.first <= uid <= self.uids.last:
                raise ValueError("Host service principals must be outside the Operator UID range.")
        return self

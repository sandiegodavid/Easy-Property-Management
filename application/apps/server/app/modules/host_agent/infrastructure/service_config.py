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
IdentityPrincipal = Annotated[int, Field(strict=True, gt=0)]
IDENTITY_RELAY_DIRECTORY = Path("/run/epm-identity-relay")


class IdentityRelaySettings(Contract):
    central_uid: IdentityPrincipal
    central_gid: IdentityPrincipal
    central_return_directory: Absolute | None = None
    source_return_directory: Absolute | None = None

    @model_validator(mode="after")
    def paired_returns(self):
        if (self.central_return_directory is None) != (self.source_return_directory is None):
            raise ValueError(
                "The two identity return socket directories must be configured together."
            )
        return self


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
    backup_proxy_runtime: Absolute = "/run/epm-backup-proxy"
    backup_proxy_projection: Absolute = "/run/epm-projections/backup-proxy"
    backup_proxy_secret: Absolute = "/etc/epm/secrets/r2.json"
    backup_proxy_config: Absolute = "/etc/epm/backup-proxy.json"
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
    auth_registration: Absolute | None = None
    identity_socket_root: Absolute = "/run/epm-source-identity"
    identity_relay: IdentityRelaySettings | None = None
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
        if self.identity_relay is not None:
            uid, gid = self.identity_relay.central_uid, self.identity_relay.central_gid
            if (
                self.auth_registration is None
                or uid in self.network.uids
                or self.uids.first <= uid <= self.uids.last
                or self.gids.first <= gid <= self.gids.last
            ):
                raise ValueError("The identity relay requires a separate central principal.")
        return self

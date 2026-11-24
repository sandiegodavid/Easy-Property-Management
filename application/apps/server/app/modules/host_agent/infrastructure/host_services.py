"""Protected host service candidates. Rendering never installs services or grants access."""

from typing import Annotated

from pydantic import Field

from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.host_agent.application.ingress import IngressProjection
from app.platform.hosted_contracts.values import CanonicalId, Contract


class TunnelSettings(Contract):
    tunnel_id: CanonicalId
    gateway_port: Annotated[int, Field(strict=True, ge=1024, le=65535)] = 8080


def tunnel_config(projection: IngressProjection, settings: TunnelSettings, *, shared=None):
    # JSON is valid YAML for cloudflared. No wildcard route or origin Host override;
    # the request's original Host and HTTPS context reach Caddy unchanged.
    origins = [row.public_origin for row in projection.records]
    if shared is not None:
        origins.extend((shared.central_origin, shared.admin_origin))
    return {
        "tunnel": settings.tunnel_id,
        "credentials-file": "/run/credentials/epm-tunnel.service/tunnel.json",
        "no-autoupdate": True,
        "ingress": [
            {
                "hostname": origin.removeprefix("https://"),
                "service": f"http://127.0.0.1:{settings.gateway_port}",
            }
            for origin in origins
        ]
        + [{"service": "http_status:403"}],
    }


def service_unit(component, layout=None):
    from app.modules.host_agent.infrastructure.service_config import ServiceLayout

    if layout is None:
        layout = ServiceLayout(
            inventory="/var/lib/epm/inventory/inventory.sqlite",
            application="/opt/epm/app",
            stops="/var/lib/epm/stops",
            data="/var/lib/epm/data",
        )
    if component not in {"gateway", "tunnel", "egress", "network", "projection", "backup_proxy"}:
        raise HostAgentDenied()
    python = layout.installation + "/bin/python"
    runner = python + " -B -m app.modules.host_agent.infrastructure.service_runtime"
    config = " --config " + layout.config
    containment = (
        python
        + " -B -m app.modules.host_agent.infrastructure.supervisor --registry "
        + layout.stops
        + " --contain-all"
    )
    if component == "backup_proxy":
        command = python + " -B -m app.modules.host_agent.infrastructure.backup_proxy"
        return f"""[Unit]
Description=EPM private off-host backup proxy
After=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
User=epm-backup-proxy
Group=epm-backup-proxy
RuntimeDirectory=epm-backup-proxy
RuntimeDirectoryMode=0711
ExecStart={command}
LoadCredential=r2.json:{layout.backup_proxy_secret}
LoadCredential=backup-proxy.json:{layout.backup_proxy_config}
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=yes
CapabilityBoundingSet=
AmbientCapabilities=
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictNamespaces=yes
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictRealtime=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ProcSubset=pid
ProtectProc=invisible
ReadWritePaths={layout.backup_proxy_runtime}
ReadOnlyPaths=/run/epm-projections/backup-proxy
InaccessiblePaths={layout.data}/workspace {layout.data}/control {layout.data}/scratch {layout.stops} -/run/docker.sock {path_parent(layout.tunnel_secret)} {layout.gateway_runtime} {layout.tunnel_runtime} {layout.proxy_runtime} -/run/credentials/epm-tunnel.service
LimitNOFILE=1024
TasksMax=64
MemoryMax=256M
CPUQuota=100%
TimeoutStartSec=30
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
"""
    if component in {"network", "projection"}:
        action = "network" if component == "network" else "refresh"
        prepare = "ExecStartPre=/usr/sbin/modprobe br_netfilter\n" if component == "network" else ""
        ordering = (
            "Requires=epm-network-policy.service\nAfter=epm-network-policy.service\n"
            if component == "projection"
            else ""
        )
        return f"""[Unit]
Description=EPM protected ingress {component}
{ordering}
Before=epm-gateway.service epm-tunnel.service

[Service]
Type=oneshot
User=root
{prepare}ExecStart={runner} {action}{config}
ExecStopPost={containment}
RemainAfterExit=yes
TimeoutStartSec=30
TimeoutStopSec=30
"""
    if component == "gateway":
        user = "epm-caddy"
        command = layout.tools + "/caddy run --config " + layout.gateway_projection + "/config.json"
        runtime = layout.gateway_runtime
        credential = ""
        extra_hidden = "-/run/credentials/epm-tunnel.service " + layout.tunnel_runtime
    elif component == "tunnel":
        user = "epm-tunnel"
        command = (
            layout.tools
            + "/cloudflared tunnel --config "
            + layout.tunnel_projection
            + "/config.json --no-autoupdate run"
        )
        runtime = layout.tunnel_runtime
        credential = "LoadCredential=tunnel.json:" + layout.tunnel_secret + "\n"
        extra_hidden = layout.gateway_runtime
    else:
        user = "epm-proxy"
        command = (
            python
            + " -B -m app.modules.host_agent.infrastructure.egress_proxy --policy "
            + layout.proxy_projection
            + "/config.json"
        )
        runtime = layout.proxy_runtime
        credential = ""
        extra_hidden = (
            layout.gateway_runtime
            + " "
            + layout.tunnel_runtime
            + " -/run/credentials/epm-tunnel.service"
        )
    service_type = "notify" if component == "gateway" else "simple"
    return f"""[Unit]
Description=EPM private {component}
Requires=epm-network-policy.service epm-ingress-projection.service
After=network-online.target epm-network-policy.service epm-ingress-projection.service
{"After=epm-gateway.service" if component in {"egress", "tunnel"} else ""}
BindsTo=epm-network-policy.service
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type={service_type}
User={user}
Group={user}
ExecStartPre=+{runner} refresh{config}
ExecStart={command}
ExecStopPost=+{containment}
{credential}Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=yes
CapabilityBoundingSet=
AmbientCapabilities=
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictNamespaces=yes
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictRealtime=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ProcSubset=pid
ProtectProc=invisible
ReadWritePaths={runtime}
InaccessiblePaths={layout.data} {path_parent(layout.inventory)} {layout.stops} -/run/docker.sock {path_parent(layout.tunnel_secret)} {extra_hidden}
LimitNOFILE=1024
TasksMax=64
MemoryMax=256M
CPUQuota=100%
TimeoutStartSec=30
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
"""


def path_parent(value):
    from pathlib import Path

    return str(Path(value).parent)

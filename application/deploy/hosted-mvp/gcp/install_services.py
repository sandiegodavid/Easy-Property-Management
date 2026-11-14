"""Protected empty-host service installation; no operators, admissions or application starts."""

import argparse
import base64
import json
import os
from pathlib import Path
import pwd
import subprocess
from tempfile import TemporaryDirectory
import time
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import create_engine
from app.modules.host_agent.infrastructure.host_services import service_unit, TunnelSettings
from app.modules.host_agent.infrastructure.network_policy import NetworkSettings
from app.modules.host_agent.infrastructure.schema_store import HostMetadata, bind_host
from app.modules.host_agent.infrastructure.service_config import ServiceInputs, ServiceLayout
from app.modules.host_agent.infrastructure.tunnel_credentials import validate_tunnel_credential
from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.host_agent.application.build_inputs import PrincipalRange
from app.modules.hosted_admin.infrastructure.project_quota import verify_project_filesystem
from app.platform.config import application_root
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore

ROOT = Path("/srv/epm/data/host")


def call(*args):
    return subprocess.run(
        [str(a) for a in args], check=True, capture_output=True, text=True, timeout=120
    ).stdout.strip()


def directory(path, mode, uid=0, gid=0):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if path.resolve(strict=True) != path:
        raise ValueError("Canonical protected directories are required")
    os.chown(path, uid, gid)
    path.chmod(mode)
    return path


def account(name):
    try:
        value = pwd.getpwnam(name)
    except KeyError:
        call("useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", name)
        value = pwd.getpwnam(name)
    if value.pw_uid == 0 or value.pw_shell != "/usr/sbin/nologin":
        raise ValueError("A separate non-login host service principal is required")
    return value


def canonical_credential(data):
    # cloudflared's generated document includes an empty Endpoint. Do not pass
    # provider-only fields or an alternate endpoint into the protected runtime.
    try:
        value = json.loads(data)
        if isinstance(value, dict) and value.get("Endpoint") == "":
            value.pop("Endpoint")
        if not isinstance(value, dict) or set(value) != {"AccountTag", "TunnelSecret", "TunnelID"}:
            raise ValueError
        return json.dumps(value, sort_keys=True).encode()
    except Exception:
        raise HostAgentDenied() from None


def publish_credential(destination, data, tunnel_id):
    directory(destination.parent, 0o700)
    # Validate in a private staging directory before the final name exists. A
    # failed fetch/validation must not poison a later setup retry.
    with TemporaryDirectory(prefix=".tunnel-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "credential.json"
        with staged.open("xb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(canonical_credential(data))
            output.flush()
            os.fsync(output.fileno())
        validate_tunnel_credential(staged, tunnel_id)
        # Publish without overwriting an existing protected credential.
        os.link(staged, destination, follow_symlinks=False)
        staged.unlink()
    descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def credential(project, tunnel_id):
    # The host account can access only this exact secret. Token/secret never enter
    # command strings, unit environments, logs, metadata or return values.
    request = Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with urlopen(request, timeout=10) as response:
        token = json.loads(response.read(65536))["access_token"]
    url = f"https://secretmanager.googleapis.com/v1/projects/{project}/secrets/epm-tunnel-{tunnel_id}/versions/1:access"
    request = Request(url, headers={"Authorization": "Bearer " + token})
    with urlopen(request, timeout=10) as response:
        data = base64.b64decode(json.loads(response.read(65536))["payload"]["data"], validate=True)
    destination = Path("/etc/epm/secrets/tunnel.json")
    publish_credential(destination, data, tunnel_id)
    validate_tunnel_credential(destination, tunnel_id)


def install(project, domain, tunnel_id):
    if os.geteuid() != 0 or os.environ.get("EPM_H02_QUALIFICATION") != "1":
        raise ValueError("Explicit protected qualification setup is required")
    disk = json.loads(Path("/etc/epm/bootstrap/data.json").read_text())
    if disk["phase"] != "ready":
        raise ValueError("Retained data disk is not ready")
    verify_project_filesystem(
        ROOT.parent,
        disk["uuid"],
        required_options={"rw", "prjquota", "nodev", "nosuid", "noexec"},
    )
    directory(ROOT, 0o700)
    metadata_path = ROOT / "metadata.json"
    if metadata_path.exists():
        metadata = HostMetadata.model_validate_json(metadata_path.read_text())
        if metadata.filesystem_identity != "gcp-data:" + disk["uuid"]:
            raise ValueError("Original host filesystem identity changed")
    else:
        metadata = HostMetadata(
            host_id=str(uuid4()),
            deployment_id=str(uuid4()),
            filesystem_identity="gcp-data:" + disk["uuid"],
            agent_contract_version="host-agent-v1",
            created_at=time.time_ns() // 1000000,
        )
        with metadata_path.open("x") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(metadata.model_dump_json())
    inventory = ROOT / "inventory/inventory.sqlite"
    directory(inventory.parent, 0o700)
    initialize_store(
        HostedStore.HOST_INVENTORY, inventory, application_directory=application_root()
    )
    engine = create_engine(f"sqlite:///{inventory}")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            bind_host(connection, metadata, application_directory=application_root())
            connection.commit()
    finally:
        engine.dispose()
    stops = directory(ROOT / "stops", 0o700)
    identities = [account(name) for name in ("epm-caddy", "epm-tunnel", "epm-proxy")]
    layout = ServiceLayout(
        inventory=str(inventory),
        application=str(application_root()),
        stops=str(stops),
        data="/srv/epm/data",
    )
    config = ServiceInputs(
        layout=layout,
        metadata=metadata,
        uids=PrincipalRange(first=100000, last=165535),
        gids=PrincipalRange(first=100000, last=165535),
        projects=PrincipalRange(first=1001, last=65535),
        public_domain=domain,
        network=NetworkSettings(
            "10.246.0.0/16", "fd47:6570:7000::/48", 1001, *(i.pw_uid for i in identities)
        ),
        tunnel=TunnelSettings(tunnel_id=tunnel_id),
    )
    directory("/etc/epm", 0o700)
    path = Path(layout.config)
    if path.exists() and path.read_text() != config.model_dump_json():
        raise ValueError("Protected service config changed; explicit review is required")
    path.write_text(config.model_dump_json())
    path.chmod(0o600)
    if not Path(layout.tunnel_secret).exists():
        credential(project, tunnel_id)
    validate_tunnel_credential(Path(layout.tunnel_secret), tunnel_id)
    publish_units(config, identities)


def installation_unit(component, layout):
    # Egress and Tunnel both refresh the same exclusively locked inventory before
    # startup. Order them on boot instead of depending on a failed-start retry.
    ordering = "After=epm-egress.service\n" if component == "tunnel" else ""
    unit = service_unit(component, layout).replace(
        "[Unit]\n",
        "[Unit]\nRequires=srv-epm-data.mount\nAfter=srv-epm-data.mount\n" + ordering,
    )
    if component == "gateway":
        unit += (
            "\n[Service]\nEnvironment=XDG_DATA_HOME="
            + layout.gateway_runtime
            + "\nEnvironment=XDG_CONFIG_HOME="
            + layout.gateway_runtime
            + "\n"
        )
    return unit


def publish_units(config, identities):
    layout = config.layout
    tmpfiles = ["d /run/epm-projections 0755 root root -"]
    for name, identity in zip(("caddy", "tunnel", "proxy"), identities, strict=True):
        runtime = {
            "caddy": layout.gateway_runtime,
            "tunnel": layout.tunnel_runtime,
            "proxy": layout.proxy_runtime,
        }[name]
        projection = {
            "caddy": layout.gateway_projection,
            "tunnel": layout.tunnel_projection,
            "proxy": layout.proxy_projection,
        }[name]
        tmpfiles.extend(
            [
                f"d {runtime} 0700 {identity.pw_name} {identity.pw_name} -",
                f"d {projection} 0750 root {identity.pw_name} -",
            ]
        )
    Path("/etc/tmpfiles.d/epm-host.conf").write_text("\n".join(tmpfiles) + "\n")
    call("systemd-tmpfiles", "--create", "/etc/tmpfiles.d/epm-host.conf")
    for component, name in {
        "network": "network-policy",
        "projection": "ingress-projection",
        "gateway": "gateway",
        "tunnel": "tunnel",
        "egress": "egress",
    }.items():
        Path(f"/etc/systemd/system/epm-{name}.service").write_text(
            installation_unit(component, layout)
        )
    runner = (
        layout.installation + "/bin/python -B -m app.modules.host_agent.infrastructure.supervisor"
    )
    guardian = f"""[Unit]
Description=EPM single containment-only runtime guardian
Requires=docker.service srv-epm-data.mount
After=docker.service srv-epm-data.mount epm-network-policy.service
[Service]
Type=simple
User=root
UMask=0077
ExecStart={runner} --registry {layout.stops}
ExecStopPost={runner} --registry {layout.stops} --contain-all
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths={layout.stops}
PrivateTmp=yes
LimitCORE=0
TasksMax=32
MemoryMax=256M
[Install]
WantedBy=multi-user.target
"""
    Path("/etc/systemd/system/epm-host-guardian.service").write_text(guardian)
    call("systemctl", "daemon-reload")
    call(
        "systemctl",
        "enable",
        "epm-gateway.service",
        "epm-tunnel.service",
        "epm-egress.service",
        "epm-host-guardian.service",
    )
    call("systemctl", "start", "epm-network-policy.service", "epm-ingress-projection.service")
    for name in (
        "epm-gateway.service",
        "epm-egress.service",
        "epm-tunnel.service",
        "epm-host-guardian.service",
    ):
        call("systemctl", "start", name)
    print("Protected empty inventory and closed services installed; admission unavailable.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--tunnel-id", required=True)
    args = parser.parse_args()
    install(args.project, args.domain, args.tunnel_id)

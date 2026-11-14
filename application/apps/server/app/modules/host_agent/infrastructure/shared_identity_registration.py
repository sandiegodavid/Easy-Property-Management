"""Resolve shared identity only from protected registration and running host evidence."""

import base64
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import ssl
import subprocess
import sys
from typing import Annotated

from pydantic import Field, model_validator

from app.modules.host_agent.application.auth_routes import SharedIdentityManifest
from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.host_agent.infrastructure.auth_projection import VerifiedAuthEndpoint
from app.modules.host_agent.infrastructure.endpoint_policy import hostname
from app.modules.host_agent.infrastructure.network_policy import bridge
from app.modules.host_agent.infrastructure.network_prerequisites import HostNetworkPrerequisites
from app.modules.host_agent.infrastructure.operator_networks import OperatorNetworks
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import Contract, RequestHash

ASSET = r"^/assets/[A-Za-z0-9_-]{1,100}\.(?:js|css)$"


class IdentityAsset(Contract):
    path: Annotated[str, Field(pattern=ASSET)]
    sha256: RequestHash


class SharedRegistration(Contract):
    manifest: SharedIdentityManifest
    manifest_sha256: RequestHash
    container_id: RequestHash
    image_config_sha256: RequestHash
    runtime_uid: Annotated[int, Field(strict=True, gt=0)]
    runtime_gid: Annotated[int, Field(strict=True, gt=0)]
    admin_database: Path
    firebase_project: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")]
    tls_name: str
    trust_pem: Annotated[str, Field(max_length=8192)]
    admin_index_sha256: RequestHash
    admin_assets: Annotated[tuple[IdentityAsset, ...], Field(min_length=1, max_length=16)]
    central_assets: Annotated[tuple[IdentityAsset, ...], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def exact_registration(self):
        if semantic_hash(self.manifest) != self.manifest_sha256:
            raise ValueError("Shared identity manifest pin does not match.")
        for assets in (self.admin_assets, self.central_assets):
            paths = {asset.path for asset in assets}
            if len(paths) != len(assets) or not any(path.endswith(".js") for path in paths):
                raise ValueError("Shared identity assets must have exact unique paths.")
        hostname(self.tls_name)
        # Only a single certificate, not additional roots or trailing material.
        if not re.fullmatch(
            r"-----BEGIN CERTIFICATE-----\n[A-Za-z0-9+/=\n]+\n-----END CERTIFICATE-----\n?",
            self.trust_pem,
        ):
            raise ValueError("Use a single PEM trust anchor.")
        ssl.PEM_cert_to_DER_cert(self.trust_pem)
        if not self.admin_database.is_absolute() or ".." in self.admin_database.parts:
            raise ValueError("Use the protected Admin store path.")
        return self


def owning_login_origin(path, deployment_id, uid):
    path = Path(path)
    if path.resolve(strict=True) != path:
        raise HostAgentDenied()
    info = path.lstat()
    if not path.is_file() or info.st_uid != uid or info.st_mode & 0o077 or info.st_nlink != 1:
        raise HostAgentDenied()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)) as connection:
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            "SELECT deployment_id, login_origin FROM control_meta WHERE id=1"
        ).fetchmany(2)
    if len(rows) != 1 or rows[0][0] != deployment_id:
        raise HostAgentDenied()
    return rows[0][1]


def verify_running_container(engine, target, registration):
    network = engine.inspect_network(target.name)
    target.verify(network)
    if set(network.get("Containers", {})) != {registration.container_id}:
        raise HostAgentDenied()
    actual = engine.inspect(registration.container_id)
    config = actual.get("Config", {}) if actual else {}
    host = actual.get("HostConfig", {}) if actual else {}
    artifact = "sha256:" + registration.manifest.artifact_sha256
    reference = config.get("Image", "")
    if reference != artifact and (
        reference.count("@") != 1
        or not reference.split("@", 1)[0]
        or reference.split("@", 1)[1] != artifact
    ):
        raise HostAgentDenied()
    if (
        not actual
        or actual.get("Id") != registration.container_id
        or actual.get("Image") != "sha256:" + registration.image_config_sha256
        or config.get("User") != f"{registration.runtime_uid}:{registration.runtime_gid}"
        or actual.get("State", {}).get("Running") is not True
        or host.get("Privileged")
        or host.get("PortBindings")
        or host.get("PublishAllPorts")
        or host.get("CapAdd")
        or set(host.get("CapDrop") or ()) != {"ALL"}
        or host.get("ReadonlyRootfs") is not True
        or not any(
            option in {"no-new-privileges", "no-new-privileges:true"}
            for option in host.get("SecurityOpt") or ()
        )
    ):
        raise HostAgentDenied()
    verify_runtime_mounts(actual)
    OperatorNetworks.verify_container(target, actual)


def verify_runtime_mounts(actual):
    protected_roots = ("/control", "/run/epm-identity-relay", "/run/epm-central-identity")
    for mount in actual.get("Mounts", ()):
        destination = mount.get("Destination", "")
        if destination == "/tmp" and mount.get("Type") == "tmpfs":
            continue
        if mount.get("Type") != "bind" or not any(
            destination == root or destination.startswith(root + "/") for root in protected_roots
        ):
            raise HostAgentDenied()
    tmpfs = actual.get("HostConfig", {}).get("Tmpfs") or {}
    if set(tmpfs) - {"/tmp"}:
        raise HostAgentDenied()


def probe_as_gateway(registration, target, uid):
    # Use the same kernel UID as Caddy while preventing root from taking an
    # alternate route and preventing any browser-supplied probe target.
    probe = subprocess.run(
        [sys.executable, "-B", "-m", "app.modules.host_agent.infrastructure.shared_identity_probe"],
        user=uid,
        extra_groups=[],
        input=(registration.model_dump_json() + "\n" + target.address4).encode(),
        capture_output=True,
        timeout=15,
        check=False,
    )
    if probe.returncode or probe.stdout != b"verified\n":
        raise HostAgentDenied()


class SharedIdentityRegistration:
    def __init__(self, inventory, engine, firewall, settings, registration):
        self.inventory, self.engine, self.firewall = inventory, engine, firewall
        self.settings, self.registration = settings, registration

    def resolve(self):
        registration = self.registration
        shared = self.settings.shared_identity
        if shared is None or shared.endpoint_id != registration.manifest.private_endpoint_id:
            raise HostAgentDenied()
        target = shared.bridge()
        operators = tuple(
            bridge(row, self.settings) for row in self.inventory.network_projection().records
        )
        HostNetworkPrerequisites(self.engine, self.settings).verify(operators)
        self.firewall.verify(operators)
        verify_running_container(self.engine, target, registration)
        login_origin = owning_login_origin(
            registration.admin_database,
            self.inventory.identity.deployment_id,
            registration.runtime_uid,
        )
        if login_origin != registration.manifest.central_origin:
            raise HostAgentDenied()
        probe_as_gateway(registration, target, self.settings.gateway_uid)
        return (
            VerifiedAuthEndpoint(
                registration.manifest,
                target.address4,
                8000,
                registration.tls_name,
                tuple(asset.path for asset in registration.admin_assets),
                tuple(asset.path for asset in registration.central_assets),
                base64.b64encode(ssl.PEM_cert_to_DER_cert(registration.trust_pem)).decode("ascii"),
            ),
            login_origin,
        )

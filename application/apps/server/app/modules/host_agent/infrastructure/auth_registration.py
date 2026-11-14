"""Protected registrations resolved against the current inventory and running source."""

from dataclasses import dataclass
from pathlib import Path
import stat
from typing import Literal

from pydantic import Field

from app.modules.host_agent.application.auth_routes import AuthRouteManifest
from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.host_agent.infrastructure.auth_projection import VerifiedAuthEndpoint
from app.modules.host_agent.infrastructure.network_policy import bridge
from app.modules.host_agent.infrastructure.shared_identity_registration import (
    SharedIdentityRegistration,
    SharedRegistration,
)
from app.modules.host_agent.infrastructure.operator_networks import OperatorNetworks
from app.modules.host_agent.infrastructure.tunnel_credentials import protected_bytes
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import CanonicalId, Contract, Reference, Revision


class SourceRegistration(Contract):
    manifest_ref: Reference
    manifest: AuthRouteManifest
    binding_id: CanonicalId
    resource_generation: Revision
    socket_name: CanonicalId
    tls_name: str
    port: Literal[8000] = 8000


class AuthRegistration(Contract):
    sources: tuple[SourceRegistration, ...] = Field(max_length=128)
    shared: SharedRegistration | None = None


@dataclass(frozen=True)
class SourceSocket:
    path: Path
    uid: int


class RegisteredSources:
    def __init__(
        self,
        inventory,
        engine,
        firewall,
        settings,
        registrations,
        socket_root,
        *,
        central_principal=None,
    ):
        self.inventory, self.engine, self.firewall = inventory, engine, firewall
        self.settings, self.socket_root = settings, socket_root
        if (
            registrations.shared is not None
            and (registrations.shared.runtime_uid, registrations.shared.runtime_gid)
            != central_principal
        ):
            raise HostAgentDenied()
        self.shared = (
            SharedIdentityRegistration(inventory, engine, firewall, settings, registrations.shared)
            if registrations.shared is not None
            else None
        )
        self.entries = {item.binding_id: item for item in registrations.sources}
        self.manifests = {item.manifest_ref: item.manifest for item in registrations.sources}
        if len(self.entries) != len(registrations.sources) or len(self.manifests) != len(
            self.entries
        ):
            raise HostAgentDenied()
        if len({row.socket_name for row in registrations.sources}) != len(self.entries):
            raise HostAgentDenied()
        if len({row.manifest.private_endpoint_id for row in registrations.sources}) != len(
            self.entries
        ):
            raise HostAgentDenied()

    @classmethod
    def load(
        cls, inventory, engine, firewall, settings, path, socket_root, *, central_principal=None
    ):
        registrations = AuthRegistration.model_validate_json(protected_bytes(path, limit=131072))
        return cls(
            inventory,
            engine,
            firewall,
            settings,
            registrations,
            socket_root,
            central_principal=central_principal,
        )

    def resolve_shared(self):
        return self.shared.resolve() if self.shared is not None else (None, None)

    def resolve_held(self, evidence):
        row = self.inventory.auth_target(binding_id=evidence.binding_id)
        registration, target = self._running(row, evidence.access_epoch)
        if (
            registration.manifest_ref != evidence.auth_manifest_ref
            or evidence.resource_generation != registration.resource_generation
            or semantic_hash(registration.manifest) != evidence.auth_manifest_sha256
        ):
            raise HostAgentDenied()
        return VerifiedAuthEndpoint(
            registration.manifest, target.address4, registration.port, registration.tls_name
        )

    def resolve_identity_source(self, deployment, scope, epoch):
        if deployment != self.inventory.identity.deployment_id:
            raise HostAgentDenied()
        row = self.inventory.auth_target(operator_id=scope.operator_id)
        if row["workspace_id"] != scope.workspace_id:
            raise HostAgentDenied()
        registration, _ = self._running(row, epoch)
        if row["auth_route_state"] != "ready" or (
            row["auth_manifest_ref"] != registration.manifest_ref
            or row["auth_manifest_sha256"] != semantic_hash(registration.manifest)
        ):
            raise HostAgentDenied()
        return self._source_socket(row, registration)

    def resolve_identity_control(self, deployment, scope, epoch, *, original):
        if deployment != self.inventory.identity.deployment_id:
            raise HostAgentDenied()
        row = self.inventory.auth_target(operator_id=scope.operator_id)
        if row["workspace_id"] != scope.workspace_id or (original and epoch > row["access_epoch"]):
            raise HostAgentDenied()
        registration, _ = self._running(
            row,
            row["access_epoch"] if original else epoch,
            allow_blocked=True,
        )
        return self._source_socket(row, registration)

    def _source_socket(self, row, registration):
        path = self.socket_root / (registration.socket_name + ".sock")
        try:
            if path.resolve(strict=True) != path:
                raise HostAgentDenied()
            info = path.lstat()
        except OSError:
            raise HostAgentDenied() from None
        if (
            not stat.S_ISSOCK(info.st_mode)
            or info.st_uid != row["host_uid"]
            or info.st_mode & 0o007
        ):
            raise HostAgentDenied()
        return SourceSocket(path, row["host_uid"])

    def _running(self, row, epoch, *, allow_blocked=False):
        registration = self.entries.get(row["binding_id"])
        if (
            registration is None
            or registration.resource_generation != row["resource_generation"]
            or row["access_epoch"] != epoch
            or (row["desired_state"] == "blocked" and not allow_blocked)
            or row["state"] != "running"
            or row["container_ref"] is None
            or row["image_digest"] != registration.manifest.artifact_sha256
        ):
            raise HostAgentDenied()
        targets = {
            item.binding_id: bridge(item, self.settings)
            for item in self.inventory.network_projection().records
        }
        target = targets.get(row["binding_id"])
        if target is None:
            raise HostAgentDenied()
        self.firewall.verify(tuple(targets.values()))
        target.verify(self.engine.inspect_network(target.name))
        actual = self.engine.inspect(row["container_ref"])
        if (
            actual is None
            or actual.get("Id") != row["container_ref"]
            or actual.get("State", {}).get("Running") is not True
            or actual.get("Config", {}).get("Image") != "sha256:" + row["image_digest"]
            or actual.get("HostConfig", {}).get("PortBindings")
            or actual.get("HostConfig", {}).get("PublishAllPorts")
        ):
            raise HostAgentDenied()
        OperatorNetworks.verify_container(target, actual)
        return registration, target

"""Resolve host routes through protected manifest and live endpoint owners."""

from dataclasses import dataclass
from typing import Protocol

from app.modules.host_agent.application.auth_routes import (
    AuthRouteManifest,
    AuthRouteObservation,
    SharedIdentityManifest,
)
from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.host_agent.infrastructure.auth_projection import VerifiedAuthEndpoint
from app.platform.hosted_contracts.semantic import semantic_hash


@dataclass(frozen=True)
class SharedAuthSelection:
    """Deployment-owned selection. The browser has no input to these values."""

    manifest_ref: str
    manifest_sha256: str


class AuthManifestOwner(Protocol):
    def held(self, reference: str) -> AuthRouteManifest: ...
    def shared(self, reference: str) -> SharedIdentityManifest: ...
    def login_origin(self) -> str:
        """Current Admin control observation, obtained through the owning port."""
        ...


class NativeAuthEndpointOwner(Protocol):
    def held(
        self, manifest: AuthRouteManifest, evidence: AuthRouteObservation
    ) -> VerifiedAuthEndpoint:
        """Inspect the exact running artifact, private peer, binding and auth readiness."""
        ...

    def shared(self, manifest: SharedIdentityManifest) -> VerifiedAuthEndpoint:
        """Inspect the shared artifact, private bridge, gateway peer and provider egress."""
        ...


class AuthEndpoints:
    def __init__(
        self,
        manifests: AuthManifestOwner,
        native: NativeAuthEndpointOwner,
        *,
        shared: SharedAuthSelection | None = None,
    ):
        self.manifests, self.native, self.shared = manifests, native, shared

    def resolve_held(self, evidence: AuthRouteObservation) -> VerifiedAuthEndpoint:
        if evidence.auth_route_state != "ready" or evidence.auth_manifest_ref is None:
            raise HostAgentDenied()
        manifest = self.manifests.held(evidence.auth_manifest_ref)
        if (
            not isinstance(manifest, AuthRouteManifest)
            or semantic_hash(manifest) != evidence.auth_manifest_sha256
        ):
            raise HostAgentDenied()
        endpoint = self.native.held(manifest, evidence)
        if not isinstance(endpoint, VerifiedAuthEndpoint) or endpoint.manifest != manifest:
            raise HostAgentDenied()
        return endpoint

    def resolve_shared(self) -> tuple[VerifiedAuthEndpoint | None, str | None]:
        if self.shared is None:
            return None, None
        manifest = self.manifests.shared(self.shared.manifest_ref)
        if (
            not isinstance(manifest, SharedIdentityManifest)
            or semantic_hash(manifest) != self.shared.manifest_sha256
        ):
            raise HostAgentDenied()
        origin = self.manifests.login_origin()
        if manifest.central_origin != origin:
            raise HostAgentDenied()
        endpoint = self.native.shared(manifest)
        if not isinstance(endpoint, VerifiedAuthEndpoint) or endpoint.manifest != manifest:
            raise HostAgentDenied()
        return endpoint, origin

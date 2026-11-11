"""Protected H02 build inputs, not a qualified release or a provisioning command.

Keep actual deployment inputs outside Git. Validating this record cannot establish
device emptiness, cloud ownership, free capacity, artifact trust or native isolation.
"""

from typing import Annotated, Literal

from pydantic import Field, StrictInt, model_validator

from app.modules.host_agent.application.effect_contracts import GuardedLifecycle
from app.platform.hosted_contracts.semantic import SemanticRequest
from app.platform.hosted_contracts.values import CanonicalId, Reference, RequestHash, Revision

HostPrincipal = Annotated[StrictInt, Field(gt=0, lt=4294967295)]

MAIN_ADMIN_TABLES = (
    "control_meta",
    "storage_policies",
    "qualified_releases",
    "component_deployments",
    "operators",
    "invitations",
    "admin_principals",
    "admin_sessions",
    "login_handoffs",
    "operations",
    "operation_events",
    "admin_audit",
    "workspace_recovery_status",
)


class PrincipalRange(SemanticRequest):
    """Protected allocation range; actual collision checks are an H02.3 gate."""

    first: HostPrincipal
    last: HostPrincipal
    reserved: Annotated[tuple[HostPrincipal, ...], Field(max_length=256)] = ()

    @model_validator(mode="after")
    def ordered_unique(self):
        if self.last < self.first or len(set(self.reserved)) != len(self.reserved):
            raise ValueError("Principal range must be ordered with distinct reservations.")
        if self.last - self.first + 1 <= sum(
            self.first <= item <= self.last for item in self.reserved
        ):
            raise ValueError("Principal range has no available identities.")
        return self


class ArtifactPin(SemanticRequest):
    """Version plus immutable bytes; a tag/version alone is insufficient."""

    version: Reference
    sha256: RequestHash


class Toolchain(SemanticRequest):
    ubuntu_image: ArtifactPin
    python_image: ArtifactPin
    dependency_lock: ArtifactPin
    docker_engine: ArtifactPin
    caddy: ArtifactPin
    cloudflared: ArtifactPin
    kernel: ArtifactPin


class HostBuildInputs(SemanticRequest):
    """Exact private inputs required before build/setup, with unmeasured capacity.

    GCP/domain/account and roots are resolved via a protected setup reference.
    Credentials and raw device/path strings are deliberately absent. Qualification
    tooling must resolve and verify that reference before any effect.
    """

    version: Literal[1] = 1
    deployment_id: CanonicalId
    protected_setup_ref: Reference
    protected_setup_sha256: RequestHash
    source_manifest_sha256: RequestHash
    toolchain: Toolchain
    image_schema_spec_sha256: RequestHash
    runtime_limits_spec_sha256: RequestHash
    architecture: Literal["amd64"] = "amd64"
    ubuntu_release: Literal["24.04"] = "24.04"
    cgroup_version: Literal[2] = 2
    filesystem: Literal["ext4"] = "ext4"
    data_disk_type: Literal["pd-balanced"] = "pd-balanced"
    spot: Literal[False] = False
    starting_vcpus: Literal[2] = 2
    starting_memory_gib: Literal[8] = 8
    starting_boot_disk_gib: Literal[20] = 20
    starting_data_disk_gib: Literal[50] = 50
    host_uids: PrincipalRange
    host_gids: PrincipalRange
    uid_mapping: Literal["direct"] = "direct"
    lifecycle: GuardedLifecycle = GuardedLifecycle()
    capacity_profile_revision: Revision
    capacity_state: Literal["unmeasured"] = "unmeasured"
    acceptance: Literal["infrastructure_candidate"] = "infrastructure_candidate"
    customer_ingress: Literal["held"] = "held"

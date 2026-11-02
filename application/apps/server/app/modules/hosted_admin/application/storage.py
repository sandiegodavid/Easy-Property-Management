"""Closed protected allocation contracts; safe views omit paths and project IDs."""

import hashlib
import json
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from app.modules.hosted_access.application.storage_policy import (
    ProtectedRecord,
    StoragePolicy,
    TierProfile,
)


def canonical_storage(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def storage_fingerprint(value):
    return hashlib.sha256(canonical_storage(value).encode()).hexdigest()


class HostStorageFacts(ProtectedRecord):
    filesystem_uuid: str
    observed: float = Field(ge=0, allow_inf_nan=False)
    total_bytes: int = Field(gt=0)
    free_bytes: int = Field(ge=0)
    free_inodes: int = Field(ge=0)
    recovery_required: int = Field(ge=0)
    shared_overhead: int = Field(ge=0)
    retained_image_growth: int = Field(ge=0)
    administrative_growth: int = Field(ge=0)
    enforcement: bool
    administrative_inodes: int = Field(default=0, ge=0)
    reclamation_bytes: int = Field(default=0, ge=0)
    reclamation_inodes: int = Field(default=0, ge=0)
    environment_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    projects: tuple["ProjectUsage", ...] = Field(default=(), max_length=3000)

    @model_validator(mode="after")
    def identity(self):
        if (
            str(UUID(self.filesystem_uuid)) != self.filesystem_uuid
            or self.free_bytes > self.total_bytes
        ):
            raise ValueError("Exact filesystem and coherent host-space facts required.")
        return self


class ProjectUsage(ProtectedRecord):
    project_id: int = Field(gt=0, lt=2**32)
    allocated_bytes: int = Field(ge=0)
    allocated_inodes: int = Field(ge=0)
    directory_inode: int = Field(gt=0)
    hard_bytes: int = Field(ge=0, multiple_of=1024)
    hard_inodes: int = Field(ge=0)
    enforcement: bool


class ProfileEvidence(ProtectedRecord):
    artifact_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    profile_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    environment_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed: float = Field(ge=0, allow_inf_nan=False)
    expires: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def coherent(self):
        if str(UUID(self.artifact_id)) != self.artifact_id or self.expires <= self.observed:
            raise ValueError("A bounded verifier artifact is required.")
        return self


class ProfileReport(ProfileEvidence):
    kind: Literal["storage_profile"]
    profile: TierProfile

    @model_validator(mode="after")
    def matches(self):
        if storage_fingerprint(self.profile.model_dump(mode="json")) != self.profile_digest:
            raise ValueError("The profile does not match its qualified artifact.")
        return self


class StorageAuthority(ProtectedRecord):
    inventory_revision: int = Field(ge=1)
    binding_revision: int = Field(ge=0)
    admin_revision: int = Field(ge=0)
    fence: int = Field(ge=0)


class BindingCheck(ProtectedRecord):
    policy_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    authority: StorageAuthority
    release_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    sandbox_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class BindingReport(BindingCheck):
    kind: Literal["storage_binding"]
    instance: str
    observed: float = Field(ge=0, allow_inf_nan=False)
    expires: float = Field(ge=0, allow_inf_nan=False)


class StorageReservation(ProtectedRecord):
    id: str
    expected_revision: int = Field(ge=0)
    policy: StoragePolicy
    reason: str = Field(min_length=1, max_length=1000)
    recovery_reference: str = Field(pattern=r"^[a-f0-9]{64}$")
    authority: StorageAuthority

    @model_validator(mode="after")
    def identity(self):
        if (
            str(UUID(self.id)) != self.id
            or self.id != self.policy.operation_id
            or not self.reason.strip()
        ):
            raise ValueError("The original operation identity and reason are required.")
        return self

    def fingerprint(self):
        return storage_fingerprint(self.model_dump(mode="json"))


class StorageView(ProtectedRecord):
    operation_id: str
    instance: str
    revision: int = Field(ge=1)
    policy_revision: int = Field(ge=1)
    state: Literal["reserved", "active", "retiring", "retired"]
    tier: Literal["50mb", "200mb", "1gb"]
    allowance_bytes: int = Field(gt=0)


class RegisteredQuotaPort(Protocol):
    def __call__(self, command: "StorageCommand", request: dict) -> "StorageProof":
        """Inspect/apply the admitted registered intent; never accept portal paths."""


class StorageCommand(ProtectedRecord):
    id: str
    operation_id: str
    expected_revision: int = Field(ge=1)
    action: Literal["apply", "reconcile", "retire", "finish_retirement"]
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def coherent(self):
        if (
            self.id == self.operation_id
            or not self.reason.strip()
            or any(str(UUID(value)) != value for value in (self.id, self.operation_id))
        ):
            raise ValueError("A distinct command identity and reason are required.")
        return self

    def fingerprint(self):
        return storage_fingerprint(self.model_dump(mode="json"))


class StorageProof(ProtectedRecord):
    """Root-collected proof, never a broker input supplied by a portal."""

    operation_id: str
    policy_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed: float = Field(ge=0, allow_inf_nan=False)
    projects: tuple[ProjectUsage, ...] = Field(min_length=3, max_length=3)
    cleanup_verified: bool = False
    no_open_files: bool = False
    directories_absent: bool = False


class StorageInspection(ProtectedRecord):
    allocation: StorageView
    observed: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    enforcement: bool | None = None
    allocated_bytes: int | None = Field(default=None, ge=0)
    allocated_inodes: int | None = Field(default=None, ge=0)
    state: Literal["unknown", "available", "stale"] = "unknown"


class CleanupReport(StorageProof):
    kind: Literal["storage_cleanup"]
    command_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    inventory_revision: int = Field(ge=1)
    expires: float = Field(ge=0, allow_inf_nan=False)


class FilesystemBudget(ProtectedRecord):
    filesystem_uuid: str
    mount: str
    recovery_required: int = Field(ge=0)
    shared_overhead: int = Field(ge=0)
    retained_image_growth: int = Field(ge=0)
    administrative_growth: int = Field(ge=0)
    administrative_inodes: int = Field(ge=0)

    @model_validator(mode="after")
    def coherent(self):
        from pathlib import PurePosixPath

        if (
            str(UUID(self.filesystem_uuid)) != self.filesystem_uuid
            or not PurePosixPath(self.mount).is_absolute()
            or str(PurePosixPath(self.mount)) != self.mount
            or ".." in PurePosixPath(self.mount).parts
        ):
            raise ValueError("An exact protected filesystem budget is required.")
        return self


class StorageHostSettings(ProtectedRecord):
    filesystems: tuple[FilesystemBudget, ...] = Field(min_length=1, max_length=10)
    profiles: dict[str, str] = Field(max_length=100)
    bindings: dict[str, str] = Field(max_length=1000)

    @model_validator(mode="after")
    def coherent(self):
        if len({item.filesystem_uuid for item in self.filesystems}) != len(self.filesystems) or any(
            str(UUID(value)) != value
            for value in (*self.profiles.values(), *self.bindings.values())
        ):
            raise ValueError("Distinct filesystems and exact verifier references required.")
        return self


def verify_storage_proof(command, policy, proof, now):
    if (
        proof.operation_id != command.operation_id
        or proof.policy_digest != storage_fingerprint(policy)
        or not 0 <= now - proof.observed < 300
    ):
        raise ValueError("Storage proof identity or observation is invalid.")
    expected = {p["project_id"]: p for p in policy["projects"]}
    if set(expected) != {p.project_id for p in proof.projects}:
        raise ValueError("Storage proof projects are invalid.")
    for usage in proof.projects:
        project = expected[usage.project_id]
        if (usage.directory_inode, usage.hard_bytes, usage.hard_inodes) != (
            project["directory_inode"],
            project["hard_bytes"],
            project["hard_inodes"],
        ):
            raise ValueError("Storage proof project binding is invalid.")
        if command.action == "finish_retirement":
            if (
                usage.allocated_bytes
                or usage.allocated_inodes
                or not (proof.cleanup_verified and proof.no_open_files and proof.directories_absent)
            ):
                raise ValueError("Storage cleanup has not been verified.")
        elif not usage.enforcement:
            raise ValueError("Storage enforcement is unavailable.")

"""Source-owned protected storage policy. No browser chooses project identities."""

from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

TIERS = {"50mb": 50_000_000, "200mb": 200_000_000, "1gb": 1_000_000_000}
SCRATCH_QUALIFICATION_CANDIDATE = 256 * 1024 * 1024
Tier = Literal["50mb", "200mb", "1gb"]


class ProtectedRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ProjectCeiling(ProtectedRecord):
    hard_bytes: int = Field(gt=0, lt=2**63, multiple_of=1024)
    hard_inodes: int = Field(gt=0, lt=2**63)


class ProjectIdentity(ProjectCeiling):
    role: Literal["workspace", "scratch", "control"]
    directory: str = Field(min_length=1, max_length=1024)
    directory_inode: int = Field(gt=0, lt=2**63)
    project_id: int = Field(gt=0, lt=2**32)
    uid: int = Field(gt=0, lt=2**32)

    @model_validator(mode="after")
    def protected_path(self):
        path = PurePosixPath(self.directory)
        if (
            not path.is_absolute()
            or str(path) != self.directory
            or ".." in path.parts
            or path == PurePosixPath("/")
            or any(c.isspace() or not c.isprintable() or c == ":" for c in self.directory)
        ):
            raise ValueError("An exact protected directory identity is required.")
        return self


class TierProfile(ProtectedRecord):
    id: str = Field(pattern=r"^[a-z0-9-]{1,80}$")
    revision: int = Field(ge=1)
    tier: Tier
    release_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    sandbox_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    qualified: bool = False
    workspace: ProjectCeiling | None = None
    scratch: ProjectCeiling | None = None
    control: ProjectCeiling | None = None
    max_transaction_bytes: int | None = Field(default=None, gt=0)
    max_concurrency: int | None = Field(default=None, gt=0, le=100)
    measurement_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    qualification_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def evidence(self):
        if self.qualified and any(
            value is None
            for value in (
                self.workspace,
                self.scratch,
                self.control,
                self.max_transaction_bytes,
                self.max_concurrency,
                self.measurement_digest,
                self.qualification_digest,
            )
        ):
            raise ValueError("Measured and qualified limits are required before allocation.")
        if self.workspace and self.workspace.hard_bytes < TIERS[self.tier]:
            raise ValueError("A workspace ceiling cannot be below its usable allowance.")
        return self


class StoragePolicy(ProtectedRecord):
    backend: Literal["project_quota"]
    instance: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")
    workspace_id: str
    operator_id: str
    filesystem_uuid: str
    policy_revision: int = Field(ge=1)
    tier: Tier
    allowance_bytes: int = Field(gt=0)
    profile_id: str = Field(pattern=r"^[a-z0-9-]{1,80}$")
    profile_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    projects: tuple[ProjectIdentity, ...] = Field(min_length=3, max_length=3)
    operation_id: str
    request_id: str | None = None

    @model_validator(mode="after")
    def coherent(self):
        for value in (
            self.workspace_id,
            self.operator_id,
            self.filesystem_uuid,
            self.operation_id,
            self.request_id,
        ):
            if value is not None and str(UUID(value)) != value:
                raise ValueError("Canonical stable identities are required.")
        if self.allowance_bytes != TIERS[self.tier]:
            raise ValueError("The tier requires its exact decimal allowance.")
        if {item.role for item in self.projects} != {"workspace", "scratch", "control"}:
            raise ValueError("Three separate project roles are required.")
        if (
            len({item.project_id for item in self.projects}) != 3
            or len({item.uid for item in self.projects}) != 1
        ):
            raise ValueError("Distinct project IDs owned by one service identity are required.")
        paths = [PurePosixPath(item.directory) for item in self.projects]
        if any(
            a.is_relative_to(b) for i, a in enumerate(paths) for j, b in enumerate(paths) if i != j
        ):
            raise ValueError("Project directories must be distinct and nonnested.")
        return self

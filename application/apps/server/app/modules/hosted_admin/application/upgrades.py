"""Closed installed-release upgrade contracts; paths and proof are host-owned."""

from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.hosted_admin.application.operations import fingerprint
from app.modules.hosted_admin.application.qualification import UUID_PATTERN
from app.modules.hosted_admin.application.recovery import RecoveryCompletionTimes

RELEASE_PATTERN = r"^release-[0-9]{8}-[0-9]{2,}$"
DIGEST_PATTERN = r"^[a-f0-9]{64}$"


class InstalledRelease(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    release: str = Field(pattern=RELEASE_PATTERN)
    digest: str = Field(pattern=DIGEST_PATTERN)
    installed: float = Field(ge=0, allow_inf_nan=False)
    notes: str = Field(default="", max_length=4000)
    eligible: bool
    blockers: list[str] = Field(max_length=20)
    preserve_sessions: bool
    compatibility_digest: str = Field(pattern=DIGEST_PATTERN)


class UpgradeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    id: str = Field(pattern=UUID_PATTERN)
    instance: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")
    action: Literal["check", "start", "accept", "rollback"]
    expected_revision: int = Field(ge=1)
    release: str | None = Field(default=None, pattern=RELEASE_PATTERN)
    operation: str | None = Field(default=None, pattern=UUID_PATTERN)
    session_handling: Literal["preserve", "revoke"] | None = None
    restore_access: bool | None = None
    confirmed: bool = False
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def coherent(self):
        if not self.reason.strip():
            raise ValueError("A reason is required.")
        if (self.action == "check") != (self.release is not None):
            raise ValueError("Only readiness selects an installed release.")
        if (self.action != "check") != (self.operation is not None):
            raise ValueError("Select the original readiness or upgrade operation.")
        if (self.action == "start") != (self.session_handling is not None):
            raise ValueError("Only start selects session handling.")
        if (self.action == "accept") != (self.restore_access is not None):
            raise ValueError("Acceptance must explicitly decide access handling.")
        if self.action != "check" and not self.confirmed:
            raise ValueError("Confirm the reviewed consequences.")
        return self

    def fingerprint(self):
        return fingerprint(self.model_dump())


class UpgradeHost(Protocol):
    def options(self, instance: str) -> list[InstalledRelease]: ...
    def prepare(self, instance: str, release: str) -> dict:
        """Verify current artifacts, compatibility, qualification and protected host facts."""

    def inspect(self, payload: dict, step: str):
        """Observe the exact operation's effect without repeating it."""

    def apply(self, payload: dict, step: str) -> None: ...
    def contain(self, payload: dict) -> bool:
        """Keep this operation's gate closed; never grant or restore data."""

    def contain_for_skip(self, payload: dict) -> bool:
        """After a durable child fence, verify containment and reconcile only its reservation."""


class UpgradeInstance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")
    instance_id: str = Field(pattern=UUID_PATTERN)
    allocation_id: str = Field(pattern=UUID_PATTERN)
    workspace_id: str = Field(pattern=UUID_PATTERN)
    operator_id: str = Field(pattern=UUID_PATTERN)
    revision: int = Field(ge=1)
    release: str = Field(pattern=RELEASE_PATTERN)
    profile: str = Field(pattern=r"^[a-z0-9-]{1,80}$")


class UpgradePlan(BaseModel):
    """Private immutable preparation facts; never projected wholesale to HTTP."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    instance: UpgradeInstance
    target: InstalledRelease
    original_digest: str = Field(pattern=DIGEST_PATTERN)
    configuration_digest: str = Field(pattern=DIGEST_PATTERN)
    binding_revision: int = Field(ge=0)
    admin_revision: int = Field(ge=0)
    fence: int = Field(ge=0)
    generation: int = Field(ge=0)
    active: bool
    environment_digest: str = Field(pattern=DIGEST_PATTERN)
    recovery_configuration_digest: str = Field(pattern=DIGEST_PATTERN)


class ReleaseQualification(BaseModel):
    """Private verifier evidence for the installed artifact and host profile."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    target: InstalledRelease
    profile: str = Field(pattern=r"^[a-z0-9-]{1,80}$")
    operator_ceiling: int = Field(ge=1, le=1000)
    environment_digest: str = Field(pattern=DIGEST_PATTERN)
    observed: float = Field(ge=0, allow_inf_nan=False)
    expires: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def coherent(self):
        if self.expires <= self.observed or self.target.eligible != (not self.target.blockers):
            raise ValueError("Qualification must have a bounded observation and coherent blockers.")
        return self


class ReleaseCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    reports: list[str] = Field(max_length=50)

    @model_validator(mode="after")
    def coherent(self):
        import re

        if len(set(self.reports)) != len(self.reports) or any(
            not re.fullmatch(UUID_PATTERN, value) for value in self.reports
        ):
            raise ValueError("Select bounded unique registered report identities.")
        return self


class UpgradeEvidence(BaseModel):
    """Safe proof of a particular paused allocation, artifact and recovery chain."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    id: str = Field(pattern=UUID_PATTERN)
    operation: str = Field(pattern=UUID_PATTERN)
    owner: str = Field(pattern=UUID_PATTERN)
    stage: Literal["recovery", "target", "rollback"]
    state: Literal["verified", "failed"]
    instance: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")
    workspace_id: str = Field(pattern=UUID_PATTERN)
    release_digest: str = Field(pattern=DIGEST_PATTERN)
    binding_digest: str = Field(pattern=DIGEST_PATTERN)
    archive_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    archive_reference: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    binding_reference: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    encrypted_binding_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    snapshot_marker: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    archive: bool = False
    readback: bool = False
    restore: bool = False
    approved_binding: bool = False
    runtime: bool = False
    protected_routing: bool = False
    completed: RecoveryCompletionTimes = Field(default_factory=RecoveryCompletionTimes)
    observed: float = Field(ge=0, allow_inf_nan=False)
    expires: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def coherent(self):
        if self.expires <= self.observed:
            raise ValueError("Evidence must expire after observation.")
        if self.state == "verified" and not all(
            (
                self.archive,
                self.readback,
                self.restore,
                self.approved_binding,
                self.archive_digest,
                self.archive_reference,
                self.binding_reference,
                self.encrypted_binding_digest,
                self.snapshot_marker,
                all(
                    value is not None and value <= self.observed
                    for key, value in self.completed.model_dump().items()
                    if key != "acceptance"
                ),
            )
        ):
            raise ValueError("Recovery evidence requires independently verified bytes and binding.")
        if (
            self.state == "verified"
            and self.stage != "recovery"
            and not (
                self.runtime
                and self.protected_routing
                and self.completed.acceptance is not None
                and self.completed.acceptance <= self.observed
            )
        ):
            raise ValueError("Resulting-release evidence requires runtime and protected routing.")
        return self


class UpgradeStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    sequence: int = Field(ge=0)
    kind: str
    state: Literal["pending", "intent", "verified"]
    reference: str | None = None
    checked: float | None = None


class UpgradeOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    id: str = Field(pattern=UUID_PATTERN)
    kind: Literal["upgrade_check", "upgrade", "upgrade_rollback"]
    target: str
    revision: int = Field(ge=1)
    state: Literal[
        "queued", "running", "waiting", "unknown", "failed", "paused", "cancelled", "succeeded"
    ]
    cancel_requested: int = Field(ge=0, le=1)
    error: str | None = None
    created: float
    updated: float
    steps: list[UpgradeStep] = Field(max_length=16)
    result: dict | None = None


class UpgradeView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation: UpgradeOperation
    original_release: str | None = Field(default=None, pattern=RELEASE_PATTERN)
    target: InstalledRelease | None = None
    workspace_id: str | None = Field(default=None, pattern=UUID_PATTERN)
    session_handling: Literal["preserve", "revoke"] | None = None
    evidence: list[UpgradeEvidence] = Field(default_factory=list, max_length=3)
    batch: str | None = Field(default=None, pattern=UUID_PATTERN)


class UpgradeCheckPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_id: str = Field(pattern=UUID_PATTERN)
    instance: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")
    release: str = Field(pattern=RELEASE_PATTERN)
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class UpgradeRunPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_id: str = Field(pattern=UUID_PATTERN)
    instance: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")
    plan: UpgradePlan
    session_handling: Literal["preserve", "revoke"]
    gate_owner: str = Field(pattern=UUID_PATTERN)
    reason: str = Field(min_length=1, max_length=1000)
    parent: str | None = Field(default=None, pattern=UUID_PATTERN)
    rollback: bool = False

    @model_validator(mode="after")
    def coherent(self):
        if (
            self.instance != self.plan.instance.key
            or self.rollback != bool(self.parent)
            or (not self.rollback and self.gate_owner != self.operation_id)
        ):
            raise ValueError("Upgrade execution must retain its exact allocation and gate owner.")
        if self.session_handling == "preserve" and not self.plan.target.preserve_sessions:
            raise ValueError("Session preservation needs qualified compatibility.")
        return self

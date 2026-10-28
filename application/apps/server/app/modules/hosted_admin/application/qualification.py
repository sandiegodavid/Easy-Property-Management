"""Bounded private qualification intents, not browser-provided capacity overrides."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.hosted_admin.application.operations import fingerprint

UUID_PATTERN = r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$"
DIGEST_PATTERN = r"^[a-f0-9]{64}$"
REQUIRED_EVIDENCE = frozenset(
    {
        "load",
        "isolation",
        "recovery",
        "revocation",
        "mount_failure",
        "reboot",
        "retirement",
        "restoration",
        "rollout",
    }
)


class TestIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    hostname: str = Field(min_length=4, max_length=253, pattern=r"^[a-z0-9.-]+$")


class QualificationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    id: str = Field(pattern=UUID_PATTERN)
    release: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")
    profile: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")
    environment_hash: str = Field(pattern=DIGEST_PATTERN)
    target: Literal[3]
    browsers: Literal[6]
    identities: list[TestIdentity] = Field(min_length=3, max_length=3)
    starts: float = Field(ge=0, allow_inf_nan=False)
    expires: float = Field(ge=0, allow_inf_nan=False)
    evidence_directory_id: str = Field(pattern=UUID_PATTERN)
    maintenance_reference: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    rollback_reference: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    workload_digest: str = Field(pattern=DIGEST_PATTERN)
    memory_bytes: int = Field(gt=0)
    disk_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def coherent(self):
        if not 0 < self.expires - self.starts <= 86400:
            raise ValueError("Qualification is bounded to one day.")
        if (
            len({item.email.casefold() for item in self.identities}) != 3
            or len({item.hostname for item in self.identities}) != 3
        ):
            raise ValueError("Three distinct controlled identities and exact hosts are required.")
        return self

    def fingerprint(self):
        return fingerprint(self.model_dump())


class QualificationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_id: str = Field(pattern=UUID_PATTERN)
    qualification_id: str = Field(pattern=UUID_PATTERN)
    action: Literal["start", "resume", "abort", "retire", "promote"]
    expected_revision: int = Field(ge=1)
    expected_capacity_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)
    confirmed: Literal[True]

    def fingerprint(self):
        return fingerprint(self.model_dump())


class QualificationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    id: str = Field(pattern=UUID_PATTERN)
    qualification_id: str = Field(pattern=UUID_PATTERN)
    kind: Literal[
        "load",
        "isolation",
        "recovery",
        "revocation",
        "mount_failure",
        "reboot",
        "retirement",
        "restoration",
        "rollout",
    ]
    environment_hash: str = Field(pattern=DIGEST_PATTERN)
    artifact_digest: str = Field(pattern=DIGEST_PATTERN)
    observed: float = Field(ge=0, allow_inf_nan=False)
    expires: float = Field(ge=0, allow_inf_nan=False)
    passed: bool


class CapacitySnapshot(BaseModel):
    """Trusted host adapter's fresh facts, never accepted from Admin HTTP/RPC."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    environment_hash: str = Field(pattern=DIGEST_PATTERN)
    release: str
    profile: str
    observed: float = Field(ge=0)
    memory_total: int = Field(gt=0)
    memory_committed: int = Field(ge=0)
    disk_total: int = Field(gt=0)
    disk_free: int = Field(ge=0)
    disk_committed: int = Field(ge=0)
    recovery_staging: int = Field(gt=0)
    active_count: int = Field(ge=0)
    inventory_clear: bool
    baseline_restored: bool
    test_resources_retired: bool
    retained_emails: list[str] = Field(default_factory=list, max_length=1000)
    retained_hostnames: list[str] = Field(default_factory=list, max_length=1000)

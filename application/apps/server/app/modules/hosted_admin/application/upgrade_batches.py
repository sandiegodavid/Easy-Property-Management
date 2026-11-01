"""Closed bulk-upgrade decisions; execution remains owned by individual upgrades."""

from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.hosted_admin.application.operations import fingerprint
from app.modules.hosted_admin.application.qualification import UUID_PATTERN
from app.modules.hosted_admin.application.upgrades import RELEASE_PATTERN

INSTANCE_PATTERN = r"^[a-z0-9][a-z0-9-]{0,31}$"


class BatchSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    instance: str = Field(pattern=INSTANCE_PATTERN)
    expected_revision: int = Field(ge=1)


class BatchSessions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    instance: str = Field(pattern=INSTANCE_PATTERN)
    handling: Literal["preserve", "revoke"]


class BatchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    id: str = Field(pattern=UUID_PATTERN)
    action: Literal["check", "recheck", "start", "pause", "cancel", "resume", "skip"]
    batch: str | None = Field(default=None, pattern=UUID_PATTERN)
    expected_revision: int | None = Field(default=None, ge=1)
    members: list[BatchSelection] = Field(default_factory=list, max_length=50)
    release: str | None = Field(default=None, pattern=RELEASE_PATTERN)
    sessions: list[BatchSessions] = Field(default_factory=list, max_length=50)
    window_start: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    window_end: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    instance: str | None = Field(default=None, pattern=INSTANCE_PATTERN)
    confirmed: bool = False
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def coherent(self):
        creating = self.action == "check"
        executing = self.action in {"start", "resume"}
        if creating != bool(self.members) or creating != bool(self.release):
            raise ValueError("Only initial readiness selects the exact operators and release.")
        if creating == (self.batch is not None) or creating == (self.expected_revision is not None):
            raise ValueError("Subsequent decisions need the original batch and revision.")
        if len({member.instance for member in self.members}) != len(self.members):
            raise ValueError("Select each operator once, up to 50 operators.")
        if len({member.instance for member in self.sessions}) != len(self.sessions):
            raise ValueError("Select one session decision per operator.")
        if executing != bool(self.sessions):
            raise ValueError("Start and resume require the reviewed session decisions.")
        if executing != (self.window_start is not None and self.window_end is not None):
            raise ValueError("Start and resume need an explicit maintenance window.")
        if not executing and (self.window_start is not None or self.window_end is not None):
            raise ValueError("Only start and resume select a maintenance window.")
        if executing and self.window_end <= self.window_start:
            raise ValueError("The maintenance window must end after it starts.")
        if (self.action == "skip") != (self.instance is not None):
            raise ValueError("Only skip selects one retained member.")
        if not self.reason.strip() or (
            self.action not in {"check", "recheck"} and not self.confirmed
        ):
            raise ValueError("Confirm the reviewed consequences and provide a reason.")
        return self

    def fingerprint(self):
        return fingerprint(self.model_dump())


class BatchMemberView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sequence: int = Field(ge=0, le=49)
    instance: str = Field(pattern=INSTANCE_PATTERN)
    name: str = Field(min_length=1, max_length=255)
    expected_revision: int = Field(ge=1)
    status: Literal[
        "containing",
        "skipped",
        "rolled_back",
        "accepted_restored",
        "accepted_disabled",
        "failed",
        "awaiting_acceptance",
        "upgrading",
        "blocked",
        "queued",
        "checking_readiness",
    ]
    operation: str | None
    rollback: str | None
    operation_revision: int | None
    observed: float | None
    original_release: str | None
    target_digest: str | None
    preserve_sessions: bool
    session_handling: Literal["preserve", "revoke"] | None
    access_active: bool | None
    error: str | None
    can_skip: bool


class BatchView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=UUID_PATTERN)
    state: Literal[
        "checking", "ready", "blocked", "running", "paused", "cancelled", "completed", "mixed"
    ]
    revision: int = Field(ge=1)
    release: str
    error: str | None
    total: int = Field(ge=1, le=50)
    counts: dict[str, int]
    window_start: float | None
    window_end: float | None
    items: list[BatchMemberView] = Field(max_length=50)
    offset: int = Field(ge=0, le=49)
    next_offset: int | None


class BatchDirectoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=UUID_PATTERN)
    state: str
    revision: int = Field(ge=1)
    created: float
    updated: float
    release: str
    total: int = Field(ge=1, le=50)
    accepted: int = Field(ge=0, le=50)
    skipped: int = Field(ge=0, le=50)


class BatchDirectory(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    items: list[BatchDirectoryEntry] = Field(max_length=10)
    total: int = Field(ge=0, le=1000)
    offset: int = Field(ge=0, le=990)
    next_offset: int | None


def child_identity(batch, instance):
    return str(uuid5(NAMESPACE_URL, f"epm-upgrade-batch:{batch}:{instance}"))

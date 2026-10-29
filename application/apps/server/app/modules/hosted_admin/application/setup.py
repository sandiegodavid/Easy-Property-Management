"""Closed setup commands. Resource identities and capacity facts are server owned."""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.hosted_admin.application.operations import fingerprint, StepResult, Reservation
from app.modules.hosted_access.application.admin_commands import AccessStatus
from app.modules.hosted_admin.application.qualification import UUID_PATTERN


class SetupData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    name: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=254)
    reference: str = Field(default="", max_length=80)
    support: str = Field(default="", max_length=254)
    release: str = Field(default="", max_length=80)
    template: Literal["synthetic", "empty"] = "synthetic"
    access: Literal["read_write", "read_only"] = "read_write"
    starts: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    expires: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    timezone: str = Field(default="UTC", max_length=80)

    @field_validator("name", "email", "reference", "support")
    @classmethod
    def plain_text(cls, value):
        if value != value.strip() or any(not character.isprintable() for character in value):
            raise ValueError("Use plain text without leading or trailing whitespace.")
        return value

    def ready(self):
        import re
        from zoneinfo import ZoneInfo

        if not self.name or not re.fullmatch(r"[^\s@<>]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", self.email):
            raise ValueError("An operator name and exact sign-in email are required.")
        if not re.fullmatch(r"[^\s@<>]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", self.support):
            raise ValueError("A support email is required.")
        if not self.release or not 0 < self.expires - self.starts <= 14 * 86400:
            raise ValueError("Choose a release and a positive window of at most fourteen days.")
        ZoneInfo(self.timezone)


class SetupCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    action: Literal["save", "discard", "create"]
    draft_id: str = Field(pattern=UUID_PATTERN)
    expected_revision: int = Field(ge=0)
    data: SetupData | None = None
    operation_id: str | None = Field(default=None, pattern=UUID_PATTERN)
    confirmed: bool = False
    review_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def coherent(self):
        if (self.action == "save") != (self.data is not None):
            raise ValueError("Only saving accepts setup fields.")
        if (self.action == "create") != (self.operation_id is not None):
            raise ValueError("Creation requires its original operation key.")
        if self.action == "create" and (not self.confirmed or not self.expected_revision):
            raise ValueError("Review and confirm the saved setup before creating resources.")
        if (self.action == "create") != (self.review_hash is not None):
            raise ValueError("Creation requires the exact reviewed assignment.")
        return self

    def fingerprint(self):
        return fingerprint(self.model_dump())


class SetupPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key: str = Field(pattern=r"^d-[a-f0-9]{8,16}$")
    instance_id: str = Field(pattern=UUID_PATTERN)
    allocation_id: str = Field(pattern=UUID_PATTERN)
    operator_id: str = Field(pattern=UUID_PATTERN)
    workspace_id: str = Field(pattern=UUID_PATTERN)
    hostname: str = Field(pattern=r"^[a-z0-9.-]{1,253}$")
    port: int = Field(ge=1024, le=65535)
    profile: str = Field(min_length=1, max_length=80)
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    reservations: list[Reservation] = Field(min_length=9, max_length=9)

    @model_validator(mode="after")
    def complete(self):
        if {item.kind for item in self.reservations} != {
            "disk",
            "email",
            "hostname",
            "image",
            "memory",
            "mount",
            "port",
            "user",
            "workspace",
        }:
            raise ValueError("Complete distinct allocation identities are required.")
        values = {item.kind: item.identity for item in self.reservations}
        if (
            values["hostname"] != self.hostname
            or values["port"] != str(self.port)
            or values["workspace"] != self.workspace_id
            or values["user"] != "epm-" + self.key
        ):
            raise ValueError("Allocation identities disagree with the setup plan.")
        if len({self.instance_id, self.allocation_id, self.operator_id, self.workspace_id}) != 4:
            raise ValueError("Instance, allocation, operator and workspace identities must differ.")
        return self


class SetupHost(Protocol):
    def options(self) -> dict:
        """Installed qualified choices, never browser-supplied paths or profiles."""

    def plan(self, draft_id: str, data: SetupData) -> dict:
        """Generate stable exact resource identities without allocating resources."""

    def admission(self, draft_id: str, data: SetupData):
        """Hold shared host maintenance ownership while gathering trusted facts."""

    def check(self, connection, plan: dict, prepared: dict) -> None:
        """Fresh capacity, retained allocations and provider-seat admission."""

    def inspect(self, payload: dict, step: str): ...

    def apply(self, payload: dict, step: str) -> None: ...

    def contain(self, payload: dict) -> bool: ...

    def enrollment(self, instance: str) -> dict:
        """Current source-owned verified enrollment and runtime checks."""


class SetupOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    releases: list[str] = Field(max_length=10)
    templates: list[Literal["synthetic", "empty"]] = Field(max_length=2)
    workspace_mib: Literal[250]
    file_mib: Literal[50]
    backup_policy: str = Field(max_length=300)


class SetupStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sequence: int = Field(ge=0, le=3)
    kind: Literal["allocate", "workspace", "provider_setup", "readiness"]
    state: Literal["pending", "intent", "verified"]
    reference: str | None
    checked: float | None


class SetupOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=UUID_PATTERN)
    kind: Literal["provision"]
    target: str
    revision: int = Field(ge=1)
    state: Literal[
        "queued", "running", "waiting", "unknown", "failed", "paused", "cancelled", "succeeded"
    ]
    cancel_requested: Literal[0, 1]
    error: str | None
    created: float
    updated: float
    steps: list[SetupStep] = Field(max_length=4)
    result: StepResult | None


class SetupEnrollment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    approved: bool
    issuer: str
    email: str
    status: AccessStatus


class SetupView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=UUID_PATTERN)
    revision: int = Field(ge=1)
    state: Literal["draft", "started", "discarded"]
    saved: float
    operation_id: str | None
    data: SetupData
    instance: str | None
    hostname: str | None
    operation: SetupOperation | None = None
    enrollment: SetupEnrollment | None = None
    lifecycle: (
        Literal[
            "scheduled",
            "awaiting_approval",
            "waiting_for_sign_in",
            "identity_approved_recovery_pending",
            "expired",
        ]
        | None
    ) = None
    invitation: str | None = None
    ready_instructions: None = None
    review_hash: str | None = None


class SetupDirectory(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    items: list[SetupView] = Field(max_length=100)

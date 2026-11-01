"""Operation-owned maintenance does not grant access or change identity bindings."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MaintenanceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    id: str
    owner: str
    action: Literal["pause", "resume"]
    expected_revision: int = Field(ge=0)
    expected_admin_revision: int = Field(ge=0)
    expected_binding_revision: int = Field(ge=0)
    expected_fence: int = Field(ge=0)
    authority_reference: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)
    release: str = Field(pattern=r"^[a-f0-9]{64}$")
    revoke_sessions: bool = False
    restore_access: bool = False

    @model_validator(mode="after")
    def coherent(self):
        if any(str(UUID(value)) != value for value in (self.id, self.owner)):
            raise ValueError("Canonical command and upgrade identities are required.")
        if not self.reason.strip() or (self.action == "pause" and self.restore_access):
            raise ValueError("Only acceptance can restore access.")
        if self.action == "resume" and self.revoke_sessions:
            raise ValueError("Session handling is decided before interruption.")
        return self


class MaintenanceState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    revision: int = Field(ge=0)
    owner: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$"
    )
    release: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    generation: int = Field(ge=0)
    binding: int = Field(ge=0)
    fence: int = Field(ge=0)
    was_active: bool

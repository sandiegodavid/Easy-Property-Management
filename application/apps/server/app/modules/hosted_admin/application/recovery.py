"""Bounded recovery handoffs and private verifier reports; no browser assertions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.hosted_admin.application.qualification import UUID_PATTERN


class RecoveryBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    instance: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")
    workspace_id: str = Field(pattern=UUID_PATTERN)
    binding_revision: int = Field(ge=1)
    subject: str = Field(min_length=1, max_length=255)
    configuration_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved_at: float = Field(ge=0, allow_inf_nan=False)
    release: str = Field(min_length=1, max_length=128)


class RecoveryCompletionTimes(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    archive: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    readback: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    restore: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    approved_binding: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    acceptance: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class RecoveryReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    id: str = Field(pattern=UUID_PATTERN)
    handoff_id: str = Field(pattern=UUID_PATTERN)
    binding: RecoveryBinding
    state: Literal["verified", "failed"]
    archive_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    binding_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    snapshot_marker: str | None = Field(default=None, max_length=128)
    archive_reference: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    binding_reference: str | None = Field(default=None, pattern=UUID_PATTERN)
    verifier_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    completed: RecoveryCompletionTimes = Field(default_factory=RecoveryCompletionTimes)
    archive: bool = False
    readback: bool = False
    restore: bool = False
    approved_binding: bool = False
    acceptance: bool = False
    observed: float = Field(ge=0, allow_inf_nan=False)
    expires: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def coherent(self):
        if self.expires <= self.observed or (
            self.state == "verified"
            and not all(
                (
                    self.archive,
                    self.readback,
                    self.restore,
                    self.approved_binding,
                    self.acceptance,
                    self.archive_digest,
                    self.binding_digest,
                    self.snapshot_marker,
                    self.archive_reference,
                    self.binding_reference,
                    self.verifier_digest,
                    all(
                        stamp is not None and self.binding.approved_at <= stamp <= self.observed
                        for stamp in self.completed.model_dump().values()
                    ),
                    self.observed >= self.binding.approved_at,
                )
            )
        ):
            raise ValueError("Recovery requires all independently verified checks after approval.")
        return self


class RecoveryCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    handoff_id: str = Field(pattern=UUID_PATTERN)
    expected_revision: int = Field(ge=0)

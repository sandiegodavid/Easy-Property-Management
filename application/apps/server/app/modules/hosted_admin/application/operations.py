"""Closed durable orchestration contracts. Provider observations are never browser assertions."""

from dataclasses import dataclass
import hashlib
import json
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OperationIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_id: str = Field(pattern=r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")
    kind: Literal["provision", "qualification_test"]
    target: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    expected_revision: int = Field(ge=0)
    qualification_id: str | None = Field(default=None, max_length=36)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def coherent(self):
        if not self.reason.strip() or (self.kind == "qualification_test") != bool(
            self.qualification_id
        ):
            raise ValueError("The operation requires its exact qualification and reason.")
        return self


class Reservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    kind: Literal[
        "hostname", "port", "user", "mount", "image", "workspace", "email", "disk", "memory"
    ]
    identity: str = Field(min_length=1, max_length=254)
    amount: int = Field(default=0, ge=0)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class Observation:
    state: Literal["absent", "verified", "unknown", "conflict", "waiting"]
    result: dict | None = None
    reference: str | None = None


class EffectAdapter(Protocol):
    def inspect(self, payload: dict, step: str) -> Observation:
        """Reconcile exact operation ownership/specification before any retry."""

    def apply(self, payload: dict, step: str) -> None:
        """Apply the fixed registered step; never return unverified success."""

    def contain(self, payload: dict) -> bool:
        """Verify access denial after a cancellation or concurrent authority fence."""


class StepResult(BaseModel):
    """Safe checkpoint/result projection; never persist raw provider responses."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_id: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$"
    )
    action: (
        Literal[
            "approve",
            "enable",
            "complete_onboarding",
            "disable",
            "revoke",
            "rebind",
            "restore_reset",
            "renew",
            "replace_email",
        ]
        | None
    ) = None
    revision: int | None = Field(default=None, ge=0)
    binding_revision: int | None = Field(default=None, ge=0)
    fence: int | None = Field(default=None, ge=0)
    generation: int | None = Field(default=None, ge=0)
    active: bool | None = None
    verified: bool | None = None
    done: bool | None = None
    resource_reference: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
    )
    spec_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

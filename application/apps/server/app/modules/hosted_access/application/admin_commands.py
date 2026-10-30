"""Source-owned administrative command contract, independent of browser transport."""

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_ENROLLMENTS = 16

AccessAction = Literal[
    "approve",
    "enable",
    "complete_onboarding",
    "disable",
    "revoke",
    "rebind",
    "renew",
    "replace_email",
]


class ActivationEvidence(BaseModel):
    """Private source-runner projection, validated against the owning row atomically."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    evidence_id: str = Field(min_length=36, max_length=36)
    acceptance_id: str = Field(min_length=36, max_length=36)
    workspace_id: str = Field(min_length=36, max_length=36)
    binding_revision: int = Field(ge=1)
    subject: str = Field(min_length=1, max_length=255)
    deployment_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    verified_at: float = Field(ge=0, allow_inf_nan=False)
    expires: float = Field(ge=0, allow_inf_nan=False)


def deployment_fingerprint(deployment) -> str:
    values = deployment.model_dump(mode="json")
    values["capabilities"] = sorted(values["capabilities"])
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class AccessCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    operation_id: str = Field(min_length=36, max_length=36)
    action: AccessAction
    expected_revision: int = Field(ge=0)
    expected_binding_revision: int = Field(ge=0)
    fence: int = Field(ge=0)
    authority_reference: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    enrollment_received_at: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    evidence_id: str | None = Field(default=None, min_length=36, max_length=36)
    acceptance_id: str | None = Field(default=None, min_length=36, max_length=36)
    activation: ActivationEvidence | None = None
    starts: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    expires: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    replacement_email: str | None = Field(default=None, min_length=3, max_length=254)

    @model_validator(mode="after")
    def coherent(self):
        if str(UUID(self.operation_id)) != self.operation_id or not self.reason.strip():
            raise ValueError("A canonical command identity and reason are required.")
        enrollment = self.action in {"approve", "rebind"}
        if enrollment != (self.subject is not None and self.enrollment_received_at is not None):
            raise ValueError("Identity changes require the exact verified enrollment.")
        if not enrollment and (self.subject is not None or self.enrollment_received_at is not None):
            raise ValueError("This command does not accept an enrollment.")
        if self.action == "complete_onboarding" and not (self.evidence_id and self.acceptance_id):
            raise ValueError("Completion requires registered recovery and acceptance identities.")
        if self.action not in {"enable", "complete_onboarding"} and any(
            (self.evidence_id, self.acceptance_id, self.activation)
        ):
            raise ValueError("Only activation accepts registered evidence.")
        if (self.action == "renew") != (self.starts is not None and self.expires is not None):
            raise ValueError("Renewal requires an explicit new window.")
        if self.action != "renew" and (self.starts is not None or self.expires is not None):
            raise ValueError("Only renewal accepts dates.")
        if self.action == "renew" and not 0 < self.expires - self.starts <= 14 * 86400:
            raise ValueError("A renewal window is positive and at most fourteen days.")
        if (self.action == "replace_email") != (self.replacement_email is not None):
            raise ValueError("Only assisted replacement accepts a new email.")
        return self

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.model_dump(exclude={"activation"}), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode()).hexdigest()


class AccessResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_id: str = Field(pattern=r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")
    action: Literal[
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
    revision: int = Field(ge=1)
    binding_revision: int = Field(ge=0)
    fence: int = Field(ge=0)
    generation: int = Field(ge=0)
    active: bool


class EnrollmentReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    subject: str = Field(min_length=1, max_length=255)
    received_at: float = Field(ge=0, allow_inf_nan=False)


class AccessStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    admin_revision: int = Field(ge=0)
    binding_revision: int = Field(ge=0)
    admin_fence: int = Field(ge=0)
    generation: int = Field(ge=0)
    active: bool
    identity_approved: bool = False
    approved_subject: str | None = Field(default=None, max_length=255)
    approved_at: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    binding_matches_configuration: bool
    enrollments: list[EnrollmentReference] = Field(max_length=MAX_ENROLLMENTS)


class AccessQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    query: Literal["status", "receipt"]
    command: AccessCommand | None = None

    @model_validator(mode="after")
    def coherent(self):
        if (self.query == "receipt") != (self.command is not None):
            raise ValueError("An exact command is required only for receipt lookup.")
        return self

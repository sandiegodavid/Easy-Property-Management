"""Closed Admin RPC vocabulary; no paths, shell, environment or caller authority."""

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.modules.hosted_access.application.admin_commands import AccessCommand


class AdminError(ValueError):
    def __init__(self, code, status=403):
        super().__init__(code)
        self.code = code
        self.status = status


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_id: str = Field(min_length=36, max_length=36)
    instance: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    action: Literal["approve", "enable", "disable", "revoke", "rebind"]
    expected_revision: int = Field(ge=0)
    expected_binding_revision: int = Field(ge=0)
    fence: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=1000)
    confirmed: Literal[True]
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    enrollment_received_at: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def identity(self):
        if str(UUID(self.operation_id)) != self.operation_id or not self.reason.strip():
            raise ValueError("Canonical operation identity and reason required.")
        # Validate the source-owned shape before consuming an action authorization.
        # This placeholder confers no authority; admission supplies the protected identity.
        AccessCommand.model_validate(
            self.model_dump(exclude={"instance", "confirmed"})
            | {"authority_reference": "request-shape-validation"}
        )
        return self

    def fingerprint(self):
        return hashlib.sha256(
            json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class BrokerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    method: Literal[
        "login",
        "session",
        "logout",
        "reauthenticate",
        "command",
        "lookup",
        "source_status",
        "operation",
        "operation_list",
        "resume",
        "cancel",
    ]
    token: str = Field(default="", max_length=128)
    csrf: str = Field(default="", max_length=128)
    credential: str = Field(default="", max_length=128)
    command: CommandRequest | None = None
    operation_id: str | None = Field(default=None, min_length=36, max_length=36)
    expected_revision: int | None = Field(default=None, ge=1)
    instance: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,31}$")

    @model_validator(mode="after")
    def coherent(self):
        if (self.method in {"command", "reauthenticate"}) != (self.command is not None):
            raise ValueError("This operation requires exactly its registered command.")
        if (self.method in {"lookup", "operation", "resume", "cancel"}) != (
            self.operation_id is not None
        ):
            raise ValueError("Only lookup accepts an operation identity.")
        if (self.method in {"resume", "cancel"}) != (self.expected_revision is not None):
            raise ValueError("Operation controls require the reviewed revision.")
        if self.operation_id is not None and str(UUID(self.operation_id)) != self.operation_id:
            raise ValueError("Canonical lookup identity required.")
        if (self.method == "source_status") != (self.instance is not None):
            raise ValueError("Only source status accepts an instance selector.")
        return self

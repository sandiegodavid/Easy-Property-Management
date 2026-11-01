"""Closed Admin RPC vocabulary; no paths, shell, environment or caller authority."""

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.modules.hosted_access.application.admin_commands import AccessCommand
from app.modules.hosted_admin.application.console import HostSection, InstanceSection
from app.modules.hosted_admin.application.setup import SetupCommand
from app.modules.hosted_admin.application.recovery import RecoveryCheck
from app.modules.hosted_admin.application.upgrades import UpgradeCommand
from app.modules.hosted_admin.application.upgrade_batches import BatchCommand


class AdminError(ValueError):
    def __init__(self, code, status=403):
        super().__init__(code)
        self.code = code
        self.status = status


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_id: str = Field(min_length=36, max_length=36)
    instance: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    action: Literal[
        "approve",
        "enable",
        "complete_onboarding",
        "disable",
        "revoke",
        "rebind",
        "renew",
        "replace_email",
    ]
    expected_revision: int = Field(ge=0)
    expected_binding_revision: int = Field(ge=0)
    fence: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=1000)
    confirmed: Literal[True]
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    enrollment_received_at: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    evidence_id: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$"
    )
    acceptance_id: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$"
    )
    starts: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    expires: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    replacement_email: str | None = Field(default=None, min_length=3, max_length=254)

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
        "console_directory",
        "console_record",
        "console_observation",
        "console_qualification",
        "console_operation",
        "setup_options",
        "setup_list",
        "setup_get",
        "setup_status",
        "setup_command",
        "recovery_handoff",
        "recovery_check",
        "recovery_acknowledge",
        "upgrade_options",
        "upgrade_command",
        "upgrade_view",
        "upgrade_lookup",
        "batch_command",
        "batch_view",
        "batch_lookup",
        "batch_list",
    ]
    token: str = Field(default="", max_length=128)
    csrf: str = Field(default="", max_length=128)
    credential: str = Field(default="", max_length=128)
    command: CommandRequest | None = None
    operation_id: str | None = Field(default=None, min_length=36, max_length=36)
    expected_revision: int | None = Field(default=None, ge=1)
    instance: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")
    offset: int = Field(default=0, ge=0, le=950, multiple_of=50)
    section: HostSection | InstanceSection | None = None
    setup: SetupCommand | None = None
    recovery: RecoveryCheck | None = None
    upgrade: UpgradeCommand | None = None
    batch: BatchCommand | None = None
    batch_offset: int = Field(default=0, ge=0, le=49)
    batch_limit: int = Field(default=10, ge=1, le=50)
    batch_page: int = Field(default=0, ge=0, le=990, multiple_of=10)
    draft_id: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$"
    )

    @model_validator(mode="after")
    def coherent(self):
        if self.method != "batch_list" and self.batch_page:
            raise ValueError("Only batch history accepts directory pagination.")
        if (self.method == "batch_command") != (self.batch is not None):
            raise ValueError("Batch commands require their exact reviewed intent.")
        if self.method != "batch_view" and (self.batch_offset or self.batch_limit != 10):
            raise ValueError("Only batch progress accepts member pagination.")
        if (self.method == "upgrade_command") != (self.upgrade is not None):
            raise ValueError("Upgrade commands require their exact typed intent.")
        if (self.method in {"recovery_check", "recovery_acknowledge"}) != (
            self.recovery is not None
        ):
            raise ValueError("Recovery checks accept only a registered handoff and revision.")
        if (self.method == "setup_command") != (self.setup is not None):
            raise ValueError("Only setup commands accept setup changes.")
        if (self.method in {"setup_get", "setup_status"}) != (self.draft_id is not None):
            raise ValueError("Select exactly one saved setup.")
        if (self.method in {"command", "reauthenticate"}) != (self.command is not None):
            raise ValueError("This operation requires exactly its registered command.")
        if (
            self.method
            in {
                "lookup",
                "operation",
                "resume",
                "cancel",
                "console_operation",
                "upgrade_view",
                "upgrade_lookup",
                "batch_view",
                "batch_lookup",
            }
        ) != (self.operation_id is not None):
            raise ValueError("Only lookup accepts an operation identity.")
        if (self.method in {"resume", "cancel"}) != (self.expected_revision is not None):
            raise ValueError("Operation controls require the reviewed revision.")
        if self.operation_id is not None and str(UUID(self.operation_id)) != self.operation_id:
            raise ValueError("Canonical lookup identity required.")
        if (
            self.method
            in {"source_status", "console_record", "recovery_handoff", "upgrade_options"}
            or (
                self.method == "console_observation"
                and self.section in {"access", "runtime", "recovery"}
            )
        ) != (self.instance is not None):
            raise ValueError("Only source status accepts an instance selector.")
        if (self.method == "console_observation") != (self.section is not None):
            raise ValueError("Observations require a registered section.")
        if self.method != "console_directory" and self.offset:
            raise ValueError("Only the directory accepts a page offset.")
        return self

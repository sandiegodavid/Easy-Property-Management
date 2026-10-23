"""Validated, non-secret deployment identity for one hosted workspace."""

from datetime import timedelta
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

CAPABILITIES = frozenset({"records.read", "records.write", "files.read", "files.write"})
DEMO_DURATION = timedelta(days=14)
SESSION_DURATION = timedelta(hours=8)
MAX_FILE_BYTES = 50 * 1024 * 1024
WORKSPACE_BYTES = 250 * 1024 * 1024


class HostedConfigurationError(ValueError):
    """Safe deployment error, without submitted configuration or credentials."""


def exact_https_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        value != value.strip()
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname != parsed.hostname.lower()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.port is not None
        or parsed.netloc != parsed.hostname
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", parsed.hostname)
        or "." not in parsed.hostname
        or not any(character.isalpha() for character in parsed.hostname)
        or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in parsed.hostname.split(".")
        )
    ):
        raise ValueError("An exact HTTPS DNS origin without a port is required.")
    return value


class HostedDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    deployment_mode: Literal["hosted_demo"]
    public_origin: str = Field(max_length=253)
    identity_issuer: str = Field(max_length=253)
    identity_audience: str = Field(pattern=r"^[a-f0-9]{64}$")
    workspace_id: UUID
    operator_id: UUID
    allowed_email: str = Field(min_length=3, max_length=254)
    administrator_contact: str = Field(min_length=3, max_length=254)
    administration_database: Path
    storage_volume: Path
    storage_image: Path
    enabled_at: AwareDatetime
    expires_at: AwareDatetime
    capabilities: frozenset[Literal["records.read", "records.write", "files.read", "files.write"]]

    @field_validator("public_origin", "identity_issuer")
    @classmethod
    def valid_origin(cls, value: str) -> str:
        return exact_https_origin(value)

    @field_validator("allowed_email", "administrator_contact")
    @classmethod
    def valid_email(cls, value: str) -> str:
        if not re.fullmatch(r"[^\s@<>]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", value):
            raise ValueError("An exact email address is required.")
        return value

    @field_validator("administration_database")
    @classmethod
    def absolute_database(cls, value: Path) -> Path:
        if not value.is_absolute() or value.suffix != ".sqlite":
            raise ValueError("An absolute administrative SQLite path is required.")
        return value

    @field_validator("storage_volume", "storage_image")
    @classmethod
    def absolute_storage(cls, value: Path) -> Path:
        if not value.is_absolute() or value == Path("/") or ".." in value.parts:
            raise ValueError("An explicit absolute storage path is required.")
        return value

    @model_validator(mode="after")
    def coherent_deployment(self):
        duration = self.expires_at - self.enabled_at
        if duration <= timedelta(0) or duration > DEMO_DURATION:
            raise ValueError("The enabled demo window must be positive and at most fourteen days.")
        if "records.read" not in self.capabilities:
            raise ValueError("Hosted demo requires records.read.")
        if "files.write" in self.capabilities and not {"files.read", "records.write"}.issubset(
            self.capabilities
        ):
            raise ValueError("File writes require file reads and record writes.")
        return self

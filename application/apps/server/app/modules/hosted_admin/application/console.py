"""Closed, privacy-safe read contracts for the separate administration console."""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

InstanceSection = Literal["access", "runtime", "recovery"]
HostSection = Literal["capacity", "tunnel", "discrepancies"]


class ConsoleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RegisteredOperator(ConsoleRecord):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(max_length=254)
    hostname: str = Field(pattern=r"^[a-z0-9.-]{1,253}$")
    release: str = Field(max_length=128)
    profile: str = Field(max_length=128)
    registered_revision: int = Field(ge=1)
    setup_id: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$"
    )


class AccessObservation(ConsoleRecord):
    active: bool
    binding_matches: bool
    pending_enrollments: int = Field(ge=0, le=100)
    starts: float = Field(ge=0, allow_inf_nan=False)
    expires: float = Field(ge=0, allow_inf_nan=False)
    capabilities: list[str] = Field(max_length=4)


class RuntimeObservation(ConsoleRecord):
    service: Literal["active", "inactive", "failed", "activating", "deactivating", "unknown"]
    mount_verified: bool
    release_matches: bool


class RecoveryObservation(ConsoleRecord):
    # Separate checks: none is inferred from a file or uploaded archive.
    local_archive: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    off_host_readback: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    restore_drill: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    approved_binding: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class TunnelObservation(ConsoleRecord):
    service: Literal["active", "inactive", "failed", "activating", "deactivating", "unknown"]
    startup: Literal["enabled", "disabled", "unknown"]


class DiscrepancyObservation(ConsoleRecord):
    unregistered: list[str] = Field(max_length=1000)
    missing: list[str] = Field(max_length=1000)


class ConsoleInventory(Protocol):
    def records(self) -> list[RegisteredOperator]: ...

    def observe(self, section: str, instance: str | None) -> BaseModel: ...

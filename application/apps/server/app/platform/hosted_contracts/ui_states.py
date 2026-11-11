"""H01.6 UI state primitives, not screens, actions or authorization grants."""

from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import Field, StrictBool, model_validator

from app.platform.hosted_contracts.reads import Freshness, FreshnessState
from app.platform.hosted_contracts.values import (
    Contract,
    Count,
    Explanation,
    Reference,
    SafeCode,
)


class UIAction(StrEnum):
    CREATE_ASSIGNMENT = "admin_create_assignment"
    PROVISION = "admin_provision"
    CHECK_OPERATION = "admin_check_operation"
    RETRY_OPERATION = "admin_retry_operation"
    REFRESH_SOURCE = "admin_refresh_source"
    REISSUE_INVITATION = "admin_reissue_invitation"
    DISABLE = "admin_disable"
    ENABLE = "admin_enable"
    REBIND = "admin_rebind"
    PREPARE_RETIREMENT = "admin_prepare_retirement"
    CONFIRM_RETIREMENT = "admin_confirm_retirement"
    REPAIR_RUNTIME = "admin_repair_runtime"
    ANNOUNCE_MAINTENANCE = "admin_announce_maintenance"
    MAINTENANCE_RELEASE = "admin_maintenance_release"
    PREVIEW_CONTROL_RESTORE = "admin_preview_control_restore"
    CONFIRM_CONTROL_RESTORE = "admin_confirm_control_restore"
    READ_SETTINGS = "operator_read_settings"
    LIST_POINTS = "operator_list_points"
    PREVIEW_RESTORE = "operator_preview_restore"
    RECENT_AUTHENTICATE = "operator_recent_authenticate"
    CONFIRM_RESTORE = "operator_confirm_restore"
    CHECK_RESTORE = "operator_check_restore"


class ActionState(Contract):
    action: UIAction
    enabled: StrictBool
    reason: SafeCode | None = None

    @model_validator(mode="after")
    def explained_availability(self):
        if self.enabled == (self.reason is not None):
            raise ValueError("Disabled actions need a reason; enabled actions cannot carry one.")
        return self


Actions = Annotated[tuple[ActionState, ...], Field(max_length=22)]
RecordT = TypeVar("RecordT", bound=Contract)


class Section(Contract, Generic[RecordT]):
    state: Literal["loading", "ready", "refreshing", "stale", "failed", "unavailable"]
    data: RecordT | None = None
    freshness: Freshness | None = None

    @model_validator(mode="after")
    def truthful_section(self):
        if self.state in {"ready", "stale", "refreshing"}:
            if self.data is None or self.freshness is None:
                raise ValueError("A visible observation needs data and capture/source context.")
            expected = (
                {FreshnessState.KNOWN}
                if self.state == "ready"
                else {FreshnessState.KNOWN, FreshnessState.STALE}
            )
            if self.freshness.state not in expected:
                raise ValueError(
                    "Visible data must retain known/stale freshness, not unknown facts."
                )
            if self.state == "stale" and self.freshness.state != FreshnessState.STALE:
                raise ValueError("A stale section must describe its stale source.")
        elif self.data is not None:
            raise ValueError("Missing/loading/failed sections cannot fabricate data.")
        elif self.state == "loading":
            if self.freshness is not None:
                raise ValueError("Initial loading cannot invent a capture.")
        elif self.freshness is None or self.freshness.state not in {
            FreshnessState.UNKNOWN,
            FreshnessState.UNAVAILABLE,
        }:
            raise ValueError("A failed/unavailable section needs a safe unknown-source reason.")
        return self


class Preservation(Contract):
    input_values: StrictBool = True
    focus: StrictBool = True
    scroll: StrictBool = True
    automatic_command_replay: StrictBool = False

    @model_validator(mode="after")
    def preserve_context(self):
        if not all((self.input_values, self.focus, self.scroll)) or self.automatic_command_replay:
            raise ValueError("Background updates retain context and never replay commands.")
        return self


class Gate(Contract):
    name: SafeCode
    state: Literal["passed", "pending", "failed", "unavailable"]
    evidence_ref: Reference | None = None

    @model_validator(mode="after")
    def no_unproven_pass(self):
        if self.state == "passed" and self.evidence_ref is None:
            raise ValueError("Passed readiness needs its protected evidence reference.")
        return self


class FreeUsage(Contract):
    plan: Literal["free"] = "free"
    usable_bytes: Literal[50_000_000] = 50_000_000
    used_bytes: Count


class Protection(Contract):
    status: Literal["protected", "degraded"]
    last_verified_at: Count | None
    point_age_ms: Count | None
    proof_ref: Reference | None

    @model_validator(mode="after")
    def verified_protection(self):
        if (self.last_verified_at is None) != (self.point_age_ms is None):
            raise ValueError("Verified point time and age must be present together.")
        if self.status == "protected" and (self.last_verified_at is None or self.proof_ref is None):
            raise ValueError("Protection cannot be healthy without a verified point.")
        return self


class MaintenanceNotice(Contract):
    message: Explanation
    starts_at: Count
    ends_at: Count

    @model_validator(mode="after")
    def valid_window(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Announced maintenance must end after it starts.")
        return self

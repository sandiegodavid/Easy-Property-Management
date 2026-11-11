"""H01.6 Operator Settings/recovery presentation contracts, not current auth grants."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.modules.workspace.application.recovery_contracts import (
    WorkspaceRecoveryObservation,
    WorkspaceRecoveryResult,
)
from app.platform.hosted_contracts.authority import ObservationPage
from app.platform.hosted_contracts.operations import OperationOutcome, OperationState
from app.platform.hosted_contracts.ui_states import (
    Actions,
    FreeUsage,
    Gate,
    MaintenanceNotice,
    Preservation,
    Protection,
    Section,
)
from app.platform.hosted_contracts.values import (
    CanonicalId,
    Contract,
    EmailAddress,
    RequestHash,
    SafeCode,
    WorkspaceScope,
)


class Settings(Contract):
    surface: Literal["operator_settings"] = "operator_settings"
    delivery_owner: Literal["H04"] = "H04"
    scope: WorkspaceScope
    usage: Section[FreeUsage]
    protection: Section[Protection]
    support_contact: EmailAddress
    maintenance: Section[MaintenanceNotice]
    preservation: Preservation = Preservation()
    actions: Actions


class Recovery(Contract):
    surface: Literal["operator_recovery"] = "operator_recovery"
    delivery_owner: Literal["H05"] = "H05"
    scope: WorkspaceScope
    mode: Literal["normal", "recovery"]
    state: Literal[
        "unavailable", "choose_point", "confirm", "running", "outcome_unknown", "completed"
    ]
    availability_reason: SafeCode | None = None
    gates: Annotated[tuple[Gate, ...], Field(min_length=5, max_length=5)]
    catalog: Section[ObservationPage[WorkspaceRecoveryObservation]]
    selected_point_id: CanonicalId | None = None
    preview_id: CanonicalId | None = None
    exact_request_hash: RequestHash | None = None
    original_outcome: OperationOutcome[WorkspaceRecoveryResult] | None = None
    preservation: Preservation = Preservation()
    actions: Actions

    @model_validator(mode="after")
    def gated_recovery(self):
        required = {
            "current_identity",
            "qualified_engine",
            "verified_catalog",
            "runtime_ready",
            "strong_step_up",
        }
        checks = {gate.name: gate.state for gate in self.gates}
        if set(checks) != required:
            raise ValueError("Recovery gates must remain explicit and independent.")
        if self.state == "unavailable":
            if not self.availability_reason:
                raise ValueError("Unavailable restore needs a safe explanation.")
        elif self.availability_reason is not None:
            raise ValueError("Available recovery cannot carry an unavailable reason.")
        if self.catalog.data is not None and checks["current_identity"] != "passed":
            raise ValueError("Catalog data requires current operator identity.")
        if self.state in {"choose_point", "confirm"}:
            if self.catalog.state != "ready":
                raise ValueError("Restore selection/confirmation needs a fresh available catalog.")
            base = required - {"strong_step_up"}
            if any(checks[name] != "passed" for name in base):
                raise ValueError(
                    "Recovery cannot proceed without qualified current authority/runtime/catalog."
                )
        if self.state == "confirm":
            if checks["strong_step_up"] != "passed" or not all(
                (self.selected_point_id, self.preview_id, self.exact_request_hash)
            ):
                raise ValueError(
                    "Restore confirmation requires strong step-up and an exact point/preview/intent."
                )
        expected = {
            "running": {OperationState.PENDING, OperationState.RUNNING},
            "outcome_unknown": {OperationState.UNKNOWN},
            "completed": {OperationState.SUCCEEDED},
        }
        if self.state in expected and (
            self.original_outcome is None or self.original_outcome.state not in expected[self.state]
        ):
            raise ValueError("Restore progress must retain its original scoped operation.")
        if self.original_outcome is not None and self.exact_request_hash is not None:
            if self.original_outcome.operation.request_hash != self.exact_request_hash:
                raise ValueError(
                    "Restore progress must retain its exact original confirmed intent."
                )
        if (
            self.original_outcome is not None
            and self.original_outcome.operation.scope != self.scope
        ):
            raise ValueError("Recovery cannot display another workspace's operation.")
        if self.catalog.data is not None and self.catalog.data.continuation is not None:
            if self.catalog.data.continuation.context.scope != self.scope:
                raise ValueError("Recovery continuation must remain in the owning workspace.")
        return self

"""H01.4 AdminRecovery owning ports; contracts only, no production implementation.

Adapters authenticate the invocation, verify proof freshness/current fences, commit
original operation/audit/receipt atomically and reconcile unknown effects. Never do
network/host work inside a store transaction or expose these as placeholder routes.
"""

from typing import Annotated, Literal, Protocol

from pydantic import Field, model_validator

from app.platform.hosted_contracts.authority import (
    ServiceAuthority,
    AdminRecoveryAuthority,
    ObservationPage,
    ObservationQuery,
    require_scope,
)
from app.platform.hosted_contracts.operations import (
    CommandEnvelope,
    OperationOutcome,
    OperationReference,
)
from app.platform.hosted_contracts.reads import Freshness
from app.platform.hosted_contracts.semantic import SemanticRequest
from app.platform.hosted_contracts.values import (
    CanonicalId,
    EpochMillis,
    Reference,
    RequestHash,
    Revision,
)


class PreviewControlRestore(SemanticRequest):
    action: Literal["preview_control_restore"] = "preview_control_restore"
    point_id: CanonicalId


class ConfirmControlRestore(SemanticRequest):
    action: Literal["confirm_control_restore"] = "confirm_control_restore"
    point_id: CanonicalId
    preview_id: CanonicalId
    confirmation_id: CanonicalId


class CaptureControl(SemanticRequest):
    action: Literal["capture_control"] = "capture_control"
    capture_policy_ref: Reference
    expected_checkpoint_revision: Revision


class ReconcileCheckpoint(SemanticRequest):
    action: Literal["reconcile_checkpoint"] = "reconcile_checkpoint"
    capture_operation_id: CanonicalId


Action = Annotated[
    PreviewControlRestore | ConfirmControlRestore | CaptureControl | ReconcileCheckpoint,
    Field(discriminator="action"),
]


class AdminRecoveryCommand(CommandEnvelope[Action]):
    @model_validator(mode="after")
    def matching_action(self):
        if self.intent.kind != self.intent.payload.action:
            raise ValueError("Envelope kind must match its owning action.")
        return self


class AdminRecoveryResult(SemanticRequest):
    point_id: CanonicalId
    phase: Literal["preview", "captured", "restoring", "restored", "reconciled"]
    receipt_ref: Reference


class AdminRecoveryObservation(SemanticRequest):
    resource_id: CanonicalId
    revision: Revision
    freshness: Freshness
    captured_at: EpochMillis
    verified_at: EpochMillis
    manifest_sha256: RequestHash
    eligible: bool


class AdminRecoveryPort(Protocol):
    """Private owning API; observations never grant mutation/recovery authority.

    Verify current invocation, expected revision and epoch for each call. Matching
    keys return the original identity/result; changed semantics conflict. Unknown
    effects require receipt inspection, not blind replay. Reads are bounded and
    independent of another owner's database; no raw locators/credentials returned.
    """

    def execute(
        self, actor: AdminRecoveryAuthority | ServiceAuthority, command: AdminRecoveryCommand
    ) -> OperationOutcome[AdminRecoveryResult]: ...
    def observe(
        self, actor: AdminRecoveryAuthority, query: ObservationQuery
    ) -> ObservationPage[AdminRecoveryObservation]: ...
    def original(
        self, actor: AdminRecoveryAuthority | ServiceAuthority, reference: OperationReference
    ) -> OperationOutcome[AdminRecoveryResult] | None: ...


def require_invocation(
    actor: AdminRecoveryAuthority | ServiceAuthority, command: AdminRecoveryCommand
) -> None:
    if command.intent.payload.action in {"capture_control", "reconcile_checkpoint"}:
        if not isinstance(actor, ServiceAuthority) or actor.service != "admin_backup":
            raise ValueError("Control capture belongs to the private Admin backup engine.")
    elif not isinstance(actor, AdminRecoveryAuthority):
        raise ValueError("Current protected bootstrap/MFA recovery authority is required.")
    elif actor.confirmed_request_hash != command.request_hash:
        raise ValueError("Control recovery confirmation must bind the exact original intent.")
    require_scope(actor, command)
    if command.intent.scope.kind != "deployment":
        raise ValueError("Admin recovery cannot restore a customer workspace.")

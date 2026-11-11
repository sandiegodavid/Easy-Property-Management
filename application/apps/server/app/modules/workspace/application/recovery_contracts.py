"""H01.4 WorkspaceRecovery owning ports; contracts only, no production implementation.

Adapters authenticate the invocation, verify proof freshness/current fences, commit
original operation/audit/receipt atomically and reconcile unknown effects. Never do
network/host work inside a store transaction or expose these as placeholder routes.
"""

from typing import Annotated, Literal, Protocol

from pydantic import Field, model_validator

from app.platform.hosted_contracts.authority import (
    LocalRestoreAuthority,
    OperatorRestoreAuthority,
    ServiceAuthority,
    OperatorAuthority,
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


class PreviewRestore(SemanticRequest):
    action: Literal["preview_restore"] = "preview_restore"
    point_id: CanonicalId


class ConfirmRestore(SemanticRequest):
    action: Literal["confirm_restore"] = "confirm_restore"
    point_id: CanonicalId
    preview_id: CanonicalId
    confirmation_id: CanonicalId


class Capture(SemanticRequest):
    action: Literal["capture"] = "capture"
    capture_policy_ref: Reference
    expected_checkpoint_revision: Revision


class ReconcileCheckpoint(SemanticRequest):
    action: Literal["reconcile_checkpoint"] = "reconcile_checkpoint"
    capture_operation_id: CanonicalId


class ReconstructCatalog(SemanticRequest):
    action: Literal["reconstruct_catalog"] = "reconstruct_catalog"
    own_manifest_set_ref: Reference


Action = Annotated[
    PreviewRestore | ConfirmRestore | Capture | ReconcileCheckpoint | ReconstructCatalog,
    Field(discriminator="action"),
]


class WorkspaceRecoveryCommand(CommandEnvelope[Action]):
    @model_validator(mode="after")
    def matching_action(self):
        if self.intent.kind != self.intent.payload.action:
            raise ValueError("Envelope kind must match its owning action.")
        return self


class WorkspaceRecoveryResult(SemanticRequest):
    point_id: CanonicalId
    phase: Literal["preview", "captured", "restoring", "restored", "reconciled"]
    receipt_ref: Reference


class WorkspaceRecoveryObservation(SemanticRequest):
    resource_id: CanonicalId
    revision: Revision
    freshness: Freshness
    captured_at: EpochMillis
    verified_at: EpochMillis
    manifest_sha256: RequestHash
    eligible: bool


class WorkspaceRecoveryPort(Protocol):
    """Private owning API; observations never grant mutation/recovery authority.

    Verify current invocation, expected revision and epoch for each call. Matching
    keys return the original identity/result; changed semantics conflict. Unknown
    effects require receipt inspection, not blind replay. Reads are bounded and
    independent of another owner's database; no raw locators/credentials returned.
    """

    def execute(
        self,
        actor: OperatorAuthority | LocalRestoreAuthority | ServiceAuthority,
        command: WorkspaceRecoveryCommand,
    ) -> OperationOutcome[WorkspaceRecoveryResult]: ...
    def observe(
        self, actor: OperatorAuthority | LocalRestoreAuthority, query: ObservationQuery
    ) -> ObservationPage[WorkspaceRecoveryObservation]: ...
    def original(
        self,
        actor: OperatorAuthority | LocalRestoreAuthority | ServiceAuthority,
        reference: OperationReference,
    ) -> OperationOutcome[WorkspaceRecoveryResult] | None: ...


def require_invocation(
    actor: OperatorAuthority | LocalRestoreAuthority | ServiceAuthority,
    command: WorkspaceRecoveryCommand,
) -> None:
    action = command.intent.payload.action
    if action in {"capture", "reconcile_checkpoint"}:
        if not isinstance(actor, ServiceAuthority) or actor.service != "operator_backup":
            raise ValueError("Workspace backup belongs to its private system engine.")
    elif action == "confirm_restore":
        if not isinstance(actor, (OperatorRestoreAuthority, LocalRestoreAuthority)):
            raise ValueError(
                "Restore requires current operator step-up or local OS-owner authority."
            )
        if actor.confirmed_request_hash != command.request_hash:
            raise ValueError("Restore confirmation must bind the exact original intent.")
    elif not isinstance(actor, (OperatorAuthority, LocalRestoreAuthority)):
        raise ValueError("Recovery catalog/preview belongs to the current operator only.")
    require_scope(actor, command)
    if command.intent.scope.kind != "workspace":
        raise ValueError("Workspace recovery cannot target deployment/control data.")

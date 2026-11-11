"""H01.4 Source owning ports; contracts only, no production implementation.

Adapters authenticate the invocation, verify proof freshness/current fences, commit
original operation/audit/receipt atomically and reconcile unknown effects. Never do
network/host work inside a store transaction or expose these as placeholder routes.
"""

from typing import Annotated, Literal, Protocol

from pydantic import Field, model_validator

from app.platform.hosted_contracts.authority import (
    ServiceAuthority,
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
    Count,
    Explanation,
    Reference,
    Revision,
)


class InitializeDisabled(SemanticRequest):
    action: Literal["initialize_disabled"] = "initialize_disabled"
    binding_id: CanonicalId
    policy_id: CanonicalId
    assignment_id: CanonicalId


class Claim(SemanticRequest):
    action: Literal["claim"] = "claim"
    invitation_id: CanonicalId
    verified_identity_ref: Reference
    readiness_proof_ref: Reference


class Enable(SemanticRequest):
    action: Literal["enable"] = "enable"
    readiness_proof_ref: Reference


class Disable(SemanticRequest):
    action: Literal["disable"] = "disable"
    reason: Explanation


class Revoke(SemanticRequest):
    action: Literal["revoke"] = "revoke"
    session_reference: Reference | None
    all_devices: bool


class MaintenanceFence(SemanticRequest):
    action: Literal["maintenance_fence"] = "maintenance_fence"
    maintenance_id: CanonicalId


class Drain(SemanticRequest):
    action: Literal["drain"] = "drain"
    maintenance_id: CanonicalId


class VerifyRestoreBinding(SemanticRequest):
    action: Literal["verify_restore_binding"] = "verify_restore_binding"
    point_id: CanonicalId
    restore_operation_id: CanonicalId


class ReserveUsage(SemanticRequest):
    action: Literal["reserve_usage"] = "reserve_usage"
    reservation_id: CanonicalId
    maximum_growth_bytes: Count
    policy_id: CanonicalId


class ReconcileUsage(SemanticRequest):
    action: Literal["reconcile_usage"] = "reconcile_usage"
    reservation_id: CanonicalId
    source_commit_ref: Reference


Action = Annotated[
    InitializeDisabled
    | Claim
    | Enable
    | Disable
    | Revoke
    | MaintenanceFence
    | Drain
    | VerifyRestoreBinding
    | ReserveUsage
    | ReconcileUsage,
    Field(discriminator="action"),
]


class SourceCommand(CommandEnvelope[Action]):
    @model_validator(mode="after")
    def matching_action(self):
        if self.intent.kind != self.intent.payload.action:
            raise ValueError("Envelope kind must match its owning action.")
        return self


class SourceResult(SemanticRequest):
    access_epoch: Revision
    effective_enabled: bool
    receipt_ref: Reference


class SourceObservation(SemanticRequest):
    resource_id: CanonicalId
    revision: Revision
    freshness: Freshness
    effective_enabled: bool | None
    access_epoch: Revision
    usage_bytes: Count | None
    maximum_bytes: Count | None
    readiness: Literal["ready", "pending", "unavailable"]


class SourcePort(Protocol):
    """Private owning API; observations never grant mutation/recovery authority.

    Verify current invocation, expected revision and epoch for each call. Matching
    keys return the original identity/result; changed semantics conflict. Unknown
    effects require receipt inspection, not blind replay. Reads are bounded and
    independent of another owner's database; no raw locators/credentials returned.
    """

    def execute(
        self, actor: ServiceAuthority, command: SourceCommand
    ) -> OperationOutcome[SourceResult]: ...
    def observe(
        self, actor: ServiceAuthority, query: ObservationQuery
    ) -> ObservationPage[SourceObservation]: ...
    def original(
        self, actor: ServiceAuthority, reference: OperationReference
    ) -> OperationOutcome[SourceResult] | None: ...


def require_invocation(actor: ServiceAuthority, command: SourceCommand) -> None:
    if not isinstance(actor, ServiceAuthority):
        raise ValueError("Wrong owning invocation authority.")
    require_scope(actor, command)
    if command.intent.scope.kind != "workspace":
        raise ValueError("Source commands require one workspace.")
    expected = (
        {"operator_recovery"}
        if command.intent.payload.action == "verify_restore_binding"
        else {"admin", "source"}
    )
    if actor.service not in expected:
        raise ValueError("Source command has the wrong calling service.")

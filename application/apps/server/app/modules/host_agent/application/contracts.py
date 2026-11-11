"""H01.4 Host owning ports; contracts only, no production implementation.

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
from app.platform.hosted_contracts.values import CanonicalId, Reference, Revision

IdList = Annotated[tuple[CanonicalId, ...], Field(min_length=1, max_length=8)]


class PrepareResources(SemanticRequest):
    action: Literal["prepare_resources"] = "prepare_resources"
    binding_id: CanonicalId
    image_id: CanonicalId
    release_id: CanonicalId
    admission_commitment_id: CanonicalId
    capacity_profile_ref: Reference


class InitializeContainer(SemanticRequest):
    action: Literal["initialize_container"] = "initialize_container"
    binding_id: CanonicalId
    image_id: CanonicalId
    release_id: CanonicalId


class RepairRuntime(SemanticRequest):
    action: Literal["repair_runtime"] = "repair_runtime"
    binding_id: CanonicalId
    image_id: CanonicalId
    release_id: CanonicalId
    expected_resource_generation: Revision


class StartContainer(SemanticRequest):
    action: Literal["start_container"] = "start_container"
    binding_id: CanonicalId


class StopContainer(SemanticRequest):
    action: Literal["stop_container"] = "stop_container"
    binding_id: CanonicalId


class ApplyLimits(SemanticRequest):
    action: Literal["apply_limits"] = "apply_limits"
    binding_id: CanonicalId
    qualified_limit_profile_id: CanonicalId


class StageRestore(SemanticRequest):
    action: Literal["stage_restore"] = "stage_restore"
    binding_id: CanonicalId
    restore_operation_id: CanonicalId
    restore_authorization_ref: Reference


class SwitchBinding(SemanticRequest):
    action: Literal["switch_binding"] = "switch_binding"
    active_binding_id: CanonicalId
    target_binding_id: CanonicalId
    restore_operation_id: CanonicalId
    restore_authorization_ref: Reference


class RetireResources(SemanticRequest):
    action: Literal["retire_resources"] = "retire_resources"
    binding_ids: IdList
    cleanup_proof_ref: Reference
    confirmation_id: CanonicalId


Action = Annotated[
    PrepareResources
    | InitializeContainer
    | RepairRuntime
    | StartContainer
    | StopContainer
    | ApplyLimits
    | StageRestore
    | SwitchBinding
    | RetireResources,
    Field(discriminator="action"),
]


class HostCommand(CommandEnvelope[Action]):
    @model_validator(mode="after")
    def matching_action(self):
        if self.intent.kind != self.intent.payload.action:
            raise ValueError("Envelope kind must match its owning action.")
        return self


class HostResult(SemanticRequest):
    binding_id: CanonicalId
    resource_generation: Revision
    effect_receipt_ref: Reference


class HostObservation(SemanticRequest):
    resource_id: CanonicalId
    revision: Revision
    freshness: Freshness
    ownership_verified: bool
    resource_generation: Revision
    release_id: CanonicalId
    qualified_profile_ref: Reference
    state: Literal["allocated", "prepared", "running", "stopped", "needs_attention", "retired"]


class HostPort(Protocol):
    """Private owning API; observations never grant mutation/recovery authority.

    Verify current invocation, expected revision and epoch for each call. Matching
    keys return the original identity/result; changed semantics conflict. Unknown
    effects require receipt inspection, not blind replay. Reads are bounded and
    independent of another owner's database; no raw locators/credentials returned.
    """

    def execute(
        self, actor: ServiceAuthority, command: HostCommand
    ) -> OperationOutcome[HostResult]: ...
    def observe(
        self, actor: ServiceAuthority, query: ObservationQuery
    ) -> ObservationPage[HostObservation]: ...
    def original(
        self, actor: ServiceAuthority, reference: OperationReference
    ) -> OperationOutcome[HostResult] | None: ...


def require_invocation(actor: ServiceAuthority, command: HostCommand) -> None:
    if not isinstance(actor, ServiceAuthority):
        raise ValueError("Wrong owning invocation authority.")
    require_scope(actor, command)
    if command.intent.payload.action in {"stage_restore", "switch_binding"}:
        expected = (
            "operator_recovery" if command.intent.scope.kind == "workspace" else "admin_recovery"
        )
        if actor.service != expected:
            raise ValueError("Only the owning recovery service may stage/switch restore targets.")
    elif actor.service != "admin":
        raise ValueError("Registered host lifecycle effects require the Admin service.")

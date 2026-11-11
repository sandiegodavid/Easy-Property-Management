"""H01.4 Admin owning ports; contracts only, no production implementation.

Adapters authenticate the invocation, verify proof freshness/current fences, commit
original operation/audit/receipt atomically and reconcile unknown effects. Never do
network/host work inside a store transaction or expose these as placeholder routes.
"""

from typing import Annotated, Literal, Protocol

from pydantic import Field, model_validator

from app.platform.hosted_contracts.authority import (
    AdminAuthority,
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
    Component,
    CanonicalId,
    Count,
    DisplayName,
    EmailAddress,
    EpochMillis,
    Explanation,
    Reference,
    PublicSlug,
    Revision,
)

IdList = Annotated[tuple[CanonicalId, ...], Field(min_length=1, max_length=8)]


class ResourceCeiling(SemanticRequest):
    bytes: Annotated[Count, Field(gt=0)]
    inodes: Annotated[Count, Field(gt=0)]


class AdmissionCommitment(SemanticRequest):
    warm_memory_bytes: Annotated[Count, Field(gt=0)]
    cpu_millis: Annotated[Count, Field(gt=0)]
    workspace: ResourceCeiling
    control: ResourceCeiling
    scratch: ResourceCeiling


class CreateAssignment(SemanticRequest):
    action: Literal["create_assignment"] = "create_assignment"
    operator_id: CanonicalId
    workspace_id: CanonicalId
    display_name: DisplayName
    email: EmailAddress
    slug: PublicSlug
    support_contact: EmailAddress
    release_id: CanonicalId
    policy_id: CanonicalId
    admission_commitment: AdmissionCommitment
    initial_data: Literal["empty", "synthetic"] = "empty"
    seed_bundle: Reference | None = None

    @model_validator(mode="after")
    def selected_seed(self):
        if (self.initial_data == "synthetic") != (self.seed_bundle is not None):
            raise ValueError("Synthetic data requires its seed bundle; empty data does not.")
        return self


class Provision(SemanticRequest):
    action: Literal["provision"] = "provision"
    assignment_id: CanonicalId
    binding_id: CanonicalId
    release_id: CanonicalId
    admission_commitment: AdmissionCommitment

    initial_data: Literal["empty", "synthetic"] = "empty"
    seed_bundle: Reference | None = None

    @model_validator(mode="after")
    def selected_seed(self):
        if (self.initial_data == "synthetic") != (self.seed_bundle is not None):
            raise ValueError("Synthetic data requires its seed bundle; empty data does not.")
        return self


class RepairRuntime(SemanticRequest):
    action: Literal["repair_runtime"] = "repair_runtime"
    binding_id: CanonicalId
    release_id: CanonicalId
    expected_resource_generation: Revision


class ReissueInvitation(SemanticRequest):
    action: Literal["reissue_invitation"] = "reissue_invitation"
    assignment_id: CanonicalId
    verified_identity_ref: Reference


class Disable(SemanticRequest):
    action: Literal["disable"] = "disable"
    reason: Explanation


class Enable(SemanticRequest):
    action: Literal["enable"] = "enable"
    readiness_proof_ref: Reference


class Rebind(SemanticRequest):
    action: Literal["rebind"] = "rebind"
    verified_identity_ref: Reference
    reason: Explanation


class PrepareRetirement(SemanticRequest):
    action: Literal["prepare_retirement"] = "prepare_retirement"
    binding_ids: IdList
    reason: Explanation


class ConfirmRetirement(SemanticRequest):
    action: Literal["confirm_retirement"] = "confirm_retirement"
    preview_id: CanonicalId
    confirmation_id: CanonicalId
    binding_ids: IdList


class RefreshSource(SemanticRequest):
    action: Literal["refresh_source"] = "refresh_source"
    assignment_id: CanonicalId


class MaintenanceRelease(SemanticRequest):
    action: Literal["maintenance_release"] = "maintenance_release"
    assignment_id: CanonicalId
    release_id: CanonicalId
    expected_assignment_revision: Revision
    maintenance_id: CanonicalId


class AnnounceMaintenance(SemanticRequest):
    action: Literal["announce_maintenance"] = "announce_maintenance"
    starts_at: EpochMillis
    ends_at: EpochMillis
    message: Explanation

    @model_validator(mode="after")
    def ordered_window(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Maintenance must end after it starts.")
        return self


Action = Annotated[
    CreateAssignment
    | Provision
    | RepairRuntime
    | ReissueInvitation
    | Disable
    | Enable
    | Rebind
    | PrepareRetirement
    | ConfirmRetirement
    | RefreshSource
    | MaintenanceRelease
    | AnnounceMaintenance,
    Field(discriminator="action"),
]


class AdminCommand(CommandEnvelope[Action]):
    @model_validator(mode="after")
    def matching_action(self):
        if self.intent.kind != self.intent.payload.action:
            raise ValueError("Envelope kind must match its owning action.")
        return self


class AdminResult(SemanticRequest):
    resource_id: CanonicalId
    revision: Revision
    state: Literal["pending", "ready", "active", "disabled", "retired"]


class AdminObservation(SemanticRequest):
    resource_id: CanonicalId
    revision: Revision
    freshness: Freshness
    display_name: DisplayName
    setup_state: Literal[
        "pending", "preparing", "ready_for_claim", "active", "needs_attention", "retired"
    ]
    desired_enabled: bool
    effective_enabled: bool | None
    usage_bytes: Count | None
    release_id: CanonicalId
    protection_state: Literal["known", "stale", "unknown", "unavailable"]


class AdminPort(Protocol):
    """Private owning API; observations never grant mutation/recovery authority.

    Verify current invocation, expected revision and epoch for each call. Matching
    keys return the original identity/result; changed semantics conflict. Unknown
    effects require receipt inspection, not blind replay. Reads are bounded and
    independent of another owner's database; no raw locators/credentials returned.
    """

    def execute(
        self, actor: AdminAuthority, command: AdminCommand
    ) -> OperationOutcome[AdminResult]: ...
    def observe(
        self, actor: AdminAuthority, query: ObservationQuery
    ) -> ObservationPage[AdminObservation]: ...
    def original(
        self, actor: AdminAuthority, reference: OperationReference
    ) -> OperationOutcome[AdminResult] | None: ...


def require_invocation(actor: AdminAuthority, command: AdminCommand) -> None:
    if not isinstance(actor, AdminAuthority):
        raise ValueError("Wrong owning invocation authority.")
    require_scope(actor, command)
    deployment_actions = {"create_assignment", "announce_maintenance"}
    if command.intent.payload.action in deployment_actions:
        if command.intent.scope.kind != "deployment":
            raise ValueError("This administrative action requires deployment scope.")
    elif command.intent.payload.action != "maintenance_release":
        if command.intent.scope.kind != "workspace":
            raise ValueError("Operator administration requires workspace scope.")
    if command.intent.payload.action == "maintenance_release":
        component = command.intent.component
        if component is None or (
            (component == Component.OPERATOR) != (command.intent.scope.kind == "workspace")
        ):
            raise ValueError("Maintenance release must retain the component assignment scope.")

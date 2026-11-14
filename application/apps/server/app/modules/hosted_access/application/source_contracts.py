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
    EpochMillis,
    Explanation,
    Reference,
    Revision,
    RequestHash,
)


class AdmittedFreePolicy(SemanticRequest):
    policy_id: CanonicalId
    policy_revision: Revision
    usable_bytes: Literal[50_000_000] = 50_000_000
    admission_hash: RequestHash


class InitializeDisabled(SemanticRequest):
    action: Literal["initialize_disabled"] = "initialize_disabled"
    binding_id: CanonicalId
    policy: AdmittedFreePolicy
    assignment_id: CanonicalId


class ApplyPolicy(SemanticRequest):
    action: Literal["apply_policy"] = "apply_policy"
    policy_id: CanonicalId
    policy_revision: Revision
    admission_hash: RequestHash


class Rebind(SemanticRequest):
    action: Literal["rebind"] = "rebind"
    assignment_id: CanonicalId
    assignment_revision: Revision
    verified_identity_hash: RequestHash
    expected_session_generation: Revision


class IssueSession(SemanticRequest):
    action: Literal["issue_session"] = "issue_session"
    assignment_id: CanonicalId
    verified_handoff_id: CanonicalId
    source_attempt_id: CanonicalId
    verified_grant_hash: RequestHash
    expected_session_generation: Revision


class RefreshSession(SemanticRequest):
    action: Literal["refresh_session"] = "refresh_session"
    verified_handoff_id: CanonicalId
    source_attempt_id: CanonicalId
    observed_predecessor_hash: RequestHash
    verified_grant_hash: RequestHash
    expected_session_generation: Revision


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

    @model_validator(mode="after")
    def exact_device_selection(self):
        if self.all_devices != (self.session_reference is None):
            raise ValueError("Select one session or all devices, never an ambiguous target.")
        return self


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
    | ApplyPolicy
    | Rebind
    | IssueSession
    | RefreshSession
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
    version: Literal[1] = 1

    @model_validator(mode="after")
    def matching_action(self):
        if self.intent.kind != self.intent.payload.action:
            raise ValueError("Envelope kind must match its owning action.")
        return self


class SourceRevocation(SemanticRequest):
    session_id: CanonicalId | None = None
    managed_session_id: CanonicalId | None
    not_before: EpochMillis | None

    @model_validator(mode="after")
    def device_or_generation(self):
        if (self.managed_session_id is None) == (self.not_before is None) or (
            self.session_id is not None and self.managed_session_id is None
        ):
            raise ValueError(
                "A source revocation requires one managed session or a generation fence."
            )
        return self


class SourceResult(SemanticRequest):
    version: Literal[1] = 1
    access_epoch: Revision
    effective_enabled: bool
    receipt_ref: Reference
    revocation: SourceRevocation | None = None


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
    action = command.intent.payload.action
    if action == "verify_restore_binding":
        expected = {"operator_recovery"}
    elif action in {"issue_session", "refresh_session"}:
        expected = {"source"}
    elif action in {"initialize_disabled", "apply_policy", "rebind", "claim", "enable", "disable"}:
        expected = {"admin"}
    else:
        expected = {"admin", "source"}
    if actor.service not in expected:
        raise ValueError("Source command has the wrong calling service.")

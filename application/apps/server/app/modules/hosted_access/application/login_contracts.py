"""H01.4 Login owning ports; contracts only, no production implementation.

Adapters authenticate the invocation, verify proof freshness/current fences, commit
original operation/audit/receipt atomically and reconcile unknown effects. Never do
network/host work inside a store transaction or expose these as placeholder routes.
"""

from typing import Annotated, Literal, Protocol

from pydantic import Field, model_validator

from app.platform.hosted_contracts.authority import (
    IdentityAuthority,
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
    Reference,
    RequestHash,
    Revision,
)


class ValidateIdentity(SemanticRequest):
    action: Literal["validate_identity"] = "validate_identity"
    assignment_id: CanonicalId
    managed_proof_ref: Reference


class ConsumeInvitation(SemanticRequest):
    action: Literal["consume_invitation"] = "consume_invitation"
    invitation_id: CanonicalId
    assignment_id: CanonicalId


class IssueHandoff(SemanticRequest):
    action: Literal["issue_handoff"] = "issue_handoff"
    assignment_id: CanonicalId
    registered_origin_id: CanonicalId


class RedeemHandoff(SemanticRequest):
    action: Literal["redeem_handoff"] = "redeem_handoff"
    handoff_id: CanonicalId
    registered_origin_id: CanonicalId


class IssueSession(SemanticRequest):
    action: Literal["issue_session"] = "issue_session"
    assignment_id: CanonicalId
    verified_handoff_id: CanonicalId


class RevokeSession(SemanticRequest):
    action: Literal["revoke_session"] = "revoke_session"
    session_reference: Reference | None
    all_devices: bool


class RecentAuthenticate(SemanticRequest):
    action: Literal["recent_authenticate"] = "recent_authenticate"
    challenge_id: CanonicalId
    exact_request_hash: RequestHash


Action = Annotated[
    ValidateIdentity
    | ConsumeInvitation
    | IssueHandoff
    | RedeemHandoff
    | IssueSession
    | RevokeSession
    | RecentAuthenticate,
    Field(discriminator="action"),
]


class LoginCommand(CommandEnvelope[Action]):
    @model_validator(mode="after")
    def matching_action(self):
        if self.intent.kind != self.intent.payload.action:
            raise ValueError("Envelope kind must match its owning action.")
        return self


class LoginResult(SemanticRequest):
    identity_receipt_ref: Reference
    expires_at: EpochMillis


class LoginObservation(SemanticRequest):
    resource_id: CanonicalId
    revision: Revision
    freshness: Freshness
    identity_receipt_ref: Reference
    active_sessions: Count


class LoginPort(Protocol):
    """Private owning API; observations never grant mutation/recovery authority.

    Verify current invocation, expected revision and epoch for each call. Matching
    keys return the original identity/result; changed semantics conflict. Unknown
    effects require receipt inspection, not blind replay. Reads are bounded and
    independent of another owner's database; no raw locators/credentials returned.
    """

    def execute(
        self, actor: IdentityAuthority, command: LoginCommand
    ) -> OperationOutcome[LoginResult]: ...
    def observe(
        self, actor: IdentityAuthority, query: ObservationQuery
    ) -> ObservationPage[LoginObservation]: ...
    def original(
        self, actor: IdentityAuthority, reference: OperationReference
    ) -> OperationOutcome[LoginResult] | None: ...


def require_invocation(actor: IdentityAuthority, command: LoginCommand) -> None:
    if not isinstance(actor, IdentityAuthority):
        raise ValueError("Wrong owning invocation authority.")
    require_scope(actor, command)
    payload = command.intent.payload
    if hasattr(payload, "assignment_id") and payload.assignment_id != actor.assignment_id:
        raise ValueError("Identity proof belongs to a different invited assignment.")
    if (
        hasattr(payload, "registered_origin_id")
        and payload.registered_origin_id != actor.registered_origin_id
    ):
        raise ValueError("Handoff must retain the registered browser origin.")

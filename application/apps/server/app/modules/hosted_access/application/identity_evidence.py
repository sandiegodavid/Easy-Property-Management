"""Private H03 claims and safe receipts. Shapes alone confer no authority.

Owning adapters must authenticate channels, verify signatures against protected key
registries, load current records/fences and reserve nonces transactionally. No bearer
belongs in these semantic models or their retained receipts.
"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.modules.hosted_access.application.identity_setup import HttpsOrigin, MINUTE
from app.platform.hosted_contracts.semantic import SemanticRequest
from app.platform.hosted_contracts.values import (
    CanonicalId,
    EpochMillis,
    Reference,
    RequestHash,
    Revision,
    WorkspaceScope,
)

Subject = Annotated[str, Field(strict=True, min_length=1, max_length=128)]


class IdentityBinding(SemanticRequest):
    deployment_id: CanonicalId
    scope: WorkspaceScope
    binding_id: CanonicalId
    resource_generation: Revision
    access_epoch: Revision
    assignment_revision: Revision
    registered_origin_id: CanonicalId
    target_origin: HttpsOrigin
    issuer: Reference
    subject: Subject


class ManagedObservation(SemanticRequest):
    version: Literal[1] = 1
    managed_session_id: CanonicalId
    revision: Revision
    issuer: Reference
    subject: Subject
    method: Literal["google", "email_link", "google_totp"]
    purpose: Literal["operator", "admin"]
    operator_id: CanonicalId | None
    email_verified: Literal[True]
    authenticated_at: EpochMillis
    mfa_verified_at: EpochMillis | None
    issued_at: EpochMillis
    provider_valid_until: EpochMillis
    remembered_until: EpochMillis
    checked_at: EpochMillis
    valid_until: EpochMillis
    revoked: bool

    @model_validator(mode="after")
    def bounded_verified_proof(self):
        if (self.purpose == "operator") != (self.operator_id is not None):
            raise ValueError("Managed observation must retain its owning purpose.")
        if self.purpose == "admin" and (
            self.method != "google_totp" or self.mfa_verified_at is None
        ):
            raise ValueError("Admin requires recognized completed Google/TOTP evidence.")
        if self.mfa_verified_at is not None and not (
            self.authenticated_at <= self.mfa_verified_at <= self.issued_at
        ):
            raise ValueError("MFA must describe a completed authentication, not token refresh.")
        if not (
            self.authenticated_at
            <= self.issued_at
            <= self.checked_at
            < self.valid_until
            <= min(self.checked_at + 5 * MINUTE, self.provider_valid_until)
            and self.issued_at < self.provider_valid_until <= self.issued_at + 14 * 24 * 60 * MINUTE
            and self.issued_at < self.remembered_until <= self.issued_at + 30 * 24 * 60 * MINUTE
        ):
            raise ValueError("Managed proof/freshness must retain the accepted absolute deadlines.")
        return self


class PrivateGrant(SemanticRequest):
    """Unsigned claims, not a token. Never accept parsed claims without verification."""

    version: Literal[1] = 1
    key_id: Reference
    issuer_service: Literal["central_identity", "owning_source"]
    audience: Literal["epm:central-identity:v1", "epm:owning-source:v1"]
    purpose: Literal["pair_email", "redeem_handoff", "observe_session", "recent_auth"]
    binding: IdentityBinding
    operation_id: CanonicalId
    request_hash: RequestHash
    nonce_hash: RequestHash
    issued_at: EpochMillis
    expires_at: EpochMillis

    @model_validator(mode="after")
    def fixed_audience(self):
        source_pair = self.purpose == "pair_email"
        expected = (
            ("owning_source", "epm:central-identity:v1")
            if source_pair
            else ("central_identity", "epm:owning-source:v1")
        )
        if (self.issuer_service, self.audience) != expected:
            raise ValueError("Grant signer and audience must match its closed purpose.")
        if not self.issued_at < self.expires_at <= self.issued_at + 5 * MINUTE:
            raise ValueError("Private grants expire within five minutes.")
        return self


class RenewalLineage(SemanticRequest):
    session_id: CanonicalId
    managed_session_id: CanonicalId
    session_generation: Revision
    remembered_until: EpochMillis
    remembered: bool = False


class SourceBindingAssertion(PrivateGrant):
    purpose: Literal["pair_email"] = "pair_email"
    issuer_service: Literal["owning_source"] = "owning_source"
    audience: Literal["epm:central-identity:v1"] = "epm:central-identity:v1"
    continuation_id: CanonicalId
    source_attempt_id: CanonicalId
    source_browser_hash: RequestHash
    renewal: RenewalLineage | None = None


class HandoffEvidence(PrivateGrant):
    purpose: Literal["redeem_handoff"] = "redeem_handoff"
    issuer_service: Literal["central_identity"] = "central_identity"
    audience: Literal["epm:owning-source:v1"] = "epm:owning-source:v1"
    handoff_id: CanonicalId
    attempt_id: CanonicalId
    source_attempt_id: CanonicalId
    source_browser_hash: RequestHash
    managed: ManagedObservation
    renewal: RenewalLineage | None = None

    @model_validator(mode="after")
    def same_identity_and_deadline(self):
        if (
            self.managed.purpose != "operator"
            or self.managed.revoked
            or self.managed.operator_id != self.binding.scope.operator_id
            or (self.managed.issuer, self.managed.subject)
            != (self.binding.issuer, self.binding.subject)
            or self.issued_at < self.managed.checked_at
            or self.expires_at > min(self.managed.valid_until, self.managed.remembered_until)
            or (
                self.renewal is not None
                and (
                    self.renewal.managed_session_id == self.managed.managed_session_id
                    or self.renewal.remembered_until != self.managed.remembered_until
                )
            )
        ):
            raise ValueError(
                "Handoff must retain the current exact managed identity and deadlines."
            )
        return self


class SessionReceipt(SemanticRequest):
    version: Literal[1] = 1
    kind: Literal["issue_session", "refresh_session", "revoke_session"]
    operation_id: CanonicalId
    request_hash: RequestHash
    binding: IdentityBinding
    session_id: CanonicalId
    handoff_id: CanonicalId | None
    source_revision: Revision
    session_generation: Revision
    recorded_at: EpochMillis
    expires_at: EpochMillis
    renewed_from_session_id: CanonicalId | None
    replaced_device_managed_id: CanonicalId | None = None

    @model_validator(mode="after")
    def safe_original(self):
        if self.kind != "revoke_session" and (
            self.handoff_id is None or self.expires_at <= self.recorded_at
        ):
            raise ValueError("Issuance requires the original handoff and future session expiry.")
        if (self.kind == "refresh_session") != (self.renewed_from_session_id is not None):
            raise ValueError("Only a replacement receipt retains its exact predecessor.")
        return self


class SessionObservationGrant(PrivateGrant):
    purpose: Literal["observe_session"] = "observe_session"
    issuer_service: Literal["central_identity"] = "central_identity"
    audience: Literal["epm:owning-source:v1"] = "epm:owning-source:v1"
    managed: ManagedObservation

    @model_validator(mode="after")
    def exact_observation(self):
        if (
            self.managed.purpose != "operator"
            or self.managed.operator_id != self.binding.scope.operator_id
            or (self.managed.issuer, self.managed.subject)
            != (self.binding.issuer, self.binding.subject)
            or self.issued_at < self.managed.checked_at
            or self.expires_at > min(self.managed.valid_until, self.managed.remembered_until)
        ):
            raise ValueError("Signed status must retain its exact identity and freshness deadline.")
        return self


class RecentAuthGrant(PrivateGrant):
    purpose: Literal["recent_auth"] = "recent_auth"
    issuer_service: Literal["central_identity"] = "central_identity"
    audience: Literal["epm:owning-source:v1"] = "epm:owning-source:v1"
    session_id: CanonicalId
    managed: ManagedObservation

    @model_validator(mode="after")
    def recognized_proof(self):
        if (
            self.managed.operator_id != self.binding.scope.operator_id
            or self.managed.purpose != "operator"
            or self.managed.revoked
            or (self.managed.issuer, self.managed.subject)
            != (self.binding.issuer, self.binding.subject)
            or not self.managed.checked_at
            <= self.issued_at
            < self.expires_at
            <= min(self.managed.valid_until, self.managed.remembered_until)
        ):
            raise ValueError("Recent authentication requires current exact Operator proof.")
        return self


def require_current_grant(
    grant: PrivateGrant, current: IdentityBinding, *, now: int, request_hash: str, audience: str
) -> None:
    """Pure binding check after signature verification; not a grant verifier."""
    if (
        grant.binding != current
        or grant.request_hash != request_hash
        or grant.audience != audience
        or not grant.issued_at <= now < grant.expires_at
    ):
        raise ValueError("Private evidence is stale or belongs to another request/source.")


class IdentityCommandResult(SemanticRequest):
    version: Literal[1] = 1
    kind: Literal[
        "claim",
        "pair_email_continuation",
        "issue_handoff",
        "redeem_handoff",
        "renew_session",
        "revoke_session",
        "revoke_all",
        "recent_auth",
    ]
    result_id: CanonicalId
    source_receipt_ref: Reference | None


class IdentityCommandState(SemanticRequest):
    """Exact central identity receipt vocabulary; separate from infrastructure operations."""

    version: Literal[1] = 1
    operation_id: CanonicalId
    kind: Literal[
        "claim",
        "pair_email_continuation",
        "issue_handoff",
        "redeem_handoff",
        "renew_session",
        "revoke_session",
        "revoke_all",
        "recent_auth",
    ]
    idempotency_key: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
    ]
    request_hash: RequestHash
    operator_id: CanonicalId | None
    managed_session_id: CanonicalId
    attempt_id: CanonicalId | None
    access_epoch: Revision | None
    state: Literal["pending", "unknown", "succeeded", "rejected"]
    result: IdentityCommandResult | None
    source_receipt_ref: Reference | None
    created_at: EpochMillis
    updated_at: EpochMillis
    revision: Revision

    @model_validator(mode="after")
    def original_result_only(self):
        if (self.operator_id is None) != (self.access_epoch is None):
            raise ValueError("Operator identity commands require their exact access fence.")
        if (self.state == "succeeded") != (self.result is not None):
            raise ValueError("Only succeeded identity commands retain a typed original result.")
        if self.result is not None and (
            self.result.kind != self.kind
            or self.result.source_receipt_ref != self.source_receipt_ref
        ):
            raise ValueError("Original identity result must retain action and source receipt.")
        if self.updated_at < self.created_at:
            raise ValueError("Identity result observation cannot predate original intent.")
        if self.kind in {
            "claim",
            "pair_email_continuation",
            "issue_handoff",
            "redeem_handoff",
            "renew_session",
        } and (self.attempt_id is None or self.operator_id is None):
            raise ValueError("Browser-bound Operator effects require attempt and Operator scope.")
        return self

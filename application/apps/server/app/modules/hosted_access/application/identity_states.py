"""H03.1 private persistence shapes and pure snapshot consistency checks.

These versioned, hashable DTOs do not verify provider/signature evidence, resolve
registered origins, authorize requests, enforce uniqueness/CAS, or write stores.
Epochs and observations must come from owning ports. Services must recheck them
under the mutation gate, inspect original receipts first, and never replay bearers.
Nullable schema columns are required inputs, even when their value is None.
"""

from typing import Annotated, Literal
from urllib.parse import unquote

from pydantic import AfterValidator, Field, StrictStr, model_validator

from app.modules.hosted_access.application.identity_setup import DAY, HOUR, MINUTE
from app.modules.hosted_access.application.identity_setup import HttpsOrigin as Origin
from app.platform.hosted_contracts.semantic import SemanticRequest
from app.platform.hosted_contracts.values import (
    CanonicalId,
    Count,
    EpochMillis,
    Reference,
    RequestHash,
    Revision,
)

LIVE_SESSION_CAP = 32
FIRST_PRINTABLE_ASCII = 32
DELETE_ASCII = 127


def _return_path(value: str) -> str:
    decoded = unquote(value)
    if (
        not value.startswith("/")
        or "//" in decoded
        or any(char in decoded for char in "\\?#%")
        or any(
            char.isspace() or ord(char) < FIRST_PRINTABLE_ASCII or ord(char) == DELETE_ASCII
            for char in decoded
        )
        or any(part in {".", ".."} for part in decoded.split("/"))
        or decoded.lower().split("/")[1] in {"api", "auth"}
    ):
        raise ValueError(
            "Return path must be a relative UI route without query/fragment or auth/API routing."
        )
    return value


ReturnPath = Annotated[
    StrictStr, Field(min_length=1, max_length=1000), AfterValidator(_return_path)
]
Subject = Annotated[StrictStr, Field(min_length=1, max_length=1024)]
EmailKey = Annotated[StrictStr, Field(min_length=1, max_length=254)]
DeviceLabel = Annotated[
    StrictStr, Field(min_length=1, max_length=120, pattern=r"^[^\x00-\x1f\x7f<>]+$")
]
Method = Literal["google", "email_link", "google_totp"]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _window(created: int, expires: int, maximum: int) -> None:
    _require(created < expires <= created + maximum, "Invalid bounded lifetime.")


def _together(*values: object) -> None:
    _require(
        all(value is None for value in values) or all(value is not None for value in values),
        "Related fields must be supplied together.",
    )


class IdentityState(SemanticRequest):
    contract_version: Literal["h03.identity.v1"] = "h03.identity.v1"


class LoginAttemptState(IdentityState):
    attempt_id: CanonicalId
    purpose: Literal["operator_login", "admin_login", "renewal", "recent_auth"]
    operator_id: CanonicalId | None
    parent_managed_session_id: CanonicalId | None
    completed_managed_session_id: CanonicalId | None = None
    source_attempt_id: CanonicalId | None
    source_browser_hash: RequestHash | None
    central_browser_hash: RequestHash
    method: Method
    email_key: EmailKey | None
    target_origin: Origin
    return_path: ReturnPath
    confirmed_request_hash: RequestHash | None
    delivery_attempts: Count = 0
    last_delivery_at: EpochMillis | None
    last_delivery_code: Literal["sent", "unknown", "rejected"] | None
    state: Literal["pending", "verified", "completed", "failed", "superseded", "expired"]
    created_at: EpochMillis
    expires_at: EpochMillis
    revision: Revision

    @model_validator(mode="after")
    def invariants(self):
        _window(self.created_at, self.expires_at, 15 * MINUTE)
        if self.completed_managed_session_id is not None:
            _require(
                self.state == "completed" and self.method == "google",
                "Only completed Google attempts bind their verified result.",
            )
        _together(self.source_attempt_id, self.source_browser_hash)
        if self.purpose in {"operator_login", "renewal"}:
            _require(
                self.operator_id is not None and self.source_attempt_id is not None,
                "Operator flows require operator and destination browser binding.",
            )
        if self.purpose == "admin_login" or self.operator_id is None:
            _require(
                self.operator_id is None
                and self.source_attempt_id is None
                and self.method == "google_totp",
                "Admin flows require Google TOTP and no Operator target.",
            )
        else:
            _require(
                self.source_attempt_id is not None and self.method != "google_totp",
                "Operator flows require destination binding and an Operator method.",
            )
        if self.purpose in {"renewal", "recent_auth"}:
            _require(self.parent_managed_session_id is not None, "Existing lineage is required.")
        if self.purpose == "recent_auth":
            _require(
                self.confirmed_request_hash is not None,
                "Recent auth requires exact request intent.",
            )
        else:
            _require(
                self.confirmed_request_hash is None, "Request confirmation is recent-auth only."
            )
        if self.method == "email_link":
            _require(self.email_key is not None, "Email-link flow requires its exact recipient.")
        if self.delivery_attempts:
            _require(
                self.method == "email_link" and self.last_delivery_at is not None,
                "Delivery reservation requires email-link method and time.",
            )
            _require(
                self.created_at <= self.last_delivery_at < self.expires_at,
                "Delivery time must be inside the attempt.",
            )
        else:
            _require(
                self.last_delivery_at is None and self.last_delivery_code is None,
                "No delivery metadata without a reserved attempt.",
            )
        return self


class EmailContinuationState(IdentityState):
    continuation_id: CanonicalId
    original_attempt_id: CanonicalId
    code_hash: RequestHash
    central_browser_hash: RequestHash
    operator_id: CanonicalId
    target_origin: Origin
    access_epoch: Revision
    managed_session_id: CanonicalId | None
    replacement_attempt_id: CanonicalId | None
    source_attempt_id: CanonicalId | None
    source_binding_hash: RequestHash | None
    handoff_id: CanonicalId | None
    state: Literal["verifying", "unknown", "verified", "paired", "completed", "rejected", "expired"]
    created_at: EpochMillis
    expires_at: EpochMillis
    revision: Revision

    @model_validator(mode="after")
    def invariants(self):
        _window(self.created_at, self.expires_at, 5 * MINUTE)
        _together(self.replacement_attempt_id, self.source_attempt_id, self.source_binding_hash)
        if self.state in {"verified", "paired", "completed"}:
            _require(
                self.managed_session_id is not None, "Verified continuation requires managed proof."
            )
        if self.state in {"paired", "completed"}:
            _require(
                self.replacement_attempt_id is not None,
                "Paired continuation requires all pairing fields.",
            )
        if self.replacement_attempt_id is not None:
            _require(
                self.replacement_attempt_id != self.original_attempt_id
                and self.managed_session_id is not None,
                "Pairing requires a fresh attempt and verified identity.",
            )
        if self.state in {"verifying", "verified"}:
            _require(
                self.replacement_attempt_id is None and self.handoff_id is None,
                "Unpaired continuation cannot retain pairing or handoff.",
            )
        if self.state == "completed":
            _require(self.handoff_id is not None, "Completed continuation requires a handoff.")
        if self.handoff_id is not None:
            _require(self.replacement_attempt_id is not None, "Handoff requires a pairing.")
        return self


class ManagedIdentitySessionState(IdentityState):
    managed_session_id: CanonicalId
    cookie_hash: RequestHash
    purpose: Literal["operator", "admin"]
    operator_id: CanonicalId | None
    issuer: Reference
    subject: Subject
    email_key: EmailKey
    method: Method
    authenticated_at: EpochMillis
    mfa_verified_at: EpochMillis | None
    provider_valid_until: EpochMillis
    remembered_until: EpochMillis
    revocation_checked_at: EpochMillis
    revocation_valid_until: EpochMillis
    issued_at: EpochMillis
    revoked_at: EpochMillis | None
    revision: Revision

    @model_validator(mode="after")
    def invariants(self):
        _require(
            (self.purpose == "operator") == (self.operator_id is not None),
            "Only Operator-purpose proof has an operator.",
        )
        _require(self.authenticated_at <= self.issued_at, "Authentication cannot follow issuance.")
        _window(self.issued_at, self.provider_valid_until, 14 * DAY)
        _window(self.issued_at, self.remembered_until, 30 * DAY)
        _require(
            self.issued_at <= self.revocation_checked_at < self.provider_valid_until,
            "Status observation must be within managed proof.",
        )
        _window(self.revocation_checked_at, self.revocation_valid_until, 5 * MINUTE)
        _require(
            self.revocation_valid_until <= self.provider_valid_until,
            "Status freshness cannot extend managed proof.",
        )
        if self.purpose == "admin":
            _require(
                self.method == "google_totp" and self.mfa_verified_at is not None,
                "Admin proof requires completed Google TOTP evidence.",
            )
        else:
            _require(
                self.method != "google_totp" and self.mfa_verified_at is None,
                "Operator proof cannot become Admin proof.",
            )
        if self.mfa_verified_at is not None:
            _require(
                self.authenticated_at <= self.mfa_verified_at <= self.issued_at,
                "MFA must follow primary authentication and precede issuance.",
            )
        if self.revoked_at is not None:
            _require(self.revoked_at >= self.issued_at, "Revocation cannot precede issuance.")
        return self


class LoginHandoffState(IdentityState):
    handoff_id: CanonicalId
    operator_id: CanonicalId
    browser_state_hash: RequestHash
    nonce_hash: RequestHash
    code_hash: RequestHash | None
    target_origin: Origin
    issuer: Reference | None
    subject: Subject | None
    assignment_revision: Revision
    access_epoch: Revision
    state: Literal["initiated", "issued", "redeeming", "redeemed", "expired"]
    expires_at: EpochMillis
    redeemed_at: EpochMillis | None
    created_at: EpochMillis
    attempt_id: CanonicalId
    managed_session_id: CanonicalId
    identity_operation_id: CanonicalId
    source_receipt_ref: Reference | None

    @model_validator(mode="after")
    def invariants(self):
        _window(self.created_at, self.expires_at, 5 * MINUTE)
        _together(self.issuer, self.subject, self.code_hash)
        if self.state in {"issued", "redeeming", "redeemed"}:
            _require(
                self.code_hash is not None,
                "Issued handoff requires verified identity and code hash.",
            )
        if self.state == "initiated":
            _require(self.code_hash is None, "Initiated handoff has not issued a code.")
        _together(self.redeemed_at, self.source_receipt_ref)
        _require(
            (self.state == "redeemed") == (self.redeemed_at is not None),
            "Only redeemed handoffs retain redemption time and matching receipt.",
        )
        if self.redeemed_at is not None:
            _require(
                self.created_at <= self.redeemed_at < self.expires_at,
                "Redemption must precede capability expiry.",
            )
        return self


class SourceLoginAttemptState(IdentityState):
    attempt_id: CanonicalId
    browser_challenge_hash: RequestHash
    access_epoch: Revision
    resource_generation: Revision
    return_path: ReturnPath
    remembered: bool
    renewal_session_id: CanonicalId | None = None
    state: Literal["pending", "redeeming", "completed", "expired"]
    handoff_id: CanonicalId | None
    continuation_id: CanonicalId | None
    binding_assertion_hash: RequestHash | None
    binding_expires_at: EpochMillis | None
    created_at: EpochMillis
    expires_at: EpochMillis
    revision: Revision

    @model_validator(mode="after")
    def invariants(self):
        _window(self.created_at, self.expires_at, 15 * MINUTE)
        _together(self.binding_assertion_hash, self.binding_expires_at)
        if self.binding_assertion_hash is not None:
            _require(self.continuation_id is not None, "Source binding requires a continuation.")
            _require(
                self.created_at < self.binding_expires_at <= self.expires_at,
                "Source binding must expire inside its source attempt.",
            )
        if self.state in {"redeeming", "completed"}:
            _require(self.handoff_id is not None, "Source redemption requires its handoff.")
            if self.continuation_id is not None:
                _require(
                    self.binding_assertion_hash is not None,
                    "Continuation redemption requires signed binding.",
                )
        return self


class AccessSessionState(IdentityState):
    session_hash: RequestHash
    csrf_hash: RequestHash
    actor_subject: Subject
    handoff_id: CanonicalId
    generation: Revision
    access_epoch: Revision
    issued_at: EpochMillis
    expires_at: EpochMillis
    managed_valid_until: EpochMillis
    last_seen_at: EpochMillis
    revoked_at: EpochMillis | None
    session_id: CanonicalId
    managed_session_id: CanonicalId
    managed_observation_revision: Revision
    revocation_valid_until: EpochMillis
    remembered_until: EpochMillis
    display_label: DeviceLabel
    renewed_from_session_id: CanonicalId | None
    remembered: bool = False

    @model_validator(mode="after")
    def invariants(self):
        _window(self.issued_at, self.remembered_until, 30 * DAY)
        _require(
            self.issued_at
            < self.expires_at
            <= min(self.remembered_until, self.managed_valid_until),
            "Session expiry exceeds proof or absolute lineage deadline.",
        )
        _require(
            self.issued_at < self.revocation_valid_until <= self.managed_valid_until,
            "Session requires bounded status freshness at issuance.",
        )
        _require(self.last_seen_at >= self.issued_at, "Last seen cannot precede issuance.")
        if self.revoked_at is not None:
            _require(self.revoked_at >= self.issued_at, "Revocation cannot precede issuance.")
        _require(self.renewed_from_session_id != self.session_id, "Session cannot replace itself.")
        return self


class RenewalAdmission(IdentityState):
    """Consistency of supplied verified snapshots, never an authorization grant.

    Caller has already inspected original receipt and selected prior via its cookie.
    Live count includes current, unrevoked, unexpired rows even with stale status.
    Owner serializes this check with replacement/revocation and receipt/audit commit.
    """

    prior: AccessSessionState
    fresh_managed: ManagedIdentitySessionState
    handoff: LoginHandoffState
    source_attempt: SourceLoginAttemptState
    login_attempt: LoginAttemptState
    now: EpochMillis
    current_operator_id: CanonicalId
    current_subject: Subject
    current_target_origin: Origin
    current_assignment_revision: Revision
    current_issuer: Reference
    current_access_epoch: Revision
    current_session_generation: Revision
    current_resource_generation: Revision
    observed_prior_resource_generation: Revision
    current_binding_id: CanonicalId
    observed_prior_binding_id: CanonicalId
    effective_access: Literal["enabled", "disabled"]
    maintenance_operation_id: CanonicalId | None
    not_before: EpochMillis
    live_session_count: Count

    @model_validator(mode="after")
    def invariants(self):
        prior, managed, handoff, source = (
            self.prior,
            self.fresh_managed,
            self.handoff,
            self.source_attempt,
        )
        _require(
            self.effective_access == "enabled" and self.maintenance_operation_id is None,
            "Disabled or maintenance-gated source cannot renew.",
        )
        _require(
            prior.revoked_at is None
            and prior.generation == self.current_session_generation
            and prior.access_epoch == self.current_access_epoch
            and self.observed_prior_resource_generation == self.current_resource_generation
            and self.observed_prior_binding_id == self.current_binding_id,
            "Prior lineage is revoked or has stale source fences.",
        )
        _require(
            prior.actor_subject == self.current_subject == managed.subject == handoff.subject
            and managed.issuer == self.current_issuer == handoff.issuer
            and managed.purpose == "operator"
            and managed.operator_id == self.current_operator_id == handoff.operator_id,
            "Renewal must retain exact Operator identity and scope.",
        )
        _require(
            self.now < prior.remembered_until == managed.remembered_until,
            "Renewal cannot slide or revive the absolute lineage deadline.",
        )
        _require(
            managed.revoked_at is None
            and self.not_before <= managed.authenticated_at <= self.now
            and managed.issued_at
            <= self.now
            < min(managed.provider_valid_until, managed.revocation_valid_until)
            and managed.revocation_checked_at <= self.now,
            "Fresh managed proof/status must be current and not predate the source fence.",
        )
        _require(
            managed.managed_session_id != prior.managed_session_id,
            "Renewal requires fresh managed proof, not the prior session.",
        )
        _require(
            handoff.state == "redeeming"
            and handoff.managed_session_id == managed.managed_session_id
            and handoff.created_at <= self.now < handoff.expires_at
            and handoff.access_epoch == self.current_access_epoch
            and handoff.target_origin == self.current_target_origin
            and handoff.assignment_revision == self.current_assignment_revision,
            "Renewal requires a reserved current handoff.",
        )
        _require(
            source.state == "redeeming"
            and source.handoff_id == handoff.handoff_id
            and source.attempt_id == self.login_attempt.source_attempt_id
            and source.browser_challenge_hash == handoff.browser_state_hash
            and source.access_epoch == self.current_access_epoch
            and source.resource_generation == self.current_resource_generation
            and source.remembered
            and source.created_at <= self.now < source.expires_at,
            "Renewal requires a matching live destination challenge and current fences.",
        )
        login = self.login_attempt
        _require(
            login.purpose == "renewal"
            and login.state == "verified"
            and login.attempt_id == handoff.attempt_id
            and login.parent_managed_session_id == prior.managed_session_id
            and login.operator_id == self.current_operator_id
            and login.method == managed.method
            and login.source_browser_hash == source.browser_challenge_hash
            and login.target_origin == self.current_target_origin
            and login.created_at
            <= managed.authenticated_at
            <= managed.issued_at
            <= handoff.created_at
            and login.created_at <= self.now < login.expires_at,
            "Renewal must bind its verified central attempt to the prior lineage and source.",
        )
        _require(0 <= self.live_session_count <= LIVE_SESSION_CAP, "Invalid live session count.")
        if prior.expires_at > self.now:
            _require(self.live_session_count >= 1, "Live predecessor must occupy a slot.")
        else:
            _require(self.live_session_count < LIVE_SESSION_CAP, "session_limit_reached")
        return self

    def replacement_expires_at(self) -> int:
        """Maximum replacement expiry; does not create or extend a session."""
        return min(self.fresh_managed.provider_valid_until, self.prior.remembered_until)


def check_continuation_context(
    continuation: EmailContinuationState,
    original: LoginAttemptState,
    managed: ManagedIdentitySessionState | None,
) -> None:
    """Check related snapshots; provider recognition and CAS remain owner duties."""
    _require(
        original.attempt_id == continuation.original_attempt_id
        and original.method == "email_link"
        and original.operator_id == continuation.operator_id
        and original.target_origin == continuation.target_origin
        and original.created_at <= continuation.created_at
        and continuation.expires_at <= original.expires_at,
        "Continuation must retain the original email attempt target and deadline.",
    )
    if continuation.managed_session_id is not None:
        _require(managed is not None, "Managed snapshot required after verification.")
        _require(
            managed.managed_session_id == continuation.managed_session_id
            and managed.purpose == "operator"
            and managed.method == "email_link"
            and managed.operator_id == continuation.operator_id
            and managed.email_key == original.email_key
            and continuation.expires_at <= managed.provider_valid_until,
            "Continuation must retain recognized email proof and its deadline.",
        )


def check_source_binding_emission(attempt: SourceLoginAttemptState, emitted_at: int) -> None:
    """Emission time is not persisted in the schema, so its bound is contextual."""
    _require(
        attempt.binding_expires_at is not None
        and attempt.created_at <= emitted_at < attempt.binding_expires_at
        and attempt.binding_expires_at <= emitted_at + 5 * MINUTE,
        "Signed source binding exceeds the five-minute emission bound.",
    )


class AdminSessionState(IdentityState):
    session_hash: RequestHash
    principal_id: CanonicalId
    csrf_hash: RequestHash
    generation: Revision
    authenticated_at: EpochMillis
    mfa_verified_at: EpochMillis
    expires_at: EpochMillis
    last_seen_at: EpochMillis
    revoked_at: EpochMillis | None
    managed_session_id: CanonicalId
    managed_valid_until: EpochMillis
    revocation_valid_until: EpochMillis

    @model_validator(mode="after")
    def invariants(self):
        _window(self.authenticated_at, self.expires_at, 8 * HOUR)
        _require(
            self.authenticated_at <= self.mfa_verified_at < self.expires_at,
            "Admin session requires completed MFA inside its authentication window.",
        )
        _require(
            self.expires_at <= self.managed_valid_until
            and self.mfa_verified_at < self.revocation_valid_until <= self.managed_valid_until,
            "Admin session exceeds managed proof/status deadlines.",
        )
        _require(self.last_seen_at >= self.mfa_verified_at, "Admin activity cannot predate MFA.")
        if self.revoked_at is not None:
            _require(self.revoked_at >= self.mfa_verified_at, "Revocation cannot predate MFA.")
        return self


def check_managed_login_policy(managed: ManagedIdentitySessionState, remembered: bool) -> None:
    """Remembered choice lives in the attempt; it cannot override provider expiry."""
    if not remembered:
        _require(
            managed.provider_valid_until <= managed.issued_at + 8 * HOUR
            and managed.remembered_until <= managed.issued_at + 8 * HOUR,
            "Unremembered sign-in is bounded to eight hours.",
        )


def check_continuation_pairing(
    continuation: EmailContinuationState,
    replacement: LoginAttemptState,
    source: SourceLoginAttemptState,
    original: LoginAttemptState,
) -> None:
    """Compare retained pairing snapshots, not a caller-submitted assertion hash.

    The owner must first authenticate the source assertion, its nonce and origin,
    and the completing central cookie. This comparison confers no such proof.
    """
    _require(
        continuation.replacement_attempt_id == replacement.attempt_id
        and continuation.source_attempt_id == source.attempt_id == replacement.source_attempt_id
        and continuation.source_binding_hash == source.binding_assertion_hash
        and source.continuation_id == continuation.continuation_id
        and continuation.central_browser_hash == replacement.central_browser_hash
        and replacement.source_browser_hash == source.browser_challenge_hash
        and replacement.operator_id == continuation.operator_id
        and replacement.target_origin == continuation.target_origin
        and replacement.method == "email_link"
        and source.access_epoch == continuation.access_epoch,
        "Continuation pairing cannot substitute browser, source binding, scope or method.",
    )
    _require(
        source.binding_assertion_hash is not None
        and original.attempt_id == continuation.original_attempt_id
        and source.attempt_id != original.source_attempt_id
        and source.browser_challenge_hash != original.source_browser_hash,
        "Pairing requires a fresh signed destination binding.",
    )

"""Closed request and result shapes for browser-authentication owner calls."""

from typing import Annotated, Literal

from pydantic import Field, SecretStr

from app.modules.hosted_access.application.identity_evidence import (
    HandoffEvidence,
    IdentityBinding,
    RenewalLineage,
    SessionReceipt,
)
from app.modules.hosted_access.application.identity_states import (
    ReturnPath,
    SourceLoginAttemptState,
)
from app.modules.hosted_access.application.source_contracts import SourceCommand
from pydantic import model_validator
from app.platform.hosted_contracts.values import (
    CanonicalId,
    Contract,
    Count,
    EpochMillis,
    RequestHash,
    Revision,
)


class InspectSource(Contract):
    method: Literal["inspect_source"] = "inspect_source"
    binding: IdentityBinding


class SourceInspection(Contract):
    binding: IdentityBinding
    effective_enabled: bool
    usage_bytes: Count
    usable_bytes: Count
    source_revision: Revision
    observed_at: EpochMillis


class ObserveDestination(Contract):
    method: Literal["observe_destination"] = "observe_destination"
    binding: IdentityBinding
    attempt_id: CanonicalId


class DestinationObservation(Contract):
    binding: IdentityBinding
    attempt: SourceLoginAttemptState
    renewal: RenewalLineage | None = None


class LookupIssuance(Contract):
    method: Literal["lookup_issuance"] = "lookup_issuance"
    receipt: SessionReceipt

    @property
    def binding(self):
        return self.receipt.binding


class ReadContinuation(Contract):
    method: Literal["read_continuation"] = "read_continuation"
    binding: IdentityBinding
    continuation_id: CanonicalId


class ContinuationTarget(Contract):
    binding: IdentityBinding
    return_path: ReturnPath
    remembered: bool
    expires_at: EpochMillis
    renewal: RenewalLineage | None = None


class ReserveHandoff(Contract):
    method: Literal["reserve_handoff"] = "reserve_handoff"
    grant: HandoffEvidence
    token: Annotated[SecretStr, Field(min_length=1, max_length=12000)]

    @property
    def binding(self):
        return self.grant.binding


class AcknowledgeIssuance(Contract):
    method: Literal["acknowledge_issuance"] = "acknowledge_issuance"
    receipt: SessionReceipt

    @property
    def binding(self):
        return self.receipt.binding


class HandoffAccepted(Contract):
    accepted: Literal[True] = True


class ObserveRecent(Contract):
    method: Literal["observe_recent"] = "observe_recent"
    binding: IdentityBinding
    challenge_id: CanonicalId


class RecentChallengeObservation(Contract):
    binding: IdentityBinding
    challenge_id: CanonicalId
    session_id: CanonicalId
    managed_session_id: CanonicalId
    request_hash: RequestHash
    created_at: EpochMillis
    expires_at: EpochMillis


class RefreshStatus(Contract):
    method: Literal["refresh_status"] = "refresh_status"
    binding: IdentityBinding
    session_id: CanonicalId
    managed_session_id: CanonicalId


class SignedStatus(Contract):
    signed: Annotated[SecretStr, Field(min_length=1, max_length=12000)]


class ReconcileRevocation(Contract):
    method: Literal["reconcile_revocation"] = "reconcile_revocation"
    binding: IdentityBinding
    command: SourceCommand

    @model_validator(mode="after")
    def exact_source(self):
        intent = self.command.intent
        if (
            intent.kind != "revoke"
            or intent.deployment_id != self.binding.deployment_id
            or intent.scope != self.binding.scope
            or intent.access_epoch != self.binding.access_epoch
        ):
            raise ValueError("Revocation requires the original exact source command.")
        return self


HandoffRequest = Annotated[
    ObserveDestination
    | LookupIssuance
    | ReadContinuation
    | ReserveHandoff
    | AcknowledgeIssuance
    | ObserveRecent
    | RefreshStatus
    | ReconcileRevocation
    | InspectSource,
    Field(discriminator="method"),
]


def check_reply(call, result):
    if isinstance(call, InspectSource):
        return isinstance(result, SourceInspection) and result.binding == call.binding
    if isinstance(call, ObserveDestination):
        return (
            isinstance(result, DestinationObservation)
            and result.binding == call.binding
            and result.attempt.attempt_id == call.attempt_id
            and result.attempt.access_epoch == call.binding.access_epoch
            and result.attempt.resource_generation == call.binding.resource_generation
            and result.attempt.renewal_session_id
            == (result.renewal.session_id if result.renewal is not None else None)
        )
    if isinstance(call, LookupIssuance):
        return result is None or result == call.receipt
    if isinstance(call, ReadContinuation):
        return isinstance(result, ContinuationTarget) and result.binding == call.binding
    if isinstance(call, ObserveRecent):
        return (
            isinstance(result, RecentChallengeObservation)
            and result.binding == call.binding
            and result.challenge_id == call.challenge_id
        )
    if isinstance(call, RefreshStatus):
        return isinstance(result, SignedStatus)
    return isinstance(result, HandoffAccepted)

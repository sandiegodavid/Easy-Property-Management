"""Trusted application invocation evidence, never browser-supplied authorization."""

from typing import Generic, Literal, TypeVar, Annotated

from pydantic import Field, model_validator

from app.platform.hosted_contracts.operations import CommandEnvelope
from app.platform.hosted_contracts.reads import ContinuationCursor, Freshness, FreshnessState
from app.platform.hosted_contracts.values import (
    CanonicalId,
    Contract,
    Count,
    EpochMillis,
    Reference,
    RequestHash,
    Scope,
)


class AdminAuthority(Contract):
    deployment_id: CanonicalId
    principal_id: CanonicalId
    identity_proof_ref: Reference
    mfa_verified_at: EpochMillis


class OperatorAuthority(Contract):
    deployment_id: CanonicalId
    scope: Scope
    identity_proof_ref: Reference

    @model_validator(mode="after")
    def own_workspace(self):
        if self.scope.kind != "workspace":
            raise ValueError("Operator authority must identify its own workspace.")
        return self


class OperatorRestoreAuthority(OperatorAuthority):
    step_up_ref: Reference
    step_up_at: EpochMillis
    confirmed_request_hash: RequestHash


class LocalRestoreAuthority(Contract):
    deployment_id: CanonicalId
    scope: Scope
    os_owner_proof_ref: Reference
    confirmed_request_hash: RequestHash

    @model_validator(mode="after")
    def own_workspace(self):
        if self.scope.kind != "workspace":
            raise ValueError("Local owner authority must identify its own workspace.")
        return self


class AdminRecoveryAuthority(Contract):
    deployment_id: CanonicalId
    bootstrap_principal_ref: Reference
    current_mfa_proof_ref: Reference
    step_up_at: EpochMillis
    confirmed_request_hash: RequestHash


class ServiceAuthority(Contract):
    deployment_id: CanonicalId
    scope: Scope
    service: Literal[
        "admin", "source", "operator_backup", "operator_recovery", "admin_backup", "admin_recovery"
    ]
    authenticated_channel_ref: Reference


def require_scope(actor, command: CommandEnvelope) -> None:
    """Shape/binding check only; adapters must verify referenced live authority/fences."""
    if actor.deployment_id != command.intent.deployment_id:
        raise ValueError("Invocation deployment mismatch.")
    if hasattr(actor, "scope") and actor.scope != command.intent.scope:
        raise ValueError("Invocation workspace mismatch.")


class ObservationQuery(Contract):
    deployment_id: CanonicalId
    scope: Scope
    limit: Annotated[int, Field(strict=True, ge=1, le=50)] = 50
    cursor: ContinuationCursor | None = None

    @model_validator(mode="after")
    def matching_cursor(self):
        if self.cursor is not None and (
            self.cursor.context.deployment_id != self.deployment_id
            or self.cursor.context.scope != self.scope
            or self.cursor.limit != self.limit
        ):
            raise ValueError("Observation cursor does not match its scope/limit.")
        return self


RecordT = TypeVar("RecordT", bound=Contract)


class ObservationPage(Contract, Generic[RecordT]):
    items: Annotated[tuple[RecordT, ...], Field(max_length=50)]
    matching_total: Count | None
    freshness: Freshness
    continuation: ContinuationCursor | None = None

    @model_validator(mode="after")
    def available_projection(self):
        if self.freshness.state in {FreshnessState.UNKNOWN, FreshnessState.UNAVAILABLE}:
            if self.items or self.matching_total is not None or self.continuation is not None:
                raise ValueError("Unavailable observations cannot fabricate rows/counts/cursors.")
        elif self.matching_total is None or self.matching_total < len(self.items):
            raise ValueError("An available projection requires its bounded matching count.")
        if self.continuation is not None and (
            self.continuation.context.as_of != self.freshness.as_of
            or self.continuation.context.source_revision != self.freshness.source_revision
        ):
            raise ValueError("Continuation must retain the observed capture/source revision.")
        return self


class IdentityAuthority(Contract):
    deployment_id: CanonicalId
    scope: Scope
    verified_identity_ref: Reference
    assignment_id: CanonicalId
    registered_origin_id: CanonicalId
    browser_binding_hash: RequestHash

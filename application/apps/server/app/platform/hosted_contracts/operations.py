"""Original-operation identity, validated outcomes and pure replay comparison."""

from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import model_validator

from app.platform.hosted_contracts.semantic import SemanticRequest, canonical_bytes, semantic_hash
from app.platform.hosted_contracts.values import (
    AccessEpoch,
    CanonicalId,
    Component,
    Contract,
    EpochMillis,
    IdempotencyKey,
    RequestHash,
    Revision,
    SafeCode,
    Scope,
)

RequestT = TypeVar("RequestT", bound=SemanticRequest)
ResultT = TypeVar("ResultT", bound=SemanticRequest)


class CommandIntent(SemanticRequest, Generic[RequestT]):
    deployment_id: CanonicalId
    scope: Scope
    kind: SafeCode
    expected_revision: Revision
    access_epoch: AccessEpoch
    payload: RequestT
    component: Component | None = None


class TransportMetadata(Contract):
    """Declared volatile metadata; never persisted as semantic intent or authority."""

    correlation_id: CanonicalId
    sent_at: EpochMillis


class OperationReference(Contract):
    deployment_id: CanonicalId
    scope: Scope
    kind: SafeCode
    operation_id: CanonicalId
    idempotency_key: IdempotencyKey
    request_hash: RequestHash


class CommandEnvelope(Contract, Generic[RequestT]):
    operation_id: CanonicalId
    idempotency_key: IdempotencyKey
    intent: CommandIntent[RequestT]
    request_hash: RequestHash
    transport: TransportMetadata | None = None

    @model_validator(mode="after")
    def matching_hash(self):
        if self.request_hash != semantic_hash(self.intent):
            raise ValueError("Request hash does not match the validated command intent.")
        return self

    def reference(self) -> OperationReference:
        return OperationReference(
            deployment_id=self.intent.deployment_id,
            scope=self.intent.scope,
            kind=self.intent.kind,
            operation_id=self.operation_id,
            idempotency_key=self.idempotency_key,
            request_hash=self.request_hash,
        )


class OperationState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    NEEDS_ATTENTION = "needs_attention"
    UNKNOWN = "unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OperationOutcome(Contract, Generic[ResultT]):
    operation: OperationReference
    state: OperationState
    revision: Revision
    observed_at: EpochMillis
    result: ResultT | None = None
    error_code: SafeCode | None = None
    action_required: SafeCode | None = None

    @model_validator(mode="after")
    def valid_outcome(self):
        if self.state == OperationState.SUCCEEDED:
            if (
                self.result is None
                or self.error_code is not None
                or self.action_required is not None
            ):
                raise ValueError(
                    "Succeeded requires the original result and no failure/action code."
                )
            canonical_bytes(self.result)
        elif self.result is not None:
            raise ValueError("Only succeeded may contain a committed result.")
        if self.state in {OperationState.FAILED, OperationState.NEEDS_ATTENTION}:
            if self.error_code is None:
                raise ValueError("A classified error is required.")
        if self.state in {OperationState.UNKNOWN, OperationState.NEEDS_ATTENTION}:
            if self.action_required is None:
                raise ValueError("An unresolved outcome requires an explicit next action.")
        if self.state in {OperationState.PENDING, OperationState.RUNNING}:
            if self.error_code is not None or self.action_required is not None:
                raise ValueError("In-progress outcomes cannot claim a failure or required action.")
        return self


class SemanticConflict(ValueError):
    code = "hosted_operation_conflict"

    def __init__(self):
        super().__init__(
            "The operation key belongs to a different request; check the original result."
        )


def original_result(
    command: CommandEnvelope, retained: OperationOutcome | None
) -> OperationOutcome | None:
    """Compare a receipt supplied by its owner, never dispatch or fabricate an effect.

    A retry may present a different proposed operation ID. The original identity wins
    for the same deployment/scope/kind/key/hash; changed semantics fail closed.
    Owners must authenticate the lookup, enforce fences and atomically reserve keys.
    """
    if retained is None:
        return None
    expected = command.reference().model_dump(exclude={"operation_id"})
    actual = retained.operation.model_dump(exclude={"operation_id"})
    if expected != actual:
        raise SemanticConflict()
    return retained


def transport_timeout(
    command: CommandEnvelope, *, revision: Revision, observed_at: EpochMillis
) -> OperationOutcome:
    """A local observation of uncertainty, not a durable state transition or retry grant."""
    return OperationOutcome(
        operation=command.reference(),
        state=OperationState.UNKNOWN,
        revision=revision,
        observed_at=observed_at,
        error_code="transport_timeout",
        action_required="check_original_result",
    )

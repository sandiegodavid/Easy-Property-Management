"""Strict OPS API contracts; readiness is enforced by the application boundary."""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, Field, StrictBool, StrictInt

from app.modules.operator.domain.models import Contract, OperatorError
from app.platform.api_errors import domain_problem


class PreferenceResponse(Contract):
    appearance: Literal["light", "dark"]
    destinationOrder: list[str]
    hiddenDestinationIds: list[str]
    revision: StrictInt
    updatedAt: AwareDatetime | None
    operationId: UUID | None = None


class RecoveryAction(Contract):
    kind: Literal["api_operation", "setup_guidance"]
    action: str
    label: str


class BootstrapResponse(Contract):
    contractVersion: StrictInt
    state: Literal["ready", "busy", "unavailable"]
    workspaceId: UUID | None
    runtimeEpoch: UUID
    canWrite: StrictBool
    reasonCode: str | None
    capabilities: list[str]
    capabilityVersion: StrictInt
    preferencesState: Literal["available", "unavailable"]
    preferences: PreferenceResponse | None
    recoveryActions: list[RecoveryAction]


class MutationInput(Contract):
    expectedRevision: StrictInt = Field(ge=0)
    idempotencyKey: UUID


class PreferenceInput(MutationInput):
    appearance: Literal["light", "dark"]
    destinationOrder: list[str] = Field(max_length=8)
    hiddenDestinationIds: list[str] = Field(default_factory=list, max_length=6)


class RecoveryInput(MutationInput):
    formKey: Literal["task.create", "maintenance.issue.create", "communication.record"]
    schemaVersion: StrictInt = Field(ge=1)
    payload: dict[str, Any]
    sourceKind: Literal["property", "space", "party"] | None = None
    sourceId: UUID | None = None
    baseSourceRevision: str | None = Field(None, max_length=100)


class AttemptInput(MutationInput):
    attemptKey: UUID
    requestFingerprint: str = Field(pattern="^[0-9a-f]{64}$")


class RecoveryMetadata(Contract):
    id: UUID
    formKey: str
    schemaVersion: StrictInt
    revision: StrictInt
    status: Literal["active", "outcome_unknown", "reconciled", "discarded", "expired"]
    savedAt: AwareDatetime
    expiresAt: AwareDatetime
    sourceKind: str | None
    sourceId: UUID | None
    baseSourceRevision: str | None


class RecoveryResponse(RecoveryMetadata):
    payload: dict[str, Any]
    attemptKey: UUID | None
    requestFingerprint: str | None
    receipt: dict[str, Any] | None
    reuseState: str
    asOf: AwareDatetime
    operationId: UUID | None = None


class RecoveryPage(Contract):
    items: list[RecoveryMetadata]
    matchingTotal: StrictInt
    nextCursor: str | None
    asOf: AwareDatetime
    sourceRevision: str


class ExpiryResponse(Contract):
    expiredCount: StrictInt
    asOf: AwareDatetime
    mayHaveMore: StrictBool


def build_router(service):
    router = APIRouter(prefix="/api/operator", tags=["operator"])

    def invoke(operation):
        try:
            return operation()
        except OperatorError as error:
            details = (
                {"currentRevision": error.current_revision}
                if getattr(error, "current_revision", None) is not None
                else {}
            )
            raise domain_problem(error, status_code=error.status_code, **details) from error

    @router.get("/bootstrap", response_model=BootstrapResponse, operation_id="getOperatorBootstrap")
    def bootstrap():
        return invoke(service.bootstrap)

    @router.get(
        "/preferences", response_model=PreferenceResponse, operation_id="getOperatorPreferences"
    )
    def preferences():
        return invoke(service.preferences)

    @router.put(
        "/preferences", response_model=PreferenceResponse, operation_id="updateOperatorPreferences"
    )
    def update_preferences(data: PreferenceInput):
        return invoke(
            lambda: service.update_preferences(
                appearance=data.appearance,
                destination_order=data.destinationOrder,
                hidden_destination_ids=data.hiddenDestinationIds,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.get("/recovery", response_model=RecoveryPage, operation_id="listOperatorRecovery")
    def recovery_records(
        limit: int = Query(50, ge=1, le=100), cursor: str | None = Query(None, max_length=4096)
    ):
        return invoke(lambda: service.recovery_page(limit=limit, cursor=cursor))

    @router.post(
        "/recovery/expire", response_model=ExpiryResponse, operation_id="expireOperatorRecovery"
    )
    def expire(limit: int = Query(100, ge=1, le=100)):
        return invoke(lambda: service.expire_recovery(limit=limit))

    @router.get(
        "/operations/{key}",
        response_model=PreferenceResponse | RecoveryResponse,
        operation_id="getOperatorOperation",
    )
    def operation(key: UUID):
        return invoke(lambda: service.operation(str(key)))

    @router.get(
        "/recovery/{record_id}", response_model=RecoveryResponse, operation_id="getOperatorRecovery"
    )
    def recovery(record_id: UUID):
        return invoke(lambda: service.recovery(str(record_id)))

    @router.put(
        "/recovery/{record_id}",
        response_model=RecoveryResponse,
        operation_id="saveOperatorRecovery",
    )
    def save_recovery(record_id: UUID, data: RecoveryInput):
        return invoke(
            lambda: service.save_recovery(
                str(record_id),
                form_key=data.formKey,
                schema_version=data.schemaVersion,
                payload=data.payload,
                source_kind=data.sourceKind,
                source_id=str(data.sourceId) if data.sourceId else None,
                base_source_revision=data.baseSourceRevision,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/recovery/{record_id}/discard",
        response_model=RecoveryResponse,
        operation_id="discardOperatorRecovery",
    )
    def discard(record_id: UUID, data: MutationInput):
        return invoke(
            lambda: service.discard_recovery(
                str(record_id),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/recovery/{record_id}/attempt",
        response_model=RecoveryResponse,
        operation_id="prepareOperatorRecoveryAttempt",
    )
    def attempt(record_id: UUID, data: AttemptInput):
        return invoke(
            lambda: service.prepare_attempt(
                str(record_id),
                attempt_key=str(data.attemptKey),
                request_fingerprint=data.requestFingerprint,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/recovery/{record_id}/reconcile",
        response_model=RecoveryResponse,
        operation_id="reconcileOperatorRecovery",
    )
    def reconcile(record_id: UUID, data: MutationInput):
        return invoke(
            lambda: service.reconcile_recovery(
                str(record_id),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    return router

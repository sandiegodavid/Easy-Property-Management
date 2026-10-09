"""Strict OPS API contracts; readiness is enforced by the application boundary."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator

from app.modules.operator.domain.models import Contract, OperatorError, source_identifier
from app.platform.api_errors import domain_problem
from app.modules.operator.application.directory_service import OperatorDirectoryService
from app.modules.operator.api.directory_router import register_directory
from app.modules.operator.api.overview_router import register_overviews
from app.modules.operator.application.overview_service import OperatorOverviewService
from app.modules.operator.application.search_service import OperatorSearchService
from app.modules.operator.api.search_router import register_search
from app.modules.operator.api.coverage_router import register_coverage
from app.modules.operator.application.coverage_service import OperatorCoverageService
from app.modules.operator.application.recovery_schemas import registered_schemas
from app.modules.operator.application.command_forms import COMMAND_SCHEMAS, command_source_kind

FormKey = Literal[tuple(registered_schemas())]
SourceId = UUID | Literal["1"] | Annotated[str, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]


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
    formKey: FormKey
    schemaVersion: StrictInt = Field(ge=1)
    payload: dict[str, Any]
    sourceKind: (
        Literal[
            "property",
            "space",
            "party",
            "task",
            "communication",
            "maintenance_issue",
            "lease",
            "expense",
            "expense_category",
            "security_deposit_account",
            "owner_rent_report",
            "intake_source",
            "file_link",
            "inspection_lease",
            "condition_report",
            "condition_observation",
            "condition_template",
            "tenant",
            "provider",
            "provider_category",
            "owner_concern",
            "ai_settings",
            "ai_connection",
            "ai_action_limit",
            "ai_draft",
        ]
        | None
    ) = None
    sourceId: SourceId | None = None
    baseSourceRevision: str | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def valid_source_identity(self):
        if self.sourceId is not None:
            source_identifier(self.sourceKind, str(self.sourceId))
        return self


class AttemptInput(MutationInput):
    attemptKey: UUID
    requestFingerprint: str | None = Field(None, pattern="^[0-9a-f]{64}$")


class RecoveryMetadata(Contract):
    id: UUID
    formKey: str
    schemaVersion: StrictInt
    revision: StrictInt
    status: Literal["active", "outcome_unknown", "reconciled", "discarded", "expired"]
    savedAt: AwareDatetime
    expiresAt: AwareDatetime
    sourceKind: str | None
    sourceId: SourceId | None
    baseSourceRevision: str | None


class RecoveredCommandResult(Contract):
    targetId: SourceId
    revision: StrictInt = Field(ge=0)
    status: str | None = Field(max_length=100)
    operationId: UUID


class IntakeRecoveredCommandResult(RecoveredCommandResult):
    evidenceRevisionId: UUID


class FileRecoveredCommandResult(RecoveredCommandResult):
    fileId: UUID
    linkId: UUID


class RecoveryReceipt(Contract):
    sourceKind: str
    sourceId: SourceId
    receiptId: UUID
    attemptKey: UUID
    result: (
        FileRecoveredCommandResult | IntakeRecoveredCommandResult | RecoveredCommandResult | None
    ) = None

    @model_validator(mode="after")
    def valid_receipt_identity(self):
        source_identifier(self.sourceKind, str(self.sourceId))
        if self.result is not None:
            source_identifier(self.sourceKind, str(self.result.targetId))
        return self


class RecoveryFormDescriptor(Contract):
    formKey: FormKey
    schemaVersion: Literal[1]
    sourceKind: str | None
    fingerprintMode: Literal["source_owned", "caller_provided"]
    payloadSchema: dict[str, Any]


class RecoveryResponse(RecoveryMetadata):
    payload: dict[str, Any]
    attemptKey: UUID | None
    requestFingerprint: str | None
    receipt: RecoveryReceipt | None
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


def build_router(
    service,
    directories: OperatorDirectoryService | None = None,
    overviews: OperatorOverviewService | None = None,
    search: OperatorSearchService | None = None,
    coverage: OperatorCoverageService | None = None,
):
    router = APIRouter(prefix="/api/operator", tags=["operator"])

    @router.get(
        "/recovery-forms",
        response_model=list[RecoveryFormDescriptor],
        operation_id="listOperatorRecoveryForms",
    )
    def recovery_forms():
        return [
            {
                "formKey": key,
                "schemaVersion": 1,
                "sourceKind": command_source_kind(key) if key in COMMAND_SCHEMAS else None,
                "fingerprintMode": "source_owned" if key in COMMAND_SCHEMAS else "caller_provided",
                "payloadSchema": schema.model_json_schema(),
            }
            for key, schema in registered_schemas().items()
        ]

    if directories is not None:
        register_directory(router, directories, invoke)
    if overviews is not None:
        register_overviews(router, overviews, invoke)
    if search is not None:
        register_search(router, search, invoke)
    if coverage is not None:
        register_coverage(router, coverage, invoke)

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

    register_recovery(router, service)
    return router


def register_recovery(router, service):
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

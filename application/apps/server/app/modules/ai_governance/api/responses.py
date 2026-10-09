"""Generated-client contracts for built-in AI configuration and review.

Action payloads and confidence provenance remain registered action-owned JSON
objects; the surrounding governance envelope is a fixed, typed contract.
"""

from typing import Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    model_validator,
)

ExecutionLocation = Literal["on_device", "cloud"]
DraftStatus = Literal["proposed", "edited", "approved", "dismissed", "superseded"]


class ResponseContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConnectionTestResponse(ResponseContract):
    ready: StrictBool
    reason: str | None


class SettingsMutationResponse(ResponseContract):
    killSwitch: StrictBool
    builtInEnabled: StrictBool
    defaultConnectionId: UUID | None
    updatedAt: AwareDatetime
    revision: StrictInt = Field(ge=1)


class RegisteredAdapterResponse(ResponseContract):
    adapterId: str
    adapterVersion: str
    executionLocation: ExecutionLocation
    models: list[str]
    credentialRequired: StrictBool
    capabilities: list[str]
    inputModalities: list[str]


class RegisteredActionResponse(ResponseContract):
    actionType: str
    owningModule: str
    maxRunsPerUtcDay: StrictInt = Field(gt=0)
    maxPromptTokens: StrictInt = Field(gt=0)
    maxCompletionTokens: StrictInt = Field(gt=0)
    requiredCapabilities: list[str]
    requiredInputModalities: list[str]


class SettingsResponse(SettingsMutationResponse):
    readiness: ConnectionTestResponse
    registeredAdapters: list[RegisteredAdapterResponse]
    actions: list[RegisteredActionResponse]


class ModelConnectionResponse(ResponseContract):
    id: UUID
    label: str
    revision: StrictInt = Field(ge=1)
    adapterId: str
    adapterVersion: str
    modelIdentifier: str
    executionLocation: ExecutionLocation
    enabled: StrictBool
    cloudDataClasses: list[str]
    disclosureVersion: str | None
    disclosureAcceptedAt: AwareDatetime | None
    credentialPresent: StrictBool
    modelArtifactDigest: str | None
    quantization: str | None
    runtimeId: str | None
    runtimeVersion: str | None
    createdAt: AwareDatetime
    updatedAt: AwareDatetime


class ActionLimitResponse(ResponseContract):
    actionType: str
    enabled: StrictBool
    connectionId: UUID | None
    maxRunsPerUtcDay: StrictInt = Field(gt=0)
    maxPromptTokens: StrictInt = Field(gt=0)
    maxCompletionTokens: StrictInt = Field(gt=0)
    allowedModels: list[str]
    updatedAt: AwareDatetime | None
    revision: StrictInt = Field(ge=0)


class RedactionProfileResponse(ResponseContract):
    name: str
    version: StrictInt = Field(ge=1)
    actionTypes: list[str]
    fieldHandling: dict[str, str]


class DraftSummaryResponse(ResponseContract):
    id: UUID
    runId: UUID
    entityKind: str
    status: DraftStatus
    version: StrictInt = Field(ge=1)
    sourceEntityType: str
    sourceEntityId: str
    actionType: str
    owningModule: str
    updatedAt: AwareDatetime


class DraftPageResponse(ResponseContract):
    items: list[DraftSummaryResponse]
    nextCursor: str | None


class ReviewDecisionResponse(ResponseContract):
    id: UUID
    decision: Literal["edited", "approved", "dismissed"]
    draftVersionBefore: StrictInt = Field(ge=1)
    draftVersionAfter: StrictInt = Field(ge=1)
    operatorNote: str | None = Field(max_length=1000)
    resultEntityType: str | None
    resultEntityId: str | None
    correlationId: UUID
    decidedAt: AwareDatetime


class CurrentSourceResponse(ResponseContract):
    revision: str | None
    fingerprint: str | None
    tombstoned: StrictBool
    availability: Literal["available", "unavailable"]
    comparisonState: str


class DraftProvenanceResponse(ResponseContract):
    executionKind: Literal["provider_generation", "external_proposal"]
    transportProvider: str | None
    adapterVersion: str | None
    modelIdentifier: str | None
    executionLocation: ExecutionLocation | None
    modelArtifactDigest: str | None
    quantization: str | None
    runtimeId: str | None
    runtimeVersion: str | None
    promptTemplateId: str | None
    promptTemplateVersion: StrictInt | None
    outputSchemaVersion: StrictInt = Field(ge=1)
    redactionProfile: str
    redactionProfileVersion: StrictInt = Field(ge=1)
    promptTokens: StrictInt | None = Field(ge=0)
    completionTokens: StrictInt | None = Field(ge=0)
    correlationId: UUID


class DraftDetailResponse(DraftSummaryResponse):
    draftPayload: dict[str, JsonValue]
    confidence: dict[str, JsonValue] | None
    governedInput: dict[str, JsonValue]
    sourceRevision: str
    sourceFingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    currentSource: CurrentSourceResponse | None
    reviewHistory: list[ReviewDecisionResponse]
    provenance: DraftProvenanceResponse
    supersedesDraftId: UUID | None
    createdAt: AwareDatetime
    terminalAt: AwareDatetime | None


class DraftApprovalResponse(ResponseContract):
    status: Literal["approved"]
    resultEntityId: str | None
    operationId: UUID
    draftId: UUID
    version: StrictInt = Field(ge=1)
    updatedAt: AwareDatetime
    resultEntityType: str | None


class SettingsCommandResponse(SettingsMutationResponse):
    operationId: UUID


class ConnectionCommandResponse(ModelConnectionResponse):
    operationId: UUID


class LimitCommandResponse(ActionLimitResponse):
    operationId: UUID


class DraftCommandResponse(DraftSummaryResponse):
    operationId: UUID


class AiCommandReceiptResponse(ResponseContract):
    id: UUID
    idempotencyKey: UUID
    action: Literal[
        "settings",
        "connection_create",
        "connection_update",
        "disclosure",
        "limit",
        "edited",
        "dismissed",
        "approved",
    ]
    targetId: str
    requestFingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    result: (
        SettingsCommandResponse
        | ConnectionCommandResponse
        | LimitCommandResponse
        | DraftCommandResponse
        | DraftApprovalResponse
    )
    correlationId: UUID
    createdAt: AwareDatetime


class ExternalCredentialResult(ResponseContract):
    status: Literal["completed"]
    beforePresent: StrictBool
    afterPresent: StrictBool
    credentialAction: Literal["credential_set", "credential_replaced", "credential_deleted"]


class ExternalProbeResult(ResponseContract):
    status: Literal["completed"]
    ready: StrictBool
    reason: Literal["connection_disabled", "credential_unavailable", "provider_unavailable"] | None


class ExternalAbandonedResult(ResponseContract):
    status: Literal["abandoned"]


class ExternalEffectResponse(ResponseContract):
    operationId: UUID
    idempotencyKey: UUID
    connectionId: UUID
    action: Literal["credential_set", "credential_delete", "connection_probe"]
    revision: StrictInt = Field(ge=1)
    updatedAt: AwareDatetime
    status: Literal["outcome_unknown", "completed", "abandoned"]
    result: ExternalCredentialResult | ExternalProbeResult | ExternalAbandonedResult | None
    createdAt: AwareDatetime
    completedAt: AwareDatetime | None
    requiresDeviceValidation: Literal[True]

    @model_validator(mode="after")
    def validate_state(self):
        if self.status == "outcome_unknown":
            if self.result is not None or self.completedAt is not None:
                raise ValueError("Unknown external effects cannot have a result.")
        elif self.result is None or self.result.status != self.status or self.completedAt is None:
            raise ValueError("External outcome does not match its result.")
        if self.status == "completed":
            if (self.action == "connection_probe") != isinstance(self.result, ExternalProbeResult):
                raise ValueError("External action does not match its result.")
        return self

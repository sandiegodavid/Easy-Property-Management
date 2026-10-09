"""Typed, deliberately non-generative HTTP surface for AI governance."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from app.platform.api_errors import api_problem, domain_problem, workspace_unavailable
from app.modules.ai_governance.application.external_effects import AiExternalEffectService

from app.modules.ai_governance.application.service import (
    AiConfigurationService,
    AiDraftReviewService,
    AiGenerationCoordinator,
)
from app.modules.ai_governance.domain.models import (
    AiConflictError,
    AiGovernanceError,
    AiNotFoundError,
    AiValidationError,
)
from app.modules.workspace.application.runtime import WorkspaceRuntime
from app.modules.ai_governance.api.responses import (
    ActionLimitResponse,
    DraftApprovalResponse,
    DraftDetailResponse,
    DraftPageResponse,
    DraftStatus,
    DraftSummaryResponse,
    ExecutionLocation,
    ModelConnectionResponse,
    RedactionProfileResponse,
    SettingsResponse,
    SettingsMutationResponse,
    SettingsCommandResponse,
    ConnectionCommandResponse,
    LimitCommandResponse,
    DraftCommandResponse,
    AiCommandReceiptResponse,
    ExternalEffectResponse,
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftConflictState(Contract):
    id: UUID
    status: DraftStatus
    version: StrictInt = Field(ge=1)


class ExternalConnectionConflictState(Contract):
    id: UUID
    revision: StrictInt = Field(ge=1)


class AiConflictDetail(Contract):
    code: str
    message: str
    current: (
        SettingsMutationResponse
        | ModelConnectionResponse
        | ActionLimitResponse
        | DraftSummaryResponse
        | DraftConflictState
        | ExternalConnectionConflictState
        | None
    ) = None
    revision: StrictInt | None = None


class AiConflictResponse(Contract):
    detail: AiConflictDetail


class SettingsInput(Contract):
    expectedRevision: StrictInt = Field(ge=1)
    killSwitch: StrictBool | None = None
    builtInEnabled: StrictBool | None = None
    defaultConnectionId: UUID | None = None
    idempotencyKey: UUID


class ConnectionInput(Contract):
    expectedRevision: StrictInt = Field(ge=0, le=0)
    idempotencyKey: UUID
    label: str = Field(min_length=1, max_length=120)
    adapterId: str = Field(min_length=1, max_length=80)
    adapterVersion: str = Field(min_length=1, max_length=80)
    modelIdentifier: str = Field(min_length=1, max_length=240)
    executionLocation: ExecutionLocation
    enabled: StrictBool = True
    modelArtifactDigest: str | None = Field(None, max_length=256)
    quantization: str | None = Field(None, max_length=128)
    runtimeId: str | None = Field(None, max_length=128)
    runtimeVersion: str | None = Field(None, max_length=128)


class ConnectionPatch(Contract):
    idempotencyKey: UUID
    expectedRevision: StrictInt = Field(ge=1)
    label: str | None = Field(None, min_length=1, max_length=120)
    enabled: StrictBool | None = None
    modelArtifactDigest: str | None = Field(None, max_length=256)
    quantization: str | None = Field(None, max_length=128)
    runtimeId: str | None = Field(None, max_length=128)
    runtimeVersion: str | None = Field(None, max_length=128)


class DisclosureInput(Contract):
    idempotencyKey: UUID
    expectedRevision: StrictInt = Field(ge=1)
    disclosureVersion: str = Field(min_length=1, max_length=80)
    dataClasses: list[str] = Field(max_length=40)


class ExternalEffectInput(Contract):
    expectedRevision: StrictInt = Field(ge=1)
    idempotencyKey: UUID


class CredentialInput(ExternalEffectInput):
    credential: str = Field(min_length=1, max_length=8192)


class ExternalUncertaintyAcknowledgement(Contract):
    acknowledgeUnknownOutcome: StrictBool


class LimitInput(Contract):
    expectedRevision: StrictInt = Field(ge=0)
    idempotencyKey: UUID
    enabled: StrictBool
    connectionId: UUID | None = None
    maxRunsPerUtcDay: StrictInt = Field(gt=0)
    maxPromptTokens: StrictInt = Field(gt=0)
    maxCompletionTokens: StrictInt = Field(gt=0)
    allowedModels: list[str] = Field(min_length=1, max_length=100)


class DraftEditInput(Contract):
    idempotencyKey: UUID
    version: StrictInt = Field(ge=1)
    draftPayload: dict[str, object]
    operatorNote: str | None = Field(None, max_length=1000)


class DraftDecisionInput(Contract):
    idempotencyKey: UUID
    version: StrictInt = Field(ge=1)
    operatorNote: str | None = Field(None, max_length=1000)


def build_router(
    configuration: AiConfigurationService,
    generation: AiGenerationCoordinator,
    drafts_service: AiDraftReviewService,
    runtime: WorkspaceRuntime,
    external: AiExternalEffectService,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/ai",
        tags=["ai-governance"],
        responses={409: {"model": AiConflictResponse}},
    )

    def ready(write=False):
        if not runtime.ready or runtime.error:
            raise workspace_unavailable(str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:
            raise workspace_unavailable("Workspace writer lock is unavailable.")

    def invoke(call):
        try:
            return call()
        except AiNotFoundError as error:
            raise domain_problem(error, status_code=404) from error
        except AiConflictError as error:
            raise api_problem(
                409,
                str(error) if str(error).startswith("ai_") else error.code,
                str(error),
                current=getattr(error, "current", None),
                revision=getattr(error, "revision", None),
            ) from error
        except AiValidationError as error:
            raise domain_problem(error, status_code=422) from error
        except AiGovernanceError as error:
            raise domain_problem(error, status_code=400) from error

    @router.get("/settings", response_model=SettingsResponse, operation_id="getAiSettings")
    def settings():
        ready()
        return invoke(configuration.settings)

    @router.put(
        "/settings", response_model=SettingsCommandResponse, operation_id="updateAiSettings"
    )
    def update_settings(data: SettingsInput):
        ready(True)
        values = {"kill_switch": data.killSwitch, "built_in_enabled": data.builtInEnabled}
        if "defaultConnectionId" in data.model_fields_set:
            values["default_connection_id"] = (
                None if data.defaultConnectionId is None else str(data.defaultConnectionId)
            )
        return invoke(
            lambda: configuration.update_settings(
                **values,
                idempotency_key=str(data.idempotencyKey),
                expected_revision=data.expectedRevision,
            )
        )

    @router.get(
        "/connections",
        response_model=list[ModelConnectionResponse],
        operation_id="listAiConnections",
    )
    def connections():
        ready()
        return invoke(configuration.connections)

    @router.post(
        "/connections",
        status_code=status.HTTP_201_CREATED,
        response_model=ConnectionCommandResponse,
        operation_id="createAiConnection",
    )
    def create_connection(data: ConnectionInput):
        ready(True)
        return invoke(
            lambda: configuration.create_connection(
                {
                    "label": data.label,
                    "adapter_id": data.adapterId,
                    "adapter_version": data.adapterVersion,
                    "model_identifier": data.modelIdentifier,
                    "execution_location": data.executionLocation,
                    "enabled": data.enabled,
                    "model_artifact_digest": data.modelArtifactDigest,
                    "quantization": data.quantization,
                    "runtime_id": data.runtimeId,
                    "runtime_version": data.runtimeVersion,
                },
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.patch(
        "/connections/{connection_id}",
        response_model=ConnectionCommandResponse,
        operation_id="updateAiConnection",
    )
    def patch_connection(connection_id: UUID, data: ConnectionPatch):
        ready(True)
        payload = data.model_dump(
            exclude={"expectedRevision", "idempotencyKey"}, exclude_unset=True
        )
        names = {
            "modelArtifactDigest": "model_artifact_digest",
            "runtimeId": "runtime_id",
            "runtimeVersion": "runtime_version",
        }
        return invoke(
            lambda: configuration.update_connection(
                str(connection_id),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
                data={names.get(key, key): value for key, value in payload.items()},
            )
        )

    @router.put(
        "/connections/{connection_id}/disclosure",
        response_model=ConnectionCommandResponse,
        operation_id="recordAiDisclosure",
    )
    def disclosure(connection_id: UUID, data: DisclosureInput):
        ready(True)
        return invoke(
            lambda: configuration.set_disclosure(
                str(connection_id),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
                disclosure_version=data.disclosureVersion,
                data_classes=data.dataClasses,
            )
        )

    @router.put(
        "/connections/{connection_id}/credential",
        response_model=ExternalEffectResponse,
        operation_id="setAiCredential",
        response_model_exclude_unset=True,
    )
    def credential(connection_id: UUID, data: CredentialInput):
        ready(True)
        return invoke(
            lambda: external.execute(
                "credential_set",
                str(connection_id),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
                credential=data.credential,
            )
        )

    @router.delete(
        "/connections/{connection_id}/credential",
        response_model=ExternalEffectResponse,
        response_model_exclude_unset=True,
        operation_id="deleteAiCredential",
    )
    def delete_credential(connection_id: UUID, data: ExternalEffectInput):
        ready(True)
        return invoke(
            lambda: external.execute(
                "credential_delete",
                str(connection_id),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/connections/{connection_id}/test",
        response_model=ExternalEffectResponse,
        response_model_exclude_unset=True,
        operation_id="testAiConnection",
    )
    def test_connection(connection_id: UUID, data: ExternalEffectInput):
        ready(True)
        return invoke(
            lambda: external.execute(
                "connection_probe",
                str(connection_id),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.get(
        "/external-operations/{operation_id}",
        response_model=ExternalEffectResponse,
        response_model_exclude_unset=True,
        operation_id="getAiExternalOperation",
    )
    def external_operation(operation_id: UUID):
        ready()
        return invoke(lambda: external.receipt(operation_id=str(operation_id)))

    @router.get(
        "/external-operations/by-key/{key}",
        response_model=ExternalEffectResponse,
        response_model_exclude_unset=True,
        operation_id="getAiExternalOperationByKey",
    )
    def external_operation_key(key: UUID):
        ready()
        return invoke(lambda: external.receipt(key=str(key)))

    @router.post(
        "/external-operations/{operation_id}/acknowledge-unknown",
        response_model=ExternalEffectResponse,
        response_model_exclude_unset=True,
        operation_id="acknowledgeAiExternalUncertainty",
    )
    def acknowledge_external(operation_id: UUID, data: ExternalUncertaintyAcknowledgement):
        ready(True)
        if data.acknowledgeUnknownOutcome is not True:
            raise api_problem(
                422, "ai_validation", "Explicit uncertainty acknowledgement is required."
            )
        return invoke(lambda: external.acknowledge_unknown(str(operation_id)))

    @router.get(
        "/limits", response_model=list[ActionLimitResponse], operation_id="listAiActionLimits"
    )
    def limits():
        ready()
        return invoke(configuration.limits)

    @router.put(
        "/limits/{action_type}",
        response_model=LimitCommandResponse,
        operation_id="updateAiActionLimit",
    )
    def limit(action_type: str, data: LimitInput):
        ready(True)
        return invoke(
            lambda: configuration.put_limit(
                action_type,
                {
                    "enabled": data.enabled,
                    "connection_id": None if data.connectionId is None else str(data.connectionId),
                    "max_runs_per_utc_day": data.maxRunsPerUtcDay,
                    "max_prompt_tokens": data.maxPromptTokens,
                    "max_completion_tokens": data.maxCompletionTokens,
                    "allowed_models": data.allowedModels,
                },
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.get(
        "/redaction-profiles",
        response_model=list[RedactionProfileResponse],
        operation_id="listAiRedactionProfiles",
    )
    def profiles():
        ready()
        return [
            {
                "name": item.name,
                "version": item.version,
                "actionTypes": [
                    action.action_type
                    for action in generation.actions.all()
                    if action.redaction_profile == (item.name, item.version)
                ],
                "fieldHandling": dict(item.summary),
            }
            for item in generation.profiles.all()
        ]

    @router.get("/drafts", response_model=DraftPageResponse, operation_id="listAiDrafts")
    def drafts(
        status: DraftStatus | None = None,
        owningModule: str | None = None,
        entityKind: str | None = None,
        actionType: str | None = None,
        sourceEntityType: str | None = None,
        sourceEntityId: str | None = None,
        cursor: str | None = None,
        pageSize: int = Query(100, ge=1, le=500),
    ):
        ready()
        parsed = None
        if cursor:
            parts = cursor.split("|", 1)
            if len(parts) != 2:
                raise api_problem(422, "ai_validation", "Invalid AI draft cursor.")
            parsed = (parts[0], parts[1])
        return invoke(
            lambda: drafts_service.list_drafts(
                status=status,
                owning_module=owningModule,
                entity_kind=entityKind,
                action_type=actionType,
                source_entity_type=sourceEntityType,
                source_entity_id=sourceEntityId,
                cursor=parsed,
                page_size=pageSize,
            )
        )

    @router.get("/drafts/{draft_id}", response_model=DraftDetailResponse, operation_id="getAiDraft")
    def draft(draft_id: UUID):
        ready()
        return invoke(lambda: drafts_service.draft_detail(str(draft_id)))

    @router.patch(
        "/drafts/{draft_id}", response_model=DraftCommandResponse, operation_id="editAiDraft"
    )
    def edit(draft_id: UUID, data: DraftEditInput):
        ready(True)
        return invoke(
            lambda: drafts_service.edit_draft(
                str(draft_id),
                version=data.version,
                idempotency_key=str(data.idempotencyKey),
                payload=data.draftPayload,
                operator_note=data.operatorNote,
            )
        )

    @router.post(
        "/drafts/{draft_id}/approve",
        response_model=DraftApprovalResponse,
        operation_id="approveAiDraft",
    )
    def approve(draft_id: UUID, data: DraftDecisionInput):
        ready(True)
        return invoke(
            lambda: drafts_service.approve_draft(
                str(draft_id),
                version=data.version,
                idempotency_key=str(data.idempotencyKey),
                operator_note=data.operatorNote,
            )
        )

    @router.post(
        "/drafts/{draft_id}/dismiss",
        response_model=DraftCommandResponse,
        operation_id="dismissAiDraft",
    )
    def dismiss(draft_id: UUID, data: DraftDecisionInput):
        ready(True)
        return invoke(
            lambda: drafts_service.dismiss_draft(
                str(draft_id),
                version=data.version,
                idempotency_key=str(data.idempotencyKey),
                operator_note=data.operatorNote,
            )
        )

    @router.get(
        "/command-operations/by-key/{key}",
        response_model=AiCommandReceiptResponse,
        operation_id="getAiCommandByKey",
    )
    def command_by_key(key: UUID):
        ready()
        return invoke(lambda: configuration.command_result(idempotency_key=str(key)))

    @router.get(
        "/command-operations/{operation_id}",
        response_model=AiCommandReceiptResponse,
        operation_id="getAiCommandOperation",
    )
    def command_by_id(operation_id: UUID):
        ready()
        return invoke(lambda: configuration.command_result(operation_id=str(operation_id)))

    return router

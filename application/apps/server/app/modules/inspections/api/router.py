"""Typed HTTP boundary for INSP-001."""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt

from app.platform.api_errors import api_problem, domain_problem, workspace_unavailable

from app.modules.files.application.errors import MAX_FILE_BYTES, FileError
from app.modules.inspections.application.service import (
    AreaInput,
    InspectionConflictError,
    InspectionError,
    InspectionNotFoundError,
    InspectionService,
    ObservationInput,
)
from app.modules.inspections.application.commands import InspectionRevisionConflict
from app.modules.workspace.application.runtime import WorkspaceRuntime


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CommandRequest(Contract):
    expectedRevision: StrictInt = Field(ge=0)
    idempotencyKey: UUID


class ObservationRequest(Contract):
    itemName: str = Field(min_length=1, max_length=160)
    conditionState: Literal[
        "good", "fair", "poor", "damaged", "missing", "not_tested", "not_applicable"
    ]
    cleanlinessState: Literal["clean", "needs_cleaning", "not_assessed"] | None = None
    observedOn: date | None = None
    isCompleted: StrictBool = False
    notes: str | None = Field(None, max_length=4000)


class AreaRequest(Contract):
    displayName: str = Field(min_length=1, max_length=160)
    observations: list[ObservationRequest] = Field(default_factory=list)
    notes: str | None = Field(None, max_length=4000)


class CreateReportRequest(CommandRequest):
    reportKind: Literal["pre_move_in", "post_move_out"]
    walkthroughOn: date
    conductedBy: str = Field(min_length=1, max_length=160)
    tenantPresence: Literal["present", "not_present", "declined", "not_recorded"] = "not_recorded"
    generalNotes: str | None = Field(None, max_length=4000)
    areas: list[AreaRequest] = Field(default_factory=list)
    templateId: UUID | None = None


class TemplateRequest(CommandRequest):
    displayName: str = Field(min_length=1, max_length=160)
    applicability: Literal["residential", "office", "any"] = "any"
    notes: str | None = Field(None, max_length=4000)
    areas: list[AreaRequest] = Field(default_factory=list)


class TemplatePatchRequest(CommandRequest):
    displayName: str | None = Field(None, min_length=1, max_length=160)
    applicability: Literal["residential", "office", "any"] | None = None
    notes: str | None = Field(None, max_length=4000)
    areas: list[AreaRequest] | None = None


class ReplaceAreasRequest(CommandRequest):
    areas: list[AreaRequest]


class ReportPatchRequest(CommandRequest):
    walkthroughOn: date | None = None
    conductedBy: str | None = Field(None, min_length=1, max_length=160)
    tenantPresence: Literal["present", "not_present", "declined", "not_recorded"] | None = None
    generalNotes: str | None = Field(None, max_length=4000)


class AcknowledgmentItem(Contract):
    status: Literal["acknowledged", "disputed", "declined", "not_requested", "pending"]
    notes: str | None = Field(None, max_length=4000)


class AcknowledgmentRequest(CommandRequest):
    acknowledgments: dict[str, AcknowledgmentItem]


class FinalizeRequest(CommandRequest):
    confirmed: StrictBool
    timingExceptionReason: str | None = Field(None, max_length=1000)


class CorrectionRequest(CreateReportRequest):
    correctionReason: str = Field(min_length=1, max_length=1000)


class ComparisonItemRequest(Contract):
    preObservationId: UUID | None = None
    postObservationId: UUID | None = None
    comparisonState: Literal[
        "unchanged",
        "improved",
        "normal_wear",
        "possible_tenant_damage",
        "maintenance_needed",
        "not_comparable",
    ]
    operatorNotes: str | None = Field(None, max_length=4000)


class ComparisonRequest(CommandRequest):
    comparisons: list[ComparisonItemRequest]


class EvidenceLinkResponse(Contract):
    id: str
    fileId: str | None = None
    archivedAt: AwareDatetime | None = None
    archiveReason: str | None = None
    revision: StrictInt = 1
    entityType: Literal["condition_observation"]
    entityId: str
    purpose: Literal["condition_photo", "supporting_document"]
    createdAt: AwareDatetime


class EvidenceResponse(Contract):
    id: str
    originalName: str
    mediaType: str
    sizeBytes: int
    contentSha256: str
    storageProvider: Literal["local", "s3"]
    storageState: Literal["available", "missing", "quarantined"]
    available: bool
    verifiedAt: AwareDatetime
    createdAt: AwareDatetime
    links: list[EvidenceLinkResponse]


class ObservationResponse(Contract):
    id: str
    conditionAreaId: str
    itemName: str
    normalizedName: str
    conditionState: Literal[
        "good", "fair", "poor", "damaged", "missing", "not_tested", "not_applicable"
    ]
    cleanlinessState: Literal["clean", "needs_cleaning", "not_assessed"] | None
    observedOn: date
    isCompleted: bool
    completedAt: AwareDatetime | None
    notes: str | None
    sortOrder: int
    files: list[EvidenceResponse]


class AreaResponse(Contract):
    id: str
    conditionReportId: str
    displayName: str
    normalizedName: str
    sortOrder: int
    notes: str | None
    observations: list[ObservationResponse]


class AcknowledgmentResponse(Contract):
    id: str
    conditionReportId: str
    leaseParticipantId: str
    status: Literal["acknowledged", "disputed", "declined", "not_requested", "pending"]
    acknowledgedOn: AwareDatetime | None
    notes: str | None


class TemplateItemResponse(Contract):
    id: str
    templateId: str
    areaDisplayName: str
    areaNormalizedName: str
    itemName: str
    itemNormalizedName: str
    sortOrder: int
    createdAt: AwareDatetime


class ComparisonItemResponse(Contract):
    id: str
    leaseId: str
    preReportId: str
    postReportId: str
    preObservationId: str | None
    postObservationId: str | None
    comparisonState: Literal[
        "unchanged",
        "improved",
        "normal_wear",
        "possible_tenant_damage",
        "maintenance_needed",
        "not_comparable",
    ]
    operatorNotes: str | None
    createdAt: AwareDatetime
    updatedAt: AwareDatetime


class AttentionResponse(Contract):
    preMoveIn: Literal["complete", "due", "overdue", "not_due"]
    postMoveOut: Literal["complete", "due", "not_due"]


class ReportResponse(Contract):
    revision: StrictInt = Field(ge=0)
    id: str
    leaseId: str
    spaceId: str
    reportKind: Literal["pre_move_in", "post_move_out"]
    status: Literal["draft", "finalized", "superseded"]
    walkthroughOn: date
    conductedBy: str
    tenantPresence: Literal["present", "not_present", "declined", "not_recorded"]
    supersedesReportId: str | None
    correctionReason: str | None
    timingExceptionReason: str | None
    generalNotes: str | None
    finalizedAt: AwareDatetime | None
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    areas: list[AreaResponse]
    acknowledgments: list[AcknowledgmentResponse]
    acknowledgmentComplete: bool


class ReportListResponse(Contract):
    revision: StrictInt = Field(ge=0)
    reports: list[ReportResponse]
    attention: AttentionResponse


class TemplateResponse(Contract):
    revision: StrictInt = Field(ge=0)
    id: str
    displayName: str
    normalizedName: str
    applicability: Literal["residential", "office", "any"]
    notes: str | None
    archivedAt: AwareDatetime | None
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    items: list[TemplateItemResponse]


class ComparisonResponse(Contract):
    revision: StrictInt = Field(ge=0)
    preReport: ReportResponse | None
    postReport: ReportResponse | None
    comparisons: list[ComparisonItemResponse]
    requiresFreshReview: bool


class ReportCommandResponse(ReportResponse):
    operationId: UUID


class TemplateCommandResponse(TemplateResponse):
    operationId: UUID


class EvidenceCommandResponse(EvidenceResponse):
    revision: StrictInt = Field(ge=0)
    operationId: UUID


class ComparisonCommandResponse(Contract):
    comparisons: list[ComparisonItemResponse]
    revision: StrictInt = Field(ge=0)
    operationId: UUID


class CommandRecoveryResponse(Contract):
    result: (
        ReportCommandResponse
        | TemplateCommandResponse
        | EvidenceCommandResponse
        | ComparisonCommandResponse
    )


class InspectionCurrentState(Contract):
    scopeKind: Literal["lease", "template"]
    scopeId: UUID | None
    revision: StrictInt = Field(ge=0)
    report: ReportResponse | None = None
    template: TemplateResponse | None = None


class InspectionConflictDetail(Contract):
    code: Literal["inspection_revision_conflict", "inspection_conflict"]
    message: str
    current: InspectionCurrentState | None = None


class InspectionConflictResponse(Contract):
    detail: InspectionConflictDetail


def build_router(service: InspectionService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(tags=["inspections"], responses={409: {"model": InspectionConflictResponse}})

    def ready(*, write=True):
        try:
            runtime.require_ready(write=write)
        except Exception as error:
            raise workspace_unavailable(str(error)) from error

    def invoke(operation):
        try:
            return operation()
        except InspectionRevisionConflict as error:
            raise api_problem(
                409, "inspection_revision_conflict", str(error), current=error.current
            ) from error
        except InspectionNotFoundError as error:
            raise domain_problem(error, status_code=404, code="inspection_not_found") from error
        except InspectionConflictError as error:
            raise domain_problem(error, status_code=409, code="inspection_conflict") from error
        except InspectionError as error:
            raise domain_problem(error, status_code=400, code="inspection_validation") from error

    def areas(values):
        return tuple(
            AreaInput(
                value.displayName,
                tuple(
                    ObservationInput(
                        x.itemName,
                        x.conditionState,
                        x.cleanlinessState,
                        None if x.observedOn is None else x.observedOn.isoformat(),
                        x.isCompleted,
                        x.notes,
                    )
                    for x in value.observations
                ),
                value.notes,
            )
            for value in values
        )

    def command(request):
        return {
            "expected_revision": request.expectedRevision,
            "idempotency_key": str(request.idempotencyKey),
        }

    @router.get(
        "/api/inspection-commands/by-key/{key}",
        response_model=CommandRecoveryResponse,
        operation_id="getInspectionCommandByKey",
    )
    def recover_by_key(key: UUID):
        ready(write=False)
        return invoke(lambda: {"result": service.recover_command(idempotency_key=str(key))})

    @router.get(
        "/api/inspection-commands/{operation_id}",
        response_model=CommandRecoveryResponse,
        operation_id="getInspectionCommand",
    )
    def recover(operation_id: UUID):
        ready(write=False)
        return invoke(lambda: {"result": service.recover_command(operation_id=str(operation_id))})

    @router.post(
        "/api/leases/{lease_id}/condition-reports",
        status_code=status.HTTP_201_CREATED,
        response_model=ReportCommandResponse,
        operation_id="createConditionReport",
    )
    def create(lease_id: UUID, request: CreateReportRequest):
        ready()
        return invoke(
            lambda: service.create(
                str(lease_id),
                report_kind=request.reportKind,
                walkthrough_on=request.walkthroughOn.isoformat(),
                conducted_by=request.conductedBy,
                tenant_presence=request.tenantPresence,
                general_notes=request.generalNotes,
                areas=areas(request.areas),
                template_id=str(request.templateId) if request.templateId else None,
                **command(request),
            )
        )

    @router.get(
        "/api/leases/{lease_id}/condition-reports",
        response_model=ReportListResponse,
        operation_id="listConditionReports",
    )
    def list_reports(lease_id: UUID):
        ready()
        return invoke(lambda: service.list_for_lease(str(lease_id)))

    @router.post(
        "/api/condition-checklist-templates",
        status_code=status.HTTP_201_CREATED,
        response_model=TemplateCommandResponse,
        operation_id="createConditionChecklistTemplate",
    )
    def create_template(request: TemplateRequest):
        ready()
        return invoke(
            lambda: service.create_template(
                display_name=request.displayName,
                applicability=request.applicability,
                notes=request.notes,
                areas=areas(request.areas),
                **command(request),
            )
        )

    @router.get(
        "/api/condition-checklist-templates",
        response_model=list[TemplateResponse],
        operation_id="listConditionChecklistTemplates",
    )
    def list_templates():
        ready()
        return invoke(service.list_templates)

    @router.patch(
        "/api/condition-checklist-templates/{template_id}",
        response_model=TemplateCommandResponse,
        operation_id="patchConditionChecklistTemplate",
    )
    def patch_template(template_id: UUID, request: TemplatePatchRequest):
        ready()
        return invoke(
            lambda: service.patch_template(
                str(template_id),
                display_name=request.displayName,
                applicability=request.applicability,
                notes=request.notes,
                notes_provided="notes" in request.model_fields_set,
                areas=None if request.areas is None else areas(request.areas),
                **command(request),
            )
        )

    @router.get(
        "/api/condition-reports/{report_id}",
        response_model=ReportResponse,
        operation_id="getConditionReport",
    )
    def get(report_id: UUID):
        ready()
        return invoke(lambda: service.get(str(report_id)))

    @router.patch(
        "/api/condition-reports/{report_id}",
        response_model=ReportCommandResponse,
        operation_id="patchConditionReport",
    )
    def patch_report(report_id: UUID, request: ReportPatchRequest):
        ready()
        return invoke(
            lambda: service.patch_report(
                str(report_id),
                walkthrough_on=None
                if request.walkthroughOn is None
                else request.walkthroughOn.isoformat(),
                conducted_by=request.conductedBy,
                tenant_presence=request.tenantPresence,
                general_notes=request.generalNotes,
                general_notes_provided="generalNotes" in request.model_fields_set,
                **command(request),
            )
        )

    @router.put(
        "/api/condition-reports/{report_id}/areas",
        response_model=ReportCommandResponse,
        operation_id="replaceConditionReportAreas",
    )
    def replace_areas(report_id: UUID, request: ReplaceAreasRequest):
        ready()
        return invoke(
            lambda: service.replace_areas(str(report_id), areas(request.areas), **command(request))
        )

    @router.put(
        "/api/condition-reports/{report_id}/acknowledgments",
        response_model=ReportCommandResponse,
        operation_id="acknowledgeConditionReport",
    )
    def acknowledge(report_id: UUID, request: AcknowledgmentRequest):
        ready()
        return invoke(
            lambda: service.acknowledge(
                str(report_id),
                {key: value.model_dump() for key, value in request.acknowledgments.items()},
                **command(request),
            )
        )

    @router.post(
        "/api/condition-observations/{observation_id}/evidence",
        status_code=status.HTTP_201_CREATED,
        response_model=EvidenceCommandResponse,
        operation_id="attachConditionEvidence",
    )
    async def attach_evidence(
        observation_id: UUID,
        file: UploadFile = File(...),
        purpose: Literal["condition_photo", "supporting_document"] = Form(...),
        expected_revision: int = Form(..., ge=0),
        idempotency_key: UUID = Form(...),
    ):
        ready()
        staged_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False) as staged:
                staged_path = Path(staged.name)
                size = 0
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise api_problem(
                            413,
                            "request_payload_too_large",
                            "File exceeds the 50 MiB local upload limit.",
                        )
                    staged.write(chunk)
            return invoke(
                lambda: service.attach_evidence(
                    str(observation_id),
                    staged_path,
                    file.filename or "evidence",
                    file.content_type or "application/octet-stream",
                    purpose,
                    expected_revision=expected_revision,
                    idempotency_key=str(idempotency_key),
                )
            )
        except FileError as error:
            raise domain_problem(error, status_code=400) from error
        except OSError as error:
            raise api_problem(
                507, "evidence_staging_failed", "Unable to stage evidence."
            ) from error
        finally:
            if staged_path is not None:
                staged_path.unlink(missing_ok=True)

    @router.post(
        "/api/condition-reports/{report_id}/finalize",
        response_model=ReportCommandResponse,
        operation_id="finalizeConditionReport",
    )
    def finalize(report_id: UUID, request: FinalizeRequest):
        ready()
        return invoke(
            lambda: service.finalize(
                str(report_id),
                confirmed=request.confirmed,
                timing_exception_reason=request.timingExceptionReason,
                **command(request),
            )
        )

    @router.post(
        "/api/condition-reports/{report_id}/corrections",
        status_code=status.HTTP_201_CREATED,
        response_model=ReportCommandResponse,
        operation_id="correctConditionReport",
    )
    def correction(report_id: UUID, request: CorrectionRequest):
        ready()

        def operation():
            source = service.get(str(report_id))
            return service.create(
                source["leaseId"],
                report_kind=source["reportKind"],
                walkthrough_on=request.walkthroughOn.isoformat(),
                conducted_by=request.conductedBy,
                tenant_presence=request.tenantPresence,
                general_notes=request.generalNotes,
                areas=areas(request.areas),
                correction_of=str(report_id),
                correction_reason=request.correctionReason,
                **command(request),
            )

        return invoke(operation)

    @router.get(
        "/api/leases/{lease_id}/condition-comparison",
        response_model=ComparisonResponse,
        operation_id="getConditionComparison",
    )
    def comparison(lease_id: UUID):
        ready()
        return invoke(lambda: service.comparison(str(lease_id)))

    @router.put(
        "/api/leases/{lease_id}/condition-comparison",
        response_model=ComparisonCommandResponse,
        operation_id="reviewConditionComparison",
    )
    def save_comparison(lease_id: UUID, request: ComparisonRequest):
        ready()
        return invoke(
            lambda: service.save_comparisons(
                str(lease_id),
                [
                    {
                        "pre_observation_id": str(item.preObservationId)
                        if item.preObservationId
                        else None,
                        "post_observation_id": str(item.postObservationId)
                        if item.postObservationId
                        else None,
                        "comparison_state": item.comparisonState,
                        "operator_notes": item.operatorNotes,
                    }
                    for item in request.comparisons
                ],
                **command(request),
            )
        )

    return router

"""Typed HTTP boundary for INSP-001."""
from __future__ import annotations
from datetime import date, datetime
from typing import Literal
import tempfile
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from app.modules.inspections.application.service import AreaInput, InspectionConflictError, InspectionError, InspectionNotFoundError, InspectionService, ObservationInput
from app.modules.workspace.application.runtime import WorkspaceRuntime
from app.modules.files.application.errors import FileError, MAX_FILE_BYTES

class Contract(BaseModel): model_config = ConfigDict(extra="forbid")
class ObservationRequest(Contract):
    itemName: str = Field(min_length=1, max_length=160); conditionState: Literal["good","fair","poor","damaged","missing","not_tested","not_applicable"]; cleanlinessState: Literal["clean","needs_cleaning","not_assessed"] | None = None; observedOn: date | None = None; isCompleted: StrictBool = False; notes: str | None = Field(None, max_length=4000)
class AreaRequest(Contract):
    displayName: str = Field(min_length=1,max_length=160); observations: list[ObservationRequest] = Field(default_factory=list); notes: str | None = Field(None,max_length=4000)
class CreateReportRequest(Contract):
    reportKind: Literal["pre_move_in","post_move_out"]; walkthroughOn: date; conductedBy: str = Field(min_length=1,max_length=160); tenantPresence: Literal["present","not_present","declined","not_recorded"] = "not_recorded"; generalNotes: str | None = Field(None,max_length=4000); areas: list[AreaRequest] = Field(default_factory=list); templateId: str | None = Field(None,min_length=1,max_length=80)
class TemplateRequest(Contract):
    displayName: str = Field(min_length=1, max_length=160); applicability: Literal["residential","office","any"] = "any"; notes: str | None = Field(None,max_length=4000); areas: list[AreaRequest] = Field(default_factory=list)
class TemplatePatchRequest(Contract):
    displayName: str | None = Field(None,min_length=1,max_length=160); applicability: Literal["residential","office","any"] | None = None; notes: str | None = Field(None,max_length=4000); areas: list[AreaRequest] | None = None
class ReplaceAreasRequest(Contract): areas: list[AreaRequest]
class ReportPatchRequest(Contract):
    walkthroughOn: date | None = None; conductedBy: str | None = Field(None,min_length=1,max_length=160); tenantPresence: Literal["present","not_present","declined","not_recorded"] | None = None; generalNotes: str | None = Field(None,max_length=4000)
class AcknowledgmentItem(Contract): status: Literal["acknowledged","disputed","declined","not_requested","pending"]; notes: str | None = Field(None,max_length=4000)
class AcknowledgmentRequest(Contract): acknowledgments: dict[str,AcknowledgmentItem]
class FinalizeRequest(Contract): confirmed: StrictBool; timingExceptionReason: str | None = Field(None,max_length=1000)
class CorrectionRequest(CreateReportRequest):
    correctionReason: str = Field(min_length=1,max_length=1000)
class ComparisonItemRequest(Contract):
    preObservationId: str | None = None; postObservationId: str | None = None; comparisonState: Literal["unchanged","improved","normal_wear","possible_tenant_damage","maintenance_needed","not_comparable"]; operatorNotes: str | None = Field(None,max_length=4000)
class ComparisonRequest(Contract): comparisons: list[ComparisonItemRequest]
class EvidenceLinkResponse(Contract): id: str; entityType: Literal["condition_observation"]; entityId: str; purpose: Literal["condition_photo", "supporting_document"]; createdAt: datetime
class EvidenceResponse(Contract): id: str; originalName: str; mediaType: str; sizeBytes: int; contentSha256: str; storageProvider: Literal["local", "s3"]; storageState: Literal["pending", "available", "missing", "quarantined"]; createdAt: datetime; links: list[EvidenceLinkResponse]
class ObservationResponse(Contract): id: str; conditionAreaId: str; itemName: str; normalizedName: str; conditionState: Literal["good","fair","poor","damaged","missing","not_tested","not_applicable"]; cleanlinessState: Literal["clean","needs_cleaning","not_assessed"] | None; observedOn: date; isCompleted: bool; completedAt: datetime | None; notes: str | None; sortOrder: int; files: list[EvidenceResponse]
class AreaResponse(Contract): id: str; conditionReportId: str; displayName: str; normalizedName: str; sortOrder: int; notes: str | None; observations: list[ObservationResponse]
class AcknowledgmentResponse(Contract): id: str; conditionReportId: str; leaseParticipantId: str; status: Literal["acknowledged","disputed","declined","not_requested","pending"]; acknowledgedOn: datetime | None; notes: str | None
class TemplateItemResponse(Contract): id: str; templateId: str; areaDisplayName: str; areaNormalizedName: str; itemName: str; itemNormalizedName: str; sortOrder: int; createdAt: datetime
class ComparisonItemResponse(Contract): id: str; leaseId: str; preReportId: str; postReportId: str; preObservationId: str | None; postObservationId: str | None; comparisonState: Literal["unchanged","improved","normal_wear","possible_tenant_damage","maintenance_needed","not_comparable"]; operatorNotes: str | None; createdAt: datetime; updatedAt: datetime
class AttentionResponse(Contract): preMoveIn: Literal["complete","due","overdue","not_due"]; postMoveOut: Literal["complete","due","not_due"]
class ReportResponse(Contract):
    id: str; leaseId: str; spaceId: str; reportKind: Literal["pre_move_in","post_move_out"]; status: Literal["draft","finalized","superseded"]; walkthroughOn: date; conductedBy: str; tenantPresence: Literal["present","not_present","declined","not_recorded"]; supersedesReportId: str | None; correctionReason: str | None; timingExceptionReason: str | None; generalNotes: str | None; finalizedAt: datetime | None; createdAt: datetime; updatedAt: datetime; areas: list[AreaResponse]; acknowledgments: list[AcknowledgmentResponse]; acknowledgmentComplete: bool
class ReportListResponse(Contract): reports: list[ReportResponse]; attention: AttentionResponse
class TemplateResponse(Contract): id: str; displayName: str; normalizedName: str; applicability: Literal["residential","office","any"]; notes: str | None; archivedAt: datetime | None; createdAt: datetime; updatedAt: datetime; items: list[TemplateItemResponse]
class ComparisonResponse(Contract): preReport: ReportResponse | None; postReport: ReportResponse | None; comparisons: list[ComparisonItemResponse]; requiresFreshReview: bool

def build_router(service: InspectionService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(tags=["inspections"])
    def ready():
        try: runtime.require_ready(write=True)
        except Exception as error: raise HTTPException(503, str(error)) from error
    def invoke(operation):
        try: return operation()
        except InspectionNotFoundError as error: raise HTTPException(404, str(error)) from error
        except InspectionConflictError as error: raise HTTPException(409, str(error)) from error
        except InspectionError as error: raise HTTPException(400, str(error)) from error
    def areas(values): return tuple(AreaInput(value.displayName, tuple(ObservationInput(x.itemName,x.conditionState,x.cleanlinessState,None if x.observedOn is None else x.observedOn.isoformat(),x.isCompleted,x.notes) for x in value.observations), value.notes) for value in values)
    @router.post("/api/leases/{lease_id}/condition-reports", status_code=status.HTTP_201_CREATED, response_model=ReportResponse)
    def create(lease_id: str, request: CreateReportRequest):
        ready(); return invoke(lambda: service.create(lease_id, report_kind=request.reportKind, walkthrough_on=request.walkthroughOn.isoformat(), conducted_by=request.conductedBy, tenant_presence=request.tenantPresence, general_notes=request.generalNotes, areas=areas(request.areas), template_id=request.templateId))
    @router.get("/api/leases/{lease_id}/condition-reports", response_model=ReportListResponse)
    def list_reports(lease_id: str): ready(); return invoke(lambda: service.list_for_lease(lease_id))
    @router.post("/api/condition-checklist-templates", status_code=status.HTTP_201_CREATED, response_model=TemplateResponse)
    def create_template(request: TemplateRequest): ready(); return invoke(lambda: service.create_template(display_name=request.displayName, applicability=request.applicability, notes=request.notes, areas=areas(request.areas)))
    @router.get("/api/condition-checklist-templates", response_model=list[TemplateResponse])
    def list_templates(): ready(); return invoke(service.list_templates)
    @router.patch("/api/condition-checklist-templates/{template_id}", response_model=TemplateResponse)
    def patch_template(template_id: str, request: TemplatePatchRequest):
        ready(); return invoke(lambda: service.patch_template(template_id, display_name=request.displayName, applicability=request.applicability, notes=request.notes, notes_provided="notes" in request.model_fields_set, areas=None if request.areas is None else areas(request.areas)))
    @router.get("/api/condition-reports/{report_id}", response_model=ReportResponse)
    def get(report_id: str): ready(); return invoke(lambda: service.get(report_id))
    @router.patch("/api/condition-reports/{report_id}", response_model=ReportResponse)
    def patch_report(report_id: str, request: ReportPatchRequest):
        ready(); return invoke(lambda: service.patch_report(report_id, walkthrough_on=None if request.walkthroughOn is None else request.walkthroughOn.isoformat(), conducted_by=request.conductedBy, tenant_presence=request.tenantPresence, general_notes=request.generalNotes, general_notes_provided="generalNotes" in request.model_fields_set))
    @router.put("/api/condition-reports/{report_id}/areas", response_model=ReportResponse)
    def replace_areas(report_id: str, request: ReplaceAreasRequest): ready(); return invoke(lambda: service.replace_areas(report_id, areas(request.areas)))
    @router.put("/api/condition-reports/{report_id}/acknowledgments", response_model=ReportResponse)
    def acknowledge(report_id: str, request: AcknowledgmentRequest): ready(); return invoke(lambda: service.acknowledge(report_id, {key:value.model_dump() for key,value in request.acknowledgments.items()}))
    @router.post("/api/condition-observations/{observation_id}/evidence", status_code=status.HTTP_201_CREATED, response_model=EvidenceResponse)
    async def attach_evidence(observation_id: str, file: UploadFile = File(...), purpose: Literal["condition_photo", "supporting_document"] = Form(...)):
        ready(); staged_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False) as staged:
                staged_path = Path(staged.name)
                size = 0
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES: raise HTTPException(status_code=413, detail="File exceeds the 50 MiB local upload limit.")
                    staged.write(chunk)
            return invoke(lambda: service.attach_evidence(observation_id, staged_path, file.filename or "evidence", file.content_type or "application/octet-stream", purpose))
        except FileError as error: raise HTTPException(status_code=400, detail=str(error)) from error
        except OSError as error: raise HTTPException(status_code=507, detail=f"Unable to stage evidence: {error}") from error
        finally:
            if staged_path is not None: staged_path.unlink(missing_ok=True)
    @router.post("/api/condition-reports/{report_id}/finalize", response_model=ReportResponse)
    def finalize(report_id: str, request: FinalizeRequest): ready(); return invoke(lambda: service.finalize(report_id, confirmed=request.confirmed, timing_exception_reason=request.timingExceptionReason))
    @router.post("/api/condition-reports/{report_id}/corrections", status_code=status.HTTP_201_CREATED, response_model=ReportResponse)
    def correction(report_id: str, request: CorrectionRequest):
        ready()
        def operation():
            source = service.get(report_id)
            return service.create(source["leaseId"], report_kind=source["reportKind"], walkthrough_on=request.walkthroughOn.isoformat(), conducted_by=request.conductedBy, tenant_presence=request.tenantPresence, general_notes=request.generalNotes, areas=areas(request.areas), correction_of=report_id, correction_reason=request.correctionReason)
        return invoke(operation)
    @router.get("/api/leases/{lease_id}/condition-comparison", response_model=ComparisonResponse)
    def comparison(lease_id: str): ready(); return invoke(lambda: service.comparison(lease_id))
    @router.put("/api/leases/{lease_id}/condition-comparison", response_model=list[ComparisonItemResponse])
    def save_comparison(lease_id: str, request: ComparisonRequest):
        ready(); return invoke(lambda: service.save_comparisons(lease_id, [{"pre_observation_id": item.preObservationId, "post_observation_id": item.postObservationId, "comparison_state": item.comparisonState, "operator_notes": item.operatorNotes} for item in request.comparisons]))
    return router

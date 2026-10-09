"""Bounded incomplete Inspection forms; attachment bytes remain source-owned."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt

from app.modules.operator.domain.models import Contract


class InspectionForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=0)


class ObservationForm(Contract):
    itemName: str = Field(min_length=1, max_length=160)
    conditionState: Literal[
        "good", "fair", "poor", "damaged", "missing", "not_tested", "not_applicable"
    ]
    cleanlinessState: Literal["clean", "needs_cleaning", "not_assessed"] | None = None
    observedOn: date | None = None
    isCompleted: StrictBool = False
    notes: str | None = Field(None, max_length=4000)


class AreaForm(Contract):
    displayName: str = Field(min_length=1, max_length=160)
    observations: list[ObservationForm] = Field(default_factory=list, max_length=100)
    notes: str | None = Field(None, max_length=4000)


class ReportForm(InspectionForm):
    reportKind: Literal["pre_move_in", "post_move_out"] | None = None
    walkthroughOn: date | None = None
    conductedBy: str | None = Field(None, max_length=160)
    tenantPresence: Literal["present", "not_present", "declined", "not_recorded"] | None = None
    generalNotes: str | None = Field(None, max_length=4000)
    areas: list[AreaForm] | None = Field(None, max_length=100)
    templateId: UUID | None = None


class CorrectionForm(ReportForm):
    correctionReason: str | None = Field(None, max_length=1000)


class ReportPatchForm(InspectionForm):
    walkthroughOn: date | None = None
    conductedBy: str | None = Field(None, max_length=160)
    tenantPresence: Literal["present", "not_present", "declined", "not_recorded"] | None = None
    generalNotes: str | None = Field(None, max_length=4000)


class AreasForm(InspectionForm):
    areas: list[AreaForm] | None = Field(None, max_length=100)


class AcknowledgmentForm(Contract):
    status: Literal["acknowledged", "disputed", "declined", "not_requested", "pending"]
    notes: str | None = Field(None, max_length=4000)


class AcknowledgeForm(InspectionForm):
    acknowledgments: dict[UUID, AcknowledgmentForm] | None = Field(None, max_length=100)


class FinalizeForm(InspectionForm):
    confirmed: StrictBool | None = None
    timingExceptionReason: str | None = Field(None, max_length=1000)


class EvidenceForm(InspectionForm):
    originalName: str | None = Field(None, max_length=255)
    mediaType: str | None = Field(None, max_length=255)
    contentSha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$", strict=True)
    sizeBytes: StrictInt | None = Field(None, gt=0, le=50 * 1024 * 1024)
    purpose: Literal["condition_photo", "supporting_document"] | None = None


class ComparisonForm(Contract):
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


class ComparisonReviewForm(InspectionForm):
    comparisons: list[ComparisonForm] | None = Field(None, max_length=100)


class TemplateForm(InspectionForm):
    displayName: str | None = Field(None, max_length=160)
    applicability: Literal["residential", "office", "any"] | None = None
    notes: str | None = Field(None, max_length=4000)
    areas: list[AreaForm] | None = Field(None, max_length=100)


INSPECTION_SCHEMAS = {
    "inspection.report.create": ReportForm,
    "inspection.report.patch": ReportPatchForm,
    "inspection.report.areas.replace": AreasForm,
    "inspection.report.acknowledge": AcknowledgeForm,
    "inspection.report.finalize": FinalizeForm,
    "inspection.report.correct": CorrectionForm,
    "inspection.evidence.attach": EvidenceForm,
    "inspection.comparison.review": ComparisonReviewForm,
    "inspection.template.create": TemplateForm,
    "inspection.template.patch": TemplateForm,
}


def inspection_source_kind(form):
    if form == "inspection.template.create":
        return None
    if form.endswith("template.patch"):
        return "condition_template"
    if form.endswith("evidence.attach"):
        return "condition_observation"
    if form in {"inspection.report.create", "inspection.comparison.review"}:
        return "inspection_lease"
    return "condition_report"

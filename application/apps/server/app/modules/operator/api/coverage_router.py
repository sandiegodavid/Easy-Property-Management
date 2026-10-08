"""Area-scoped coverage reads and strict, durable review commands."""

from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import Field

from app.modules.operator.domain.models import Contract
from app.modules.operator.application.coverage_models import CoverageReview, CoverageResult
from app.platform.coverage import CoverageArea


class ReviewInput(Contract):
    expectedEvidenceRevision: str = Field(pattern="^[0-9a-f]{64}$")
    basis: Literal["acknowledged", "not_applicable"] = "acknowledged"
    reason: str = Field(min_length=1, max_length=1000)
    nextReviewOn: date | None = None
    idempotencyKey: UUID


def register_coverage(router, service, invoke):
    @router.get(
        "/coverage/operations/{key}",
        response_model=CoverageResult,
        operation_id="getOperatorCoverageOperation",
    )
    def operation(key: UUID):
        return invoke(lambda: service.operation(str(key)))

    @router.get(
        "/coverage/{kind}/{subject_id}/{area}",
        response_model=CoverageResult,
        operation_id="getOperatorCoverage",
    )
    def get_coverage(kind: Literal["property", "space"], subject_id: UUID, area: CoverageArea):
        return invoke(lambda: service.read(kind, str(subject_id), area))

    @router.post(
        "/coverage/{kind}/{subject_id}/{area}/reviews",
        response_model=CoverageResult,
        operation_id="recordOperatorCoverageReview",
    )
    def review(
        kind: Literal["property", "space"], subject_id: UUID, area: CoverageArea, data: ReviewInput
    ):
        return invoke(
            lambda: service.review(
                CoverageReview(
                    subject_kind=kind,
                    subject_id=subject_id,
                    area=area,
                    expected_evidence_revision=data.expectedEvidenceRevision,
                    basis=data.basis,
                    reason=data.reason,
                    next_review_on=data.nextReviewOn,
                    idempotency_key=data.idempotencyKey,
                )
            )
        )

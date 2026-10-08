"""Strict coverage commands and pure precedence/trigger projection."""

from datetime import date
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field, AwareDatetime

from app.modules.operator.domain.models import Contract
from app.platform.coverage import CoverageArea, CoverageCause


class ResolutionTarget(Contract):
    entityType: Literal["property", "space"]
    entityId: UUID
    section: CoverageArea


class CoverageResult(Contract):
    subjectKind: Literal["property", "space"]
    subjectId: UUID
    area: CoverageArea
    availability: Literal["available", "unavailable"]
    applicability: Literal["applicable", "not_applicable"] | None = None
    state: (
        Literal["recorded", "needs_review", "missing_required_information", "not_applicable"] | None
    )
    causes: list[CoverageCause]
    evidenceRevision: str | None = Field(None, pattern="^[0-9a-f]{64}$")
    lastManualReviewAt: AwareDatetime | None = None
    trigger: Literal["source_changed", "review_date_reached", "manual_review_required"] | None = (
        None
    )
    leaseId: UUID | None = None
    asOf: AwareDatetime
    effectiveLocalDate: date | None = None
    resolutionRoute: ResolutionTarget | None = None
    operationId: UUID | None = None


class CoverageReview(Contract):
    subject_kind: Literal["property", "space"]
    subject_id: UUID
    area: CoverageArea
    expected_evidence_revision: str = Field(pattern="^[0-9a-f]{64}$")
    basis: Literal["acknowledged", "not_applicable"] = "acknowledged"
    reason: str = Field(min_length=1, max_length=1000)
    next_review_on: date | None = None
    idempotency_key: UUID


def review_audit_snapshot(row, result):
    """Bind the recorded replay response without disclosing free-form review reasons."""
    return {
        **result,
        "basis": row["basis"],
        "nextReviewOn": row["next_review_on"],
        "timeZone": row["time_zone"],
    }


def coverage_view(subject, facts, review, as_of):
    day = as_of.astimezone(ZoneInfo(facts.time_zone)).date()
    causes = list(facts.missing) + list(facts.needs_review)
    trigger = None
    valid_review = review is not None and review["evidence_revision"] == facts.revision
    if review is not None and not valid_review:
        causes.append("source_changed")
        trigger = "source_changed"
    if (
        review is not None
        and review["next_review_on"]
        and date.fromisoformat(review["next_review_on"]) <= day
    ):
        valid_review = False
        causes.append("review_date_reached")
        trigger = "review_date_reached"
    if facts.requires_manual_review and not valid_review and not trigger:
        causes.append("manual_review_required")
        trigger = "manual_review_required"
    if facts.missing:
        state = "missing_required_information"
    elif facts.not_applicable_reason:
        state = "not_applicable"
        causes = [facts.not_applicable_reason, *causes]
    elif facts.needs_review or not valid_review and (review or facts.requires_manual_review):
        state = "needs_review"
    else:
        state = "recorded"
    return {
        "subjectKind": subject.kind,
        "subjectId": subject.id,
        "area": facts.area,
        "availability": "available",
        "applicability": "not_applicable" if facts.not_applicable_reason else "applicable",
        "state": state,
        "causes": causes,
        "evidenceRevision": facts.revision,
        "lastManualReviewAt": review["created_at"] if review else None,
        "trigger": trigger,
        "leaseId": facts.lease_id,
        "asOf": as_of.isoformat(),
        "effectiveLocalDate": day.isoformat(),
        "resolutionRoute": {
            "entityType": "property" if facts.area == "maintenance" else "space",
            "entityId": subject.id,
            "section": facts.area,
        },
    }

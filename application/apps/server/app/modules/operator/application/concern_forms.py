"""Approved incomplete Owner-concern inputs; source commands remain authoritative."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, StrictInt

from app.modules.operator.domain.models import Contract


class ConcernFollowUpFields(Contract):
    title: str | None = Field(None, min_length=1, max_length=255)
    notes: str | None = Field(None, max_length=10_000)
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    dueAtUtc: AwareDatetime | None = None
    dueTimezone: str | None = Field(None, max_length=128)


class ConcernCreateForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=0, le=0)
    ownerPartyId: UUID | None = None
    propertyId: UUID | None = None
    concernType: Literal["general_rental", "lease", "tenant", "vacancy"] | None = None
    summary: str | None = Field(None, min_length=1, max_length=240)
    description: str | None = Field(None, min_length=1, max_length=10_000)
    raisedAtUtc: AwareDatetime | None = None
    spaceId: UUID | None = None
    leaseId: UUID | None = None
    tenantPartyId: UUID | None = None
    originatingCommunicationId: UUID | None = None
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    historicalSelectionConfirmed: StrictBool | None = None
    historicalSelectionReason: str | None = Field(None, max_length=1000)
    duplicateConfirmed: StrictBool | None = None
    duplicateReason: str | None = Field(None, max_length=1000)
    replacesConcernId: UUID | None = None
    followUp: ConcernFollowUpFields | None = None


class ConcernPatchForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=1)
    summary: str | None = Field(None, min_length=1, max_length=240)
    description: str | None = Field(None, min_length=1, max_length=10_000)
    priority: Literal["low", "normal", "high", "urgent"] | None = None


class ConcernTransitionForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=1)
    confirmed: StrictBool | None = None
    summary: str | None = Field(None, min_length=1, max_length=4000)


class ConcernFollowUpForm(ConcernFollowUpFields):
    expectedRevision: StrictInt | None = Field(None, ge=1)


CONCERN_SCHEMAS = {
    "owner_concern.create": ConcernCreateForm,
    "owner_concern.patch": ConcernPatchForm,
    **{
        "owner_concern." + action: ConcernTransitionForm
        for action in ("in_progress", "open", "resolved", "dismissed")
    },
    "owner_concern.follow_up": ConcernFollowUpForm,
}

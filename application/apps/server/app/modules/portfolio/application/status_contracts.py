"""Typed status projections and retained manual command receipts."""

from datetime import date
from uuid import UUID
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpaceResponse(ContractModel):
    id: UUID
    propertyId: UUID
    spaceKind: Literal["whole_home", "whole_office", "office_suite"]
    displayName: str
    suiteOrFloor: str | None
    notes: str | None
    status: Literal["active", "archived"]
    revision: StrictInt = Field(ge=0)
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    archivedAt: AwareDatetime | None


class OccupancyPeriodResponse(ContractModel):
    id: UUID
    spaceId: UUID
    occupancyStatus: Literal["occupied", "vacant", "unknown"]
    startsOn: date
    endsOn: date | None
    recordState: Literal["valid", "cancelled", "superseded"]
    supersededById: UUID | None
    sourceKind: Literal["manual", "lease"]
    sourceId: str | None
    note: str | None
    createdAt: AwareDatetime
    endedAt: AwareDatetime | None
    cancelledAt: AwareDatetime | None


class AvailabilityResponse(ContractModel):
    spaceId: UUID
    availabilityStatus: Literal["available_now", "available_on", "not_available", "unknown"]
    availableOn: date | None
    sourceKind: Literal["manual", "listing", "lease"]
    sourceId: str | None
    note: str | None
    updatedAt: AwareDatetime
    recordedStatus: Literal["available_now", "available_on", "not_available", "unknown"]
    effectiveStatus: Literal["available_now", "available_on", "not_available", "unknown"]


class AttentionReasonResponse(ContractModel):
    code: Literal[
        "occupancy_unknown", "availability_unknown", "source_conflict", "missing_status_record"
    ]
    resolution: str


class SpaceStatusResponse(SpaceResponse):
    currentOccupancy: OccupancyPeriodResponse
    scheduledOccupancy: OccupancyPeriodResponse | None
    scheduledOccupancyTimeline: list[OccupancyPeriodResponse]
    availability: AvailabilityResponse
    attentionReasons: list[AttentionReasonResponse]
    asOf: AwareDatetime
    effectiveLocalDate: date
    operationId: UUID | None = None


class ManualStatusMutationResponse(SpaceStatusResponse):
    model_config = ConfigDict(extra="forbid", frozen=True)
    revision: StrictInt = Field(ge=1)
    operationId: UUID


class ManualStatusOperationReceipt(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operationId: UUID
    spaceId: UUID
    idempotencyKey: str
    revision: StrictInt = Field(ge=1)
    committedAt: AwareDatetime
    result: ManualStatusMutationResponse


class ManualStatusConflictDetail(ContractModel):
    code: Literal[
        "portfolio_status_payload_conflict",
        "portfolio_status_revision_conflict",
        "portfolio_status_lifecycle_conflict",
    ]
    message: str
    currentStatus: SpaceStatusResponse


class ManualStatusConflictResponse(ContractModel):
    detail: ManualStatusConflictDetail

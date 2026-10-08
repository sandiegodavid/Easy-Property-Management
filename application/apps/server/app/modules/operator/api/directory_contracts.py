"""Fixed OPS directory envelopes for generated clients."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator

from app.modules.operator.domain.models import Contract
from app.modules.operator.application.coverage_models import CoverageResult

PropertyState = Literal["active", "archived", "all"]
OwnershipContext = Literal["self_owned", "managed_for_owner", "mixed"]
Occupancy = Literal["occupied", "vacant", "unknown"]
Availability = Literal["available_now", "available_on", "not_available", "unknown"]


class CoverageTarget(Contract):
    subjectKind: Literal["property", "owner"]
    subjectId: UUID
    section: Literal["coverage"]
    relationshipScope: Literal["current", "former", "all"]


class CoveragePreview(Contract):
    availability: Literal["available", "unavailable"]
    reasonCode: Literal["source_read_unavailable"] | None
    matchingTotal: StrictInt | None = Field(ge=0)
    items: list[CoverageResult] | None = Field(max_length=5)
    hasMore: StrictBool | None
    asOf: AwareDatetime
    sourceRevision: str | None
    viewAll: CoverageTarget

    @model_validator(mode="after")
    def consistent_preview(self):
        if self.availability == "available":
            if (
                self.items is None
                or self.matchingTotal is None
                or self.matchingTotal < len(self.items)
                or self.hasMore != (self.matchingTotal > len(self.items))
                or self.sourceRevision is None
                or self.reasonCode is not None
            ):
                raise ValueError(
                    "Available coverage requires a counted bounded preview and provenance."
                )
        elif self.reasonCode is None or any(
            value is not None
            for value in (self.items, self.matchingTotal, self.hasMore, self.sourceRevision)
        ):
            raise ValueError("Unavailable coverage cannot fabricate a result.")
        return self


class OwnerPreview(Contract):
    partyId: UUID
    displayName: str


class SpacePreview(Contract):
    id: UUID
    displayName: str
    revision: StrictInt
    occupancy: Occupancy
    availability: Availability
    needsAttention: StrictBool


class PropertyCard(Contract):
    id: UUID
    displayName: str
    addressLine1: str
    addressLine2: str | None
    city: str
    region: str | None
    postalCode: str | None
    countryCode: str
    timeZone: str
    status: Literal["active", "archived"]
    propertyType: str
    inventoryLayout: str
    ownershipContext: Literal["self_owned", "managed_for_owner", "mixed", "unknown"]
    needsAttention: StrictBool
    effectiveLocalDate: date
    ownerCount: StrictInt = Field(ge=0)
    owners: list[OwnerPreview] = Field(max_length=3)
    spaceCount: StrictInt = Field(ge=0)
    spaces: list[SpacePreview] = Field(max_length=3)
    coverage: CoveragePreview


class PropertyQueryEcho(Contract):
    q: str
    status: PropertyState
    ownershipContext: OwnershipContext | None
    occupancy: Occupancy | None
    availability: Availability | None
    needsAttention: StrictBool | None
    limit: StrictInt


class PropertyDirectoryPage(Contract):
    items: list[PropertyCard]
    matchingTotal: StrictInt = Field(ge=0)
    nextCursor: str | None
    asOf: AwareDatetime
    sourceRevision: str
    query: PropertyQueryEcho


class RelatedPropertyPreview(Contract):
    id: UUID
    displayName: str
    status: Literal["active", "archived"]
    addressLine1: str
    city: str


class OwnerCard(Contract):
    partyId: UUID
    displayName: str
    partyKind: Literal["individual", "organization"]
    archived: StrictBool
    propertyCount: StrictInt = Field(ge=0)
    properties: list[RelatedPropertyPreview] = Field(max_length=3)
    coverage: CoveragePreview


class OwnerQueryEcho(Contract):
    q: str
    archiveState: PropertyState
    relationshipScope: Literal["current", "former", "all"]
    propertyState: PropertyState
    limit: StrictInt


class OwnerDirectoryPage(Contract):
    items: list[OwnerCard]
    matchingTotal: StrictInt = Field(ge=0)
    nextCursor: str | None
    asOf: AwareDatetime
    sourceRevision: str
    query: OwnerQueryEcho

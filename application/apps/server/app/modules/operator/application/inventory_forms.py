"""Bounded incomplete Portfolio inventory inputs; not domain commands."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt

from app.modules.operator.domain.models import Contract


class InlineOwner(Contract):
    partyKind: Literal["individual", "organization"] | None = None
    displayName: str | None = Field(None, max_length=240)


class InventoryOwner(Contract):
    ownerKind: Literal["local_operator", "client_owner"] | None = None
    partyId: UUID | None = None
    inlineParty: InlineOwner | None = None


class InitialOccupancy(Contract):
    occupancyStatus: Literal["occupied", "vacant", "unknown"] | None = None
    effectiveOn: date | None = None
    note: str | None = Field(None, max_length=1000)


class InitialAvailability(Contract):
    availabilityStatus: (
        Literal["available_now", "available_on", "not_available", "unknown"] | None
    ) = None
    availableOn: date | None = None
    note: str | None = Field(None, max_length=1000)


class InitialSpace(Contract):
    displayName: str | None = Field(None, max_length=120)
    suiteOrFloor: str | None = Field(None, max_length=80)
    notes: str | None = Field(None, max_length=4000)
    occupancy: InitialOccupancy | None = None
    availability: InitialAvailability | None = None


class InventoryRevision(Contract):
    expectedPropertyRevision: StrictInt | None = Field(None, ge=0)


class PropertyChanges(Contract):
    displayName: str | None = Field(None, max_length=240)
    addressLine1: str | None = Field(None, max_length=240)
    addressLine2: str | None = Field(None, max_length=240)
    city: str | None = Field(None, max_length=120)
    region: str | None = Field(None, max_length=120)
    postalCode: str | None = Field(None, max_length=40)
    countryCode: str | None = Field(None, max_length=2)
    notes: str | None = Field(None, max_length=4000)


class PropertyCreateForm(PropertyChanges, InventoryRevision):
    expectedPropertyRevision: StrictInt | None = Field(None, ge=0, le=0)
    propertyType: Literal["single_family_home", "condo", "townhome", "office"] | None = None
    inventoryLayout: Literal["single_space", "whole_office", "office_suites"] | None = None
    ownerships: list[InventoryOwner] | None = Field(None, max_length=100)
    spaces: list[InitialSpace] | None = Field(None, max_length=100)


class PropertyPatchForm(InventoryRevision):
    changes: PropertyChanges | None = None


class InventoryArchiveForm(InventoryRevision):
    confirmed: StrictBool | None = None


class OwnershipReplaceForm(InventoryRevision):
    ownerships: list[InventoryOwner] | None = Field(None, max_length=100)
    effectiveOn: date | None = None


class SpaceCreateForm(InitialSpace, InventoryRevision):
    pass


class SpaceTarget(InventoryRevision):
    spaceId: UUID | None = None


class SpaceChanges(Contract):
    displayName: str | None = Field(None, max_length=120)
    suiteOrFloor: str | None = Field(None, max_length=80)
    notes: str | None = Field(None, max_length=4000)


class SpacePatchForm(SpaceTarget):
    changes: SpaceChanges | None = None


class SpaceArchiveForm(SpaceTarget):
    confirmed: StrictBool | None = None


INVENTORY_SCHEMAS = {
    "portfolio.property.create": PropertyCreateForm,
    "portfolio.property.patch": PropertyPatchForm,
    "portfolio.property.archive": InventoryArchiveForm,
    "portfolio.property.restore": InventoryRevision,
    "portfolio.ownerships.replace": OwnershipReplaceForm,
    "portfolio.space.create": SpaceCreateForm,
    "portfolio.space.patch": SpacePatchForm,
    "portfolio.space.archive": SpaceArchiveForm,
    "portfolio.space.restore": SpaceTarget,
}

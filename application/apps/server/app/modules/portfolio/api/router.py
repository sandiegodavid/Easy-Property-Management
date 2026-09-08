"""Strict, documented local portfolio API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.modules.portfolio.application.service import (
    OwnershipInput,
    PartyCreateCommand,
    PortfolioError,
    PortfolioNotFoundError,
    PortfolioService,
    PropertyCreateCommand,
    OccupancyCommand,
    AvailabilityCommand,
    SpaceClassificationCommand,
    SpaceCreateCommand,
)
from app.modules.parties.application.service import PartyValidationError
from app.modules.portfolio.application.ports import PortfolioConflictError
from app.modules.workspace.application.runtime import WorkspaceRuntime


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PartyRequest(ContractModel):
    partyKind: Literal["individual", "organization"]
    displayName: str = Field(min_length=1, max_length=240)
    email: str | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=80)


class OwnershipRequest(ContractModel):
    ownerKind: Literal["local_operator", "client_owner"]
    partyId: str | None = None
    inlineParty: PartyRequest | None = None

    @model_validator(mode="after")
    def validate_party_reference(self) -> "OwnershipRequest":
        party_id = self.partyId.strip() if self.partyId is not None else None
        if self.ownerKind == "local_operator" and (
            party_id is not None or self.inlineParty is not None
        ):
            raise ValueError("local_operator ownership cannot include an owner party")
        if self.ownerKind == "client_owner" and (
            (party_id is None) == (self.inlineParty is None)
        ):
            raise ValueError(
                "client_owner ownership requires exactly one partyId or inlineParty"
            )
        self.partyId = party_id
        return self


class PropertyCreateRequest(ContractModel):
    displayName: str = Field(min_length=1, max_length=240)
    addressLine1: str = Field(min_length=1, max_length=240)
    addressLine2: str | None = Field(None, max_length=240)
    city: str = Field(min_length=1, max_length=120)
    region: str | None = Field(None, max_length=120)
    postalCode: str | None = Field(None, max_length=40)
    countryCode: str = Field(min_length=2, max_length=2)
    notes: str | None = Field(None, max_length=4000)
    ownerships: list[OwnershipRequest] = Field(min_length=1)
    propertyType: Literal["single_family_home", "condo", "townhome", "office"]
    inventoryLayout: Literal["single_space", "whole_office", "office_suites"] | None = None
    spaces: list["SpaceCreateRequest"] | None = None


class SpaceCreateRequest(ContractModel):
    displayName: str = Field(min_length=1, max_length=120)
    suiteOrFloor: str | None = Field(None, max_length=80)
    notes: str | None = Field(None, max_length=4000)
    occupancy: "OccupancyRequest | None" = None
    availability: "AvailabilityRequest | None" = None


class OccupancyRequest(ContractModel):
    occupancyStatus: Literal["occupied", "vacant", "unknown"]
    effectiveOn: date
    note: str | None = Field(None, max_length=1000)


class AvailabilityRequest(ContractModel):
    availabilityStatus: Literal["available_now", "available_on", "not_available", "unknown"]
    availableOn: date | None = None
    note: str | None = Field(None, max_length=1000)

    @model_validator(mode="after")
    def validate_date(self) -> "AvailabilityRequest":
        if (self.availabilityStatus == "available_on") != (self.availableOn is not None):
            raise ValueError("availableOn is required only with available_on")
        return self


class SpaceClassificationRequest(ContractModel):
    occupancy: OccupancyRequest | None = None
    availability: AvailabilityRequest | None = None

    @model_validator(mode="after")
    def require_status(self) -> "SpaceClassificationRequest":
        if self.occupancy is None and self.availability is None:
            raise ValueError("occupancy or availability is required")
        if self.occupancy is not None and self.occupancy.occupancyStatus == "unknown":
            raise ValueError("classification occupancy must be occupied or vacant")
        if self.availability is not None and self.availability.availabilityStatus == "unknown":
            raise ValueError("classification availability must select a known status")
        return self


class SpacePatchRequest(ContractModel):
    displayName: str | None = Field(None, min_length=1, max_length=120)
    suiteOrFloor: str | None = Field(None, max_length=80)
    notes: str | None = Field(None, max_length=4000)


class PropertyPatchRequest(ContractModel):
    displayName: str | None = Field(None, min_length=1, max_length=240)
    addressLine1: str | None = Field(None, min_length=1, max_length=240)
    addressLine2: str | None = Field(None, max_length=240)
    city: str | None = Field(None, min_length=1, max_length=120)
    region: str | None = Field(None, max_length=120)
    postalCode: str | None = Field(None, max_length=40)
    countryCode: str | None = Field(None, min_length=2, max_length=2)
    notes: str | None = Field(None, max_length=4000)


class OwnershipReplaceRequest(ContractModel):
    effectiveOn: str
    ownerships: list[OwnershipRequest] = Field(min_length=1)


class ConfirmationRequest(ContractModel):
    confirmed: StrictBool


class SpaceResponse(ContractModel):
    id: str
    propertyId: str
    spaceKind: Literal["whole_home", "whole_office", "office_suite"]
    displayName: str
    suiteOrFloor: str | None
    notes: str | None
    status: Literal["active", "archived"]
    createdAt: str
    updatedAt: str
    archivedAt: str | None


class OccupancyPeriodResponse(ContractModel):
    id: str
    spaceId: str
    occupancyStatus: Literal["occupied", "vacant", "unknown"]
    startsOn: date
    endsOn: date | None
    recordState: Literal["valid", "cancelled", "superseded"]
    supersededById: str | None
    sourceKind: Literal["manual", "lease"]
    sourceId: str | None
    note: str | None
    createdAt: datetime
    endedAt: datetime | None
    cancelledAt: datetime | None


class AvailabilityResponse(ContractModel):
    spaceId: str
    availabilityStatus: Literal["available_now", "available_on", "not_available", "unknown"]
    availableOn: date | None
    sourceKind: Literal["manual", "listing", "lease"]
    sourceId: str | None
    note: str | None
    updatedAt: datetime


class SpaceStatusResponse(SpaceResponse):
    currentOccupancy: OccupancyPeriodResponse
    scheduledOccupancy: OccupancyPeriodResponse | None
    scheduledOccupancyTimeline: list[OccupancyPeriodResponse]
    availability: AvailabilityResponse


class PropertyStatusSummaryResponse(ContractModel):
    activeSpaceCount: int
    occupiedCount: int
    vacantCount: int
    unknownOccupancyCount: int
    availableNowCount: int
    availableLaterCount: int
    nearestAvailableOn: date | None
    needsAttentionCount: int


class PortfolioStatusSummaryResponse(ContractModel):
    activePropertyCount: int
    activeSpaceCount: int
    occupiedCount: int
    vacantCount: int
    unknownOccupancyCount: int
    availableNowCount: int
    availableLaterCount: int
    nearestAvailableOn: date | None
    needsAttentionSpaceCount: int
    needsAttentionPropertyCount: int


class PartyResponse(ContractModel):
    id: str
    partyKind: Literal["individual", "organization"]
    displayName: str
    email: str | None
    phone: str | None
    createdAt: str
    updatedAt: str
    archivedAt: str | None


class OwnershipResponse(ContractModel):
    id: str
    propertyId: str
    ownerKind: Literal["local_operator", "client_owner"]
    partyId: str | None
    party: PartyResponse | None
    startsOn: str
    endsOn: str | None
    createdAt: str
    endedAt: str | None


class PropertyResponse(ContractModel):
    id: str
    displayName: str
    addressLine1: str
    addressLine2: str | None
    city: str
    region: str | None
    postalCode: str | None
    countryCode: str
    notes: str | None
    status: Literal["active", "archived"]
    createdAt: str
    updatedAt: str
    archivedAt: str | None
    propertyType: Literal["single_family_home", "condo", "townhome", "office"]
    inventoryLayout: Literal["single_space", "whole_office", "office_suites"]
    ownershipContext: Literal["self_owned", "managed_for_owner", "mixed"]
    ownerships: list[OwnershipResponse]
    spaces: list[SpaceStatusResponse]
    statusSummary: PropertyStatusSummaryResponse


def build_router(service: PortfolioService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(tags=["portfolio"])

    def require_ready(*, write: bool = False) -> None:
        if not runtime.ready or runtime.error:
            raise HTTPException(503, str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:
            raise HTTPException(503, "Workspace writer lock is unavailable.")

    def invoke(operation):
        try:
            return operation()
        except PortfolioNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except PortfolioConflictError as error:
            raise HTTPException(409, str(error)) from error
        except PortfolioError as error:
            raise HTTPException(400, str(error)) from error
        except PartyValidationError as error:
            raise HTTPException(400, str(error)) from error

    @router.post("/api/parties", response_model=PartyResponse, status_code=status.HTTP_201_CREATED)
    def create_party(data: PartyRequest):
        require_ready(write=True)
        return invoke(lambda: service.create_party(_party(data)).to_dict())

    @router.get("/api/parties", response_model=list[PartyResponse])
    def list_parties(activeOnly: bool = False):
        require_ready()
        return invoke(lambda: service.list_parties(active_only=activeOnly))

    @router.post("/api/parties/{party_id}/archive", response_model=PartyResponse)
    def archive_party(party_id: str, data: ConfirmationRequest):
        require_ready(write=True)
        return invoke(lambda: service.archive_party(party_id, confirmed=data.confirmed).to_dict())

    @router.post("/api/parties/{party_id}/restore", response_model=PartyResponse)
    def restore_party(party_id: str):
        require_ready(write=True)
        return invoke(lambda: service.restore_party(party_id).to_dict())

    @router.post("/api/properties", response_model=PropertyResponse, status_code=status.HTTP_201_CREATED)
    def create_property(data: PropertyCreateRequest):
        require_ready(write=True)

        def create_and_load() -> dict[str, object]:
            property_id = service.create_property(_create(data)).id
            return service.get_property(property_id)

        return invoke(create_and_load)

    @router.get("/api/properties", response_model=list[PropertyResponse])
    def list_properties(
        status: Literal["active", "archived"] | None = None,
        ownershipContext: Literal["self_owned", "managed_for_owner", "mixed"] | None = None,
        occupancy: Literal["occupied", "vacant", "unknown"] | None = None,
        availability: Literal["available_now", "available_on", "not_available", "unknown"] | None = None,
        needsAttention: bool | None = None,
    ):
        require_ready()
        return invoke(lambda: service.list_properties(
            status=status,
            ownership_context_filter=ownershipContext,
            occupancy_filter=occupancy,
            availability_filter=availability,
            needs_attention=needsAttention,
        ))

    @router.get("/api/properties/{property_id}", response_model=PropertyResponse)
    def get_property(property_id: str):
        require_ready()
        return invoke(lambda: service.get_property(property_id))

    @router.get("/api/portfolio/status-summary", response_model=PortfolioStatusSummaryResponse)
    def get_portfolio_status_summary():
        require_ready()
        return invoke(service.portfolio_status_summary)

    @router.patch("/api/properties/{property_id}", response_model=PropertyResponse)
    def patch_property(property_id: str, data: PropertyPatchRequest):
        require_ready(write=True)

        def patch_and_load() -> dict[str, object]:
            updated = service.patch_property(property_id, data.model_dump(exclude_unset=True))
            return service.get_property(updated.id)

        return invoke(patch_and_load)

    @router.post("/api/properties/{property_id}/archive", response_model=PropertyResponse)
    def archive_property(property_id: str, data: ConfirmationRequest):
        require_ready(write=True)

        def archive_and_load() -> dict[str, object]:
            archived = service.archive_property(property_id, confirmed=data.confirmed)
            return service.get_property(archived.id)

        return invoke(archive_and_load)

    @router.post("/api/properties/{property_id}/restore", response_model=PropertyResponse)
    def restore_property(property_id: str):
        require_ready(write=True)

        def restore_and_load() -> dict[str, object]:
            restored = service.restore_property(property_id)
            return service.get_property(restored.id)

        return invoke(restore_and_load)

    @router.put("/api/properties/{property_id}/ownerships", response_model=PropertyResponse)
    def replace_ownerships(property_id: str, data: OwnershipReplaceRequest):
        require_ready(write=True)
        return invoke(lambda: service.replace_ownerships(property_id, _ownerships(data.ownerships), data.effectiveOn))

    @router.post("/api/properties/{property_id}/spaces", response_model=SpaceResponse, status_code=status.HTTP_201_CREATED)
    def add_space(property_id: str, data: SpaceCreateRequest):
        require_ready(write=True)
        return invoke(lambda: service.add_space(property_id, _space(data)).to_dict())

    @router.post("/api/spaces/{space_id}/archive", response_model=SpaceResponse)
    def archive_space(space_id: str, data: ConfirmationRequest):
        require_ready(write=True)
        return invoke(lambda: service.archive_space(space_id, confirmed=data.confirmed).to_dict())

    @router.patch("/api/spaces/{space_id}", response_model=SpaceResponse)
    def patch_space(space_id: str, data: SpacePatchRequest):
        require_ready(write=True)
        return invoke(
            lambda: service.patch_space(
                space_id,
                data.model_dump(exclude_unset=True),
            ).to_dict()
        )

    @router.post("/api/spaces/{space_id}/restore", response_model=SpaceResponse)
    def restore_space(space_id: str):
        require_ready(write=True)
        return invoke(lambda: service.restore_space(space_id).to_dict())

    @router.get("/api/spaces/{space_id}/status", response_model=SpaceStatusResponse)
    def get_space_status(space_id: str):
        require_ready()
        return invoke(lambda: service.get_space_status(space_id))

    @router.put("/api/spaces/{space_id}/occupancy", response_model=SpaceStatusResponse)
    def change_occupancy(space_id: str, data: OccupancyRequest):
        require_ready(write=True)
        return invoke(lambda: service.change_occupancy(space_id, _occupancy(data)))

    @router.post("/api/spaces/{space_id}/occupancy/scheduled/{period_id}/cancel", response_model=SpaceStatusResponse)
    def cancel_scheduled_occupancy(space_id: str, period_id: str):
        require_ready(write=True)
        return invoke(lambda: service.cancel_scheduled_occupancy(space_id, period_id))

    @router.put("/api/spaces/{space_id}/occupancy/scheduled/{period_id}/replace", response_model=SpaceStatusResponse)
    def replace_scheduled_occupancy(
        space_id: str,
        period_id: str,
        data: OccupancyRequest,
    ):
        require_ready(write=True)
        return invoke(
            lambda: service.replace_scheduled_occupancy(
                space_id,
                period_id,
                _occupancy(data),
            )
        )

    @router.put("/api/spaces/{space_id}/availability", response_model=SpaceStatusResponse)
    def change_availability(space_id: str, data: AvailabilityRequest):
        require_ready(write=True)
        return invoke(lambda: service.change_availability(space_id, _availability(data)))

    @router.put("/api/spaces/{space_id}/classification", response_model=SpaceStatusResponse)
    def classify_space(space_id: str, data: SpaceClassificationRequest):
        require_ready(write=True)
        return invoke(lambda: service.classify_space(
            space_id,
            SpaceClassificationCommand(
                None if data.occupancy is None else _occupancy(data.occupancy),
                None if data.availability is None else _availability(data.availability),
            ),
        ))

    return router


def _party(data: PartyRequest) -> PartyCreateCommand:
    return PartyCreateCommand(data.partyKind, data.displayName, data.email, data.phone)


def _ownerships(items: list[OwnershipRequest]) -> tuple[OwnershipInput, ...]:
    return tuple(
        OwnershipInput(
            item.ownerKind,
            item.partyId,
            None if item.inlineParty is None else _party(item.inlineParty),
        )
        for item in items
    )


def _create(data: PropertyCreateRequest) -> PropertyCreateCommand:
    return PropertyCreateCommand(
        data.displayName,
        data.addressLine1,
        data.city,
        data.countryCode,
        data.propertyType,
        _ownerships(data.ownerships),
        data.addressLine2,
        data.region,
        data.postalCode,
        data.notes,
        data.inventoryLayout,
        None if data.spaces is None else tuple(_space(item) for item in data.spaces),
    )


def _space(data: SpaceCreateRequest) -> SpaceCreateCommand:
    return SpaceCreateCommand(
        data.displayName,
        data.suiteOrFloor,
        data.notes,
        None if data.occupancy is None else _occupancy(data.occupancy),
        None if data.availability is None else _availability(data.availability),
    )


def _occupancy(data: OccupancyRequest) -> OccupancyCommand:
    return OccupancyCommand(data.occupancyStatus, data.effectiveOn.isoformat(), data.note)


def _availability(data: AvailabilityRequest) -> AvailabilityCommand:
    return AvailabilityCommand(
        data.availabilityStatus,
        None if data.availableOn is None else data.availableOn.isoformat(),
        data.note,
    )

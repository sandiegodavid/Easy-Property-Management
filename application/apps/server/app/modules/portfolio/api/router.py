"""Strict, documented local portfolio API."""

from __future__ import annotations

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
)
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
    ownershipContext: Literal["self_owned", "managed_for_owner", "mixed"]
    ownerships: list[OwnershipResponse]


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
        except PortfolioError as error:
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
    ):
        require_ready()
        return invoke(lambda: service.list_properties(status=status, ownership_context_filter=ownershipContext))

    @router.get("/api/properties/{property_id}", response_model=PropertyResponse)
    def get_property(property_id: str):
        require_ready()
        return invoke(lambda: service.get_property(property_id))

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
        _ownerships(data.ownerships),
        data.addressLine2,
        data.region,
        data.postalCode,
        data.notes,
    )

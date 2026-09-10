"""Typed provider HTTP contract."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.modules.parties.application.service import ContactMethodCommand, PartyCreateCommand, PartyValidationError
from app.modules.vendors.application.service import (
    PossibleDuplicateParty, ProviderError, ProviderLifecycleConflict, ProviderNotFoundError,
    ProviderProfileCommand, ProviderProfilePatchCommand, ProviderSearchCommand, ProviderService, ReferenceCommand, ServiceAreaCommand, ServiceCommand, UNSET,
    ReputationLinkCommand, ReputationLinkPatchCommand, WorkHistoryCommand,
    canonical_reputation_url,
)
from app.modules.workspace.application.runtime import WorkspaceRuntime


class Contract(BaseModel): model_config = ConfigDict(extra="forbid")
class PartyInput(Contract): partyKind: Literal["individual", "organization"]; displayName: str = Field(min_length=1, max_length=240)
class ContactInput(Contract): methodKind: Literal["email", "phone"]; value: str = Field(min_length=1, max_length=320); extension: str | None = Field(None, max_length=6); label: str | None = Field(None, max_length=80)
class ProfileInput(Contract): selectionStatus: Literal["neutral", "preferred", "avoid"] = "neutral"; selectionReason: str | None = Field(None, max_length=1000); notes: str | None = Field(None, max_length=4000)
class CreateProviderInput(ProfileInput): party: PartyInput; contacts: list[ContactInput] = Field(default_factory=list); services: list["ServiceInput"] = Field(default_factory=list); serviceAreas: list["AreaInput"] = Field(default_factory=list); workHistory: list["WorkInput"] = Field(default_factory=list); references: list["ReferenceInput"] = Field(default_factory=list); confirmedNewParty: StrictBool = False
class ProfilePatchInput(Contract):
    selectionStatus: Literal["neutral", "preferred", "avoid"] | None = None
    selectionReason: str | None = Field(None, max_length=1000)
    notes: str | None = Field(None, max_length=4000)

    @model_validator(mode="after")
    def require_non_null_selection_status_when_supplied(self):
        if "selectionStatus" in self.model_fields_set and self.selectionStatus is None:
            raise ValueError("selectionStatus cannot be null.")
        return self
class ServiceInput(Contract): displayName: str = Field(min_length=1, max_length=160)
class AreaInput(ServiceInput): countryCode: str | None = Field(None, min_length=2, max_length=2)
class WorkInput(Contract): performedOn: date; summary: str = Field(min_length=1, max_length=1000); propertyId: str | None = None; outcomeNotes: str | None = Field(None, max_length=4000)
class ReferenceInput(Contract): referenceName: str | None = Field(None, max_length=240); organizationName: str | None = Field(None, max_length=240); relationship: str | None = Field(None, max_length=240); email: str | None = Field(None, max_length=320); phone: str | None = Field(None, max_length=320); notes: str | None = Field(None, max_length=4000)
class ReputationLinkInput(Contract):
    sourceKind: Literal["google", "yelp", "angi", "other"]
    sourceName: str | None = Field(None, max_length=80)
    url: str = Field(min_length=1)
    notes: str | None = Field(None, max_length=4000)
    lastCheckedOn: date | None = None

    @model_validator(mode="after")
    def validate_complete_link(self):
        try:
            ReputationLinkCommand(
                self.sourceKind, self.url, self.sourceName, self.notes,
                self.lastCheckedOn.isoformat() if self.lastCheckedOn else None,
            )
        except ProviderError as error:
            raise ValueError(str(error)) from error
        return self

class ReputationLinkPatchInput(Contract):
    sourceKind: Literal["google", "yelp", "angi", "other"] | None = None
    sourceName: str | None = Field(None, max_length=80)
    url: str | None = Field(None, min_length=1)
    notes: str | None = Field(None, max_length=4000)
    lastCheckedOn: date | None = None

    @model_validator(mode="after")
    def validate_supplied_fields(self):
        fields = self.model_fields_set
        if "sourceKind" in fields and self.sourceKind is None:
            raise ValueError("sourceKind cannot be null.")
        if "url" in fields:
            if self.url is None:
                raise ValueError("url cannot be null.")
            try:
                canonical_reputation_url(self.url)
            except ProviderError as error:
                raise ValueError(str(error)) from error
        if "sourceName" in fields and self.sourceName is not None and not self.sourceName.strip():
            raise ValueError("sourceName cannot be blank.")
        if "lastCheckedOn" in fields and self.lastCheckedOn is not None and self.lastCheckedOn > date.today():
            raise ValueError("lastCheckedOn cannot be in the future.")
        return self
class Confirmation(Contract): confirmed: StrictBool
class PartyResponse(Contract): id: str; partyKind: Literal["individual", "organization"]; displayName: str; createdAt: str; updatedAt: str; archivedAt: str | None
class ContactResponse(Contract): id: str; partyId: str; methodKind: Literal["email", "phone"]; displayValue: str; extension: str | None; label: str | None; status: Literal["active", "archived"]; createdAt: str; updatedAt: str; archivedAt: str | None
class ProfileResponse(Contract): partyId: str; selectionStatus: Literal["neutral", "preferred", "avoid"]; selectionReason: str | None; notes: str | None; createdAt: str; updatedAt: str; archivedAt: str | None
class ServiceResponse(Contract): id: str; partyId: str; displayName: str; normalizedName: str; createdAt: str; updatedAt: str; archivedAt: str | None
class AreaResponse(ServiceResponse): countryCode: str | None
class WorkResponse(Contract): id: str; partyId: str; propertyId: str | None; performedOn: date; summary: str; outcomeNotes: str | None; createdAt: str; updatedAt: str; archivedAt: str | None
class ReferenceResponse(Contract): id: str; partyId: str; referenceName: str | None; organizationName: str | None; relationship: str | None; email: str | None; phone: str | None; notes: str | None; createdAt: str; updatedAt: str; archivedAt: str | None
class ReputationLinkResponse(Contract): id: str; partyId: str; sourceKind: Literal["google", "yelp", "angi", "other"]; sourceName: str | None; normalizedSourceKey: str; url: str; normalizedUrl: str; notes: str | None; lastCheckedOn: date | None; createdAt: str; updatedAt: str; archivedAt: str | None
class ProviderResponse(Contract): party: PartyResponse; profile: ProfileResponse; contactMethods: list[ContactResponse]; services: list[ServiceResponse]; serviceAreas: list[AreaResponse]; workHistory: list[WorkResponse]; references: list[ReferenceResponse]; reputationLinks: list[ReputationLinkResponse]
class ProviderListResponse(Contract): party: PartyResponse; profile: ProfileResponse; services: list[ServiceResponse]; serviceAreas: list[AreaResponse]; workHistoryCount: int; referenceCount: int; reputationLinkCount: int


def build_router(provider_service: ProviderService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(prefix="/api/providers", tags=["providers"])
    def ready(write=False):
        if not runtime.ready or runtime.error: raise HTTPException(503, str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write: raise HTTPException(503, "Workspace writer lock is unavailable.")
    def invoke(operation):
        try: return operation()
        except ProviderNotFoundError as error: raise HTTPException(404, str(error)) from error
        except PossibleDuplicateParty as error: raise HTTPException(409, {"code":"possible_duplicate_party", "candidatePartyIds":error.candidate_party_ids}) from error
        except ProviderLifecycleConflict as error: raise HTTPException(409, str(error)) from error
        except (ProviderError, PartyValidationError) as error: raise HTTPException(400, str(error)) from error
    @router.post("", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
    def create(data: CreateProviderInput):
        ready(True); return invoke(lambda: provider_service.create(PartyCreateCommand(data.party.partyKind, data.party.displayName), _profile(data), contacts=tuple(_contact(item) for item in data.contacts), services=tuple(ServiceCommand(item.displayName) for item in data.services), areas=tuple(ServiceAreaCommand(item.displayName, item.countryCode) for item in data.serviceAreas), work_history=tuple(WorkHistoryCommand(item.performedOn.isoformat(), item.summary, item.propertyId, item.outcomeNotes) for item in data.workHistory), references=tuple(_command(item) for item in data.references), confirmed_new_party=data.confirmedNewParty))
    @router.post("/from-party/{party_id}", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
    def designate(party_id: str, data: ProfileInput):
        ready(True); return invoke(lambda: provider_service.designate(party_id, _profile(data)))
    @router.get("", response_model=list[ProviderListResponse])
    def list_providers(archiveState: Literal["active", "archived", "all"] = "active", search: str | None = Query(None, max_length=240), service: str | None = Query(None, max_length=160), serviceArea: str | None = Query(None, max_length=160), selectionStatus: Literal["neutral", "preferred", "avoid"] | None = None, propertyId: str | None = None, hasReference: bool | None = None):
        ready()
        return invoke(lambda: provider_service.list(ProviderSearchCommand(
            archive_state=archiveState,
            search=search,
            service=service,
            service_area=serviceArea,
            selection_status=selectionStatus,
            property_id=propertyId,
            has_reference=hasReference,
        )))
    @router.get("/{party_id}", response_model=ProviderResponse)
    def detail(party_id: str, includeArchived: bool = False): ready(); return invoke(lambda: provider_service.detail(party_id, include_archived=includeArchived))
    @router.patch("/{party_id}", response_model=ProviderResponse)
    def update(party_id: str, data: ProfilePatchInput):
        ready(True)
        return invoke(lambda: provider_service.update_profile(party_id, _patch_profile(data)))
    @router.post("/{party_id}/archive", response_model=ProviderResponse)
    def archive(party_id: str, data: Confirmation): ready(True); return invoke(lambda: provider_service.archive(party_id, confirmed=data.confirmed))
    @router.post("/{party_id}/restore", response_model=ProviderResponse)
    def restore(party_id: str): ready(True); return invoke(lambda: provider_service.restore(party_id))
    @router.post("/{party_id}/reputation-links", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
    def add_reputation_link(party_id: str, data: ReputationLinkInput):
        ready(True); return invoke(lambda: provider_service.add_reputation_link(party_id, _reputation(data)))
    @router.patch("/{party_id}/reputation-links/{link_id}", response_model=ProviderResponse)
    def patch_reputation_link(party_id: str, link_id: str, data: ReputationLinkPatchInput):
        ready(True); return invoke(lambda: provider_service.update_reputation_link(party_id, link_id, _reputation_patch(data)))
    @router.post("/{party_id}/reputation-links/{link_id}/archive", response_model=ProviderResponse)
    def archive_reputation_link(party_id: str, link_id: str, data: Confirmation):
        ready(True); return invoke(lambda: provider_service.archive_reputation_link(party_id, link_id, confirmed=data.confirmed))
    @router.post("/{party_id}/reputation-links/{link_id}/restore", response_model=ProviderResponse)
    def restore_reputation_link(party_id: str, link_id: str):
        ready(True); return invoke(lambda: provider_service.restore_reputation_link(party_id, link_id))
    _children(router, provider_service, ready, invoke)
    return router


def _children(router, service, ready, invoke):
    specs = (("services", ServiceInput, "service", ServiceResponse), ("service-areas", AreaInput, "area", AreaResponse), ("work-history", WorkInput, "work_history", WorkResponse), ("references", ReferenceInput, "reference", ReferenceResponse))
    for path, model, suffix, _response in specs:
        add = getattr(service, f"add_{suffix}"); update = getattr(service, f"update_{suffix}"); archive = getattr(service, f"archive_{suffix}"); restore = getattr(service, f"restore_{suffix}")
        create = _create_endpoint(add, model, ready, invoke)
        patch = _patch_endpoint(update, model, ready, invoke)
        archive_item = _archive_endpoint(archive, ready, invoke)
        restore_item = _restore_endpoint(restore, ready, invoke)
        router.add_api_route(f"/{{party_id}}/{path}", create, methods=["POST"], response_model=ProviderResponse, status_code=201)
        router.add_api_route(f"/{{party_id}}/{path}/{{item_id}}", patch, methods=["PATCH"], response_model=ProviderResponse)
        router.add_api_route(f"/{{party_id}}/{path}/{{item_id}}/archive", archive_item, methods=["POST"], response_model=ProviderResponse)
        router.add_api_route(f"/{{party_id}}/{path}/{{item_id}}/restore", restore_item, methods=["POST"], response_model=ProviderResponse)


def _create_endpoint(operation, model, ready, invoke):
    def endpoint(party_id: str, data):
        ready(True)
        return invoke(lambda: operation(party_id, _command(data)))
    endpoint.__annotations__["data"] = model
    return endpoint


def _patch_endpoint(operation, model, ready, invoke):
    def endpoint(party_id: str, item_id: str, data):
        ready(True)
        return invoke(lambda: operation(party_id, item_id, _command(data)))
    endpoint.__annotations__["data"] = model
    return endpoint


def _archive_endpoint(operation, ready, invoke):
    def endpoint(party_id: str, item_id: str, data: Confirmation):
        ready(True)
        return invoke(lambda: operation(party_id, item_id, confirmed=data.confirmed))
    return endpoint


def _restore_endpoint(operation, ready, invoke):
    def endpoint(party_id: str, item_id: str):
        ready(True)
        return invoke(lambda: operation(party_id, item_id))
    return endpoint


def _profile(data): return ProviderProfileCommand(data.selectionStatus, data.selectionReason, data.notes)
def _patch_profile(data):
    fields = data.model_fields_set
    return ProviderProfilePatchCommand(
        data.selectionStatus if "selectionStatus" in fields else UNSET,
        data.selectionReason if "selectionReason" in fields else UNSET,
        data.notes if "notes" in fields else UNSET,
    )
def _contact(data): return ContactMethodCommand(data.methodKind, data.value, data.extension, data.label)
def _reputation(data): return ReputationLinkCommand(data.sourceKind, data.url, data.sourceName, data.notes, data.lastCheckedOn.isoformat() if data.lastCheckedOn else None)
def _reputation_patch(data):
    fields = data.model_fields_set
    last_checked_on = UNSET
    if "lastCheckedOn" in fields:
        last_checked_on = data.lastCheckedOn.isoformat() if data.lastCheckedOn else None
    return ReputationLinkPatchCommand(
        data.sourceKind if "sourceKind" in fields else UNSET,
        data.url if "url" in fields else UNSET,
        data.sourceName if "sourceName" in fields else UNSET,
        data.notes if "notes" in fields else UNSET,
        last_checked_on,
    )
def _command(data):
    if isinstance(data, ServiceInput) and not isinstance(data, AreaInput): return ServiceCommand(data.displayName)
    if isinstance(data, AreaInput): return ServiceAreaCommand(data.displayName, data.countryCode)
    if isinstance(data, WorkInput): return WorkHistoryCommand(data.performedOn.isoformat(), data.summary, data.propertyId, data.outcomeNotes)
    return ReferenceCommand(data.referenceName, data.organizationName, data.relationship, data.email, data.phone, data.notes)

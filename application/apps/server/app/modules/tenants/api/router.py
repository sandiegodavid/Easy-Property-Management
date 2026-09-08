"""Typed local tenant contact API."""

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.modules.tenants.application.service import (
    ContactMethodCommand,
    TenantConflictError,
    TenantCreateCommand,
    TenantError,
    TenantNotFoundError,
    TenantProfilePatchCommand,
    TenantService,
)
from app.modules.workspace.application.runtime import WorkspaceRuntime


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContactRequest(Contract):
    methodKind: Literal["email", "phone"]
    value: str = Field(min_length=1, max_length=320)
    label: str | None = Field(None, max_length=80)


class TenantCreateRequest(Contract):
    partyKind: Literal["individual", "organization"]
    displayName: str = Field(min_length=1, max_length=240)
    email: str | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=80)
    contacts: list[ContactRequest] = Field(default_factory=list)
    notes: str | None = Field(None, max_length=4000)
    doNotContact: StrictBool = False


class DesignateRequest(Contract):
    notes: str | None = Field(None, max_length=4000)


class ProfilePatchRequest(Contract):
    preferredContactMethodId: str | None = None
    doNotContact: StrictBool = False
    notes: str | None = Field(None, max_length=4000)

    def command(self) -> TenantProfilePatchCommand:
        return TenantProfilePatchCommand.from_mapping({
            field: getattr(self, field)
            for field in self.model_fields_set
        })


class ConfirmationRequest(Contract):
    confirmed: StrictBool


class ContactArchiveRequest(ConfirmationRequest):
    replacementPreferredContactMethodId: str | None = None
    clearPreference: StrictBool = False


class TenantProfileResponse(Contract):
    partyId: str
    preferredContactMethodId: str | None
    doNotContact: bool
    notes: str | None
    createdAt: str
    updatedAt: str
    archivedAt: str | None


class ContactMethodResponse(Contract):
    id: str
    partyId: str
    methodKind: Literal["email", "phone"]
    displayValue: str
    label: str | None
    status: Literal["active", "archived"]
    createdAt: str
    updatedAt: str
    archivedAt: str | None


class TenantResponse(Contract):
    id: str
    partyKind: Literal["individual", "organization"]
    displayName: str
    email: str | None
    phone: str | None
    createdAt: str
    updatedAt: str
    archivedAt: str | None
    profile: TenantProfileResponse
    contactMethods: list[ContactMethodResponse]


def build_router(service: TenantService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(prefix="/api/tenants", tags=["tenants"])

    def ready(write: bool = False) -> None:
        if not runtime.ready or runtime.error:
            raise HTTPException(503, str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:
            raise HTTPException(503, "Workspace writer lock is unavailable.")

    def invoke(operation):
        try:
            return operation()
        except TenantNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except TenantConflictError as error:
            raise HTTPException(409, str(error)) from error
        except TenantError as error:
            raise HTTPException(400, str(error)) from error

    @router.post("", status_code=status.HTTP_201_CREATED, response_model=TenantResponse)
    def create(data: TenantCreateRequest):
        ready(True)
        return invoke(lambda: service.create(TenantCreateCommand(
            data.partyKind,
            data.displayName,
            data.email,
            data.phone,
            tuple(ContactMethodCommand(item.methodKind, item.value, item.label) for item in data.contacts),
            data.notes,
            data.doNotContact,
        )))

    @router.post("/from-party/{party_id}", status_code=status.HTTP_201_CREATED, response_model=TenantResponse)
    def designate(party_id: str, data: DesignateRequest):
        ready(True)
        return invoke(lambda: service.designate(party_id, notes=data.notes))

    @router.get("", response_model=list[TenantResponse])
    def list_tenants(archiveState: Literal["active", "archived", "all"] = "active", search: str | None = None):
        ready()
        return invoke(lambda: service.list(archive_state=archiveState, search=search))

    @router.get("/{party_id}", response_model=TenantResponse)
    def get(party_id: str):
        ready()
        return invoke(lambda: service.get(party_id))

    @router.patch("/{party_id}", response_model=TenantResponse)
    def update(party_id: str, data: ProfilePatchRequest):
        ready(True)
        return invoke(lambda: service.update_profile(party_id, data.command()))

    @router.post("/{party_id}/contact-methods", status_code=status.HTTP_201_CREATED, response_model=ContactMethodResponse)
    def add_contact(party_id: str, data: ContactRequest):
        ready(True)
        return invoke(lambda: service.add_contact(party_id, ContactMethodCommand(data.methodKind, data.value, data.label)).to_dict())

    @router.patch("/{party_id}/contact-methods/{method_id}", response_model=ContactMethodResponse)
    def update_contact(party_id: str, method_id: str, data: ContactRequest):
        ready(True)
        return invoke(lambda: service.update_contact(party_id, method_id, ContactMethodCommand(data.methodKind, data.value, data.label)).to_dict())

    @router.post("/{party_id}/contact-methods/{method_id}/archive", response_model=ContactMethodResponse)
    def archive_contact(party_id: str, method_id: str, data: ContactArchiveRequest):
        ready(True)
        return invoke(lambda: service.archive_contact(
            party_id, method_id, confirmed=data.confirmed,
            replacement_preferred_contact_method_id=data.replacementPreferredContactMethodId,
            clear_preference=data.clearPreference,
        ).to_dict())

    @router.post("/{party_id}/contact-methods/{method_id}/restore", response_model=ContactMethodResponse)
    def restore_contact(party_id: str, method_id: str):
        ready(True)
        return invoke(lambda: service.restore_contact(party_id, method_id).to_dict())

    @router.post("/{party_id}/archive", response_model=TenantResponse)
    def archive(party_id: str, data: ConfirmationRequest):
        ready(True)
        return invoke(lambda: service.archive(party_id, confirmed=data.confirmed))

    @router.post("/{party_id}/restore", response_model=TenantResponse)
    def restore(party_id: str):
        ready(True)
        return invoke(lambda: service.restore(party_id))

    return router

"""Typed local tenant contact API."""

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from app.modules.parties.application.service import PartyValidationError

from app.modules.tenants.application.service import (
    PossibleDuplicatePartyError,
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
    extension: str | None = Field(None, max_length=6)
    label: str | None = Field(None, max_length=80)


class TenantCreateRequest(Contract):
    partyKind: Literal["individual", "organization"]
    displayName: str = Field(min_length=1, max_length=240)
    contacts: list[ContactRequest] = Field(default_factory=list)
    notes: str | None = Field(None, max_length=4000)
    doNotContact: StrictBool = False
    confirmedNewParty: StrictBool = False


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
    extension: str | None
    label: str | None
    status: Literal["active", "archived"]
    createdAt: str
    updatedAt: str
    archivedAt: str | None


class TenantResponse(Contract):
    id: str
    partyKind: Literal["individual", "organization"]
    displayName: str
    createdAt: str
    updatedAt: str
    archivedAt: str | None
    profile: TenantProfileResponse
    contactMethods: list[ContactMethodResponse]


class PossibleDuplicateDetail(Contract):
    code: Literal["possible_duplicate_party"]
    candidatePartyIds: list[str] = Field(max_length=10)


class PossibleDuplicateResponse(Contract):
    detail: PossibleDuplicateDetail


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
        except PossibleDuplicatePartyError as error:
            raise HTTPException(409, detail={
                "code": "possible_duplicate_party",
                "candidatePartyIds": error.candidate_party_ids,
            }) from error
        except TenantConflictError as error:
            raise HTTPException(409, str(error)) from error
        except TenantError as error:
            raise HTTPException(400, str(error)) from error
        except PartyValidationError as error:
            raise HTTPException(400, str(error)) from error

    @router.post("", status_code=status.HTTP_201_CREATED, response_model=TenantResponse,
                 responses={409: {"model": PossibleDuplicateResponse}})
    def create(data: TenantCreateRequest):
        ready(True)
        from app.modules.parties.application.service import ContactMethodCommand
        return invoke(lambda: service.create(TenantCreateCommand(
            party_kind=data.partyKind,
            display_name=data.displayName,
            contacts=tuple(ContactMethodCommand(item.methodKind, item.value, item.extension, item.label)
                           for item in data.contacts),
            notes=data.notes,
            do_not_contact=data.doNotContact,
            confirmed_new_party=data.confirmedNewParty,
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

    @router.post("/{party_id}/archive", response_model=TenantResponse)
    def archive(party_id: str, data: ConfirmationRequest):
        ready(True)
        return invoke(lambda: service.archive(party_id, confirmed=data.confirmed))

    @router.post("/{party_id}/restore", response_model=TenantResponse)
    def restore(party_id: str):
        ready(True)
        return invoke(lambda: service.restore(party_id))

    return router

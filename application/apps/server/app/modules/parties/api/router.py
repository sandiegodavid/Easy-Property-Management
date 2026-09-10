"""Shared party contact API."""

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.modules.parties.application.service import (
    ContactReferenceResolution,
    ContactMethodCommand,
    PartyConflictError,
    PartyContactService,
    PartyIdentityService,
    PartyNotFoundError,
    PartyCreateCommand,
    PartyPatchCommand,
    PossibleDuplicatePartyError,
    PartyValidationError,
)
from app.modules.workspace.application.runtime import WorkspaceRuntime


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContactRequest(Contract):
    methodKind: Literal["email", "phone"]
    value: str = Field(min_length=1, max_length=320)
    extension: str | None = Field(None, max_length=6)
    label: str | None = Field(None, max_length=80)


class ReferenceResolution(Contract):
    role: str
    roleRecordId: str
    replacementContactMethodId: str | None = None
    clear: StrictBool = False

    @model_validator(mode="after")
    def exact_resolution(self):
        if (self.replacementContactMethodId is None) == (self.clear is False):
            raise ValueError("Choose exactly one replacement contact or explicit clear action.")
        return self


class ArchiveRequest(Contract):
    confirmed: StrictBool
    referenceResolutions: list[ReferenceResolution] = Field(default_factory=list, max_length=20)


class ContactResponse(Contract):
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


class PartyRequest(Contract):
    partyKind: Literal["individual", "organization"]
    displayName: str = Field(min_length=1, max_length=240)
    contacts: list[ContactRequest] = Field(default_factory=list)
    confirmedNewParty: StrictBool = False


class PartyPatchRequest(Contract):
    displayName: str = Field(min_length=1, max_length=240)


class PartyResponse(Contract):
    id: str
    partyKind: Literal["individual", "organization"]
    displayName: str
    createdAt: str
    updatedAt: str
    archivedAt: str | None
    contactMethods: list[ContactResponse] = Field(default_factory=list)
    activeRoles: list[Literal["tenant", "provider", "client_owner"]] = Field(default_factory=list)


def build_router(identity: PartyIdentityService, service: PartyContactService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(prefix="/api/parties", tags=["parties"])

    def ready(write: bool = False) -> None:
        if not runtime.ready or runtime.error:
            raise HTTPException(503, str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:
            raise HTTPException(503, "Workspace writer lock is unavailable.")

    def invoke(operation):
        try:
            return operation()
        except PartyNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except PartyConflictError as error:
            raise HTTPException(409, str(error)) from error
        except PartyValidationError as error:
            raise HTTPException(400, str(error)) from error

    def party_view(record) -> dict[str, object]:
        party, methods = record
        return {**party.to_dict(), "contactMethods": [item.to_dict() for item in methods], "activeRoles": identity.active_roles(party.id)}

    @router.post("", response_model=PartyResponse, status_code=status.HTTP_201_CREATED)
    def create_party(data: PartyRequest):
        ready(True)
        def create() -> dict[str, object]:
            party = identity.create(
                PartyCreateCommand(data.partyKind, data.displayName),
                contacts=tuple(_command(item) for item in data.contacts),
                confirmed_new_party=data.confirmedNewParty,
            )
            return party_view(identity.get(party.id))
        try:
            return create()
        except PossibleDuplicatePartyError as error:
            raise HTTPException(409, {"code": "possible_duplicate_party", "candidatePartyIds": error.candidate_party_ids}) from error
        except PartyConflictError as error:
            raise HTTPException(409, str(error)) from error
        except PartyValidationError as error:
            raise HTTPException(400, str(error)) from error

    @router.get("", response_model=list[PartyResponse])
    def list_parties(archiveState: Literal["active", "archived", "all"] = "active", search: str | None = None):
        ready()
        return invoke(lambda: [party_view(item) for item in identity.list(archive_state=archiveState, search=search)])

    @router.get("/{party_id}", response_model=PartyResponse)
    def get_party(party_id: str):
        ready(); return invoke(lambda: party_view(identity.get(party_id)))

    @router.patch("/{party_id}", response_model=PartyResponse)
    def patch_party(party_id: str, data: PartyPatchRequest):
        ready(True)
        return invoke(lambda: party_view(identity.get(identity.patch(party_id, PartyPatchCommand(data.displayName)).id)))

    @router.post("/{party_id}/archive", response_model=PartyResponse)
    def archive_party(party_id: str, data: "ArchiveRequest"):
        ready(True)
        return invoke(lambda: party_view(identity.get(identity.archive(party_id, confirmed=data.confirmed).id)))

    @router.post("/{party_id}/restore", response_model=PartyResponse)
    def restore_party(party_id: str):
        ready(True)
        return invoke(lambda: party_view(identity.get(identity.restore(party_id).id)))

    @router.get("/{party_id}/contact-methods", response_model=list[ContactResponse])
    def list_contacts(party_id: str):
        ready()
        return invoke(lambda: service.list(party_id))

    @router.post("/{party_id}/contact-methods", status_code=status.HTTP_201_CREATED,
                 response_model=ContactResponse)
    def add_contact(party_id: str, data: ContactRequest):
        ready(True)
        return invoke(lambda: service.add(party_id, _command(data)))

    @router.patch("/{party_id}/contact-methods/{method_id}", response_model=ContactResponse)
    def update_contact(party_id: str, method_id: str, data: ContactRequest):
        ready(True)
        return invoke(lambda: service.update(party_id, method_id, _command(data)))

    @router.post("/{party_id}/contact-methods/{method_id}/archive", response_model=ContactResponse)
    def archive_contact(party_id: str, method_id: str, data: ArchiveRequest):
        ready(True)
        return invoke(lambda: service.archive(
            party_id, method_id, confirmed=data.confirmed,
            reference_resolutions=tuple(ContactReferenceResolution(
                item.role, item.roleRecordId, item.replacementContactMethodId, item.clear
            ) for item in data.referenceResolutions),
        ))

    @router.post("/{party_id}/contact-methods/{method_id}/restore", response_model=ContactResponse)
    def restore_contact(party_id: str, method_id: str):
        ready(True)
        return invoke(lambda: service.restore(party_id, method_id))

    return router


def _command(data: ContactRequest) -> ContactMethodCommand:
    return ContactMethodCommand(data.methodKind, data.value, data.extension, data.label)

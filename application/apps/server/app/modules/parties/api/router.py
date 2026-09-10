"""Shared party contact API."""

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.modules.parties.application.service import (
    ContactReferenceResolution,
    ContactMethodCommand,
    PartyConflictError,
    PartyContactService,
    PartyNotFoundError,
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


def build_router(service: PartyContactService, runtime: WorkspaceRuntime) -> APIRouter:
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

"""Shared party contact API."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

from app.modules.parties.application.service import (
    ContactMethodCommand,
    ContactReferenceResolution,
    PartyConflictError,
    PartyContactService,
    PartyCreateCommand,
    PartyIdentityService,
    PartyNotFoundError,
    PartyPatchCommand,
    PartyValidationError,
    PossibleDuplicatePartyError,
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
    role: str = Field(min_length=1)
    roleRecordId: UUID
    replacementContactMethodId: UUID | None = None
    clear: StrictBool = False
    expectedTenantRevision: StrictInt | None = Field(None, ge=1)

    @model_validator(mode="after")
    def exact_resolution(self):
        if (self.role == "tenant") != (self.expectedTenantRevision is not None):
            raise ValueError(
                "Tenant resolutions require expectedTenantRevision; other roles must omit it."
            )
        if (self.replacementContactMethodId is None) == (self.clear is False):
            raise ValueError("Choose exactly one replacement contact or explicit clear action.")
        return self


class ArchiveRequest(Contract):
    expectedRevision: StrictInt = Field(ge=1)
    idempotencyKey: UUID
    confirmed: StrictBool
    referenceResolutions: list[ReferenceResolution] = Field(default_factory=list, max_length=20)


class ContactResponse(Contract):
    id: UUID
    partyId: UUID
    methodKind: Literal["email", "phone"]
    displayValue: str
    extension: str | None
    label: str | None
    status: Literal["active", "archived"]
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    archivedAt: AwareDatetime | None


class IdentityConcurrency(Contract):
    expectedRevision: StrictInt = Field(ge=0)
    idempotencyKey: UUID


class ContactConcurrency(IdentityConcurrency):
    expectedRevision: StrictInt = Field(ge=1)


class ContactMutationRequest(ContactRequest, ContactConcurrency):
    pass


class ContactMutationResponse(ContactResponse):
    revision: StrictInt = Field(ge=1)
    operationId: UUID


class PartyRequest(IdentityConcurrency):
    partyKind: Literal["individual", "organization"]
    displayName: str = Field(min_length=1, max_length=240)
    contacts: list[ContactRequest] = Field(default_factory=list)
    confirmedNewParty: StrictBool = False


class PartyPatchRequest(IdentityConcurrency):
    displayName: str = Field(min_length=1, max_length=240)


class PartyState(Contract):
    id: UUID
    partyKind: Literal["individual", "organization"]
    displayName: str
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    archivedAt: AwareDatetime | None
    revision: StrictInt = Field(ge=1)


class PartyResponse(PartyState):
    contactMethods: list[ContactResponse] = Field(default_factory=list)
    activeRoles: list[Literal["tenant", "provider", "client_owner"]] = Field(default_factory=list)


class PartyMutationResponse(PartyState):
    operationId: UUID


class IdentityArchiveRequest(IdentityConcurrency):
    confirmed: StrictBool


class TenantPreferenceState(Contract):
    partyId: UUID
    preferredContactMethodId: UUID | None
    doNotContact: StrictBool
    notes: str | None
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    archivedAt: AwareDatetime | None
    revision: StrictInt = Field(ge=1)


class PartyConflictDetail(Contract):
    code: str
    message: str
    current: PartyState | None = None
    candidatePartyIds: list[UUID] = Field(default_factory=list, max_length=10)
    currentTenant: TenantPreferenceState | None = None


class PartyConflictResponse(Contract):
    detail: PartyConflictDetail


def build_router(
    identity: PartyIdentityService, service: PartyContactService, runtime: WorkspaceRuntime
) -> APIRouter:
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
            raise HTTPException(
                409,
                {
                    "code": error.code,
                    "message": str(error),
                    "current": error.current,
                    "currentTenant": TenantPreferenceState.model_validate(
                        error.current_tenant
                    ).model_dump(mode="json")
                    if error.current_tenant
                    else None,
                },
            ) from error
        except PartyValidationError as error:
            raise HTTPException(400, str(error)) from error

    def party_view(record) -> dict[str, object]:
        party, methods = record
        return {
            **party.identity_snapshot(),
            "contactMethods": [item.to_dict() for item in methods],
            "activeRoles": identity.active_roles(party.id),
        }

    @router.post(
        "",
        response_model=PartyMutationResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createParty",
        responses={409: {"model": PartyConflictResponse}},
    )
    def create_party(data: PartyRequest):
        ready(True)

        def create() -> dict[str, object]:
            return identity.create(
                PartyCreateCommand(data.partyKind, data.displayName),
                contacts=tuple(_command(item) for item in data.contacts),
                confirmed_new_party=data.confirmedNewParty,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )

        try:
            return create()
        except PossibleDuplicatePartyError as error:
            raise HTTPException(
                409,
                {
                    "code": "possible_duplicate_party",
                    "message": str(error),
                    "candidatePartyIds": error.candidate_party_ids,
                },
            ) from error
        except PartyConflictError as error:
            raise HTTPException(
                409, {"code": error.code, "message": str(error), "current": error.current}
            ) from error
        except PartyValidationError as error:
            raise HTTPException(400, str(error)) from error

    @router.get("", response_model=list[PartyResponse], operation_id="listParties")
    def list_parties(
        archiveState: Literal["active", "archived", "all"] = "active", search: str | None = None
    ):
        ready()
        return invoke(
            lambda: [
                party_view(item)
                for item in identity.list(archive_state=archiveState, search=search)
            ]
        )

    @router.get(
        "/operations/by-key/{key}",
        response_model=PartyMutationResponse | ContactMutationResponse,
        operation_id="getPartyOperationByKey",
    )
    def operation_by_key(key: UUID):
        ready()
        return invoke(lambda: identity.recovery(key=str(key)))

    @router.get(
        "/operations/{operation_id}",
        response_model=PartyMutationResponse | ContactMutationResponse,
        operation_id="getPartyOperation",
    )
    def operation_by_id(operation_id: UUID):
        ready()
        return invoke(lambda: identity.recovery(operation_id=str(operation_id)))

    @router.get("/{party_id}", response_model=PartyResponse, operation_id="getParty")
    def get_party(party_id: UUID):
        ready()
        return invoke(lambda: party_view(identity.get(str(party_id))))

    @router.patch(
        "/{party_id}",
        response_model=PartyMutationResponse,
        operation_id="patchParty",
        responses={409: {"model": PartyConflictResponse}},
    )
    def patch_party(party_id: UUID, data: PartyPatchRequest):
        ready(True)
        return invoke(
            lambda: identity.patch(
                str(party_id),
                PartyPatchCommand(data.displayName),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/{party_id}/archive",
        response_model=PartyMutationResponse,
        operation_id="archiveParty",
        responses={409: {"model": PartyConflictResponse}},
    )
    def archive_party(party_id: UUID, data: IdentityArchiveRequest):
        ready(True)
        return invoke(
            lambda: identity.archive(
                str(party_id),
                confirmed=data.confirmed,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/{party_id}/restore",
        response_model=PartyMutationResponse,
        operation_id="restoreParty",
        responses={409: {"model": PartyConflictResponse}},
    )
    def restore_party(party_id: UUID, data: IdentityConcurrency):
        ready(True)
        return invoke(
            lambda: identity.restore(
                str(party_id),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.get(
        "/{party_id}/contact-methods",
        response_model=list[ContactResponse],
        operation_id="listPartyContactMethods",
    )
    def list_contacts(party_id: UUID):
        ready()
        return invoke(lambda: service.list(str(party_id)))

    @router.post(
        "/{party_id}/contact-methods",
        status_code=status.HTTP_201_CREATED,
        response_model=ContactMutationResponse,
        operation_id="addPartyContactMethod",
        responses={409: {"model": PartyConflictResponse}},
    )
    def add_contact(party_id: UUID, data: ContactMutationRequest):
        ready(True)
        return invoke(
            lambda: service.add(
                str(party_id),
                _command(data),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.patch(
        "/{party_id}/contact-methods/{method_id}",
        response_model=ContactMutationResponse,
        operation_id="updatePartyContactMethod",
        responses={409: {"model": PartyConflictResponse}},
    )
    def update_contact(party_id: UUID, method_id: UUID, data: ContactMutationRequest):
        ready(True)
        return invoke(
            lambda: service.update(
                str(party_id),
                str(method_id),
                _command(data),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/{party_id}/contact-methods/{method_id}/archive",
        response_model=ContactMutationResponse,
        operation_id="archivePartyContactMethod",
        responses={409: {"model": PartyConflictResponse}},
    )
    def archive_contact(party_id: UUID, method_id: UUID, data: ArchiveRequest):
        ready(True)
        return invoke(
            lambda: service.archive(
                str(party_id),
                str(method_id),
                confirmed=data.confirmed,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
                reference_resolutions=tuple(
                    ContactReferenceResolution(
                        item.role,
                        str(item.roleRecordId),
                        str(item.replacementContactMethodId)
                        if item.replacementContactMethodId
                        else None,
                        item.clear,
                        item.expectedTenantRevision,
                    )
                    for item in data.referenceResolutions
                ),
            )
        )

    @router.post(
        "/{party_id}/contact-methods/{method_id}/restore",
        response_model=ContactMutationResponse,
        operation_id="restorePartyContactMethod",
        responses={409: {"model": PartyConflictResponse}},
    )
    def restore_contact(party_id: UUID, method_id: UUID, data: ContactConcurrency):
        ready(True)
        return invoke(
            lambda: service.restore(
                str(party_id),
                str(method_id),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    return router


def _command(data: ContactRequest) -> ContactMethodCommand:
    return ContactMethodCommand(data.methodKind, data.value, data.extension, data.label)

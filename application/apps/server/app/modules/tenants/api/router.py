"""Typed local tenant contact API."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, AwareDatetime

from app.platform.api_errors import domain_problem, workspace_unavailable

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


class ConcurrencyRequest(Contract):
    expectedRevision: StrictInt = Field(ge=0)
    idempotencyKey: UUID


class ExistingRequest(ConcurrencyRequest):
    expectedRevision: StrictInt = Field(ge=1)


class TenantCreateRequest(ConcurrencyRequest):
    partyKind: Literal["individual", "organization"]
    displayName: str = Field(min_length=1, max_length=240)
    contacts: list[ContactRequest] = Field(default_factory=list)
    notes: str | None = Field(None, max_length=4000)
    doNotContact: StrictBool = False
    confirmedNewParty: StrictBool = False


class DesignateRequest(ConcurrencyRequest):
    notes: str | None = Field(None, max_length=4000)


class ProfilePatchRequest(ExistingRequest):
    preferredContactMethodId: UUID | None = None
    doNotContact: StrictBool = False
    notes: str | None = Field(None, max_length=4000)

    def command(self) -> TenantProfilePatchCommand:
        return TenantProfilePatchCommand.from_mapping(
            {
                field: str(value) if isinstance(value := getattr(self, field), UUID) else value
                for field in self.model_fields_set - {"expectedRevision", "idempotencyKey"}
            }
        )


class ConfirmationRequest(ExistingRequest):
    confirmed: StrictBool


class TenantProfileResponse(Contract):
    revision: StrictInt = Field(ge=1)
    partyId: UUID
    preferredContactMethodId: UUID | None
    doNotContact: bool
    notes: str | None
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    archivedAt: AwareDatetime | None


class ContactMethodResponse(Contract):
    id: str
    partyId: str
    methodKind: Literal["email", "phone"]
    displayValue: str
    extension: str | None
    label: str | None
    status: Literal["active", "archived"]
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    archivedAt: AwareDatetime | None


class TenantResponse(Contract):
    revision: StrictInt = Field(ge=1)
    partyRevision: StrictInt = Field(ge=1)
    id: str
    partyKind: Literal["individual", "organization"]
    displayName: str
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    archivedAt: AwareDatetime | None
    profile: TenantProfileResponse
    contactMethods: list[ContactMethodResponse]


class TenantMutationResponse(TenantResponse):
    operationId: UUID


class ProfileMutationResponse(TenantProfileResponse):
    operationId: UUID


class ConflictDetail(Contract):
    code: str
    message: str
    current: TenantProfileResponse | None = None
    candidatePartyIds: list[UUID] = Field(default_factory=list, max_length=10)


class ConflictResponse(Contract):
    detail: ConflictDetail


def build_router(service: TenantService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(prefix="/api/tenants", tags=["tenants"])

    def ready(write: bool = False) -> None:
        if not runtime.ready or runtime.error:
            raise workspace_unavailable(str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:
            raise workspace_unavailable("Workspace writer lock is unavailable.")

    def invoke(operation):
        try:
            return operation()
        except TenantNotFoundError as error:
            raise domain_problem(error, status_code=404, code="tenant_not_found") from error
        except PossibleDuplicatePartyError as error:
            raise domain_problem(
                error,
                status_code=409,
                code="possible_duplicate_party",
                candidatePartyIds=error.candidate_party_ids,
            ) from error
        except TenantConflictError as error:
            raise domain_problem(
                error,
                status_code=409,
                code=error.code,
                current=TenantProfileResponse.model_validate(error.current).model_dump(mode="json")
                if error.current
                else None,
            ) from error
        except TenantError as error:
            raise domain_problem(error, status_code=400, code="tenant_validation") from error
        except PartyValidationError as error:
            raise domain_problem(error, status_code=400, code="tenant_validation") from error

    @router.post(
        "",
        operation_id="create_tenant",
        status_code=status.HTTP_201_CREATED,
        response_model=TenantMutationResponse,
        responses={409: {"model": ConflictResponse}},
    )
    def create(data: TenantCreateRequest):
        ready(True)
        from app.modules.parties.application.service import ContactMethodCommand

        return invoke(
            lambda: service.create(
                TenantCreateCommand(
                    party_kind=data.partyKind,
                    display_name=data.displayName,
                    contacts=tuple(
                        ContactMethodCommand(
                            item.methodKind, item.value, item.extension, item.label
                        )
                        for item in data.contacts
                    ),
                    notes=data.notes,
                    do_not_contact=data.doNotContact,
                    confirmed_new_party=data.confirmedNewParty,
                ),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/from-party/{party_id}",
        operation_id="designate_party_as_tenant",
        status_code=status.HTTP_201_CREATED,
        response_model=TenantMutationResponse,
        responses={409: {"model": ConflictResponse}},
    )
    def designate(party_id: UUID, data: DesignateRequest):
        ready(True)
        return invoke(
            lambda: service.designate(
                str(party_id),
                notes=data.notes,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.get("", operation_id="list_tenants", response_model=list[TenantResponse])
    def list_tenants(
        archiveState: Literal["active", "archived", "all"] = "active", search: str | None = None
    ):
        ready()
        return invoke(lambda: service.list(archive_state=archiveState, search=search))

    @router.get(
        "/operations/by-key/{key}",
        operation_id="get_tenant_operation_by_key",
        response_model=TenantMutationResponse | ProfileMutationResponse,
    )
    def recover_key(key: UUID):
        ready()
        return invoke(lambda: service.recover(key=str(key)))

    @router.get(
        "/operations/{operation_id}",
        operation_id="get_tenant_operation",
        response_model=TenantMutationResponse | ProfileMutationResponse,
    )
    def recover_id(operation_id: UUID):
        ready()
        return invoke(lambda: service.recover(operation_id=str(operation_id)))

    @router.get("/{party_id}", operation_id="get_tenant", response_model=TenantResponse)
    def get(party_id: UUID):
        ready()
        return invoke(lambda: service.get(str(party_id)))

    @router.patch(
        "/{party_id}",
        operation_id="update_tenant_profile",
        response_model=TenantMutationResponse,
        responses={409: {"model": ConflictResponse}},
    )
    def update(party_id: UUID, data: ProfilePatchRequest):
        ready(True)
        return invoke(
            lambda: service.update_profile(
                str(party_id),
                data.command(),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/{party_id}/archive",
        operation_id="archive_tenant",
        response_model=TenantMutationResponse,
        responses={409: {"model": ConflictResponse}},
    )
    def archive(party_id: UUID, data: ConfirmationRequest):
        ready(True)
        return invoke(
            lambda: service.archive(
                str(party_id),
                confirmed=data.confirmed,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/{party_id}/restore",
        operation_id="restore_tenant",
        response_model=TenantMutationResponse,
        responses={409: {"model": ConflictResponse}},
    )
    def restore(party_id: UUID, data: ExistingRequest):
        ready(True)
        return invoke(
            lambda: service.restore(
                str(party_id),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    return router

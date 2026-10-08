"""Typed provider HTTP contract."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    AwareDatetime,
    model_validator,
)

from app.platform.api_errors import domain_problem, workspace_unavailable

from app.modules.parties.application.service import (
    ContactMethodCommand,
    PartyCreateCommand,
    PartyValidationError,
)
from app.modules.vendors.application.service import (
    UNSET,
    PossibleDuplicateParty,
    ProviderError,
    ProviderCategoryCommand,
    ProviderCategoryAssignmentCommand,
    ProviderCategoryIdempotencyConflict,
    ProviderCategoryPatchCommand,
    ProviderLifecycleConflict,
    ProviderNotFoundError,
    ProviderProfileCommand,
    ProviderProfilePatchCommand,
    ProviderSearchCommand,
    ProviderService,
    ReferenceCommand,
    ReputationLinkCommand,
    ReputationLinkPatchCommand,
    ServiceAreaCommand,
    ServiceCommand,
    WorkHistoryCommand,
    canonical_reputation_url,
)
from app.modules.workspace.application.runtime import WorkspaceRuntime


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PartyInput(Contract):
    partyKind: Literal["individual", "organization"]
    displayName: str = Field(min_length=1, max_length=240)


class ContactInput(Contract):
    methodKind: Literal["email", "phone"]
    value: str = Field(min_length=1, max_length=320)
    extension: str | None = Field(None, max_length=6)
    label: str | None = Field(None, max_length=80)


class ProfileInput(Contract):
    selectionStatus: Literal["neutral", "preferred", "avoid"] = "neutral"
    selectionReason: str | None = Field(None, max_length=1000)
    notes: str | None = Field(None, max_length=4000)


class ProviderConcurrency(Contract):
    expectedRevision: StrictInt = Field(ge=0)
    idempotencyKey: UUID


class ExistingProviderConcurrency(ProviderConcurrency):
    expectedRevision: StrictInt = Field(ge=1)


class DesignateInput(ProfileInput, ProviderConcurrency):
    pass


class ProviderArchiveInput(ExistingProviderConcurrency):
    confirmed: StrictBool


class CreateProviderInput(ProfileInput, ProviderConcurrency):
    party: PartyInput
    contacts: list[ContactInput] = Field(default_factory=list)
    services: list["ServiceInput"] = Field(default_factory=list)
    serviceAreas: list["AreaInput"] = Field(default_factory=list)
    workHistory: list["WorkInput"] = Field(default_factory=list)
    references: list["ReferenceInput"] = Field(default_factory=list)
    categoryIds: list[UUID] = Field(default_factory=list)
    confirmedNewParty: StrictBool = False


class ProfilePatchInput(ExistingProviderConcurrency):
    selectionStatus: Literal["neutral", "preferred", "avoid"] | None = None
    selectionReason: str | None = Field(None, max_length=1000)
    notes: str | None = Field(None, max_length=4000)

    @model_validator(mode="after")
    def require_non_null_selection_status_when_supplied(self):
        if "selectionStatus" in self.model_fields_set and self.selectionStatus is None:
            raise ValueError("selectionStatus cannot be null.")
        return self


class ServiceInput(Contract):
    displayName: str = Field(min_length=1, max_length=160)


class AreaInput(ServiceInput):
    countryCode: str | None = Field(None, min_length=2, max_length=2)


class WorkInput(Contract):
    performedOn: date
    summary: str = Field(min_length=1, max_length=1000)
    propertyId: UUID | None = None
    outcomeNotes: str | None = Field(None, max_length=4000)


class ReferenceInput(Contract):
    referenceName: str | None = Field(None, max_length=240)
    organizationName: str | None = Field(None, max_length=240)
    relationship: str | None = Field(None, max_length=240)
    email: str | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=320)
    notes: str | None = Field(None, max_length=4000)


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
                self.sourceKind,
                self.url,
                self.sourceName,
                self.notes,
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
        if (
            "lastCheckedOn" in fields
            and self.lastCheckedOn is not None
            and self.lastCheckedOn > date.today()
        ):
            raise ValueError("lastCheckedOn cannot be in the future.")
        return self


class ServiceMutationInput(ServiceInput, ExistingProviderConcurrency):
    pass


class AreaMutationInput(AreaInput, ExistingProviderConcurrency):
    pass


class WorkMutationInput(WorkInput, ExistingProviderConcurrency):
    pass


class ReferenceMutationInput(ReferenceInput, ExistingProviderConcurrency):
    pass


class ReputationMutationInput(ReputationLinkInput, ExistingProviderConcurrency):
    pass


class ReputationPatchMutationInput(ReputationLinkPatchInput, ExistingProviderConcurrency):
    pass


class Confirmation(Contract):
    confirmed: StrictBool


class ArchiveConfirmation(Confirmation):
    reason: str = Field(min_length=1, max_length=1000)


class CategoryInput(ProviderConcurrency):
    displayName: str = Field(min_length=1, max_length=160)
    description: str | None = Field(None, max_length=1000)
    displayOrder: int = Field(ge=0, strict=True)
    idempotencyKey: UUID


class CategoryPatchInput(ExistingProviderConcurrency):
    displayName: str | None = Field(None, min_length=1, max_length=160)
    description: str | None = Field(None, max_length=1000)
    displayOrder: int | None = Field(None, ge=0, strict=True)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set & {"displayName", "description", "displayOrder"}:
            raise ValueError("Category patch cannot be empty.")
        return self


class CategoryAssignmentInput(ExistingProviderConcurrency):
    categoryId: UUID
    expectedCategoryRevision: StrictInt = Field(ge=1)


class AssignmentArchiveInput(ArchiveConfirmation, ExistingProviderConcurrency):
    pass


class AssignmentRestoreInput(ExistingProviderConcurrency):
    confirmed: StrictBool
    expectedCategoryRevision: StrictInt = Field(ge=1)


class CategoryLifecycleInput(ArchiveConfirmation, ExistingProviderConcurrency):
    pass


class CategoryRestoreInput(Confirmation, ExistingProviderConcurrency):
    pass


class PartyResponse(Contract):
    id: str
    partyKind: Literal["individual", "organization"]
    displayName: str
    createdAt: str
    updatedAt: str
    archivedAt: str | None


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


class ProfileResponse(Contract):
    revision: StrictInt = Field(ge=1)
    partyId: UUID
    selectionStatus: Literal["neutral", "preferred", "avoid"]
    selectionReason: str | None
    notes: str | None
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    archivedAt: AwareDatetime | None


class ServiceResponse(Contract):
    id: str
    partyId: str
    displayName: str
    normalizedName: str
    createdAt: str
    updatedAt: str
    archivedAt: str | None


class AreaResponse(ServiceResponse):
    countryCode: str | None


class WorkResponse(Contract):
    id: str
    partyId: str
    propertyId: str | None
    performedOn: date
    summary: str
    outcomeNotes: str | None
    createdAt: str
    updatedAt: str
    archivedAt: str | None


class ReferenceResponse(Contract):
    id: str
    partyId: str
    referenceName: str | None
    organizationName: str | None
    relationship: str | None
    email: str | None
    phone: str | None
    notes: str | None
    createdAt: str
    updatedAt: str
    archivedAt: str | None


class ReputationLinkResponse(Contract):
    id: str
    partyId: str
    sourceKind: Literal["google", "yelp", "angi", "other"]
    sourceName: str | None
    normalizedSourceKey: str
    url: str
    normalizedUrl: str
    notes: str | None
    lastCheckedOn: date | None
    createdAt: str
    updatedAt: str
    archivedAt: str | None


class CategorySnapshotResponse(Contract):
    revision: StrictInt = Field(ge=1)
    id: UUID
    displayName: str
    normalizedName: str
    description: str | None
    displayOrder: StrictInt = Field(ge=0)
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    archivedAt: AwareDatetime | None
    archiveReason: str | None


class CategoryResponse(CategorySnapshotResponse):
    effectiveProviderCount: StrictInt = Field(ge=0)


class CategoryMutationResponse(Contract):
    category: CategoryResponse
    revision: StrictInt = Field(ge=1)
    operationId: UUID


class ProviderCategoryResponse(CategoryResponse):
    assignmentId: str
    assignmentArchivedAt: str | None
    assignmentArchiveReason: str | None
    effectiveProviderCount: int = 0


class ProviderResponse(Contract):
    party: PartyResponse
    profile: ProfileResponse
    contactMethods: list[ContactResponse]
    services: list[ServiceResponse]
    serviceAreas: list[AreaResponse]
    workHistory: list[WorkResponse]
    references: list[ReferenceResponse]
    reputationLinks: list[ReputationLinkResponse]
    categories: list[ProviderCategoryResponse]


class ProviderMutationResponse(Contract):
    party: PartyResponse
    profile: ProfileResponse
    revision: StrictInt = Field(ge=1)
    partyRevision: StrictInt = Field(ge=1)
    operationId: UUID


class AssignmentResponse(Contract):
    id: UUID
    providerPartyId: UUID
    categoryId: UUID
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    archivedAt: AwareDatetime | None
    archiveReason: str | None


class ProviderChildResult(Contract):
    profile: ProfileResponse
    revision: StrictInt = Field(ge=1)
    operationId: UUID


class ServiceMutationResponse(ProviderChildResult):
    kind: Literal["service"]
    item: ServiceResponse


class AreaMutationResponse(ProviderChildResult):
    kind: Literal["area"]
    item: AreaResponse


class WorkMutationResponse(ProviderChildResult):
    kind: Literal["work"]
    item: WorkResponse


class ReferenceMutationResponse(ProviderChildResult):
    kind: Literal["reference"]
    item: ReferenceResponse


class ReputationMutationResponse(ProviderChildResult):
    kind: Literal["reputation"]
    item: ReputationLinkResponse


class AssignmentMutationResponse(ProviderChildResult):
    kind: Literal["assignment"]
    item: AssignmentResponse
    category: CategorySnapshotResponse


ProviderChildMutationResponse = Annotated[
    ServiceMutationResponse
    | AreaMutationResponse
    | WorkMutationResponse
    | ReferenceMutationResponse
    | ReputationMutationResponse
    | AssignmentMutationResponse,
    Field(discriminator="kind"),
]


ProviderOperationResponse = ProviderMutationResponse | ProviderChildMutationResponse


class ProviderConflictDetail(Contract):
    code: str
    message: str
    current: ProfileResponse | CategorySnapshotResponse | None = None
    candidatePartyIds: list[UUID] = Field(default_factory=list, max_length=10)


class ProviderConflictResponse(Contract):
    detail: ProviderConflictDetail


class ProviderListResponse(Contract):
    party: PartyResponse
    profile: ProfileResponse
    services: list[ServiceResponse]
    serviceAreas: list[AreaResponse]
    workHistoryCount: int
    referenceCount: int
    reputationLinkCount: int
    categories: list[ProviderCategoryResponse]


class ProviderPageResponse(Contract):
    items: list[ProviderListResponse]
    nextCursor: str | None


def build_router(provider_service: ProviderService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(prefix="/api/providers", tags=["providers"])

    def ready(write=False):
        if not runtime.ready or runtime.error:
            raise workspace_unavailable(str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:
            raise workspace_unavailable("Workspace writer lock is unavailable.")

    def invoke(operation):
        try:
            return operation()
        except ProviderNotFoundError as error:
            raise domain_problem(error, status_code=404, code="provider_not_found") from error
        except PossibleDuplicateParty as error:
            raise domain_problem(
                error,
                status_code=409,
                code="possible_duplicate_party",
                candidatePartyIds=error.candidate_party_ids,
            ) from error
        except ProviderCategoryIdempotencyConflict as error:
            raise domain_problem(
                error, status_code=409, code="provider_category_idempotency_conflict"
            ) from error
        except ProviderLifecycleConflict as error:
            raise domain_problem(
                error,
                status_code=409,
                code=error.code,
                current=(
                    ProfileResponse if "partyId" in error.current else CategorySnapshotResponse
                )
                .model_validate(error.current)
                .model_dump(mode="json")
                if error.current
                else None,
            ) from error
        except (ProviderError, PartyValidationError) as error:
            raise domain_problem(error, status_code=400, code="provider_validation") from error

    @router.post(
        "",
        operation_id="create_provider",
        response_model=ProviderMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
        status_code=status.HTTP_201_CREATED,
    )
    def create(data: CreateProviderInput):
        ready(True)
        return invoke(
            lambda: provider_service.create(
                PartyCreateCommand(data.party.partyKind, data.party.displayName),
                _profile(data),
                contacts=tuple(_contact(item) for item in data.contacts),
                services=tuple(ServiceCommand(item.displayName) for item in data.services),
                areas=tuple(
                    ServiceAreaCommand(item.displayName, item.countryCode)
                    for item in data.serviceAreas
                ),
                work_history=tuple(
                    WorkHistoryCommand(
                        item.performedOn.isoformat(),
                        item.summary,
                        str(item.propertyId) if item.propertyId else None,
                        item.outcomeNotes,
                    )
                    for item in data.workHistory
                ),
                references=tuple(_command(item) for item in data.references),
                category_ids=tuple(str(item) for item in data.categoryIds),
                confirmed_new_party=data.confirmedNewParty,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/from-party/{party_id}",
        operation_id="designate_party_as_provider",
        response_model=ProviderMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
        status_code=status.HTTP_201_CREATED,
    )
    def designate(party_id: UUID, data: DesignateInput):
        ready(True)
        return invoke(
            lambda: provider_service.designate(
                str(party_id),
                _profile(data),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.get("", operation_id="list_providers", response_model=ProviderPageResponse)
    def list_providers(
        archiveState: Literal["active", "archived", "all"] = "active",
        search: str | None = Query(None, max_length=240),
        service: str | None = Query(None, max_length=160),
        serviceArea: str | None = Query(None, max_length=160),
        selectionStatus: Literal["neutral", "preferred", "avoid"] | None = None,
        propertyId: UUID | None = None,
        hasReference: bool | None = None,
        categoryId: UUID | None = None,
        categoryState: Literal["categorized", "uncategorized"] | None = None,
        limit: int = Query(100, ge=1, le=200),
        cursor: str | None = None,
    ):
        ready()
        return invoke(
            lambda: provider_service.page(
                ProviderSearchCommand(
                    archive_state=archiveState,
                    search=search,
                    service=service,
                    service_area=serviceArea,
                    selection_status=selectionStatus,
                    property_id=str(propertyId) if propertyId else None,
                    has_reference=hasReference,
                    category_id=str(categoryId) if categoryId else None,
                    category_state=categoryState,
                    limit=limit,
                    cursor=cursor,
                )
            )
        )

    @router.get(
        "/operations/by-key/{key}",
        operation_id="get_provider_operation_by_key",
        response_model=ProviderOperationResponse,
    )
    def recover_key(key: UUID):
        ready()
        return invoke(lambda: provider_service.recover(key=str(key)))

    @router.get(
        "/operations/{operation_id}",
        operation_id="get_provider_operation",
        response_model=ProviderOperationResponse,
    )
    def recover_id(operation_id: UUID):
        ready()
        return invoke(lambda: provider_service.recover(operation_id=str(operation_id)))

    @router.get("/{party_id}", operation_id="get_provider", response_model=ProviderResponse)
    def detail(party_id: UUID, includeArchived: bool = False):
        ready()
        return invoke(
            lambda: provider_service.detail(str(party_id), include_archived=includeArchived)
        )

    @router.patch(
        "/{party_id}",
        operation_id="update_provider_profile",
        response_model=ProviderMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
    )
    def update(party_id: UUID, data: ProfilePatchInput):
        ready(True)
        return invoke(
            lambda: provider_service.update_profile(
                str(party_id),
                _patch_profile(data),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/{party_id}/archive",
        operation_id="archive_provider",
        response_model=ProviderMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
    )
    def archive(party_id: UUID, data: ProviderArchiveInput):
        ready(True)
        return invoke(
            lambda: provider_service.archive(
                str(party_id),
                confirmed=data.confirmed,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/{party_id}/restore",
        operation_id="restore_provider",
        response_model=ProviderMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
    )
    def restore(party_id: UUID, data: ExistingProviderConcurrency):
        ready(True)
        return invoke(
            lambda: provider_service.restore(
                str(party_id),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/{party_id}/category-assignments",
        operation_id="assign_provider_category",
        response_model=AssignmentMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
        status_code=status.HTTP_201_CREATED,
    )
    def assign_category(party_id: UUID, data: CategoryAssignmentInput):
        ready(True)
        return invoke(
            lambda: provider_service.assign_category(
                str(party_id),
                ProviderCategoryAssignmentCommand(str(data.categoryId), str(data.idempotencyKey)),
                expected_revision=data.expectedRevision,
                expected_category_revision=data.expectedCategoryRevision,
            )
        )

    @router.post(
        "/{party_id}/category-assignments/{assignment_id}/archive",
        operation_id="archive_provider_category_assignment",
        response_model=AssignmentMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
    )
    def archive_category_assignment(
        party_id: UUID, assignment_id: UUID, data: AssignmentArchiveInput
    ):
        ready(True)
        return invoke(
            lambda: provider_service.archive_category_assignment(
                str(party_id),
                str(assignment_id),
                confirmed=data.confirmed,
                reason=data.reason,
                **_concurrency(data),
            )
        )

    @router.post(
        "/{party_id}/category-assignments/{assignment_id}/restore",
        operation_id="restore_provider_category_assignment",
        response_model=AssignmentMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
    )
    def restore_category_assignment(
        party_id: UUID, assignment_id: UUID, data: AssignmentRestoreInput
    ):
        ready(True)
        return invoke(
            lambda: provider_service.restore_category_assignment(
                str(party_id),
                str(assignment_id),
                confirmed=data.confirmed,
                expected_category_revision=data.expectedCategoryRevision,
                **_concurrency(data),
            )
        )

    @router.post(
        "/{party_id}/reputation-links",
        operation_id="add_provider_reputation_link",
        response_model=ReputationMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
        status_code=status.HTTP_201_CREATED,
    )
    def add_reputation_link(party_id: UUID, data: ReputationMutationInput):
        ready(True)
        return invoke(
            lambda: provider_service.add_reputation_link(
                str(party_id), _reputation(data), **_concurrency(data)
            )
        )

    @router.patch(
        "/{party_id}/reputation-links/{link_id}",
        operation_id="update_provider_reputation_link",
        response_model=ReputationMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
    )
    def patch_reputation_link(party_id: UUID, link_id: UUID, data: ReputationPatchMutationInput):
        ready(True)
        return invoke(
            lambda: provider_service.update_reputation_link(
                str(party_id), str(link_id), _reputation_patch(data), **_concurrency(data)
            )
        )

    @router.post(
        "/{party_id}/reputation-links/{link_id}/archive",
        operation_id="archive_provider_reputation_link",
        response_model=ReputationMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
    )
    def archive_reputation_link(party_id: UUID, link_id: UUID, data: ProviderArchiveInput):
        ready(True)
        return invoke(
            lambda: provider_service.archive_reputation_link(
                str(party_id), str(link_id), confirmed=data.confirmed, **_concurrency(data)
            )
        )

    @router.post(
        "/{party_id}/reputation-links/{link_id}/restore",
        operation_id="restore_provider_reputation_link",
        response_model=ReputationMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
    )
    def restore_reputation_link(party_id: UUID, link_id: UUID, data: ExistingProviderConcurrency):
        ready(True)
        return invoke(
            lambda: provider_service.restore_reputation_link(
                str(party_id), str(link_id), **_concurrency(data)
            )
        )

    _children(router, provider_service, ready, invoke)
    return router


def build_category_router(
    provider_service: ProviderService, runtime: WorkspaceRuntime
) -> APIRouter:
    """Settings-owned provider category catalog contract."""
    router = APIRouter(prefix="/api/provider-categories", tags=["provider-categories"])

    def ready(write=False):
        if not runtime.ready or runtime.error:
            raise workspace_unavailable(str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:
            raise workspace_unavailable("Workspace writer lock is unavailable.")

    def invoke(operation):
        try:
            return operation()
        except ProviderNotFoundError as error:
            raise domain_problem(
                error, status_code=404, code="provider_category_not_found"
            ) from error
        except ProviderCategoryIdempotencyConflict as error:
            raise domain_problem(
                error, status_code=409, code="provider_category_idempotency_conflict"
            ) from error
        except ProviderLifecycleConflict as error:
            raise domain_problem(
                error, status_code=409, code=error.code, current=error.current
            ) from error
        except ProviderError as error:
            raise domain_problem(
                error, status_code=400, code="provider_category_validation"
            ) from error

    @router.get("", operation_id="list_provider_categories", response_model=list[CategoryResponse])
    def categories(
        archiveState: Literal["active", "archived", "all"] = "active",
        search: str | None = Query(None, max_length=160),
    ):
        ready()
        return invoke(
            lambda: provider_service.list_categories(archive_state=archiveState, search=search)
        )

    @router.post(
        "",
        operation_id="create_provider_category",
        response_model=CategoryMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
        status_code=status.HTTP_201_CREATED,
    )
    def create(data: CategoryInput):
        ready(True)
        return invoke(
            lambda: provider_service.create_category(
                ProviderCategoryCommand(
                    data.displayName, data.displayOrder, str(data.idempotencyKey), data.description
                ),
                expected_revision=data.expectedRevision,
            )
        )

    @router.get(
        "/operations/by-key/{key}",
        operation_id="get_provider_category_operation_by_key",
        response_model=CategoryMutationResponse,
    )
    def recover_key(key: UUID):
        ready()
        return invoke(lambda: provider_service.recover_category(key=str(key)))

    @router.get(
        "/operations/{operation_id}",
        operation_id="get_provider_category_operation",
        response_model=CategoryMutationResponse,
    )
    def recover_id(operation_id: UUID):
        ready()
        return invoke(lambda: provider_service.recover_category(operation_id=str(operation_id)))

    @router.patch(
        "/{category_id}",
        operation_id="update_provider_category",
        response_model=CategoryMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
    )
    def patch(category_id: UUID, data: CategoryPatchInput):
        ready(True)
        fields = data.model_fields_set
        return invoke(
            lambda: provider_service.update_category(
                str(category_id),
                ProviderCategoryPatchCommand(
                    data.displayName if "displayName" in fields else UNSET,
                    data.description if "description" in fields else UNSET,
                    data.displayOrder if "displayOrder" in fields else UNSET,
                ),
                **_concurrency(data),
            )
        )

    @router.post(
        "/{category_id}/archive",
        operation_id="archive_provider_category",
        response_model=CategoryMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
    )
    def archive(category_id: UUID, data: CategoryLifecycleInput):
        ready(True)
        return invoke(
            lambda: provider_service.archive_category(
                str(category_id), confirmed=data.confirmed, reason=data.reason, **_concurrency(data)
            )
        )

    @router.post(
        "/{category_id}/restore",
        operation_id="restore_provider_category",
        response_model=CategoryMutationResponse,
        responses={409: {"model": ProviderConflictResponse}},
    )
    def restore(category_id: UUID, data: CategoryRestoreInput):
        ready(True)
        return invoke(
            lambda: provider_service.restore_category(
                str(category_id), confirmed=data.confirmed, **_concurrency(data)
            )
        )

    return router


def _children(router, service, ready, invoke):
    specs = (
        ("services", ServiceMutationInput, "service", ServiceMutationResponse),
        ("service-areas", AreaMutationInput, "area", AreaMutationResponse),
        ("work-history", WorkMutationInput, "work_history", WorkMutationResponse),
        ("references", ReferenceMutationInput, "reference", ReferenceMutationResponse),
    )
    for path, model, suffix, _response in specs:
        add = getattr(service, f"add_{suffix}")
        update = getattr(service, f"update_{suffix}")
        archive = getattr(service, f"archive_{suffix}")
        restore = getattr(service, f"restore_{suffix}")
        create = _create_endpoint(add, model, ready, invoke)
        patch = _patch_endpoint(update, model, ready, invoke)
        archive_item = _archive_endpoint(archive, ready, invoke)
        restore_item = _restore_endpoint(restore, ready, invoke)
        router.add_api_route(
            f"/{{party_id}}/{path}",
            create,
            operation_id=f"add_provider_{suffix}",
            methods=["POST"],
            response_model=_response,
            responses={409: {"model": ProviderConflictResponse}},
            status_code=201,
        )
        router.add_api_route(
            f"/{{party_id}}/{path}/{{item_id}}",
            patch,
            operation_id=f"update_provider_{suffix}",
            methods=["PATCH"],
            response_model=_response,
            responses={409: {"model": ProviderConflictResponse}},
        )
        router.add_api_route(
            f"/{{party_id}}/{path}/{{item_id}}/archive",
            archive_item,
            operation_id=f"archive_provider_{suffix}",
            methods=["POST"],
            response_model=_response,
            responses={409: {"model": ProviderConflictResponse}},
        )
        router.add_api_route(
            f"/{{party_id}}/{path}/{{item_id}}/restore",
            restore_item,
            operation_id=f"restore_provider_{suffix}",
            methods=["POST"],
            response_model=_response,
            responses={409: {"model": ProviderConflictResponse}},
        )


def _create_endpoint(operation, model, ready, invoke):
    def endpoint(party_id: UUID, data):
        ready(True)
        return invoke(lambda: operation(str(party_id), _command(data), **_concurrency(data)))

    endpoint.__annotations__["data"] = model
    return endpoint


def _patch_endpoint(operation, model, ready, invoke):
    def endpoint(party_id: UUID, item_id: UUID, data):
        ready(True)
        return invoke(
            lambda: operation(str(party_id), str(item_id), _command(data), **_concurrency(data))
        )

    endpoint.__annotations__["data"] = model
    return endpoint


def _archive_endpoint(operation, ready, invoke):
    def endpoint(party_id: UUID, item_id: UUID, data: ProviderArchiveInput):
        ready(True)
        return invoke(
            lambda: operation(
                str(party_id), str(item_id), confirmed=data.confirmed, **_concurrency(data)
            )
        )

    return endpoint


def _restore_endpoint(operation, ready, invoke):
    def endpoint(party_id: UUID, item_id: UUID, data: ExistingProviderConcurrency):
        ready(True)
        return invoke(lambda: operation(str(party_id), str(item_id), **_concurrency(data)))

    return endpoint


def _profile(data):
    return ProviderProfileCommand(data.selectionStatus, data.selectionReason, data.notes)


def _patch_profile(data):
    fields = data.model_fields_set
    return ProviderProfilePatchCommand(
        data.selectionStatus if "selectionStatus" in fields else UNSET,
        data.selectionReason if "selectionReason" in fields else UNSET,
        data.notes if "notes" in fields else UNSET,
    )


def _contact(data):
    return ContactMethodCommand(data.methodKind, data.value, data.extension, data.label)


def _reputation(data):
    return ReputationLinkCommand(
        data.sourceKind,
        data.url,
        data.sourceName,
        data.notes,
        data.lastCheckedOn.isoformat() if data.lastCheckedOn else None,
    )


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
    if isinstance(data, ServiceInput) and not isinstance(data, AreaInput):
        return ServiceCommand(data.displayName)
    if isinstance(data, AreaInput):
        return ServiceAreaCommand(data.displayName, data.countryCode)
    if isinstance(data, WorkInput):
        return WorkHistoryCommand(
            data.performedOn.isoformat(),
            data.summary,
            str(data.propertyId) if data.propertyId else None,
            data.outcomeNotes,
        )
    return ReferenceCommand(
        data.referenceName,
        data.organizationName,
        data.relationship,
        data.email,
        data.phone,
        data.notes,
    )


def _concurrency(data):
    return {"expected_revision": data.expectedRevision, "idempotency_key": str(data.idempotencyKey)}

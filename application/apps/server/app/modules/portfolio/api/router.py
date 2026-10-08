"""Strict, documented local portfolio API."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

from app.platform.api_errors import domain_problem, workspace_unavailable

from app.modules.parties.application.service import PartyValidationError
from app.modules.portfolio.application.ports import PortfolioConflictError
from app.modules.portfolio.application.status_contracts import (
    ManualStatusConflictResponse,
    ManualStatusMutationResponse,
    ManualStatusOperationReceipt,
    SpaceResponse,
    SpaceStatusResponse,
)
from app.modules.portfolio.application.service import (
    AvailabilityCommand,
    OccupancyCommand,
    OccupancyCorrectionCommand,
    OwnershipInput,
    PartyCreateCommand,
    PortfolioError,
    PortfolioNotFoundError,
    PortfolioService,
    PropertyCreateCommand,
    SpaceClassificationCommand,
    SpaceCreateCommand,
)
from app.modules.workspace.application.runtime import WorkspaceRuntime


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InventoryRequest(ContractModel):
    expectedPropertyRevision: StrictInt = Field(ge=0)
    idempotencyKey: str = Field(min_length=1, max_length=200, pattern=r"^\S(?:.*\S)?$")


class PartyRequest(ContractModel):
    partyKind: Literal["individual", "organization"]
    displayName: str = Field(min_length=1, max_length=240)


class OwnershipRequest(ContractModel):
    ownerKind: Literal["local_operator", "client_owner"]
    partyId: UUID | None = None
    inlineParty: PartyRequest | None = None

    @model_validator(mode="after")
    def validate_party_reference(self) -> "OwnershipRequest":
        party_id = self.partyId
        if self.ownerKind == "local_operator" and (
            party_id is not None or self.inlineParty is not None
        ):
            raise ValueError("local_operator ownership cannot include an owner party")
        if self.ownerKind == "client_owner" and ((party_id is None) == (self.inlineParty is None)):
            raise ValueError("client_owner ownership requires exactly one partyId or inlineParty")
        self.partyId = party_id
        return self


class PropertyCreateRequest(InventoryRequest):
    expectedPropertyRevision: StrictInt = Field(ge=0, le=0)
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


class SpaceAddRequest(SpaceCreateRequest, InventoryRequest):
    pass


class OccupancyRequest(ContractModel):
    occupancyStatus: Literal["occupied", "vacant", "unknown"]
    effectiveOn: date
    note: str | None = Field(None, max_length=1000)
    expectedRevision: StrictInt | None = Field(None, ge=0)
    idempotencyKey: str | None = Field(None, min_length=1, max_length=200)


class AvailabilityRequest(ContractModel):
    availabilityStatus: Literal["available_now", "available_on", "not_available", "unknown"]
    availableOn: date | None = None
    note: str | None = Field(None, max_length=1000)
    expectedRevision: StrictInt | None = Field(None, ge=0)
    idempotencyKey: str | None = Field(None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_date(self) -> "AvailabilityRequest":
        if (self.availabilityStatus == "available_on") != (self.availableOn is not None):
            raise ValueError("availableOn is required only with available_on")
        return self


class OccupancyMutationRequest(OccupancyRequest):
    expectedRevision: StrictInt = Field(ge=0)
    idempotencyKey: str = Field(min_length=1, max_length=200)


class AvailabilityMutationRequest(AvailabilityRequest):
    expectedRevision: StrictInt = Field(ge=0)
    idempotencyKey: str = Field(min_length=1, max_length=200)


class SpaceClassificationRequest(ContractModel):
    occupancy: OccupancyRequest | None = None
    availability: AvailabilityRequest | None = None
    expectedRevision: StrictInt = Field(ge=0)
    idempotencyKey: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def require_status(self) -> "SpaceClassificationRequest":
        if self.occupancy is None and self.availability is None:
            raise ValueError("occupancy or availability is required")
        if self.occupancy is not None and self.occupancy.occupancyStatus == "unknown":
            raise ValueError("classification occupancy must be occupied or vacant")
        if self.availability is not None and self.availability.availabilityStatus == "unknown":
            raise ValueError("classification availability must select a known status")
        return self


class OccupancyCorrectionRequest(ContractModel):
    occupancy: OccupancyRequest
    reason: str = Field(min_length=1, max_length=1000)
    expectedRevision: StrictInt = Field(ge=0)
    idempotencyKey: str = Field(min_length=1, max_length=200)


class StatusMutationRequest(ContractModel):
    expectedRevision: StrictInt = Field(ge=0)
    idempotencyKey: str = Field(min_length=1, max_length=200)


class SpacePatchRequest(InventoryRequest):
    displayName: str | None = Field(None, min_length=1, max_length=120)
    suiteOrFloor: str | None = Field(None, max_length=80)
    notes: str | None = Field(None, max_length=4000)


class PropertyPatchRequest(InventoryRequest):
    displayName: str | None = Field(None, min_length=1, max_length=240)
    addressLine1: str | None = Field(None, min_length=1, max_length=240)
    addressLine2: str | None = Field(None, max_length=240)
    city: str | None = Field(None, min_length=1, max_length=120)
    region: str | None = Field(None, max_length=120)
    postalCode: str | None = Field(None, max_length=40)
    countryCode: str | None = Field(None, min_length=2, max_length=2)
    notes: str | None = Field(None, max_length=4000)


class OwnershipReplaceRequest(InventoryRequest):
    effectiveOn: date
    ownerships: list[OwnershipRequest] = Field(min_length=1)


class ConfirmationRequest(ContractModel):
    confirmed: StrictBool


class InventoryConfirmationRequest(InventoryRequest):
    confirmed: StrictBool


MANUAL_STATUS_RESPONSES = {409: {"model": ManualStatusConflictResponse}}


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
    asOf: AwareDatetime


class PartyResponse(ContractModel):
    id: UUID
    partyKind: Literal["individual", "organization"]
    displayName: str
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    archivedAt: AwareDatetime | None


class OwnershipResponse(ContractModel):
    id: UUID
    propertyId: UUID
    ownerKind: Literal["local_operator", "client_owner"]
    partyId: UUID | None
    party: PartyResponse | None
    startsOn: date
    endsOn: date | None
    createdAt: AwareDatetime
    endedAt: AwareDatetime | None


class PropertyResponse(ContractModel):
    propertyRevision: StrictInt = Field(ge=1)
    id: UUID
    displayName: str
    addressLine1: str
    addressLine2: str | None
    city: str
    region: str | None
    postalCode: str | None
    countryCode: str
    timeZone: str
    notes: str | None
    status: Literal["active", "archived"]
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    archivedAt: AwareDatetime | None
    propertyType: Literal["single_family_home", "condo", "townhome", "office"]
    inventoryLayout: Literal["single_space", "whole_office", "office_suites"]
    ownershipContext: Literal["self_owned", "managed_for_owner", "mixed"]
    ownerships: list[OwnershipResponse]
    spaces: list[SpaceStatusResponse]
    statusSummary: PropertyStatusSummaryResponse
    asOf: AwareDatetime
    effectiveLocalDate: date


class PropertyMutationResponse(PropertyResponse):
    operationId: UUID


class SpaceInventoryMutationResponse(SpaceResponse):
    id: UUID
    propertyId: UUID
    propertyRevision: StrictInt = Field(ge=1)
    operationId: UUID
    asOf: AwareDatetime
    effectiveLocalDate: date


class InventoryOperationReceipt(ContractModel):
    operationId: UUID
    propertyId: UUID
    action: Literal[
        "create_property",
        "patch_property",
        "archive_property",
        "restore_property",
        "replace_ownerships",
        "add_space",
        "patch_space",
        "archive_space",
        "restore_space",
    ]
    idempotencyKey: str
    expectedPropertyRevision: StrictInt = Field(ge=0)
    propertyRevision: StrictInt = Field(ge=1)
    effective: bool
    correlationId: UUID
    committedAt: AwareDatetime
    result: PropertyMutationResponse | SpaceInventoryMutationResponse


class InventoryConflictDetail(ContractModel):
    code: Literal[
        "portfolio_conflict",
        "portfolio_inventory_payload_conflict",
        "portfolio_inventory_revision_conflict",
    ]
    message: str
    currentStatus: PropertyResponse | None = None


class InventoryConflictResponse(ContractModel):
    detail: InventoryConflictDetail


INVENTORY_RESPONSES = {409: {"model": InventoryConflictResponse}}


class PropertyPageResponse(ContractModel):
    items: list[PropertyResponse]
    nextCursor: str | None
    matchingTotal: int
    asOf: AwareDatetime


def build_router(service: PortfolioService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(tags=["portfolio"])

    def require_ready(*, write: bool = False) -> None:
        if not runtime.ready or runtime.error:
            raise workspace_unavailable(str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:
            raise workspace_unavailable("Workspace writer lock is unavailable.")

    def invoke(operation):
        try:
            return operation()
        except PortfolioNotFoundError as error:
            raise domain_problem(error, status_code=404, code="portfolio_not_found") from error
        except PortfolioConflictError as error:
            detail: object = str(error)
            if error.current_status is not None:
                detail = {
                    "message": str(error),
                    "currentStatus": (
                        PropertyResponse
                        if "ownershipContext" in error.current_status
                        else SpaceStatusResponse
                    )
                    .model_validate(error.current_status)
                    .model_dump(mode="json"),
                }
            if isinstance(detail, dict):
                raise domain_problem(
                    error,
                    status_code=409,
                    code=error.code,
                    **{key: value for key, value in detail.items() if key != "message"},
                ) from error
            raise domain_problem(error, status_code=409, code=error.code) from error
        except PortfolioError as error:
            raise domain_problem(error, status_code=400, code="portfolio_validation") from error
        except PartyValidationError as error:
            raise domain_problem(error, status_code=400, code="portfolio_validation") from error

    @router.post(
        "/api/properties",
        response_model=PropertyMutationResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createPortfolioProperty",
        responses=INVENTORY_RESPONSES,
    )
    def create_property(data: PropertyCreateRequest):
        require_ready(write=True)

        return invoke(
            lambda: service.create_property(
                _create(data),
                expected_revision=data.expectedPropertyRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.get(
        "/api/properties",
        response_model=PropertyPageResponse,
        operation_id="getPortfolioPropertySourcePage",
    )
    def list_properties(
        status: Literal["active", "archived"] | None = None,
        ownershipContext: Literal["self_owned", "managed_for_owner", "mixed"] | None = None,
        occupancy: Literal["occupied", "vacant", "unknown"] | None = None,
        availability: Literal["available_now", "available_on", "not_available", "unknown"]
        | None = None,
        needsAttention: bool | None = None,
        pageSize: int = Query(100, ge=1, le=500),
        cursor: str | None = None,
    ):
        require_ready()
        return invoke(
            lambda: service.page_properties(
                status=status,
                ownership_context_filter=ownershipContext,
                occupancy_filter=occupancy,
                availability_filter=availability,
                needs_attention=needsAttention,
                page_size=pageSize,
                cursor=cursor,
            )
        )

    @router.get(
        "/api/properties/{property_id}",
        response_model=PropertyResponse,
        operation_id="getPortfolioProperty",
    )
    def get_property(property_id: UUID):
        require_ready()
        return invoke(lambda: service.get_property(str(property_id)))

    @router.get(
        "/api/portfolio/status-summary",
        response_model=PortfolioStatusSummaryResponse,
        operation_id="getPortfolioStatusSummary",
    )
    def get_portfolio_status_summary():
        require_ready()
        return invoke(service.portfolio_status_summary)

    @router.patch(
        "/api/properties/{property_id}",
        response_model=PropertyMutationResponse,
        operation_id="patchPortfolioProperty",
        responses=INVENTORY_RESPONSES,
    )
    def patch_property(property_id: UUID, data: PropertyPatchRequest):
        require_ready(write=True)

        return invoke(
            lambda: service.patch_property(
                str(property_id),
                data.model_dump(
                    exclude_unset=True, exclude={"expectedPropertyRevision", "idempotencyKey"}
                ),
                expected_revision=data.expectedPropertyRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.post(
        "/api/properties/{property_id}/archive",
        response_model=PropertyMutationResponse,
        operation_id="archivePortfolioProperty",
        responses=INVENTORY_RESPONSES,
    )
    def archive_property(property_id: UUID, data: InventoryConfirmationRequest):
        require_ready(write=True)

        return invoke(
            lambda: service.archive_property(
                str(property_id),
                confirmed=data.confirmed,
                expected_revision=data.expectedPropertyRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.post(
        "/api/properties/{property_id}/restore",
        response_model=PropertyMutationResponse,
        operation_id="restorePortfolioProperty",
        responses=INVENTORY_RESPONSES,
    )
    def restore_property(property_id: UUID, data: InventoryRequest):
        require_ready(write=True)

        return invoke(
            lambda: service.restore_property(
                str(property_id),
                expected_revision=data.expectedPropertyRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.put(
        "/api/properties/{property_id}/ownerships",
        response_model=PropertyMutationResponse,
        operation_id="replacePortfolioOwnerships",
        responses=INVENTORY_RESPONSES,
    )
    def replace_ownerships(property_id: UUID, data: OwnershipReplaceRequest):
        require_ready(write=True)
        return invoke(
            lambda: service.replace_ownerships(
                str(property_id),
                _ownerships(data.ownerships),
                data.effectiveOn.isoformat(),
                expected_revision=data.expectedPropertyRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.post(
        "/api/properties/{property_id}/spaces",
        response_model=SpaceInventoryMutationResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="addPortfolioSpace",
        responses=INVENTORY_RESPONSES,
    )
    def add_space(property_id: UUID, data: SpaceAddRequest):
        require_ready(write=True)
        return invoke(
            lambda: service.add_space(
                str(property_id),
                _space(data),
                expected_revision=data.expectedPropertyRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.post(
        "/api/spaces/{space_id}/archive",
        response_model=SpaceInventoryMutationResponse,
        operation_id="archivePortfolioSpace",
        responses=INVENTORY_RESPONSES,
    )
    def archive_space(space_id: UUID, data: InventoryConfirmationRequest):
        require_ready(write=True)
        return invoke(
            lambda: service.archive_space(
                str(space_id),
                confirmed=data.confirmed,
                expected_revision=data.expectedPropertyRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.patch(
        "/api/spaces/{space_id}",
        response_model=SpaceInventoryMutationResponse,
        operation_id="patchPortfolioSpace",
        responses=INVENTORY_RESPONSES,
    )
    def patch_space(space_id: UUID, data: SpacePatchRequest):
        require_ready(write=True)
        return invoke(
            lambda: service.patch_space(
                str(space_id),
                data.model_dump(
                    exclude_unset=True, exclude={"expectedPropertyRevision", "idempotencyKey"}
                ),
                expected_revision=data.expectedPropertyRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.post(
        "/api/spaces/{space_id}/restore",
        response_model=SpaceInventoryMutationResponse,
        operation_id="restorePortfolioSpace",
        responses=INVENTORY_RESPONSES,
    )
    def restore_space(space_id: UUID, data: InventoryRequest):
        require_ready(write=True)
        return invoke(
            lambda: service.restore_space(
                str(space_id),
                expected_revision=data.expectedPropertyRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.get(
        "/api/portfolio/inventory-operations/by-key",
        response_model=InventoryOperationReceipt,
        operation_id="getPortfolioInventoryOperationByGlobalKey",
    )
    def get_inventory_operation_by_global_key(
        idempotencyKey: str = Query(min_length=1, max_length=200),
    ):
        require_ready()
        return invoke(lambda: service.get_inventory_operation(idempotency_key=idempotencyKey))

    @router.get(
        "/api/portfolio/inventory-operations/{operation_id}",
        response_model=InventoryOperationReceipt,
        operation_id="getPortfolioInventoryOperation",
    )
    def get_inventory_operation(operation_id: UUID):
        require_ready()
        return invoke(lambda: service.get_inventory_operation(operation_id=str(operation_id)))

    @router.get(
        "/api/properties/{property_id}/inventory-operations/by-key",
        response_model=InventoryOperationReceipt,
        operation_id="getPortfolioInventoryOperationByKey",
    )
    def get_inventory_operation_by_key(
        property_id: UUID, idempotencyKey: str = Query(min_length=1, max_length=200)
    ):
        require_ready()
        return invoke(
            lambda: service.get_inventory_operation(
                property_id=str(property_id), idempotency_key=idempotencyKey
            )
        )

    @router.get(
        "/api/spaces/{space_id}/status",
        response_model=SpaceStatusResponse,
        operation_id="getPortfolioSpaceStatus",
    )
    def get_space_status(space_id: UUID):
        require_ready()
        return invoke(lambda: service.get_space_status(str(space_id)))

    @router.get(
        "/api/portfolio/status-operations/{operation_id}",
        response_model=ManualStatusOperationReceipt,
        operation_id="getPortfolioStatusOperation",
    )
    def get_status_operation(operation_id: UUID):
        require_ready()
        return invoke(lambda: service.get_status_operation(operation_id=str(operation_id)))

    @router.get(
        "/api/spaces/{space_id}/status-operations/{idempotency_key}",
        response_model=ManualStatusOperationReceipt,
        operation_id="getPortfolioStatusOperationByKey",
    )
    def get_status_operation_by_key(space_id: UUID, idempotency_key: str):
        require_ready()
        return invoke(
            lambda: service.get_status_operation(
                space_id=str(space_id), idempotency_key=idempotency_key
            )
        )

    @router.put(
        "/api/spaces/{space_id}/occupancy",
        response_model=ManualStatusMutationResponse,
        responses=MANUAL_STATUS_RESPONSES,
        operation_id="changePortfolioSpaceOccupancy",
    )
    def change_occupancy(space_id: UUID, data: OccupancyMutationRequest):
        require_ready(write=True)
        return invoke(
            lambda: service.change_occupancy(
                str(space_id),
                _occupancy(data),
                expected_revision=data.expectedRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.post(
        "/api/spaces/{space_id}/occupancy/scheduled/{period_id}/cancel",
        response_model=ManualStatusMutationResponse,
        responses=MANUAL_STATUS_RESPONSES,
        operation_id="cancelPortfolioScheduledOccupancy",
    )
    def cancel_scheduled_occupancy(space_id: UUID, period_id: UUID, data: StatusMutationRequest):
        require_ready(write=True)
        return invoke(
            lambda: service.cancel_scheduled_occupancy(
                str(space_id),
                str(period_id),
                expected_revision=data.expectedRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.post(
        "/api/spaces/{space_id}/occupancy/{period_id}/correct",
        response_model=ManualStatusMutationResponse,
        responses=MANUAL_STATUS_RESPONSES,
        operation_id="correctPortfolioSpaceOccupancy",
    )
    def correct_occupancy(space_id: UUID, period_id: UUID, data: OccupancyCorrectionRequest):
        require_ready(write=True)
        return invoke(
            lambda: service.correct_occupancy(
                str(space_id),
                str(period_id),
                OccupancyCorrectionCommand(_occupancy(data.occupancy), data.reason),
                expected_revision=data.expectedRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.put(
        "/api/spaces/{space_id}/occupancy/scheduled/{period_id}/reschedule",
        response_model=ManualStatusMutationResponse,
        responses=MANUAL_STATUS_RESPONSES,
        operation_id="reschedulePortfolioScheduledOccupancy",
    )
    def reschedule_scheduled_occupancy(
        space_id: UUID,
        period_id: UUID,
        data: OccupancyMutationRequest,
    ):
        require_ready(write=True)
        return invoke(
            lambda: service.reschedule_scheduled_occupancy(
                str(space_id),
                str(period_id),
                _occupancy(data),
                expected_revision=data.expectedRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.put(
        "/api/spaces/{space_id}/occupancy/scheduled/{period_id}/replace",
        response_model=ManualStatusMutationResponse,
        responses=MANUAL_STATUS_RESPONSES,
        deprecated=True,
        operation_id="replacePortfolioScheduledOccupancy",
    )
    def replace_scheduled_occupancy(
        space_id: UUID, period_id: UUID, data: OccupancyMutationRequest
    ):
        """Compatibility alias retained for callers of the pre-PORT-003 operation."""
        require_ready(write=True)
        return invoke(
            lambda: service.replace_scheduled_occupancy(
                str(space_id),
                str(period_id),
                _occupancy(data),
                expected_revision=data.expectedRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.put(
        "/api/spaces/{space_id}/availability",
        response_model=ManualStatusMutationResponse,
        responses=MANUAL_STATUS_RESPONSES,
        operation_id="changePortfolioSpaceAvailability",
    )
    def change_availability(space_id: UUID, data: AvailabilityMutationRequest):
        require_ready(write=True)
        return invoke(
            lambda: service.change_availability(
                str(space_id),
                _availability(data),
                expected_revision=data.expectedRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    @router.put(
        "/api/spaces/{space_id}/classification",
        response_model=ManualStatusMutationResponse,
        responses=MANUAL_STATUS_RESPONSES,
        operation_id="classifyPortfolioSpace",
    )
    def classify_space(space_id: UUID, data: SpaceClassificationRequest):
        require_ready(write=True)
        return invoke(
            lambda: service.classify_space(
                str(space_id),
                SpaceClassificationCommand(
                    None if data.occupancy is None else _occupancy(data.occupancy),
                    None if data.availability is None else _availability(data.availability),
                ),
                expected_revision=data.expectedRevision,
                idempotency_key=data.idempotencyKey,
            )
        )

    return router


def _party(data: PartyRequest) -> PartyCreateCommand:
    return PartyCreateCommand(data.partyKind, data.displayName)


def _ownerships(items: list[OwnershipRequest]) -> tuple[OwnershipInput, ...]:
    return tuple(
        OwnershipInput(
            item.ownerKind,
            None if item.partyId is None else str(item.partyId),
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

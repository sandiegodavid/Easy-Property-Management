from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool

from app.platform.api_errors import api_problem, domain_problem, workspace_unavailable

from app.modules.owner_management.application.service import OwnerConcernService, _cursor
from app.modules.owner_management.domain.models import (
    ConcernCreateCommand,
    FollowUpInput,
    OwnerConcernConflictError,
    OwnerConcernError,
    OwnerConcernNotFoundError,
)
from app.modules.workspace.application.runtime import WorkspaceRuntime


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FollowUpRequest(Contract):
    title: str = Field(min_length=1, max_length=255)
    notes: str | None = Field(default=None, max_length=10_000)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    dueAtUtc: AwareDatetime | None = None
    dueTimezone: str | None = Field(default=None, max_length=128)


class ConcernCreateRequest(Contract):
    expectedRevision: int = Field(strict=True, ge=0, le=0)
    ownerPartyId: UUID
    propertyId: UUID
    concernType: Literal["general_rental", "lease", "tenant", "vacancy"]
    summary: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=10_000)
    raisedAtUtc: AwareDatetime
    idempotencyKey: UUID
    spaceId: UUID | None = None
    leaseId: UUID | None = None
    tenantPartyId: UUID | None = None
    originatingCommunicationId: UUID | None = None
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    historicalSelectionConfirmed: StrictBool = False
    historicalSelectionReason: str | None = Field(default=None, max_length=1000)
    duplicateConfirmed: StrictBool = False
    duplicateReason: str | None = Field(default=None, max_length=1000)
    replacesConcernId: UUID | None = None
    followUp: FollowUpRequest | None = None


class ConcernPatchRequest(Contract):
    expectedRevision: int = Field(strict=True, ge=1)
    idempotencyKey: UUID
    summary: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, min_length=1, max_length=10_000)
    priority: Literal["low", "normal", "high", "urgent"] | None = None


class TransitionRequest(Contract):
    expectedRevision: int = Field(strict=True, ge=1)
    idempotencyKey: UUID
    confirmed: StrictBool
    summary: str | None = Field(default=None, min_length=1, max_length=4000)


class ConcernFollowUpRequest(FollowUpRequest):
    expectedRevision: int = Field(strict=True, ge=1)
    idempotencyKey: UUID


class FollowUpSummary(Contract):
    id: UUID
    status: Literal["open", "in_progress", "completed", "cancelled"]
    title: str
    dueAtUtc: AwareDatetime | None = None


class LineageSummary(Contract):
    id: UUID
    status: Literal["open", "in_progress", "resolved", "dismissed"]
    summary: str


class OriginatingCommunicationState(Contract):
    id: UUID
    status: Literal["recorded", "superseded"]
    supersededByCommunicationId: UUID | None = None


class RecentCommunicationSummary(Contract):
    id: UUID
    subject: str
    occurredAtUtc: AwareDatetime
    status: Literal["draft", "recorded", "superseded"]


class CurrentSourceState(Contract):
    propertyStatus: Literal["active", "archived"] | None = None
    propertyDisplayName: str | None = None
    ownerArchived: bool
    ownerDisplayName: str | None = None
    spaceStatus: Literal["active", "archived"] | None = None
    spaceDisplayName: str | None = None
    leaseStatus: str | None = None
    leaseActualMoveOutOn: date | None = None
    tenantArchived: bool
    tenantDisplayName: str | None = None
    tenantProfileActive: bool
    tenantParticipationActive: bool | None = None
    occupancyStatus: Literal["occupied", "vacant", "unknown"] | None = None
    availabilityStatus: (
        Literal["available_now", "available_on", "not_available", "unknown"] | None
    ) = None
    availableOn: date | None = None


class ConcernResponse(Contract):
    id: UUID
    revision: int = Field(strict=True, ge=1)
    operationId: UUID | None = None
    ownerPartyId: UUID
    ownerDisplayNameSnapshot: str
    propertyId: UUID
    propertyDisplayNameSnapshot: str
    spaceId: UUID | None = None
    spaceDisplayNameSnapshot: str | None = None
    leaseId: UUID | None = None
    leaseDisplaySnapshot: str | None = None
    tenantPartyId: UUID | None = None
    tenantDisplayNameSnapshot: str | None = None
    originatingCommunicationId: UUID | None = None
    concernType: Literal["general_rental", "lease", "tenant", "vacancy"]
    summary: str
    description: str
    priority: Literal["low", "normal", "high", "urgent"]
    status: Literal["open", "in_progress", "resolved", "dismissed"]
    raisedAtUtc: AwareDatetime
    propertyTimezoneSnapshot: str
    recordedAtUtc: AwareDatetime
    updatedAtUtc: AwareDatetime
    resolvedAtUtc: AwareDatetime | None = None
    resolutionSummary: str | None = None
    dismissedAtUtc: AwareDatetime | None = None
    dismissalReason: str | None = None
    replacesConcernId: UUID | None = None
    observedOccupancyStatus: str | None = None
    observedAvailabilityStatus: str | None = None
    observedAvailableOn: str | None = None
    followUpTasks: list[FollowUpSummary] = []
    linkedCommunicationCount: int = 0
    predecessor: LineageSummary | None = None
    successor: LineageSummary | None = None
    originatingCommunicationState: OriginatingCommunicationState | None = None
    recentCommunications: list[RecentCommunicationSummary] = []
    currentSourceState: CurrentSourceState


class ConcernFollowUpTaskResponse(Contract):
    """Original Task.to_dict snapshot retained by the concern command receipt."""

    id: UUID
    title: str
    notes: str | None
    status: Literal["open", "in_progress", "completed", "cancelled"]
    priority: Literal["low", "normal", "high", "urgent"]
    dueAtUtc: AwareDatetime | None
    dueTimezone: str | None
    isAllDay: StrictBool
    completedAtUtc: AwareDatetime | None
    cancelledAtUtc: AwareDatetime | None
    outcomeNote: str | None
    relatedEntityType: str | None
    relatedEntityId: UUID | None
    relatedLabel: str | None
    createdAtUtc: AwareDatetime
    updatedAtUtc: AwareDatetime
    revision: int = Field(strict=True, ge=1)
    waitingForKind: str | None
    waitingForLabel: str | None
    followUpAt: AwareDatetime | None
    followUpTimezone: str | None
    waitingSetAtUtc: AwareDatetime | None
    waitingClearedAtUtc: AwareDatetime | None
    deletedAtUtc: AwareDatetime | None


class ConcernMutationResponse(ConcernResponse):
    operationId: UUID
    followUpTask: ConcernFollowUpTaskResponse | None = None


class ConcernConflictDetail(Contract):
    code: str
    message: str
    currentRevision: int | None = Field(default=None, strict=True, ge=1)
    current: ConcernResponse | None = None
    candidateConcernIds: list[UUID] | None = Field(default=None, max_length=20)


class ConcernConflictResponse(Contract):
    detail: ConcernConflictDetail


class ConcernSummaryResponse(Contract):
    id: UUID
    ownerPartyId: UUID
    ownerDisplayNameSnapshot: str
    propertyId: UUID
    propertyDisplayNameSnapshot: str
    spaceId: UUID | None = None
    spaceDisplayNameSnapshot: str | None = None
    concernType: Literal["general_rental", "lease", "tenant", "vacancy"]
    summary: str
    priority: Literal["low", "normal", "high", "urgent"]
    status: Literal["open", "in_progress", "resolved", "dismissed"]
    raisedAtUtc: AwareDatetime
    propertyTimezoneSnapshot: str
    activeFollowUpCount: int
    linkedCommunicationCount: int


class ConcernPage(Contract):
    items: list[ConcernSummaryResponse]
    nextCursor: str | None = None


def build_router(service: OwnerConcernService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(
        prefix="/api/owner-concerns",
        tags=["owner concerns"],
        responses={409: {"model": ConcernConflictResponse}},
    )

    def ready():
        if not runtime.ready or runtime.error:
            raise workspace_unavailable(str(runtime.error or "Workspace is not ready."))

    def writable():
        ready()
        if not runtime.can_write:
            raise workspace_unavailable("Workspace writer lock is unavailable.")

    def invoke(operation):
        try:
            return operation()
        except OwnerConcernNotFoundError as error:
            raise domain_problem(error, status_code=404) from error
        except OwnerConcernConflictError as error:
            raise domain_problem(error, status_code=409, **error.details) from error
        except OwnerConcernError as error:
            raise domain_problem(error, status_code=400) from error

    def follow(value):
        return (
            None
            if value is None
            else FollowUpInput(
                value.title,
                value.notes,
                value.priority,
                value.dueAtUtc.isoformat() if value.dueAtUtc else None,
                value.dueTimezone,
            )
        )

    def command(data):
        return ConcernCreateCommand(
            str(data.ownerPartyId),
            str(data.propertyId),
            data.concernType,
            data.summary,
            data.description,
            data.raisedAtUtc.isoformat(),
            str(data.idempotencyKey),
            str(data.spaceId) if data.spaceId else None,
            str(data.leaseId) if data.leaseId else None,
            str(data.tenantPartyId) if data.tenantPartyId else None,
            str(data.originatingCommunicationId) if data.originatingCommunicationId else None,
            data.priority,
            data.historicalSelectionConfirmed,
            data.historicalSelectionReason,
            data.duplicateConfirmed,
            data.duplicateReason,
            str(data.replacesConcernId) if data.replacesConcernId else None,
            follow(data.followUp),
        )

    @router.post(
        "",
        operation_id="create_owner_concern",
        response_model=ConcernMutationResponse,
        dependencies=[Depends(writable)],
    )
    def create(data: ConcernCreateRequest):
        return invoke(
            lambda: service.create(command(data), expected_revision=data.expectedRevision)
        )

    @router.get(
        "",
        operation_id="list_owner_concerns",
        response_model=ConcernPage,
        dependencies=[Depends(ready)],
    )
    def list_concerns(
        ownerPartyId: UUID | None = None,
        propertyId: UUID | None = None,
        spaceId: UUID | None = None,
        leaseId: UUID | None = None,
        tenantPartyId: UUID | None = None,
        concernType: Literal["general_rental", "lease", "tenant", "vacancy"] | None = None,
        priority: Literal["low", "normal", "high", "urgent"] | None = None,
        status: Literal["open", "in_progress", "resolved", "dismissed"] | None = None,
        raisedLocalOnOrAfter: date | None = None,
        raisedLocalOnOrBefore: date | None = None,
        activeTask: StrictBool | None = None,
        linkedCommunication: StrictBool | None = None,
        pageSize: int = Query(100, ge=1, le=500),
        cursor: str | None = None,
    ):
        if cursor is not None:
            try:
                _cursor(cursor)
            except Exception as error:
                raise api_problem(422, "owner_concern_validation", "Cursor is invalid.") from error
        items, next_cursor = invoke(
            lambda: service.list(
                owner_party_id=str(ownerPartyId) if ownerPartyId else None,
                property_id=str(propertyId) if propertyId else None,
                space_id=str(spaceId) if spaceId else None,
                lease_id=str(leaseId) if leaseId else None,
                tenant_party_id=str(tenantPartyId) if tenantPartyId else None,
                concern_type=concernType,
                priority=priority,
                status=status,
                raised_local_on_or_after=raisedLocalOnOrAfter.isoformat()
                if raisedLocalOnOrAfter
                else None,
                raised_local_on_or_before=raisedLocalOnOrBefore.isoformat()
                if raisedLocalOnOrBefore
                else None,
                active_task=activeTask,
                linked_communication=linkedCommunication,
                page_size=pageSize,
                cursor=cursor,
            )
        )
        return {"items": items, "nextCursor": next_cursor}

    @router.get(
        "/operations/by-key/{key}",
        operation_id="get_owner_concern_operation_by_key",
        response_model=ConcernMutationResponse,
        dependencies=[Depends(ready)],
    )
    def operation_by_key(key: UUID):
        return invoke(lambda: service.command_operation_by_key(str(key)))

    @router.get(
        "/operations/{operation_id}",
        operation_id="get_owner_concern_operation",
        response_model=ConcernMutationResponse,
        dependencies=[Depends(ready)],
    )
    def operation_by_id(operation_id: UUID):
        return invoke(lambda: service.command_operation(str(operation_id)))

    @router.get(
        "/{concern_id}",
        operation_id="get_owner_concern",
        response_model=ConcernResponse,
        dependencies=[Depends(ready)],
    )
    def detail(concern_id: UUID):
        return invoke(lambda: service.get(str(concern_id)))

    @router.patch(
        "/{concern_id}",
        operation_id="update_owner_concern",
        response_model=ConcernMutationResponse,
        dependencies=[Depends(writable)],
    )
    def patch(concern_id: UUID, data: ConcernPatchRequest):
        return invoke(
            lambda: service.patch(
                str(concern_id),
                data.model_dump(exclude_unset=True, exclude={"expectedRevision", "idempotencyKey"}),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/{concern_id}/start",
        operation_id="start_owner_concern",
        response_model=ConcernMutationResponse,
        dependencies=[Depends(writable)],
    )
    def start(concern_id: UUID, data: TransitionRequest):
        return invoke(
            lambda: service.transition(
                str(concern_id),
                "in_progress",
                confirmed=data.confirmed,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/{concern_id}/resolve",
        operation_id="resolve_owner_concern",
        response_model=ConcernMutationResponse,
        dependencies=[Depends(writable)],
    )
    def resolve(concern_id: UUID, data: TransitionRequest):
        return invoke(
            lambda: service.transition(
                str(concern_id),
                "resolved",
                confirmed=data.confirmed,
                narrative=data.summary,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/{concern_id}/dismiss",
        operation_id="dismiss_owner_concern",
        response_model=ConcernMutationResponse,
        dependencies=[Depends(writable)],
    )
    def dismiss(concern_id: UUID, data: TransitionRequest):
        return invoke(
            lambda: service.transition(
                str(concern_id),
                "dismissed",
                confirmed=data.confirmed,
                narrative=data.summary,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/{concern_id}/reopen",
        operation_id="reopen_owner_concern",
        response_model=ConcernMutationResponse,
        dependencies=[Depends(writable)],
    )
    def reopen(concern_id: UUID, data: TransitionRequest):
        return invoke(
            lambda: service.transition(
                str(concern_id),
                "open",
                confirmed=data.confirmed,
                narrative=data.summary,
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/{concern_id}/follow-ups",
        operation_id="add_owner_concern_follow_up",
        response_model=ConcernMutationResponse,
        dependencies=[Depends(writable)],
    )
    def follow_up(concern_id: UUID, data: ConcernFollowUpRequest):
        return invoke(
            lambda: service.follow_up(
                str(concern_id),
                follow(data),
                str(data.idempotencyKey),
                expected_revision=data.expectedRevision,
            )
        )

    return router

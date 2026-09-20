"""Typed HTTP boundary for COM-001."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.communications.application.service import (
    CommunicationCommand, CommunicationConflictError, CommunicationError, CommunicationNotFoundError,
    CommunicationService, FollowUpInput, LinkInput, ParticipantInput, PatchCommand,
)
from app.modules.workspace.application.runtime import WorkspaceRuntime

class Contract(BaseModel): model_config = ConfigDict(extra="forbid")
class ParticipantInputModel(Contract):
    partyId: UUID; role: Literal["sender", "recipient", "reporter", "other"]; partyContactMethodId: UUID | None = None
class LinkInputModel(Contract):
    entityType: Literal["party", "property", "space", "lease", "rent_expectation", "rent_receipt", "renewal_option", "task", "maintenance_issue"]; entityId: UUID
class FollowUpInputModel(Contract):
    title: str = Field(min_length=1, max_length=240); notes: str | None = Field(default=None, max_length=10_000)
    dueAtUtc: datetime | None = None; dueTimezone: str | None = None
class CommunicationInput(Contract):
    direction: Literal["inbound", "outbound", "internal"]; channel: Literal["phone", "email", "sms", "in_person", "letter", "other"]
    subject: str = Field(min_length=1, max_length=240); body: str = Field(min_length=1, max_length=10_000)
    occurredAtUtc: datetime; occurredTimezone: str; participants: list[ParticipantInputModel] = Field(min_length=1)
    links: list[LinkInputModel] = Field(default_factory=list); followUp: FollowUpInputModel | None = None; record: bool = False; idempotencyKey: UUID
class PatchInput(Contract):
    subject: str | None = Field(default=None, min_length=1, max_length=240); body: str | None = Field(default=None, min_length=1, max_length=10_000)
    occurredAtUtc: datetime | None = None; occurredTimezone: str | None = None
    participants: list[ParticipantInputModel] | None = Field(default=None, min_length=1)
    links: list[LinkInputModel] | None = None; idempotencyKey: UUID
    @model_validator(mode="after")
    def reject_required_field_clears(self):
        required = ("subject", "body", "occurredAtUtc", "occurredTimezone", "participants", "links")
        if any(field in self.model_fields_set and getattr(self, field) is None for field in required):
            raise ValueError("PATCH cannot clear required communication fields.")
        return self
class RecordInput(Contract): idempotencyKey: UUID; followUp: FollowUpInputModel | None = None
class CorrectionInput(Contract):
    direction: Literal["inbound", "outbound", "internal"]
    channel: Literal["phone", "email", "sms", "in_person", "letter", "other"]
    subject: str = Field(min_length=1, max_length=240)
    body: str = Field(min_length=1, max_length=10_000)
    occurredAtUtc: datetime
    occurredTimezone: str
    participants: list[ParticipantInputModel] = Field(min_length=1)
    links: list[LinkInputModel] = Field(default_factory=list)
    followUp: FollowUpInputModel | None = None
    correctionReason: str = Field(min_length=1, max_length=1000)
    idempotencyKey: UUID
class ParticipantResponse(Contract):
    id: UUID; communicationId: UUID; partyId: UUID; partyContactMethodId: UUID | None = None; role: Literal["sender", "recipient", "reporter", "other"]; partyDisplayName: str; contactDisplayValue: str | None = None
class LinkResponse(Contract):
    id: UUID
    communicationId: UUID
    entityType: str
    entityId: UUID
    propertyTimezoneSnapshot: str | None = None
class FollowUpResponse(Contract): id: UUID; status: str; title: str; dueAtUtc: datetime | None = None; dueTimezone: str | None = None
class CommunicationResponse(Contract):
    id: UUID; direction: Literal["inbound", "outbound", "internal"]; channel: Literal["phone", "email", "sms", "in_person", "letter", "other"]
    subject: str; body: str; occurredAtUtc: datetime; occurredTimezone: str; status: Literal["draft", "recorded", "superseded"]
    recordedAt: datetime | None = None; supersedesCommunicationId: UUID | None = None; supersededByCommunicationId: UUID | None = None; correctionReason: str | None = None
    createdAt: datetime; updatedAt: datetime; participants: list[ParticipantResponse]; links: list[LinkResponse]; followUpTasks: list[FollowUpResponse]
class CommunicationPage(Contract): items: list[CommunicationResponse]; nextCursor: str | None = None


def build_router(service: CommunicationService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(prefix="/api/communications", tags=["communications"])
    def ready() -> None:
        if not runtime.ready or runtime.error:
            raise HTTPException(503, str(runtime.error or "Workspace is not ready."))
        if not runtime.can_write:
            raise HTTPException(503, "Workspace writer lock is unavailable.")
    def invoke(operation):
        try: return operation()
        except CommunicationNotFoundError as error: raise HTTPException(404, {"code": error.code, "message": str(error)}) from error
        except CommunicationConflictError as error: raise HTTPException(409, {"code": error.code, "message": str(error)}) from error
        except CommunicationError as error: raise HTTPException(422, {"code": error.code, "message": str(error)}) from error
        except (KeyError, ValueError) as error: raise HTTPException(422, {"code": "communication_validation", "message": str(error)}) from error
    def command(data: CommunicationInput | CorrectionInput, *, record: bool | None = None) -> CommunicationCommand:
        return CommunicationCommand(data.direction, data.channel, data.subject, data.body, data.occurredAtUtc.isoformat(), data.occurredTimezone,
            tuple(ParticipantInput(str(x.partyId), x.role, str(x.partyContactMethodId) if x.partyContactMethodId else None) for x in data.participants),
            tuple(LinkInput(x.entityType, str(x.entityId)) for x in data.links), follow_up(data.followUp), data.record if record is None else record)
    def follow_up(value: FollowUpInputModel | None) -> FollowUpInput | None:
        return None if value is None else FollowUpInput(value.title, value.notes, value.dueAtUtc.isoformat() if value.dueAtUtc else None, value.dueTimezone)
    @router.post("", response_model=CommunicationResponse, dependencies=[Depends(ready)])
    def create(payload: CommunicationInput): return invoke(lambda: service.create(command(payload), str(payload.idempotencyKey)))
    @router.get("", response_model=CommunicationPage, dependencies=[Depends(ready)])
    def list_communications(
        status: Literal["draft", "recorded", "superseded"] | None = Query(default=None),
        direction: Literal["inbound", "outbound", "internal"] | None = Query(default=None),
        channel: Literal["phone", "email", "sms", "in_person", "letter", "other"] | None = Query(default=None),
        partyId: UUID | None = Query(default=None), propertyId: UUID | None = Query(default=None), spaceId: UUID | None = Query(default=None), leaseId: UUID | None = Query(default=None),
        entityType: str | None = Query(default=None), entityId: UUID | None = Query(default=None),
        occurredOnOrAfter: date | None = Query(default=None), occurredOnOrBefore: date | None = Query(default=None),
        linkedTaskStatus: Literal["open", "in_progress", "completed", "cancelled"] | None = Query(default=None),
        pageSize: int = Query(default=100, ge=1, le=100), cursor: str | None = Query(default=None),
    ):
        contextual = [("property", propertyId), ("space", spaceId), ("lease", leaseId), (entityType, entityId)]
        if (entityType is None) != (entityId is None):
            raise HTTPException(422, {"code": "communication_validation", "message": "entityType and entityId must be provided together."})
        supplied = [(kind, value) for kind, value in contextual if value is not None]
        if len(supplied) > 1: raise HTTPException(422, {"code": "communication_validation", "message": "Use one context-link filter."})
        link_type, link_id = supplied[0] if supplied else (None, None)
        items, next_cursor = invoke(lambda: service.list(status=status, direction=direction, channel=channel,
            party_id=str(partyId) if partyId else None, entity_type=link_type, entity_id=str(link_id) if link_id else None, limit=pageSize, cursor=cursor,
            occurred_on_or_after=occurredOnOrAfter.isoformat() if occurredOnOrAfter else None, occurred_on_or_before=occurredOnOrBefore.isoformat() if occurredOnOrBefore else None, linked_task_status=linkedTaskStatus))
        return {"items": items, "nextCursor": next_cursor}
    @router.get("/{communication_id}", response_model=CommunicationResponse, dependencies=[Depends(ready)])
    def get(communication_id: UUID): return invoke(lambda: service.get(str(communication_id)))
    @router.patch("/{communication_id}", response_model=CommunicationResponse, dependencies=[Depends(ready)])
    def patch(communication_id: UUID, payload: PatchInput):
        return invoke(lambda: service.patch(str(communication_id), PatchCommand(
            payload.subject if "subject" in payload.model_fields_set else None,
            payload.body if "body" in payload.model_fields_set else None,
            payload.occurredAtUtc.isoformat() if "occurredAtUtc" in payload.model_fields_set and payload.occurredAtUtc else None,
            payload.occurredTimezone if "occurredTimezone" in payload.model_fields_set else None,
            tuple(ParticipantInput(str(x.partyId), x.role, str(x.partyContactMethodId) if x.partyContactMethodId else None) for x in payload.participants) if "participants" in payload.model_fields_set and payload.participants is not None else None,
            tuple(LinkInput(x.entityType, str(x.entityId)) for x in payload.links) if "links" in payload.model_fields_set and payload.links is not None else None,
        ), str(payload.idempotencyKey)))
    @router.post("/{communication_id}/record", response_model=CommunicationResponse, dependencies=[Depends(ready)])
    def record(communication_id: UUID, payload: RecordInput): return invoke(lambda: service.record(str(communication_id), follow_up(payload.followUp), str(payload.idempotencyKey)))
    @router.post("/{communication_id}/correct", response_model=CommunicationResponse, dependencies=[Depends(ready)])
    def correct(communication_id: UUID, payload: CorrectionInput): return invoke(lambda: service.correct(str(communication_id), command(payload, record=True), payload.correctionReason, str(payload.idempotencyKey)))
    return router

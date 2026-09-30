"""Operator-only API for retained Intake evidence."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app.modules.files.application.errors import PublicationCleanupIncomplete
from app.modules.intake.application.service import AttachmentInput, IntakeAdmissionCommand, IntakeService
from app.modules.intake.domain.models import EvidenceEnvelope, IntakeConflictError, IntakeError, IntakeNotFoundError
from app.modules.workspace.application.runtime import WorkspaceRuntime


class Contract(BaseModel): model_config=ConfigDict(extra="forbid")
class Participant(Contract): role: str=Field(min_length=1,max_length=500); display: str|None=Field(default=None,max_length=500); address: str|None=Field(default=None,max_length=500)
class SourceInput(Contract):
    sourceKind: Literal["email_message","sms_message","chat_message","operator_note","voice_transcript"]
    channel: Literal["email","sms","chat","internal","voice"]
    body: str=Field(min_length=1,max_length=131072); occurredAtUtc: datetime; subject: str|None=Field(default=None,max_length=500)
    participants: list[Participant]=Field(default_factory=list,max_length=50); provider: str|None=Field(default=None,max_length=500); conversationRef: str|None=Field(default=None,max_length=500); externalSourceId: str|None=Field(default=None,max_length=500)
    originSystem: str=Field(min_length=1,max_length=500); idempotencyKey: UUID
class CorrectInput(SourceInput): correctionReason: str=Field(min_length=1,max_length=1000)
class AttentionInput(Contract):
    reason: str=Field(min_length=1,max_length=1000)
    idempotencyKey: UUID
    expectedRevision: UUID
    expectedStatus: Literal["unprocessed","in_review","resolved","dismissed"]

def build_router(service: IntakeService, runtime: WorkspaceRuntime) -> APIRouter:
    router=APIRouter(prefix="/api/intake/sources",tags=["intake"])
    def ready():
        if not runtime.ready or runtime.error: raise HTTPException(503,str(runtime.error or "Workspace is not ready."))
        if not runtime.can_write: raise HTTPException(503,"Workspace writer lock is unavailable.")
    def call(op):
        try:return op()
        except PublicationCleanupIncomplete as error:
            # FILE-001 deliberately keeps provider locations and cleanup
            # failures private.  If attention persistence also failed, this
            # response is the operator's immediate repair signal.
            raise HTTPException(503, {"code": error.code, "message": str(error),
                                      "repairRequired": True,
                                      "attentionRecorded": error.attention_recording_failure is None}) from error
        except IntakeNotFoundError as error: raise HTTPException(404,{"code":error.code,"message":str(error)}) from error
        except IntakeConflictError as error: raise HTTPException(409,{"code":error.code,"message":str(error)}) from error
        except IntakeError as error: raise HTTPException(422,{"code":error.code,"message":str(error)}) from error
    def command(data: SourceInput):
        envelope=EvidenceEnvelope(data.sourceKind,data.channel,data.body,data.occurredAtUtc.isoformat(),data.subject,tuple(x.model_dump(exclude_none=True) for x in data.participants),data.provider,data.conversationRef,data.externalSourceId)
        return IntakeAdmissionCommand(envelope, data.originSystem, str(data.idempotencyKey))
    @router.post("",dependencies=[Depends(ready)])
    def admit(payload:SourceInput): return call(lambda:service.admit(command(payload)))
    @router.post("/import", dependencies=[Depends(ready)])
    async def import_source(metadata: str = Form(...), attachmentRoles: str | None = Form(default=None), files: list[UploadFile] = File(default=[])):
        try: data = SourceInput.model_validate(json.loads(metadata))
        except Exception as error: raise HTTPException(422, {"code": "intake_validation", "message": "Import metadata is invalid."}) from error
        if len(files) > 20: raise HTTPException(422, {"code":"intake_validation","message":"Too many attachments."})
        try:
            roles = json.loads(attachmentRoles) if attachmentRoles is not None else ["source_attachment"] * len(files)
            if not isinstance(roles, list) or len(roles) != len(files) or any(role not in {"source_attachment", "raw_source"} for role in roles): raise ValueError
        except (TypeError, ValueError, json.JSONDecodeError):
            raise HTTPException(422, {"code":"intake_validation", "message":"Attachment roles are invalid."})
        with TemporaryDirectory(prefix="intake-import-") as temporary:
            attachments=[]
            total = 0
            for position, upload in enumerate(files):
                name = upload.filename or "attachment"
                destination=Path(temporary) / str(position)
                size = 0
                with destination.open("wb") as output:
                    while chunk := await upload.read(1024 * 1024):
                        size += len(chunk); total += len(chunk)
                        if size > 50 * 1024 * 1024 or total > 100 * 1024 * 1024:
                            raise HTTPException(413, {"code":"intake_attachment_too_large", "message":"Attachment limits were exceeded."})
                        output.write(chunk)
                attachments.append(AttachmentInput(destination, name, upload.content_type, roles[position]))
            base=command(data)
            payload=IntakeAdmissionCommand(base.envelope, base.origin_system, base.idempotency_key, tuple(attachments))
            return call(lambda: service.admit(payload))
    @router.get("",dependencies=[Depends(ready)])
    def list_sources(limit:int=Query(50,ge=1,le=200),cursor:str|None=None,sourceKind:str|None=None,technicalStatus:str|None=None,attentionStatus:str|None=None,channel:str|None=None,originSystem:str|None=None,receivedFrom:datetime|None=None,receivedTo:datetime|None=None,hasDuplicate:bool|None=None):
        parsed=None
        if cursor:
            try: parsed=tuple(cursor.split("|",1)); assert len(parsed)==2
            except (AssertionError,ValueError): raise HTTPException(422,{"code":"intake_validation","message":"cursor is invalid."})
        items,next_cursor=call(lambda:service.list(limit=limit,cursor=parsed,source_kind=sourceKind,technical_status=technicalStatus,attention_status=attentionStatus,channel=channel,origin_system=originSystem,received_from=None if receivedFrom is None else receivedFrom.isoformat(),received_to=None if receivedTo is None else receivedTo.isoformat(),has_duplicate=hasDuplicate)); return {"items":items,"nextCursor":next_cursor}
    @router.get("/{source_id}",dependencies=[Depends(ready)])
    def get(source_id:UUID): return call(lambda:service.get(str(source_id)))
    @router.post("/{source_id}/correct",dependencies=[Depends(ready)])
    def correct(source_id:UUID,payload:CorrectInput): return call(lambda:service.correct(str(source_id),command(payload).envelope,payload.correctionReason,str(payload.idempotencyKey)))
    @router.post("/{source_id}/supersede", dependencies=[Depends(ready)])
    def supersede(source_id: UUID, payload: SourceInput):
        return call(lambda: service.supersede(str(source_id), command(payload)))
    @router.post("/{source_id}/dismiss",dependencies=[Depends(ready)])
    def dismiss(source_id:UUID,payload:AttentionInput): return call(lambda:service.attention(str(source_id),target="dismissed",reason=payload.reason,idempotency_key=str(payload.idempotencyKey),expected_revision=str(payload.expectedRevision),expected_status=payload.expectedStatus))
    @router.post("/{source_id}/reopen",dependencies=[Depends(ready)])
    def reopen(source_id:UUID,payload:AttentionInput): return call(lambda:service.attention(str(source_id),target="unprocessed",reason=payload.reason,idempotency_key=str(payload.idempotencyKey),expected_revision=str(payload.expectedRevision),expected_status=payload.expectedStatus))
    return router

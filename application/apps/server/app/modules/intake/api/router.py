"""Operator-only API for retained Intake evidence."""
from __future__ import annotations
from datetime import datetime
from typing import Literal
from uuid import UUID
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel, ConfigDict, Field
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
    accountScopeHash: str|None=Field(default=None,min_length=64,max_length=64); accountIdentityState: Literal["operator_confirmed","unverified_claim","not_applicable"]="not_applicable"; accountDisplayHint: str|None=Field(default=None,max_length=500)
class CorrectInput(SourceInput): correctionReason: str=Field(min_length=1,max_length=1000)
class AttentionInput(Contract): reason: str=Field(min_length=1,max_length=1000); idempotencyKey: UUID

def build_router(service: IntakeService, runtime: WorkspaceRuntime) -> APIRouter:
    router=APIRouter(prefix="/api/intake/sources",tags=["intake"])
    def ready():
        if not runtime.ready or runtime.error: raise HTTPException(503,str(runtime.error or "Workspace is not ready."))
        if not runtime.can_write: raise HTTPException(503,"Workspace writer lock is unavailable.")
    def call(op):
        try:return op()
        except IntakeNotFoundError as error: raise HTTPException(404,{"code":error.code,"message":str(error)}) from error
        except IntakeConflictError as error: raise HTTPException(409,{"code":error.code,"message":str(error)}) from error
        except IntakeError as error: raise HTTPException(422,{"code":error.code,"message":str(error)}) from error
    def command(data: SourceInput):
        envelope=EvidenceEnvelope(data.sourceKind,data.channel,data.body,data.occurredAtUtc.isoformat(),data.subject,tuple(x.model_dump(exclude_none=True) for x in data.participants),data.provider,data.conversationRef,data.externalSourceId)
        return IntakeAdmissionCommand(envelope,data.originSystem,str(data.idempotencyKey),data.accountScopeHash,data.accountIdentityState,data.accountDisplayHint)
    @router.post("",dependencies=[Depends(ready)])
    def admit(payload:SourceInput): return call(lambda:service.admit(command(payload)))
    @router.post("/import", dependencies=[Depends(ready)])
    async def import_source(metadata: str = Form(...), files: list[UploadFile] = File(default=[])):
        try: data = SourceInput.model_validate(json.loads(metadata))
        except Exception as error: raise HTTPException(422, {"code": "intake_validation", "message": "Import metadata is invalid."}) from error
        if len(files) > 20: raise HTTPException(422, {"code":"intake_validation","message":"Too many attachments."})
        with TemporaryDirectory(prefix="intake-import-") as temporary:
            attachments=[]
            for position, upload in enumerate(files):
                name = upload.filename or "attachment"
                destination=Path(temporary) / str(position)
                destination.write_bytes(await upload.read())
                attachments.append(AttachmentInput(destination, name, upload.content_type))
            base=command(data)
            payload=IntakeAdmissionCommand(base.envelope,base.origin_system,base.idempotency_key,base.account_scope_hash,base.account_identity_state,base.account_display_hint,tuple(attachments))
            return call(lambda: service.admit(payload))
    @router.get("",dependencies=[Depends(ready)])
    def list_sources(limit:int=Query(50,ge=1,le=200),cursor:str|None=None,sourceKind:str|None=None,technicalStatus:str|None=None,attentionStatus:str|None=None):
        parsed=None
        if cursor:
            try: parsed=tuple(cursor.split("|",1)); assert len(parsed)==2
            except (AssertionError,ValueError): raise HTTPException(422,{"code":"intake_validation","message":"cursor is invalid."})
        items,next_cursor=call(lambda:service.list(limit=limit,cursor=parsed,source_kind=sourceKind,technical_status=technicalStatus,attention_status=attentionStatus)); return {"items":items,"nextCursor":next_cursor}
    @router.get("/{source_id}",dependencies=[Depends(ready)])
    def get(source_id:UUID): return call(lambda:service.get(str(source_id)))
    @router.post("/{source_id}/correct",dependencies=[Depends(ready)])
    def correct(source_id:UUID,payload:CorrectInput): return call(lambda:service.correct(str(source_id),command(payload).envelope,payload.correctionReason,str(payload.idempotencyKey)))
    @router.post("/{source_id}/dismiss",dependencies=[Depends(ready)])
    def dismiss(source_id:UUID,payload:AttentionInput): return call(lambda:service.attention(str(source_id),target="dismissed",reason=payload.reason,idempotency_key=str(payload.idempotencyKey)))
    @router.post("/{source_id}/reopen",dependencies=[Depends(ready)])
    def reopen(source_id:UUID,payload:AttentionInput): return call(lambda:service.attention(str(source_id),target="unprocessed",reason=payload.reason,idempotency_key=str(payload.idempotencyKey)))
    return router

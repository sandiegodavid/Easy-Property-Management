"""Typed, deliberately non-generative HTTP surface for AI governance."""
from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from app.modules.ai_governance.application.service import AiConfigurationService, AiDraftReviewService, AiGenerationCoordinator
from app.modules.ai_governance.domain.models import AiConflictError, AiGovernanceError, AiNotFoundError, AiValidationError
from app.modules.workspace.application.runtime import WorkspaceRuntime

class Contract(BaseModel): model_config=ConfigDict(extra="forbid")
class SettingsInput(Contract): killSwitch:StrictBool|None=None; builtInEnabled:StrictBool|None=None; defaultConnectionId:UUID|None=None; idempotencyKey:UUID|None=None
class ConnectionInput(Contract): label:str=Field(min_length=1,max_length=120);adapterId:str=Field(min_length=1,max_length=80);adapterVersion:str=Field(min_length=1,max_length=80);modelIdentifier:str=Field(min_length=1,max_length=240);executionLocation:str;enabled:StrictBool=True;modelArtifactDigest:str|None=Field(None,max_length=256);quantization:str|None=Field(None,max_length=128);runtimeId:str|None=Field(None,max_length=128);runtimeVersion:str|None=Field(None,max_length=128)
class ConnectionPatch(Contract): expectedRevision:StrictInt=Field(ge=1);label:str|None=Field(None,min_length=1,max_length=120);enabled:StrictBool|None=None;modelArtifactDigest:str|None=Field(None,max_length=256);quantization:str|None=Field(None,max_length=128);runtimeId:str|None=Field(None,max_length=128);runtimeVersion:str|None=Field(None,max_length=128)
class DisclosureInput(Contract): expectedRevision:StrictInt=Field(ge=1);disclosureVersion:str=Field(min_length=1,max_length=80);dataClasses:list[str]=Field(max_length=40)
class CredentialInput(Contract): credential:str=Field(min_length=1,max_length=8192)
class LimitInput(Contract): enabled:StrictBool;connectionId:UUID|None=None;maxRunsPerUtcDay:StrictInt=Field(gt=0);maxPromptTokens:StrictInt=Field(gt=0);maxCompletionTokens:StrictInt=Field(gt=0);allowedModels:list[str]=Field(min_length=1,max_length=100)
class DraftEditInput(Contract): version:StrictInt=Field(ge=1);draftPayload:dict[str,object];operatorNote:str|None=Field(None,max_length=1000)
class DraftDecisionInput(Contract): version:StrictInt=Field(ge=1);operatorNote:str|None=Field(None,max_length=1000)

def build_router(configuration: AiConfigurationService, generation: AiGenerationCoordinator,
                 drafts_service: AiDraftReviewService, runtime: WorkspaceRuntime)->APIRouter:
    router=APIRouter(prefix="/api/ai",tags=["ai-governance"])
    def ready(write=False):
        if not runtime.ready or runtime.error:raise HTTPException(503,str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:raise HTTPException(503,"Workspace writer lock is unavailable.")
    def invoke(call):
        try:return call()
        except AiNotFoundError as error:raise HTTPException(404,{"code":error.code,"message":str(error)}) from error
        except AiConflictError as error:raise HTTPException(409,{"code":str(error) if str(error).startswith("ai_") else error.code,"message":str(error)}) from error
        except AiValidationError as error:raise HTTPException(422,{"code":error.code,"message":str(error)}) from error
        except AiGovernanceError as error:raise HTTPException(400,{"code":error.code,"message":str(error)}) from error
    @router.get("/settings",operation_id="getAiSettings")
    def settings():ready();return invoke(configuration.settings)
    @router.put("/settings",operation_id="updateAiSettings")
    def update_settings(data:SettingsInput):
        ready(True); values={"kill_switch":data.killSwitch,"built_in_enabled":data.builtInEnabled}
        if "defaultConnectionId" in data.model_fields_set: values["default_connection_id"]=None if data.defaultConnectionId is None else str(data.defaultConnectionId)
        return invoke(lambda:configuration.update_settings(**values, idempotency_key=None if data.idempotencyKey is None else str(data.idempotencyKey)))
    @router.get("/connections",operation_id="listAiConnections")
    def connections():ready();return invoke(configuration.connections)
    @router.post("/connections",status_code=status.HTTP_201_CREATED,operation_id="createAiConnection")
    def create_connection(data:ConnectionInput):ready(True);return invoke(lambda:configuration.create_connection({"label":data.label,"adapter_id":data.adapterId,"adapter_version":data.adapterVersion,"model_identifier":data.modelIdentifier,"execution_location":data.executionLocation,"enabled":data.enabled,"model_artifact_digest":data.modelArtifactDigest,"quantization":data.quantization,"runtime_id":data.runtimeId,"runtime_version":data.runtimeVersion}))
    @router.patch("/connections/{connection_id}",operation_id="updateAiConnection")
    def patch_connection(connection_id:UUID,data:ConnectionPatch):
        ready(True);payload=data.model_dump(exclude={"expectedRevision"},exclude_unset=True);names={"modelArtifactDigest":"model_artifact_digest","runtimeId":"runtime_id","runtimeVersion":"runtime_version"};return invoke(lambda:configuration.update_connection(str(connection_id),expected_revision=data.expectedRevision,data={names.get(key,key):value for key,value in payload.items()}))
    @router.put("/connections/{connection_id}/disclosure",operation_id="recordAiDisclosure")
    def disclosure(connection_id:UUID,data:DisclosureInput):ready(True);return invoke(lambda:configuration.set_disclosure(str(connection_id),expected_revision=data.expectedRevision,disclosure_version=data.disclosureVersion,data_classes=data.dataClasses))
    @router.put("/connections/{connection_id}/credential",status_code=204,operation_id="setAiCredential")
    def credential(connection_id:UUID,data:CredentialInput):ready(True);invoke(lambda:configuration.set_credential(str(connection_id),data.credential))
    @router.delete("/connections/{connection_id}/credential",status_code=204,operation_id="deleteAiCredential")
    def delete_credential(connection_id:UUID):ready(True);invoke(lambda:configuration.delete_credential(str(connection_id)))
    @router.post("/connections/{connection_id}/test",operation_id="testAiConnection")
    def test_connection(connection_id:UUID):ready();return invoke(lambda:configuration.test_connection(str(connection_id)))
    @router.get("/limits",operation_id="listAiActionLimits")
    def limits():ready();return invoke(configuration.limits)
    @router.put("/limits/{action_type}",operation_id="updateAiActionLimit")
    def limit(action_type:str,data:LimitInput):ready(True);return invoke(lambda:configuration.put_limit(action_type,{"enabled":data.enabled,"connection_id":None if data.connectionId is None else str(data.connectionId),"max_runs_per_utc_day":data.maxRunsPerUtcDay,"max_prompt_tokens":data.maxPromptTokens,"max_completion_tokens":data.maxCompletionTokens,"allowed_models":data.allowedModels}))
    @router.get("/redaction-profiles",operation_id="listAiRedactionProfiles")
    def profiles():
        ready()
        return [{"name":item.name,"version":item.version,
                 "actionTypes":[action.action_type for action in generation.actions.all()
                                if action.redaction_profile == (item.name,item.version)],
                 "fieldHandling":dict(item.summary)} for item in generation.profiles.all()]
    @router.get("/drafts",operation_id="listAiDrafts")
    def drafts(status:str|None=None,owningModule:str|None=None,entityKind:str|None=None,actionType:str|None=None,sourceEntityType:str|None=None,sourceEntityId:str|None=None,cursor:str|None=None,pageSize:int=Query(100,ge=1,le=500)):
        ready();parsed=None
        if cursor:
            parts=cursor.split("|",1)
            if len(parts)!=2:raise HTTPException(422,"Invalid AI draft cursor.")
            parsed=(parts[0],parts[1])
        return invoke(lambda:drafts_service.list_drafts(status=status,owning_module=owningModule,entity_kind=entityKind,action_type=actionType,source_entity_type=sourceEntityType,source_entity_id=sourceEntityId,cursor=parsed,page_size=pageSize))
    @router.get("/drafts/{draft_id}",operation_id="getAiDraft")
    def draft(draft_id:UUID):ready();return invoke(lambda:drafts_service.draft_detail(str(draft_id)))
    @router.patch("/drafts/{draft_id}",operation_id="editAiDraft")
    def edit(draft_id:UUID,data:DraftEditInput):ready(True);return invoke(lambda:drafts_service.edit_draft(str(draft_id),version=data.version,payload=data.draftPayload,operator_note=data.operatorNote))
    @router.post("/drafts/{draft_id}/approve",operation_id="approveAiDraft")
    def approve(draft_id:UUID,data:DraftDecisionInput):ready(True);return invoke(lambda:drafts_service.approve_draft(str(draft_id),version=data.version,operator_note=data.operatorNote))
    @router.post("/drafts/{draft_id}/dismiss",operation_id="dismissAiDraft")
    def dismiss(draft_id:UUID,data:DraftDecisionInput):ready(True);return invoke(lambda:drafts_service.dismiss_draft(str(draft_id),version=data.version,operator_note=data.operatorNote))
    return router

"""Bounded incomplete AI configuration/review forms, never provider requests."""

from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, StrictBool, StrictInt

from app.modules.operator.domain.models import Contract


class AiRevisionForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=1)


class AiSettingsForm(AiRevisionForm):
    killSwitch: StrictBool | None = None
    builtInEnabled: StrictBool | None = None
    defaultConnectionId: UUID | None = None


class AiConnectionPatchForm(AiRevisionForm):
    label: str | None = Field(None, min_length=1, max_length=120)
    enabled: StrictBool | None = None
    modelArtifactDigest: str | None = Field(None, max_length=256)
    quantization: str | None = Field(None, max_length=128)
    runtimeId: str | None = Field(None, max_length=128)
    runtimeVersion: str | None = Field(None, max_length=128)


class AiConnectionCreateForm(AiConnectionPatchForm):
    expectedRevision: StrictInt | None = Field(None, ge=0, le=0)
    adapterId: str | None = Field(None, min_length=1, max_length=80)
    adapterVersion: str | None = Field(None, min_length=1, max_length=80)
    modelIdentifier: str | None = Field(None, min_length=1, max_length=240)
    executionLocation: Literal["on_device", "cloud"] | None = None


class AiDisclosureForm(AiRevisionForm):
    disclosureVersion: str | None = Field(None, min_length=1, max_length=80)
    dataClasses: list[str] | None = Field(None, max_length=40)


class AiLimitForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=0)
    enabled: StrictBool | None = None
    connectionId: UUID | None = None
    maxRunsPerUtcDay: StrictInt | None = Field(None, gt=0)
    maxPromptTokens: StrictInt | None = Field(None, gt=0)
    maxCompletionTokens: StrictInt | None = Field(None, gt=0)
    allowedModels: list[str] | None = Field(None, min_length=1, max_length=100)


class AiDraftDecisionForm(Contract):
    version: StrictInt | None = Field(None, ge=1)
    operatorNote: str | None = Field(None, max_length=1000)


class AiDraftEditForm(AiDraftDecisionForm):
    draftPayload: dict[str, JsonValue] | None = None


AI_SCHEMAS = {
    "ai.settings.update": AiSettingsForm,
    "ai.connection.create": AiConnectionCreateForm,
    "ai.connection.update": AiConnectionPatchForm,
    "ai.connection.disclosure": AiDisclosureForm,
    "ai.action_limit.update": AiLimitForm,
    "ai.draft.edit": AiDraftEditForm,
    "ai.draft.approve": AiDraftDecisionForm,
    "ai.draft.dismiss": AiDraftDecisionForm,
    # Secret values are supplied only to the live write-only owning request.
    "ai.connection.credential.set": AiRevisionForm,
    "ai.connection.credential.delete": AiRevisionForm,
    "ai.connection.probe": AiRevisionForm,
}


def ai_source_kind(form):
    if form == "ai.connection.create":
        return None
    if form.startswith("ai.draft."):
        return "ai_draft"
    if form.startswith("ai.connection."):
        return "ai_connection"
    return "ai_settings" if form == "ai.settings.update" else "ai_action_limit"

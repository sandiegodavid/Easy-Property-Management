"""Explicit bounded local-operator Intake forms; never attachment bytes or paths."""

from typing import Literal
from uuid import UUID

from pydantic import Field, StrictInt, field_validator

from app.modules.operator.domain.models import Contract
from app.modules.intake.domain.models import utc


class IntakeParticipantForm(Contract):
    role: str | None = Field(None, max_length=500)
    display: str | None = Field(None, max_length=500)
    address: str | None = Field(None, max_length=500)


class IntakeManifestEntry(Contract):
    role: Literal["source_attachment", "raw_source"]
    contentSha256: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)


class IntakeAdmissionForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=0)
    sourceKind: (
        Literal["email_message", "sms_message", "chat_message", "operator_note", "voice_transcript"]
        | None
    ) = None
    channel: Literal["email", "sms", "chat", "internal", "voice"] | None = None
    body: str | None = Field(None, max_length=131072)
    # Keep the original textual offset: Intake retains it as occurrence context.
    occurredAtUtc: str | None = Field(None, max_length=64)
    subject: str | None = Field(None, max_length=500)
    participants: list[IntakeParticipantForm] = Field(default_factory=list, max_length=50)
    provider: str | None = Field(None, max_length=500)
    conversationRef: str | None = Field(None, max_length=500)
    externalSourceId: str | None = Field(None, max_length=500)
    originSystem: str | None = Field(None, max_length=500)

    @field_validator("occurredAtUtc")
    @classmethod
    def aware_occurrence(cls, value):
        if value is not None:
            utc(value, "occurredAtUtc")
        return value


class IntakeImportForm(IntakeAdmissionForm):
    attachments: list[IntakeManifestEntry] = Field(default_factory=list, max_length=20)


class IntakeCorrectionForm(IntakeAdmissionForm):
    expectedEvidenceRevisionId: UUID | None = None
    correctionReason: str | None = Field(None, max_length=1000)


class IntakeSupersessionForm(IntakeAdmissionForm):
    expectedEvidenceRevisionId: UUID | None = None


class IntakeAttentionForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=1)
    expectedEvidenceRevisionId: UUID | None = None
    expectedStatus: Literal["unprocessed", "in_review", "resolved", "dismissed"] | None = None
    reason: str | None = Field(None, max_length=1000)


INTAKE_SCHEMAS = {
    "intake.source.admit": IntakeAdmissionForm,
    "intake.source.import": IntakeImportForm,
    "intake.source.correct": IntakeCorrectionForm,
    "intake.source.supersede": IntakeSupersessionForm,
    "intake.source.dismiss": IntakeAttentionForm,
    "intake.source.reopen": IntakeAttentionForm,
}

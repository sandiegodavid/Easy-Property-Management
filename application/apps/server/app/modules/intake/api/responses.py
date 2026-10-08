"""Exact public contracts for Intake projections and retained command results."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StrictBool,
    StrictInt,
    model_serializer,
)

SourceKind = Literal[
    "email_message", "sms_message", "chat_message", "operator_note", "voice_transcript"
]
Channel = Literal["email", "sms", "chat", "internal", "voice"]
AttentionStatus = Literal["unprocessed", "in_review", "resolved", "dismissed"]
AttachmentRole = Literal["source_attachment", "raw_source"]
Digest = Annotated[str, Field(pattern="^[0-9a-f]{64}$")]
# Keep the existing ISO offset spelling in responses (including +00:00).
Timestamp = Annotated[
    AwareDatetime,
    PlainSerializer(lambda value: value.isoformat(), return_type=str, when_used="json"),
]


class ResponseContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProvenanceResponse(ResponseContract):
    originSystem: str
    accountIdentityState: Literal[
        "transport_verified", "operator_confirmed", "unverified_claim", "not_applicable"
    ]
    submitterKind: Literal["local_operator", "assistant_connection", "voice_workflow"]


class SourceSummaryResponse(ResponseContract):
    sourceId: UUID
    sourceKind: SourceKind
    channel: Channel
    revision: UUID
    sourceRevision: StrictInt = Field(ge=1)
    evidenceRevisionId: UUID
    updatedAt: Timestamp
    fingerprint: Digest | None
    technicalStatus: Literal["ready", "failed", "superseded"]
    failureCode: Literal["attachment_content_unavailable"] | None
    attentionStatus: AttentionStatus
    occurredAtUtc: Timestamp
    receivedAtUtc: Timestamp
    supersedesSourceId: UUID | None
    supersededBySourceId: UUID | None
    provenance: ProvenanceResponse
    attachmentCount: StrictInt = Field(ge=0)
    comparisonAvailable: StrictBool


class SourcePageResponse(ResponseContract):
    items: list[SourceSummaryResponse]
    nextCursor: str | None


class EvidenceParticipantResponse(ResponseContract):
    role: str
    display: str | None = None
    address: str | None = None

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        # Canonical participants omit absent optional keys; do not add nulls.
        return {key: value for key, value in handler(self).items() if key in self.model_fields_set}


class EvidenceAttachmentResponse(ResponseContract):
    role: AttachmentRole
    contentSha256: Digest


class EvidenceResponse(ResponseContract):
    schemaVersion: Literal[1]
    sourceKind: SourceKind
    channel: Channel
    subject: str | None
    body: str
    participants: list[EvidenceParticipantResponse]
    occurredAtUtc: Timestamp
    occurredAtContext: str
    provider: str | None
    conversationRef: str | None
    externalSourceId: str | None
    attachments: list[EvidenceAttachmentResponse]


class EvidenceRevisionResponse(ResponseContract):
    id: UUID
    number: StrictInt = Field(ge=1)
    kind: Literal["submitted", "operator_correction", "transcript_revision"]
    createdAt: Timestamp
    correctionReason: str | None


class AttachmentFileResponse(ResponseContract):
    link_id: UUID
    file_id: UUID
    original_name: str
    media_type: str | None
    size_bytes: StrictInt = Field(ge=0)
    content_sha256: Digest
    storage_state: Literal["available", "missing", "quarantined"]
    verified_at: Timestamp | None


class AttachmentResponse(ResponseContract):
    fileLinkId: UUID
    role: AttachmentRole
    displayOrder: StrictInt = Field(ge=0)
    file: AttachmentFileResponse | None


class OperationResponse(ResponseContract):
    type: Literal[
        "admit",
        "integrity_failed",
        "integrity_restored",
        "correct",
        "supersede",
        "attention_transition",
    ]
    outcome: Literal["succeeded", "failed"]
    createdAt: Timestamp


class DuplicateCandidateResponse(ResponseContract):
    sourceId: UUID
    candidateSourceId: UUID
    reason: Literal["content_fingerprint", "conversation_similarity"]
    disposition: Literal["unreviewed", "distinct", "same_source"]


class SourceDetailResponse(SourceSummaryResponse):
    fingerprint: Digest
    evidence: EvidenceResponse
    revisions: list[EvidenceRevisionResponse]
    attachments: list[AttachmentResponse]
    operations: list[OperationResponse]
    duplicateCandidates: list[DuplicateCandidateResponse]


class SourceMutationResponse(SourceSummaryResponse):
    operationId: UUID


class CorrectionResponse(SourceDetailResponse):
    operationId: UUID


# Recovery returns the immutable original result, rather than current source state.
CommandReceiptResponse = CorrectionResponse | SourceMutationResponse


class ConflictDetailResponse(ResponseContract):
    code: str
    message: str


class RevisionConflictDetailResponse(ConflictDetailResponse):
    currentRevision: StrictInt = Field(ge=1)
    currentEvidenceRevisionId: UUID
    currentAttentionStatus: AttentionStatus


class ConflictResponse(ResponseContract):
    detail: RevisionConflictDetailResponse | ConflictDetailResponse

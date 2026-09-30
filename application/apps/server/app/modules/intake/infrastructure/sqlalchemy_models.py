"""Current SQLite persistence schema for INGEST-001."""
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from app.platform.sqlalchemy_models import LocalBase


class IntakeSourceModel(LocalBase):
    __tablename__ = "intake_sources"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[str] = mapped_column(String, nullable=False)
    origin_system: Mapped[str] = mapped_column(String, nullable=False)
    external_source_id: Mapped[str | None] = mapped_column(String)
    conversation_ref: Mapped[str | None] = mapped_column(String)
    account_scope_hash: Mapped[str | None] = mapped_column(String)
    account_identity_state: Mapped[str] = mapped_column(String, nullable=False)
    account_display_hint: Mapped[str | None] = mapped_column(String)
    submitter_kind: Mapped[str] = mapped_column(String, nullable=False)
    submitter_reference: Mapped[str | None] = mapped_column(String)
    occurred_at_utc: Mapped[str] = mapped_column(String, nullable=False)
    received_at_utc: Mapped[str] = mapped_column(String, nullable=False)
    technical_status: Mapped[str] = mapped_column(String, nullable=False)
    attention_status: Mapped[str] = mapped_column(String, nullable=False)
    current_revision_id: Mapped[str] = mapped_column(ForeignKey("intake_evidence_revisions.id", use_alter=True), nullable=False)
    supersedes_source_id: Mapped[str | None] = mapped_column(ForeignKey("intake_sources.id"), unique=True)
    superseded_by_source_id: Mapped[str | None] = mapped_column(ForeignKey("intake_sources.id"), unique=True)
    failure_code: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("source_kind IN ('email_message','sms_message','chat_message','operator_note','voice_transcript')"),
        CheckConstraint("channel IN ('email','sms','chat','internal','voice')"),
        CheckConstraint("(source_kind='email_message' AND channel='email') OR (source_kind='sms_message' AND channel='sms') OR (source_kind='chat_message' AND channel='chat') OR (source_kind='operator_note' AND channel='internal') OR (source_kind='voice_transcript' AND channel='voice')"),
        CheckConstraint("account_identity_state IN ('transport_verified','operator_confirmed','unverified_claim','not_applicable')"),
        CheckConstraint("submitter_kind IN ('local_operator','assistant_connection','voice_workflow')"),
        CheckConstraint("technical_status IN ('ready','failed','superseded')"),
        CheckConstraint("(technical_status != 'failed' AND failure_code IS NULL) OR (technical_status = 'failed' AND failure_code IN ('attachment_content_unavailable'))"),
        CheckConstraint("attention_status IN ('unprocessed','in_review','resolved','dismissed')"),
        CheckConstraint("length(trim(origin_system)) BETWEEN 1 AND 500"),
        Index("intake_sources_received", "received_at_utc", "id"),
        Index("intake_sources_status", "technical_status", "attention_status", "received_at_utc", "id"),
        Index("intake_sources_trusted_external", "origin_system", "account_scope_hash", "source_kind", "external_source_id", unique=True,
              sqlite_where=text("account_identity_state IN ('transport_verified','operator_confirmed') AND external_source_id IS NOT NULL AND superseded_by_source_id IS NULL")),
    )


class IntakeEvidenceRevisionModel(LocalBase):
    __tablename__ = "intake_evidence_revisions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("intake_sources.id"), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    envelope_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_kind: Mapped[str] = mapped_column(String, nullable=False)
    envelope_json: Mapped[str] = mapped_column(String, nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    correction_reason: Mapped[str | None] = mapped_column(String)
    actor_kind: Mapped[str] = mapped_column(String, nullable=False)
    actor_reference: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    supersedes_revision_id: Mapped[str | None] = mapped_column(ForeignKey("intake_evidence_revisions.id"), unique=True)
    superseded_by_revision_id: Mapped[str | None] = mapped_column(ForeignKey("intake_evidence_revisions.id"), unique=True)
    __table_args__ = (CheckConstraint("revision_number > 0"), CheckConstraint("envelope_schema_version = 1"), CheckConstraint("revision_kind IN ('submitted','operator_correction','transcript_revision')"), CheckConstraint("length(content_fingerprint)=64"), UniqueConstraint("source_id", "revision_number", name="intake_revision_number"), Index("intake_revisions_source", "source_id", "revision_number"))


class IntakeRevisionFileLinkModel(LocalBase):
    __tablename__ = "intake_revision_file_links"
    revision_id: Mapped[str] = mapped_column(ForeignKey("intake_evidence_revisions.id"), primary_key=True)
    file_link_id: Mapped[str] = mapped_column(ForeignKey("file_links.id"), primary_key=True)
    attachment_role: Mapped[str] = mapped_column(String, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (CheckConstraint("attachment_role IN ('source_attachment','raw_source')"), CheckConstraint("display_order >= 0"), UniqueConstraint("revision_id", "display_order", name="intake_revision_attachment_order"))


class IntakeSourceOperationModel(LocalBase):
    __tablename__ = "intake_source_operations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    operation_type: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("intake_sources.id"), nullable=False)
    result_revision_id: Mapped[str | None] = mapped_column(ForeignKey("intake_evidence_revisions.id"))
    result_json: Mapped[str | None] = mapped_column(String)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    actor_kind: Mapped[str] = mapped_column(String, nullable=False)
    actor_reference: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (CheckConstraint("operation_type IN ('admit','integrity_failed','integrity_restored','correct','supersede','attention_transition')"), CheckConstraint("outcome IN ('succeeded','failed')"), CheckConstraint("length(request_fingerprint)=64"), Index("intake_operations_source", "source_id", "created_at"))


class IntakeDuplicateCandidateModel(LocalBase):
    __tablename__ = "intake_source_duplicate_candidates"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("intake_sources.id"), nullable=False)
    candidate_source_id: Mapped[str] = mapped_column(ForeignKey("intake_sources.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    confidence_label: Mapped[str] = mapped_column(String, nullable=False)
    confidence_provenance: Mapped[str] = mapped_column(String, nullable=False)
    disposition: Mapped[str] = mapped_column(String, nullable=False)
    decided_at: Mapped[str | None] = mapped_column(String)
    decision_reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (CheckConstraint("source_id < candidate_source_id"), CheckConstraint("reason IN ('content_fingerprint','conversation_similarity')"), CheckConstraint("confidence_label IN ('low','medium','high')"), CheckConstraint("disposition IN ('unreviewed','distinct','same_source')"), UniqueConstraint("source_id", "candidate_source_id", "reason", name="intake_duplicate_pair"))

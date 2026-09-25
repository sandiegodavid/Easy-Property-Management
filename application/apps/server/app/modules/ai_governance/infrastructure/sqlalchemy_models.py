"""SQLite persistence owned by the AI governance module."""
from __future__ import annotations
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.platform.sqlalchemy_models import LocalBase


class AiSettingsModel(LocalBase):
    __tablename__ = "ai_settings"
    singleton: Mapped[int] = mapped_column(Integer, primary_key=True)
    kill_switch: Mapped[bool] = mapped_column(Integer, nullable=False, default=False)
    built_in_enabled: Mapped[bool] = mapped_column(Integer, nullable=False, default=False)
    default_connection_id: Mapped[str | None] = mapped_column(ForeignKey("ai_model_connections.id"))
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("singleton=1"),
        CheckConstraint("kill_switch IN (0,1) AND built_in_enabled IN (0,1)"),
    )


class AiSettingsOperationModel(LocalBase):
    __tablename__ = "ai_settings_operations"
    idempotency_key: Mapped[str] = mapped_column(String, primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (CheckConstraint("length(request_fingerprint)=64"),)


class AiModelConnectionModel(LocalBase):
    __tablename__ = "ai_model_connections"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    adapter_id: Mapped[str] = mapped_column(String, nullable=False)
    adapter_version: Mapped[str] = mapped_column(String, nullable=False)
    model_identifier: Mapped[str] = mapped_column(String, nullable=False)
    execution_location: Mapped[str] = mapped_column(String, nullable=False)
    model_artifact_digest: Mapped[str | None] = mapped_column(String)
    quantization: Mapped[str | None] = mapped_column(String)
    runtime_id: Mapped[str | None] = mapped_column(String)
    runtime_version: Mapped[str | None] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Integer, nullable=False)
    cloud_data_classes: Mapped[str] = mapped_column(Text, nullable=False)
    disclosure_version: Mapped[str | None] = mapped_column(String)
    disclosure_accepted_at: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("revision >= 1"), CheckConstraint("execution_location IN ('on_device','cloud')"),
        CheckConstraint("enabled IN (0,1)"), CheckConstraint("length(trim(label)) BETWEEN 1 AND 120"),
        CheckConstraint("length(adapter_id) BETWEEN 1 AND 80 AND length(adapter_version) BETWEEN 1 AND 80 AND length(model_identifier) BETWEEN 1 AND 240"),
        Index("ai_model_connections_enabled", "enabled", "execution_location"),
    )


class AiActionLimitModel(LocalBase):
    __tablename__ = "ai_action_limits"
    action_type: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Integer, nullable=False)
    connection_id: Mapped[str | None] = mapped_column(ForeignKey("ai_model_connections.id"))
    max_runs_per_utc_day: Mapped[int] = mapped_column(Integer, nullable=False)
    max_prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    max_completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    allowed_models: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (CheckConstraint("enabled IN (0,1)"), CheckConstraint("max_runs_per_utc_day>0 AND max_prompt_tokens>0 AND max_completion_tokens>0"),)


class AiRunModel(LocalBase):
    __tablename__ = "ai_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    execution_kind: Mapped[str] = mapped_column(String, nullable=False)
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    owning_module: Mapped[str] = mapped_column(String, nullable=False)
    source_entity_type: Mapped[str] = mapped_column(String, nullable=False)
    source_entity_id: Mapped[str] = mapped_column(String, nullable=False)
    source_revision: Mapped[str] = mapped_column(String, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    requested_supersedes_draft_id: Mapped[str | None] = mapped_column(ForeignKey("ai_drafts.id"))
    connection_id: Mapped[str | None] = mapped_column(ForeignKey("ai_model_connections.id"))
    configuration_revision: Mapped[int | None] = mapped_column(Integer)
    transport_provider: Mapped[str | None] = mapped_column(String)
    adapter_version: Mapped[str | None] = mapped_column(String)
    model_identifier: Mapped[str | None] = mapped_column(String)
    execution_location: Mapped[str | None] = mapped_column(String)
    model_artifact_digest: Mapped[str | None] = mapped_column(String)
    quantization: Mapped[str | None] = mapped_column(String)
    runtime_id: Mapped[str | None] = mapped_column(String)
    runtime_version: Mapped[str | None] = mapped_column(String)
    assistant_name: Mapped[str | None] = mapped_column(String)
    assistant_connection_id: Mapped[str | None] = mapped_column(String)
    delegation_id: Mapped[str | None] = mapped_column(String)
    reported_model_identifier: Mapped[str | None] = mapped_column(String)
    prompt_template_id: Mapped[str | None] = mapped_column(String)
    prompt_template_version: Mapped[int | None] = mapped_column(Integer)
    output_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    redaction_profile: Mapped[str] = mapped_column(String, nullable=False)
    redaction_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    governed_input_json: Mapped[str] = mapped_column(Text, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    provider_request_id: Mapped[str | None] = mapped_column(String)
    error_code: Mapped[str | None] = mapped_column(String)
    error_detail: Mapped[str | None] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[str | None] = mapped_column(String)
    finished_at: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("execution_kind IN ('provider_generation','external_proposal')"),
        CheckConstraint("status IN ('reserved','running','succeeded','failed','blocked')"),
        CheckConstraint("length(input_fingerprint)=64 AND length(request_fingerprint)=64 AND length(source_fingerprint)=64"),
        CheckConstraint("(status IN ('failed','blocked')) = (error_code IS NOT NULL)"),
        Index("ai_runs_action_status_started", "action_type", "status", "started_at"),
        Index("ai_runs_source", "source_entity_type", "source_entity_id", "created_at"),
    )


class AiDraftModel(LocalBase):
    __tablename__ = "ai_drafts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("ai_runs.id"), nullable=False, unique=True)
    entity_kind: Mapped[str] = mapped_column(String, nullable=False)
    draft_payload: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False)
    supersedes_draft_id: Mapped[str | None] = mapped_column(ForeignKey("ai_drafts.id"), unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    terminal_at: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (CheckConstraint("status IN ('proposed','edited','approved','dismissed','superseded')"), CheckConstraint("version>=1"), CheckConstraint("(status IN ('approved','dismissed','superseded')) = (terminal_at IS NOT NULL)"), Index("ai_drafts_status_updated", "status", "updated_at"))


class AiReviewDecisionModel(LocalBase):
    __tablename__ = "ai_review_decisions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("ai_drafts.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    draft_version_before: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_version_after: Mapped[int] = mapped_column(Integer, nullable=False)
    operator_note: Mapped[str | None] = mapped_column(String)
    result_entity_type: Mapped[str | None] = mapped_column(String)
    result_entity_id: Mapped[str | None] = mapped_column(String)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    decided_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (CheckConstraint("decision IN ('edited','approved','dismissed')"), CheckConstraint("draft_version_after>=draft_version_before"), Index("ai_review_decisions_draft", "draft_id", "decided_at"))

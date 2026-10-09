"""SQLite persistence owned by the AI governance module."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase


class AiSettingsModel(LocalBase):
    __tablename__ = "ai_settings"
    singleton: Mapped[int] = mapped_column(Integer, primary_key=True)
    kill_switch: Mapped[bool] = mapped_column(Integer, nullable=False, default=False)
    built_in_enabled: Mapped[bool] = mapped_column(Integer, nullable=False, default=False)
    default_connection_id: Mapped[str | None] = mapped_column(ForeignKey("ai_model_connections.id"))
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        CheckConstraint("singleton=1"),
        CheckConstraint("typeof(revision)='integer' AND revision>=1"),
        CheckConstraint("kill_switch IN (0,1) AND built_in_enabled IN (0,1)"),
    )


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
        CheckConstraint("revision >= 1"),
        CheckConstraint("execution_location IN ('on_device','cloud')"),
        CheckConstraint("enabled IN (0,1)"),
        CheckConstraint("length(trim(label)) BETWEEN 1 AND 120"),
        CheckConstraint(
            "length(adapter_id) BETWEEN 1 AND 80 AND length(adapter_version) BETWEEN 1 AND 80 AND length(model_identifier) BETWEEN 1 AND 240"
        ),
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
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        CheckConstraint("enabled IN (0,1)"),
        CheckConstraint("typeof(revision)='integer' AND revision>=1"),
        CheckConstraint(
            "max_runs_per_utc_day>0 AND max_prompt_tokens>0 AND max_completion_tokens>0"
        ),
    )


class AiCommandOperationModel(LocalBase):
    __tablename__ = "ai_command_operations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[str] = mapped_column(String, nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint(
            "length(id)=36 AND length(idempotency_key)=36 AND length(correlation_id)=36"
        ),
        CheckConstraint(
            "length(request_fingerprint)=64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'"
        ),
        CheckConstraint(
            "action IN ('settings','connection_create','connection_update','disclosure','limit','edited','dismissed','approved')"
        ),
        CheckConstraint("json_valid(request_json) AND json_valid(result_json)"),
        Index("ai_commands_target", "target_id", "created_at"),
    )


class AiExternalOperationModel(LocalBase):
    __tablename__ = "ai_external_operations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("ai_model_connections.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint(
            "length(id)=36 AND length(idempotency_key)=36 AND length(correlation_id)=36"
        ),
        CheckConstraint("action IN ('credential_set','credential_delete','connection_probe')"),
        CheckConstraint("typeof(expected_revision)='integer' AND expected_revision>=1"),
        CheckConstraint("typeof(revision)='integer' AND revision=expected_revision+1"),
        CheckConstraint(
            "length(request_fingerprint)=64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'"
        ),
        CheckConstraint("json_valid(request_json)"),
        CheckConstraint("(result_json IS NULL) = (completed_at IS NULL)"),
        CheckConstraint(
            "result_json IS NULL OR (json_valid(result_json) AND json_extract(result_json,'$.status') IN ('completed','abandoned'))"
        ),
        Index("ai_external_connection", "connection_id", "created_at"),
        Index(
            "ai_external_pending_connection",
            "connection_id",
            unique=True,
            sqlite_where=text("result_json IS NULL"),
        ),
    )


EXTERNAL_TRIGGERS = {
    "ai_external_no_delete": "CREATE TRIGGER ai_external_no_delete BEFORE DELETE ON ai_external_operations BEGIN SELECT RAISE(ABORT, 'AI external intents are retained'); END",
    "ai_external_no_replace": "CREATE TRIGGER ai_external_no_replace BEFORE INSERT ON ai_external_operations WHEN EXISTS (SELECT 1 FROM ai_external_operations WHERE id=NEW.id OR idempotency_key=NEW.idempotency_key) BEGIN SELECT RAISE(ABORT, 'AI external intents are retained'); END",
    "ai_external_finish_only": "CREATE TRIGGER ai_external_finish_only BEFORE UPDATE ON ai_external_operations WHEN OLD.result_json IS NOT NULL OR NEW.result_json IS NULL OR NEW.completed_at IS NULL OR NEW.id IS NOT OLD.id OR NEW.idempotency_key IS NOT OLD.idempotency_key OR NEW.connection_id IS NOT OLD.connection_id OR NEW.action IS NOT OLD.action OR NEW.revision IS NOT OLD.revision OR NEW.expected_revision IS NOT OLD.expected_revision OR NEW.request_json IS NOT OLD.request_json OR NEW.request_fingerprint IS NOT OLD.request_fingerprint OR NEW.correlation_id IS NOT OLD.correlation_id OR NEW.created_at IS NOT OLD.created_at BEGIN SELECT RAISE(ABORT, 'AI external intent and completed result are immutable'); END",
}


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
        CheckConstraint(
            "length(input_fingerprint)=64 AND length(request_fingerprint)=64 AND length(source_fingerprint)=64"
        ),
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
    __table_args__ = (
        CheckConstraint("status IN ('proposed','edited','approved','dismissed','superseded')"),
        CheckConstraint("version>=1"),
        CheckConstraint(
            "(status IN ('approved','dismissed','superseded')) = (terminal_at IS NOT NULL)"
        ),
        Index("ai_drafts_status_updated", "status", "updated_at"),
    )


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
    __table_args__ = (
        CheckConstraint("decision IN ('edited','approved','dismissed')"),
        CheckConstraint("draft_version_after>=draft_version_before"),
        Index("ai_review_decisions_draft", "draft_id", "decided_at"),
    )

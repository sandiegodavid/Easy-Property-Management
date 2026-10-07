"""Current greenfield OPS schema and append-only receipt/review inventory."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase


class OperatorPreferenceModel(LocalBase):
    __tablename__ = "operator_preferences"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    appearance: Mapped[str] = mapped_column(String, nullable=False)
    destination_order: Mapped[str] = mapped_column(String, nullable=False)
    hidden_destination_ids: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("id = 'workspace'"),
        CheckConstraint("appearance IN ('light','dark')"),
        CheckConstraint("json_valid(destination_order) AND json_type(destination_order) = 'array'"),
        CheckConstraint(
            "json_valid(hidden_destination_ids) AND json_type(hidden_destination_ids) = 'array'"
        ),
        CheckConstraint("typeof(revision) = 'integer' AND revision >= 1"),
    )


class OperatorRecoveryModel(LocalBase):
    __tablename__ = "operator_recovery_records"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    form_key: Mapped[str] = mapped_column(String, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str | None] = mapped_column(String)
    source_id: Mapped[str | None] = mapped_column(String)
    base_source_revision: Mapped[str | None] = mapped_column(String)
    payload_json: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    attempt_key: Mapped[str | None] = mapped_column(String)
    request_fingerprint: Mapped[str | None] = mapped_column(String)
    receipt_json: Mapped[str | None] = mapped_column(String)
    saved_at: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("length(id) = 36"),
        CheckConstraint(
            "form_key IN ('task.create','maintenance.issue.create','communication.record')"
        ),
        CheckConstraint("typeof(schema_version) = 'integer' AND schema_version >= 1"),
        CheckConstraint("typeof(revision) = 'integer' AND revision >= 1"),
        CheckConstraint(
            "json_valid(payload_json) AND json_type(payload_json) = 'object' AND length(cast(payload_json AS BLOB)) <= 65536"
        ),
        CheckConstraint(
            "status IN ('active','outcome_unknown','reconciled','discarded','expired')"
        ),
        CheckConstraint(
            "(source_kind IS NULL AND source_id IS NULL AND base_source_revision IS NULL) OR (source_kind IS NOT NULL AND source_id IS NOT NULL)"
        ),
        CheckConstraint(
            "(attempt_key IS NULL AND request_fingerprint IS NULL) OR (length(attempt_key) = 36 AND length(request_fingerprint) = 64)"
        ),
        CheckConstraint(
            "status != 'outcome_unknown' OR (attempt_key IS NOT NULL AND receipt_json IS NULL)"
        ),
        CheckConstraint("status != 'reconciled' OR receipt_json IS NOT NULL"),
        CheckConstraint("receipt_json IS NULL OR json_valid(receipt_json)"),
        Index("operator_recovery_status_saved", "status", "saved_at", "id"),
        Index("operator_recovery_status_expiry", "status", "expires_at", "id"),
    )


class OperatorOperationModel(LocalBase):
    __tablename__ = "operator_operations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    request_json: Mapped[str] = mapped_column(String, nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    result_json: Mapped[str] = mapped_column(String, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    recovery_id: Mapped[str | None] = mapped_column(ForeignKey("operator_recovery_records.id"))
    __table_args__ = (
        CheckConstraint(
            "length(id) = 36 AND length(idempotency_key) = 36 AND length(correlation_id) = 36"
        ),
        CheckConstraint("entity_type IN ('operator_preferences','operator_recovery')"),
        CheckConstraint("action IN ('updated','saved','discarded','expired','reconciled')"),
        CheckConstraint(
            "length(request_fingerprint) = 64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'"
        ),
        CheckConstraint("json_valid(request_json) AND json_type(request_json) = 'object'"),
        CheckConstraint("typeof(expected_revision) = 'integer' AND expected_revision >= 0"),
        CheckConstraint(
            "typeof(resulting_revision) = 'integer' AND resulting_revision = expected_revision + 1"
        ),
        CheckConstraint("json_valid(result_json) AND json_type(result_json) = 'object'"),
        Index("operator_operations_entity_time", "entity_type", "entity_id", "created_at"),
    )


MODELS = (
    OperatorPreferenceModel,
    OperatorRecoveryModel,
    OperatorOperationModel,
)
APPEND_ONLY = ("operator_operations",)


def trigger_sql(table, action):
    return f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'operator history is append-only'); END"

"""SQLAlchemy-owned FILE-001 schema."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase


class FileRecordModel(LocalBase):
    __tablename__ = "file_records"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    original_name: Mapped[str] = mapped_column(String, nullable=False)
    media_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(
        Integer, CheckConstraint("size_bytes >= 0"), nullable=False
    )
    content_sha256: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (Index("file_records_content", "content_sha256"),)


class FileLinkModel(LocalBase):
    __tablename__ = "file_links"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("file_records.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String)
    archive_reason: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint(
            "(archived_at IS NULL AND archive_reason IS NULL) OR (archived_at IS NOT NULL AND archive_reason IS NOT NULL AND length(trim(archive_reason)) BETWEEN 1 AND 1000)"
        ),
        Index("file_links_entity", "entity_type", "entity_id"),
        Index(
            "file_links_one_active_association",
            "file_id",
            "entity_type",
            "entity_id",
            "purpose",
            unique=True,
            sqlite_where=text("archived_at IS NULL"),
        ),
    )


class FileContentLocationModel(LocalBase):
    __tablename__ = "file_content_locations"
    file_id: Mapped[str] = mapped_column(ForeignKey("file_records.id"), primary_key=True)
    storage_provider: Mapped[str] = mapped_column(String, nullable=False)
    storage_state: Mapped[str] = mapped_column(String, nullable=False)
    local_relative_path: Mapped[str | None] = mapped_column(String)
    s3_bucket: Mapped[str | None] = mapped_column(String)
    s3_object_key: Mapped[str | None] = mapped_column(String)
    s3_version_id: Mapped[str | None] = mapped_column(String)
    provider_etag: Mapped[str | None] = mapped_column(String)
    verified_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("storage_provider IN ('local', 's3')"),
        CheckConstraint("storage_state IN ('available', 'missing', 'quarantined')"),
        CheckConstraint(
            "(storage_provider = 'local' AND local_relative_path IS NOT NULL AND s3_bucket IS NULL AND s3_object_key IS NULL AND s3_version_id IS NULL) OR (storage_provider = 's3' AND local_relative_path IS NULL AND s3_bucket IS NOT NULL AND s3_object_key IS NOT NULL AND s3_version_id IS NOT NULL)"
        ),
        Index(
            "file_content_locations_provider",
            "storage_provider",
            "local_relative_path",
            "s3_bucket",
            "s3_object_key",
        ),
    )


class FilePublicationCleanupAttentionModel(LocalBase):
    """Durable operational attention for a publication that could not be cleaned up.

    The publication ID is deliberately the primary key: it is the only safe
    identity available when storage metadata could not be committed.
    """

    __tablename__ = "file_publication_cleanup_attentions"
    publication_id: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    opened_at: Mapped[str] = mapped_column(String, nullable=False)
    resolved_at: Mapped[str | None] = mapped_column(String)


class FileCommandOperationModel(LocalBase):
    __tablename__ = "file_command_operations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    request_json: Mapped[str] = mapped_column(String, nullable=False)
    file_id: Mapped[str] = mapped_column(ForeignKey("file_records.id"), nullable=False)
    link_id: Mapped[str] = mapped_column(ForeignKey("file_links.id"), nullable=False)
    result_json: Mapped[str] = mapped_column(String, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("action IN ('upload', 'archive_link')"),
        CheckConstraint(
            "length(request_fingerprint) = 64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'"
        ),
        CheckConstraint("json_valid(request_json) AND json_type(request_json) = 'object'"),
        CheckConstraint("json_valid(result_json) AND json_type(result_json) = 'object'"),
        Index("file_command_operations_key", "idempotency_key", unique=True),
    )

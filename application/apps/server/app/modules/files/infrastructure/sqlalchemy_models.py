"""SQLAlchemy-owned FILE-001 schema."""
from __future__ import annotations
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.platform.sqlalchemy_models import LocalBase

class FileRecordModel(LocalBase):
    __tablename__ = "file_records"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    original_name: Mapped[str] = mapped_column(String, nullable=False)
    media_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, CheckConstraint("size_bytes >= 0"), nullable=False)
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
    __table_args__ = (Index("file_links_entity", "entity_type", "entity_id"),)


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
        CheckConstraint("storage_state IN ('pending', 'available', 'missing', 'quarantined')"),
        CheckConstraint("(storage_provider = 'local' AND local_relative_path IS NOT NULL AND s3_bucket IS NULL AND s3_object_key IS NULL AND s3_version_id IS NULL) OR (storage_provider = 's3' AND local_relative_path IS NULL AND s3_bucket IS NOT NULL AND s3_object_key IS NOT NULL)"),
        Index("file_content_locations_provider", "storage_provider", "local_relative_path", "s3_bucket", "s3_object_key"),
    )

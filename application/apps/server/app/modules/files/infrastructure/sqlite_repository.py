"""SQLAlchemy adapter for FILE-001 metadata and its audit transaction."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.files.application.ports import FileAuditChange, FileLink
from app.modules.files.domain.models import StoredFile
from app.modules.files.infrastructure.sqlalchemy_models import (
    FileContentLocationModel,
    FileLinkModel,
    FilePublicationCleanupAttentionModel,
    FileRecordModel,
)
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction


class SQLiteFileUnitOfWork:
    def __init__(self, database: Path, recorder: AuditRecorder) -> None:
        self.engine = create_sqlite_engine(database)
        self.recorder = recorder

    def write(self, item: StoredFile, link: FileLink | None, audit_changes: list[FileAuditChange], validate_link=None) -> None:
        with immediate_transaction(self.engine) as connection:
            if link is not None and validate_link is not None:
                validate_link(connection, link)
            self.write_in_transaction(connection, item, link, audit_changes)

    def write_in_transaction(self, connection, item: StoredFile, link: FileLink | None, audit_changes: list[FileAuditChange]) -> None:
            connection.execute(FileRecordModel.__table__.insert().values(
                id=item.id, original_name=item.original_name, media_type=item.media_type,
                size_bytes=item.size_bytes, content_sha256=item.content_sha256, created_at=item.created_at,
            ))
            connection.execute(FileContentLocationModel.__table__.insert().values(
                file_id=item.id, storage_provider=item.storage_provider,
                storage_state=item.storage_state, local_relative_path=item.local_relative_path,
                s3_bucket=item.s3_bucket, s3_object_key=item.s3_object_key,
                s3_version_id=item.s3_version_id, provider_etag=item.provider_etag,
                verified_at=item.verified_at,
            ))
            raw = connection.connection.driver_connection
            if link is not None:
                connection.execute(FileLinkModel.__table__.insert().values(
                    id=link.id, file_id=item.id, entity_type=link.entity_type, entity_id=link.entity_id,
                    purpose=link.purpose, created_at=link.created_at, archived_at=None, archive_reason=None,
                ))
            for change in audit_changes:
                self.recorder.record_change(raw, entity_type=change.entity_type, entity_id=change.entity_id,
                                            action=change.action, before=change.before, after=change.after,
                                            reason=change.reason, correlation_id=change.correlation_id,
                                            actor_kind=change.actor_kind)

    def get(self, file_id: str) -> StoredFile | None:
        with Session(self.engine) as session:
            record = session.execute(select(FileRecordModel).where(FileRecordModel.id == file_id)).scalar_one_or_none()
            if record is None:
                return None
            location = session.get(FileContentLocationModel, file_id)
            if location is None:
                return None
            links = session.execute(select(FileLinkModel).where(FileLinkModel.file_id == file_id).order_by(FileLinkModel.created_at, FileLinkModel.id)).scalars()
            return StoredFile(record.id, record.original_name, record.media_type, record.size_bytes,
                              record.content_sha256, location.storage_provider, location.storage_state,
                              location.local_relative_path, location.s3_bucket, location.s3_object_key,
                              location.s3_version_id, location.provider_etag, location.verified_at, record.created_at,
                              links=tuple({"id": link.id, "entityType": link.entity_type, "entityId": link.entity_id,
                                           "purpose": link.purpose, "createdAt": link.created_at,
                                           "archivedAt": link.archived_at, "archiveReason": link.archive_reason} for link in links))
    def get_link(self, link_id: str) -> FileLink | None:
        with Session(self.engine) as session:
            row = session.get(FileLinkModel, link_id)
            if row is None:
                return None
            return FileLink(row.id, row.entity_type, row.entity_id, row.purpose, row.created_at, row.file_id, row.archived_at, row.archive_reason)
    def archive_link(self, link: FileLink, audit_change: FileAuditChange, validate_link) -> FileLink:
        with immediate_transaction(self.engine) as connection:
            validate_link(connection, link)
            result = connection.execute(FileLinkModel.__table__.update().where(
                FileLinkModel.id == link.id,
                FileLinkModel.archived_at.is_(None),
            ).values(archived_at=link.archived_at, archive_reason=link.archive_reason))
            if result.rowcount != 1:
                raise ValueError("File link is already archived or no longer exists.")
            self.recorder.record_change(connection.connection.driver_connection, entity_type=audit_change.entity_type,
                entity_id=audit_change.entity_id, action=audit_change.action, before=audit_change.before,
                after=audit_change.after, reason=audit_change.reason, correlation_id=audit_change.correlation_id,
                actor_kind=audit_change.actor_kind)
        return link

    def link_existing(self, link: FileLink, audit_change: FileAuditChange, validate_link) -> FileLink:
        with immediate_transaction(self.engine) as connection:
            validate_link(connection, link)
            location = connection.execute(select(FileContentLocationModel.storage_state).where(
                FileContentLocationModel.file_id == link.file_id
            )).scalar_one_or_none()
            if location is None:
                raise ValueError("File record was not found.")
            if location != "available":
                raise ValueError("Only available file content can be associated.")
            connection.execute(FileLinkModel.__table__.insert().values(
                id=link.id, file_id=link.file_id, entity_type=link.entity_type,
                entity_id=link.entity_id, purpose=link.purpose, created_at=link.created_at,
                archived_at=None, archive_reason=None,
            ))
            self.recorder.record_change(connection.connection.driver_connection, entity_type=audit_change.entity_type,
                entity_id=audit_change.entity_id, action=audit_change.action, before=audit_change.before,
                after=audit_change.after, reason=audit_change.reason, correlation_id=audit_change.correlation_id,
                actor_kind=audit_change.actor_kind)
        return link

    def files_for_verification(self) -> list[StoredFile]:
        with Session(self.engine) as session:
            rows = session.execute(select(FileRecordModel, FileContentLocationModel).join(
                FileContentLocationModel, FileContentLocationModel.file_id == FileRecordModel.id,
            )).all()
            return [StoredFile(record.id, record.original_name, record.media_type, record.size_bytes,
                               record.content_sha256, location.storage_provider, location.storage_state,
                               location.local_relative_path, location.s3_bucket, location.s3_object_key,
                               location.s3_version_id, location.provider_etag, location.verified_at,
                               record.created_at) for record, location in rows]

    def replace_storage_verification(self, item: StoredFile, storage_state: str, verified_at: str,
                                     audit_change: FileAuditChange, consequences=None) -> None:
        with immediate_transaction(self.engine) as connection:
            result = connection.execute(FileContentLocationModel.__table__.update().where(
                FileContentLocationModel.file_id == item.id,
            ).values(storage_state=storage_state, verified_at=verified_at))
            if result.rowcount != 1:
                raise ValueError("File record was not found.")
            self.recorder.record_change(connection.connection.driver_connection, entity_type=audit_change.entity_type,
                entity_id=audit_change.entity_id, action=audit_change.action, before=audit_change.before,
                after=audit_change.after, reason=audit_change.reason, correlation_id=audit_change.correlation_id,
                actor_kind=audit_change.actor_kind)
            if consequences is not None:
                consequences.apply_storage_verification(
                    connection, item.id, storage_state, audit_change.correlation_id
                )

    def record_cleanup_incomplete(self, publication_id: str, provider: str, correlation_id: str) -> None:
        """Durable, privacy-safe integrity attention after failed cleanup."""
        with immediate_transaction(self.engine) as connection:
            opened_at = datetime.now(UTC).isoformat()
            result = connection.execute(FilePublicationCleanupAttentionModel.__table__.insert().prefix_with("OR IGNORE").values(
                publication_id=publication_id, provider=provider, opened_at=opened_at, resolved_at=None,
            ))
            if result.rowcount:
                self.recorder.record_change(connection.connection.driver_connection,
                    entity_type="file_publication_cleanup", entity_id=publication_id, action="cleanup_incomplete",
                    before=None, after={"publicationId": publication_id, "provider": provider},
                    reason="cleanup_incomplete", correlation_id=correlation_id, actor_kind="system")

    def record_cleanup_resolved(self, correlation_id: str) -> None:
        with immediate_transaction(self.engine) as connection:
            opened = connection.execute(select(FilePublicationCleanupAttentionModel).where(
                FilePublicationCleanupAttentionModel.resolved_at.is_(None)
            )).scalars().all()
            resolved_at = datetime.now(UTC).isoformat()
            for attention in opened:
                connection.execute(FilePublicationCleanupAttentionModel.__table__.update().where(
                    FilePublicationCleanupAttentionModel.publication_id == attention.publication_id,
                    FilePublicationCleanupAttentionModel.resolved_at.is_(None),
                ).values(resolved_at=resolved_at))
                self.recorder.record_change(connection.connection.driver_connection,
                    entity_type="file_publication_cleanup", entity_id=attention.publication_id, action="cleanup_resolved",
                    before={"publicationId": attention.publication_id, "provider": attention.provider},
                    after={"publicationId": attention.publication_id, "provider": attention.provider, "verifiedAt": resolved_at},
                    reason="storage_verification_complete", correlation_id=correlation_id, actor_kind="system")

    def outstanding_cleanup_attentions(self) -> list[dict[str, object]]:
        with Session(self.engine) as session:
            return [
                {"publicationId": row["publication_id"], "provider": row["provider"], "openedAt": row["opened_at"]}
                for row in session.execute(select(FilePublicationCleanupAttentionModel.__table__).where(
                    FilePublicationCleanupAttentionModel.resolved_at.is_(None)
                )).mappings()
            ]

"""SQLAlchemy adapter for FILE-001 metadata and its audit transaction."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.files.application.ports import FileAuditChange, FileLink
from app.modules.files.domain.models import StoredFile
from app.modules.files.infrastructure.sqlalchemy_models import FileContentLocationModel, FileLinkModel, FileRecordModel
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
                                            reason=change.reason, correlation_id=change.correlation_id)

    def get(self, file_id: str) -> StoredFile | None:
        with Session(self.engine) as session:
            record = session.execute(select(FileRecordModel).where(FileRecordModel.id == file_id)).scalar_one_or_none()
            if record is None:
                return None
            location = session.get(FileContentLocationModel, file_id)
            if location is None:
                return None
            links = session.execute(select(FileLinkModel).where(FileLinkModel.file_id == file_id, FileLinkModel.archived_at.is_(None)).order_by(FileLinkModel.created_at, FileLinkModel.id)).scalars()
            return StoredFile(record.id, record.original_name, record.media_type, record.size_bytes,
                              record.content_sha256, location.storage_provider, location.storage_state,
                              location.local_relative_path, location.s3_bucket, location.s3_object_key,
                              location.s3_version_id, location.provider_etag, location.verified_at, record.created_at,
                              links=tuple({"id": link.id, "entityType": link.entity_type, "entityId": link.entity_id,
                                           "purpose": link.purpose, "createdAt": link.created_at} for link in links))
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
                after=audit_change.after, reason=audit_change.reason, correlation_id=audit_change.correlation_id)
        return link

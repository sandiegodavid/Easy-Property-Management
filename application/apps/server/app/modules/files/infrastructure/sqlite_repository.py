"""SQLAlchemy adapter for FILE-001 metadata and its audit transaction."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.files.application.ports import FileAuditChange, FileLink
from app.modules.files.domain.models import StoredFile
from app.modules.files.infrastructure.sqlalchemy_models import FileContentLocationModel, FileLinkModel, FileRecordModel
from app.platform.sqlite_engine import create_sqlite_engine


class SQLiteFileUnitOfWork:
    def __init__(self, database: Path, recorder: AuditRecorder) -> None:
        self.engine = create_sqlite_engine(database)
        self.recorder = recorder

    def write(self, item: StoredFile, link: FileLink | None, audit_changes: list[FileAuditChange]) -> None:
        with self.engine.begin() as connection:
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
                    purpose=link.purpose, created_at=link.created_at,
                ))
            for change in audit_changes:
                self.recorder.record_change(raw, entity_type=change.entity_type, entity_id=change.entity_id,
                                            action=change.action, before=None, after=change.after,
                                            reason=change.reason, correlation_id=change.correlation_id)

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
                                           "purpose": link.purpose, "createdAt": link.created_at} for link in links))

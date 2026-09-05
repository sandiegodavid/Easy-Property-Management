"""SQLAlchemy adapter for FILE-001 metadata and its audit transaction."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.files.domain.models import StoredFile
from app.modules.files.infrastructure.sqlalchemy_models import FileLinkModel, FileRecordModel
from app.platform.sqlite_engine import create_sqlite_engine


class SQLiteFileMetadataRepository:
    def __init__(self, database: Path, recorder: AuditRecorder) -> None:
        self.engine = create_sqlite_engine(database)
        self.recorder = recorder

    def create(self, item: StoredFile, entity_type: str | None, entity_id: str | None, purpose: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(FileRecordModel.__table__.insert().values(
                id=item.id, original_name=item.original_name, media_type=item.media_type,
                size_bytes=item.size_bytes, content_sha256=item.content_sha256,
                relative_path=item.relative_path, created_at=item.created_at,
            ))
            raw = connection.connection.driver_connection
            self.recorder.record_change(raw, entity_type="file", entity_id=item.id, action="created",
                                        before=None, after=item.to_dict(), reason="file_stored")
            if entity_type:
                link_id = str(uuid4()); now = datetime.now(UTC).isoformat()
                connection.execute(FileLinkModel.__table__.insert().values(
                    id=link_id, file_id=item.id, entity_type=entity_type, entity_id=entity_id,
                    purpose=purpose, created_at=now,
                ))
                self.recorder.record_change(raw, entity_type="file_link", entity_id=link_id, action="created",
                                            before=None, after={"fileId": item.id, "entityType": entity_type,
                                            "entityId": entity_id, "purpose": purpose}, reason="file_linked")

    def get(self, file_id: str) -> StoredFile | None:
        with Session(self.engine) as session:
            record = session.execute(select(FileRecordModel).where(FileRecordModel.id == file_id)).scalar_one_or_none()
            if record is None:
                return None
            links = session.execute(select(FileLinkModel).where(FileLinkModel.file_id == file_id).order_by(FileLinkModel.created_at, FileLinkModel.id)).scalars()
            return StoredFile(record.id, record.original_name, record.media_type, record.size_bytes,
                              record.content_sha256, record.relative_path, record.created_at,
                              links=tuple({"id": link.id, "entityType": link.entity_type, "entityId": link.entity_id,
                                           "purpose": link.purpose, "createdAt": link.created_at} for link in links))

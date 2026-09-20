"""SQLite implementation of transaction-aware file-link reads."""

from collections.abc import Sequence

from sqlalchemy import func, select

from app.modules.files.application.ports import FileLink, FileLinkWithFile
from app.modules.files.infrastructure.sqlalchemy_models import (
    FileContentLocationModel,
    FileLinkModel,
    FileRecordModel,
)


class SQLiteFileLinkReader:
    def active_link_count(self, connection, entity_type: str, entity_id: str) -> int:
        return int(connection.execute(
            select(func.count()).select_from(FileLinkModel).where(
                FileLinkModel.entity_type == entity_type,
                FileLinkModel.entity_id == entity_id,
                FileLinkModel.archived_at.is_(None),
            )
        ).scalar_one())

    def has_active_available_link(self, connection, entity_type: str, entity_id: str) -> bool:
        return connection.execute(
            select(FileLinkModel.id)
            .join(FileContentLocationModel, FileContentLocationModel.file_id == FileLinkModel.file_id)
            .where(
                FileLinkModel.entity_type == entity_type,
                FileLinkModel.entity_id == entity_id,
                FileLinkModel.archived_at.is_(None),
                FileContentLocationModel.storage_state == "available",
            )
            .limit(1)
        ).first() is not None

    def links_for_entity(self, connection, entity_type: str, entity_id: str) -> list[FileLink]:
        return [
            FileLink(**dict(row))
            for row in connection.execute(
                select(FileLinkModel.__table__)
                .where(FileLinkModel.entity_type == entity_type, FileLinkModel.entity_id == entity_id)
                .order_by(FileLinkModel.created_at)
            ).mappings()
        ]

    def links_for_entities(self, connection, entity_type: str, entity_ids: Sequence[str]) -> dict[str, list[FileLinkWithFile]]:
        result = {entity_id: [] for entity_id in entity_ids}
        if not entity_ids:
            return result
        query = select(
            FileLinkModel.id,
            FileLinkModel.entity_type,
            FileLinkModel.entity_id,
            FileLinkModel.purpose,
            FileLinkModel.created_at,
            FileLinkModel.file_id,
            FileLinkModel.archived_at,
            FileLinkModel.archive_reason,
            FileRecordModel.original_name,
            FileRecordModel.media_type,
            FileRecordModel.size_bytes,
            FileRecordModel.content_sha256,
        ).join(FileRecordModel, FileRecordModel.id == FileLinkModel.file_id).where(
            FileLinkModel.entity_type == entity_type,
            FileLinkModel.entity_id.in_(entity_ids),
        ).order_by(FileLinkModel.created_at, FileLinkModel.id)
        for row in connection.execute(query).mappings():
            item = FileLinkWithFile(**dict(row))
            result[item.entity_id].append(item)
        return result

    def entity_ids_with_active_links(self, connection, entity_type: str) -> set[str]:
        return set(connection.execute(select(FileLinkModel.entity_id).where(
            FileLinkModel.entity_type == entity_type,
            FileLinkModel.archived_at.is_(None),
        )).scalars())

    def active_linked_entity_ids(self, connection, entity_type: str, entity_ids: Sequence[str]) -> set[str]:
        if not entity_ids:
            return set()
        return set(connection.execute(select(FileLinkModel.entity_id).where(
            FileLinkModel.entity_type == entity_type,
            FileLinkModel.entity_id.in_(set(entity_ids)),
            FileLinkModel.archived_at.is_(None),
        )).scalars())

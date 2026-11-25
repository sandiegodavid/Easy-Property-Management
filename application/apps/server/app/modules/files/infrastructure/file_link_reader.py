"""SQLite implementation of transaction-aware file-link reads."""

from collections.abc import Sequence

from sqlalchemy import and_, func, or_, select

from app.modules.files.application.ports import FileLink, FileLinkWithFile
from app.modules.files.infrastructure.sqlalchemy_models import (
    FileContentLocationModel,
    FileLinkModel,
    FileRecordModel,
)


class SQLiteFileLinkReader:
    def active_link_count(self, connection, entity_type: str, entity_id: str) -> int:
        return int(
            connection.execute(
                select(func.count())
                .select_from(FileLinkModel)
                .where(
                    FileLinkModel.entity_type == entity_type,
                    FileLinkModel.entity_id == entity_id,
                    FileLinkModel.archived_at.is_(None),
                )
            ).scalar_one()
        )

    def has_active_available_link(self, connection, entity_type: str, entity_id: str) -> bool:
        return (
            connection.execute(
                select(FileLinkModel.id)
                .join(
                    FileContentLocationModel,
                    FileContentLocationModel.file_id == FileLinkModel.file_id,
                )
                .where(
                    FileLinkModel.entity_type == entity_type,
                    FileLinkModel.entity_id == entity_id,
                    FileLinkModel.archived_at.is_(None),
                    FileContentLocationModel.storage_state == "available",
                )
                .limit(1)
            ).first()
            is not None
        )

    def active_available_link_count(self, connection, entity_type: str, entity_id: str) -> int:
        return int(
            connection.execute(
                select(func.count())
                .select_from(FileLinkModel)
                .join(
                    FileContentLocationModel,
                    FileContentLocationModel.file_id == FileLinkModel.file_id,
                )
                .where(
                    FileLinkModel.entity_type == entity_type,
                    FileLinkModel.entity_id == entity_id,
                    FileLinkModel.archived_at.is_(None),
                    FileContentLocationModel.storage_state == "available",
                )
            ).scalar_one()
        )

    def link_is_active_available(self, connection, link_id: str) -> bool:
        return (
            connection.execute(
                select(FileLinkModel.id)
                .join(
                    FileContentLocationModel,
                    FileContentLocationModel.file_id == FileLinkModel.file_id,
                )
                .where(
                    FileLinkModel.id == link_id,
                    FileLinkModel.archived_at.is_(None),
                    FileContentLocationModel.storage_state == "available",
                )
                .limit(1)
            ).first()
            is not None
        )

    def active_available_links(
        self, connection, entity_type: str, entity_id: str
    ) -> list[FileLink]:
        return [
            FileLink(**dict(row))
            for row in connection.execute(
                select(FileLinkModel.__table__)
                .join(
                    FileContentLocationModel,
                    FileContentLocationModel.file_id == FileLinkModel.file_id,
                )
                .where(
                    FileLinkModel.entity_type == entity_type,
                    FileLinkModel.entity_id == entity_id,
                    FileLinkModel.archived_at.is_(None),
                    FileContentLocationModel.storage_state == "available",
                )
                .order_by(FileLinkModel.created_at, FileLinkModel.id)
            ).mappings()
        ]

    def links_for_entity(self, connection, entity_type: str, entity_id: str) -> list[FileLink]:
        return [
            FileLink(**dict(row))
            for row in connection.execute(
                select(FileLinkModel.__table__)
                .where(
                    FileLinkModel.entity_type == entity_type, FileLinkModel.entity_id == entity_id
                )
                .order_by(FileLinkModel.created_at)
            ).mappings()
        ]

    def links_with_files_for_ids(
        self, connection, link_ids: Sequence[str]
    ) -> dict[str, FileLinkWithFile]:
        """Load immutable file metadata for a bounded set of link identities."""
        ids = tuple(dict.fromkeys(link_ids))
        if not ids:
            return {}
        rows = connection.execute(
            select(
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
                FileContentLocationModel.storage_state,
                FileContentLocationModel.verified_at,
            )
            .join(FileRecordModel, FileRecordModel.id == FileLinkModel.file_id)
            .join(FileContentLocationModel, FileContentLocationModel.file_id == FileRecordModel.id)
            .where(FileLinkModel.id.in_(ids)),
        ).mappings()
        return {row["id"]: FileLinkWithFile(**dict(row)) for row in rows}

    def links_for_entities(
        self, connection, entity_type: str, entity_ids: Sequence[str]
    ) -> dict[str, list[FileLinkWithFile]]:
        return self._links_for_entities(connection, entity_type, entity_ids, active_only=False)

    def active_links_for_entities(
        self, connection, entity_type: str, entity_ids: Sequence[str]
    ) -> dict[str, list[FileLinkWithFile]]:
        """Normal evidence projection: archived links belong only to history."""
        return self._links_for_entities(connection, entity_type, entity_ids, active_only=True)

    def active_entity_files_summary(
        self, connection, entity_type: str, entity_id: str
    ) -> list[dict[str, object]]:
        rows = connection.execute(
            select(
                FileLinkModel.id.label("link_id"),
                FileLinkModel.purpose,
                FileRecordModel.id.label("file_id"),
                FileRecordModel.original_name,
                FileRecordModel.media_type,
                FileRecordModel.size_bytes,
                FileRecordModel.content_sha256,
                FileContentLocationModel.storage_state,
                FileContentLocationModel.verified_at,
            )
            .join(FileRecordModel, FileRecordModel.id == FileLinkModel.file_id)
            .join(FileContentLocationModel, FileContentLocationModel.file_id == FileRecordModel.id)
            .where(
                FileLinkModel.entity_type == entity_type,
                FileLinkModel.entity_id == entity_id,
                FileLinkModel.archived_at.is_(None),
            )
            .order_by(FileLinkModel.created_at)
        ).mappings()
        return [
            {
                "id": row["file_id"],
                "originalName": row["original_name"],
                "mediaType": row["media_type"],
                "sizeBytes": row["size_bytes"],
                "contentSha256": row["content_sha256"],
                "linkId": row["link_id"],
                "purpose": row["purpose"],
                "storageState": row["storage_state"],
                "available": row["storage_state"] == "available",
                "verifiedAt": row["verified_at"],
            }
            for row in rows
        ]

    def active_observation_files(
        self, connection, observation_ids: Sequence[str]
    ) -> dict[str, list[dict[str, object]]]:
        result: dict[str, list[dict[str, object]]] = {obs_id: [] for obs_id in observation_ids}
        if not observation_ids:
            return result
        rows = connection.execute(
            select(
                FileLinkModel.id.label("link_id"),
                FileLinkModel.entity_type,
                FileLinkModel.entity_id,
                FileLinkModel.purpose,
                FileLinkModel.created_at.label("link_created_at"),
                FileRecordModel.id.label("file_id"),
                FileRecordModel.original_name,
                FileRecordModel.media_type,
                FileRecordModel.size_bytes,
                FileRecordModel.content_sha256,
                FileRecordModel.created_at.label("file_created_at"),
                FileContentLocationModel.storage_provider,
                FileContentLocationModel.storage_state,
                FileContentLocationModel.verified_at,
            )
            .join(FileRecordModel, FileRecordModel.id == FileLinkModel.file_id)
            .join(FileContentLocationModel, FileContentLocationModel.file_id == FileRecordModel.id)
            .where(
                FileLinkModel.entity_type == "condition_observation",
                FileLinkModel.entity_id.in_(observation_ids),
                FileLinkModel.archived_at.is_(None),
            )
        ).mappings()
        for row in rows:
            result[row["entity_id"]].append(
                {
                    "id": row["file_id"],
                    "originalName": row["original_name"],
                    "mediaType": row["media_type"],
                    "sizeBytes": row["size_bytes"],
                    "contentSha256": row["content_sha256"],
                    "storageProvider": row["storage_provider"],
                    "storageState": row["storage_state"],
                    "available": row["storage_state"] == "available",
                    "verifiedAt": row["verified_at"],
                    "createdAt": row["file_created_at"],
                    "links": [
                        {
                            "id": row["link_id"],
                            "entityType": row["entity_type"],
                            "entityId": row["entity_id"],
                            "purpose": row["purpose"],
                            "createdAt": row["link_created_at"],
                        }
                    ],
                }
            )
        return result

    def has_active_link_for_any(
        self, connection, entity_type: str, entity_ids: Sequence[str]
    ) -> bool:
        if not entity_ids:
            return False
        return (
            connection.execute(
                select(FileLinkModel.id)
                .where(
                    FileLinkModel.entity_type == entity_type,
                    FileLinkModel.entity_id.in_(entity_ids),
                    FileLinkModel.archived_at.is_(None),
                )
                .limit(1)
            ).first()
            is not None
        )

    def _links_for_entities(
        self, connection, entity_type: str, entity_ids: Sequence[str], *, active_only: bool
    ) -> dict[str, list[FileLinkWithFile]]:
        result = {entity_id: [] for entity_id in entity_ids}
        if not entity_ids:
            return result
        query = (
            select(
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
                FileContentLocationModel.storage_state,
                FileContentLocationModel.verified_at,
            )
            .join(FileRecordModel, FileRecordModel.id == FileLinkModel.file_id)
            .join(
                FileContentLocationModel,
                FileContentLocationModel.file_id == FileRecordModel.id,
            )
            .where(
                FileLinkModel.entity_type == entity_type,
                FileLinkModel.entity_id.in_(entity_ids),
                *([FileLinkModel.archived_at.is_(None)] if active_only else []),
            )
            .order_by(FileLinkModel.created_at, FileLinkModel.id)
        )
        for row in connection.execute(query).mappings():
            item = FileLinkWithFile(**dict(row))
            result[item.entity_id].append(item)
        return result

    def active_link_predicate(self, entity_type: str, entity_id):
        return (
            select(FileLinkModel.id)
            .where(
                FileLinkModel.entity_type == entity_type,
                FileLinkModel.entity_id == entity_id,
                FileLinkModel.archived_at.is_(None),
            )
            .exists()
        )

    # Kept for existing internal callers; cross-module filtered reads use the
    # SQL predicate above so they never materialize a workspace-wide ID set.
    def entity_ids_with_active_links(self, connection, entity_type: str) -> set[str]:
        return set(
            connection.execute(
                select(FileLinkModel.entity_id).where(
                    FileLinkModel.entity_type == entity_type,
                    FileLinkModel.archived_at.is_(None),
                )
            ).scalars()
        )

    def active_linked_entity_ids(
        self, connection, entity_type: str, entity_ids: Sequence[str]
    ) -> set[str]:
        if not entity_ids:
            return set()
        return set(
            connection.execute(
                select(FileLinkModel.entity_id).where(
                    FileLinkModel.entity_type == entity_type,
                    FileLinkModel.entity_id.in_(set(entity_ids)),
                    FileLinkModel.archived_at.is_(None),
                )
            ).scalars()
        )

    def active_entity_ids_for_file(self, connection, file_id: str, entity_type: str) -> set[str]:
        return set(
            connection.execute(
                select(FileLinkModel.entity_id).where(
                    FileLinkModel.file_id == file_id,
                    FileLinkModel.entity_type == entity_type,
                    FileLinkModel.archived_at.is_(None),
                )
            ).scalars()
        )

    def active_link_counts_for_entities(
        self, connection, entity_type: str, entity_ids: Sequence[str]
    ) -> dict[str, int]:
        entity_ids = list(dict.fromkeys(entity_ids))
        if not entity_ids:
            return {}
        return {
            row["entity_id"]: int(row["count"])
            for row in connection.execute(
                select(
                    FileLinkModel.entity_id,
                    func.count().label("count"),
                )
                .where(
                    FileLinkModel.entity_type == entity_type,
                    FileLinkModel.entity_id.in_(entity_ids),
                    FileLinkModel.archived_at.is_(None),
                )
                .group_by(FileLinkModel.entity_id)
            ).mappings()
        }

    def active_link_counts_for_entity_groups(
        self, connection, entity_ids_by_type: dict[str, Sequence[str]]
    ) -> dict[tuple[str, str], int]:
        conditions = [
            and_(
                FileLinkModel.entity_type == entity_type,
                FileLinkModel.entity_id.in_(set(entity_ids)),
            )
            for entity_type, entity_ids in entity_ids_by_type.items()
            if entity_ids
        ]
        if not conditions:
            return {}
        return {
            (row["entity_type"], row["entity_id"]): int(row["count"])
            for row in connection.execute(
                select(
                    FileLinkModel.entity_type,
                    FileLinkModel.entity_id,
                    func.count().label("count"),
                )
                .where(FileLinkModel.archived_at.is_(None), or_(*conditions))
                .group_by(
                    FileLinkModel.entity_type,
                    FileLinkModel.entity_id,
                )
            ).mappings()
        }

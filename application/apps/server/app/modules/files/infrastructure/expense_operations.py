"""FILE-001 evidence projection for FIN-002."""

from sqlalchemy import select

from app.modules.files.infrastructure.sqlalchemy_models import FileLinkModel, FileRecordModel


class SQLiteFileExpenseOperations:
    def active_link_count(self, connection, entity_type, entity_id):
        from sqlalchemy import func
        return int(connection.execute(select(func.count()).select_from(FileLinkModel).where(
            FileLinkModel.entity_type == entity_type,
            FileLinkModel.entity_id == entity_id,
            FileLinkModel.archived_at.is_(None),
        )).scalar_one())

    def expense_ids_with_active_evidence(self, connection):
        return set(connection.execute(select(FileLinkModel.entity_id).where(
            FileLinkModel.entity_type == "expense",
            FileLinkModel.archived_at.is_(None),
        )).scalars())

    def evidence_for_expenses(self, connection, expense_ids):
        result = {expense_id: [] for expense_id in expense_ids}
        if not expense_ids:
            return result
        query = select(
            FileLinkModel.id.label("link_id"),
            FileLinkModel.entity_id,
            FileLinkModel.purpose,
            FileLinkModel.created_at,
            FileLinkModel.archived_at,
            FileLinkModel.archive_reason,
            FileRecordModel.id.label("file_id"),
            FileRecordModel.original_name,
            FileRecordModel.media_type,
            FileRecordModel.size_bytes,
            FileRecordModel.content_sha256,
        ).join(
            FileRecordModel, FileRecordModel.id == FileLinkModel.file_id
        ).where(
            FileLinkModel.entity_type == "expense",
            FileLinkModel.entity_id.in_(expense_ids),
        ).order_by(FileLinkModel.created_at, FileLinkModel.id)
        for row in connection.execute(query).mappings():
            result[row["entity_id"]].append({
                "linkId": row["link_id"],
                "fileId": row["file_id"],
                "originalName": row["original_name"],
                "mediaType": row["media_type"],
                "sizeBytes": row["size_bytes"],
                "contentSha256": row["content_sha256"],
                "purpose": row["purpose"],
                "createdAt": row["created_at"],
                "archivedAt": row["archived_at"],
                "archiveReason": row["archive_reason"],
            })
        return result

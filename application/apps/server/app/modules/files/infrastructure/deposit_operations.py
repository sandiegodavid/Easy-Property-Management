"""FIN-008 evidence projection owned by FILE-001."""
from sqlalchemy import select

from app.modules.files.infrastructure.sqlalchemy_models import FileContentLocationModel, FileLinkModel


class SQLiteDepositFileOperations:
    def active_deduction_evidence(self, connection, deduction_id: str) -> bool:
        return connection.execute(
            select(FileLinkModel.id)
            .join(FileContentLocationModel, FileContentLocationModel.file_id == FileLinkModel.file_id)
            .where(
                FileLinkModel.entity_type == "security_deposit_deduction",
                FileLinkModel.entity_id == deduction_id,
                FileLinkModel.archived_at.is_(None),
                FileContentLocationModel.storage_state == "available",
            )
        ).first() is not None

    def evidence(self, connection, entity_type: str, entity_id: str) -> list[dict]:
        return [
            dict(row)
            for row in connection.execute(
                select(FileLinkModel.__table__)
                .where(FileLinkModel.entity_type == entity_type, FileLinkModel.entity_id == entity_id)
                .order_by(FileLinkModel.created_at)
            ).mappings()
        ]

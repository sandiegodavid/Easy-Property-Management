"""Task-owned durable creation receipts on the caller's connection."""

from sqlalchemy import select

from app.modules.tasks.infrastructure.sqlalchemy_models import TaskCreationOperationModel


class SQLiteTaskCreationReceiptReader:
    def receipt(self, connection, key):
        return (
            connection.execute(
                select(
                    TaskCreationOperationModel.id,
                    TaskCreationOperationModel.task_id,
                    TaskCreationOperationModel.request_fingerprint,
                ).where(TaskCreationOperationModel.idempotency_key == key)
            )
            .mappings()
            .first()
        )

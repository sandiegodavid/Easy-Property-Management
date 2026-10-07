"""Communication-owned operation identity for outcome reconciliation."""

from sqlalchemy import select

from app.modules.communications.infrastructure.sqlalchemy_models import CommunicationOperationModel


class SQLiteCommunicationReceiptReader:
    def receipt(self, connection, key):
        return (
            connection.execute(
                select(
                    CommunicationOperationModel.id,
                    CommunicationOperationModel.result_communication_id,
                    CommunicationOperationModel.request_fingerprint,
                ).where(CommunicationOperationModel.idempotency_key == key)
            )
            .mappings()
            .first()
        )

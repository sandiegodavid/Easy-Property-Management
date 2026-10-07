"""Maintenance-owned durable issue creation identity and fingerprint."""

from sqlalchemy import select

from app.modules.maintenance.infrastructure.sqlalchemy_models import MaintenanceIssueModel


class SQLiteIssueCommandReceiptReader:
    def receipt(self, connection, key):
        return (
            connection.execute(
                select(MaintenanceIssueModel.id, MaintenanceIssueModel.request_fingerprint).where(
                    MaintenanceIssueModel.idempotency_key == key
                )
            )
            .mappings()
            .first()
        )

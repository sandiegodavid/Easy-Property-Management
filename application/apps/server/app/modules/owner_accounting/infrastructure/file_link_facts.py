"""Owner-accounting facts for its FILE-001 evidence policy."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from app.modules.owner_accounting.infrastructure.sqlalchemy_models import OwnerRentReportModel


@dataclass(frozen=True)
class OwnerRentReportFileLinkTarget:
    status: str


class SQLiteOwnerRentReportFileLinkFacts:
    def exists(self, connection, report_id: str) -> bool:
        return (
            connection.execute(
                select(OwnerRentReportModel.id).where(OwnerRentReportModel.id == report_id).limit(1)
            ).first()
            is not None
        )

    def report(self, connection, report_id: str) -> OwnerRentReportFileLinkTarget | None:
        status = connection.execute(
            select(OwnerRentReportModel.status).where(OwnerRentReportModel.id == report_id)
        ).scalar_one_or_none()
        return None if status is None else OwnerRentReportFileLinkTarget(status)

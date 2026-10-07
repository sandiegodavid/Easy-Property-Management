"""INSP-001 ownership policy for FILE-001 observation evidence."""

from __future__ import annotations

from sqlalchemy import select

from app.modules.files.application.errors import FileError
from app.modules.files.application.ports import FileLink
from app.modules.inspections.infrastructure.sqlalchemy_models import (
    ConditionAreaModel,
    ConditionObservationModel,
    ConditionReportModel,
)


class ConditionObservationFileLinkValidator:
    """Only the inspection workflow may add or archive draft observation evidence."""

    entity_types = frozenset({"condition_observation"})
    allows_generic_upload = False
    _purposes = frozenset({"condition_photo", "supporting_document"})

    def validate_create(self, connection, link: FileLink) -> None:
        self._validate_draft(connection, link)

    def validate_archive(self, connection, link: FileLink) -> None:
        self._validate_draft(connection, link)

    def validate_retained(self, connection, link: FileLink) -> None:
        if link.purpose not in self._purposes:
            raise FileError("Unsupported condition-observation evidence purpose.")
        exists = connection.execute(
            select(ConditionObservationModel.id).where(
                ConditionObservationModel.id == link.entity_id
            )
        ).first()
        if exists is None:
            raise FileError("The linked condition observation does not exist.")

    def _validate_draft(self, connection, link: FileLink) -> None:
        if link.purpose not in self._purposes:
            raise FileError("Unsupported condition-observation evidence purpose.")
        status = connection.execute(
            select(ConditionReportModel.status)
            .join(
                ConditionAreaModel,
                ConditionAreaModel.condition_report_id == ConditionReportModel.id,
            )
            .join(
                ConditionObservationModel,
                ConditionObservationModel.condition_area_id == ConditionAreaModel.id,
            )
            .where(ConditionObservationModel.id == link.entity_id)
        ).scalar_one_or_none()
        if status is None:
            raise FileError("The linked condition observation does not exist.")
        if status != "draft":
            raise FileError(
                "Inspection evidence can be changed only while its report is draft.",
                "file_lifecycle_conflict",
            )

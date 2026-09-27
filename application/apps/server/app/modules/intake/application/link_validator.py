"""COM-001's narrow Intake target validator."""
from __future__ import annotations
from typing import Any
from sqlalchemy import select
from app.modules.intake.infrastructure.sqlalchemy_models import IntakeSourceModel


class IntakeSourceLinkValidator:
    def validate_new_link(self, connection: Any, source_id: str) -> None:
        source=connection.execute(select(IntakeSourceModel.id).where(IntakeSourceModel.id==source_id,IntakeSourceModel.technical_status=="ready",IntakeSourceModel.superseded_by_source_id.is_(None))).scalar_one_or_none()
        if source is None: raise KeyError("Linked intake source was not found or is not ready.")
    def validate_retained_link(self, connection: Any, source_id: str) -> None:
        if connection.execute(select(IntakeSourceModel.id).where(IntakeSourceModel.id==source_id)).scalar_one_or_none() is None:
            raise KeyError("Linked intake source was not found.")

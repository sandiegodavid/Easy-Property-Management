"""Maintenance-owned transaction facts used by FILE-001 evidence policies."""

from __future__ import annotations

from sqlalchemy import exists, select

from app.modules.maintenance.infrastructure.sqlalchemy_models import (
    MaintenanceAppointmentModel,
    MaintenanceAssignmentModel,
    MaintenanceCostContextModel,
    MaintenanceIssueModel,
    MaintenanceQuoteModel,
    MaintenanceWorkJournalEntryModel,
)


class SQLiteMaintenanceFileLinkFacts:
    _models = {
        "maintenance_issue": MaintenanceIssueModel,
        "maintenance_appointment": MaintenanceAppointmentModel,
        "maintenance_cost_context": MaintenanceCostContextModel,
        "maintenance_quote": MaintenanceQuoteModel,
        "maintenance_assignment": MaintenanceAssignmentModel,
        "maintenance_work_journal_entry": MaintenanceWorkJournalEntryModel,
    }

    def exists(self, connection, entity_type: str, entity_id: str) -> bool:
        model = self._models.get(entity_type)
        return (
            model is not None
            and connection.execute(select(model.id).where(model.id == entity_id).limit(1)).first()
            is not None
        )

    def work_journal_effective_kind(self, connection, entry_id: str):
        entry = MaintenanceWorkJournalEntryModel
        correction = entry.__table__.alias("maintenance_work_journal_corrections")
        row = connection.execute(
            select(entry.corrected_entry_kind, entry.entry_kind).where(
                entry.id == entry_id,
                ~exists(select(correction.c.id).where(correction.c.corrects_entry_id == entry.id)),
            )
        ).first()
        return None if row is None else row[0] or row[1]

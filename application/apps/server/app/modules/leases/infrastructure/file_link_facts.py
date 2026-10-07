"""Lease-owned transaction facts used by the FILE-001 policy."""

from __future__ import annotations

from sqlalchemy import select

from app.modules.leases.infrastructure.sqlalchemy_models import (
    LeaseModel,
    LeaseTerminationCaseModel,
)


class SQLiteLeaseFileLinkFacts:
    _models = {"lease": LeaseModel, "lease_termination_case": LeaseTerminationCaseModel}

    def file_link_target_exists(self, connection, entity_type: str, entity_id: str) -> bool:
        model = self._models.get(entity_type)
        return (
            model is not None
            and connection.execute(select(model.id).where(model.id == entity_id).limit(1)).first()
            is not None
        )

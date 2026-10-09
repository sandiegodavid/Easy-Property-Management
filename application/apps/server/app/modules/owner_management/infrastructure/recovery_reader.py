"""Concern-owned, connection-bound original command receipt projection."""

from sqlalchemy import func, select

from app.modules.owner_management.infrastructure.sqlalchemy_models import (
    OwnerConcernCommandOperationModel,
    OwnerConcernModel,
)
from app.platform.command_recovery import CommandOutcome, CommandResult


class SQLiteOwnerConcernRecoveryReader:
    def state(self, connection, source_id):
        model = OwnerConcernModel
        return (
            connection.execute(select(model.revision, model.status).where(model.id == source_id))
            .mappings()
            .first()
        )

    def outcome(self, connection, key, *, family):
        if family != "owner_concern":
            raise ValueError("Unsupported concern command family.")
        model = OwnerConcernCommandOperationModel
        row = (
            connection.execute(
                select(
                    model.id,
                    model.concern_id,
                    model.action,
                    model.request_fingerprint,
                    model.resulting_revision,
                    func.json_extract(model.result_json, "$.status").label("status"),
                ).where(model.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        return (
            CommandOutcome(
                row["id"],
                row["action"],
                row["concern_id"],
                row["request_fingerprint"],
                CommandResult(row["concern_id"], row["resulting_revision"], row["status"]),
            )
            if row
            else None
        )

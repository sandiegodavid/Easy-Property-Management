"""Indexed original inventory outcomes on the caller-owned snapshot."""

from sqlalchemy import select, func

from app.platform.command_recovery import CommandOutcome, CommandResult
from app.modules.portfolio.infrastructure.sqlalchemy_models import (
    PropertyModel,
    SpaceModel,
    PortfolioInventoryOperationModel,
)


class SQLiteInventoryRecoveryReader:
    def state(self, connection, source_id):
        return (
            connection.execute(
                select(
                    PropertyModel.property_revision.label("revision"),
                    PropertyModel.status,
                    PropertyModel.inventory_layout,
                ).where(PropertyModel.id == source_id)
            )
            .mappings()
            .first()
        )

    def related_state(self, connection, kind, target_id):
        if kind != "space":
            raise ValueError("Unsupported inventory child kind.")
        return (
            connection.execute(
                select(
                    SpaceModel.property_id.label("source_id"),
                    SpaceModel.status,
                ).where(SpaceModel.id == target_id)
            )
            .mappings()
            .first()
        )

    def outcome(self, connection, key, *, family):
        if family != "inventory":
            raise ValueError("Unsupported inventory receipt family.")
        model = PortfolioInventoryOperationModel
        row = (
            connection.execute(
                select(
                    model.id,
                    model.action,
                    model.property_id,
                    model.request_fingerprint,
                    model.result_revision,
                    func.json_extract(model.response_json, "$.id").label("target_id"),
                    func.json_extract(model.response_json, "$.status").label("status"),
                ).where(model.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return CommandOutcome(
            row["id"],
            row["action"],
            row["property_id"],
            row["request_fingerprint"],
            CommandResult(row["target_id"], row["result_revision"], row["status"]),
        )

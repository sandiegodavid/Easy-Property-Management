"""Portfolio-owned manual-status recovery on the caller's snapshot."""

from hashlib import sha256
from sqlalchemy import select, func

from app.platform.command_recovery import CommandOutcome, CommandResult
from app.modules.portfolio.infrastructure.sqlalchemy_models import (
    SpaceModel,
    SpaceStatusOperationModel,
    SpaceOccupancyPeriodModel,
)


class SQLitePortfolioStatusRecoveryReader:
    def related_state(self, connection, kind, target_id):
        model = SpaceOccupancyPeriodModel
        return (
            connection.execute(
                select(
                    model.space_id.label("source_id"),
                    model.record_state.label("status"),
                    model.source_kind,
                ).where(model.id == target_id)
            )
            .mappings()
            .first()
        )

    def state(self, connection, source_id):
        return (
            connection.execute(
                select(SpaceModel.status_revision.label("revision"), SpaceModel.status).where(
                    SpaceModel.id == source_id
                )
            )
            .mappings()
            .first()
        )

    def outcome(self, connection, key, *, family):
        row = (
            connection.execute(
                select(
                    SpaceStatusOperationModel.id,
                    SpaceStatusOperationModel.space_id,
                    SpaceStatusOperationModel.request_fingerprint,
                    func.json_extract(
                        SpaceStatusOperationModel.request_fingerprint, "$.action"
                    ).label("action"),
                    func.json_extract(SpaceStatusOperationModel.result_snapshot, "$.id").label(
                        "target_id"
                    ),
                    func.json_extract(
                        SpaceStatusOperationModel.result_snapshot, "$.revision"
                    ).label("revision"),
                    func.json_extract(SpaceStatusOperationModel.result_snapshot, "$.status").label(
                        "status"
                    ),
                ).where(SpaceStatusOperationModel.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return CommandOutcome(
            row["id"],
            row["action"],
            row["space_id"],
            sha256(row["request_fingerprint"].encode()).hexdigest(),
            CommandResult(row["target_id"], row["revision"], row["status"]),
        )

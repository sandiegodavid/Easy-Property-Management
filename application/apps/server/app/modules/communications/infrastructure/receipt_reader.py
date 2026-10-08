"""Communication-owned operation identity for outcome reconciliation."""

from sqlalchemy import select, func
from typing import Any
from app.platform.command_recovery import CommandOutcome, CommandResult

from app.modules.communications.application.receipt_ports import CommunicationReceipt

from app.modules.communications.infrastructure.sqlalchemy_models import (
    CommunicationOperationModel,
    CommunicationModel,
)


class SQLiteCommunicationReceiptReader:
    def state(self, connection, source_id):
        return (
            connection.execute(
                select(CommunicationModel.revision, CommunicationModel.status).where(
                    CommunicationModel.id == source_id
                )
            )
            .mappings()
            .first()
        )

    def outcome(self, connection, key, *, family):
        row = (
            connection.execute(
                select(
                    CommunicationOperationModel.id,
                    CommunicationOperationModel.action,
                    CommunicationOperationModel.result_communication_id,
                    CommunicationOperationModel.request_fingerprint,
                    func.json_extract(CommunicationOperationModel.request_json, "$.target").label(
                        "source_id"
                    ),
                    func.json_extract(CommunicationOperationModel.response_json, "$.id").label(
                        "target_id"
                    ),
                    func.json_extract(
                        CommunicationOperationModel.response_json, "$.revision"
                    ).label("revision"),
                    func.json_extract(CommunicationOperationModel.response_json, "$.status").label(
                        "status"
                    ),
                ).where(CommunicationOperationModel.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return CommandOutcome(
            row["id"],
            row["action"],
            row["source_id"] or row["result_communication_id"],
            row["request_fingerprint"],
            CommandResult(row["target_id"], row["revision"], row["status"]),
        )

    def receipt(self, connection: Any, key: str) -> CommunicationReceipt | None:
        row = (
            connection.execute(
                select(
                    CommunicationOperationModel.id,
                    CommunicationOperationModel.result_communication_id,
                    CommunicationOperationModel.request_fingerprint,
                    CommunicationOperationModel.result_revision,
                    CommunicationOperationModel.outcome,
                    CommunicationOperationModel.response_json,
                ).where(CommunicationOperationModel.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        return CommunicationReceipt(**dict(row)) if row else None

"""Read-only original Owner report command outcomes on the caller's connection."""

from json import loads
from sqlalchemy import select

from app.modules.owner_accounting.infrastructure.sqlalchemy_models import (
    OwnerRentReportModel,
    OwnerRentReportOperationModel,
)
from app.platform.command_recovery import CommandOutcome, CommandResult


class SQLiteOwnerReportRecoveryReader:
    def __init__(self, lease_reader, ledger_reader):
        self.lease_reader = lease_reader
        self.ledger_reader = ledger_reader

    def verification_state(self, connection, source_id, payload):
        expected = payload.get("expectedLedgerRevision")
        if expected is None:
            return "available"
        lease_id = connection.scalar(
            select(OwnerRentReportModel.lease_id).where(OwnerRentReportModel.id == source_id)
        )
        state = self.ledger_reader.state(connection, lease_id)
        return (
            "available" if state is not None and state["revision"] == expected else "source_changed"
        )

    def state(self, connection, source_id):
        row = (
            connection.execute(
                select(OwnerRentReportModel.report_revision, OwnerRentReportModel.status).where(
                    OwnerRentReportModel.id == source_id
                )
            )
            .mappings()
            .first()
        )
        return (
            None if row is None else {"revision": row["report_revision"], "status": row["status"]}
        )

    def creation_state(self, connection, payload):
        if payload.get("leaseId") is None:
            return "available"
        lease = self.lease_reader.state(connection, payload.get("leaseId"))
        return (
            "available"
            if lease is not None and lease["status"] in {"executed", "ended", "terminated"}
            else "source_unavailable"
        )

    def outcome(self, connection, key, *, family):
        if family != "owner_rent_report":
            raise ValueError("Unsupported Owner report recovery family.")
        row = (
            connection.execute(
                select(OwnerRentReportOperationModel.__table__).where(
                    OwnerRentReportOperationModel.idempotency_key == key
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        result = loads(row["response_json"])
        return CommandOutcome(
            row["id"],
            row["action"],
            row["report_id"],
            row["request_fingerprint"],
            CommandResult(row["report_id"], row["result_revision"], result["status"]),
        )

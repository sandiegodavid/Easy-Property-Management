"""Lease-owned read-only recovery for immutable Lease command receipts."""

from sqlalchemy import func, select

from app.modules.leases.infrastructure.sqlalchemy_models import (
    LeaseCommandOperationModel,
    LeaseModel,
    LeaseTermModel,
    LeaseTerminationCaseModel,
)
from app.platform.command_recovery import CommandOutcome, CommandResult


class SQLiteLeaseRecoveryReader:
    def term_state(self, connection, term_id):
        return (
            connection.execute(
                select(LeaseTermModel.lease_id.label("source_id")).where(
                    LeaseTermModel.id == term_id
                )
            )
            .mappings()
            .first()
        )

    def termination_case_reason(self, connection, lease_id, case_id):
        return connection.execute(
            select(LeaseTerminationCaseModel.reason).where(
                LeaseTerminationCaseModel.id == case_id,
                LeaseTerminationCaseModel.lease_id == lease_id,
            )
        ).scalar_one_or_none()

    def state(self, connection, source_id):
        return (
            connection.execute(
                select(
                    LeaseModel.lease_revision.label("revision"),
                    LeaseModel.status,
                ).where(LeaseModel.id == source_id)
            )
            .mappings()
            .first()
        )

    def outcome(self, connection, key, *, family):
        if family != "lease":
            raise ValueError("Unsupported Lease recovery family.")
        response = LeaseCommandOperationModel.response_json
        row = (
            connection.execute(
                select(
                    LeaseCommandOperationModel.id,
                    LeaseCommandOperationModel.action,
                    LeaseCommandOperationModel.lease_id,
                    LeaseCommandOperationModel.request_fingerprint,
                    func.coalesce(
                        func.json_extract(response, "$.leaseId"),
                        func.json_extract(response, "$.id"),
                        LeaseCommandOperationModel.lease_id,
                    ).label("target_id"),
                    func.coalesce(
                        func.json_extract(response, "$.leaseRevision"),
                        LeaseCommandOperationModel.result_revision,
                    ).label("revision"),
                    func.json_extract(response, "$.status").label("status"),
                ).where(LeaseCommandOperationModel.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return CommandOutcome(
            row["id"],
            row["action"],
            row["lease_id"],
            row["request_fingerprint"],
            CommandResult(row["target_id"], row["revision"], row["status"]),
        )

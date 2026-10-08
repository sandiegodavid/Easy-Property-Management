"""Maintenance-owned immutable issue creation outcome for reconciliation."""

from sqlalchemy import select, func
from app.platform.command_recovery import CommandOutcome, CommandResult

from app.modules.maintenance.application.receipt_ports import IssueCommandReceipt
from app.modules.maintenance.infrastructure.sqlalchemy_models import (
    MaintenanceCommandReceiptModel,
    MaintenanceIssueModel,
    MaintenanceAppointmentModel,
    MaintenanceCostContextModel,
    MaintenanceIssueExpenseLinkModel,
    MaintenanceQuoteModel,
    MaintenanceAssignmentModel,
)


class SQLiteIssueCommandReceiptReader:
    def related_state(self, connection, kind, target_id):
        model, state_column = {
            "appointment": (
                MaintenanceAppointmentModel,
                MaintenanceAppointmentModel.status.label("status"),
            ),
            "cost_context": (
                MaintenanceCostContextModel,
                MaintenanceCostContextModel.voided_at.label("terminal_at"),
            ),
            "expense_link": (
                MaintenanceIssueExpenseLinkModel,
                MaintenanceIssueExpenseLinkModel.archived_at.label("terminal_at"),
            ),
            "quote": (
                MaintenanceQuoteModel,
                MaintenanceQuoteModel.withdrawn_at.label("terminal_at"),
            ),
            "assignment": (
                MaintenanceAssignmentModel,
                MaintenanceAssignmentModel.ended_at.label("terminal_at"),
            ),
        }[kind]
        return (
            connection.execute(
                select(model.issue_id.label("source_id"), state_column).where(model.id == target_id)
            )
            .mappings()
            .first()
        )

    def state(self, connection, source_id):
        return (
            connection.execute(
                select(MaintenanceIssueModel.revision, MaintenanceIssueModel.status).where(
                    MaintenanceIssueModel.id == source_id
                )
            )
            .mappings()
            .first()
        )

    def outcome(self, connection, key, *, family):
        row = (
            connection.execute(
                select(
                    MaintenanceCommandReceiptModel.id,
                    MaintenanceCommandReceiptModel.action,
                    MaintenanceCommandReceiptModel.issue_id,
                    MaintenanceCommandReceiptModel.request_fingerprint,
                    func.json_extract(
                        MaintenanceCommandReceiptModel.response_payload, "$.id"
                    ).label("target_id"),
                    func.json_extract(
                        MaintenanceCommandReceiptModel.response_payload, "$.revision"
                    ).label("revision"),
                    func.json_extract(
                        MaintenanceCommandReceiptModel.response_payload, "$.status"
                    ).label("status"),
                ).where(MaintenanceCommandReceiptModel.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return CommandOutcome(
            row["id"],
            row["action"],
            row["issue_id"],
            row["request_fingerprint"],
            CommandResult(row["target_id"], row["revision"], row["status"]),
        )

    def receipt(self, connection, key) -> IssueCommandReceipt | None:
        row = (
            connection.execute(
                select(
                    MaintenanceCommandReceiptModel.id,
                    MaintenanceCommandReceiptModel.issue_id.label("result_issue_id"),
                    MaintenanceCommandReceiptModel.request_fingerprint,
                    MaintenanceCommandReceiptModel.request_payload,
                    MaintenanceCommandReceiptModel.response_payload,
                    MaintenanceCommandReceiptModel.revision,
                ).where(
                    MaintenanceCommandReceiptModel.idempotency_key == key,
                    MaintenanceCommandReceiptModel.action == "create_issue",
                )
            )
            .mappings()
            .first()
        )
        return IssueCommandReceipt(**dict(row)) if row else None

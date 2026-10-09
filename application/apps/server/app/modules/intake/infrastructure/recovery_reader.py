"""Indexed, read-only original Intake outcomes on the caller's transaction."""

import json

from sqlalchemy import func, select

from app.modules.intake.infrastructure.sqlalchemy_models import (
    IntakeSourceModel,
    IntakeSourceOperationModel,
    IntakeEvidenceRevisionModel,
)
from app.modules.intake.domain.models import IntakeError
from app.platform.command_recovery import CommandOutcome, CommandResult


class SQLiteIntakeRecoveryReader:
    def state(self, connection, source_id):
        return (
            connection.execute(
                select(
                    IntakeSourceModel.source_revision.label("revision"),
                    IntakeSourceModel.technical_status.label("status"),
                    IntakeSourceModel.current_revision_id.label("evidence_revision_id"),
                    IntakeSourceModel.attention_status,
                ).where(IntakeSourceModel.id == source_id)
            )
            .mappings()
            .first()
        )

    def correction_payload(self, connection, source_id, payload):
        row = (
            connection.execute(
                select(
                    func.json_extract(
                        IntakeEvidenceRevisionModel.envelope_json, "$.attachments"
                    ).label("manifest_json")
                ).where(
                    IntakeEvidenceRevisionModel.id == payload.get("expectedEvidenceRevisionId"),
                    IntakeEvidenceRevisionModel.source_id == source_id,
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise IntakeError("Evidence revision does not belong to the source.")
        return {**payload, "attachments": json.loads(row["manifest_json"])}

    def outcome(self, connection, key, *, family):
        if family != "intake":
            raise ValueError("Unsupported Intake recovery family.")
        row = (
            connection.execute(
                select(
                    IntakeSourceOperationModel.id,
                    IntakeSourceOperationModel.operation_type,
                    IntakeSourceOperationModel.source_id,
                    IntakeSourceOperationModel.request_fingerprint,
                    func.json_extract(IntakeSourceOperationModel.result_json, "$.sourceId").label(
                        "target_id"
                    ),
                    func.json_extract(
                        IntakeSourceOperationModel.result_json, "$.sourceRevision"
                    ).label("result_revision"),
                    func.json_extract(
                        IntakeSourceOperationModel.result_json, "$.technicalStatus"
                    ).label("result_status"),
                    func.json_extract(IntakeSourceOperationModel.result_json, "$.revision").label(
                        "evidence_revision_id"
                    ),
                    func.json_extract(
                        IntakeSourceOperationModel.result_json, "$.supersedesSourceId"
                    ).label("predecessor_id"),
                ).where(
                    IntakeSourceOperationModel.idempotency_key == key,
                    IntakeSourceOperationModel.actor_kind == "local_operator",
                    IntakeSourceOperationModel.operation_type.in_(
                        ("admit", "supersede", "correct", "attention_transition")
                    ),
                    IntakeSourceOperationModel.outcome == "succeeded",
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        # Supersession binds the predecessor, while its result targets the replacement.
        source_id = (
            row["predecessor_id"] if row["operation_type"] == "supersede" else row["source_id"]
        )
        return CommandOutcome(
            row["id"],
            row["operation_type"],
            source_id,
            row["request_fingerprint"],
            CommandResult(
                row["target_id"],
                row["result_revision"],
                row["result_status"],
                row["evidence_revision_id"],
            ),
        )

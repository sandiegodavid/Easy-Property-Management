"""Inspection-owned state and indexed immutable command projections."""

from sqlalchemy import select, func

from app.modules.inspections.infrastructure.command_models import InspectionCommandOperationModel
from app.modules.inspections.infrastructure.sqlalchemy_models import (
    ConditionReportModel,
    ConditionAreaModel,
    ConditionObservationModel,
    ConditionChecklistTemplateModel,
)
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel
from app.platform.command_recovery import CommandOutcome, CommandResult


class SQLiteInspectionRecoveryReader:
    def __init__(self, kind):
        self.kind = kind

    def state(self, connection, source_id):
        if self.kind == "inspection_lease":
            query = select(LeaseModel.id.label("scope_id"), LeaseModel.status).where(
                LeaseModel.id == source_id
            )
        elif self.kind == "condition_template":
            model = ConditionChecklistTemplateModel
            query = select(model.id.label("scope_id"), model.archived_at).where(
                model.id == source_id
            )
        else:
            model = ConditionReportModel
            query = select(model.lease_id.label("scope_id"), model.status, model.report_kind).where(
                model.id == source_id
            )
            if self.kind == "condition_observation":
                query = (
                    select(model.lease_id.label("scope_id"), model.status)
                    .join(ConditionAreaModel, ConditionAreaModel.condition_report_id == model.id)
                    .join(
                        ConditionObservationModel,
                        ConditionObservationModel.condition_area_id == ConditionAreaModel.id,
                    )
                    .where(ConditionObservationModel.id == source_id)
                )
        row = connection.execute(query).mappings().first()
        if row is None:
            return None
        receipt = InspectionCommandOperationModel
        column = receipt.template_id if self.kind == "condition_template" else receipt.lease_id
        revision = connection.execute(
            select(func.coalesce(func.max(receipt.revision), 0)).where(column == row["scope_id"])
        ).scalar_one()
        return dict(row) | {
            "revision": revision,
            "status": ("active" if row["archived_at"] is None else "archived")
            if self.kind == "condition_template"
            else row["status"],
        }

    def correction_payload(self, connection, source_id, payload):
        # These immutable facts remain usable after the source has been superseded.
        row = (
            connection.execute(
                select(ConditionReportModel.lease_id, ConditionReportModel.report_kind).where(
                    ConditionReportModel.id == source_id
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ValueError("Corrected report was not found.")
        return payload | {"leaseId": row["lease_id"], "reportKind": row["report_kind"]}

    def outcome(self, connection, key, *, family):
        if family != "inspection":
            raise ValueError("Unsupported Inspection recovery family.")
        model = InspectionCommandOperationModel
        row = (
            connection.execute(
                select(
                    model.id,
                    model.action,
                    model.request_fingerprint,
                    model.revision,
                    func.json_extract(model.request_json, "$.targetId").label("source_id"),
                    func.json_extract(model.request_json, "$.payload.correction_of").label(
                        "correction_of"
                    ),
                    func.json_extract(model.result_json, "$.id").label("target_id"),
                    func.coalesce(
                        func.json_extract(model.result_json, "$.status"),
                        func.json_extract(model.result_json, "$.storageState"),
                    ).label("status"),
                    func.json_extract(model.result_json, "$.links[0].id").label("link_id"),
                ).where(model.idempotency_key == key)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        target = row["target_id"] or row["source_id"]
        source = row["correction_of"] or row["source_id"] or target
        return CommandOutcome(
            row["id"],
            row["action"],
            source,
            row["request_fingerprint"],
            CommandResult(
                target,
                row["revision"],
                row["status"],
                file_id=target if row["action"] == "evidence.attach" else None,
                link_id=row["link_id"],
            ),
        )

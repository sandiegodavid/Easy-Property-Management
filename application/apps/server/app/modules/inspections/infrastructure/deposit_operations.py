"""FIN-008 read projection owned by the inspection persistence adapter."""
from sqlalchemy import select

from app.modules.inspections.infrastructure.sqlalchemy_models import (
    ConditionAreaModel,
    ConditionComparisonModel,
    ConditionObservationModel,
    ConditionReportModel,
)


class SQLiteInspectionDepositOperations:
    def deposit_warnings(self, connection, lease_id: str) -> list[str]:
        kinds = set(connection.execute(
            select(ConditionReportModel.report_kind).where(
                ConditionReportModel.lease_id == lease_id,
                ConditionReportModel.status == "finalized",
            )
        ).scalars())
        warnings = []
        if "pre_move_in" not in kinds:
            warnings.append("missing_pre_move_in_inspection")
        if "post_move_out" not in kinds:
            warnings.append("missing_post_move_out_inspection")
        return warnings
    def source_context(self, connection, source_kind: str, source_id: str):
        if source_kind == "inspection_comparison":
            reports = ConditionReportModel.__table__
            pre = reports.alias("pre_condition_report")
            post = reports.alias("post_condition_report")
            row = connection.execute(
                select(
                    ConditionComparisonModel.__table__.c.lease_id,
                    ConditionComparisonModel.__table__.c.comparison_state,
                    pre.c.status.label("pre_status"),
                    post.c.status.label("post_status"),
                )
                .join(pre, ConditionComparisonModel.pre_report_id == pre.c.id)
                .join(post, ConditionComparisonModel.post_report_id == post.c.id)
                .where(ConditionComparisonModel.id == source_id)
            ).mappings().first()
            if row is None:
                return None
            return {
                "leaseId": row["lease_id"],
                "summary": f"Inspection comparison {row['comparison_state']}",
                "active": row["pre_status"] == "finalized" and row["post_status"] == "finalized",
            }
        row = connection.execute(
            select(
                ConditionReportModel.lease_id,
                ConditionReportModel.space_id,
                ConditionReportModel.status,
                ConditionObservationModel.condition_state,
            )
            .join(ConditionAreaModel, ConditionObservationModel.condition_area_id == ConditionAreaModel.id)
            .join(ConditionReportModel, ConditionAreaModel.condition_report_id == ConditionReportModel.id)
            .where(ConditionObservationModel.id == source_id)
        ).mappings().first()
        if row is None:
            return None
        return {
            "leaseId": row["lease_id"],
            "spaceId": row["space_id"],
            "summary": f"Inspection observation {row['condition_state']}",
            "active": row["status"] == "finalized",
        }

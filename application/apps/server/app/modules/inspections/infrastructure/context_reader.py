"""SQLite inspection facts for caller-owned transactions."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select

from app.modules.inspections.infrastructure.sqlalchemy_models import (
    ConditionAreaModel,
    ConditionComparisonModel,
    ConditionObservationModel,
    ConditionReportModel,
)


class SQLiteInspectionContextReader:
    def finalized_report_kinds(self, connection: Any, lease_id: str) -> set[str]:
        return set(connection.execute(
            select(ConditionReportModel.report_kind).where(
                ConditionReportModel.lease_id == lease_id,
                ConditionReportModel.status == "finalized",
            )
        ).scalars())

    def comparison_context(self, connection: Any, comparison_id: str) -> Mapping[str, object] | None:
        reports = ConditionReportModel.__table__
        pre = reports.alias("pre_condition_report")
        post = reports.alias("post_condition_report")
        return connection.execute(
            select(
                ConditionComparisonModel.__table__.c.lease_id,
                ConditionComparisonModel.__table__.c.comparison_state,
                pre.c.status.label("pre_status"),
                post.c.status.label("post_status"),
            )
            .join(pre, ConditionComparisonModel.pre_report_id == pre.c.id)
            .join(post, ConditionComparisonModel.post_report_id == post.c.id)
            .where(ConditionComparisonModel.id == comparison_id)
        ).mappings().first()

    def observation_context(self, connection: Any, observation_id: str) -> Mapping[str, object] | None:
        return connection.execute(
            select(
                ConditionReportModel.lease_id,
                ConditionReportModel.space_id,
                ConditionReportModel.status,
                ConditionObservationModel.condition_state,
            )
            .join(ConditionAreaModel, ConditionObservationModel.condition_area_id == ConditionAreaModel.id)
            .join(ConditionReportModel, ConditionAreaModel.condition_report_id == ConditionReportModel.id)
            .where(ConditionObservationModel.id == observation_id)
        ).mappings().first()

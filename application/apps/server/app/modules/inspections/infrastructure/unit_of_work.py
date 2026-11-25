"""SQLite persistence boundary for INSP-001."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.inspections.application.commands import InspectionCommandReceipt
from app.modules.inspections.infrastructure.command_models import InspectionCommandOperationModel
from app.modules.inspections.domain.models import (
    ConditionAcknowledgment,
    ConditionArea,
    ConditionChecklistTemplate,
    ConditionChecklistTemplateItem,
    ConditionComparison,
    ConditionObservation,
    ConditionReport,
)
from app.modules.inspections.infrastructure.sqlalchemy_models import (
    ConditionAcknowledgmentModel,
    ConditionAreaModel,
    ConditionChecklistTemplateItemModel,
    ConditionChecklistTemplateModel,
    ConditionComparisonModel,
    ConditionObservationModel,
    ConditionReportModel,
)
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

Result = TypeVar("Result")


class SQLiteInspectionUnitOfWork:
    def __init__(
        self,
        database,
        recorder: AuditRecorder,
        *,
        space_time_zones=None,
        lease_context_reader=None,
        file_link_reader=None,
    ) -> None:
        self.engine = create_sqlite_engine(database)
        self.recorder = recorder
        self._space_time_zones = space_time_zones
        self._lease_context_reader = lease_context_reader
        self._file_link_reader = file_link_reader

    def write(self, operation: Callable[[Any], Result]) -> Result:
        try:
            with immediate_transaction(self.engine) as connection:
                return operation(
                    _Transaction(
                        connection,
                        self.recorder,
                        lease_context_reader=self._lease_context_reader,
                        file_link_reader=self._file_link_reader,
                    )
                )
        except IntegrityError as error:
            from app.modules.inspections.application.service import InspectionConflictError

            raise InspectionConflictError(
                "The inspection changed concurrently or violates a protected relationship."
            ) from error
        except OperationalError as error:
            if "locked" in str(error).casefold():
                from app.modules.inspections.application.service import InspectionConflictError

                raise InspectionConflictError(
                    "The inspection changed concurrently; reload it and try again."
                ) from error
            raise

    def command_lookup(self, *, operation_id=None, idempotency_key=None):
        model = InspectionCommandOperationModel
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(model).where(
                        model.id == operation_id
                        if operation_id is not None
                        else model.idempotency_key == idempotency_key
                    )
                )
                .mappings()
                .first()
            )
            return None if row is None else InspectionCommandReceipt(**row)

    def command_revision(self, kind, scope_id):
        with self.engine.connect() as connection:
            return _revision(connection, kind, scope_id)

    def report_view(self, report_id: str):
        with Session(self.engine) as session:
            return _report_view(session, report_id, file_link_reader=self._file_link_reader)

    def observation_report_view(self, observation_id: str):
        with Session(self.engine) as session:
            report_id = session.execute(
                select(ConditionAreaModel.condition_report_id)
                .join(
                    ConditionObservationModel,
                    ConditionObservationModel.condition_area_id == ConditionAreaModel.id,
                )
                .where(ConditionObservationModel.id == observation_id)
            ).scalar_one_or_none()
            return (
                None
                if report_id is None
                else _report_view(session, report_id, file_link_reader=self._file_link_reader)
            )

    def report_views(self, lease_id: str):
        with Session(self.engine) as session:
            revision = _revision(session, "lease", lease_id)
            rows = list(
                session.execute(
                    select(ConditionReportModel)
                    .where(ConditionReportModel.lease_id == lease_id)
                    .order_by(ConditionReportModel.created_at)
                ).scalars()
            )
            return _report_views_for_rows(
                session, rows, revision=revision, file_link_reader=self._file_link_reader
            )

    def lease_exists(self, lease_id: str) -> bool:
        if self._lease_context_reader is None:
            raise RuntimeError("Lease context reader is not configured.")
        with self.engine.connect() as connection:
            return self._lease_context_reader.lease_row(connection, lease_id) is not None

    def lease_summary(self, lease_id: str):
        if self._lease_context_reader is None:
            raise RuntimeError("Lease context reader is not configured.")
        with self.engine.connect() as connection:
            row = self._lease_context_reader.lease_row(connection, lease_id)
            if row is None:
                return None
            zones = (
                self._space_time_zones(connection, {row["space_id"]})
                if self._space_time_zones is not None
                else {}
            )
            return {
                "status": row["status"],
                "occupancy_starts_on": row["occupancy_starts_on"],
                "actual_move_out_on": row["actual_move_out_on"],
                "time_zone": zones.get(row["space_id"]),
            }

    def template_views(self):
        with Session(self.engine) as session:
            revision = (
                select(func.coalesce(func.max(InspectionCommandOperationModel.revision), 0))
                .where(
                    InspectionCommandOperationModel.template_id
                    == ConditionChecklistTemplateModel.id
                )
                .correlate(ConditionChecklistTemplateModel)
                .scalar_subquery()
            )
            rows = session.execute(
                select(ConditionChecklistTemplateModel, revision)
                .where(ConditionChecklistTemplateModel.archived_at.is_(None))
                .order_by(ConditionChecklistTemplateModel.display_name)
            ).all()
            if not rows:
                return []
            template_ids = [item.id for item, _ in rows]
            items_by_template: dict[str, list[dict[str, Any]]] = {
                template_id: [] for template_id in template_ids
            }
            for item in session.execute(
                select(ConditionChecklistTemplateItemModel)
                .where(ConditionChecklistTemplateItemModel.template_id.in_(template_ids))
                .order_by(ConditionChecklistTemplateItemModel.sort_order)
            ).scalars():
                items_by_template[item.template_id].append(
                    ConditionChecklistTemplateItem(
                        **{
                            name: getattr(item, name)
                            for name in ConditionChecklistTemplateItem.__dataclass_fields__
                        }
                    ).to_dict()
                )
            results = []
            for template_row, current_revision in rows:
                result = ConditionChecklistTemplate(
                    **{
                        name: getattr(template_row, name)
                        for name in ConditionChecklistTemplate.__dataclass_fields__
                    }
                ).to_dict()
                result["items"] = items_by_template[template_row.id]
                result["revision"] = current_revision
                results.append(result)
            return results

    def template_view(self, template_id: str):
        with Session(self.engine) as session:
            return _template_view(session, template_id)


class _Transaction:
    def __init__(
        self,
        connection,
        recorder,
        *,
        lease_context_reader=None,
        file_link_reader=None,
    ):
        self.connection = connection
        self.recorder = recorder
        self._lease_context_reader = lease_context_reader
        self._file_link_reader = file_link_reader

    def file_transaction(self):
        return self.connection

    def command_by_key(self, key):
        row = (
            self.connection.execute(
                select(InspectionCommandOperationModel).where(
                    InspectionCommandOperationModel.idempotency_key == key
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else InspectionCommandReceipt(**row)

    def command_revision(self, kind, scope_id):
        return _revision(self.connection, kind, scope_id)

    def insert_command(self, receipt):
        self.insert(InspectionCommandOperationModel, receipt)

    def template_view(self, item_id):
        with Session(bind=self.connection) as session:
            return _template_view(session, item_id)

    def lease(self, item_id):
        if self._lease_context_reader is None:
            raise RuntimeError("Lease context reader is not configured.")
        return self._lease_context_reader.lease_row(self.connection, item_id)

    def report(self, item_id):
        return _domain(self.connection, ConditionReportModel, ConditionReport, item_id)

    def reports(self, lease_id):
        return _many(
            self.connection,
            ConditionReportModel,
            ConditionReport,
            ConditionReportModel.lease_id == lease_id,
            ConditionReportModel.created_at,
        )

    def participants(self, lease_id):
        if self._lease_context_reader is None:
            raise RuntimeError("Lease context reader is not configured.")
        return self._lease_context_reader.lease_participants(self.connection, lease_id)

    def areas(self, report_id):
        return _many(
            self.connection,
            ConditionAreaModel,
            ConditionArea,
            ConditionAreaModel.condition_report_id == report_id,
            ConditionAreaModel.sort_order,
        )

    def observations(self, area_id):
        return _many(
            self.connection,
            ConditionObservationModel,
            ConditionObservation,
            ConditionObservationModel.condition_area_id == area_id,
            ConditionObservationModel.sort_order,
        )

    def observation_context(self, observation_id):
        return (
            self.connection.execute(
                select(
                    ConditionObservationModel.id.label("observation_id"),
                    ConditionReportModel.lease_id,
                    ConditionReportModel.space_id,
                    ConditionReportModel.report_kind,
                    ConditionReportModel.status,
                )
                .join(
                    ConditionAreaModel,
                    ConditionAreaModel.id == ConditionObservationModel.condition_area_id,
                )
                .join(
                    ConditionReportModel,
                    ConditionReportModel.id == ConditionAreaModel.condition_report_id,
                )
                .where(ConditionObservationModel.id == observation_id)
            )
            .mappings()
            .first()
        )

    def has_evidence(self, report_id):
        if self._file_link_reader is None:
            return False
        obs_ids = list(
            self.connection.execute(
                select(ConditionObservationModel.id)
                .join(
                    ConditionAreaModel,
                    ConditionAreaModel.id == ConditionObservationModel.condition_area_id,
                )
                .where(ConditionAreaModel.condition_report_id == report_id)
            ).scalars()
        )
        return self._file_link_reader.has_active_link_for_any(
            self.connection, "condition_observation", obs_ids
        )

    def acknowledgments(self, report_id):
        return _many(
            self.connection,
            ConditionAcknowledgmentModel,
            ConditionAcknowledgment,
            ConditionAcknowledgmentModel.condition_report_id == report_id,
            ConditionAcknowledgmentModel.id,
        )

    def comparisons(self, lease_id):
        return _many(
            self.connection,
            ConditionComparisonModel,
            ConditionComparison,
            ConditionComparisonModel.lease_id == lease_id,
            ConditionComparisonModel.created_at,
        )

    def termination_accepted(self, lease_id):
        if self._lease_context_reader is None:
            raise RuntimeError("Lease context reader is not configured.")
        return self._lease_context_reader.has_accepted_termination_case(self.connection, lease_id)

    def template(self, item_id):
        return _domain(
            self.connection, ConditionChecklistTemplateModel, ConditionChecklistTemplate, item_id
        )

    def template_items(self, template_id):
        return _many(
            self.connection,
            ConditionChecklistTemplateItemModel,
            ConditionChecklistTemplateItem,
            ConditionChecklistTemplateItemModel.template_id == template_id,
            ConditionChecklistTemplateItemModel.sort_order,
        )

    def template_name_exists(self, normalized_name, excluding_id=None):
        query = select(ConditionChecklistTemplateModel.id).where(
            ConditionChecklistTemplateModel.normalized_name == normalized_name
        )
        if excluding_id is not None:
            query = query.where(ConditionChecklistTemplateModel.id != excluding_id)
        return self.connection.execute(query).first() is not None

    def insert(self, model, item):
        self.connection.execute(model.__table__.insert().values(**item.__dict__))

    def replace(self, model, item):
        self.connection.execute(
            model.__table__.update().where(model.id == item.id).values(**item.__dict__)
        )

    def delete_report_children(self, report_id):
        area_ids = select(ConditionAreaModel.id).where(
            ConditionAreaModel.condition_report_id == report_id
        )
        self.connection.execute(
            ConditionObservationModel.__table__.delete().where(
                ConditionObservationModel.condition_area_id.in_(area_ids)
            )
        )
        self.connection.execute(
            ConditionAreaModel.__table__.delete().where(
                ConditionAreaModel.condition_report_id == report_id
            )
        )

    def insert_template(self, item):
        self.insert(ConditionChecklistTemplateModel, item)

    def replace_template(self, item):
        self.replace(ConditionChecklistTemplateModel, item)

    def insert_template_item(self, item):
        self.insert(ConditionChecklistTemplateItemModel, item)

    def delete_template_items(self, template_id):
        self.connection.execute(
            ConditionChecklistTemplateItemModel.__table__.delete().where(
                ConditionChecklistTemplateItemModel.template_id == template_id
            )
        )

    def insert_report(self, item):
        self.insert(ConditionReportModel, item)

    def replace_report(self, item):
        self.replace(ConditionReportModel, item)

    def insert_area(self, item):
        self.insert(ConditionAreaModel, item)

    def insert_observation(self, item):
        self.insert(ConditionObservationModel, item)

    def insert_acknowledgment(self, item):
        self.insert(ConditionAcknowledgmentModel, item)

    def delete_acknowledgment(self, item_id):
        self.connection.execute(
            ConditionAcknowledgmentModel.__table__.delete().where(
                ConditionAcknowledgmentModel.id == item_id
            )
        )

    def insert_comparison(self, item):
        self.insert(ConditionComparisonModel, item)

    def delete_comparison(self, item_id):
        self.connection.execute(
            ConditionComparisonModel.__table__.delete().where(
                ConditionComparisonModel.id == item_id
            )
        )

    def record_change(self, **change):
        self.recorder.record_change(self.connection.connection.driver_connection, **change)

    def report_view(self, item_id):
        with Session(bind=self.connection) as session:
            return _report_view(session, item_id, file_link_reader=self._file_link_reader)


def _one(connection, model, item_id):
    return connection.execute(select(model).where(model.id == item_id)).mappings().first()


def _revision(connection, kind, scope_id):
    model = InspectionCommandOperationModel
    column = model.lease_id if kind == "lease" else model.template_id
    return connection.execute(
        select(func.coalesce(func.max(model.revision), 0)).where(column == scope_id)
    ).scalar_one()


def _domain(connection, model, domain, item_id):
    row = _one(connection, model, item_id)
    return None if row is None else domain(**dict(row))


def _many(connection, model, domain, predicate, ordering):
    return [
        domain(**dict(row))
        for row in connection.execute(select(model).where(predicate).order_by(ordering)).mappings()
    ]


def _report_view(session: Session, report_id: str, *, revision=None, file_link_reader=None):
    row = session.get(ConditionReportModel, report_id)
    if row is None:
        return None
    return _report_views_for_rows(
        session, [row], revision=revision, file_link_reader=file_link_reader
    )[0]


def _report_views_for_rows(
    session: Session, rows: list[ConditionReportModel], *, revision=None, file_link_reader=None
) -> list[dict[str, Any]]:
    if not rows:
        return []
    report_ids = [row.id for row in rows]
    area_rows = list(
        session.execute(
            select(ConditionAreaModel)
            .where(ConditionAreaModel.condition_report_id.in_(report_ids))
            .order_by(ConditionAreaModel.sort_order)
        ).scalars()
    )
    areas_by_report: dict[str, list[ConditionAreaModel]] = {
        report_id: [] for report_id in report_ids
    }
    for area_row in area_rows:
        areas_by_report[area_row.condition_report_id].append(area_row)

    area_ids = [area_row.id for area_row in area_rows]
    observations_by_area: dict[str, list[ConditionObservationModel]] = {
        area_id: [] for area_id in area_ids
    }
    observation_rows: list[ConditionObservationModel] = []
    if area_ids:
        observation_rows = list(
            session.execute(
                select(ConditionObservationModel)
                .where(ConditionObservationModel.condition_area_id.in_(area_ids))
                .order_by(ConditionObservationModel.sort_order)
            ).scalars()
        )
        for obs_row in observation_rows:
            observations_by_area[obs_row.condition_area_id].append(obs_row)

    observation_ids = [obs_row.id for obs_row in observation_rows]
    files_by_observation: dict[str, list[dict[str, Any]]] = (
        file_link_reader.active_observation_files(session.connection(), observation_ids)
        if observation_ids and file_link_reader is not None
        else {obs_id: [] for obs_id in observation_ids}
    )

    acknowledgments_by_report: dict[str, list[dict[str, Any]]] = {
        report_id: [] for report_id in report_ids
    }
    for ack_row in session.execute(
        select(ConditionAcknowledgmentModel).where(
            ConditionAcknowledgmentModel.condition_report_id.in_(report_ids)
        )
    ).scalars():
        acknowledgments_by_report[ack_row.condition_report_id].append(
            ConditionAcknowledgment(
                **{
                    name: getattr(ack_row, name)
                    for name in ConditionAcknowledgment.__dataclass_fields__
                }
            ).to_dict()
        )

    revisions_by_lease: dict[str, int] = {}
    results: list[dict[str, Any]] = []
    for row in rows:
        report = ConditionReport(
            **{name: getattr(row, name) for name in ConditionReport.__dataclass_fields__}
        ).to_dict()
        areas = []
        for area_row in areas_by_report[row.id]:
            area = ConditionArea(
                **{name: getattr(area_row, name) for name in ConditionArea.__dataclass_fields__}
            ).to_dict()
            observations = []
            for obs_row in observations_by_area[area_row.id]:
                item = ConditionObservation(
                    **{
                        name: getattr(obs_row, name)
                        for name in ConditionObservation.__dataclass_fields__
                    }
                ).to_dict()
                item["files"] = files_by_observation[obs_row.id]
                observations.append(item)
            area["observations"] = observations
            areas.append(area)
        acknowledgments = acknowledgments_by_report[row.id]
        report["areas"] = areas
        report["acknowledgments"] = acknowledgments
        report["acknowledgmentComplete"] = bool(acknowledgments) and all(
            item["status"] != "pending" for item in acknowledgments
        )
        if revision is not None:
            report["revision"] = revision
        else:
            if row.lease_id not in revisions_by_lease:
                revisions_by_lease[row.lease_id] = _revision(session, "lease", row.lease_id)
            report["revision"] = revisions_by_lease[row.lease_id]
        results.append(report)
    return results


def _template_view(session: Session, template_id: str, *, revision=None):
    row = session.get(ConditionChecklistTemplateModel, template_id)
    if row is None:
        return None
    result = ConditionChecklistTemplate(
        **{name: getattr(row, name) for name in ConditionChecklistTemplate.__dataclass_fields__}
    ).to_dict()
    result["items"] = [
        ConditionChecklistTemplateItem(
            **{
                name: getattr(item, name)
                for name in ConditionChecklistTemplateItem.__dataclass_fields__
            }
        ).to_dict()
        for item in session.execute(
            select(ConditionChecklistTemplateItemModel)
            .where(ConditionChecklistTemplateItemModel.template_id == template_id)
            .order_by(ConditionChecklistTemplateItemModel.sort_order)
        ).scalars()
    ]
    result["revision"] = (
        _revision(session, "template", template_id) if revision is None else revision
    )
    return result

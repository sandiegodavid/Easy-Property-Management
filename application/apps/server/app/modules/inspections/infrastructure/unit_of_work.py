"""SQLite persistence boundary for INSP-001."""
from __future__ import annotations
from collections.abc import Callable
from typing import Any, TypeVar
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseParticipantModel, LeaseTerminationCaseModel
from app.modules.files.infrastructure.sqlalchemy_models import FileContentLocationModel, FileLinkModel, FileRecordModel
from app.modules.inspections.domain.models import (ConditionAcknowledgment, ConditionArea, ConditionChecklistTemplate, ConditionChecklistTemplateItem, ConditionComparison, ConditionObservation, ConditionReport)
from app.modules.inspections.infrastructure.sqlalchemy_models import (ConditionAcknowledgmentModel, ConditionAreaModel, ConditionChecklistTemplateItemModel, ConditionChecklistTemplateModel, ConditionComparisonModel, ConditionObservationModel, ConditionReportModel)

Result = TypeVar("Result")


class SQLiteInspectionUnitOfWork:
    def __init__(self, database, recorder: AuditRecorder) -> None:
        self.engine = create_sqlite_engine(database); self.recorder = recorder
    def write(self, operation: Callable[[Any], Result]) -> Result:
        try:
            with immediate_transaction(self.engine) as connection:
                return operation(_Transaction(connection, self.recorder))
        except (IntegrityError, OperationalError) as error:
            from app.modules.inspections.application.service import InspectionConflictError
            raise InspectionConflictError("The inspection changed concurrently or violates a protected relationship.") from error
    def report_view(self, report_id: str):
        with Session(self.engine) as session: return _report_view(session, report_id)
    def report_views(self, lease_id: str):
        with Session(self.engine) as session:
            return [_report_view(session, item.id) for item in session.execute(select(ConditionReportModel).where(ConditionReportModel.lease_id == lease_id).order_by(ConditionReportModel.created_at)).scalars()]
    def lease_exists(self, lease_id: str) -> bool:
        with Session(self.engine) as session: return session.get(LeaseModel, lease_id) is not None
    def lease_summary(self, lease_id: str):
        with Session(self.engine) as session:
            row = session.get(LeaseModel, lease_id)
            return None if row is None else {"status": row.status, "occupancy_starts_on": row.occupancy_starts_on, "actual_move_out_on": row.actual_move_out_on}
    def template_views(self):
        with Session(self.engine) as session:
            return [_template_view(session, item.id) for item in session.execute(select(ConditionChecklistTemplateModel).where(ConditionChecklistTemplateModel.archived_at.is_(None)).order_by(ConditionChecklistTemplateModel.display_name)).scalars()]
    def template_view(self, template_id: str):
        with Session(self.engine) as session: return _template_view(session, template_id)


class _Transaction:
    def __init__(self, connection, recorder): self.connection = connection; self.recorder = recorder
    def file_transaction(self): return self.connection
    def lease(self, item_id): return _one(self.connection, LeaseModel, item_id)
    def report(self, item_id): return _domain(self.connection, ConditionReportModel, ConditionReport, item_id)
    def reports(self, lease_id): return _many(self.connection, ConditionReportModel, ConditionReport, ConditionReportModel.lease_id == lease_id, ConditionReportModel.created_at)
    def participants(self, lease_id): return self.connection.execute(select(LeaseParticipantModel).where(LeaseParticipantModel.lease_id == lease_id)).mappings().all()
    def areas(self, report_id): return _many(self.connection, ConditionAreaModel, ConditionArea, ConditionAreaModel.condition_report_id == report_id, ConditionAreaModel.sort_order)
    def observations(self, area_id): return _many(self.connection, ConditionObservationModel, ConditionObservation, ConditionObservationModel.condition_area_id == area_id, ConditionObservationModel.sort_order)
    def observation_context(self, observation_id):
        return self.connection.execute(select(ConditionObservationModel.id.label("observation_id"), ConditionReportModel.lease_id, ConditionReportModel.space_id, ConditionReportModel.report_kind, ConditionReportModel.status).join(ConditionAreaModel, ConditionAreaModel.id == ConditionObservationModel.condition_area_id).join(ConditionReportModel, ConditionReportModel.id == ConditionAreaModel.condition_report_id).where(ConditionObservationModel.id == observation_id)).mappings().first()
    def has_evidence(self, report_id):
        return self.connection.execute(select(FileLinkModel.id).join(ConditionObservationModel, ConditionObservationModel.id == FileLinkModel.entity_id).join(ConditionAreaModel, ConditionAreaModel.id == ConditionObservationModel.condition_area_id).where(FileLinkModel.entity_type == "condition_observation", ConditionAreaModel.condition_report_id == report_id)).first() is not None
    def acknowledgments(self, report_id): return _many(self.connection, ConditionAcknowledgmentModel, ConditionAcknowledgment, ConditionAcknowledgmentModel.condition_report_id == report_id, ConditionAcknowledgmentModel.id)
    def comparisons(self, lease_id): return _many(self.connection, ConditionComparisonModel, ConditionComparison, ConditionComparisonModel.lease_id == lease_id, ConditionComparisonModel.created_at)
    def termination_accepted(self, lease_id): return self.connection.execute(select(LeaseTerminationCaseModel.id).where(LeaseTerminationCaseModel.lease_id == lease_id, LeaseTerminationCaseModel.status == "accepted")).first() is not None
    def template(self, item_id): return _domain(self.connection, ConditionChecklistTemplateModel, ConditionChecklistTemplate, item_id)
    def template_items(self, template_id): return _many(self.connection, ConditionChecklistTemplateItemModel, ConditionChecklistTemplateItem, ConditionChecklistTemplateItemModel.template_id == template_id, ConditionChecklistTemplateItemModel.sort_order)
    def template_name_exists(self, normalized_name, excluding_id=None):
        query = select(ConditionChecklistTemplateModel.id).where(ConditionChecklistTemplateModel.normalized_name == normalized_name)
        if excluding_id is not None: query = query.where(ConditionChecklistTemplateModel.id != excluding_id)
        return self.connection.execute(query).first() is not None
    def insert(self, model, item): self.connection.execute(model.__table__.insert().values(**item.__dict__))
    def replace(self, model, item): self.connection.execute(model.__table__.update().where(model.id == item.id).values(**item.__dict__))
    def delete_report_children(self, report_id):
        area_ids = select(ConditionAreaModel.id).where(ConditionAreaModel.condition_report_id == report_id)
        self.connection.execute(ConditionObservationModel.__table__.delete().where(ConditionObservationModel.condition_area_id.in_(area_ids)))
        self.connection.execute(ConditionAreaModel.__table__.delete().where(ConditionAreaModel.condition_report_id == report_id))
    def insert_template(self, item): self.insert(ConditionChecklistTemplateModel, item)
    def replace_template(self, item): self.replace(ConditionChecklistTemplateModel, item)
    def insert_template_item(self, item): self.insert(ConditionChecklistTemplateItemModel, item)
    def delete_template_items(self, template_id): self.connection.execute(ConditionChecklistTemplateItemModel.__table__.delete().where(ConditionChecklistTemplateItemModel.template_id == template_id))
    def insert_report(self, item): self.insert(ConditionReportModel, item)
    def replace_report(self, item): self.replace(ConditionReportModel, item)
    def insert_area(self, item): self.insert(ConditionAreaModel, item)
    def insert_observation(self, item): self.insert(ConditionObservationModel, item)
    def insert_acknowledgment(self, item): self.insert(ConditionAcknowledgmentModel, item)
    def delete_acknowledgment(self, item_id): self.connection.execute(ConditionAcknowledgmentModel.__table__.delete().where(ConditionAcknowledgmentModel.id == item_id))
    def insert_comparison(self, item): self.insert(ConditionComparisonModel, item)
    def delete_comparison(self, item_id): self.connection.execute(ConditionComparisonModel.__table__.delete().where(ConditionComparisonModel.id == item_id))
    def record_change(self, **change): self.recorder.record_change(self.connection.connection.driver_connection, **change)
    def report_view(self, item_id):
        with Session(bind=self.connection) as session: return _report_view(session, item_id)


def _one(connection, model, item_id): return connection.execute(select(model).where(model.id == item_id)).mappings().first()
def _domain(connection, model, domain, item_id):
    row = _one(connection, model, item_id); return None if row is None else domain(**dict(row))
def _many(connection, model, domain, predicate, ordering):
    return [domain(**dict(row)) for row in connection.execute(select(model).where(predicate).order_by(ordering)).mappings()]


def _report_view(session: Session, report_id: str):
    row = session.get(ConditionReportModel, report_id)
    if row is None: return None
    report = ConditionReport(**{name: getattr(row, name) for name in ConditionReport.__dataclass_fields__}).to_dict()
    areas = []
    for area_row in session.execute(select(ConditionAreaModel).where(ConditionAreaModel.condition_report_id == report_id).order_by(ConditionAreaModel.sort_order)).scalars():
        area = ConditionArea(**{name: getattr(area_row, name) for name in ConditionArea.__dataclass_fields__}).to_dict()
        observations = []
        for observation_row in session.execute(select(ConditionObservationModel).where(ConditionObservationModel.condition_area_id == area_row.id).order_by(ConditionObservationModel.sort_order)).scalars():
            item = ConditionObservation(**{name: getattr(observation_row, name) for name in ConditionObservation.__dataclass_fields__}).to_dict()
            item["files"] = [{"id": file.id, "originalName": file.original_name, "mediaType": file.media_type, "sizeBytes": file.size_bytes, "contentSha256": file.content_sha256, "storageProvider": location.storage_provider, "storageState": location.storage_state, "createdAt": file.created_at, "links": [{"id": link.id, "entityType": link.entity_type, "entityId": link.entity_id, "purpose": link.purpose, "createdAt": link.created_at}]} for link, file, location in session.execute(select(FileLinkModel, FileRecordModel, FileContentLocationModel).join(FileRecordModel, FileRecordModel.id == FileLinkModel.file_id).join(FileContentLocationModel, FileContentLocationModel.file_id == FileRecordModel.id).where(FileLinkModel.entity_type == "condition_observation", FileLinkModel.entity_id == observation_row.id))]
            observations.append(item)
        area["observations"] = observations; areas.append(area)
    acknowledgments = [ConditionAcknowledgment(**{name: getattr(item, name) for name in ConditionAcknowledgment.__dataclass_fields__}).to_dict() for item in session.execute(select(ConditionAcknowledgmentModel).where(ConditionAcknowledgmentModel.condition_report_id == report_id)).scalars()]
    report["areas"] = areas; report["acknowledgments"] = acknowledgments
    report["acknowledgmentComplete"] = bool(acknowledgments) and all(item["status"] != "pending" for item in acknowledgments)
    return report


def _template_view(session: Session, template_id: str):
    row = session.get(ConditionChecklistTemplateModel, template_id)
    if row is None: return None
    result = ConditionChecklistTemplate(**{name: getattr(row, name) for name in ConditionChecklistTemplate.__dataclass_fields__}).to_dict()
    result["items"] = [ConditionChecklistTemplateItem(**{name: getattr(item, name) for name in ConditionChecklistTemplateItem.__dataclass_fields__}).to_dict() for item in session.execute(select(ConditionChecklistTemplateItemModel).where(ConditionChecklistTemplateItemModel.template_id == template_id).order_by(ConditionChecklistTemplateItemModel.sort_order)).scalars()]
    return result

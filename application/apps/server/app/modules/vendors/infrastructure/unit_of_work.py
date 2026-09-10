"""SQLite implementation of the VEND-001 transaction boundary."""

from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.parties.application.ports import PartyTransactionOperations
from app.modules.parties.domain.models import Party, PartyContactMethod
from app.modules.vendors.application.ports import (
    PropertyAvailability, ProviderRoleActivityGuard, ProviderTransaction, ProviderUnitOfWork,
    ProviderStorageConflict,
)
from app.modules.vendors.domain.models import (
    ProviderProfile, ProviderReference, ProviderService, ProviderServiceArea, ProviderWorkHistory,
)
from app.modules.vendors.infrastructure.sqlalchemy_models import (
    ProviderProfileModel, ProviderReferenceModel, ProviderServiceAreaModel,
    ProviderServiceModel, ProviderWorkHistoryModel,
)
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

Result = TypeVar("Result")


class SQLiteProviderUnitOfWork(ProviderUnitOfWork):
    def __init__(self, database, recorder: AuditRecorder, party_operations: PartyTransactionOperations,
                 properties: PropertyAvailability) -> None:
        self.engine = create_sqlite_engine(database)
        self.recorder = recorder
        self.party_operations = party_operations
        self.properties = properties

    def write(self, operation: Callable[[ProviderTransaction], Result]) -> Result:
        try:
            with immediate_transaction(self.engine) as connection:
                return operation(_Transaction(connection, self.recorder, self.party_operations, self.properties))
        except (IntegrityError, OperationalError) as error:
            if isinstance(error, IntegrityError) or "locked" in str(error).casefold():
                raise ProviderStorageConflict("The provider changed concurrently or conflicts with an active record.") from error
            raise

    def detail(self, party_id, *, include_archived):
        with Session(self.engine) as session:
            profile_row = session.get(ProviderProfileModel, party_id)
            if profile_row is None:
                return None
            party = self.party_operations.parties([party_id]).get(party_id)
            if party is None:
                return None
            def rows(model):
                query = select(model).where(model.party_id == party_id).order_by(model.created_at, model.id)
                if not include_archived:
                    query = query.where(model.archived_at.is_(None))
                return session.execute(query).scalars().all()
            methods = self.party_operations.methods_for_parties([party_id])[party_id]
            if not include_archived:
                methods = [item for item in methods if item.status == "active"]
            return (
                party, _profile(profile_row), methods,
                [_service(item) for item in rows(ProviderServiceModel)],
                [_area(item) for item in rows(ProviderServiceAreaModel)],
                [_work(item) for item in rows(ProviderWorkHistoryModel)],
                [_reference(item) for item in rows(ProviderReferenceModel)],
            )

    def list(self, *, archive_state, search, service, service_area, selection_status, property_id, has_reference):
        with Session(self.engine) as session:
            query = select(ProviderProfileModel)
            if archive_state == "active":
                query = query.where(ProviderProfileModel.archived_at.is_(None))
            elif archive_state == "archived":
                query = query.where(ProviderProfileModel.archived_at.is_not(None))
            if selection_status:
                query = query.where(ProviderProfileModel.selection_status == selection_status)
            profiles = [_profile(item) for item in session.execute(query).scalars()]
            party_ids = [item.party_id for item in profiles]
            parties = self.party_operations.parties(party_ids)
            active_services = _group(session, ProviderServiceModel, party_ids)
            active_areas = _group(session, ProviderServiceAreaModel, party_ids)
            active_work = _group(session, ProviderWorkHistoryModel, party_ids)
            active_references = _group(session, ProviderReferenceModel, party_ids)
            needle = search.casefold() if search else None
            results = []
            for profile in profiles:
                party = parties.get(profile.party_id)
                if party is None:
                    continue
                services = [_service(item) for item in active_services.get(profile.party_id, [])]
                areas = [_area(item) for item in active_areas.get(profile.party_id, [])]
                work = [_work(item) for item in active_work.get(profile.party_id, [])]
                references = [_reference(item) for item in active_references.get(profile.party_id, [])]
                if service and not any(item.normalized_name == service for item in services):
                    continue
                if service_area and not any(item.normalized_name == service_area for item in areas):
                    continue
                if property_id and not any(item.property_id == property_id for item in work):
                    continue
                if has_reference is not None and bool(references) != has_reference:
                    continue
                if needle and not _matches(needle, party, services, areas, work, references):
                    continue
                results.append((party, profile, services, areas, len(work), len(references)))
            return sorted(results, key=lambda item: (item[0].display_name.casefold(), item[0].id))


class _Transaction:
    def __init__(self, connection: Any, recorder: AuditRecorder,
                 party_operations: PartyTransactionOperations, properties: PropertyAvailability) -> None:
        self.connection = connection
        self.recorder = recorder
        self.party_operations = party_operations
        self.properties = properties

    def party(self, party_id): return self.party_operations.party(self.connection, party_id)
    def methods(self, party_id): return self.party_operations.methods(self.connection, party_id)
    def insert_party(self, item): self.party_operations.insert_party(self.connection, item)
    def insert_method(self, item): self.party_operations.insert_method(self.connection, item)
    def duplicate_party_ids(self, methods, limit): return self.party_operations.duplicate_party_ids(self.connection, methods, limit)
    def profile(self, party_id): return _one(self.connection, ProviderProfileModel, party_id, _profile)
    def services(self, party_id): return _many(self.connection, ProviderServiceModel, party_id, _service)
    def areas(self, party_id): return _many(self.connection, ProviderServiceAreaModel, party_id, _area)
    def work_history(self, party_id): return _many(self.connection, ProviderWorkHistoryModel, party_id, _work)
    def references(self, party_id): return _many(self.connection, ProviderReferenceModel, party_id, _reference)
    def property_exists(self, property_id): return self.properties.property(self.connection, property_id) is not None
    def insert_profile(self, item): self.connection.execute(ProviderProfileModel.__table__.insert().values(**item.__dict__))
    def replace_profile(self, item): self.connection.execute(ProviderProfileModel.__table__.update().where(ProviderProfileModel.party_id == item.party_id).values(**item.__dict__))
    def insert_service(self, item): self.connection.execute(ProviderServiceModel.__table__.insert().values(**item.__dict__))
    def replace_service(self, item): self.connection.execute(ProviderServiceModel.__table__.update().where(ProviderServiceModel.id == item.id).values(**item.__dict__))
    def insert_area(self, item): self.connection.execute(ProviderServiceAreaModel.__table__.insert().values(**item.__dict__))
    def replace_area(self, item): self.connection.execute(ProviderServiceAreaModel.__table__.update().where(ProviderServiceAreaModel.id == item.id).values(**item.__dict__))
    def insert_work_history(self, item): self.connection.execute(ProviderWorkHistoryModel.__table__.insert().values(**item.__dict__))
    def replace_work_history(self, item): self.connection.execute(ProviderWorkHistoryModel.__table__.update().where(ProviderWorkHistoryModel.id == item.id).values(**item.__dict__))
    def insert_reference(self, item): self.connection.execute(ProviderReferenceModel.__table__.insert().values(**item.__dict__))
    def replace_reference(self, item): self.connection.execute(ProviderReferenceModel.__table__.update().where(ProviderReferenceModel.id == item.id).values(**item.__dict__))
    def record_change(self, **change): self.recorder.record_change(self.connection.connection.driver_connection, **change)


class SQLiteProviderRoleActivityGuard(ProviderRoleActivityGuard):
    def conflict(self, connection, party_id):
        row = connection.execute(ProviderProfileModel.__table__.select().where(
            ProviderProfileModel.party_id == party_id, ProviderProfileModel.archived_at.is_(None)
        )).first()
        return "An active provider profile prevents party archival." if row else None


class SQLiteProviderRoleSummaryReader:
    def __init__(self, database) -> None: self.engine = create_sqlite_engine(database)
    def active_roles(self, party_id):
        with self.engine.connect() as connection:
            row = connection.execute(ProviderProfileModel.__table__.select().where(
                ProviderProfileModel.party_id == party_id, ProviderProfileModel.archived_at.is_(None)
            )).first()
        return {"provider"} if row else set()


def _one(connection, model, key, mapper):
    row = connection.execute(model.__table__.select().where(model.party_id == key)).mappings().first()
    return mapper(row) if row else None


def _many(connection, model, party_id, mapper):
    rows = connection.execute(model.__table__.select().where(model.party_id == party_id).order_by(model.created_at, model.id)).mappings().all()
    return [mapper(row) for row in rows]


def _group(session, model, party_ids):
    if not party_ids: return {}
    rows = session.execute(select(model).where(model.party_id.in_(party_ids), model.archived_at.is_(None))).scalars()
    result = {party_id: [] for party_id in party_ids}
    for row in rows: result[row.party_id].append(row)
    return result


def _matches(needle, party, services, areas, work, references):
    texts = [party.display_name, *(item.display_name for item in services), *(item.display_name for item in areas), *(item.summary for item in work), *(item.outcome_notes or "" for item in work), *(item.reference_name or "" for item in references), *(item.organization_name or "" for item in references), *(item.relationship or "" for item in references)]
    return any(needle in value.casefold() for value in texts)


def _profile(row): return ProviderProfile(row.party_id, row.selection_status, row.selection_reason, row.notes, row.created_at, row.updated_at, row.archived_at)
def _service(row): return ProviderService(row.id, row.party_id, row.display_name, row.normalized_name, row.created_at, row.updated_at, row.archived_at)
def _area(row): return ProviderServiceArea(row.id, row.party_id, row.display_name, row.normalized_name, row.country_code, row.created_at, row.updated_at, row.archived_at)
def _work(row): return ProviderWorkHistory(row.id, row.party_id, row.property_id, row.performed_on, row.summary, row.outcome_notes, row.created_at, row.updated_at, row.archived_at)
def _reference(row): return ProviderReference(row.id, row.party_id, row.reference_name, row.organization_name, row.relationship, row.email, row.phone, row.notes, row.created_at, row.updated_at, row.archived_at)

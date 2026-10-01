"""SQLite implementation of the provider transaction boundary."""

from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.parties.application.ports import PartyTransactionOperations
from app.modules.parties.domain.models import Party, PartyContactMethod
from app.modules.vendors.application.ports import (
    PropertyAvailability,
    ProviderRoleActivityGuard,
    ProviderStorageConflict,
    ProviderTransaction,
    ProviderUnitOfWork,
)
from app.modules.vendors.domain.models import (
    ProviderProfile,
    ProviderCategory,
    ProviderCategoryAssignment,
    ProviderReference,
    ProviderReputationLink,
    ProviderService,
    ProviderServiceArea,
    ProviderWorkHistory,
)
from app.modules.vendors.infrastructure.sqlalchemy_models import (
    ProviderCategoryAssignmentModel,
    ProviderCategoryModel,
    ProviderProfileModel,
    ProviderReferenceModel,
    ProviderReputationLinkModel,
    ProviderServiceAreaModel,
    ProviderServiceModel,
    ProviderWorkHistoryModel,
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
                sorted(
                    (_reputation_link(item) for item in rows(ProviderReputationLinkModel)),
                    key=_reputation_sort_key,
                ),
                _assignment_pairs(session, [party_id], include_archived=include_archived).get(party_id, [])
                if include_archived or profile_row.archived_at is None else [],
            )

    def categories(self, archive_state, search=None):
        with Session(self.engine) as session:
            query = select(ProviderCategoryModel)
            if archive_state == "active":
                query = query.where(ProviderCategoryModel.archived_at.is_(None))
            elif archive_state == "archived":
                query = query.where(ProviderCategoryModel.archived_at.is_not(None))
            if search:
                query = query.where(ProviderCategoryModel.normalized_name.contains(search))
            return [_category(row) for row in session.execute(query.order_by(
                ProviderCategoryModel.display_order, ProviderCategoryModel.normalized_name,
                ProviderCategoryModel.id,
            )).scalars()]

    def effective_assignment_counts(self, category_ids):
        category_ids = set(category_ids)
        if not category_ids:
            return {}
        with Session(self.engine) as session:
            rows = session.execute(select(
                ProviderCategoryAssignmentModel.category_id,
                func.count(ProviderCategoryAssignmentModel.id),
            ).join(
                ProviderProfileModel, ProviderProfileModel.party_id == ProviderCategoryAssignmentModel.provider_party_id,
            ).join(
                ProviderCategoryModel, ProviderCategoryModel.id == ProviderCategoryAssignmentModel.category_id,
            ).where(
                ProviderCategoryAssignmentModel.category_id.in_(category_ids),
                ProviderCategoryAssignmentModel.archived_at.is_(None),
                ProviderCategoryModel.archived_at.is_(None), ProviderProfileModel.archived_at.is_(None),
            ).group_by(ProviderCategoryAssignmentModel.category_id)).all()
        return {category_id: int(count) for category_id, count in rows}

    def list(self, *, archive_state, search, service, service_area, selection_status, property_id, has_reference,
             category_id=None, category_state=None, limit=None, cursor=None):
        with Session(self.engine) as session:
            conditions, parameters = [], {}
            if archive_state == "active":
                conditions.append("pp.archived_at IS NULL")
            elif archive_state == "archived":
                conditions.append("pp.archived_at IS NOT NULL")
            if selection_status:
                conditions.append("pp.selection_status = :selection_status")
                parameters["selection_status"] = selection_status
            if service:
                conditions.append("EXISTS (SELECT 1 FROM provider_services ps WHERE ps.party_id = pp.party_id AND ps.archived_at IS NULL AND ps.normalized_name = :service)")
                parameters["service"] = service
            if service_area:
                conditions.append("EXISTS (SELECT 1 FROM provider_service_areas pa WHERE pa.party_id = pp.party_id AND pa.archived_at IS NULL AND pa.normalized_name = :service_area)")
                parameters["service_area"] = service_area
            if property_id:
                conditions.append("EXISTS (SELECT 1 FROM provider_work_history pw WHERE pw.party_id = pp.party_id AND pw.archived_at IS NULL AND pw.property_id = :property_id)")
                parameters["property_id"] = property_id
            if has_reference is not None:
                predicate = "EXISTS (SELECT 1 FROM provider_references pr WHERE pr.party_id = pp.party_id AND pr.archived_at IS NULL)"
                conditions.append(predicate if has_reference else f"NOT {predicate}")
            # Categories are effective only while their provider profile is active.
            # Archive history remains available from the provider detail projection.
            effective_category = "(pp.archived_at IS NULL AND EXISTS (SELECT 1 FROM provider_category_assignments pca JOIN provider_categories pc ON pc.id = pca.category_id WHERE pca.provider_party_id = pp.party_id AND pca.archived_at IS NULL AND pc.archived_at IS NULL))"
            if category_id:
                conditions.append("pp.archived_at IS NULL AND EXISTS (SELECT 1 FROM provider_category_assignments pca JOIN provider_categories pc ON pc.id = pca.category_id WHERE pca.provider_party_id = pp.party_id AND pca.archived_at IS NULL AND pc.archived_at IS NULL AND pca.category_id = :category_id)")
                parameters["category_id"] = category_id
            if category_state == "categorized":
                conditions.append(effective_category)
            elif category_state == "uncategorized":
                conditions.append(f"NOT {effective_category}")
            if search:
                parameters["search"] = f"%{_like(search.casefold())}%"
                conditions.append("""(
                    unicode_casefold(p.display_name) LIKE :search ESCAPE '\\'
                    OR EXISTS (SELECT 1 FROM provider_services ps WHERE ps.party_id = pp.party_id AND ps.archived_at IS NULL AND unicode_casefold(ps.display_name) LIKE :search ESCAPE '\\')
                    OR EXISTS (SELECT 1 FROM provider_service_areas pa WHERE pa.party_id = pp.party_id AND pa.archived_at IS NULL AND unicode_casefold(pa.display_name) LIKE :search ESCAPE '\\')
                    OR EXISTS (SELECT 1 FROM provider_work_history pw WHERE pw.party_id = pp.party_id AND pw.archived_at IS NULL AND (unicode_casefold(pw.summary) LIKE :search ESCAPE '\\' OR unicode_casefold(coalesce(pw.outcome_notes, '')) LIKE :search ESCAPE '\\'))
                    OR EXISTS (SELECT 1 FROM provider_references pr WHERE pr.party_id = pp.party_id AND pr.archived_at IS NULL AND (unicode_casefold(coalesce(pr.reference_name, '')) LIKE :search ESCAPE '\\' OR unicode_casefold(coalesce(pr.organization_name, '')) LIKE :search ESCAPE '\\' OR unicode_casefold(coalesce(pr.relationship, '')) LIKE :search ESCAPE '\\'))
                    OR (pp.archived_at IS NULL AND EXISTS (SELECT 1 FROM provider_category_assignments pca JOIN provider_categories pc ON pc.id = pca.category_id WHERE pca.provider_party_id = pp.party_id AND pca.archived_at IS NULL AND pc.archived_at IS NULL AND unicode_casefold(pc.display_name) LIKE :search ESCAPE '\\'))
                )""")
            if cursor:
                conditions.append("(unicode_casefold(p.display_name) > :cursor_name OR (unicode_casefold(p.display_name) = :cursor_name AND p.id > :cursor_id))")
                parameters["cursor_name"], parameters["cursor_id"] = cursor
            query = "SELECT pp.party_id FROM provider_profiles pp JOIN parties p ON p.id = pp.party_id"
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY unicode_casefold(p.display_name), p.id"
            if limit:
                query += " LIMIT :limit"
                parameters["limit"] = limit
            party_ids = list(session.execute(text(query), parameters).scalars())
            if not party_ids:
                return []
            profile_rows = session.execute(select(ProviderProfileModel).where(
                ProviderProfileModel.party_id.in_(party_ids),
            )).scalars()
            profiles = {item.party_id: _profile(item) for item in profile_rows}
            parties = self.party_operations.parties(party_ids)
            active_services = _group(session, ProviderServiceModel, party_ids)
            active_areas = _group(session, ProviderServiceAreaModel, party_ids)
            active_work = _group(session, ProviderWorkHistoryModel, party_ids)
            active_references = _group(session, ProviderReferenceModel, party_ids)
            active_reputation_links = _group(session, ProviderReputationLinkModel, party_ids)
            # Effective categories are a current-provider projection.  Keep the
            # assignments themselves for historical detail, but do not let an
            # archived profile retain a current categorization in list results.
            active_party_ids = [item.party_id for item in profiles.values() if item.archived_at is None]
            effective_categories = _assignment_pairs(session, active_party_ids, include_archived=False)
            results = []
            for party_id in party_ids:
                profile = profiles.get(party_id)
                party = parties.get(party_id)
                if party is None:
                    continue
                services = [_service(item) for item in active_services.get(profile.party_id, [])]
                areas = [_area(item) for item in active_areas.get(profile.party_id, [])]
                work = [_work(item) for item in active_work.get(profile.party_id, [])]
                references = [_reference(item) for item in active_references.get(profile.party_id, [])]
                categories = effective_categories.get(profile.party_id, [])
                results.append((party, profile, services, areas, len(work), len(references), len(active_reputation_links.get(profile.party_id, []),), categories))
            return results


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
    def reputation_links(self, party_id):
        return sorted(
            _many(self.connection, ProviderReputationLinkModel, party_id, _reputation_link),
            key=_reputation_sort_key,
        )
    def category(self, category_id): return _category_one(self.connection, category_id)
    def categories(self, archive_state, search=None):
        query = ProviderCategoryModel.__table__.select()
        if archive_state == "active": query = query.where(ProviderCategoryModel.archived_at.is_(None))
        elif archive_state == "archived": query = query.where(ProviderCategoryModel.archived_at.is_not(None))
        if search: query = query.where(ProviderCategoryModel.normalized_name.contains(search))
        return [_category(row) for row in self.connection.execute(query.order_by(ProviderCategoryModel.display_order, ProviderCategoryModel.normalized_name, ProviderCategoryModel.id)).mappings()]
    def category_by_create_key(self, key):
        row = self.connection.execute(ProviderCategoryModel.__table__.select().where(ProviderCategoryModel.create_idempotency_key == key)).mappings().first()
        return _category(row) if row else None
    def assignments(self, party_id, *, include_archived=True):
        query = ProviderCategoryAssignmentModel.__table__.select().where(ProviderCategoryAssignmentModel.provider_party_id == party_id).order_by(ProviderCategoryAssignmentModel.created_at, ProviderCategoryAssignmentModel.id)
        if not include_archived: query = query.where(ProviderCategoryAssignmentModel.archived_at.is_(None))
        return [_assignment(row) for row in self.connection.execute(query).mappings()]
    def assignment(self, assignment_id):
        row = self.connection.execute(ProviderCategoryAssignmentModel.__table__.select().where(ProviderCategoryAssignmentModel.id == assignment_id)).mappings().first()
        return _assignment(row) if row else None
    def assignment_by_create_key(self, key):
        row = self.connection.execute(ProviderCategoryAssignmentModel.__table__.select().where(ProviderCategoryAssignmentModel.create_idempotency_key == key)).mappings().first()
        return _assignment(row) if row else None
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
    def insert_reputation_link(self, item): self.connection.execute(ProviderReputationLinkModel.__table__.insert().values(**item.__dict__))
    def replace_reputation_link(self, item): self.connection.execute(ProviderReputationLinkModel.__table__.update().where(ProviderReputationLinkModel.id == item.id).values(**item.__dict__))
    def insert_category(self, item): self.connection.execute(ProviderCategoryModel.__table__.insert().values(**item.__dict__))
    def replace_category(self, item): self.connection.execute(ProviderCategoryModel.__table__.update().where(ProviderCategoryModel.id == item.id).values(**item.__dict__))
    def insert_assignment(self, item): self.connection.execute(ProviderCategoryAssignmentModel.__table__.insert().values(**item.__dict__))
    def replace_assignment(self, item): self.connection.execute(ProviderCategoryAssignmentModel.__table__.update().where(ProviderCategoryAssignmentModel.id == item.id).values(**item.__dict__))
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


def _matches(needle, party, services, areas, work, references, categories=()):
    texts = [party.display_name, *(item.display_name for item in services), *(item.display_name for item in areas), *(item.summary for item in work), *(item.outcome_notes or "" for item in work), *(item.reference_name or "" for item in references), *(item.organization_name or "" for item in references), *(item.relationship or "" for item in references), *(item.display_name for item in categories)]
    return any(needle in value.casefold() for value in texts)


def _like(value):
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _profile(row): return ProviderProfile(row.party_id, row.selection_status, row.selection_reason, row.notes, row.created_at, row.updated_at, row.archived_at)
def _service(row): return ProviderService(row.id, row.party_id, row.display_name, row.normalized_name, row.created_at, row.updated_at, row.archived_at)
def _area(row): return ProviderServiceArea(row.id, row.party_id, row.display_name, row.normalized_name, row.country_code, row.created_at, row.updated_at, row.archived_at)
def _work(row): return ProviderWorkHistory(row.id, row.party_id, row.property_id, row.performed_on, row.summary, row.outcome_notes, row.created_at, row.updated_at, row.archived_at)
def _reference(row): return ProviderReference(row.id, row.party_id, row.reference_name, row.organization_name, row.relationship, row.email, row.phone, row.notes, row.created_at, row.updated_at, row.archived_at)
def _reputation_link(row): return ProviderReputationLink(row.id, row.party_id, row.source_kind, row.source_name, row.normalized_source_key, row.url, row.normalized_url, row.notes, row.last_checked_on, row.created_at, row.updated_at, row.archived_at)
def _reputation_sort_key(item): return ((item.source_name or item.source_kind).casefold(), item.id)
def _category(row):
    return ProviderCategory(
        row.id, row.display_name, row.normalized_name, row.description, row.display_order,
        row.created_at, row.updated_at, row.archived_at, row.archive_reason,
        row.create_idempotency_key, row.create_request_fingerprint,
    )


def _assignment(row):
    return ProviderCategoryAssignment(
        row.id, row.provider_party_id, row.category_id, row.created_at, row.updated_at,
        row.archived_at, row.archive_reason, row.create_idempotency_key,
        row.create_request_fingerprint,
    )
def _category_one(connection, category_id):
    row = connection.execute(ProviderCategoryModel.__table__.select().where(ProviderCategoryModel.id == category_id)).mappings().first()
    return _category(row) if row else None


def _assignment_pairs(session, party_ids, *, include_archived):
    if not party_ids:
        return {}
    query = select(ProviderCategoryAssignmentModel, ProviderCategoryModel).join(
        ProviderCategoryModel, ProviderCategoryModel.id == ProviderCategoryAssignmentModel.category_id,
    ).where(ProviderCategoryAssignmentModel.provider_party_id.in_(party_ids))
    if not include_archived:
        query = query.where(
            ProviderCategoryAssignmentModel.archived_at.is_(None),
            ProviderCategoryModel.archived_at.is_(None),
        )
    pairs = {party_id: [] for party_id in party_ids}
    for assignment, category in session.execute(query):
        pairs[assignment.provider_party_id].append((_assignment(assignment), _category(category)))
    for value in pairs.values():
        value.sort(key=lambda pair: (pair[1].display_order, pair[1].normalized_name, pair[1].id, pair[0].id))
    return pairs

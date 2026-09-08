"""SQLite transaction adapter for tenant contacts."""
from collections.abc import Callable
from typing import Any, TypeVar
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.parties.domain.models import Party
from app.modules.parties.infrastructure.sqlalchemy_models import PartyModel
from app.modules.tenants.infrastructure.sqlalchemy_models import TenantContactMethodModel, TenantProfileModel
from app.modules.tenants.application.ports import TenantTransaction
from app.modules.tenants.domain.models import TenantContactMethod, TenantProfile
from app.modules.tenants.domain.contact_values import contact_search_terms, like_contains_pattern, normalize_contact_value, phone_search_value
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction
Result = TypeVar("Result")

class SQLiteTenantUnitOfWork:
    def __init__(self, database, recorder: AuditRecorder): self.engine = create_sqlite_engine(database); self.recorder = recorder
    def write(self, operation: Callable[[TenantTransaction], Result]) -> Result:
        with immediate_transaction(self.engine) as connection: return operation(_Transaction(connection, self.recorder))
    def get(self, party_id):
        with Session(self.engine) as session:
            party = session.get(PartyModel, party_id); profile = session.get(TenantProfileModel, party_id)
            if party is None or profile is None: return None
            return _party(party), _profile(profile), [_method(row) for row in session.execute(select(TenantContactMethodModel).where(TenantContactMethodModel.party_id == party_id).order_by(TenantContactMethodModel.created_at)).scalars()]
    def list(self, *, archive_state, search):
        with Session(self.engine) as session:
            query = select(TenantProfileModel, PartyModel).join(PartyModel, PartyModel.id == TenantProfileModel.party_id).order_by(PartyModel.display_name)
            if archive_state == "active": query = query.where(TenantProfileModel.archived_at.is_(None))
            elif archive_state == "archived": query = query.where(TenantProfileModel.archived_at.is_not(None))
            if search:
                terms = contact_search_terms(search)
                patterns = [like_contains_pattern(term) for term in terms]
                phone_query = phone_search_value(search)
                contact_match = select(TenantContactMethodModel.party_id).where(or_(
                    *(TenantContactMethodModel.display_value.ilike(pattern, escape="\\") for pattern in patterns),
                    *(TenantContactMethodModel.normalized_value.ilike(pattern, escape="\\") for pattern in patterns),
                ))
                name_pattern = like_contains_pattern(search.casefold())
                query = query.where(or_(
                    PartyModel.display_name.ilike(name_pattern, escape="\\"),
                    PartyModel.email.ilike(name_pattern, escape="\\"),
                    PartyModel.phone.ilike(name_pattern, escape="\\"),
                    PartyModel.phone.is_not(None) if phone_query is not None else False,
                    TenantProfileModel.party_id.in_(contact_match),
                ))
            rows = session.execute(query).all(); ids = [profile.party_id for profile, _ in rows]
            methods = {party_id: [] for party_id in ids}
            if ids:
                for item in session.execute(select(TenantContactMethodModel).where(TenantContactMethodModel.party_id.in_(ids)).order_by(TenantContactMethodModel.created_at)).scalars():
                    methods[item.party_id].append(_method(item))
            records = [(_party(party), _profile(profile), methods[profile.party_id]) for profile, party in rows]
            if search:
                return [record for record in records if _matches_search(record[0], record[2], search, terms, phone_query)]
            return records

class _Transaction:
    def __init__(self, connection: Any, recorder): self.connection = connection; self.recorder = recorder
    def party(self, party_id):
        row = self.connection.execute(PartyModel.__table__.select().where(PartyModel.id == party_id)).mappings().first(); return Party(**dict(row)) if row else None
    def profile(self, party_id):
        row = self.connection.execute(TenantProfileModel.__table__.select().where(TenantProfileModel.party_id == party_id)).mappings().first(); return _profile_mapping(row) if row else None
    def methods(self, party_id):
        rows = self.connection.execute(TenantContactMethodModel.__table__.select().where(TenantContactMethodModel.party_id == party_id).order_by(TenantContactMethodModel.created_at)).mappings().all(); return [TenantContactMethod(**dict(row)) for row in rows]
    def insert_party(self, item): self.connection.execute(PartyModel.__table__.insert().values(**item.__dict__))
    def insert_profile(self, item): self.connection.execute(TenantProfileModel.__table__.insert().values(**_profile_values(item)))
    def replace_profile(self, item): self.connection.execute(TenantProfileModel.__table__.update().where(TenantProfileModel.party_id == item.party_id).values(**_profile_values(item)))
    def insert_method(self, item): self.connection.execute(TenantContactMethodModel.__table__.insert().values(**item.__dict__))
    def replace_method(self, item): self.connection.execute(TenantContactMethodModel.__table__.update().where(TenantContactMethodModel.id == item.id).values(**item.__dict__))
    def record_change(self, **change): self.recorder.record_change(self.connection.connection.driver_connection, **change)
def _party(row): return Party(**{key: getattr(row, key) for key in Party.__dataclass_fields__})
def _profile(row): return TenantProfile(row.party_id, row.preferred_contact_method_id, bool(row.do_not_contact), row.notes, row.created_at, row.updated_at, row.archived_at)
def _profile_mapping(row): return TenantProfile(row["party_id"], row["preferred_contact_method_id"], bool(row["do_not_contact"]), row["notes"], row["created_at"], row["updated_at"], row["archived_at"])
def _profile_values(item): return {**item.__dict__, "do_not_contact": int(item.do_not_contact)}
def _method(row): return TenantContactMethod(**{key: getattr(row, key) for key in TenantContactMethod.__dataclass_fields__})


def _matches_search(party, methods, search, terms, phone_query):
    raw = search.casefold()
    party_values = (party.display_name, party.email, party.phone)
    if any(value is not None and raw in value.casefold() for value in party_values):
        return True
    if phone_query is not None and party.phone is not None:
        try:
            if phone_query in normalize_contact_value("phone", party.phone).lstrip("+"):
                return True
        except ValueError:
            pass
    return any(
        any(term in value.casefold() for term in terms)
        for method in methods
        for value in (method.display_value, method.normalized_value)
    )

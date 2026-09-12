"""SQLite adapter for shared party contact lifecycle operations."""

from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.parties.application.ports import (
    ContactReferenceGuard,
    PartyRoleActivityGuard,
    PartyTransaction,
    PartyTransactionOperations,
)
from app.modules.parties.domain.contact_values import (
    contact_search_terms,
    like_contains_pattern,
)
from app.modules.parties.domain.models import Party, PartyContactMethod
from app.modules.parties.infrastructure.sqlalchemy_models import PartyContactMethodModel, PartyModel
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

Result = TypeVar("Result")


class SQLitePartyUnitOfWork:
    def __init__(self, database, recorder: AuditRecorder,
                 contact_reference_guards: tuple[ContactReferenceGuard, ...] = (),
                 role_activity_guards: tuple[PartyRoleActivityGuard, ...] = ()) -> None:
        self.engine = create_sqlite_engine(database)
        self.recorder = recorder
        self.contact_reference_guards = contact_reference_guards
        self.role_activity_guards = role_activity_guards

    def write(self, operation: Callable[[PartyTransaction], Result]) -> Result:
        with immediate_transaction(self.engine) as connection:
            return operation(_Transaction(connection, self.recorder, self.contact_reference_guards, self.role_activity_guards))

    def methods(self, party_id: str) -> tuple[Party, list[PartyContactMethod]] | None:
        with Session(self.engine) as session:
            party = session.get(PartyModel, party_id)
            if party is None:
                return None
            methods = session.query(PartyContactMethodModel).filter_by(party_id=party_id).order_by(
                PartyContactMethodModel.created_at
            ).all()
            return _party(party), [_method(item) for item in methods]


class SQLitePartyOperations(PartyTransactionOperations):
    """Reusable party reads/writes for other feature transactions."""

    def __init__(self, database) -> None:
        self.engine = create_sqlite_engine(database)

    def party(self, connection, party_id):
        row = connection.execute(
            PartyModel.__table__.select().where(PartyModel.id == party_id)
        ).mappings().first()
        return Party(**dict(row)) if row else None

    def exists(self, connection, party_id):
        return connection.execute(PartyModel.__table__.select().where(PartyModel.id == party_id)).first() is not None

    def party_map(self, connection, party_ids):
        if not party_ids:
            return {}
        rows = connection.execute(
            PartyModel.__table__.select().where(PartyModel.id.in_(party_ids))
        ).mappings()
        return {row["id"]: Party(**dict(row)) for row in rows}

    def methods(self, connection, party_id):
        rows = connection.execute(
            PartyContactMethodModel.__table__.select()
            .where(PartyContactMethodModel.party_id == party_id)
            .order_by(PartyContactMethodModel.created_at)
        ).mappings().all()
        return [PartyContactMethod(**dict(row)) for row in rows]

    def insert_party(self, connection, party):
        connection.execute(PartyModel.__table__.insert().values(**party.__dict__))

    def insert_method(self, connection, method):
        connection.execute(PartyContactMethodModel.__table__.insert().values(**method.__dict__))

    def duplicate_party_ids(self, connection, methods, limit):
        if not methods:
            return []
        clauses = [
            (PartyContactMethodModel.method_kind == item.method_kind)
            & (PartyContactMethodModel.normalized_value == item.normalized_value)
            & (
                PartyContactMethodModel.extension == item.extension
                if item.extension is not None
                else PartyContactMethodModel.extension.is_(None)
            )
            for item in methods
        ]
        query = (
            select(PartyContactMethodModel.party_id)
            .join(PartyModel)
            .where(
                PartyContactMethodModel.status == "active",
                PartyModel.archived_at.is_(None),
                or_(*clauses),
            )
            .distinct()
            .order_by(PartyModel.display_name, PartyContactMethodModel.party_id)
            .limit(limit)
        )
        return list(connection.execute(query).scalars())

    def parties(self, party_ids):
        if not party_ids:
            return {}
        with Session(self.engine) as session:
            rows = session.execute(
                select(PartyModel).where(PartyModel.id.in_(party_ids))
            ).scalars()
            return {row.id: _party(row) for row in rows}

    def methods_for_parties(self, party_ids):
        result = {party_id: [] for party_id in party_ids}
        if not party_ids:
            return result
        with Session(self.engine) as session:
            rows = session.execute(
                select(PartyContactMethodModel)
                .where(PartyContactMethodModel.party_id.in_(party_ids))
                .order_by(PartyContactMethodModel.created_at)
            ).scalars()
            for row in rows:
                result[row.party_id].append(_method(row))
        return result

    def search(self, *, active_only, search):
        with Session(self.engine) as session:
            query = select(PartyModel).order_by(PartyModel.display_name, PartyModel.id)
            if active_only:
                query = query.where(PartyModel.archived_at.is_(None))
            if search:
                terms = contact_search_terms(search)
                patterns = [like_contains_pattern(term) for term in terms]
                contact_match = select(PartyContactMethodModel.party_id).where(
                    PartyContactMethodModel.status == "active",
                    or_(
                        *(PartyContactMethodModel.display_value.ilike(pattern, escape="\\") for pattern in patterns),
                        *(PartyContactMethodModel.normalized_value.ilike(pattern, escape="\\") for pattern in patterns),
                    ),
                )
                query = query.where(or_(
                    PartyModel.display_name.ilike(like_contains_pattern(search), escape="\\"),
                    PartyModel.id.in_(contact_match),
                ))
            return [_party(row) for row in session.execute(query).scalars()]


class SQLitePartyReadOperations:
    def __init__(self, operations: SQLitePartyOperations) -> None:
        self.operations = operations

    def get_party(self, party_id):
        return self.operations.parties([party_id]).get(party_id)

    def parties(self, party_ids):
        return self.operations.parties(party_ids)

    def methods_for_parties(self, party_ids):
        return self.operations.methods_for_parties(party_ids)

    def search(self, *, active_only, search):
        return self.operations.search(active_only=active_only, search=search)


class _Transaction:
    def __init__(self, connection: Any, recorder: AuditRecorder,
                 guards: tuple[ContactReferenceGuard, ...],
                 role_guards: tuple[PartyRoleActivityGuard, ...]) -> None:
        self.connection = connection
        self.recorder = recorder
        self.guards = guards
        self.role_guards = role_guards

    def party(self, party_id):
        row = self.connection.execute(
            PartyModel.__table__.select().where(PartyModel.id == party_id)
        ).mappings().first()
        return Party(**dict(row)) if row else None

    def methods(self, party_id):
        rows = self.connection.execute(
            PartyContactMethodModel.__table__.select()
            .where(PartyContactMethodModel.party_id == party_id)
            .order_by(PartyContactMethodModel.created_at)
        ).mappings().all()
        return [PartyContactMethod(**dict(row)) for row in rows]

    def duplicate_party_ids(self, methods, limit):
        if not methods:
            return []
        clauses = [
            (PartyContactMethodModel.method_kind == item.method_kind)
            & (PartyContactMethodModel.normalized_value == item.normalized_value)
            & (PartyContactMethodModel.extension == item.extension if item.extension is not None else PartyContactMethodModel.extension.is_(None))
            for item in methods
        ]
        query = select(PartyContactMethodModel.party_id).join(PartyModel).where(
            PartyContactMethodModel.status == "active", PartyModel.archived_at.is_(None), or_(*clauses)
        ).distinct().order_by(PartyModel.display_name, PartyContactMethodModel.party_id).limit(limit)
        return list(self.connection.execute(query).scalars())

    def insert_method(self, item):
        self.connection.execute(PartyContactMethodModel.__table__.insert().values(**item.__dict__))

    def insert_party(self, item):
        self.connection.execute(PartyModel.__table__.insert().values(**item.__dict__))

    def replace_party(self, item):
        self.connection.execute(
            PartyModel.__table__.update().where(PartyModel.id == item.id).values(**item.__dict__)
        )

    def party_role_conflicts(self, party_id):
        return [message for guard in self.role_guards if (message := guard.conflict(self.connection, party_id))]

    def replace_method(self, item):
        self.connection.execute(
            PartyContactMethodModel.__table__.update()
            .where(PartyContactMethodModel.id == item.id)
            .values(**item.__dict__)
        )

    def resolve_contact_references(self, party_id, method_id, resolutions,
                                   timestamp, correlation_id):
        consumed = []
        for guard in self.guards:
            consumed.extend(guard.resolve_before_archive(
                self.connection, party_id, method_id, resolutions, timestamp, correlation_id
            ))
        return tuple(consumed)

    def record_change(self, **change):
        self.recorder.record_change(self.connection.connection.driver_connection, **change)


def _party(row) -> Party:
    return Party(**{field: getattr(row, field) for field in Party.__dataclass_fields__})


def _method(row) -> PartyContactMethod:
    return PartyContactMethod(**{
        field: getattr(row, field) for field in PartyContactMethod.__dataclass_fields__
    })

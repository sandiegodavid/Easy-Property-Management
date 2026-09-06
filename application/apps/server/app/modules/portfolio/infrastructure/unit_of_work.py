"""SQLite transaction adapter for PORT-001."""

from __future__ import annotations

from collections.abc import Callable
from collections import defaultdict
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.portfolio.application.ports import PortfolioTransaction
from app.modules.portfolio.domain.models import Party, Property, PropertyOwnership
from app.modules.portfolio.infrastructure.sqlalchemy_models import PartyModel, PropertyModel, PropertyOwnershipModel
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

Result = TypeVar("Result")


class SQLitePortfolioUnitOfWork:
    def __init__(self, database, recorder: AuditRecorder) -> None:
        self.engine = create_sqlite_engine(database); self.recorder = recorder

    def write(self, operation: Callable[[PortfolioTransaction], Result]) -> Result:
        with immediate_transaction(self.engine) as connection:
            return operation(_SQLitePortfolioTransaction(connection, self.recorder))

    def get_property(self, property_id: str) -> Property | None:
        with Session(self.engine) as session:
            row = session.get(PropertyModel, property_id)
            return _property(row) if row else None

    def ownerships(self, property_id: str) -> list[PropertyOwnership]:
        with Session(self.engine) as session:
            query = select(PropertyOwnershipModel).where(PropertyOwnershipModel.property_id == property_id).order_by(PropertyOwnershipModel.created_at)
            return [_ownership(row) for row in session.execute(query).scalars()]

    def parties(self, *, active_only: bool = False) -> list[Party]:
        with Session(self.engine) as session:
            query = select(PartyModel).order_by(PartyModel.display_name)
            if active_only: query = query.where(PartyModel.archived_at.is_(None))
            return [_party(row) for row in session.execute(query).scalars()]

    def parties_for_ownerships(self, ownerships: list[PropertyOwnership]) -> dict[str, Party]:
        party_ids = {item.party_id for item in ownerships if item.party_id is not None}
        if not party_ids: return {}
        with Session(self.engine) as session:
            return {item.id: _party(item) for item in session.execute(select(PartyModel).where(PartyModel.id.in_(party_ids))).scalars()}

    def property_views(self, *, status: str | None = None) -> list[tuple[Property, list[PropertyOwnership], dict[str, Party]]]:
        with Session(self.engine) as session:
            query = select(PropertyModel).order_by(PropertyModel.display_name)
            if status is not None: query = query.where(PropertyModel.status == status)
            properties = [_property(row) for row in session.execute(query).scalars()]
            property_ids = [item.id for item in properties]
            if not property_ids: return []
            ownerships = [_ownership(row) for row in session.execute(select(PropertyOwnershipModel).where(PropertyOwnershipModel.property_id.in_(property_ids)).order_by(PropertyOwnershipModel.created_at)).scalars()]
            party_ids = {item.party_id for item in ownerships if item.party_id is not None}
            parties = {} if not party_ids else {item.id: _party(item) for item in session.execute(select(PartyModel).where(PartyModel.id.in_(party_ids))).scalars()}
            by_property: dict[str, list[PropertyOwnership]] = defaultdict(list)
            for ownership in ownerships:
                by_property[ownership.property_id].append(ownership)
            return [(item, by_property[item.id], parties) for item in properties]


class _SQLitePortfolioTransaction:
    def __init__(self, connection: Any, recorder: AuditRecorder) -> None:
        self.connection = connection; self.recorder = recorder

    def get_property(self, property_id: str) -> Property | None:
        row = self.connection.execute(PropertyModel.__table__.select().where(PropertyModel.id == property_id)).mappings().first()
        return Property(**dict(row)) if row else None

    def get_party(self, party_id: str) -> Party | None:
        row = self.connection.execute(PartyModel.__table__.select().where(PartyModel.id == party_id)).mappings().first()
        return Party(**dict(row)) if row else None

    def ownerships_at(self, property_id: str, when: str) -> list[PropertyOwnership]:
        rows = self.connection.execute(PropertyOwnershipModel.__table__.select().where(
            PropertyOwnershipModel.property_id == property_id, PropertyOwnershipModel.starts_on <= when,
            (PropertyOwnershipModel.ends_on.is_(None) | (PropertyOwnershipModel.ends_on > when)),
        )).mappings().all()
        return [PropertyOwnership(**dict(row)) for row in rows]

    def future_ownerships(self, property_id: str, after: str) -> list[PropertyOwnership]:
        rows = self.connection.execute(PropertyOwnershipModel.__table__.select().where(
            PropertyOwnershipModel.property_id == property_id, PropertyOwnershipModel.starts_on > after,
            PropertyOwnershipModel.ends_on.is_(None),
        )).mappings().all()
        return [PropertyOwnership(**dict(row)) for row in rows]

    def open_ownerships_for_party(self, party_id: str, today: str) -> list[PropertyOwnership]:
        rows = self.connection.execute(PropertyOwnershipModel.__table__.select().where(
            PropertyOwnershipModel.party_id == party_id,
            (PropertyOwnershipModel.ends_on.is_(None) | (PropertyOwnershipModel.ends_on > today)),
        )).mappings().all()
        return [PropertyOwnership(**dict(row)) for row in rows]

    def insert_party(self, party: Party) -> None:
        self.connection.execute(PartyModel.__table__.insert().values(**party.__dict__))

    def replace_party(self, party: Party) -> None:
        self.connection.execute(PartyModel.__table__.update().where(PartyModel.id == party.id).values(**party.__dict__))

    def insert_property(self, property: Property) -> None:
        self.connection.execute(PropertyModel.__table__.insert().values(**property.__dict__))

    def replace_property(self, property: Property) -> None:
        self.connection.execute(PropertyModel.__table__.update().where(PropertyModel.id == property.id).values(**property.__dict__))

    def insert_ownership(self, ownership: PropertyOwnership) -> None:
        self.connection.execute(PropertyOwnershipModel.__table__.insert().values(**ownership.__dict__))

    def end_ownership(self, ownership: PropertyOwnership) -> None:
        self.connection.execute(PropertyOwnershipModel.__table__.update().where(PropertyOwnershipModel.id == ownership.id).values(
            ends_on=ownership.ends_on, ended_at=ownership.ended_at
        ))

    def record_change(self, *, entity_type: str, entity_id: str, action: str,
                      before: dict[str, Any] | None, after: dict[str, Any] | None,
                      reason: str, correlation_id: str) -> None:
        self.recorder.record_change(
            self.connection.connection.driver_connection, entity_type=entity_type, entity_id=entity_id,
            action=action, before=before, after=after, reason=reason, correlation_id=correlation_id,
        )


def _party(row: PartyModel) -> Party:
    return Party(**{name: getattr(row, name) for name in Party.__dataclass_fields__})


def _property(row: PropertyModel) -> Property:
    return Property(**{name: getattr(row, name) for name in Property.__dataclass_fields__})


def _ownership(row: PropertyOwnershipModel) -> PropertyOwnership:
    return PropertyOwnership(**{name: getattr(row, name) for name in PropertyOwnership.__dataclass_fields__})

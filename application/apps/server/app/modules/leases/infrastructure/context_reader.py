"""SQLite lease context facts for caller-owned transactions."""

from collections.abc import Collection, Mapping
from typing import Any

from sqlalchemy import or_, select

from app.modules.leases.infrastructure.sqlalchemy_models import (
    LeaseModel,
    LeaseParticipantModel,
    LeaseTerminationCaseModel,
    LeaseTerminationProposalModel,
    LeaseTermModel,
)
from app.modules.portfolio.infrastructure.sqlalchemy_models import SpaceModel


class SQLiteLeaseContextReader:
    def lease_space_id(self, connection: Any, lease_id: str) -> str | None:
        return connection.execute(
            select(LeaseModel.space_id).where(LeaseModel.id == lease_id)
        ).scalar_one_or_none()

    def term_context(self, connection: Any, lease_id: str, term_id: str) -> Mapping[str, object] | None:
        lease = connection.execute(
            LeaseModel.__table__.select().where(LeaseModel.id == lease_id)
        ).mappings().first()
        term = connection.execute(
            LeaseTermModel.__table__.select().where(
                LeaseTermModel.id == term_id, LeaseTermModel.lease_id == lease_id,
            )
        ).mappings().first()
        if lease is None or term is None:
            return None
        return {"lease": lease, "term": term}

    def term_contexts(self, connection: Any, pairs: Collection[tuple[str, str]]) -> Mapping[tuple[str, str], Mapping[str, object]]:
        pairs = set(pairs)
        if not pairs:
            return {}
        lease_ids = {lease_id for lease_id, _ in pairs}
        term_predicates = [
            (LeaseTermModel.lease_id == lease_id) & (LeaseTermModel.id == term_id)
            for lease_id, term_id in pairs
        ]
        leases = {
            row["id"]: row
            for row in connection.execute(
                LeaseModel.__table__.select().where(LeaseModel.id.in_(lease_ids))
            ).mappings()
        }
        terms = {
            (row["lease_id"], row["id"]): row
            for row in connection.execute(
                LeaseTermModel.__table__.select().where(or_(*term_predicates))
            ).mappings()
        }
        responsibilities = {}
        statement = select(
            LeaseTerminationCaseModel.lease_id,
            LeaseTerminationProposalModel.rent_responsibility_ends_on,
            LeaseTerminationProposalModel.created_at,
        ).join(LeaseTerminationCaseModel).where(
            LeaseTerminationCaseModel.lease_id.in_(lease_ids),
            LeaseTerminationCaseModel.status.in_(("accepted", "completed")),
            LeaseTerminationProposalModel.status == "accepted",
        ).order_by(LeaseTerminationCaseModel.lease_id, LeaseTerminationProposalModel.created_at.desc())
        for row in connection.execute(statement).mappings():
            responsibilities.setdefault(row["lease_id"], row["rent_responsibility_ends_on"])
        return {
            pair: {"lease": lease, "term": term, "rent_responsibility_ends_on": responsibilities.get(pair[0])}
            for pair in pairs
            if (lease := leases.get(pair[0])) is not None and (term := terms.get(pair)) is not None
        }

    def participant_active(self, connection: Any, lease_id: str, party_id: str, on: str) -> bool:
        return connection.execute(select(LeaseParticipantModel.id).where(
            LeaseParticipantModel.lease_id == lease_id,
            LeaseParticipantModel.tenant_party_id == party_id,
            LeaseParticipantModel.starts_on <= on,
            or_(LeaseParticipantModel.ends_on.is_(None), LeaseParticipantModel.ends_on > on),
        ).limit(1)).first() is not None

    def rent_responsibility_ends_on(self, connection: Any, lease_id: str) -> str | None:
        return self._rent_responsibility_ends_on(connection, lease_id)

    def participant_ids(self, connection: Any, lease_id: str) -> set[str]:
        return set(connection.execute(select(LeaseParticipantModel.tenant_party_id).where(
            LeaseParticipantModel.lease_id == lease_id
        )).scalars())

    def participant_active_for_property(self, connection: Any, party_id: str, property_id: str, space_id: str | None, on: str) -> bool:
        query = select(LeaseParticipantModel.id).join(
            LeaseModel, LeaseModel.id == LeaseParticipantModel.lease_id,
        ).join(SpaceModel, SpaceModel.id == LeaseModel.space_id).where(
            LeaseParticipantModel.tenant_party_id == party_id,
            SpaceModel.property_id == property_id,
            LeaseModel.status.in_(("executed", "ended", "terminated")),
            LeaseModel.occupancy_starts_on <= on,
            or_(LeaseModel.actual_move_out_on.is_(None), LeaseModel.actual_move_out_on > on),
            LeaseParticipantModel.starts_on <= on,
            or_(LeaseParticipantModel.ends_on.is_(None), LeaseParticipantModel.ends_on > on),
        )
        if space_id is not None:
            query = query.where(LeaseModel.space_id == space_id)
        return connection.execute(query.limit(1)).first() is not None

    @staticmethod
    def _rent_responsibility_ends_on(connection: Any, lease_id: str) -> str | None:
        return connection.execute(select(LeaseTerminationProposalModel.rent_responsibility_ends_on)
            .join(LeaseTerminationCaseModel)
            .where(
                LeaseTerminationCaseModel.lease_id == lease_id,
                LeaseTerminationCaseModel.status.in_(("accepted", "completed")),
                LeaseTerminationProposalModel.status == "accepted",
            )
            .order_by(LeaseTerminationProposalModel.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

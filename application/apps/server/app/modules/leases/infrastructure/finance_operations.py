"""Lease-owned FIN-001 projection, with portfolio context supplied at composition."""
from sqlalchemy import or_, select
from app.modules.finance.application.ports import LeaseTermFinanceSnapshot
from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseTermModel, LeaseTerminationCaseModel, LeaseTerminationProposalModel

class SQLiteLeaseFinanceOperations:
    def __init__(self, portfolio_operations): self.portfolio_operations = portfolio_operations
    def lease_time_zone(self, connection, lease_id):
        lease = connection.execute(LeaseModel.__table__.select().where(LeaseModel.id == lease_id)).mappings().first()
        if not lease: return None
        context = self.portfolio_operations.context_for_space(connection, lease["space_id"])
        return context["time_zone"] if context else None
    def term_snapshot(self, connection, lease_id, term_id):
        term = connection.execute(LeaseTermModel.__table__.select().where(LeaseTermModel.id == term_id, LeaseTermModel.lease_id == lease_id)).mappings().first()
        lease = connection.execute(LeaseModel.__table__.select().where(LeaseModel.id == lease_id)).mappings().first()
        if not term or not lease or lease["status"] not in {"executed", "ended", "terminated"}: return None
        return self._snapshot(connection, lease, term)
    def historical_term_snapshot(self, connection, lease_id, term_id):
        term = connection.execute(LeaseTermModel.__table__.select().where(LeaseTermModel.id == term_id, LeaseTermModel.lease_id == lease_id)).mappings().first()
        lease = connection.execute(LeaseModel.__table__.select().where(LeaseModel.id == lease_id)).mappings().first()
        if not term or not lease: return None
        return self._snapshot(connection, lease, term)
    def historical_term_snapshots(self, connection, pairs):
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
        contexts = self.portfolio_operations.contexts_for_spaces(
            connection, [lease["space_id"] for lease in leases.values()]
        )
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
        result = {}
        for key in pairs:
            lease = leases.get(key[0]); term = terms.get(key)
            context = contexts.get(lease["space_id"]) if lease else None
            if lease and term and context:
                result[key] = LeaseTermFinanceSnapshot(
                    term["id"], lease["id"], lease["status"], context["property_id"],
                    context["space_id"], context["time_zone"], term["effective_on"],
                    term["ends_on"], term["base_rent_minor"], term["currency_code"],
                    term["payment_frequency"], term["payment_due_day"],
                    lease["actual_move_out_on"], responsibilities.get(lease["id"]),
                )
        return result
    def _snapshot(self, connection, lease, term):
        context = self.portfolio_operations.context_for_space(connection, lease["space_id"])
        if not context: return None
        responsibility = connection.execute(select(LeaseTerminationProposalModel.rent_responsibility_ends_on).join(LeaseTerminationCaseModel).where(LeaseTerminationCaseModel.lease_id == lease["id"], LeaseTerminationCaseModel.status.in_(("accepted", "completed")), LeaseTerminationProposalModel.status == "accepted").order_by(LeaseTerminationProposalModel.created_at.desc()).limit(1)).scalar_one_or_none()
        return LeaseTermFinanceSnapshot(term["id"], lease["id"], lease["status"], context["property_id"], context["space_id"], context["time_zone"], term["effective_on"], term["ends_on"], term["base_rent_minor"], term["currency_code"], term["payment_frequency"], term["payment_due_day"], lease["actual_move_out_on"], responsibility)

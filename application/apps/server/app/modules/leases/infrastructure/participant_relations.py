"""Lease-owned participant projection; no sessions or consumer policy."""

from sqlalchemy import select

from app.modules.leases.infrastructure.sqlalchemy_models import LeaseModel, LeaseParticipantModel


class SQLiteLeaseParticipantRelations:
    def participants(self):
        return (
            select(
                LeaseModel.id.label("lease_id"),
                LeaseModel.space_id,
                LeaseModel.status.label("lease_status"),
                LeaseModel.occupancy_starts_on,
                LeaseModel.actual_move_out_on,
                LeaseParticipantModel.tenant_party_id.label("party_id"),
                LeaseParticipantModel.participant_role,
                LeaseParticipantModel.starts_on,
                LeaseParticipantModel.ends_on,
            )
            .join(LeaseParticipantModel, LeaseParticipantModel.lease_id == LeaseModel.id)
            .subquery("lease_participant_facts")
        )

"""SQLite transaction adapter for LEASE-001."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.files.infrastructure.sqlalchemy_models import FileLinkModel, FileRecordModel
from app.modules.leases.application.ports import LeaseConflictError, LeaseTransaction
from app.modules.leases.domain.models import Lease, LeaseParticipant, LeaseRenewalOption, LeaseTerm, LeaseTerminationCase, LeaseTerminationProposal
from app.modules.leases.infrastructure.sqlalchemy_models import (
    LeaseModel,
    LeaseParticipantModel,
    LeaseRenewalOptionModel,
    LeaseTermModel,
    LeaseTerminationCaseModel,
    LeaseTerminationProposalModel,
)
from app.modules.portfolio.domain.models import Property, Space, SpaceOccupancyPeriod
from app.modules.portfolio.infrastructure.sqlalchemy_models import PropertyModel, SpaceModel, SpaceOccupancyPeriodModel
from app.modules.tenants.infrastructure.sqlalchemy_models import TenantProfileModel
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

Result = TypeVar("Result")


class SQLiteLeaseUnitOfWork:
    def __init__(self, database, recorder: AuditRecorder) -> None:
        self.engine = create_sqlite_engine(database)
        self.recorder = recorder

    def write(self, operation: Callable[[LeaseTransaction], Result]) -> Result:
        try:
            with immediate_transaction(self.engine) as connection:
                return operation(_Transaction(connection, self.recorder))
        except OperationalError as error:
            if "locked" in str(error).casefold():
                raise LeaseConflictError("The lease changed concurrently; reload it and try again.") from error
            raise

    def lease_view(self, lease_id: str):
        with Session(self.engine) as session:
            lease = session.get(LeaseModel, lease_id)
            if lease is None:
                return None
            return _view_record(session, lease)

    def lease_views(self, *, status=None, property_id=None, space_id=None, tenant_party_id=None,
                    contract_start_from=None, contract_start_to=None, renewal_due_on_or_before=None):
        with Session(self.engine) as session:
            query = select(LeaseModel).join(SpaceModel, SpaceModel.id == LeaseModel.space_id)
            if status is not None:
                query = query.where(LeaseModel.status == status)
            if property_id is not None:
                query = query.where(SpaceModel.property_id == property_id)
            if space_id is not None:
                query = query.where(LeaseModel.space_id == space_id)
            if tenant_party_id is not None:
                query = query.where(
                    LeaseModel.id.in_(
                        select(LeaseParticipantModel.lease_id).where(
                            LeaseParticipantModel.tenant_party_id == tenant_party_id
                        )
                    )
                )
            if contract_start_from is not None:
                query = query.where(LeaseModel.contract_starts_on >= contract_start_from)
            if contract_start_to is not None:
                query = query.where(LeaseModel.contract_starts_on <= contract_start_to)
            if renewal_due_on_or_before is not None:
                query = query.where(LeaseModel.id.in_(select(LeaseRenewalOptionModel.lease_id).where(
                    LeaseRenewalOptionModel.status == "open",
                    or_(
                        LeaseRenewalOptionModel.notice_due_on <= renewal_due_on_or_before,
                        LeaseRenewalOptionModel.response_due_on <= renewal_due_on_or_before,
                    ),
                )))
            leases = session.execute(query.order_by(LeaseModel.contract_starts_on, LeaseModel.id)).scalars().all()
            return [_view_record(session, lease) for lease in leases]

    def termination_case_view(self, case_id):
        with Session(self.engine) as session:
            item = session.get(LeaseTerminationCaseModel, case_id)
            return None if item is None else _termination_record(session, item)

    def termination_case_views(self, lease_id):
        with Session(self.engine) as session:
            items = session.execute(select(LeaseTerminationCaseModel).where(LeaseTerminationCaseModel.lease_id == lease_id).order_by(LeaseTerminationCaseModel.created_at)).scalars()
            return [_termination_record(session, item) for item in items]


class _Transaction:
    def __init__(self, connection: Any, recorder: AuditRecorder) -> None:
        self.connection = connection
        self.recorder = recorder

    def lease(self, lease_id):
        return _mapped(self.connection, LeaseModel, lease_id, Lease)

    def space(self, space_id):
        return _mapped(self.connection, SpaceModel, space_id, Space)

    def property(self, property_id):
        return _mapped(self.connection, PropertyModel, property_id, Property)

    def tenant_profile_active(self, party_id):
        row = self.connection.execute(
            TenantProfileModel.__table__.select().where(TenantProfileModel.party_id == party_id)
        ).mappings().first()
        return row is not None and row["archived_at"] is None

    def terms(self, lease_id):
        return _mapped_many(self.connection, LeaseTermModel, LeaseTerm, LeaseTermModel.lease_id == lease_id, LeaseTermModel.effective_on)

    def participants(self, lease_id):
        return _mapped_many(self.connection, LeaseParticipantModel, LeaseParticipant, LeaseParticipantModel.lease_id == lease_id, LeaseParticipantModel.created_at)

    def renewal_options(self, lease_id):
        return _mapped_many(self.connection, LeaseRenewalOptionModel, LeaseRenewalOption, LeaseRenewalOptionModel.lease_id == lease_id, LeaseRenewalOptionModel.created_at)

    def termination_cases(self, lease_id):
        return _mapped_many(self.connection, LeaseTerminationCaseModel, LeaseTerminationCase, LeaseTerminationCaseModel.lease_id == lease_id, LeaseTerminationCaseModel.created_at)

    def termination_case(self, case_id):
        return _mapped(self.connection, LeaseTerminationCaseModel, case_id, LeaseTerminationCase)

    def termination_proposals(self, case_id):
        return _mapped_many(self.connection, LeaseTerminationProposalModel, LeaseTerminationProposal, LeaseTerminationProposalModel.termination_case_id == case_id, LeaseTerminationProposalModel.proposal_version)

    def occupancy_periods(self, space_id):
        return _mapped_many(self.connection, SpaceOccupancyPeriodModel, SpaceOccupancyPeriod, SpaceOccupancyPeriodModel.space_id == space_id, SpaceOccupancyPeriodModel.starts_on)

    def insert_lease(self, item):
        self.connection.execute(LeaseModel.__table__.insert().values(**item.__dict__))

    def replace_lease(self, item):
        self.connection.execute(LeaseModel.__table__.update().where(LeaseModel.id == item.id).values(**item.__dict__))

    def insert_term(self, item):
        self.connection.execute(LeaseTermModel.__table__.insert().values(**item.__dict__))

    def delete_terms(self, lease_id):
        self.connection.execute(LeaseTermModel.__table__.delete().where(LeaseTermModel.lease_id == lease_id))

    def insert_participant(self, item):
        self.connection.execute(LeaseParticipantModel.__table__.insert().values(**item.__dict__))

    def replace_participant(self, item):
        self.connection.execute(LeaseParticipantModel.__table__.update().where(LeaseParticipantModel.id == item.id).values(**item.__dict__))

    def delete_participant(self, participant_id):
        self.connection.execute(LeaseParticipantModel.__table__.delete().where(LeaseParticipantModel.id == participant_id))

    def insert_renewal_option(self, item):
        self.connection.execute(LeaseRenewalOptionModel.__table__.insert().values(**item.__dict__))

    def replace_renewal_option(self, item):
        self.connection.execute(LeaseRenewalOptionModel.__table__.update().where(LeaseRenewalOptionModel.id == item.id).values(**item.__dict__))

    def insert_termination_case(self, item):
        self.connection.execute(LeaseTerminationCaseModel.__table__.insert().values(**item.__dict__))

    def replace_termination_case(self, item):
        self.connection.execute(LeaseTerminationCaseModel.__table__.update().where(LeaseTerminationCaseModel.id == item.id).values(**item.__dict__))

    def insert_termination_proposal(self, item):
        self.connection.execute(LeaseTerminationProposalModel.__table__.insert().values(**item.__dict__))

    def replace_termination_proposal(self, item):
        self.connection.execute(LeaseTerminationProposalModel.__table__.update().where(LeaseTerminationProposalModel.id == item.id).values(**item.__dict__))

    def insert_occupancy_period(self, item):
        self.connection.execute(SpaceOccupancyPeriodModel.__table__.insert().values(**item.__dict__))

    def replace_occupancy_period(self, item):
        self.connection.execute(SpaceOccupancyPeriodModel.__table__.update().where(SpaceOccupancyPeriodModel.id == item.id).values(**item.__dict__))

    def record_change(self, **change):
        self.recorder.record_change(self.connection.connection.driver_connection, **change)


def _mapped(connection, model, record_id, domain):
    row = connection.execute(model.__table__.select().where(model.id == record_id)).mappings().first()
    return domain(**dict(row)) if row else None


def _mapped_many(connection, model, domain, condition, ordering):
    rows = connection.execute(model.__table__.select().where(condition).order_by(ordering)).mappings().all()
    return [domain(**dict(row)) for row in rows]


def _view_record(session: Session, row: LeaseModel):
    lease = Lease(**{name: getattr(row, name) for name in Lease.__dataclass_fields__})
    terms = [LeaseTerm(**{name: getattr(item, name) for name in LeaseTerm.__dataclass_fields__}) for item in session.execute(select(LeaseTermModel).where(LeaseTermModel.lease_id == row.id).order_by(LeaseTermModel.effective_on)).scalars()]
    participants = [LeaseParticipant(**{name: getattr(item, name) for name in LeaseParticipant.__dataclass_fields__}) for item in session.execute(select(LeaseParticipantModel).where(LeaseParticipantModel.lease_id == row.id).order_by(LeaseParticipantModel.created_at)).scalars()]
    renewals = [LeaseRenewalOption(**{name: getattr(item, name) for name in LeaseRenewalOption.__dataclass_fields__}) for item in session.execute(select(LeaseRenewalOptionModel).where(LeaseRenewalOptionModel.lease_id == row.id).order_by(LeaseRenewalOptionModel.created_at)).scalars()]
    files = [
        {
            "id": file.id,
            "originalName": file.original_name,
            "mediaType": file.media_type,
            "sizeBytes": file.size_bytes,
            "contentSha256": file.content_sha256,
            "linkId": link.id,
            "purpose": link.purpose,
        }
        for link, file in session.execute(
            select(FileLinkModel, FileRecordModel)
            .join(FileRecordModel, FileRecordModel.id == FileLinkModel.file_id)
            .where(FileLinkModel.entity_type == "lease", FileLinkModel.entity_id == row.id)
            .order_by(FileLinkModel.created_at)
        )
    ]
    return lease, terms, participants, renewals, files


def _termination_record(session: Session, row: LeaseTerminationCaseModel):
    case = LeaseTerminationCase(**{name: getattr(row, name) for name in LeaseTerminationCase.__dataclass_fields__})
    proposals = [LeaseTerminationProposal(**{name: getattr(item, name) for name in LeaseTerminationProposal.__dataclass_fields__}) for item in session.execute(select(LeaseTerminationProposalModel).where(LeaseTerminationProposalModel.termination_case_id == row.id).order_by(LeaseTerminationProposalModel.proposal_version)).scalars()]
    files = [
        {"id": file.id, "originalName": file.original_name, "mediaType": file.media_type,
         "sizeBytes": file.size_bytes, "contentSha256": file.content_sha256,
         "linkId": link.id, "purpose": link.purpose}
        for link, file in session.execute(
            select(FileLinkModel, FileRecordModel)
            .join(FileRecordModel, FileRecordModel.id == FileLinkModel.file_id)
            .where(FileLinkModel.entity_type == "lease_termination_case", FileLinkModel.entity_id == row.id)
            .order_by(FileLinkModel.created_at)
        )
    ]
    return case, proposals, files

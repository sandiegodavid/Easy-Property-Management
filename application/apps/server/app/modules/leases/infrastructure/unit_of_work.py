"""SQLite transaction adapter for LEASE-001."""

from __future__ import annotations

from collections.abc import Callable, Collection
from datetime import UTC, datetime
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.inspections.application.ports import InspectionContextReader
from app.modules.leases.application.ports import (
    LeaseConflictError,
    LeaseFinanceActivityReader,
    LeaseTransaction,
    PortfolioLeaseOperations,
    TenantProfileAvailability,
)
from app.modules.leases.domain.models import (
    Lease,
    LeaseParticipant,
    LeaseRenewalOption,
    LeaseTerm,
    LeaseTerminationCase,
    LeaseTerminationProposal,
)
from app.modules.leases.infrastructure.sqlalchemy_models import (
    LeaseCommandOperationModel,
    LeaseModel,
    LeaseParticipantModel,
    LeaseRenewalOptionModel,
    LeaseTerminationCaseModel,
    LeaseTerminationProposalModel,
    LeaseTermModel,
)
from app.modules.portfolio.application.ports import PortfolioConflictError
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

Result = TypeVar("Result")


class SQLiteLeaseUnitOfWork:
    def command_operation(self, *, operation_id=None, idempotency_key=None):
        column, value = (
            (LeaseCommandOperationModel.id, operation_id)
            if operation_id is not None
            else (LeaseCommandOperationModel.idempotency_key, idempotency_key)
        )
        with self.engine.connect() as connection:
            return (
                connection.execute(
                    LeaseCommandOperationModel.__table__.select().where(column == value)
                )
                .mappings()
                .first()
            )

    def __init__(
        self,
        database,
        recorder: AuditRecorder,
        tenant_profiles: TenantProfileAvailability,
        portfolio_operations: PortfolioLeaseOperations,
        inspection_context_reader: InspectionContextReader,
        finance_activity_reader: LeaseFinanceActivityReader | None = None,
        *,
        file_link_reader=None,
    ) -> None:
        self.engine = create_sqlite_engine(database)
        self.recorder = recorder
        self.tenant_profiles = tenant_profiles
        self.portfolio_operations = portfolio_operations
        self.inspection_context_reader = inspection_context_reader
        self.finance_activity_reader = finance_activity_reader
        self._file_link_reader = file_link_reader

    def write(self, operation: Callable[[LeaseTransaction], Result]) -> Result:
        try:
            with immediate_transaction(self.engine) as connection:
                return operation(
                    _Transaction(
                        connection,
                        self.recorder,
                        self.tenant_profiles,
                        self.portfolio_operations,
                        self.inspection_context_reader,
                        self.finance_activity_reader,
                        file_link_reader=self._file_link_reader,
                    )
                )
        except OperationalError as error:
            if "locked" in str(error).casefold():
                raise LeaseConflictError(
                    "The lease changed concurrently; reload it and try again."
                ) from error
            raise
        except PortfolioConflictError as error:
            raise LeaseConflictError(str(error), current_status=error.current_status) from error

    def lease_view(self, lease_id: str):
        with Session(self.engine) as session:
            lease = session.get(LeaseModel, lease_id)
            if lease is None:
                return None
            return _view_record(session, lease, file_link_reader=self._file_link_reader)

    def lease_directory_page(self, *, status, property_id, resolve_cursor, limit):
        model = LeaseModel
        filters = []
        if status is not None:
            filters.append(model.status == status)
        if property_id is not None:
            filters.append(
                model.space_id.in_(self.portfolio_operations.space_ids_for_property(property_id))
            )
        with self.engine.begin() as connection:
            marker = connection.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(model.lease_revision), 0),
                    func.max(model.updated_at),
                ).select_from(model)
            ).one()
            cursor = resolve_cursor(str(tuple(marker)))
            total = connection.execute(
                select(func.count()).select_from(model).where(*filters)
            ).scalar_one()
            query = select(
                model.id,
                model.space_id,
                model.lease_kind,
                model.status,
                model.contract_starts_on,
                model.contract_ends_on,
                model.lease_revision,
            ).where(*filters)
            if cursor is not None:
                query = query.where(tuple_(model.contract_starts_on, model.id) > cursor)
            rows = (
                connection.execute(
                    query.order_by(model.contract_starts_on, model.id).limit(limit + 1)
                )
                .mappings()
                .all()
            )
            labels = self.portfolio_operations.rental_labels(
                connection, {row["space_id"] for row in rows[:limit]}
            )
            return [
                dict(row)
                | (
                    {
                        "property_id": labels[row["space_id"]].property_id,
                        "property_name": labels[row["space_id"]].property_name,
                        "rental_name": labels[row["space_id"]].rental_name,
                    }
                    if row["space_id"] in labels
                    else {}
                )
                for row in rows
            ], total

    def lease_views(
        self,
        *,
        status=None,
        property_id=None,
        space_id=None,
        tenant_party_id=None,
        contract_start_from=None,
        contract_start_to=None,
        renewal_due_on_or_before=None,
    ):
        with Session(self.engine) as session:
            query = select(LeaseModel)
            if status is not None:
                query = query.where(LeaseModel.status == status)
            if property_id is not None:
                query = query.where(
                    LeaseModel.space_id.in_(
                        self.portfolio_operations.space_ids_for_property(property_id)
                    )
                )
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
                query = query.where(
                    LeaseModel.id.in_(
                        select(LeaseRenewalOptionModel.lease_id).where(
                            LeaseRenewalOptionModel.status == "open",
                            or_(
                                LeaseRenewalOptionModel.notice_due_on <= renewal_due_on_or_before,
                                LeaseRenewalOptionModel.response_due_on <= renewal_due_on_or_before,
                            ),
                        )
                    )
                )
            leases = (
                session.execute(query.order_by(LeaseModel.contract_starts_on, LeaseModel.id))
                .scalars()
                .all()
            )
            return [
                _view_record(session, lease, file_link_reader=self._file_link_reader)
                for lease in leases
            ]

    def termination_case_view(self, case_id):
        with Session(self.engine) as session:
            item = session.get(LeaseTerminationCaseModel, case_id)
            return (
                None
                if item is None
                else _termination_record(session, item, file_link_reader=self._file_link_reader)
            )

    def termination_case_views(self, lease_id):
        with Session(self.engine) as session:
            items = session.execute(
                select(LeaseTerminationCaseModel)
                .where(LeaseTerminationCaseModel.lease_id == lease_id)
                .order_by(LeaseTerminationCaseModel.created_at)
            ).scalars()
            return [
                _termination_record(session, item, file_link_reader=self._file_link_reader)
                for item in items
            ]

    def file_link_target_exists(self, connection, entity_type: str, entity_id: str) -> bool:
        model = {
            "lease": LeaseModel,
            "lease_termination_case": LeaseTerminationCaseModel,
        }.get(entity_type)
        if model is None:
            return False
        return (
            connection.execute(select(model.id).where(model.id == entity_id).limit(1)).first()
            is not None
        )

    def space_time_zones(self, space_ids: Collection[str]) -> dict[str, str]:
        if not space_ids:
            return {}
        with self.engine.connect() as connection:
            return self.portfolio_operations.space_time_zones(connection, space_ids)


class _Transaction:
    def command_operation(self, idempotency_key):
        return (
            self.connection.execute(
                LeaseCommandOperationModel.__table__.select().where(
                    LeaseCommandOperationModel.idempotency_key == idempotency_key
                )
            )
            .mappings()
            .first()
        )

    def insert_command_operation(self, receipt):
        self.connection.execute(LeaseCommandOperationModel.__table__.insert().values(**receipt))

    def termination_case_snapshot(self, case_id):
        item = self.termination_case(case_id)
        if item is None:
            raise KeyError(case_id)
        return _termination_snapshot(self.connection, item, file_link_reader=self._file_link_reader)

    def __init__(
        self,
        connection: Any,
        recorder: AuditRecorder,
        tenant_profiles: TenantProfileAvailability,
        portfolio_operations: PortfolioLeaseOperations,
        inspection_context_reader,
        finance_activity_reader: LeaseFinanceActivityReader | None = None,
        *,
        file_link_reader=None,
    ) -> None:
        self.connection = connection
        self.recorder = recorder
        self.tenant_profiles = tenant_profiles
        self.portfolio_operations = portfolio_operations
        self.inspection_context_reader = inspection_context_reader
        self.finance_activity_reader = finance_activity_reader
        self._file_link_reader = file_link_reader

    def lease(self, lease_id):
        return _mapped(self.connection, LeaseModel, lease_id, Lease)

    def space(self, space_id):
        return self.portfolio_operations.space(self.connection, space_id)

    def property(self, property_id):
        return self.portfolio_operations.property(self.connection, property_id)

    def tenant_profile_active(self, party_id):
        return self.tenant_profiles.is_active(self.connection, party_id)

    def tenants_without_official_id(self, party_ids):
        return self.tenant_profiles.without_official_id(self.connection, party_ids)

    def terms(self, lease_id):
        return _mapped_many(
            self.connection,
            LeaseTermModel,
            LeaseTerm,
            LeaseTermModel.lease_id == lease_id,
            LeaseTermModel.effective_on,
        )

    def participants(self, lease_id):
        return _mapped_many(
            self.connection,
            LeaseParticipantModel,
            LeaseParticipant,
            LeaseParticipantModel.lease_id == lease_id,
            LeaseParticipantModel.created_at,
        )

    def renewal_options(self, lease_id):
        return _mapped_many(
            self.connection,
            LeaseRenewalOptionModel,
            LeaseRenewalOption,
            LeaseRenewalOptionModel.lease_id == lease_id,
            LeaseRenewalOptionModel.created_at,
        )

    def termination_cases(self, lease_id):
        return _mapped_many(
            self.connection,
            LeaseTerminationCaseModel,
            LeaseTerminationCase,
            LeaseTerminationCaseModel.lease_id == lease_id,
            LeaseTerminationCaseModel.created_at,
        )

    def termination_case(self, case_id):
        return _mapped(self.connection, LeaseTerminationCaseModel, case_id, LeaseTerminationCase)

    def termination_proposals(self, case_id):
        return _mapped_many(
            self.connection,
            LeaseTerminationProposalModel,
            LeaseTerminationProposal,
            LeaseTerminationProposalModel.termination_case_id == case_id,
            LeaseTerminationProposalModel.proposal_version,
        )

    def occupancy_periods(self, space_id):
        return self.portfolio_operations.occupancy_periods(self.connection, space_id)

    def finalized_inspection_report_kinds(self, lease_id):
        return self.inspection_context_reader.finalized_report_kinds(self.connection, lease_id)

    def has_active_financial_activity(self, lease_id):
        if self.finance_activity_reader is None:
            return False
        return self.finance_activity_reader.has_active_financial_activity(self.connection, lease_id)

    def insert_lease(self, item):
        self.connection.execute(LeaseModel.__table__.insert().values(**item.__dict__))

    def replace_lease(self, item):
        self.connection.execute(
            LeaseModel.__table__.update().where(LeaseModel.id == item.id).values(**item.__dict__)
        )

    def insert_term(self, item):
        self.connection.execute(LeaseTermModel.__table__.insert().values(**item.__dict__))

    def delete_terms(self, lease_id):
        self.connection.execute(
            LeaseTermModel.__table__.delete().where(LeaseTermModel.lease_id == lease_id)
        )

    def insert_participant(self, item):
        self.connection.execute(LeaseParticipantModel.__table__.insert().values(**item.__dict__))

    def replace_participant(self, item):
        self.connection.execute(
            LeaseParticipantModel.__table__.update()
            .where(LeaseParticipantModel.id == item.id)
            .values(**item.__dict__)
        )

    def delete_participant(self, participant_id):
        self.connection.execute(
            LeaseParticipantModel.__table__.delete().where(
                LeaseParticipantModel.id == participant_id
            )
        )

    def insert_renewal_option(self, item):
        self.connection.execute(LeaseRenewalOptionModel.__table__.insert().values(**item.__dict__))

    def replace_renewal_option(self, item):
        self.connection.execute(
            LeaseRenewalOptionModel.__table__.update()
            .where(LeaseRenewalOptionModel.id == item.id)
            .values(**item.__dict__)
        )

    def insert_termination_case(self, item):
        self.connection.execute(
            LeaseTerminationCaseModel.__table__.insert().values(**item.__dict__)
        )

    def replace_termination_case(self, item):
        self.connection.execute(
            LeaseTerminationCaseModel.__table__.update()
            .where(LeaseTerminationCaseModel.id == item.id)
            .values(**item.__dict__)
        )

    def insert_termination_proposal(self, item):
        self.connection.execute(
            LeaseTerminationProposalModel.__table__.insert().values(**item.__dict__)
        )

    def replace_termination_proposal(self, item):
        self.connection.execute(
            LeaseTerminationProposalModel.__table__.update()
            .where(LeaseTerminationProposalModel.id == item.id)
            .values(**item.__dict__)
        )

    def apply_source_timeline(self, changes):
        return self.portfolio_operations.apply_source_timeline(self.connection, changes)

    def lease_snapshot(self, lease_id):
        lease = self.lease(lease_id)
        if lease is None:
            raise KeyError(lease_id)
        return _lease_snapshot(self.connection, lease, file_link_reader=self._file_link_reader)

    def store_source_timeline_consumer_result(self, operation_id, result):
        self.portfolio_operations.store_source_timeline_consumer_result(
            self.connection,
            operation_id,
            result,
        )

    def record_change(self, **change):
        self.recorder.record_change(self.connection.connection.driver_connection, **change)


class SQLiteLeaseParticipationGuard:
    def __init__(self, space_time_zones=None) -> None:
        self._space_time_zones = space_time_zones

    def has_open_participation(self, connection, party_id, today=None):
        if today is not None:
            query = (
                select(LeaseParticipantModel.id)
                .join(LeaseModel, LeaseModel.id == LeaseParticipantModel.lease_id)
                .where(
                    LeaseParticipantModel.tenant_party_id == party_id,
                    LeaseModel.status == "executed",
                    (
                        LeaseParticipantModel.ends_on.is_(None)
                        | (LeaseParticipantModel.ends_on > today)
                    ),
                )
                .limit(1)
            )
            return connection.execute(query).first() is not None
        rows = connection.execute(
            select(LeaseParticipantModel.ends_on, LeaseModel.space_id)
            .join(LeaseModel, LeaseModel.id == LeaseParticipantModel.lease_id)
            .where(
                LeaseParticipantModel.tenant_party_id == party_id,
                LeaseModel.status == "executed",
            )
        ).all()
        if not rows:
            return False
        if any(ends_on is None for ends_on, _ in rows):
            return True
        zones = (
            self._space_time_zones(connection, {space_id for _, space_id in rows})
            if self._space_time_zones is not None
            else {}
        )
        return any(
            ends_on
            > datetime.now(ZoneInfo(zones[space_id]) if space_id in zones else UTC)
            .date()
            .isoformat()
            for ends_on, space_id in rows
        )


def _mapped(connection, model, record_id, domain):
    row = (
        connection.execute(model.__table__.select().where(model.id == record_id)).mappings().first()
    )
    return domain(**dict(row)) if row else None


def _mapped_many(connection, model, domain, condition, ordering):
    rows = (
        connection.execute(model.__table__.select().where(condition).order_by(ordering))
        .mappings()
        .all()
    )
    return [domain(**dict(row)) for row in rows]


def _view_record(session: Session, row: LeaseModel, *, file_link_reader=None):
    lease = Lease(**{name: getattr(row, name) for name in Lease.__dataclass_fields__})
    return _lease_snapshot(session.connection(), lease, file_link_reader=file_link_reader)


def _lease_snapshot(connection, lease: Lease, *, file_link_reader=None):
    terms = _mapped_many(
        connection,
        LeaseTermModel,
        LeaseTerm,
        LeaseTermModel.lease_id == lease.id,
        LeaseTermModel.effective_on,
    )
    participants = _mapped_many(
        connection,
        LeaseParticipantModel,
        LeaseParticipant,
        LeaseParticipantModel.lease_id == lease.id,
        LeaseParticipantModel.created_at,
    )
    renewals = _mapped_many(
        connection,
        LeaseRenewalOptionModel,
        LeaseRenewalOption,
        LeaseRenewalOptionModel.lease_id == lease.id,
        LeaseRenewalOptionModel.created_at,
    )
    files = (
        file_link_reader.active_entity_files_summary(connection, "lease", lease.id)
        if file_link_reader is not None
        else []
    )
    return lease, terms, participants, renewals, files


def _termination_record(session: Session, row: LeaseTerminationCaseModel, *, file_link_reader=None):
    case = LeaseTerminationCase(
        **{name: getattr(row, name) for name in LeaseTerminationCase.__dataclass_fields__}
    )
    parent = session.get(LeaseModel, case.lease_id)
    return (
        *_termination_snapshot(session.connection(), case, file_link_reader=file_link_reader),
        parent.lease_revision,
    )


def _termination_snapshot(connection, case: LeaseTerminationCase, *, file_link_reader=None):
    proposals = _mapped_many(
        connection,
        LeaseTerminationProposalModel,
        LeaseTerminationProposal,
        LeaseTerminationProposalModel.termination_case_id == case.id,
        LeaseTerminationProposalModel.proposal_version,
    )
    files = (
        file_link_reader.active_entity_files_summary(connection, "lease_termination_case", case.id)
        if file_link_reader is not None
        else []
    )
    return case, proposals, files

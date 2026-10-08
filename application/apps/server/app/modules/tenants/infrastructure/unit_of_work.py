"""SQLite transaction adapter for tenant profiles and creation."""

from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.parties.application.ports import PartyReadOperations, PartyTransactionOperations
from app.modules.tenants.application.ports import LeaseParticipationGuard, TenantTransaction
from app.modules.tenants.domain.models import TenantProfile
from app.modules.tenants.infrastructure.sqlalchemy_models import (
    TenantProfileModel,
    TenantCommandOperationModel,
)
from app.modules.tenants.application.commands import resolve_contact
from app.modules.tenants.application.errors import TenantConflictError
from app.modules.parties.application.errors import PartyConflictError
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

Result = TypeVar("Result")


class SQLiteTenantUnitOfWork:
    def __init__(
        self,
        database,
        recorder: AuditRecorder,
        lease_guard: LeaseParticipationGuard,
        party_operations: PartyTransactionOperations,
        party_reads: PartyReadOperations,
    ):
        self.engine = create_sqlite_engine(database)
        self.recorder = recorder
        self.lease_guard = lease_guard
        self.party_operations = party_operations
        self.party_reads = party_reads

    def write(self, operation: Callable[[TenantTransaction], Result]) -> Result:
        with immediate_transaction(self.engine) as connection:
            return operation(
                _Transaction(connection, self.recorder, self.lease_guard, self.party_operations)
            )

    def operation(self, *, operation_id=None, key=None):
        table = TenantCommandOperationModel.__table__
        predicate = (
            table.c.id == operation_id
            if operation_id is not None
            else table.c.idempotency_key == key
        )
        with self.engine.connect() as connection:
            row = connection.execute(table.select().where(predicate)).mappings().first()
            return dict(row) if row else None

    def get(self, party_id):
        with self.engine.connect() as connection:
            tx = _Transaction(connection, self.recorder, self.lease_guard, self.party_operations)
            party, profile = tx.party(party_id), tx.profile(party_id)
            return (party, profile, tx.methods(party_id)) if party and profile else None

    def list(self, *, archive_state, search):
        with Session(self.engine) as session:
            query = select(TenantProfileModel)
            if archive_state == "active":
                query = query.where(TenantProfileModel.archived_at.is_(None))
            elif archive_state == "archived":
                query = query.where(TenantProfileModel.archived_at.is_not(None))
            profiles = [_profile(row) for row in session.execute(query).scalars()]
            ids = [profile.party_id for profile in profiles]
            parties = self.party_reads.parties(ids)
            methods = self.party_reads.methods_for_parties(ids)
            records = [
                (parties[profile.party_id], profile, methods[profile.party_id])
                for profile in profiles
                if profile.party_id in parties
            ]
            if not search:
                return sorted(records, key=lambda item: (item[0].display_name, item[0].id))
            matched_ids = {
                item.id for item in self.party_reads.search(active_only=False, search=search)
            }
            return [item for item in records if item[0].id in matched_ids]


class _ProfileTransaction:
    def __init__(self, connection, recorder):
        self.connection, self.recorder = connection, recorder

    def tenant_operation_by_key(self, key):
        table = TenantCommandOperationModel.__table__
        row = (
            self.connection.execute(table.select().where(table.c.idempotency_key == key))
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def insert_tenant_operation(self, operation):
        self.connection.execute(TenantCommandOperationModel.__table__.insert().values(**operation))

    def profile(self, party_id):
        row = (
            self.connection.execute(
                TenantProfileModel.__table__.select().where(TenantProfileModel.party_id == party_id)
            )
            .mappings()
            .first()
        )
        return _profile_mapping(row) if row else None

    def replace_profile(self, item):
        self.connection.execute(
            TenantProfileModel.__table__.update()
            .where(TenantProfileModel.party_id == item.party_id)
            .values(**_profile_values(item))
        )

    def record_change(self, **change):
        self.recorder.record_change(self.connection.connection.driver_connection, **change)


class _Transaction(_ProfileTransaction):
    def __init__(self, connection: Any, recorder, lease_guard, party_operations):
        super().__init__(connection, recorder)
        self.lease_guard = lease_guard
        self.party_operations = party_operations

    def party(self, party_id):
        return self.party_operations.party(self.connection, party_id)

    def methods(self, party_id):
        return self.party_operations.methods(self.connection, party_id)

    def has_open_lease_participation(self, party_id, today):
        return self.lease_guard.has_open_participation(self.connection, party_id, today)

    def duplicate_party_ids(self, methods, limit):
        return self.party_operations.duplicate_party_ids(self.connection, methods, limit)

    def insert_party(self, item):
        self.party_operations.insert_party(self.connection, item)

    def insert_profile(self, item):
        self.connection.execute(
            TenantProfileModel.__table__.insert().values(**_profile_values(item))
        )

    def insert_method(self, item):
        self.party_operations.insert_method(self.connection, item)


def _profile(row):
    return TenantProfile(
        row.party_id,
        row.preferred_contact_method_id,
        bool(row.do_not_contact),
        row.notes,
        row.created_at,
        row.updated_at,
        row.archived_at,
        row.revision,
    )


def _profile_mapping(row):
    return TenantProfile(
        row["party_id"],
        row["preferred_contact_method_id"],
        bool(row["do_not_contact"]),
        row["notes"],
        row["created_at"],
        row["updated_at"],
        row["archived_at"],
        row["revision"],
    )


def _profile_values(item):
    return {**item.__dict__, "do_not_contact": int(item.do_not_contact)}


class SQLiteTenantRoleActivityGuard:
    def conflict(self, connection, party_id):
        row = connection.execute(
            TenantProfileModel.__table__.select().where(
                TenantProfileModel.party_id == party_id,
                TenantProfileModel.archived_at.is_(None),
            )
        ).first()
        return "An active tenant profile prevents party archival." if row else None


class SQLiteTenantRoleSummaryReader:
    def __init__(self, database) -> None:
        self.engine = create_sqlite_engine(database)

    def active_roles(self, party_id):
        with self.engine.connect() as connection:
            row = connection.execute(
                TenantProfileModel.__table__.select().where(
                    TenantProfileModel.party_id == party_id,
                    TenantProfileModel.archived_at.is_(None),
                )
            ).first()
        return {"tenant"} if row else set()


class SQLiteTenantProfileAvailability:
    def is_active(self, connection, party_id):
        row = (
            connection.execute(
                TenantProfileModel.__table__.select().where(TenantProfileModel.party_id == party_id)
            )
            .mappings()
            .first()
        )
        return row is not None and row["archived_at"] is None


class SQLiteTenantContactReferenceGuard:
    role = "tenant"

    def __init__(self, recorder):
        self.recorder = recorder

    def resolve_before_archive(
        self, connection, party_id, contact_method_id, resolutions, timestamp, correlation_id
    ):
        row = (
            connection.execute(
                TenantProfileModel.__table__.select().where(TenantProfileModel.party_id == party_id)
            )
            .mappings()
            .first()
        )
        if (
            row is None
            or row["archived_at"] is not None
            or row["preferred_contact_method_id"] != contact_method_id
        ):
            return ()
        matching = tuple(
            item
            for item in resolutions
            if item.role == self.role and item.role_record_id == party_id
        )
        if len(matching) != 1:
            from app.modules.parties.application.service import PartyValidationError

            raise PartyValidationError(
                "Clear or replace the preferred contact before archiving it."
            )
        try:
            resolve_contact(
                _ProfileTransaction(connection, self.recorder),
                matching[0],
                timestamp,
                correlation_id,
            )
        except TenantConflictError as error:
            raise PartyConflictError(
                str(error), code=error.code, current_tenant=error.current
            ) from error
        return matching

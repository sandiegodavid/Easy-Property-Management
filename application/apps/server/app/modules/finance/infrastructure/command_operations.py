"""Finance command persistence on a caller-owned SQLite transaction."""

from collections.abc import Iterable

from sqlalchemy import select

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.finance.application.commands import (
    FinanceCommandReceipt,
    FinanceScope,
    receipt_audit,
)
from app.modules.finance.domain.models import FinanceConflictError
from app.modules.finance.infrastructure.command_models import (
    FinanceCommandOperationModel,
    FinanceCommandRevisionModel,
)


class SQLiteFinanceCommandTransaction:
    def __init__(self, connection, recorder: AuditRecorder):
        self.connection = connection
        self.recorder = recorder

    def command_operation(self, key: str) -> FinanceCommandReceipt | None:
        row = (
            self.connection.execute(
                select(FinanceCommandOperationModel.__table__).where(
                    FinanceCommandOperationModel.idempotency_key == key
                )
            )
            .mappings()
            .first()
        )
        return (
            None if row is None else {key: value for key, value in row.items() if key != "sequence"}
        )

    def command_revision(self, scope: FinanceScope) -> int:
        value = self.connection.scalar(
            select(FinanceCommandRevisionModel.revision).where(
                FinanceCommandRevisionModel.scope_kind == scope.kind,
                FinanceCommandRevisionModel.scope_id == scope.id,
            )
        )
        return 0 if value is None else value

    def command_revisions(self, scopes: Iterable[FinanceScope]) -> dict[FinanceScope, int]:
        from sqlalchemy import tuple_

        identities = set(scopes)
        if len(identities) > 500:
            raise ValueError("At most 500 financial scopes may be projected.")
        projection = dict.fromkeys(identities, 0)
        if not identities:
            return projection
        rows = self.connection.execute(
            select(
                FinanceCommandRevisionModel.scope_kind,
                FinanceCommandRevisionModel.scope_id,
                FinanceCommandRevisionModel.revision,
            ).where(
                tuple_(
                    FinanceCommandRevisionModel.scope_kind, FinanceCommandRevisionModel.scope_id
                ).in_([(scope.kind, scope.id) for scope in identities])
            )
        )
        for kind, record_id, revision in rows:
            projection[FinanceScope(kind, record_id)] = revision
        return projection

    def store_command(self, receipt: FinanceCommandReceipt) -> None:
        scopes = FinanceCommandRevisionModel.__table__
        predicate = (
            scopes.c.scope_kind == receipt["scope_kind"],
            scopes.c.scope_id == receipt["scope_id"],
        )
        before = self.connection.execute(select(scopes).where(*predicate)).mappings().first()
        after = {
            "scope_kind": receipt["scope_kind"],
            "scope_id": receipt["scope_id"],
            "revision": receipt["result_revision"],
            "updated_at": receipt["created_at"]
            if before is None or receipt["effective"]
            else before["updated_at"],
        }
        if before is None:
            if receipt["expected_revision"] != 0:
                raise FinanceConflictError("Financial revision changed concurrently.")
            reference = {
                "rent_ledger": "lease_id",
                "expense": "expense_id",
                "deposit_account": "deposit_account_id",
            }[receipt["scope_kind"]]
            self.connection.execute(
                scopes.insert().values(**after, **{reference: receipt["scope_id"]})
            )
        else:
            result = self.connection.execute(
                scopes.update()
                .where(*predicate, scopes.c.revision == receipt["expected_revision"])
                .values(revision=after["revision"], updated_at=after["updated_at"])
            )
            if result.rowcount != 1:
                raise FinanceConflictError("Financial revision changed concurrently.")
        self.connection.execute(FinanceCommandOperationModel.__table__.insert().values(**receipt))
        common = {
            "correlation_id": receipt["correlation_id"],
            "reason": "financial_command_committed",
        }
        self.recorder.record_change(
            self.connection.connection.driver_connection,
            entity_type="finance_command_scope",
            entity_id=receipt["scope_id"],
            action="command_applied",
            before=None if before is None else {key: before[key] for key in after},
            after=after,
            **common,
        )
        self.recorder.record_change(
            self.connection.connection.driver_connection,
            entity_type="finance_command_operation",
            entity_id=receipt["id"],
            action="recorded",
            before=None,
            after=receipt_audit(receipt),
            **common,
        )

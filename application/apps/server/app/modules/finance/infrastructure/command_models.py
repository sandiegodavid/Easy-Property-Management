"""Current greenfield financial revision and immutable outcome storage."""

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase


def _uuid_check(column: str) -> str:
    return (
        f"length({column}) = 36 AND substr({column}, 9, 1) = '-' "
        f"AND substr({column}, 14, 1) = '-' AND substr({column}, 19, 1) = '-' "
        f"AND substr({column}, 24, 1) = '-' "
        f"AND length(replace({column}, '-', '')) = 32 "
        f"AND replace({column}, '-', '') NOT GLOB '*[^0-9a-f]*'"
    )


class FinanceCommandRevisionModel(LocalBase):
    __tablename__ = "finance_command_revisions"

    scope_kind: Mapped[str] = mapped_column(String, primary_key=True)
    scope_id: Mapped[str] = mapped_column(String, primary_key=True)
    lease_id: Mapped[str | None] = mapped_column(ForeignKey("leases.id"), unique=True)
    expense_id: Mapped[str | None] = mapped_column(ForeignKey("expenses.id"), unique=True)
    deposit_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("security_deposit_accounts.id"), unique=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("typeof(revision) = 'integer' AND revision >= 0"),
        CheckConstraint(_uuid_check("scope_id")),
        CheckConstraint(
            "(scope_kind = 'rent_ledger' AND lease_id IS NOT NULL AND scope_id = lease_id AND expense_id IS NULL AND deposit_account_id IS NULL) OR "
            "(scope_kind = 'expense' AND expense_id IS NOT NULL AND scope_id = expense_id AND lease_id IS NULL AND deposit_account_id IS NULL) OR "
            "(scope_kind = 'deposit_account' AND deposit_account_id IS NOT NULL AND scope_id = deposit_account_id AND lease_id IS NULL AND expense_id IS NULL)"
        ),
    )


class FinanceCommandOperationModel(LocalBase):
    __tablename__ = "finance_command_operations"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    scope_kind: Mapped[str] = mapped_column(String, nullable=False)
    scope_id: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[str] = mapped_column(String, nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    result_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    effective: Mapped[int] = mapped_column(Integer, nullable=False)
    request_json: Mapped[str] = mapped_column(String, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    response_json: Mapped[str] = mapped_column(String, nullable=False)
    response_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["scope_kind", "scope_id"],
            ["finance_command_revisions.scope_kind", "finance_command_revisions.scope_id"],
        ),
        CheckConstraint("typeof(expected_revision) = 'integer' AND expected_revision >= 0"),
        CheckConstraint("typeof(effective) = 'integer' AND effective IN (0, 1)"),
        CheckConstraint(
            "typeof(result_revision) = 'integer' AND result_revision = expected_revision + effective"
        ),
        *(
            CheckConstraint(_uuid_check(column))
            for column in ("id", "scope_id", "target_id", "idempotency_key", "correlation_id")
        ),
        *(
            CheckConstraint(f"length({column}) = 64 AND {column} NOT GLOB '*[^0-9a-f]*'")
            for column in ("request_fingerprint", "response_fingerprint")
        ),
        Index(
            "finance_commands_scope_revision",
            "scope_kind",
            "scope_id",
            "result_revision",
            unique=True,
            sqlite_where=text("effective = 1"),
        ),
        UniqueConstraint("scope_kind", "scope_id", "correlation_id"),
    )


FINANCE_COMMAND_TRIGGERS = {
    f"finance_command_operations_no_{action}": (
        f"CREATE TRIGGER finance_command_operations_no_{action} BEFORE {action.upper()} "
        "ON finance_command_operations BEGIN SELECT RAISE(ABORT, 'financial command receipts are append-only'); END"
    )
    for action in ("update", "delete")
}
FINANCE_COMMAND_TRIGGERS["finance_command_operations_no_replace"] = """
CREATE TRIGGER finance_command_operations_no_replace BEFORE INSERT ON finance_command_operations
WHEN EXISTS (
    SELECT 1 FROM finance_command_operations
    WHERE id = NEW.id OR idempotency_key = NEW.idempotency_key
       OR (scope_kind = NEW.scope_kind AND scope_id = NEW.scope_id AND correlation_id = NEW.correlation_id)
       OR (effective = 1 AND NEW.effective = 1
           AND scope_kind = NEW.scope_kind AND scope_id = NEW.scope_id
           AND result_revision = NEW.result_revision)
)
BEGIN SELECT RAISE(ABORT, 'financial command receipts are append-only'); END
"""

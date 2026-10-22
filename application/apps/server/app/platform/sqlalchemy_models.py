"""Shared SQLAlchemy declarative metadata for local product modules."""

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class LocalBase(DeclarativeBase):
    pass


class CommandOperationColumns:
    """Receipt storage mechanics; owners declare foreign keys and constraints.

    Sort orders preserve id, owner key, then receipt fields in existing DDL.
    """

    id: Mapped[str] = mapped_column(String, primary_key=True, sort_order=-1)
    action: Mapped[str] = mapped_column(String, nullable=False, sort_order=1)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True, sort_order=1)
    request_json: Mapped[str] = mapped_column(String, nullable=False, sort_order=1)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False, sort_order=1)
    expected_revision: Mapped[int] = mapped_column(nullable=False, sort_order=1)
    resulting_revision: Mapped[int] = mapped_column(nullable=False, sort_order=1)
    result_json: Mapped[str] = mapped_column(String, nullable=False, sort_order=1)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False, sort_order=1)
    created_at: Mapped[str] = mapped_column(String, nullable=False, sort_order=1)


def immutable_command_triggers(table_name: str, message: str) -> dict[str, str]:
    """Generate append-only SQLite DDL from trusted owner metadata constants."""
    triggers = {
        f"{table_name}_no_{action}": (
            f"CREATE TRIGGER {table_name}_no_{action} BEFORE {action.upper()} ON {table_name} "
            f"BEGIN SELECT RAISE(ABORT, '{message}'); END"
        )
        for action in ("update", "delete")
    }
    triggers[f"{table_name}_no_replace"] = (
        f"CREATE TRIGGER {table_name}_no_replace BEFORE INSERT ON {table_name}\n"
        f"WHEN EXISTS (SELECT 1 FROM {table_name} "
        "WHERE id = NEW.id OR idempotency_key = NEW.idempotency_key)\n"
        f"BEGIN SELECT RAISE(ABORT, '{message}'); END"
    )
    return triggers

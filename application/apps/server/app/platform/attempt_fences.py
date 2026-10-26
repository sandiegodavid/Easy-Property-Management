"""Durable closure of prepared command identities, independent of domain receipts.

A receipt insert and a closure serialize on SQLite's writer reservation. If a
request was already committed, its owner supplies the receipt instead of closing
it. Otherwise even a delayed copy of the request must roll back before commit.
"""

from sqlalchemy import CheckConstraint, String, select, UniqueConstraint, inspect, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase
from app.platform.command_validation import validate_receipt_schema, canonical_uuid, canonical_utc


FENCE_TABLE = "command_attempt_fences"


def fence_trigger(action):
    return (
        f"CREATE TRIGGER {FENCE_TABLE}_no_{action.lower()} "
        f"BEFORE {action} ON {FENCE_TABLE} "
        "BEGIN SELECT RAISE(ABORT, 'Command closures are immutable.'); END"
    )


FENCE_TRIGGERS = {
    f"{FENCE_TABLE}_no_{action.lower()}": fence_trigger(action) for action in ("UPDATE", "DELETE")
}
FENCE_TRIGGERS[f"{FENCE_TABLE}_no_replace"] = (
    f"CREATE TRIGGER {FENCE_TABLE}_no_replace BEFORE INSERT ON {FENCE_TABLE} "
    f"WHEN EXISTS (SELECT 1 FROM {FENCE_TABLE} WHERE id=NEW.id OR "
    "(receipt_table=NEW.receipt_table AND attempt_key=NEW.attempt_key)) "
    "BEGIN SELECT RAISE(ABORT, 'Command closures are immutable.'); END"
)


class ClosedCommandError(Exception):
    pass


class CommandAttemptFenceModel(LocalBase):
    __tablename__ = "command_attempt_fences"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    attempt_key: Mapped[str] = mapped_column(String, nullable=False)
    receipt_table: Mapped[str] = mapped_column(String, nullable=False)
    recovery_id: Mapped[str] = mapped_column(String, nullable=False)
    form_key: Mapped[str] = mapped_column(String, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("length(id) = 36 AND length(recovery_id) = 36"),
        CheckConstraint("length(attempt_key) = 36"),
        UniqueConstraint("receipt_table", "attempt_key"),
        CheckConstraint(
            "length(request_fingerprint) = 64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'"
        ),
    )


def receipt_fence_sql(table_name):
    return (
        f"CREATE TRIGGER epm_closed_{table_name} BEFORE INSERT ON {table_name} "
        "WHEN EXISTS (SELECT 1 FROM command_attempt_fences "
        f"WHERE receipt_table='{table_name}' AND attempt_key=NEW.idempotency_key) "
        "BEGIN SELECT RAISE(ABORT, 'EPM submission closed'); END"
    )


def receipt_tables(connection):
    present = set(inspect(connection).get_table_names())
    return [
        table
        for name, table in LocalBase.metadata.tables.items()
        if name in present and "idempotency_key" in table.c
    ]


def install_receipt_fences(connection):
    for table in receipt_tables(connection):
        connection.exec_driver_sql(receipt_fence_sql(table.name))


def raise_closed_attempt(context):
    if "EPM submission closed" in str(context.original_exception):
        raise ClosedCommandError(
            "This submission was closed. Continue from the saved form."
        ) from context.original_exception


def validate_attempt_fences(connection, namespaces):
    """Fences travel with backups and may never be silently omitted on restore."""
    table = CommandAttemptFenceModel.__table__
    validate_receipt_schema(connection, table, FENCE_TRIGGERS)
    expected = {
        f"epm_closed_{owner.name}": receipt_fence_sql(owner.name)
        for owner in receipt_tables(connection)
    }
    actual = dict(
        connection.execute(
            text(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' "
                "AND name LIKE 'epm_closed_%'"
            )
        ).all()
    )

    def normalize(sql):
        return "".join(sql.lower().split())

    if {key: normalize(value) for key, value in actual.items()} != {
        key: normalize(value) for key, value in expected.items()
    }:
        raise ValueError("Command closure admission guards differ.")
    for row in connection.execute(select(table)).mappings():
        canonical_uuid(row["id"])
        canonical_uuid(row["attempt_key"])
        canonical_uuid(row["recovery_id"])
        canonical_utc(row["created_at"])
        if namespaces.get(row["form_key"]) != row["receipt_table"]:
            raise ValueError("Command closure has the wrong owning namespace.")
        owner = LocalBase.metadata.tables[row["receipt_table"]]
        if connection.execute(
            select(owner.c.idempotency_key).where(owner.c.idempotency_key == row["attempt_key"])
        ).first():
            raise ValueError("A closed command also has a committed receipt.")

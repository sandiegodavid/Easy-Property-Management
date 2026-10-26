"""Technical schema and canonical-value checks for retained command receipts.

Owning modules supply their table metadata and retain all lifecycle policy.
"""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
from uuid import UUID

from sqlalchemy import CheckConstraint, Table, UniqueConstraint, inspect, text


def canonical_uuid(value: str) -> None:
    if str(UUID(value)) != value:
        raise ValueError("Noncanonical UUID.")


def canonical_utc(value: str) -> datetime:
    instant = datetime.fromisoformat(value)
    if (
        instant.tzinfo is None
        or instant.utcoffset() != UTC.utcoffset(instant)
        or instant.isoformat() != value
    ):
        raise ValueError("Noncanonical UTC timestamp.")
    return instant


def receipt_payload(
    row: Mapping,
    canonical: Callable[[object], str],
    fingerprint: Callable[[object], str],
) -> tuple[dict, dict]:
    """Read the canonical envelope shared by Party-backed profile commands."""
    request, result = json.loads(row["request_json"]), json.loads(row["result_json"])
    if (
        set(request) != {"action", "partyId", "expectedRevision", "payload"}
        or canonical(request) != row["request_json"]
        or fingerprint(request) != row["request_fingerprint"]
        or canonical(result) != row["result_json"]
    ):
        raise ValueError("Receipt payload differs.")
    return request, result


def profile_timestamps(state: Mapping, recorded_at: datetime) -> None:
    if (
        canonical_utc(state["createdAt"]) > canonical_utc(state["updatedAt"])
        or canonical_utc(state["updatedAt"]) > recorded_at
    ):
        raise ValueError("Profile timestamps differ.")
    if state["archivedAt"] is not None:
        canonical_utc(state["archivedAt"])


def _sql(value) -> str:
    return "".join(str(value).lower().split())


def validate_receipt_schema(connection, table: Table, triggers: Mapping, *, inspector=None) -> None:
    inspector = inspector if inspector is not None else inspect(connection)
    _columns(inspector, table)
    _constraints(inspector, table)
    _relations(inspector, table)
    actual = dict(
        connection.execute(
            text(
                "SELECT name, sql FROM sqlite_master WHERE type='trigger' "
                "AND name NOT LIKE 'epm_closed_%' AND tbl_name=:table"
            ),
            {"table": table.name},
        ).all()
    )
    if {name: _sql(sql) for name, sql in actual.items()} != {
        name: _sql(sql) for name, sql in triggers.items()
    }:
        raise ValueError("Receipt immutability differs.")


def _columns(inspector, table):
    columns = inspector.get_columns(table.name)
    if {c["name"] for c in columns} != set(table.c.keys()) or any(
        str(c["type"]) != str(table.c[c["name"]].type)
        or (not c["primary_key"] and c["nullable"] != table.c[c["name"]].nullable)
        for c in columns
    ):
        raise ValueError("Receipt columns differ.")
    if inspector.get_pk_constraint(table.name)["constrained_columns"] != ["id"]:
        raise ValueError("Receipt primary key differs.")


def _constraints(inspector, table):
    if {_sql(c["sqltext"]) for c in inspector.get_check_constraints(table.name)} != {
        _sql(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)
    }:
        raise ValueError("Receipt checks differ.")
    if {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table.name)} != {
        tuple(col.name for col in c.columns)
        for c in table.constraints
        if isinstance(c, UniqueConstraint)
    }:
        raise ValueError("Receipt uniqueness differs.")


def _relations(inspector, table):
    if {
        (i["name"], tuple(i["column_names"]), bool(i["unique"]))
        for i in inspector.get_indexes(table.name)
    } != {(i.name, tuple(c.name for c in i.columns), bool(i.unique)) for i in table.indexes}:
        raise ValueError("Receipt indexes differ.")
    if {
        (tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]))
        for f in inspector.get_foreign_keys(table.name)
    } != {
        ((fk.parent.name,), fk.column.table.name, (fk.column.name,)) for fk in table.foreign_keys
    }:
        raise ValueError("Receipt references differ.")

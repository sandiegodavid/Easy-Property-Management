"""Shared receipt mechanics: real SQLite schema faults and canonical payloads.

Owner suites retain lifecycle, replay, rollback and encrypted-restore coverage.
"""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
)
from sqlalchemy.exc import IntegrityError

from app.platform.command_validation import (
    canonical_utc,
    canonical_uuid,
    profile_timestamps,
    receipt_payload,
    validate_receipt_schema,
)
from app.platform.sqlalchemy_models import immutable_command_triggers

TRIGGER = (
    "CREATE TRIGGER receipts_no_update BEFORE UPDATE ON receipts "
    "BEGIN SELECT RAISE(ABORT, 'immutable'); END"
)


def receipt_table(defect=None):
    metadata = MetaData()
    Table("owners", metadata, Column("id", String, primary_key=True))
    table = Table(
        "receipts",
        metadata,
        Column(
            "id",
            Integer if defect == "type" else String,
            primary_key=defect != "primary_key",
            nullable=False,
        ),
        Column(
            "owner_id",
            String,
            *(() if defect == "foreign_key" else (ForeignKey("owners.id"),)),
            primary_key=defect == "primary_key",
            nullable=False,
        ),
        Column("idempotency_key", String, unique=defect != "unique", nullable=defect == "nullable"),
    )
    if defect == "columns":
        table.append_column(Column("unexpected", String))
    if defect != "checks":
        table.append_constraint(CheckConstraint("length(idempotency_key) > 0"))
    if defect != "indexes":
        Index("receipts_owner", table.c.owner_id)
    return table


@pytest.mark.parametrize(
    "defect,reason",
    [
        (None, None),
        ("columns", "columns"),
        ("type", "columns"),
        ("nullable", "columns"),
        ("primary_key", "primary key"),
        ("checks", "checks"),
        ("unique", "uniqueness"),
        ("indexes", "indexes"),
        ("foreign_key", "references"),
        ("trigger", "immutability"),
    ],
)
def test_exact_receipt_schema_rejects_sqlite_faults(defect, reason):
    engine = create_engine("sqlite://")
    try:
        actual, expected = receipt_table(defect), receipt_table()
        actual.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER receipts_no_update BEFORE UPDATE ON receipts BEGIN SELECT 1; END"
                if defect == "trigger"
                else TRIGGER
            )
            if reason is None:
                validate_receipt_schema(connection, expected, {"receipts_no_update": TRIGGER})
            else:
                with pytest.raises(ValueError, match=f"Receipt {reason} differ"):
                    validate_receipt_schema(connection, expected, {"receipts_no_update": TRIGGER})
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE receipts SET idempotency_key='changed' WHERE id='original'",
        "DELETE FROM receipts WHERE id='original'",
        "INSERT OR REPLACE INTO receipts VALUES ('original','owner','changed')",
        "INSERT OR REPLACE INTO receipts VALUES ('different','owner','key')",
    ],
)
def test_generated_triggers_prevent_updates_deletes_and_either_replace_collision(statement):
    table = receipt_table()
    engine = create_engine("sqlite://")
    try:
        table.metadata.create_all(engine)
        with engine.begin() as connection:
            for sql in immutable_command_triggers("receipts", "immutable").values():
                connection.exec_driver_sql(sql)
            connection.execute(
                table.insert().values(id="original", owner_id="owner", idempotency_key="key")
            )
            with pytest.raises(IntegrityError, match="immutable"):
                connection.exec_driver_sql(statement)
            assert connection.execute(table.select()).all() == [("original", "owner", "key")]
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "value", ["2026-01-01T12:00:00", "2026-01-01T12:00:00+01:00", "2026-01-01T12:00:00Z"]
)
def test_noncanonical_timestamp_is_rejected(value):
    with pytest.raises(ValueError, match="Noncanonical UTC"):
        canonical_utc(value)


def test_canonical_identity_and_profile_timestamps():
    key = str(UUID("abcdef01-0000-4000-8000-000000000001"))
    canonical_uuid(key)
    with pytest.raises(ValueError, match="Noncanonical UUID"):
        canonical_uuid(key.upper())
    now = datetime(2026, 1, 2, tzinfo=UTC)
    created = "2026-01-01T00:00:00+00:00"
    profile = {"createdAt": created, "updatedAt": now.isoformat(), "archivedAt": None}
    profile_timestamps(profile, now)
    with pytest.raises(ValueError, match="Profile timestamps differ"):
        profile_timestamps({**profile, "createdAt": "2026-01-03T00:00:00+00:00"}, now)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@pytest.mark.parametrize("defect", [None, "request", "result", "fingerprint", "fields"])
def test_receipt_payload_preserves_canonical_request_result_and_fingerprint(defect):
    request = {"action": "patch", "partyId": "owner", "expectedRevision": 1, "payload": {}}
    result = {"revision": 1}
    if defect == "fields":
        request["extra"] = True
    row = {
        "request_json": canonical(request),
        "result_json": canonical(result),
        "request_fingerprint": fingerprint(request),
    }
    if defect in {"request", "result"}:
        row[f"{defect}_json"] += " "
    elif defect == "fingerprint":
        row["request_fingerprint"] = "0" * 64
    if defect is None:
        assert receipt_payload(row, canonical, fingerprint) == (request, result)
    else:
        with pytest.raises(ValueError, match="Receipt payload differs"):
            receipt_payload(row, canonical, fingerprint)

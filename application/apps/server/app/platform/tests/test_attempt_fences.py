"""A closed command identity is scoped to its owner and enforced inside the write."""

from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, Column, String, select

from app.platform.attempt_fences import (
    CommandAttemptFenceModel,
    ClosedCommandError,
    receipt_fence_sql,
)
from app.platform.sqlite_engine import create_sqlite_engine


def test_namespaced_closure_allows_other_owners_and_rolls_back_prior_writes(tmp_path):
    engine = create_sqlite_engine(tmp_path / "fences.sqlite")
    metadata = MetaData()
    first, other = [
        Table(
            name,
            metadata,
            Column("id", String, primary_key=True),
            Column("idempotency_key", String),
            Column("payload", String),
        )
        for name in ("first_operations", "other_operations")
    ]
    key = str(uuid4())
    try:
        with engine.begin() as connection:
            CommandAttemptFenceModel.__table__.create(connection)
            metadata.create_all(connection)
            for table in (first, other):
                connection.exec_driver_sql(receipt_fence_sql(table.name))
            connection.execute(
                CommandAttemptFenceModel.__table__.insert().values(
                    id=str(uuid4()),
                    attempt_key=key,
                    receipt_table=first.name,
                    recovery_id=str(uuid4()),
                    form_key="test.first",
                    request_fingerprint="a" * 64,
                    created_at="2026-10-26T00:00:00+00:00",
                )
            )
            connection.execute(
                other.insert().values(id="other", idempotency_key=key, payload="original")
            )
        with pytest.raises(ClosedCommandError):
            with engine.begin() as connection:
                connection.execute(other.update().values(payload="must roll back"))
                connection.execute(
                    first.insert().values(id="first", idempotency_key=key, payload="changed")
                )
        with engine.connect() as connection:
            assert connection.execute(select(other.c.payload)).scalar_one() == "original"
            assert connection.execute(select(first)).all() == []
    finally:
        engine.dispose()

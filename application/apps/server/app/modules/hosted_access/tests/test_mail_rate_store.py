"""Admission matrix: rolling limits, rotation, retries, rollback, schema and restore.

No provider/network calls; independent SQLite writers exercise atomic admission.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.modules.hosted_access.application.identity_setup import DAY, HOUR, MINUTE
from app.modules.hosted_access.infrastructure.mail_rate_store import (
    RETENTION_MS,
    SQLiteMailRateStore,
)
from app.platform.hosted_contracts.operations import OperationReference, SemanticConflict
from app.platform.hosted_schema import initialize_store, validate_schema
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine

APPLICATION = Path(__file__).resolve().parents[6]
DEPLOYMENT = "00000000-0000-4000-8000-000000000001"
KEY = b"a" * 32
NEXT_KEY = b"b" * 32


def operation(**changes):
    return OperationReference.model_validate(
        dict(
            deployment_id=DEPLOYMENT,
            scope={"kind": "deployment"},
            kind="send_email",
            operation_id=str(uuid4()),
            idempotency_key=str(uuid4()),
            request_hash="a" * 64,
        )
        | changes
    )


@pytest.fixture
def admission(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "admin.sqlite"
    initialize_store(HostedStore.ADMIN, path, application_directory=APPLICATION)
    engine = create_sqlite_engine(path)
    tick = [2 * DAY]
    store = SQLiteMailRateStore(engine, DEPLOYMENT, keys=(KEY,), clock=lambda: tick[0])
    yield store, tick, path
    engine.dispose()


def send(store, destination="User@example.invalid", network="192.0.2.1", op=None):
    return store.reserve_email(destination, network, op or operation())


def test_resource_empty_readonly_reinit_and_missing_schema(admission, tmp_path):
    store, _, path = admission
    with store.engine.connect() as conn:
        assert conn.scalar(select(text("count(*)")).select_from(store.table)) == 0
        assert validate_schema(conn, HostedStore.ADMIN, application_directory=APPLICATION)
    before = path.read_bytes()
    initialize_store(HostedStore.ADMIN, path, application_directory=APPLICATION)
    assert path.read_bytes() == before
    missing = create_sqlite_engine(tmp_path / "missing.sqlite")
    with pytest.raises(Exception, match="identity_mail_reservations"):
        SQLiteMailRateStore(missing, DEPLOYMENT, keys=(KEY,))
    missing.dispose()


def test_resend_and_destination_window_boundaries(admission):
    store, tick, _ = admission
    start = tick[0]
    assert send(store) == "reserved"
    tick[0] += MINUTE - 1
    assert send(store) == "throttled"
    tick[0] += 1
    for _ in range(4):
        assert send(store) == "reserved"
        tick[0] += MINUTE
    assert send(store) == "throttled"
    tick[0] = start + HOUR
    assert send(store) == "reserved"


def test_network_and_deployment_rolling_limits(admission):
    store, tick, _ = admission
    start = tick[0]
    for index in range(20):
        assert send(store, f"user{index}@example.invalid") == "reserved"
    assert send(store, "new@example.invalid") == "throttled"
    tick[0] += HOUR
    assert send(store, "new@example.invalid") == "reserved"
    store.daily_limit = 21
    assert send(store, "other@example.invalid", "other") == "throttled"
    tick[0] = start + DAY
    assert send(store, "other@example.invalid", "other") == "reserved"


@pytest.mark.parametrize("limit", (None, 9))
def test_deployment_ceiling_blocks_next_send_and_recovers_after_day(admission, limit):
    store, tick, _ = admission
    if limit is not None:
        store.daily_limit = limit
    for index in range(100 if limit is None else limit):
        assert send(store, f"user{index}@example.invalid", str(index)) == "reserved"
    assert send(store, "other@example.invalid", "other") == "throttled"
    tick[0] += DAY
    assert send(store, "other@example.invalid", "other") == "reserved"


def test_retries_changed_intent_and_scope_are_immutable(admission):
    store, _, _ = admission
    op = operation()
    assert send(store, op=op) == "reserved"
    assert send(store, op=op) == "unknown"
    retry = op.model_copy(update={"operation_id": str(uuid4())})
    assert send(store, network="changed", op=retry) == "unknown"
    for change in (
        {"request_hash": "b" * 64},
        {"kind": "other"},
        {"idempotency_key": "other"},
        {"scope": {"kind": "workspace", "workspace_id": DEPLOYMENT, "operator_id": DEPLOYMENT}},
    ):
        changed = operation(**(op.model_dump() | change))
        with pytest.raises(SemanticConflict):
            send(store, op=changed)
    with pytest.raises(SemanticConflict):
        send(
            store, "changed@example.invalid", op=retry.model_copy(update={"request_hash": "b" * 64})
        )
    with pytest.raises(ValueError, match="deployment"):
        send(store, op=operation(deployment_id=str(uuid4())))


def test_rotation_restart_and_hash_port_coordination(admission):
    store, tick, path = admission
    op = operation()
    assert send(store, op=op) == "reserved"
    engine = create_sqlite_engine(path)
    rotated = SQLiteMailRateStore(engine, DEPLOYMENT, keys=(NEXT_KEY, KEY), clock=lambda: tick[0])
    assert send(rotated, op=op) == "unknown"
    assert send(rotated) == "throttled"
    tick[0] += MINUTE
    for _ in range(4):
        assert send(rotated) == "reserved"
        tick[0] += MINUTE
    assert send(rotated) == "throttled"
    with pytest.raises(ValueError, match="Rotation"):
        rotated.reserve("a" * 64, "b" * 64, operation())
    destinations = rotated._hashes("destination", "mail:User@example.invalid")
    networks = rotated._hashes("network", "192.0.2.1")
    rotated.alias_provider = lambda d, n: (destinations, networks)
    assert rotated.reserve(destinations[0], networks[0], operation()) == "throttled"
    engine.dispose()


def test_atomic_independent_writers(admission):
    store, tick, path = admission

    def reserve(index):
        engine = create_sqlite_engine(path)
        try:
            worker = SQLiteMailRateStore(engine, DEPLOYMENT, keys=(KEY,), clock=lambda: tick[0])
            return send(worker, f"user{index}@example.invalid")
        finally:
            engine.dispose()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(28)))
    assert results.count("reserved") == 20
    assert results.count("throttled") == 8


def test_cleanup_bounded_redaction_replay_and_backup_restore(admission):
    store, tick, path = admission
    store.daily_limit = 200
    ops = [operation() for _ in range(105)]
    for index, op in enumerate(ops):
        assert send(store, f"u{index}@example.invalid", str(index), op) == "reserved"
    tick[0] += RETENTION_MS - 1
    assert store.cleanup() == 0
    tick[0] += 1
    assert store.cleanup() == 100
    assert store.cleanup() == 5
    assert store.cleanup() == 0
    assert send(store, "u0@example.invalid", "0", ops[0]) == "unknown"
    with pytest.raises(SemanticConflict):
        send(store, op=ops[0].model_copy(update={"request_hash": "b" * 64}))
    with store.engine.connect() as conn:
        assert all(
            row == (None, None)
            for row in conn.execute(
                select(store.table.c.destination_hash, store.table.c.network_hash)
            )
        )
    restored = path.with_name("restored.sqlite")
    shutil.copyfile(path, restored)
    engine = create_sqlite_engine(restored)
    backup = SQLiteMailRateStore(engine, DEPLOYMENT, keys=(KEY,), clock=lambda: tick[0])
    assert send(backup, "u0@example.invalid", "0", ops[0]) == "unknown"
    engine.dispose()


def test_schema_guards_and_rollback(admission):
    store, _, path = admission
    assert send(store) == "reserved"
    with store.engine.connect() as conn:
        row = dict(conn.execute(select(store.table)).mappings().one())
    for statement in (
        "UPDATE identity_mail_reservations SET request_hash='" + "b" * 64 + "'",
        "UPDATE identity_mail_reservations SET destination_hash='" + "b" * 64 + "'",
        "DELETE FROM identity_mail_reservations",
    ):
        with pytest.raises(IntegrityError), store.engine.begin() as conn:
            conn.exec_driver_sql(statement)
    with pytest.raises(IntegrityError), store.engine.begin() as conn:
        conn.execute(store.table.insert().prefix_with("OR REPLACE").values(**row))
    with pytest.raises(IntegrityError), store.engine.begin() as conn:
        conn.execute(
            store.table.insert().values(
                **(
                    row
                    | {
                        "operation_id": str(uuid4()),
                        "idempotency_key": "new",
                        "redact_after": 1,
                    }
                )
            )
        )
    with store.engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TRIGGER reject_mail BEFORE INSERT ON identity_mail_reservations "
            "BEGIN SELECT RAISE(ABORT, 'test rollback'); END"
        )
    assert send(store, "other@example.invalid", "other") == "unknown"
    with store.engine.connect() as conn:
        assert conn.scalar(select(text("count(*)")).select_from(store.table)) == 1
    assert b"User@example.invalid" not in path.read_bytes()
    assert b"192.0.2.1" not in path.read_bytes()


def test_hash_port_and_retired_key_retry(admission):
    store, tick, path = admission
    op = operation()
    assert store.reserve("a" * 64, "b" * 64, op) == "reserved"
    assert store.reserve("a" * 64, "b" * 64, op) == "unknown"
    assert store.reserve("a" * 64, "b" * 64, operation()) == "throttled"
    with pytest.raises(ValueError):
        store.reserve("raw@example.invalid", "b" * 64, operation())
    tick[0] += DAY
    engine = create_sqlite_engine(path)
    retired = SQLiteMailRateStore(engine, DEPLOYMENT, keys=(NEXT_KEY,), clock=lambda: tick[0])
    assert retired.reserve("c" * 64, "d" * 64, op) == "unknown"
    engine.dispose()


def test_rotated_network_budget(admission):
    store, tick, path = admission
    for index in range(20):
        assert send(store, f"user{index}@example.invalid") == "reserved"
    engine = create_sqlite_engine(path)
    rotated = SQLiteMailRateStore(engine, DEPLOYMENT, keys=(NEXT_KEY, KEY), clock=lambda: tick[0])
    assert send(rotated, "new@example.invalid") == "throttled"
    assert send(rotated, "new@example.invalid", "other") == "reserved"
    engine.dispose()


def test_concurrent_same_operation_grants_once(admission):
    store, _, _ = admission
    op = operation()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: send(store, op=op), range(12)))
    assert results.count("reserved") == 1
    assert results.count("unknown") == 11

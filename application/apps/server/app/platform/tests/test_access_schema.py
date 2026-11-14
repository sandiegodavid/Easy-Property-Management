"""Resource-owned H03 baseline: constraints, evidence, rollback and restore."""

from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.modules.hosted_access.application.identity_evidence import IdentityBinding, SessionReceipt
from app.platform.hosted_schema import HostedSchemaError, create_schema, validate_schema
from app.platform.schema_resources import HostedStore

APPLICATION = Path(__file__).resolve().parents[5]
STORE = HostedStore.HOSTED_ACCESS
FIRST = "00000000-0000-4000-8000-000000000001"
SECOND = "00000000-0000-4000-8000-000000000002"
TABLES = {
    "access_meta",
    "access_sessions",
    "access_receipts",
    "access_audit",
    "usage_state",
    "usage_reservations",
    "draft_leases",
    "source_login_attempts",
    "source_recent_challenges",
}


@pytest.fixture
def connection():
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        create_schema(conn, STORE, application_directory=APPLICATION)
        yield conn
        conn.rollback()
    engine.dispose()


def insert(conn, table, values):
    names = ",".join(values)
    placeholders = ",".join(":" + name for name in values)
    conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({placeholders})"), values)


def session(**changes):
    values = dict(
        session_hash="a" * 64,
        csrf_hash="b" * 64,
        actor_subject="provider-subject",
        handoff_id=FIRST,
        generation=1,
        access_epoch=1,
        issued_at=1000,
        expires_at=2000,
        managed_valid_until=3000,
        last_seen_at=1000,
        revoked_at=None,
        session_id=FIRST,
        managed_session_id=FIRST,
        managed_observation_revision=1,
        revocation_valid_until=2000,
        remembered_until=4000,
        display_label="Browser",
        renewed_from_session_id=None,
    )
    return values | changes


def attempt(**changes):
    return (
        dict(
            attempt_id=FIRST,
            browser_challenge_hash="c" * 64,
            access_epoch=1,
            resource_generation=1,
            return_path="/workspace",
            remembered=1,
            state="pending",
            handoff_id=None,
            continuation_id=None,
            binding_assertion_hash=None,
            binding_expires_at=None,
            created_at=1000,
            expires_at=2000,
            revision=1,
        )
        | changes
    )


def receipt():
    return dict(
        operation_id=FIRST,
        request_hash="d" * 64,
        kind="issue_session",
        access_epoch=1,
        source_revision=1,
        result_json=SessionReceipt(
            kind="issue_session",
            operation_id=FIRST,
            request_hash="d" * 64,
            binding=IdentityBinding(
                deployment_id=FIRST,
                scope={"operator_id": FIRST, "workspace_id": FIRST},
                binding_id=FIRST,
                resource_generation=1,
                access_epoch=1,
                assignment_revision=1,
                registered_origin_id=FIRST,
                target_origin="https://operator.example.test",
                issuer="provider",
                subject="provider-subject",
            ),
            session_id=FIRST,
            handoff_id=FIRST,
            source_revision=1,
            session_generation=1,
            recorded_at=1000,
            expires_at=2000,
            renewed_from_session_id=None,
        ).model_dump_json(),
        recorded_at=1000,
    )


def test_empty_complete_schema_and_indexes(connection):
    inspector = inspect(connection)
    assert set(inspector.get_table_names()) == TABLES | {"alembic_version"}
    for table in TABLES:
        assert connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one() == 0
    assert validate_schema(connection, STORE, application_directory=APPLICATION)
    assert not inspector.get_foreign_keys("draft_leases")
    assert not inspector.get_foreign_keys("usage_reservations")
    indexes = {tuple(i["column_names"]) for i in inspector.get_indexes("access_sessions")}
    assert {
        ("generation", "revoked_at", "expires_at"),
        ("expires_at",),
        ("managed_session_id",),
    } <= indexes
    assert inspector.get_foreign_keys("access_audit")[0]["referred_table"] == "access_receipts"


@pytest.mark.parametrize(
    "changes",
    [
        {"expires_at": 1000},
        {"expires_at": 3001},
        {"remembered_until": 2592001001},
        {"revocation_valid_until": 3001},
        {"revocation_valid_until": 1000},
        {"last_seen_at": 999},
        {"revoked_at": 999},
        {"generation": 0},
        {"session_hash": "raw-cookie"},
        {"renewed_from_session_id": FIRST},
        {"display_label": "<script>"},
        {"display_label": "bad\nlabel"},
    ],
)
def test_invalid_session(connection, changes):
    with pytest.raises(IntegrityError):
        insert(connection, "access_sessions", session(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"expires_at": 901001},
        {"expires_at": 1000},
        {"remembered": 2},
        {"state": "issued"},
        {"state": "completed"},
        {"binding_expires_at": 1500},
        {"binding_assertion_hash": "a" * 64, "binding_expires_at": 1500},
        {"return_path": "https://external.test"},
        {"return_path": "//external.test"},
    ],
)
def test_invalid_attempt(connection, changes):
    with pytest.raises(IntegrityError):
        insert(connection, "source_login_attempts", attempt(**changes))


def test_replacement_fk_unique_and_restrict(connection):
    insert(connection, "access_sessions", session())
    insert(
        connection,
        "access_sessions",
        session(
            session_hash="c" * 64,
            session_id=SECOND,
            handoff_id=SECOND,
            renewed_from_session_id=FIRST,
        ),
    )
    with pytest.raises(IntegrityError):
        connection.exec_driver_sql("DELETE FROM access_sessions WHERE session_id=?", (FIRST,))
    with pytest.raises(IntegrityError):
        insert(connection, "access_sessions", session(session_hash="e" * 64))
    connection.exec_driver_sql("DELETE FROM access_sessions WHERE session_id=?", (SECOND,))
    connection.exec_driver_sql("DELETE FROM access_sessions WHERE session_id=?", (FIRST,))


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE access_receipts SET result_json='{}'",
        "UPDATE access_receipts SET request_hash='" + "e" * 64 + "'",
        "DELETE FROM access_receipts",
        "INSERT OR REPLACE INTO access_receipts SELECT * FROM access_receipts",
    ],
)
def test_original_receipt_is_retained(connection, sql):
    insert(connection, "access_receipts", receipt())
    with pytest.raises(IntegrityError):
        connection.exec_driver_sql(sql)
    assert (
        connection.exec_driver_sql("SELECT result_json FROM access_receipts").scalar_one()
        == (receipt()["result_json"])
    )


def test_atomic_rollback_and_backup(connection):
    connection.exec_driver_sql("SAVEPOINT issuance")
    insert(connection, "source_login_attempts", attempt())
    insert(connection, "access_sessions", session())
    insert(connection, "access_receipts", receipt())
    connection.exec_driver_sql("ROLLBACK TO issuance")
    for table in ("access_sessions", "source_login_attempts", "access_receipts"):
        assert connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one() == 0
    connection.commit()
    raw = connection.connection.driver_connection
    restored = sqlite3.connect(":memory:")
    try:
        raw.backup(restored)
        assert restored.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert restored.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "access_0001_initial",
        )
    finally:
        restored.close()


def test_schema_drift_rejected(connection):
    connection.exec_driver_sql("DROP INDEX draft_leases_session")
    with pytest.raises(HostedSchemaError):
        validate_schema(connection, STORE, application_directory=APPLICATION)


def metadata(**changes):
    return (
        dict(
            id=1,
            deployment_id=FIRST,
            operator_id=FIRST,
            workspace_id=FIRST,
            binding_id=FIRST,
            resource_generation=1,
            issuer="provider",
            subject=None,
            email_key="provider:user@example.test",
            effective_access="disabled",
            access_epoch=1,
            session_generation=1,
            not_before=1000,
            effective_policy_id=FIRST,
            usable_bytes=50000000,
            policy_revision=1,
            maintenance_operation_id=None,
            restore_generation=1,
            revision=1,
        )
        | changes
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"effective_access": "enabled", "subject": "subject"},
        {"subject": "subject"},
        {"id": 2},
        {"usable_bytes": 0},
        {"access_epoch": 0},
        {"resource_generation": 0},
        {"binding_id": None},
    ],
)
def test_invalid_initial_metadata(connection, changes):
    with pytest.raises(IntegrityError):
        insert(connection, "access_meta", metadata(**changes))


def test_disabled_metadata_requires_explicit_valid_enable(connection):
    insert(connection, "access_meta", metadata())
    with pytest.raises(IntegrityError):
        connection.exec_driver_sql("UPDATE access_meta SET effective_access='enabled'")
    connection.exec_driver_sql(
        "UPDATE access_meta SET effective_access='enabled',subject='verified',revision=2"
    )
    assert connection.exec_driver_sql("SELECT access_epoch FROM access_meta").scalar_one() == 1


def test_usage_and_draft_constraints(connection):
    usage = dict(
        id=1,
        business_revision="business:1",
        committed_db_bytes=0,
        retained_file_bytes=0,
        observed_at=1000,
        measurement_version="v1",
        revision=1,
    )
    insert(connection, "usage_state", usage)
    with pytest.raises(IntegrityError):
        connection.exec_driver_sql("UPDATE usage_state SET committed_db_bytes=-1")
    with pytest.raises(IntegrityError):
        insert(connection, "usage_state", usage | {"id": 2})
    reservation = dict(
        reservation_id=FIRST,
        operation_id=FIRST,
        request_hash="a" * 64,
        reserved_bytes=1,
        purpose="upload",
        source_epoch=1,
        state="unknown",
        created_at=1000,
        updated_at=1000,
        result_revision=None,
    )
    insert(connection, "usage_reservations", reservation)
    with pytest.raises(IntegrityError):
        insert(connection, "usage_reservations", reservation | {"reservation_id": SECOND})
    for assignment in ("reserved_bytes=0", "state='expired'", "updated_at=999"):
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(f"UPDATE usage_reservations SET {assignment}")
    insert(connection, "access_sessions", session())
    lease = dict(
        record_id=FIRST,
        session_hash="a" * 64,
        lease_token_hash="e" * 64,
        access_epoch=1,
        expires_at=2000,
        renewed_at=1000,
    )
    insert(connection, "draft_leases", lease)
    connection.exec_driver_sql("DELETE FROM access_sessions")
    assert connection.exec_driver_sql("SELECT count(*) FROM draft_leases").scalar_one() == 1
    with pytest.raises(IntegrityError):
        insert(connection, "draft_leases", lease | {"record_id": SECOND})
    with pytest.raises(IntegrityError):
        connection.exec_driver_sql("UPDATE draft_leases SET expires_at=renewed_at")


def test_receipt_json_and_audit_closure(connection):
    for changes in (
        {"result_json": "[]"},
        {"result_json": '{"x":"' + "x" * 16384 + '"}'},
        {"kind": "unknown"},
        {"source_revision": 0},
    ):
        with pytest.raises(IntegrityError):
            insert(connection, "access_receipts", receipt() | changes)
    audit = dict(
        audit_id=FIRST,
        operation_id=FIRST,
        action="issue_session",
        actor_ref="system",
        recorded_at=1000,
        safe_facts_json="{}",
    )
    with pytest.raises(IntegrityError):
        insert(connection, "access_audit", audit)
    insert(connection, "access_receipts", receipt())
    insert(connection, "access_audit", audit)
    for sql in (
        "UPDATE access_audit SET safe_facts_json='{}'",
        "DELETE FROM access_audit",
        "INSERT OR REPLACE INTO access_audit SELECT * FROM access_audit",
    ):
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(sql)


def test_attempt_uniqueness_and_continuation_binding(connection):
    insert(
        connection,
        "source_login_attempts",
        attempt(
            state="completed",
            handoff_id=FIRST,
            continuation_id=FIRST,
            binding_assertion_hash="f" * 64,
            binding_expires_at=1500,
        ),
    )
    with pytest.raises(IntegrityError):
        insert(connection, "source_login_attempts", attempt(attempt_id=SECOND))
    with pytest.raises(IntegrityError):
        insert(
            connection,
            "source_login_attempts",
            attempt(
                attempt_id=SECOND,
                browser_challenge_hash="e" * 64,
                handoff_id=FIRST,
            ),
        )


def test_temporary_identity_rows_are_immutable_but_deletable(connection):
    insert(connection, "source_login_attempts", attempt(state="expired"))
    insert(connection, "access_sessions", session(revoked_at=1500))
    for sql in (
        "UPDATE access_sessions SET remembered_until=5000",
        "UPDATE source_login_attempts SET expires_at=3000",
        "INSERT OR REPLACE INTO access_sessions SELECT * FROM access_sessions",
        "INSERT OR REPLACE INTO source_login_attempts SELECT * FROM source_login_attempts",
    ):
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(sql)
    connection.exec_driver_sql("DELETE FROM access_sessions")
    connection.exec_driver_sql("DELETE FROM source_login_attempts")

"""H03.2 row constraints, durable guards, reverse references and rollback.

Matrix: valid Admin flow; invalid scope/deadline/result combinations; idempotency
and one-way evidence; rollback; persistence/backup via SQLite serialization; indexed
reverse dependencies. Remote proof, lineage policy, CAS and cleanup are owner tests.
"""

from pathlib import Path
import json
import runpy
import sqlite3

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.modules.host_agent.application.build_inputs import MAIN_ADMIN_TABLES

APPLICATION = Path(__file__).resolve().parents[5]
REVISION = APPLICATION / "database/admin-migrations/versions/admin_0001_initial.py"
FIRST = "00000000-0000-4000-8000-000000000001"
SECOND = "00000000-0000-4000-8000-000000000002"


@pytest.fixture
def database():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        revision = runpy.run_path(str(REVISION))
        with Operations.context(MigrationContext.configure(connection)):
            revision["upgrade"]()
        connection.commit()
        yield connection
    engine.dispose()


def insert(connection, table, values):
    connection.execute(
        sa.text(
            f"INSERT INTO {table} ({','.join(values)}) "
            f"VALUES ({','.join(':' + name for name in values)})"
        ),
        values,
    )


def managed():
    return dict(
        managed_session_id=FIRST,
        cookie_hash="a" * 64,
        purpose="admin",
        operator_id=None,
        issuer="firebase:realm",
        subject="uid",
        email_key="google:user@example.com",
        method="google_totp",
        authenticated_at=100,
        mfa_verified_at=101,
        issued_at=102,
        provider_valid_until=10000,
        remembered_until=20000,
        revocation_checked_at=103,
        revocation_valid_until=5000,
        revoked_at=None,
        revision=1,
    )


def attempt():
    return dict(
        attempt_id=FIRST,
        purpose="admin_login",
        operator_id=None,
        parent_managed_session_id=None,
        source_attempt_id=None,
        source_browser_hash=None,
        central_browser_hash="b" * 64,
        method="google_totp",
        email_key=None,
        target_origin="https://admin.example.com",
        return_path="/",
        confirmed_request_hash=None,
        delivery_attempts=0,
        last_delivery_at=None,
        last_delivery_code=None,
        state="pending",
        created_at=1,
        expires_at=1000,
        revision=1,
    )


def command():
    return dict(
        operation_id=SECOND,
        kind="recent_auth",
        idempotency_key="auth:1",
        request_hash="c" * 64,
        operator_id=None,
        managed_session_id=FIRST,
        attempt_id=FIRST,
        access_epoch=None,
        state="pending",
        result_json=None,
        source_receipt_ref=None,
        created_at=103,
        updated_at=103,
        revision=1,
    )


def test_empty_baseline_and_indexed_restrict_references(database):
    revision = runpy.run_path(str(REVISION))
    assert revision["down_revision"] is None
    assert revision["TABLES"] == MAIN_ADMIN_TABLES
    inspector = sa.inspect(database)
    for table in MAIN_ADMIN_TABLES:
        assert database.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar() == 0
    for table in (
        "login_attempts",
        "email_continuations",
        "managed_identity_sessions",
        "identity_commands",
        "login_handoffs",
        "admin_sessions",
    ):
        keys = [tuple(item["column_names"]) for item in inspector.get_indexes(table)]
        keys += [tuple(item["column_names"]) for item in inspector.get_unique_constraints(table)]
        for foreign in inspector.get_foreign_keys(table):
            assert foreign["options"]["ondelete"] == "RESTRICT"
            columns = tuple(foreign["constrained_columns"])
            assert any(key[: len(columns)] == columns for key in keys)


@pytest.mark.parametrize(
    "changes",
    [
        {"purpose": "operator"},
        {"method": "google"},
        {"mfa_verified_at": None},
        {"provider_valid_until": 102},
        {"remembered_until": 102},
        {"revocation_valid_until": 400000},
        {"revoked_at": 101},
        {"subject": ""},
    ],
)
def test_managed_invalid_combinations(database, changes):
    with pytest.raises(IntegrityError):
        insert(database, "managed_identity_sessions", managed() | changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"purpose": "operator_login"},
        {"method": "email_link"},
        {"source_attempt_id": SECOND},
        {"purpose": "recent_auth"},
        {"confirmed_request_hash": "c" * 64},
        {"expires_at": 1000000},
        {"delivery_attempts": 1},
        {"last_delivery_code": "sent"},
        {"return_path": "//evil"},
    ],
)
def test_attempt_invalid_combinations(database, changes):
    with pytest.raises(IntegrityError):
        insert(database, "login_attempts", attempt() | changes)


def test_original_result_retry_and_terminal_guards(database):
    insert(database, "managed_identity_sessions", managed())
    insert(database, "login_attempts", attempt())
    insert(database, "identity_commands", command())
    result = json.dumps(
        dict(version=1, kind="recent_auth", result_id=FIRST, source_receipt_ref=None)
    )
    database.execute(
        sa.text("UPDATE identity_commands SET state='succeeded', result_json=:r"), {"r": result}
    )
    for sql in (
        "UPDATE identity_commands SET state='pending', result_json=NULL",
        "UPDATE identity_commands SET request_hash='" + "d" * 64 + "'",
        "DELETE FROM managed_identity_sessions",
        "DELETE FROM login_attempts",
    ):
        with pytest.raises(IntegrityError):
            database.exec_driver_sql(sql)
    with pytest.raises(IntegrityError):
        insert(database, "identity_commands", command())
    database.exec_driver_sql("UPDATE managed_identity_sessions SET revoked_at=200")
    with pytest.raises(IntegrityError):
        database.exec_driver_sql("UPDATE managed_identity_sessions SET revoked_at=NULL")
    database.exec_driver_sql("UPDATE login_attempts SET state='verified'")
    with pytest.raises(IntegrityError):
        database.exec_driver_sql("UPDATE login_attempts SET state='pending'")


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"version": 1, "kind": "recent_auth", "result_id": FIRST},
        dict(version=1, kind="claim", result_id=FIRST, source_receipt_ref=None),
        dict(version=1, kind="recent_auth", result_id="bad", source_receipt_ref=None),
        dict(
            version=1, kind="recent_auth", result_id=FIRST, source_receipt_ref=None, token="secret"
        ),
    ],
)
def test_typed_result_rejects_incomplete_or_extra_facts(database, result):
    insert(database, "managed_identity_sessions", managed())
    insert(database, "login_attempts", attempt())
    with pytest.raises(IntegrityError):
        insert(
            database,
            "identity_commands",
            command() | {"state": "succeeded", "result_json": json.dumps(result)},
        )


def test_rollback_and_backup_preserve_guards(database):
    insert(database, "managed_identity_sessions", managed())
    database.commit()
    insert(database, "login_attempts", attempt())
    database.rollback()
    assert database.exec_driver_sql("SELECT count(*) FROM login_attempts").scalar() == 0
    raw = database.connection.driver_connection

    restored = sqlite3.connect(":memory:")
    try:
        restored.deserialize(raw.serialize())
        assert restored.execute("SELECT subject FROM managed_identity_sessions").fetchone() == (
            "uid",
        )
        with pytest.raises(sqlite3.IntegrityError):
            restored.execute("UPDATE managed_identity_sessions SET subject='other'")
    finally:
        restored.close()


def test_admin_session_extensions(database):
    insert(database, "managed_identity_sessions", managed())
    insert(
        database,
        "admin_principals",
        dict(
            principal_id=FIRST,
            issuer="realm",
            subject="uid",
            enabled=1,
            session_generation=1,
            revision=1,
            created_at=1,
        ),
    )
    session = dict(
        session_hash="e" * 64,
        principal_id=FIRST,
        csrf_hash="f" * 64,
        generation=1,
        authenticated_at=100,
        mfa_verified_at=101,
        expires_at=4000,
        last_seen_at=102,
        revoked_at=None,
        managed_session_id=FIRST,
        managed_valid_until=10000,
        revocation_valid_until=5000,
    )
    with pytest.raises(IntegrityError):
        insert(database, "admin_sessions", session | {"managed_valid_until": 3000})
    insert(database, "admin_sessions", session)
    with pytest.raises(IntegrityError):
        database.exec_driver_sql("UPDATE admin_sessions SET managed_session_id='" + SECOND + "'")


def test_continuation_and_handoff_checks(database):
    # Scope correspondence across these records is intentionally an owner obligation.
    insert(
        database,
        "storage_policies",
        dict(
            policy_id=FIRST,
            plan_code="free",
            policy_version=1,
            usable_bytes=1,
            backup_interval_seconds=1,
            retained_nightly_points=1,
            keep_warm=0,
            created_at=1,
        ),
    )
    insert(
        database,
        "operators",
        dict(
            operator_id=FIRST,
            workspace_id=SECOND,
            display_name="Test",
            invited_email="a@example.com",
            email_key="a@example.com",
            workspace_slug="test",
            issuer="realm",
            subject=None,
            desired_policy_id=FIRST,
            desired_access="enabled",
            setup_state="pending",
            support_contact="a@example.com",
            access_epoch=1,
            revision=1,
            created_at=1,
            updated_at=1,
            retired_at=None,
        ),
    )
    insert(database, "managed_identity_sessions", managed())
    insert(database, "login_attempts", attempt())
    insert(database, "login_attempts", attempt() | {"attempt_id": SECOND})
    insert(database, "identity_commands", command())
    handoff = dict(
        handoff_id=FIRST,
        operator_id=FIRST,
        browser_state_hash="a" * 64,
        nonce_hash="b" * 64,
        code_hash=None,
        target_origin="https://test.example.com",
        issuer=None,
        subject=None,
        assignment_revision=1,
        access_epoch=1,
        state="initiated",
        expires_at=1000,
        redeemed_at=None,
        created_at=103,
        attempt_id=FIRST,
        managed_session_id=FIRST,
        identity_operation_id=SECOND,
        source_receipt_ref=None,
    )
    with pytest.raises(IntegrityError):
        insert(database, "login_handoffs", handoff | {"state": "issued"})
    insert(database, "login_handoffs", handoff)
    database.exec_driver_sql(
        "UPDATE login_handoffs SET state='issued', issuer='realm', "
        "subject='uid', code_hash='" + "c" * 64 + "'"
    )
    database.exec_driver_sql("UPDATE login_handoffs SET state='redeeming'")
    with pytest.raises(IntegrityError):
        database.exec_driver_sql("UPDATE login_handoffs SET state='issued'")
    with pytest.raises(IntegrityError):
        database.exec_driver_sql("UPDATE login_handoffs SET state='redeemed', redeemed_at=200")
    database.exec_driver_sql(
        "UPDATE login_handoffs SET state='redeemed', redeemed_at=200, "
        "source_receipt_ref='receipt:1'"
    )
    continuation = dict(
        continuation_id=FIRST,
        original_attempt_id=FIRST,
        code_hash="d" * 64,
        central_browser_hash="e" * 64,
        operator_id=FIRST,
        target_origin="https://test.example.com",
        access_epoch=1,
        managed_session_id=None,
        replacement_attempt_id=None,
        source_attempt_id=None,
        source_binding_hash=None,
        handoff_id=None,
        state="verifying",
        created_at=103,
        expires_at=1000,
        revision=1,
    )
    with pytest.raises(IntegrityError):
        insert(database, "email_continuations", continuation | {"state": "verified"})
    insert(database, "email_continuations", continuation)
    database.exec_driver_sql(
        "UPDATE email_continuations SET state='verified', managed_session_id='" + FIRST + "'"
    )
    with pytest.raises(IntegrityError):
        database.exec_driver_sql("UPDATE email_continuations SET state='paired'")
    database.exec_driver_sql(
        "UPDATE email_continuations SET state='paired', "
        "replacement_attempt_id='" + SECOND + "', source_attempt_id='" + SECOND + "', "
        "source_binding_hash='" + "f" * 64 + "'"
    )
    with pytest.raises(IntegrityError):
        database.exec_driver_sql(
            "UPDATE email_continuations SET source_binding_hash='" + "a" * 64 + "'"
        )
    database.exec_driver_sql(
        "UPDATE email_continuations SET state='completed', handoff_id='" + FIRST + "'"
    )
    with pytest.raises(IntegrityError):
        database.exec_driver_sql("DELETE FROM login_handoffs")

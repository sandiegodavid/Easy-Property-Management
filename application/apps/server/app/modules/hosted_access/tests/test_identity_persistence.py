"""H03.2 explicit binding, retained-record validation and dependency-aware cleanup."""

from pathlib import Path
import json
import sqlite3

from scripts.hosted_package import copy_resources
from uuid import UUID

from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine, event, text

from app.modules.hosted_access.application.identity_setup import DAY
from app.modules.hosted_access.application.source_contracts import AdmittedFreePolicy
from app.modules.hosted_access.infrastructure.identity_cleanup import cleanup_identity
from app.modules.hosted_access.infrastructure.schema_store import (
    DisabledAccessBinding,
    bind_disabled_access,
)
from app.platform.hosted_schema import (
    HostedSchemaError,
    InitializationResult,
    initialize_store,
    validate_schema,
)
from app.platform.schema_resources import HostedStore, SchemaResourcesUnavailable
from app.platform.tests.test_hosted_schema import seed_admin, insert
from app.platform.tests.test_admin_identity_schema import (
    managed as admin_managed,
    attempt as admin_attempt,
)
from app.platform.tests.test_access_schema import session, attempt as source_attempt

APPLICATION = Path(__file__).resolve().parents[6]
FIRST = "00000000-0000-4000-8000-000000000001"
SECOND = "00000000-0000-4000-8000-000000000002"


@pytest.fixture(params=[HostedStore.ADMIN, HostedStore.HOSTED_ACCESS])
def store(request, tmp_path):
    private = tmp_path.resolve() / "private"
    private.mkdir(mode=0o700)
    path = private / "store.sqlite"
    initialize_store(request.param, path, application_directory=APPLICATION)
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        yield request.param, conn, path
        conn.rollback()
    engine.dispose()


def binding(**changes):
    return DisabledAccessBinding(
        **(
            dict(
                deployment_id=FIRST,
                operator_id=FIRST,
                workspace_id=FIRST,
                binding_id=FIRST,
                resource_generation=1,
                issuer="realm-v1",
                email_key="realm:user@example.invalid",
                access_epoch=1,
                session_generation=1,
                not_before=100,
                policy=AdmittedFreePolicy(
                    policy_id=FIRST, policy_revision=1, admission_hash="a" * 64
                ),
                restore_generation=1,
                revision=1,
            )
            | changes
        )
    )


def source_only(store):
    owner, conn, path = store
    if owner != HostedStore.HOSTED_ACCESS:
        return None
    return conn, path


def test_fresh_resource_reinit_is_readonly_and_disabled_binding_is_explicit(store):
    owner, conn, path = store
    assert validate_schema(conn, owner, application_directory=APPLICATION)
    if owner == HostedStore.HOSTED_ACCESS:
        assert conn.exec_driver_sql("SELECT count(*) FROM access_meta").scalar_one() == 0
        assert bind_disabled_access(conn, binding(), application_directory=APPLICATION)
        conn.commit()
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        assert not bind_disabled_access(conn, binding(), application_directory=APPLICATION)
        for table in (
            "access_sessions",
            "source_login_attempts",
            "usage_state",
            "usage_reservations",
            "access_receipts",
        ):
            assert conn.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one() == 0
        with pytest.raises(HostedSchemaError):
            bind_disabled_access(conn, binding(access_epoch=2), application_directory=APPLICATION)
    conn.commit()
    before = path.read_bytes(), path.stat().st_mtime_ns
    assert (
        initialize_store(owner, path, application_directory=APPLICATION)
        == InitializationResult.ALREADY_INITIALIZED
    )
    assert before == (path.read_bytes(), path.stat().st_mtime_ns)


@pytest.mark.parametrize("store", [HostedStore.HOSTED_ACCESS], indirect=True)
def test_binding_rolls_back_without_inventing_policy_or_usage(store):
    if not source_only(store):
        return
    conn, _ = source_only(store)
    bind_disabled_access(conn, binding(), application_directory=APPLICATION)
    conn.rollback()
    conn.exec_driver_sql("BEGIN IMMEDIATE")
    assert conn.exec_driver_sql("SELECT count(*) FROM access_meta").scalar_one() == 0
    with pytest.raises(ValidationError):
        binding(
            policy=AdmittedFreePolicy(
                policy_id=FIRST, policy_revision=1, admission_hash="a" * 64, usable_bytes=0
            )
        )


def seed_flow(conn, *, unknown=False, email=False):
    seed_admin(conn)
    m = admin_managed() | dict(
        purpose="operator",
        operator_id=FIRST,
        method="email_link" if email else "google",
        mfa_verified_at=None,
        remembered_until=30 * DAY,
    )
    insert(conn, "managed_identity_sessions", m)
    a = admin_attempt() | dict(
        purpose="operator_login",
        operator_id=FIRST,
        method="email_link" if email else "google",
        email_key=m["email_key"] if email else None,
        source_attempt_id=FIRST,
        source_browser_hash="c" * 64,
        target_origin="https://synthetic-operator.example.invalid",
        state="expired",
    )
    insert(conn, "login_attempts", a)
    result = dict(version=1, kind="issue_handoff", result_id=FIRST, source_receipt_ref=None)
    insert(
        conn,
        "identity_commands",
        dict(
            operation_id=FIRST,
            kind="issue_handoff",
            idempotency_key="original",
            request_hash="d" * 64,
            operator_id=FIRST,
            managed_session_id=FIRST,
            attempt_id=FIRST,
            access_epoch=1,
            state="unknown" if unknown else "succeeded",
            result_json=None if unknown else json.dumps(result),
            source_receipt_ref=None,
            created_at=102,
            updated_at=103,
            revision=1,
        ),
    )
    insert(
        conn,
        "login_handoffs",
        dict(
            handoff_id=FIRST,
            operator_id=FIRST,
            browser_state_hash="c" * 64,
            nonce_hash="e" * 64,
            code_hash=None,
            target_origin=a["target_origin"],
            issuer=None,
            subject=None,
            assignment_revision=1,
            access_epoch=1,
            state="expired",
            expires_at=1000,
            redeemed_at=None,
            created_at=110,
            attempt_id=FIRST,
            managed_session_id=FIRST,
            identity_operation_id=FIRST,
            source_receipt_ref=None,
        ),
    )


@pytest.mark.parametrize("store", [HostedStore.ADMIN], indirect=True)
def test_cleanup_keeps_live_lineage_and_unknown_source_results_then_reclaims(store):
    owner, conn, _ = store
    if owner != HostedStore.ADMIN:
        return
    seed_flow(conn, unknown=True, email=True)
    insert(
        conn,
        "email_continuations",
        dict(
            continuation_id=FIRST,
            original_attempt_id=FIRST,
            code_hash="f" * 64,
            central_browser_hash="c" * 64,
            operator_id=FIRST,
            target_origin="https://synthetic-operator.example.invalid",
            access_epoch=1,
            managed_session_id=FIRST,
            replacement_attempt_id=None,
            source_attempt_id=None,
            source_binding_hash=None,
            handoff_id=None,
            state="expired",
            created_at=110,
            expires_at=900,
            revision=1,
        ),
    )
    validate_schema(conn, owner, application_directory=APPLICATION)
    assert cleanup_identity(conn, owner, now=2 * DAY).deleted == 0
    # More than thirty days does not turn unknown into an absent result.
    assert cleanup_identity(conn, owner, now=40 * DAY).deleted == 0
    payload = json.dumps(
        dict(version=1, kind="issue_handoff", result_id=FIRST, source_receipt_ref=None)
    )
    conn.execute(
        text(
            "UPDATE identity_commands SET state='succeeded',result_json=:result,updated_at=:at,revision=2"
        ),
        dict(result=payload, at=40 * DAY),
    )
    assert (
        cleanup_identity(conn, owner, now=40 * DAY).deleted == 2
    )  # continuation/handoff retired; command still held 24h
    for _ in range(3):
        cleanup_identity(conn, owner, now=42 * DAY)
    for table in (
        "login_handoffs",
        "identity_commands",
        "login_attempts",
        "managed_identity_sessions",
    ):
        assert conn.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one() == 0
    assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []


@pytest.mark.parametrize("store", [HostedStore.HOSTED_ACCESS], indirect=True)
def test_source_replacement_chains_retire_leaf_first_only_with_owning_reconciliation(store):
    if not source_only(store):
        return
    conn, _ = source_only(store)
    insert(conn, "access_sessions", session())
    insert(
        conn,
        "access_sessions",
        session(
            session_id=SECOND,
            session_hash="f" * 64,
            handoff_id=SECOND,
            renewed_from_session_id=FIRST,
        ),
    )
    insert(conn, "source_login_attempts", source_attempt(state="completed", handoff_id=SECOND))
    assert cleanup_identity(conn, HostedStore.HOSTED_ACCESS, now=3 * DAY).deleted == 0
    assert (
        cleanup_identity(
            conn, HostedStore.HOSTED_ACCESS, now=3 * DAY, reconciled_handoffs=(FIRST, SECOND)
        ).deleted
        == 2
    )
    assert (
        cleanup_identity(
            conn, HostedStore.HOSTED_ACCESS, now=3 * DAY, reconciled_handoffs=(FIRST, SECOND)
        ).deleted
        == 1
    )
    assert conn.exec_driver_sql("SELECT count(*) FROM access_sessions").scalar_one() == 0
    assert conn.exec_driver_sql("SELECT count(*) FROM source_login_attempts").scalar_one() == 0


@pytest.mark.parametrize("store", [HostedStore.HOSTED_ACCESS], indirect=True)
def test_cleanup_total_bound_and_rollback(store):
    if not source_only(store):
        return
    conn, _ = source_only(store)
    for number in range(1, 106):
        insert(
            conn,
            "source_login_attempts",
            source_attempt(
                attempt_id=str(UUID(int=number)),
                browser_challenge_hash=f"{number:064x}",
                state="expired",
            ),
        )
    conn.commit()
    conn.exec_driver_sql("BEGIN IMMEDIATE")
    result = cleanup_identity(conn, HostedStore.HOSTED_ACCESS, now=3 * DAY)
    assert result.examined == result.deleted == 100
    conn.rollback()
    conn.exec_driver_sql("BEGIN IMMEDIATE")
    assert conn.exec_driver_sql("SELECT count(*) FROM source_login_attempts").scalar_one() == 105
    with pytest.raises(ValueError):
        cleanup_identity(conn, HostedStore.HOSTED_ACCESS, now=3 * DAY, limit=101)


@pytest.mark.parametrize("store", [HostedStore.HOSTED_ACCESS], indirect=True)
def test_retained_return_path_and_receipt_json_are_not_accepted_as_authority(store):
    owner, conn, _ = store
    if owner != HostedStore.HOSTED_ACCESS:
        return
    # The row CHECK is deliberately weaker than decoded route validation.
    insert(conn, "source_login_attempts", source_attempt(return_path="/%61uth/start"))
    with pytest.raises(HostedSchemaError):
        validate_schema(conn, owner, application_directory=APPLICATION)
    conn.rollback()
    conn.exec_driver_sql("BEGIN IMMEDIATE")
    insert(
        conn,
        "access_receipts",
        dict(
            operation_id=FIRST,
            request_hash="a" * 64,
            kind="issue_session",
            access_epoch=1,
            source_revision=1,
            result_json='{"cookie":"secret"}',
            recorded_at=100,
        ),
    )
    with pytest.raises(HostedSchemaError):
        validate_schema(conn, owner, application_directory=APPLICATION)


def test_data_validation_queries_are_fixed_as_rows_grow_and_control_backup_reopens(store):
    owner, conn, path = store
    counts = []
    for number in range(2):
        statements = []

        def capture(*args):
            statements.append(args[2])

        event.listen(conn, "before_cursor_execute", capture)
        validate_schema(conn, owner, application_directory=APPLICATION)
        event.remove(conn, "before_cursor_execute", capture)
        counts.append(len(statements))
        if owner == HostedStore.ADMIN and number == 0:
            seed_flow(conn)
        elif owner == HostedStore.HOSTED_ACCESS and number == 0:
            bind_disabled_access(conn, binding(), application_directory=APPLICATION)
    assert counts[0] == counts[1]
    assert not any(sql.startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)
    conn.commit()
    copy = path.with_name("backup.sqlite")
    with sqlite3.connect(path) as original, sqlite3.connect(copy) as restored:
        original.backup(restored)
    copy.chmod(0o600)
    assert (
        initialize_store(owner, copy, application_directory=APPLICATION)
        == InitializationResult.ALREADY_INITIALIZED
    )


def test_installed_resource_initialization_has_no_checkout_or_scaffold_fallback(
    tmp_path, monkeypatch
):
    installed = tmp_path.resolve() / "installed"
    copy_resources(APPLICATION, installed, "operator")
    private = tmp_path.resolve() / "private"
    private.mkdir(mode=0o700)
    monkeypatch.chdir(tmp_path)
    destination = private / "installed-access.sqlite"
    assert (
        initialize_store(HostedStore.HOSTED_ACCESS, destination, application_directory=installed)
        == InitializationResult.INITIALIZED
    )
    assert (
        initialize_store(HostedStore.HOSTED_ACCESS, destination, application_directory=installed)
        == InitializationResult.ALREADY_INITIALIZED
    )
    baseline = installed / "database/hosted-access-migrations/versions/access_0001_initial.py"
    baseline.unlink()
    with pytest.raises(SchemaResourcesUnavailable):
        initialize_store(
            HostedStore.HOSTED_ACCESS,
            private / "must-not-exist.sqlite",
            application_directory=installed,
        )
    assert not (private / "must-not-exist.sqlite").exists()

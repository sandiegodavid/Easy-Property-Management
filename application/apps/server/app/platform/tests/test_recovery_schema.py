"""H05.1 greenfield recovery and admin-recovery schema, trigger, and relationship tests."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.platform.hosted_schema import (
    PRIVATE_FILE_MODE,
    HostedSchemaError,
    InitializationResult,
    create_schema,
    initialize_store,
    validate_schema,
)
from app.platform.schema_resources import HostedStore

APPLICATION = Path(__file__).resolve().parents[5]
SHA256_HEX_LEN = 64
FIRST = "00000000-0000-4000-8000-000000000001"
SECOND = "00000000-0000-4000-8000-000000000002"
THIRD = "00000000-0000-4000-8000-000000000003"
FOURTH = "00000000-0000-4000-8000-000000000004"


@pytest.fixture
def recovery_conn():
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        create_schema(conn, HostedStore.RECOVERY, application_directory=APPLICATION)
        yield conn
        conn.rollback()
    engine.dispose()


@pytest.fixture
def admin_recovery_conn():
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        create_schema(conn, HostedStore.ADMIN_RECOVERY, application_directory=APPLICATION)
        yield conn
        conn.rollback()
    engine.dispose()


def _insert(conn, table, values):
    cols = ", ".join(values)
    params = ", ".join(f":{k}" for k in values)
    conn.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({params})"), values)


def _seed_recovery_meta(conn):
    _insert(
        conn,
        "recovery_meta",
        dict(
            id=1,
            workspace_id=FIRST,
            deployment_ref="dep:pilot-0",
            source_generation=1,
            restore_generation=1,
            active_business_ref="incarnation-1",
            encryption_key_ref="kms:epm-v1",
            namespace_prefix=f"deployments/{FIRST}/operators/{SECOND}",
            revision=1,
        ),
    )


def _seed_backup_op_and_point(conn):
    _insert(
        conn,
        "recovery_operations",
        dict(
            operation_id=FIRST,
            kind="backup",
            idempotency_key="backup-1",
            request_hash="a" * 64,
            request_json='{"kind":"backup"}',
            actor_kind="system",
            actor_ref="scheduler:nightly",
            state="succeeded",
            source_generation=1,
            result_json='{"point_id":"' + SECOND + '"}',
            error_code=None,
            created_at=1000,
            updated_at=1500,
            revision=2,
        ),
    )
    _insert(
        conn,
        "recovery_points",
        dict(
            point_id=SECOND,
            workspace_id=FIRST,
            operation_id=FIRST,
            manifest_ref="manifest:point-1",
            manifest_sha256="b" * 64,
            manifest_format="epm-recovery-v1",
            business_revision="biz-rev:10",
            files_generation="files-gen:3",
            source_generation=1,
            release_ref="release:h05",
            schema_revision="0001_initial_schema",
            access_schema_revision="access_0001_initial",
            captured_at=1100,
            verified_at=1400,
            retain_until=9000,
            key_ref="kms:epm-v1",
            stored_bytes=4096,
            state="verified",
            last_checked_at=1400,
            revision=1,
        ),
    )


def _seed_admin_recovery_meta(conn):
    _insert(
        conn,
        "admin_recovery_meta",
        dict(
            id=1,
            deployment_id=FIRST,
            incarnation_id=SECOND,
            recovery_authority_ref="authority:sha256-pin",
            source_generation=1,
            active_admin_resource_ref="admin-db:incarnation-1",
            encryption_key_ref="kms:control-v1",
            namespace_prefix=f"deployments/{FIRST}/control",
            created_at=1000,
            revision=1,
        ),
    )


def _seed_control_op_and_point(conn):
    _insert(
        conn,
        "control_recovery_operations",
        dict(
            operation_id=FIRST,
            kind="backup",
            idempotency_key="ctrl-backup-1",
            request_hash="c" * 64,
            request_json='{"kind":"backup"}',
            actor_kind="system",
            actor_ref="scheduler:control",
            authorization_ref=None,
            authorized_at=None,
            authorization_expires_at=None,
            source_generation=1,
            state="succeeded",
            result_json='{"point_id":"' + SECOND + '"}',
            error_code=None,
            created_at=1000,
            updated_at=1500,
            revision=2,
        ),
    )
    _insert(
        conn,
        "control_recovery_points",
        dict(
            point_id=SECOND,
            operation_id=FIRST,
            manifest_ref="control-manifest:point-1",
            manifest_sha256="d" * 64,
            manifest_format="epm-control-v1",
            captured_at=1100,
            verified_at=1400,
            retain_until=9000,
            key_ref="kms:control-v1",
            stored_bytes=2048,
            state="verified",
            last_checked_at=1400,
            revision=1,
        ),
    )


@pytest.mark.parametrize("store", (HostedStore.RECOVERY, HostedStore.ADMIN_RECOVERY))
def test_initialize_store_is_idempotent_and_private(store, tmp_path):
    private = tmp_path.resolve() / "control"
    private.mkdir(mode=0o700)
    target = private / f"{store.value}.sqlite"
    assert (
        initialize_store(store, target, application_directory=APPLICATION)
        == InitializationResult.INITIALIZED
    )
    assert (target.stat().st_mode & 0o777) == PRIVATE_FILE_MODE
    assert (
        initialize_store(store, target, application_directory=APPLICATION)
        == InitializationResult.ALREADY_INITIALIZED
    )


def test_recovery_tables_and_valid_lifecycle_pass_validation(recovery_conn):
    tables = set(inspect(recovery_conn).get_table_names())
    assert tables == {
        "alembic_version",
        "recovery_meta",
        "recovery_operations",
        "recovery_points",
        "backup_state",
        "restore_operations",
        "recovery_audit",
    }
    _seed_recovery_meta(recovery_conn)
    _seed_backup_op_and_point(recovery_conn)
    _insert(
        recovery_conn,
        "backup_state",
        dict(
            id=1,
            last_point_id=SECOND,
            protected_business_revision="biz-rev:10",
            protected_files_generation="files-gen:3",
            protected_source_generation=1,
            protection_state="healthy",
            dirty_since=None,
            last_checked_at=1500,
            last_backup_attempt_at=1500,
            consecutive_failures=0,
            last_error_code=None,
            revision=1,
        ),
    )
    _insert(
        recovery_conn,
        "recovery_operations",
        dict(
            operation_id=THIRD,
            kind="restore",
            idempotency_key="restore-1",
            request_hash="e" * 64,
            request_json='{"point_id":"' + SECOND + '"}',
            actor_kind="operator",
            actor_ref="operator:sub-1",
            state="running",
            source_generation=1,
            result_json=None,
            error_code=None,
            created_at=2000,
            updated_at=2100,
            revision=1,
        ),
    )
    _insert(
        recovery_conn,
        "restore_operations",
        dict(
            operation_id=THIRD,
            point_id=SECOND,
            preview_id=FOURTH,
            prior_business_ref="incarnation-1",
            prior_tree_kind="healthy_pre_state",
            target_business_ref="incarnation-2",
            new_source_generation=2,
            new_access_epoch=2,
            authorized_subject="firebase:sub-1",
            authorization_ref="stepup:proof-1",
            authorized_at=1900,
            execution_authorization_expires_at=2500,
            preview_source_revision="biz-rev:10",
            executor_ref="operator-internal",
            phase="fenced",
            validation_ref=None,
            started_at=2000,
            updated_at=2100,
            accepted_at=None,
        ),
    )
    _insert(
        recovery_conn,
        "recovery_audit",
        dict(
            audit_id=FIRST,
            operation_id=THIRD,
            actor_ref="operator:sub-1",
            action="restore_fenced",
            recorded_at=2100,
            safe_facts_json='{"phase":"fenced"}',
        ),
    )
    fp = validate_schema(recovery_conn, HostedStore.RECOVERY, application_directory=APPLICATION)
    assert len(fp) == SHA256_HEX_LEN


def test_recovery_constraints_and_immutability_guards(recovery_conn):
    _seed_recovery_meta(recovery_conn)
    _seed_backup_op_and_point(recovery_conn)

    # Path traversal in namespace_prefix is rejected.
    with pytest.raises(IntegrityError):
        recovery_conn.exec_driver_sql("UPDATE recovery_meta SET namespace_prefix='../escape'")

    # Identity columns and DELETE on recovery_meta are blocked.
    with pytest.raises(IntegrityError):
        recovery_conn.exec_driver_sql(f"UPDATE recovery_meta SET workspace_id='{SECOND}'")
    with pytest.raises(IntegrityError):
        recovery_conn.exec_driver_sql("DELETE FROM recovery_meta")

    # System actor cannot originate a restore operation.
    with pytest.raises(IntegrityError):
        _insert(
            recovery_conn,
            "recovery_operations",
            dict(
                operation_id=THIRD,
                kind="restore",
                idempotency_key="bad-restore",
                request_hash="e" * 64,
                request_json="{}",
                actor_kind="system",
                actor_ref="scheduler:nightly",
                state="pending",
                source_generation=1,
                result_json=None,
                error_code=None,
                created_at=2000,
                updated_at=2000,
                revision=1,
            ),
        )

    # Terminal operation cannot be mutated; audit is strictly append-only.
    with pytest.raises(IntegrityError):
        recovery_conn.exec_driver_sql("UPDATE recovery_operations SET state='failed'")
    with pytest.raises(IntegrityError):
        recovery_conn.exec_driver_sql("UPDATE recovery_points SET manifest_ref='manifest:tampered'")
    with pytest.raises(IntegrityError):
        recovery_conn.exec_driver_sql("DELETE FROM recovery_points")

    _insert(
        recovery_conn,
        "recovery_audit",
        dict(
            audit_id=FIRST,
            operation_id=FIRST,
            actor_ref="scheduler:nightly",
            action="backup_verified",
            recorded_at=1500,
            safe_facts_json='{"state":"verified"}',
        ),
    )
    with pytest.raises(IntegrityError):
        recovery_conn.exec_driver_sql("UPDATE recovery_audit SET action='tampered'")
    with pytest.raises(IntegrityError):
        recovery_conn.exec_driver_sql("DELETE FROM recovery_audit")

    # backup_state cannot claim healthy without a verified point.
    with pytest.raises(IntegrityError):
        _insert(
            recovery_conn,
            "backup_state",
            dict(
                id=1,
                last_point_id=None,
                protected_business_revision=None,
                protected_files_generation=None,
                protected_source_generation=None,
                protection_state="healthy",
                dirty_since=None,
                last_checked_at=1500,
                last_backup_attempt_at=1500,
                consecutive_failures=0,
                last_error_code=None,
                revision=1,
            ),
        )


def test_recovery_cross_table_relationship_validation_rejects_mismatch(recovery_conn):
    _seed_recovery_meta(recovery_conn)
    _seed_backup_op_and_point(recovery_conn)
    # Insert a backup_state whose protected_business_revision disagrees with recovery_points.
    _insert(
        recovery_conn,
        "backup_state",
        dict(
            id=1,
            last_point_id=SECOND,
            protected_business_revision="biz-rev:999",
            protected_files_generation="files-gen:3",
            protected_source_generation=1,
            protection_state="healthy",
            dirty_since=None,
            last_checked_at=1500,
            last_backup_attempt_at=1500,
            consecutive_failures=0,
            last_error_code=None,
            revision=1,
        ),
    )
    with pytest.raises(HostedSchemaError):
        validate_schema(recovery_conn, HostedStore.RECOVERY, application_directory=APPLICATION)


def test_admin_recovery_tables_constraints_and_validation(admin_recovery_conn):
    tables = set(inspect(admin_recovery_conn).get_table_names())
    assert tables == {
        "alembic_version",
        "admin_recovery_meta",
        "control_recovery_operations",
        "control_recovery_points",
        "control_restore_operations",
        "control_backup_state",
        "control_recovery_audit",
    }
    _seed_admin_recovery_meta(admin_recovery_conn)
    _seed_control_op_and_point(admin_recovery_conn)

    # Restore without admin authorization fields is rejected.
    with pytest.raises(IntegrityError):
        _insert(
            admin_recovery_conn,
            "control_recovery_operations",
            dict(
                operation_id=THIRD,
                kind="restore",
                idempotency_key="ctrl-restore-noauth",
                request_hash="e" * 64,
                request_json="{}",
                actor_kind="admin",
                actor_ref="admin:principal-1",
                authorization_ref=None,
                authorized_at=None,
                authorization_expires_at=None,
                source_generation=1,
                state="pending",
                result_json=None,
                error_code=None,
                created_at=2000,
                updated_at=2000,
                revision=1,
            ),
        )

    # Valid admin restore + control_restore_operations + audit passes validation.
    _insert(
        admin_recovery_conn,
        "control_recovery_operations",
        dict(
            operation_id=THIRD,
            kind="restore",
            idempotency_key="ctrl-restore-1",
            request_hash="e" * 64,
            request_json='{"point_id":"' + SECOND + '"}',
            actor_kind="admin",
            actor_ref="admin:principal-1",
            authorization_ref="mfa:proof-1",
            authorized_at=1900,
            authorization_expires_at=2500,
            source_generation=1,
            state="running",
            result_json=None,
            error_code=None,
            created_at=2000,
            updated_at=2100,
            revision=1,
        ),
    )
    _insert(
        admin_recovery_conn,
        "control_restore_operations",
        dict(
            operation_id=THIRD,
            point_id=SECOND,
            target_resource_ref="admin-db:incarnation-2",
            prior_resource_ref="admin-db:incarnation-1",
            new_registry_generation=2,
            phase="restored",
            validation_ref=None,
            started_at=2000,
            updated_at=2100,
        ),
    )
    _insert(
        admin_recovery_conn,
        "control_recovery_audit",
        dict(
            audit_id=FIRST,
            operation_id=THIRD,
            actor_ref="admin:principal-1",
            action="control_restore_started",
            recorded_at=2100,
            safe_facts_json='{"phase":"restored"}',
        ),
    )
    fp = validate_schema(
        admin_recovery_conn, HostedStore.ADMIN_RECOVERY, application_directory=APPLICATION
    )
    assert len(fp) == SHA256_HEX_LEN

    # Audit is immutable.
    with pytest.raises(IntegrityError):
        admin_recovery_conn.exec_driver_sql("DELETE FROM control_recovery_audit")

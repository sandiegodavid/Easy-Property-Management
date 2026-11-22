"""H04.1 greenfield Admin schema additions and Free v1 storage policy bootstrap tests."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.modules.hosted_admin.infrastructure.policy_bootstrap import (
    FREE_V1_BACKUP_INTERVAL_SECONDS,
    FREE_V1_KEEP_WARM,
    FREE_V1_PLAN_CODE,
    FREE_V1_POLICY_VERSION,
    FREE_V1_RETAINED_NIGHTLY_POINTS,
    FREE_V1_USABLE_BYTES,
    bootstrap_free_v1_policy,
    free_v1_policy_id,
)
from app.modules.hosted_admin.infrastructure.schema_store import DeploymentMetadata, bind_deployment
from app.platform.hosted_schema import (
    HostedSchemaError,
    InitializationResult,
    initialize_store,
    validate_schema,
)
from app.platform.schema_resources import HostedStore

APPLICATION = Path(__file__).resolve().parents[6]
DEPLOYMENT_ID = "00000000-0000-4000-8000-000000000010"
OPERATOR_ID = "00000000-0000-4000-8000-000000000011"
WORKSPACE_ID = "00000000-0000-4000-8000-000000000012"
OTHER_ID = "00000000-0000-4000-8000-000000000013"
CUSTOM_POLICY_ID = "00000000-0000-4000-8000-000000000014"
EMPTY_RESOURCES = (
    '{"boot_bytes":0,"boot_inodes":0,"cpu_millicores":0,'
    '"data_bytes":0,"data_inodes":0,"memory_bytes":0,"pids":0}'
)


@pytest.fixture
def admin_db(tmp_path):
    private = tmp_path.resolve() / "private"
    private.mkdir(mode=0o700)
    target = private / "admin.sqlite"
    assert (
        initialize_store(HostedStore.ADMIN, target, application_directory=APPLICATION)
        == InitializationResult.INITIALIZED
    )
    return target


@contextmanager
def write_tx(path: Path):
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            yield connection
            connection.rollback()
    finally:
        engine.dispose()


def insert(connection, table: str, values: dict):
    columns = ",".join(values)
    params = ",".join(":" + name for name in values)
    connection.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({params})"), values)


def bind_default_deployment(connection):
    assert bind_deployment(
        connection,
        DeploymentMetadata(
            deployment_id=DEPLOYMENT_ID,
            public_base_domain="example.invalid",
            login_origin="https://login.example.invalid",
            registry_generation=1,
            created_at=100,
        ),
        application_directory=APPLICATION,
    )


def seed_operator(connection, *, policy_id: str):
    insert(
        connection,
        "operators",
        dict(
            operator_id=OPERATOR_ID,
            workspace_id=WORKSPACE_ID,
            display_name="Pilot Operator",
            invited_email="pilot@example.invalid",
            email_key="firebase:pilot@example.invalid",
            workspace_slug="pilot-one",
            issuer="firebase:realm",
            desired_policy_id=policy_id,
            desired_access="enabled",
            setup_state="pending",
            support_contact="support@example.invalid",
            access_epoch=1,
            revision=1,
            created_at=100,
            updated_at=100,
        ),
    )


def capacity_profile(**changes):
    return (
        dict(
            profile_ref="pilot0-free-v1",
            profile_revision=1,
            measurement_sha256="a" * 64,
            source_sha256="b" * 64,
            runtime_policy_sha256="c" * 64,
            maximum_observation_age_ms=300_000,
            shared_reserve_json=EMPTY_RESOURCES,
            recovery_reserve_json=EMPTY_RESOURCES,
            free_budget_json=EMPTY_RESOURCES,
            created_at=100,
        )
        | changes
    )


def capacity_snapshot(**changes):
    return (
        dict(
            id=1,
            snapshot_revision=1,
            profile_ref="pilot0-free-v1",
            profile_revision=1,
            observed_at=200,
            complete=1,
            total_json=EMPTY_RESOURCES,
            available_json=EMPTY_RESOURCES,
            shared_observed_json=EMPTY_RESOURCES,
        )
        | changes
    )


def source_observation(**changes):
    return (
        dict(
            operator_id=OPERATOR_ID,
            workspace_id=WORKSPACE_ID,
            access_epoch=1,
            effective_enabled=1,
            usage_bytes=1234,
            usable_bytes=FREE_V1_USABLE_BYTES,
            source_revision=3,
            observed_at=200,
            checked_at=210,
            freshness_state="known",
            revision=1,
        )
        | changes
    )


def test_h04_tables_have_indexed_restrict_foreign_keys(admin_db):
    with write_tx(admin_db) as connection:
        validate_schema(connection, HostedStore.ADMIN, application_directory=APPLICATION)
        inspector = sa.inspect(connection)
        for table in ("capacity_snapshots", "capacity_commitments", "operator_source_observations"):
            keys = [tuple(item["column_names"]) for item in inspector.get_indexes(table)]
            keys += [
                tuple(item["column_names"]) for item in inspector.get_unique_constraints(table)
            ]
            pk = tuple(inspector.get_pk_constraint(table)["constrained_columns"])
            if pk:
                keys.append(pk)
            foreign_keys = inspector.get_foreign_keys(table)
            assert foreign_keys
            for foreign in foreign_keys:
                assert foreign["options"]["ondelete"] == "RESTRICT"
                columns = tuple(foreign["constrained_columns"])
                assert any(key[: len(columns)] == columns for key in keys)


def test_free_v1_policy_bootstrap_is_idempotent_and_deterministic(admin_db):
    with write_tx(admin_db) as connection:
        bind_default_deployment(connection)
        created_at = 500
        policy, inserted = bootstrap_free_v1_policy(
            connection, created_at=created_at, application_directory=APPLICATION
        )
        assert inserted is True
        assert policy.policy_id == free_v1_policy_id(DEPLOYMENT_ID)
        assert policy.plan_code == FREE_V1_PLAN_CODE
        assert policy.policy_version == FREE_V1_POLICY_VERSION
        assert policy.usable_bytes == FREE_V1_USABLE_BYTES
        assert policy.backup_interval_seconds == FREE_V1_BACKUP_INTERVAL_SECONDS
        assert policy.retained_nightly_points == FREE_V1_RETAINED_NIGHTLY_POINTS
        assert policy.keep_warm == FREE_V1_KEEP_WARM
        assert policy.created_at == created_at

        again, inserted_again = bootstrap_free_v1_policy(
            connection, created_at=999, application_directory=APPLICATION
        )
        assert inserted_again is False
        assert again == policy


def test_free_v1_policy_bootstrap_rejects_unbound_deployment_or_drift(admin_db):
    with write_tx(admin_db) as connection:
        with pytest.raises(HostedSchemaError):
            bootstrap_free_v1_policy(connection, created_at=500, application_directory=APPLICATION)

        bind_default_deployment(connection)
        policy, inserted = bootstrap_free_v1_policy(
            connection,
            created_at=500,
            policy_id=CUSTOM_POLICY_ID,
            application_directory=APPLICATION,
        )
        assert inserted is True
        assert policy.policy_id == CUSTOM_POLICY_ID

        # Mismatched expected policy_id fails closed.
        with pytest.raises(HostedSchemaError):
            bootstrap_free_v1_policy(connection, created_at=500, application_directory=APPLICATION)

    # Drifted usable_bytes row fails closed.
    with write_tx(admin_db) as connection:
        bind_default_deployment(connection)
        insert(
            connection,
            "storage_policies",
            dict(
                policy_id=free_v1_policy_id(DEPLOYMENT_ID),
                plan_code="free",
                policy_version=1,
                usable_bytes=10_000_000,
                backup_interval_seconds=86_400,
                retained_nightly_points=7,
                keep_warm=1,
                created_at=500,
            ),
        )
        with pytest.raises(HostedSchemaError):
            bootstrap_free_v1_policy(connection, created_at=500, application_directory=APPLICATION)


def test_free_v1_policy_bootstrap_rollback_leaves_no_row(admin_db):
    with write_tx(admin_db) as connection:
        bind_default_deployment(connection)
        _, inserted = bootstrap_free_v1_policy(
            connection, created_at=500, application_directory=APPLICATION
        )
        assert inserted is True
    with write_tx(admin_db) as connection:
        count = connection.execute(text("SELECT count(*) FROM main.storage_policies")).scalar_one()
        assert count == 0


def test_free_v1_policy_bootstrap_rejects_invalid_inputs(admin_db):
    with write_tx(admin_db) as connection:
        bind_default_deployment(connection)
        with pytest.raises(ValidationError):
            bootstrap_free_v1_policy(
                connection,
                created_at=-1,
                application_directory=APPLICATION,
            )
        with pytest.raises(ValidationError):
            bootstrap_free_v1_policy(
                connection,
                created_at=100,
                policy_id="not-a-uuid",
                application_directory=APPLICATION,
            )


def test_operations_kind_accepts_h04_kinds_and_rejects_unknown(admin_db):
    with write_tx(admin_db) as connection:
        bind_default_deployment(connection)
        policy, _ = bootstrap_free_v1_policy(
            connection, created_at=100, application_directory=APPLICATION
        )
        seed_operator(connection, policy_id=policy.policy_id)
        for index, kind in enumerate(("reissue_invitation", "refresh_source"), start=1):
            insert(
                connection,
                "operations",
                dict(
                    operation_id=f"00000000-0000-4000-8000-00000000010{index}",
                    operator_id=OPERATOR_ID,
                    component_deployment_id=None,
                    kind=kind,
                    idempotency_key=f"key-{kind}",
                    request_hash="a" * 64,
                    request_json="{}",
                    system_actor="admin-control",
                    expected_revision=1,
                    access_epoch=1,
                    state="pending",
                    created_at=100,
                    updated_at=100,
                    revision=1,
                ),
            )
        with pytest.raises(IntegrityError):
            insert(
                connection,
                "operations",
                dict(
                    operation_id=OTHER_ID,
                    operator_id=OPERATOR_ID,
                    component_deployment_id=None,
                    kind="create_assignment",
                    idempotency_key="bad-kind",
                    request_hash="a" * 64,
                    request_json="{}",
                    system_actor="admin-control",
                    expected_revision=1,
                    access_epoch=1,
                    state="pending",
                    created_at=100,
                    updated_at=100,
                    revision=1,
                ),
            )


def test_capacity_tables_constraints_and_immutability(admin_db):
    with write_tx(admin_db) as connection:
        bind_default_deployment(connection)
        policy, _ = bootstrap_free_v1_policy(
            connection, created_at=100, application_directory=APPLICATION
        )
        seed_operator(connection, policy_id=policy.policy_id)
        insert(connection, "capacity_profiles", capacity_profile())
        insert(connection, "capacity_snapshots", capacity_snapshot())

        # capacity_profiles is immutable (no UPDATE, DELETE, or INSERT OR REPLACE).
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "UPDATE capacity_profiles SET maximum_observation_age_ms = 1 "
                    "WHERE profile_ref = 'pilot0-free-v1'"
                )
            )
        with pytest.raises(IntegrityError):
            connection.execute(
                text("DELETE FROM capacity_profiles WHERE profile_ref = 'pilot0-free-v1'")
            )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT OR REPLACE INTO capacity_profiles ("
                    "profile_ref, profile_revision, measurement_sha256, source_sha256, "
                    "runtime_policy_sha256, maximum_observation_age_ms, shared_reserve_json, "
                    "recovery_reserve_json, free_budget_json, created_at"
                    ") VALUES ("
                    ":profile_ref, :profile_revision, :measurement_sha256, :source_sha256, "
                    ":runtime_policy_sha256, :maximum_observation_age_ms, :shared_reserve_json, "
                    ":recovery_reserve_json, :free_budget_json, :created_at"
                    ")"
                ),
                capacity_profile(created_at=999),
            )

        # Singleton check on capacity_snapshots.
        with pytest.raises(IntegrityError):
            insert(connection, "capacity_snapshots", capacity_snapshot(id=2))

        # All five commitment states are accepted.
        insert(
            connection,
            "capacity_commitments",
            dict(
                operator_id=OPERATOR_ID,
                workspace_id=WORKSPACE_ID,
                state="pending",
                reserved_json=EMPTY_RESOURCES,
                observed_json=EMPTY_RESOURCES,
                updated_at=200,
                revision=1,
            ),
        )
        for state in ("active", "retained", "unknown", "cleanup_pending"):
            connection.execute(
                text(
                    "UPDATE capacity_commitments SET state = :state, revision = revision + 1 "
                    "WHERE operator_id = :id"
                ),
                {"state": state, "id": OPERATOR_ID},
            )
        with pytest.raises(IntegrityError):
            connection.execute(
                text("UPDATE capacity_commitments SET state = 'released' WHERE operator_id = :id"),
                {"id": OPERATOR_ID},
            )


@pytest.mark.parametrize(
    "changes",
    [
        {"freshness_state": "known", "effective_enabled": None},
        {"freshness_state": "stale", "usage_bytes": None},
        {"freshness_state": "known", "checked_at": 199, "observed_at": 200},
        {"freshness_state": "unknown", "effective_enabled": 1},
        {
            "freshness_state": "unavailable",
            "effective_enabled": None,
            "usage_bytes": 0,
            "usable_bytes": None,
            "source_revision": None,
            "observed_at": None,
        },
        {"freshness_state": "invalid_state"},
    ],
)
def test_operator_source_observations_rejects_invalid_freshness_combinations(admin_db, changes):
    with write_tx(admin_db) as connection:
        bind_default_deployment(connection)
        policy, _ = bootstrap_free_v1_policy(
            connection, created_at=100, application_directory=APPLICATION
        )
        seed_operator(connection, policy_id=policy.policy_id)
        with pytest.raises(IntegrityError):
            insert(connection, "operator_source_observations", source_observation(**changes))


def test_operator_source_observations_accepts_known_and_unavailable(admin_db):
    with write_tx(admin_db) as connection:
        bind_default_deployment(connection)
        policy, _ = bootstrap_free_v1_policy(
            connection, created_at=100, application_directory=APPLICATION
        )
        seed_operator(connection, policy_id=policy.policy_id)
        insert(connection, "operator_source_observations", source_observation())
        connection.execute(
            text(
                "UPDATE operator_source_observations SET "
                "freshness_state = 'unavailable', effective_enabled = NULL, "
                "usage_bytes = NULL, usable_bytes = NULL, source_revision = NULL, "
                "observed_at = NULL, checked_at = 300, revision = 2 "
                "WHERE operator_id = :id"
            ),
            {"id": OPERATOR_ID},
        )

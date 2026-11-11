"""H02.2 real owning resources: schema/transaction/path tests, not native readiness."""

from contextlib import contextmanager
from pathlib import Path
import os
import re
import shutil
import sqlite3

from alembic import command
import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import IntegrityError

from app.modules.host_agent.infrastructure.schema_store import HostMetadata, bind_host
from app.modules.hosted_admin.infrastructure.schema_store import DeploymentMetadata, bind_deployment
from app.platform import hosted_schema
from app.platform.hosted_schema import (
    HostedSchemaError,
    InitializationResult,
    create_schema,
    initialize_store,
    validate_schema,
)
from app.platform.schema_resources import HostedStore, SchemaResourcesUnavailable, resource_config

APPLICATION = Path(__file__).resolve().parents[5]
STORES = (HostedStore.ADMIN, HostedStore.HOST_INVENTORY)
ADMIN = HostedStore.ADMIN
INVENTORY = HostedStore.HOST_INVENTORY
FIRST = "00000000-0000-4000-8000-000000000001"
SECOND = "00000000-0000-4000-8000-000000000002"
THIRD = "00000000-0000-4000-8000-000000000003"


@pytest.fixture
def private(tmp_path):
    path = tmp_path.resolve() / "private"
    path.mkdir(mode=0o700)
    return path


@contextmanager
def connect(path):
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            yield connection
            connection.rollback()
    finally:
        engine.dispose()


def initialized(private, store):
    target = private / f"{store}.sqlite"
    assert (
        initialize_store(store, target, application_directory=APPLICATION)
        == InitializationResult.INITIALIZED
    )
    return target


def insert(connection, table, values):
    names = ",".join(values)
    bindings = ",".join(":" + name for name in values)
    connection.execute(text(f"INSERT INTO {table} ({names}) VALUES ({bindings})"), values)


def seed_admin(connection):
    assert bind_deployment(connection, deployment(), application_directory=APPLICATION)
    insert(
        connection,
        "storage_policies",
        dict(
            policy_id=FIRST,
            plan_code="free",
            policy_version=1,
            usable_bytes=50000000,
            backup_interval_seconds=86400,
            retained_nightly_points=7,
            keep_warm=1,
            created_at=1,
        ),
    )
    insert(connection, "operators", operator())
    insert(
        connection,
        "qualified_releases",
        dict(
            release_id=FIRST,
            component="operator",
            artifact_kind="oci_image",
            artifact_digest="a" * 64,
            artifact_ref="synthetic-artifact",
            compatibility_manifest_ref="synthetic-manifest",
            compatibility_manifest_sha256="b" * 64,
            business_schema_revision="business_1",
            access_schema_revision="access_1",
            recovery_schema_revision="recovery_1",
            qualification_ref="synthetic-only-not-qualified",
            state="qualified",
            qualified_at=1,
            revision=1,
        ),
    )
    insert(connection, "component_deployments", assignment())


def operator(**changes):
    return (
        dict(
            operator_id=FIRST,
            workspace_id=SECOND,
            display_name="Synthetic Operator",
            invited_email="synthetic@example.invalid",
            email_key="provider:synthetic@example.invalid",
            workspace_slug="synthetic-operator",
            issuer="synthetic-provider",
            desired_policy_id=FIRST,
            desired_access="enabled",
            setup_state="pending",
            support_contact="support@example.invalid",
            access_epoch=1,
            revision=1,
            created_at=1,
            updated_at=1,
        )
        | changes
    )


def assignment(**changes):
    return (
        dict(
            component_deployment_id=FIRST,
            deployment_id=FIRST,
            component="operator",
            scope_kind="workspace",
            operator_id=FIRST,
            workspace_id=SECOND,
            desired_release_id=FIRST,
            state="pending",
            revision=1,
        )
        | changes
    )


def operation(**changes):
    return (
        dict(
            operation_id=FIRST,
            operator_id=FIRST,
            component_deployment_id=FIRST,
            kind="provision",
            idempotency_key="synthetic-key",
            request_hash="a" * 64,
            request_json="{}",
            system_actor="synthetic-bootstrap",
            expected_revision=1,
            access_epoch=1,
            state="pending",
            created_at=1,
            updated_at=1,
            revision=1,
        )
        | changes
    )


def deployment(**changes):
    return DeploymentMetadata(
        **(
            dict(
                deployment_id=FIRST,
                public_base_domain="example.invalid",
                login_origin="https://login.example.invalid",
                registry_generation=1,
                created_at=1,
            )
            | changes
        )
    )


def host(**changes):
    return HostMetadata(
        **(
            dict(
                host_id=FIRST,
                deployment_id=SECOND,
                filesystem_identity="synthetic-filesystem",
                agent_contract_version="synthetic-agent-v1",
                created_at=1,
            )
            | changes
        )
    )


def seed_inventory(connection):
    assert bind_host(connection, host(), application_directory=APPLICATION)
    insert(connection, "operator_principals", principal())
    insert(connection, "resource_bindings", binding())
    insert(connection, "host_receipts", receipt())


def principal(**changes):
    return (
        dict(
            operator_id=FIRST,
            workspace_id=SECOND,
            host_uid=100000,
            host_gid=100000,
            assigned_at=1,
            revision=1,
        )
        | changes
    )


def binding(**changes):
    return (
        dict(
            binding_id=FIRST,
            operator_id=FIRST,
            workspace_id=SECOND,
            resource_generation=1,
            role="active",
            workspace_relative_ref="workspace-v1",
            access_relative_ref="control-v1",
            scratch_relative_ref="scratch-v1",
            image_digest="a" * 64,
            workspace_byte_ceiling=100000000,
            workspace_inode_ceiling=1000,
            control_byte_ceiling=1000000,
            control_inode_ceiling=100,
            scratch_byte_ceiling=1000000,
            scratch_inode_ceiling=100,
            state="allocated",
            provision_operation_id=FIRST,
            revision=1,
        )
        | changes
    )


def receipt(**changes):
    return (
        dict(
            operation_id=FIRST,
            parent_operation_id=SECOND,
            idempotency_key="synthetic-child",
            request_hash="a" * 64,
            request_json="{}",
            binding_id=FIRST,
            access_epoch=1,
            kind="prepare_resources",
            state="pending",
            recorded_at=1,
            revision=1,
        )
        | changes
    )


def ingress(**changes):
    return (
        dict(
            operator_id=FIRST,
            workspace_id=SECOND,
            binding_id=FIRST,
            resource_generation=1,
            public_origin="https://synthetic.example.invalid",
            access_epoch=1,
            desired_state="held",
            operation_id=FIRST,
            verified_state="unknown",
            updated_at=1,
            revision=1,
        )
        | changes
    )


@pytest.mark.parametrize("store", STORES)
def test_fresh_matching_reinit_is_read_only_and_never_seeds_authority(private, store, monkeypatch):
    monkeypatch.chdir(private)
    target = initialized(private, store)
    before = target.read_bytes(), target.stat().st_mtime_ns, sorted(private.iterdir())
    assert (
        initialize_store(store, target, application_directory=APPLICATION)
        == InitializationResult.ALREADY_INITIALIZED
    )
    assert (target.read_bytes(), target.stat().st_mtime_ns, sorted(private.iterdir())) == before
    with connect(target) as connection:
        tables = (
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name!='alembic_version'"
            )
            .scalars()
            .all()
        )
        assert all(
            connection.exec_driver_sql(f"SELECT count(*) FROM {name}").scalar_one() == 0
            for name in tables
        )
        assert validate_schema(connection, store, application_directory=APPLICATION)


@pytest.mark.parametrize("store", STORES)
def test_table_column_closure_matches_owning_dictionary(private, store):
    names = (
        ("admin-registry", "admin-identity", "admin-operations")
        if store == ADMIN
        else ("host-inventory",)
    )
    expected = {}
    table = None
    for name in names:
        for line in (APPLICATION.parent / "docs/database" / f"{name}.md").read_text().splitlines():
            heading = re.match(r"### `([^`]+)`", line)
            if heading:
                table = heading[1]
                expected[table] = set()
            column = re.match(r"\| `([^`]+)` \|", line)
            if column and table:
                expected[table].add(column[1])
    with connect(initialized(private, store)) as connection:
        actual = {
            name: {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({name})")}
            for name in expected
        }
        assert actual == expected


@pytest.mark.parametrize("store", STORES)
@pytest.mark.parametrize(
    "tamper",
    [
        "empty",
        "partial",
        "version_only",
        "wrong_revision",
        "extra_table",
        "missing_index",
        "missing_trigger",
    ],
)
def test_invalid_existing_store_is_preserved(private, store, tamper):
    target = initialized(private, store)
    if tamper == "empty":
        target.write_bytes(b"")
    elif tamper == "partial":
        target.write_bytes(b"interrupted initialization evidence")
    else:
        with sqlite3.connect(target) as connection:
            if tamper == "version_only":
                tables = connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table' AND name!='alembic_version'"
                ).fetchall()
                for (name,) in tables:
                    connection.execute(f"DROP TABLE {name}")
            elif tamper == "wrong_revision":
                connection.execute("UPDATE alembic_version SET version_num='wrong_revision'")
            elif tamper == "extra_table":
                connection.execute("CREATE TABLE unexpected (id INTEGER)")
            else:
                kind = "index" if tamper == "missing_index" else "trigger"
                name = connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type=? AND sql IS NOT NULL", (kind,)
                ).fetchone()[0]
                connection.execute(f"DROP {kind} {name}")
    before = target.read_bytes()
    with pytest.raises(HostedSchemaError):
        initialize_store(store, target, application_directory=APPLICATION)
    assert target.read_bytes() == before


@pytest.mark.parametrize("store", STORES)
def test_wrong_owning_store_cannot_be_relabelled(private, store):
    target = initialized(private, INVENTORY if store == ADMIN else ADMIN)
    before = target.read_bytes()
    with pytest.raises(HostedSchemaError):
        initialize_store(store, target, application_directory=APPLICATION)
    assert target.read_bytes() == before


@pytest.mark.parametrize("store", STORES)
@pytest.mark.parametrize("command_name", ["upgrade", "stamp", "ensure_version"])
@pytest.mark.parametrize("offline", [True, False])
def test_raw_alembic_cannot_bypass_owning_runner(private, store, command_name, offline):
    config = resource_config(store, application_directory=APPLICATION)
    config.set_main_option("sqlalchemy.url", f"sqlite:///{private / 'never.sqlite'}")
    with pytest.raises(SchemaResourcesUnavailable):
        if command_name == "ensure_version":
            command.ensure_version(config, sql=offline)
        else:
            getattr(command, command_name)(config, "head", sql=offline)
    assert list(private.iterdir()) == []


@pytest.mark.parametrize("store", STORES)
def test_caller_owned_transaction_rolls_back_ddl_without_commit_or_close(private, store):
    target = private / "caller.sqlite"
    with connect(target) as connection:
        create_schema(connection, store, application_directory=APPLICATION)
        assert connection.in_transaction()
        connection.rollback()
        assert not connection.closed
        assert connection.exec_driver_sql("SELECT name FROM sqlite_schema").all() == []


@pytest.mark.parametrize("store", STORES)
def test_commit_failure_never_reports_ready(private, store):
    def fail_commit(connection):
        raise RuntimeError("synthetic commit failure")

    event.listen(Engine, "commit", fail_commit)
    target = private / "failed.sqlite"
    try:
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            initialize_store(store, target, application_directory=APPLICATION)
    finally:
        event.remove(Engine, "commit", fail_commit)
    assert target.exists()
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT name FROM sqlite_schema").fetchall() == []
    with pytest.raises(HostedSchemaError):
        initialize_store(store, target, application_directory=APPLICATION)


@pytest.mark.parametrize("store", STORES)
def test_missing_baseline_fails_before_destination_creation(private, store, tmp_path):
    app = tmp_path / "installed"
    shutil.copytree(APPLICATION / "database", app / "database")
    for p in (app / "database" / f"{store}-migrations/versions").glob("*.py"):
        p.unlink()
    with pytest.raises(SchemaResourcesUnavailable):
        initialize_store(store, private / "never.sqlite", application_directory=app)
    assert list(private.iterdir()) == []


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory", "public_file"])
def test_nonprivate_or_nonregular_destination_rejected_without_effect(private, kind):
    target = private / "unsafe.sqlite"
    if kind in {"symlink", "hardlink"}:
        other = private / "other.sqlite"
        other.touch(mode=0o600)
        target.symlink_to(other) if kind == "symlink" else target.hardlink_to(other)
    elif kind == "fifo":
        os.mkfifo(target, 0o600)
    elif kind == "directory":
        target.mkdir(mode=0o700)
    else:
        target.touch(mode=0o644)
    with pytest.raises(HostedSchemaError):
        initialize_store(ADMIN, target, application_directory=APPLICATION)


@pytest.mark.parametrize("store", STORES)
def test_bound_metadata_retry_mismatch_and_rollback(private, store):
    target = initialized(private, store)
    metadata, binder = (deployment(), bind_deployment) if store == ADMIN else (host(), bind_host)
    table = "control_meta" if store == ADMIN else "host_identity"
    with connect(target) as connection:
        assert binder(connection, metadata, application_directory=APPLICATION)
        assert not binder(connection, metadata, application_directory=APPLICATION)
        changed = metadata.model_copy(update={"deployment_id": THIRD})
        with pytest.raises(HostedSchemaError):
            binder(connection, changed, application_directory=APPLICATION)
        assert connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one() == 1
    with connect(target) as connection:
        assert connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one() == 0


@pytest.mark.parametrize("store", STORES)
def test_connection_with_attachment_or_disabled_foreign_keys_rejected(private, store):
    target = initialized(private, store)
    with connect(target) as connection:
        connection.exec_driver_sql("ATTACH ':memory:' AS another_authority")
        with pytest.raises(HostedSchemaError):
            validate_schema(connection, store, application_directory=APPLICATION)
    engine = create_engine(f"sqlite:///{target}")
    try:
        with engine.connect() as connection:
            with pytest.raises(HostedSchemaError):
                validate_schema(connection, store, application_directory=APPLICATION)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "changes",
    [
        {"workspace_id": THIRD},
        {"component": "admin"},
        {"scope_kind": "deployment"},
        {"state": "applied"},
        {"desired_release_id": THIRD},
    ],
)
def test_assignment_scope_component_fk_and_applied_checks(private, changes):
    with connect(initialized(private, ADMIN)) as connection:
        seed_admin(connection)
        connection.exec_driver_sql("DELETE FROM component_deployments")
        with pytest.raises(IntegrityError):
            insert(
                connection,
                "component_deployments",
                assignment(component_deployment_id=SECOND, **changes),
            )


@pytest.mark.parametrize(
    "changes",
    [
        {"setup_state": "active"},
        {"setup_state": "retired"},
        {"updated_at": 0},
        {"workspace_slug": "admin"},
        {"workspace_slug": "Uppercase"},
        {"access_epoch": 0},
        {"operator_id": "INVALID"},
        {"operator_id": "ABCDEFAB-CDEF-4ABC-8ABC-ABCDEFABCDEF"},
    ],
)
def test_operator_state_and_value_constraints(private, changes):
    with connect(initialized(private, ADMIN)) as connection:
        seed_admin(connection)
        values = operator(
            **(
                dict(
                    operator_id=THIRD,
                    workspace_id=THIRD,
                    workspace_slug="other",
                    email_key="other@example.invalid",
                )
                | changes
            )
        )
        with pytest.raises(IntegrityError):
            insert(connection, "operators", values)


@pytest.mark.parametrize(
    "changes",
    [
        {"system_actor": None},
        {"actor_principal_id": THIRD},
        {"state": "succeeded"},
        {"state": "failed"},
        {"kind": "backup"},
        {"request_hash": "A" * 64},
        {"request_json": "[]"},
        {"request_json": '{"text":"' + "x" * 16384 + '"}'},
    ],
)
def test_operation_actor_states_and_bounded_objects(private, changes):
    with connect(initialized(private, ADMIN)) as connection:
        seed_admin(connection)
        insert(
            connection,
            "admin_principals",
            dict(
                principal_id=THIRD,
                issuer="synthetic-provider",
                subject="synthetic-admin",
                session_generation=1,
                revision=1,
                created_at=1,
            ),
        )
        with pytest.raises(IntegrityError):
            insert(connection, "operations", operation(**changes))


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE operations SET request_json='{\"changed\":true}'",
        "DELETE FROM operations",
        "UPDATE storage_policies SET usable_bytes=1",
        "UPDATE operation_events SET safe_summary='changed'",
        "DELETE FROM admin_audit",
    ],
)
def test_original_intent_and_append_only_evidence_are_retained(private, sql):
    with connect(initialized(private, ADMIN)) as connection:
        seed_admin(connection)
        insert(connection, "operations", operation())
        insert(
            connection,
            "operation_events",
            dict(
                operation_id=FIRST,
                sequence=1,
                event_code="admitted",
                safe_summary="Synthetic admission",
                recorded_at=1,
            ),
        )
        insert(
            connection,
            "admin_audit",
            dict(
                audit_id=FIRST,
                actor_ref="synthetic-system",
                action="admitted",
                operator_id=FIRST,
                operation_id=FIRST,
                recorded_at=1,
                safe_facts_json="{}",
            ),
        )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(sql)


def test_terminal_result_kind_key_and_assignment_operation_cycle(private):
    with connect(initialized(private, ADMIN)) as connection:
        seed_admin(connection)
        insert(connection, "operations", operation())
        connection.execute(text("UPDATE component_deployments SET operation_id=:id"), {"id": FIRST})
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        with pytest.raises(IntegrityError):
            insert(connection, "operations", operation(operation_id=SECOND))
        connection.exec_driver_sql(
            "UPDATE operations SET state='succeeded',result_json='{}',revision=2"
        )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql("UPDATE operations SET result_json='{\"rewritten\":true}'")


def test_live_invitation_uniqueness_and_claim_fields(private):
    with connect(initialized(private, ADMIN)) as connection:
        seed_admin(connection)
        values = dict(
            invitation_id=FIRST,
            operator_id=FIRST,
            token_hash="a" * 64,
            email_key="synthetic@example.invalid",
            assignment_revision=1,
            access_epoch=1,
            state="sent",
            expires_at=100,
            created_at=1,
            revision=1,
        )
        insert(connection, "invitations", values)
        with pytest.raises(IntegrityError):
            insert(
                connection, "invitations", values | dict(invitation_id=SECOND, token_hash="b" * 64)
            )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql("UPDATE invitations SET state='claimed'")
        connection.exec_driver_sql("UPDATE invitations SET state='revoked'")
        insert(connection, "invitations", values | dict(invitation_id=SECOND, token_hash="b" * 64))


@pytest.mark.parametrize(
    "changes",
    [
        {"host_uid": 0},
        {"host_gid": 4294967295},
        {"retired_at": 0},
        {"cleanup_verified_at": 2},
    ],
)
def test_principal_identity_retirement_and_cleanup(private, changes):
    with connect(initialized(private, INVENTORY)) as connection:
        seed_inventory(connection)
        with pytest.raises(IntegrityError):
            insert(
                connection,
                "operator_principals",
                principal(
                    **(
                        dict(
                            operator_id=THIRD, workspace_id=THIRD, host_uid=100001, host_gid=100001
                        )
                        | changes
                    )
                ),
            )


@pytest.mark.parametrize(
    "changes",
    [
        {"workspace_id": FIRST},
        {"role": "unregistered"},
        {"workspace_byte_ceiling": 0},
        {"scratch_inode_ceiling": -1},
        {"workspace_relative_ref": "../escape"},
        {"image_digest": "latest"},
    ],
)
def test_binding_scope_limits_and_refs(private, changes):
    with connect(initialized(private, INVENTORY)) as connection:
        seed_inventory(connection)
        values = binding(
            **(
                dict(
                    binding_id=THIRD,
                    resource_generation=2,
                    role="retained",
                    workspace_relative_ref="workspace-v2",
                    access_relative_ref="control-v2",
                    scratch_relative_ref="scratch-v2",
                )
                | changes
            )
        )
        with pytest.raises(IntegrityError):
            insert(connection, "resource_bindings", values)


def test_unique_principals_active_bindings_and_project_allocations(private):
    with connect(initialized(private, INVENTORY)) as connection:
        seed_inventory(connection)
        with pytest.raises(IntegrityError):
            insert(
                connection, "operator_principals", principal(operator_id=THIRD, workspace_id=THIRD)
            )
        with pytest.raises(IntegrityError):
            insert(
                connection,
                "resource_bindings",
                binding(
                    binding_id=THIRD,
                    resource_generation=2,
                    workspace_relative_ref="workspace-v2",
                    access_relative_ref="control-v2",
                    scratch_relative_ref="scratch-v2",
                ),
            )
        values = dict(
            project_id=1,
            binding_id=FIRST,
            tree_kind="workspace",
            filesystem_identity="synthetic-filesystem",
            assigned_at=1,
        )
        insert(connection, "project_assignments", values)
        for changes in [dict(tree_kind="control"), dict(project_id=2)]:
            with pytest.raises(IntegrityError):
                insert(connection, "project_assignments", values | changes)
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql("DELETE FROM project_assignments")
        connection.exec_driver_sql("UPDATE resource_bindings SET state='retired'")
        connection.exec_driver_sql(
            "UPDATE operator_principals SET retired_at=2,cleanup_verified_at=3"
        )
        connection.exec_driver_sql("DELETE FROM project_assignments")


@pytest.mark.parametrize(
    "changes",
    [
        {"desired_state": "eligible"},
        {"verified_state": "held"},
        {"verified_revision": 1},
        {"operation_id": THIRD},
        {"resource_generation": 2},
        {"public_origin": "http://synthetic.example.invalid"},
        {"public_origin": "https://synthetic.example.invalid:443"},
        {"public_origin": "https://synthetic.example.invalid/path"},
    ],
)
def test_initial_ingress_requires_held_registered_consistent_observation(private, changes):
    with connect(initialized(private, INVENTORY)) as connection:
        seed_inventory(connection)
        with pytest.raises(IntegrityError):
            insert(connection, "ingress_bindings", ingress(**changes))


def test_ingress_monotonic_fences_and_pending_observation(private):
    with connect(initialized(private, INVENTORY)) as connection:
        seed_inventory(connection)
        insert(connection, "ingress_bindings", ingress())
        connection.exec_driver_sql(
            "UPDATE ingress_bindings SET access_epoch=2,desired_state='blocked',revision=2,"
            "updated_at=2,verified_state='blocked',verified_revision=2,"
            "verification_ref='synthetic-deny-proof',verified_at=2"
        )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql("UPDATE ingress_bindings SET access_epoch=1,revision=3")
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql("UPDATE ingress_bindings SET verified_revision=4,revision=3")
        connection.exec_driver_sql("UPDATE ingress_bindings SET revision=3,updated_at=3")
        row = connection.exec_driver_sql(
            "SELECT revision,verified_revision FROM ingress_bindings"
        ).one()
        assert row.revision > row.verified_revision


def test_host_receipt_original_intent_key_and_terminal_result(private):
    with connect(initialized(private, INVENTORY)) as connection:
        seed_inventory(connection)
        with pytest.raises(IntegrityError):
            insert(connection, "host_receipts", receipt(operation_id=SECOND))
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql("UPDATE host_receipts SET request_json='{\"changed\":true}'")
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql("UPDATE host_receipts SET state='applied'")
        connection.exec_driver_sql(
            "UPDATE host_receipts SET state='applied',observed_json='{}',revision=2"
        )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "UPDATE host_receipts SET observed_json='{\"rewritten\":true}'"
            )


@pytest.mark.parametrize("store", STORES)
def test_validation_query_budget_and_snapshot_backup(private, store):
    target = initialized(private, store)
    with connect(target) as connection:
        seed_admin(connection) if store == ADMIN else seed_inventory(connection)
        connection.commit()
        connection.exec_driver_sql("BEGIN")
        statements = []
        event.listen(connection, "before_cursor_execute", lambda *args: statements.append(args[2]))
        validate_schema(connection, store, application_directory=APPLICATION)
        max_statements = 6
        assert len(statements) <= max_statements
        assert not any("INSERT" in sql or "UPDATE" in sql or "CREATE" in sql for sql in statements)
    copy = private / "snapshot.sqlite"
    with sqlite3.connect(target) as source, sqlite3.connect(copy) as destination:
        source.backup(destination)
    with connect(copy) as connection:
        assert validate_schema(connection, store, application_directory=APPLICATION)
        table = "control_meta" if store == ADMIN else "host_identity"
        assert connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one() == 1


@pytest.mark.parametrize("store", STORES)
def test_failed_baseline_retains_reservation_and_rolls_back_all_ddl(private, store, monkeypatch):
    original = hosted_schema._run_baseline

    def fail_after_baseline(connection, config, selected):
        original(connection, config, selected)
        if any(
            row[2] for row in connection.exec_driver_sql("PRAGMA database_list") if row[1] == "main"
        ):
            raise RuntimeError("synthetic baseline failure")

    monkeypatch.setattr(hosted_schema, "_run_baseline", fail_after_baseline)
    path = private / "interrupted.sqlite"
    with pytest.raises(RuntimeError, match="synthetic baseline failure"):
        initialize_store(store, path, application_directory=APPLICATION)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT name FROM sqlite_schema").fetchall() == []


@pytest.mark.parametrize("store", STORES)
def test_foreign_key_tampering_is_not_accepted_as_matching(private, store):
    path = initialized(private, store)
    with sqlite3.connect(path) as connection:
        if store == ADMIN:
            connection.execute(
                "INSERT INTO admin_sessions VALUES (?,?,?,?,?,?,?,?,?)",
                ("a" * 64, FIRST, "b" * 64, 1, 1, 1, 100, 1, None),
            )
        else:
            connection.execute(
                "INSERT INTO project_assignments VALUES (?,?,?,?,?)",
                (1, FIRST, "workspace", "synthetic-filesystem", 1),
            )
    before = path.read_bytes()
    with pytest.raises(HostedSchemaError):
        initialize_store(store, path, application_directory=APPLICATION)
    assert path.read_bytes() == before


@pytest.mark.parametrize("store", STORES)
def test_replace_cannot_rewrite_original_evidence(private, store):
    with connect(initialized(private, store)) as connection:
        if store == ADMIN:
            seed_admin(connection)
            insert(connection, "operations", operation())
            statement = "INSERT OR REPLACE INTO operations SELECT * FROM operations"
        else:
            seed_inventory(connection)
            insert(connection, "ingress_bindings", ingress())
            statement = "INSERT OR REPLACE INTO ingress_bindings SELECT * FROM ingress_bindings"
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(statement)


def test_nonprivate_parent_never_reserves_destination(private):
    private.chmod(0o755)
    with pytest.raises(HostedSchemaError):
        initialize_store(ADMIN, private / "never.sqlite", application_directory=APPLICATION)
    assert list(private.iterdir()) == []


def test_symlink_parent_cannot_redirect_creation(private):
    link = private.parent / "private-link"
    link.symlink_to(private, target_is_directory=True)
    with pytest.raises(HostedSchemaError):
        initialize_store(ADMIN, link / "never.sqlite", application_directory=APPLICATION)
    assert list(private.iterdir()) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"public_base_domain": "EXAMPLE.invalid"},
        {"public_base_domain": "-invalid.example"},
        {"login_origin": "http://login.example.invalid"},
        {"login_origin": "https://login.example.invalid:443"},
        {"login_origin": "https://login.other.invalid"},
        {"login_origin": "https://login.example.invalid/path"},
    ],
)
def test_protected_deployment_rejects_noncanonical_origins(changes):
    with pytest.raises(ValidationError):
        deployment(**changes)


@pytest.mark.parametrize("store", STORES)
def test_missing_common_definitions_and_redirected_resource_paths_fail_before_creation(
    private, store, tmp_path
):
    installed = tmp_path / "installed"
    shutil.copytree(APPLICATION / "database", installed / "database")
    helper = installed / "database/hosted_ddl.py"
    helper.unlink()
    with pytest.raises(SchemaResourcesUnavailable):
        initialize_store(store, private / "never.sqlite", application_directory=installed)
    shutil.copyfile(APPLICATION / "database/hosted_ddl.py", helper)
    ini = installed / "database" / f"{store}-migrations/alembic.ini"
    content = ini.read_text()
    ini.write_text(
        content.replace("script_location = %(here)s", "script_location = /tmp/untrusted")
    )
    with pytest.raises(SchemaResourcesUnavailable):
        initialize_store(store, private / "never.sqlite", application_directory=installed)
    assert list(private.iterdir()) == []


@pytest.mark.parametrize("store", STORES)
def test_sqlalchemy_autobegin_is_not_an_explicit_sqlite_write(private, store):
    engine = create_engine(f"sqlite:///{private / 'caller.sqlite'}")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            with pytest.raises(HostedSchemaError):
                create_schema(connection, store, application_directory=APPLICATION)
            assert not connection.closed
            assert connection.exec_driver_sql("SELECT name FROM sqlite_schema").all() == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("store", STORES)
def test_temp_objects_cannot_shadow_owning_schema(private, store):
    with connect(initialized(private, store)) as connection:
        connection.exec_driver_sql("CREATE TEMP TABLE alembic_version (version_num TEXT)")
        with pytest.raises(HostedSchemaError):
            validate_schema(connection, store, application_directory=APPLICATION)


@pytest.mark.parametrize("store", STORES)
def test_committed_binding_is_preserved_by_reinit(private, store):
    target = initialized(private, store)
    metadata, binder = (deployment(), bind_deployment) if store == ADMIN else (host(), bind_host)
    with connect(target) as connection:
        assert binder(connection, metadata, application_directory=APPLICATION)
        connection.commit()
    before = target.read_bytes(), target.stat().st_mtime_ns
    assert (
        initialize_store(store, target, application_directory=APPLICATION)
        == InitializationResult.ALREADY_INITIALIZED
    )
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
    with connect(target) as connection:
        assert not binder(connection, metadata, application_directory=APPLICATION)


@pytest.mark.parametrize("store", STORES)
@pytest.mark.parametrize("broken", ["empty_upgrade", "syntax"])
def test_incomplete_executable_resources_never_reserve_a_destination(
    private, store, broken, tmp_path
):
    installed = tmp_path / "installed"
    shutil.copytree(APPLICATION / "database", installed / "database")
    version = next((installed / "database" / f"{store}-migrations/versions").glob("*.py"))
    content = version.read_text()
    if broken == "syntax":
        content += "\ninvalid Python syntax!!!\n"
    else:
        content = content.replace("def upgrade():", "def incomplete_upgrade():")
        content += "\ndef upgrade():\n    pass\n"
    version.write_text(content)
    with pytest.raises(SchemaResourcesUnavailable):
        initialize_store(store, private / "never.sqlite", application_directory=installed)
    assert list(private.iterdir()) == []


@pytest.mark.parametrize("store", STORES)
def test_resource_directory_symlink_is_not_an_installation(private, store, tmp_path):
    installed = tmp_path / "installed"
    installed.mkdir()
    (installed / "database").symlink_to(APPLICATION / "database", target_is_directory=True)
    with pytest.raises(SchemaResourcesUnavailable):
        initialize_store(store, private / "never.sqlite", application_directory=installed)
    assert list(private.iterdir()) == []


@pytest.mark.parametrize("store", STORES)
@pytest.mark.parametrize("kind", ["table", "index", "trigger"])
def test_sqlite_lookalike_names_cannot_hide_schema_changes(private, store, kind):
    path = initialized(private, store)
    table = "control_meta" if store == ADMIN else "host_identity"
    definitions = {
        "table": "CREATE TABLE sqliteXunexpected(value TEXT)",
        "index": f"CREATE INDEX sqliteXunexpected ON {table}(created_at)",
        "trigger": f"CREATE TRIGGER sqliteXunexpected AFTER INSERT ON {table} BEGIN SELECT 1; END",
    }
    with sqlite3.connect(path) as connection:
        connection.execute(definitions[kind])
    before = path.read_bytes()
    with pytest.raises(HostedSchemaError):
        initialize_store(store, path, application_directory=APPLICATION)
    assert path.read_bytes() == before


@pytest.mark.parametrize("store", STORES)
def test_sqlite_lookalike_table_is_not_an_empty_creation_target(private, store):
    with connect(private / "nonempty.sqlite") as connection:
        connection.exec_driver_sql("CREATE TABLE sqliteXunexpected(value TEXT)")
        with pytest.raises(HostedSchemaError):
            create_schema(connection, store, application_directory=APPLICATION)
        assert connection.exec_driver_sql("SELECT name FROM sqlite_schema").scalars().all() == [
            "sqliteXunexpected"
        ]

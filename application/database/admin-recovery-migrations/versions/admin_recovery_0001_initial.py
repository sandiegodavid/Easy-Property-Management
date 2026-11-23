"""Complete greenfield Admin control-plane recovery baseline; independent of admin.sqlite."""

from pathlib import Path
import runpy

from alembic import op
import sqlalchemy as sa

revision = "admin_recovery_0001_initial"
down_revision = None
branch_labels = None
depends_on = None
TABLES = (
    "admin_recovery_meta",
    "control_recovery_operations",
    "control_recovery_points",
    "control_restore_operations",
    "control_backup_state",
    "control_recovery_audit",
)
helpers = runpy.run_path(str(Path(__file__).resolve().parents[2] / "hosted_ddl.py"))
f = helpers["field"]
c = helpers["choices"]
fk = helpers["foreign"]


def upgrade():
    _meta()
    _operations()
    _points()
    _restore_operations()
    _backup_state()
    _audit()
    _guards()


def _guard(table, name, condition):
    op.execute(
        f"CREATE TRIGGER {table}_{name} BEFORE UPDATE ON {table} "
        f"WHEN {condition} "
        "BEGIN SELECT RAISE(ABORT, 'invalid control recovery state transition'); END"
    )


def _meta():
    op.create_table(
        "admin_recovery_meta",
        f("id", "POSITIVE", primary=True),
        f("deployment_id", "ID", unique=True),
        f("incarnation_id", "ID", unique=True),
        f("recovery_authority_ref", "REF"),
        f("source_generation", "REV"),
        f("active_admin_resource_ref", "REF"),
        f("encryption_key_ref", "REF"),
        sa.Column("namespace_prefix", sa.Text(), nullable=False),
        f("created_at", "TIME"),
        f("revision", "REV"),
        sa.CheckConstraint("id=1", name="ck_singleton"),
        sa.CheckConstraint(
            "typeof(namespace_prefix)='text' AND length(namespace_prefix) BETWEEN 1 AND 256 "
            "AND substr(namespace_prefix,1,1) GLOB '[A-Za-z0-9]' "
            "AND namespace_prefix NOT GLOB '*[^A-Za-z0-9._:/-]*' "
            "AND instr(namespace_prefix,'..')=0",
            name="ck_namespace_prefix",
        ),
    )


def _operations():
    op.create_table(
        "control_recovery_operations",
        f("operation_id", "ID", primary=True),
        f("kind", "CODE"),
        f("idempotency_key", "KEY"),
        f("request_hash", "HASH"),
        f("request_json", "JSON"),
        f("actor_kind", "CODE"),
        f("actor_ref", "REF"),
        f("authorization_ref", "REF", nullable=True),
        f("authorized_at", "TIME", nullable=True),
        f("authorization_expires_at", "TIME", nullable=True),
        f("source_generation", "REV"),
        f("state", "CODE"),
        f("result_json", "JSON", nullable=True),
        f("error_code", "CODE", nullable=True),
        f("created_at", "TIME"),
        f("updated_at", "TIME"),
        f("revision", "REV"),
        sa.UniqueConstraint("kind", "idempotency_key"),
        c("kind", "backup restore"),
        c("actor_kind", "admin system"),
        c("state", "pending running needs_attention unknown succeeded failed"),
        sa.CheckConstraint(
            "(kind='backup' AND authorization_ref IS NULL AND authorized_at IS NULL "
            "AND authorization_expires_at IS NULL) "
            "OR (kind='restore' AND actor_kind='admin' AND authorization_ref IS NOT NULL "
            "AND authorized_at IS NOT NULL AND authorization_expires_at IS NOT NULL "
            "AND authorization_expires_at>authorized_at)",
            name="ck_control_restore_auth",
        ),
        sa.CheckConstraint("updated_at>=created_at", name="ck_control_op_time"),
        sa.CheckConstraint(
            "(state NOT IN ('succeeded','failed') AND result_json IS NULL) "
            "OR (state='succeeded' AND result_json IS NOT NULL AND error_code IS NULL) "
            "OR (state='failed' AND error_code IS NOT NULL)",
            name="ck_control_terminal_result",
        ),
    )
    op.create_index(
        "control_recovery_operations_state",
        "control_recovery_operations",
        ["state", "updated_at", "operation_id"],
    )
    op.create_index(
        "control_recovery_operations_created",
        "control_recovery_operations",
        ["created_at", "operation_id"],
    )


def _points():
    op.create_table(
        "control_recovery_points",
        f("point_id", "ID", primary=True),
        f("operation_id", "ID"),
        f("manifest_ref", "REF", unique=True),
        f("manifest_sha256", "HASH"),
        f("manifest_format", "REF"),
        f("captured_at", "TIME"),
        f("verified_at", "TIME"),
        f("retain_until", "TIME"),
        f("key_ref", "REF"),
        f("stored_bytes", "COUNT"),
        f("state", "CODE"),
        f("last_checked_at", "TIME"),
        f("revision", "REV"),
        fk("operation_id", "control_recovery_operations.operation_id"),
        c("state", "verified unavailable expired pruned"),
        sa.CheckConstraint(
            "verified_at>=captured_at AND retain_until>captured_at "
            "AND last_checked_at>=verified_at",
            name="ck_control_point_times",
        ),
    )
    op.create_index(
        "control_recovery_points_state_captured",
        "control_recovery_points",
        ["state", "captured_at", "point_id"],
    )
    op.create_index(
        "control_recovery_points_state_retain",
        "control_recovery_points",
        ["state", "retain_until"],
    )
    op.create_index(
        "control_recovery_points_operation",
        "control_recovery_points",
        ["operation_id"],
    )


def _restore_operations():
    op.create_table(
        "control_restore_operations",
        f("operation_id", "ID", primary=True),
        f("point_id", "ID"),
        f("target_resource_ref", "REF"),
        f("prior_resource_ref", "REF", nullable=True),
        f("new_registry_generation", "REV", nullable=True),
        f("phase", "CODE"),
        f("validation_ref", "REF", nullable=True),
        f("started_at", "TIME"),
        f("updated_at", "TIME"),
        fk("operation_id", "control_recovery_operations.operation_id"),
        fk("point_id", "control_recovery_points.point_id"),
        c("phase", "prepared fenced restored validated switched accepted needs_attention"),
        sa.CheckConstraint(
            "prior_resource_ref IS NULL OR prior_resource_ref!=target_resource_ref",
            name="ck_control_restore_targets",
        ),
        sa.CheckConstraint("updated_at>=started_at", name="ck_control_restore_time"),
    )
    op.create_index("control_restore_operations_point", "control_restore_operations", ["point_id"])
    op.create_index(
        "control_restore_operations_phase",
        "control_restore_operations",
        ["phase", "updated_at", "operation_id"],
    )


def _backup_state():
    op.create_table(
        "control_backup_state",
        f("id", "POSITIVE", primary=True),
        f("last_point_id", "ID", nullable=True),
        f("protected_admin_snapshot_ref", "REF", nullable=True),
        f("protected_inventory_manifest_ref", "REF", nullable=True),
        f("protected_config_revision", "REF", nullable=True),
        f("protected_source_generation", "REV", nullable=True),
        f("protection_state", "CODE", default="'unknown'"),
        f("last_checked_at", "TIME", nullable=True),
        f("last_attempt_at", "TIME", nullable=True),
        f("dirty_since", "TIME", nullable=True),
        f("consecutive_failures", "COUNT", default=0),
        f("last_error_code", "CODE", nullable=True),
        f("revision", "REV"),
        fk("last_point_id", "control_recovery_points.point_id"),
        c("protection_state", "healthy unchanged overdue unavailable unknown"),
        sa.CheckConstraint("id=1", name="ck_singleton"),
        sa.CheckConstraint(
            "(last_point_id IS NULL AND protected_admin_snapshot_ref IS NULL "
            "AND protected_inventory_manifest_ref IS NULL AND protected_config_revision IS NULL "
            "AND protected_source_generation IS NULL) "
            "OR (last_point_id IS NOT NULL AND protected_admin_snapshot_ref IS NOT NULL "
            "AND protected_inventory_manifest_ref IS NOT NULL "
            "AND protected_config_revision IS NOT NULL "
            "AND protected_source_generation IS NOT NULL)",
            name="ck_control_protected_tuple",
        ),
        sa.CheckConstraint(
            "protection_state NOT IN ('healthy','unchanged') OR last_point_id IS NOT NULL",
            name="ck_control_protection_requires_point",
        ),
    )
    op.create_index("control_backup_state_last_point", "control_backup_state", ["last_point_id"])


def _audit():
    op.create_table(
        "control_recovery_audit",
        f("audit_id", "ID", primary=True),
        f("operation_id", "ID", nullable=True),
        f("actor_ref", "REF"),
        f("action", "CODE"),
        f("recorded_at", "TIME"),
        f("safe_facts_json", "AUDIT_JSON"),
        fk("operation_id", "control_recovery_operations.operation_id"),
    )
    op.create_index("control_recovery_audit_operation", "control_recovery_audit", ["operation_id"])
    op.create_index(
        "control_recovery_audit_recorded",
        "control_recovery_audit",
        ["recorded_at", "audit_id"],
    )


def _guards():
    helpers["immutable"](
        op,
        "admin_recovery_meta",
        "id deployment_id incarnation_id namespace_prefix created_at",
        retain=True,
    )
    _guard(
        "admin_recovery_meta",
        "monotonic",
        "NEW.source_generation<OLD.source_generation OR NEW.revision<OLD.revision",
    )
    helpers["immutable"](
        op,
        "control_recovery_operations",
        "operation_id kind idempotency_key request_hash request_json "
        "actor_kind actor_ref authorization_ref authorized_at authorization_expires_at "
        "source_generation created_at",
        retain=True,
    )
    _guard("control_recovery_operations", "terminal", "OLD.state IN ('succeeded','failed')")
    helpers["immutable"](
        op,
        "control_recovery_points",
        "point_id operation_id manifest_ref manifest_sha256 manifest_format "
        "captured_at verified_at key_ref stored_bytes",
        retain=True,
    )
    _guard(
        "control_recovery_points",
        "monotonic",
        "NEW.last_checked_at<OLD.last_checked_at OR NEW.revision<OLD.revision",
    )
    helpers["immutable"](
        op,
        "control_restore_operations",
        "operation_id point_id target_resource_ref prior_resource_ref started_at",
        retain=True,
    )
    _guard(
        "control_restore_operations",
        "new_registry_generation_write_once",
        "OLD.new_registry_generation IS NOT NULL "
        "AND NEW.new_registry_generation IS NOT OLD.new_registry_generation",
    )
    _guard("control_restore_operations", "terminal", "OLD.phase='accepted'")
    op.execute(
        "CREATE TRIGGER control_backup_state_retained BEFORE DELETE ON control_backup_state "
        "BEGIN SELECT RAISE(ABORT, 'retained hosted record'); END"
    )
    _guard("control_backup_state", "monotonic", "NEW.revision<OLD.revision")
    helpers["immutable"](op, "control_recovery_audit")


def downgrade():
    raise RuntimeError("Greenfield hosted stores do not support downgrade.")

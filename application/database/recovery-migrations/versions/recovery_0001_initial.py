"""Complete greenfield operator recovery baseline; no secrets, sessions or business data."""

from pathlib import Path
import runpy

from alembic import op
import sqlalchemy as sa

revision = "recovery_0001_initial"
down_revision = None
branch_labels = None
depends_on = None
TABLES = (
    "recovery_meta",
    "recovery_operations",
    "recovery_points",
    "backup_state",
    "restore_operations",
    "recovery_audit",
)
helpers = runpy.run_path(str(Path(__file__).resolve().parents[2] / "hosted_ddl.py"))
f = helpers["field"]
c = helpers["choices"]
fk = helpers["foreign"]


def upgrade():
    _meta()
    _operations()
    _points()
    _backup_state()
    _restore_operations()
    _audit()
    _guards()


def _guard(table, name, condition):
    op.execute(
        f"CREATE TRIGGER {table}_{name} BEFORE UPDATE ON {table} "
        f"WHEN {condition} BEGIN SELECT RAISE(ABORT, 'invalid recovery state transition'); END"
    )


def _meta():
    op.create_table(
        "recovery_meta",
        f("id", "POSITIVE", primary=True),
        f("workspace_id", "ID", unique=True),
        f("deployment_ref", "REF"),
        f("source_generation", "REV"),
        f("restore_generation", "REV", default=1),
        f("active_business_ref", "REF"),
        f("encryption_key_ref", "REF"),
        sa.Column("namespace_prefix", sa.Text(), nullable=False),
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
        "recovery_operations",
        f("operation_id", "ID", primary=True),
        f("kind", "CODE"),
        f("idempotency_key", "KEY"),
        f("request_hash", "HASH"),
        f("request_json", "JSON"),
        f("actor_kind", "CODE"),
        f("actor_ref", "REF"),
        f("state", "CODE"),
        f("source_generation", "REV"),
        f("result_json", "JSON", nullable=True),
        f("error_code", "CODE", nullable=True),
        f("created_at", "TIME"),
        f("updated_at", "TIME"),
        f("revision", "REV"),
        sa.UniqueConstraint("kind", "idempotency_key"),
        c("kind", "backup restore"),
        c("actor_kind", "operator system"),
        c("state", "pending running needs_attention unknown succeeded failed"),
        sa.CheckConstraint(
            "kind!='restore' OR actor_kind='operator'",
            name="ck_restore_requires_operator",
        ),
        sa.CheckConstraint("updated_at>=created_at", name="ck_operation_time"),
        sa.CheckConstraint(
            "(state NOT IN ('succeeded','failed') AND result_json IS NULL) "
            "OR (state='succeeded' AND result_json IS NOT NULL AND error_code IS NULL) "
            "OR (state='failed' AND error_code IS NOT NULL)",
            name="ck_terminal_result",
        ),
    )
    op.create_index(
        "recovery_operations_state",
        "recovery_operations",
        ["state", "updated_at", "operation_id"],
    )
    op.create_index(
        "recovery_operations_created",
        "recovery_operations",
        ["created_at", "operation_id"],
    )


def _points():
    op.create_table(
        "recovery_points",
        f("point_id", "ID", primary=True),
        f("workspace_id", "ID"),
        f("operation_id", "ID"),
        f("manifest_ref", "REF", unique=True),
        f("manifest_sha256", "HASH"),
        f("manifest_format", "REF"),
        f("business_revision", "REF"),
        f("files_generation", "REF"),
        f("source_generation", "REV"),
        f("release_ref", "REF"),
        f("schema_revision", "REF"),
        f("access_schema_revision", "REF"),
        f("captured_at", "TIME"),
        f("verified_at", "TIME"),
        f("retain_until", "TIME"),
        f("key_ref", "REF"),
        f("stored_bytes", "COUNT"),
        f("state", "CODE"),
        f("last_checked_at", "TIME"),
        f("revision", "REV"),
        fk("operation_id", "recovery_operations.operation_id"),
        c("state", "verified unavailable expired pruned"),
        sa.CheckConstraint(
            "verified_at>=captured_at AND retain_until>captured_at "
            "AND last_checked_at>=verified_at",
            name="ck_point_times",
        ),
    )
    op.create_index(
        "recovery_points_state_captured",
        "recovery_points",
        ["state", "captured_at", "point_id"],
    )
    op.create_index(
        "recovery_points_state_retain",
        "recovery_points",
        ["state", "retain_until"],
    )
    op.create_index("recovery_points_operation", "recovery_points", ["operation_id"])


def _backup_state():
    op.create_table(
        "backup_state",
        f("id", "POSITIVE", primary=True),
        f("last_point_id", "ID", nullable=True),
        f("protected_business_revision", "REF", nullable=True),
        f("protected_files_generation", "REF", nullable=True),
        f("protected_source_generation", "REV", nullable=True),
        f("protection_state", "CODE", default="'unknown'"),
        f("dirty_since", "TIME", nullable=True),
        f("last_checked_at", "TIME", nullable=True),
        f("last_backup_attempt_at", "TIME", nullable=True),
        f("consecutive_failures", "COUNT", default=0),
        f("last_error_code", "CODE", nullable=True),
        f("revision", "REV"),
        fk("last_point_id", "recovery_points.point_id"),
        c("protection_state", "healthy unchanged overdue unavailable unknown"),
        sa.CheckConstraint("id=1", name="ck_singleton"),
        sa.CheckConstraint(
            "(last_point_id IS NULL AND protected_business_revision IS NULL "
            "AND protected_files_generation IS NULL AND protected_source_generation IS NULL) "
            "OR (last_point_id IS NOT NULL AND protected_business_revision IS NOT NULL "
            "AND protected_files_generation IS NOT NULL "
            "AND protected_source_generation IS NOT NULL)",
            name="ck_protected_tuple",
        ),
        sa.CheckConstraint(
            "protection_state NOT IN ('healthy','unchanged') OR last_point_id IS NOT NULL",
            name="ck_protection_requires_point",
        ),
    )
    op.create_index("backup_state_last_point", "backup_state", ["last_point_id"])


def _restore_operations():
    op.create_table(
        "restore_operations",
        f("operation_id", "ID", primary=True),
        f("point_id", "ID"),
        f("preview_id", "ID"),
        f("prior_business_ref", "REF"),
        f("prior_tree_kind", "CODE"),
        f("target_business_ref", "REF"),
        f("new_source_generation", "REV"),
        f("new_access_epoch", "REV", nullable=True),
        sa.Column("authorized_subject", sa.Text(), nullable=False),
        f("authorization_ref", "REF"),
        f("authorized_at", "TIME"),
        f("execution_authorization_expires_at", "TIME"),
        f("preview_source_revision", "REF", nullable=True),
        f("executor_ref", "REF"),
        f("phase", "CODE"),
        f("validation_ref", "REF", nullable=True),
        f("started_at", "TIME"),
        f("updated_at", "TIME"),
        f("accepted_at", "TIME", nullable=True),
        fk("operation_id", "recovery_operations.operation_id"),
        fk("point_id", "recovery_points.point_id"),
        c("prior_tree_kind", "healthy_pre_state forensic_damaged"),
        c("phase", "prepared fenced restored validated switched accepted needs_attention"),
        sa.CheckConstraint(
            "typeof(authorized_subject)='text' AND length(authorized_subject) BETWEEN 1 AND 1024",
            name="ck_authorized_subject",
        ),
        sa.CheckConstraint(
            "prior_business_ref!=target_business_ref",
            name="ck_restore_targets",
        ),
        sa.CheckConstraint(
            "execution_authorization_expires_at>authorized_at "
            "AND started_at>=authorized_at AND updated_at>=started_at",
            name="ck_restore_auth_window",
        ),
        sa.CheckConstraint(
            "(phase='accepted' AND accepted_at IS NOT NULL AND accepted_at>=started_at) "
            "OR (phase!='accepted' AND accepted_at IS NULL)",
            name="ck_restore_accepted",
        ),
    )
    op.create_index("restore_operations_point", "restore_operations", ["point_id"])
    op.create_index(
        "restore_operations_phase",
        "restore_operations",
        ["phase", "updated_at", "operation_id"],
    )


def _audit():
    op.create_table(
        "recovery_audit",
        f("audit_id", "ID", primary=True),
        f("operation_id", "ID", nullable=True),
        f("actor_ref", "REF"),
        f("action", "CODE"),
        f("recorded_at", "TIME"),
        f("safe_facts_json", "AUDIT_JSON"),
        fk("operation_id", "recovery_operations.operation_id"),
    )
    op.create_index("recovery_audit_operation", "recovery_audit", ["operation_id"])
    op.create_index("recovery_audit_recorded", "recovery_audit", ["recorded_at", "audit_id"])


def _guards():
    helpers["immutable"](
        op,
        "recovery_meta",
        "id workspace_id deployment_ref namespace_prefix",
        retain=True,
    )
    _guard(
        "recovery_meta",
        "monotonic",
        "NEW.source_generation<OLD.source_generation "
        "OR NEW.restore_generation<OLD.restore_generation "
        "OR NEW.revision<OLD.revision",
    )
    helpers["immutable"](
        op,
        "recovery_operations",
        "operation_id kind idempotency_key request_hash request_json "
        "actor_kind actor_ref source_generation created_at",
        retain=True,
    )
    _guard("recovery_operations", "terminal", "OLD.state IN ('succeeded','failed')")
    helpers["immutable"](
        op,
        "recovery_points",
        "point_id workspace_id operation_id manifest_ref manifest_sha256 manifest_format "
        "business_revision files_generation source_generation release_ref schema_revision "
        "access_schema_revision captured_at verified_at key_ref stored_bytes",
        retain=True,
    )
    _guard(
        "recovery_points",
        "monotonic",
        "NEW.last_checked_at<OLD.last_checked_at OR NEW.revision<OLD.revision",
    )
    op.execute(
        "CREATE TRIGGER backup_state_retained BEFORE DELETE ON backup_state "
        "BEGIN SELECT RAISE(ABORT, 'retained hosted record'); END"
    )
    _guard("backup_state", "monotonic", "NEW.revision<OLD.revision")
    helpers["immutable"](
        op,
        "restore_operations",
        "operation_id point_id preview_id prior_business_ref prior_tree_kind "
        "target_business_ref new_source_generation authorized_subject authorization_ref "
        "authorized_at execution_authorization_expires_at preview_source_revision "
        "executor_ref started_at",
        retain=True,
    )
    _guard("restore_operations", "terminal", "OLD.phase='accepted'")
    helpers["immutable"](op, "recovery_audit")


def downgrade():
    raise RuntimeError("Greenfield hosted stores do not support downgrade.")

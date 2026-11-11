"Protected host inventory baseline; no resource allocation or host effects."

from pathlib import Path
import runpy

from alembic import op
import sqlalchemy as sa

revision = "host_inventory_0001_initial"
down_revision = None
branch_labels = None
depends_on = None
TABLES = (
    "host_identity",
    "operator_principals",
    "resource_bindings",
    "project_assignments",
    "ingress_bindings",
    "host_receipts",
)

helpers = runpy.run_path(str(Path(__file__).resolve().parents[2] / "hosted_ddl.py"))
f = helpers["field"]
c = helpers["choices"]
fk = helpers["foreign"]


def upgrade():
    _identity()
    _resources()
    _effects()
    _guards()


def _identity():
    op.create_table(
        "host_identity",
        f("id", "POSITIVE", primary=True),
        f("host_id", "ID", unique=True),
        f("deployment_id", "ID"),
        f("filesystem_identity", "REF"),
        f("agent_contract_version", "REF"),
        f("created_at", "TIME"),
        sa.CheckConstraint("id=1", name="ck_singleton"),
    )
    op.create_table(
        "operator_principals",
        f("operator_id", "ID", primary=True),
        f("workspace_id", "ID", unique=True),
        f("host_uid", "UID", unique=True),
        f("host_gid", "UID", unique=True),
        f("assigned_at", "TIME"),
        f("retired_at", "TIME", nullable=True),
        f("cleanup_verified_at", "TIME", nullable=True),
        f("revision", "REV"),
        sa.UniqueConstraint("operator_id", "workspace_id"),
        sa.CheckConstraint("retired_at IS NULL OR retired_at>=assigned_at", name="ck_retired_time"),
        sa.CheckConstraint(
            (
                "cleanup_verified_at IS NULL OR (retired_at IS NOT NULL AND "
                "cleanup_verified_at>=retired_at)"
            ),
            name="ck_cleanup_time",
        ),
    )


def _resources():
    op.create_table(
        "resource_bindings",
        f("binding_id", "ID", primary=True),
        f("operator_id", "ID"),
        f("workspace_id", "ID"),
        f("resource_generation", "REV"),
        f("role", "CODE"),
        f("workspace_relative_ref", "REF", unique=True),
        f("access_relative_ref", "REF", unique=True),
        f("scratch_relative_ref", "REF", unique=True),
        f("container_ref", "REF", nullable=True, unique=True),
        f("image_digest", "HASH"),
        *(
            f(tree + "_" + unit + "_ceiling", "POSITIVE")
            for tree in ("workspace", "control", "scratch")
            for unit in ("byte", "inode")
        ),
        f("state", "CODE"),
        f("provision_operation_id", "ID"),
        f("last_verified_at", "TIME", nullable=True),
        f("revision", "REV"),
        fk(
            "operator_id workspace_id",
            "operator_principals.operator_id operator_principals.workspace_id",
        ),
        c("role", "active restore_staging retained"),
        c("state", "allocated prepared running stopped needs_attention retired"),
        sa.UniqueConstraint("workspace_id", "resource_generation"),
        sa.UniqueConstraint("binding_id", "operator_id", "workspace_id", "resource_generation"),
    )
    op.create_index(
        "resource_bindings_active",
        "resource_bindings",
        ["operator_id"],
        unique=True,
        sqlite_where=sa.text("role='active' AND state!='retired'"),
    )
    op.create_table(
        "project_assignments",
        f("project_id", "POSITIVE", primary=True),
        f("binding_id", "ID"),
        f("tree_kind", "CODE"),
        f("filesystem_identity", "REF"),
        f("assigned_at", "TIME"),
        fk("binding_id", "resource_bindings.binding_id"),
        c("tree_kind", "workspace control scratch"),
        sa.UniqueConstraint("binding_id", "tree_kind"),
    )


def _effects():
    op.create_table(
        "host_receipts",
        f("operation_id", "ID", primary=True),
        f("parent_operation_id", "ID"),
        f("idempotency_key", "KEY"),
        f("request_hash", "HASH"),
        f("request_json", "JSON"),
        f("binding_id", "ID", nullable=True),
        f("access_epoch", "REV"),
        f("kind", "CODE"),
        f("state", "CODE"),
        f("observed_json", "JSON", nullable=True),
        f("recorded_at", "TIME"),
        f("revision", "REV"),
        fk("binding_id", "resource_bindings.binding_id"),
        c(
            "kind",
            (
                "prepare_resources initialize_container repair_runtime start_container "
                "stop_container apply_limits apply_ingress_policy stage_restore "
                "switch_binding retire_resources"
            ),
        ),
        c("state", "pending unknown applied rejected superseded"),
        sa.CheckConstraint(
            "state!='superseded' OR (kind='start_container' AND "
            "json_type(observed_json,'$.superseded_by_operation_id') IS 'text' AND "
            "json_type(observed_json,'$.containment_evidence_ref') IS 'text' AND "
            "json_type(observed_json,'$.superseded_at') IS 'integer')",
            name="ck_superseded_start_containment",
        ),
        sa.UniqueConstraint("kind", "idempotency_key"),
        sa.CheckConstraint(
            "kind IN ('stage_restore','switch_binding') OR binding_id IS NOT NULL",
            name="ck_registered_effect_binding",
        ),
        sa.CheckConstraint(
            "state NOT IN ('applied','superseded') OR observed_json IS NOT NULL",
            name="ck_applied_observation",
        ),
    )
    op.create_index(
        "host_receipts_parent", "host_receipts", ["parent_operation_id", "operation_id"]
    )
    op.create_index(
        "host_receipts_state", "host_receipts", ["state", "recorded_at", "operation_id"]
    )
    op.create_table(
        "ingress_bindings",
        f("operator_id", "ID", primary=True),
        f("workspace_id", "ID", unique=True),
        f("binding_id", "ID"),
        f("resource_generation", "REV"),
        f("public_origin", "ORIGIN", unique=True),
        f("access_epoch", "REV"),
        f("desired_state", "CODE"),
        f("operation_id", "ID"),
        f("verified_state", "CODE"),
        f("verified_revision", "REV", nullable=True),
        f("verification_ref", "REF", nullable=True),
        f("verified_at", "TIME", nullable=True),
        f("updated_at", "TIME"),
        f("revision", "REV"),
        fk(
            "binding_id operator_id workspace_id resource_generation",
            (
                "resource_bindings.binding_id resource_bindings.operator_id "
                "resource_bindings.workspace_id resource_bindings.resource_generation"
            ),
        ),
        fk("operation_id", "host_receipts.operation_id"),
        c("desired_state", "held eligible blocked"),
        c("verified_state", "held eligible blocked unknown"),
        sa.CheckConstraint(
            (
                "(verified_state='unknown' AND verified_revision IS NULL AND "
                "verification_ref IS NULL AND verified_at IS NULL) OR "
                "(verified_state!='unknown' AND verified_revision IS NOT NULL AND "
                "verification_ref IS NOT NULL AND verified_at IS NOT NULL AND "
                "verified_revision<=revision)"
            ),
            name="ck_verification",
        ),
    )
    op.create_index("ingress_bindings_state", "ingress_bindings", ["desired_state", "operator_id"])


def _guards():
    immutable = helpers["immutable"]
    immutable(op, "host_identity")
    immutable(op, "operator_principals", "operator_id workspace_id host_uid host_gid assigned_at")
    immutable(op, "ingress_bindings", "operator_id workspace_id public_origin")
    immutable(
        op,
        "resource_bindings",
        (
            "binding_id operator_id workspace_id resource_generation "
            "workspace_relative_ref access_relative_ref scratch_relative_ref "
            "provision_operation_id"
        ),
    )
    immutable(
        op,
        "host_receipts",
        (
            "operation_id parent_operation_id idempotency_key request_hash "
            "request_json binding_id access_epoch kind recorded_at"
        ),
    )
    immutable(
        op,
        "project_assignments",
        "project_id binding_id tree_kind filesystem_identity assigned_at",
        retain=False,
    )
    op.execute(
        "CREATE TRIGGER binding_no_replace_active BEFORE INSERT ON resource_bindings "
        "WHEN NEW.role='active' AND NEW.state!='retired' AND EXISTS "
        "(SELECT 1 FROM resource_bindings WHERE operator_id=NEW.operator_id "
        "AND role='active' AND state!='retired') "
        "BEGIN SELECT RAISE(ABORT, 'retained active binding'); END"
    )
    op.execute(
        (
            "CREATE TRIGGER project_cleanup_required BEFORE DELETE ON "
            "project_assignments WHEN NOT EXISTS (SELECT 1 FROM resource_bindings "
            "r JOIN operator_principals p ON p.operator_id=r.operator_id WHERE "
            "r.binding_id=OLD.binding_id AND r.state='retired' AND "
            "p.cleanup_verified_at IS NOT NULL) BEGIN SELECT RAISE(ABORT, "
            "'verified cleanup required'); END"
        )
    )
    op.execute(
        (
            "CREATE TRIGGER host_receipts_terminal BEFORE UPDATE ON host_receipts "
            "WHEN OLD.state IN ('applied','rejected','superseded') BEGIN SELECT RAISE(ABORT, "
            "'terminal host receipt'); END"
        )
    )
    op.execute(
        (
            "CREATE TRIGGER ingress_initial_held BEFORE INSERT ON ingress_bindings "
            "WHEN NEW.desired_state!='held' OR NEW.verified_state!='unknown' BEGIN "
            "SELECT RAISE(ABORT, 'new ingress must be held'); END"
        )
    )
    op.execute(
        (
            "CREATE TRIGGER ingress_fence BEFORE UPDATE ON ingress_bindings WHEN "
            "NEW.access_epoch<OLD.access_epoch OR NEW.revision<=OLD.revision OR "
            "NEW.updated_at<OLD.updated_at BEGIN SELECT RAISE(ABORT, 'stale "
            "ingress fence'); END"
        )
    )


def downgrade():
    raise RuntimeError("Greenfield hosted stores do not support downgrade.")

"Complete Pilot 0 main-Admin structural baseline; no access or operator seed."

from pathlib import Path
import runpy

from alembic import op
import sqlalchemy as sa

revision = "admin_0001_initial"
down_revision = None
branch_labels = None
depends_on = None
TABLES = (
    "control_meta",
    "storage_policies",
    "qualified_releases",
    "component_deployments",
    "operators",
    "invitations",
    "admin_principals",
    "admin_sessions",
    "login_handoffs",
    "operations",
    "operation_events",
    "admin_audit",
    "workspace_recovery_status",
)

helpers = runpy.run_path(str(Path(__file__).resolve().parents[2] / "hosted_ddl.py"))
f = helpers["field"]
c = helpers["choices"]
fk = helpers["foreign"]


def upgrade():
    _registry()
    _assignments()
    _identity()
    _operations()
    _guards()


def _registry():
    op.create_table(
        "control_meta",
        f("id", "POSITIVE", primary=True),
        f("deployment_id", "ID", unique=True),
        f("public_base_domain", "DOMAIN"),
        f("login_origin", "ORIGIN"),
        f("registry_generation", "REV"),
        f("created_at", "TIME"),
        sa.CheckConstraint("id=1", name="ck_singleton"),
    )
    op.create_table(
        "storage_policies",
        f("policy_id", "ID", primary=True),
        f("plan_code", "CODE"),
        f("policy_version", "POSITIVE"),
        f("usable_bytes", "POSITIVE"),
        f("backup_interval_seconds", "POSITIVE"),
        f("retained_nightly_points", "POSITIVE"),
        f("keep_warm", "BOOLEAN"),
        f("created_at", "TIME"),
        c("plan_code", "free"),
        sa.UniqueConstraint("plan_code", "policy_version"),
    )
    op.create_table(
        "qualified_releases",
        f("release_id", "ID", primary=True),
        f("component", "CODE"),
        f("artifact_kind", "CODE"),
        f("artifact_digest", "HASH"),
        f("artifact_ref", "REF"),
        f("compatibility_manifest_ref", "REF"),
        f("compatibility_manifest_sha256", "HASH"),
        *(
            f(name + "_schema_revision", "REF", nullable=True)
            for name in ("business", "access", "admin", "admin_recovery", "inventory", "recovery")
        ),
        f("qualification_ref", "REF"),
        f("state", "CODE"),
        f("qualified_at", "TIME"),
        f("revision", "REV"),
        c("component", "admin operator tenant owner"),
        c("artifact_kind", "oci_image web_bundle"),
        c("state", "qualified withdrawn"),
        sa.UniqueConstraint("component", "artifact_digest"),
        sa.UniqueConstraint("release_id", "component"),
        sa.CheckConstraint("inventory_schema_revision IS NULL", name="ck_agent_not_portal"),
        sa.CheckConstraint(
            (
                "(component='admin' AND artifact_kind='oci_image' AND "
                "admin_schema_revision IS NOT NULL AND admin_recovery_schema_revision "
                "IS NOT NULL AND business_schema_revision IS NULL AND "
                "access_schema_revision IS NULL AND recovery_schema_revision IS NULL) "
                "OR (component='operator' AND artifact_kind='oci_image' AND "
                "business_schema_revision IS NOT NULL AND access_schema_revision IS "
                "NOT NULL AND recovery_schema_revision IS NOT NULL AND "
                "admin_schema_revision IS NULL AND admin_recovery_schema_revision IS "
                "NULL) OR (component IN ('tenant','owner') AND "
                "artifact_kind='web_bundle' AND business_schema_revision IS NULL AND "
                "access_schema_revision IS NULL AND recovery_schema_revision IS NULL "
                "AND admin_schema_revision IS NULL AND admin_recovery_schema_revision "
                "IS NULL)"
            ),
            name="ck_release_ownership",
        ),
    )
    op.create_table(
        "operators",
        f("operator_id", "ID", primary=True),
        f("workspace_id", "ID", unique=True),
        f("display_name", "NAME"),
        f("invited_email", "EMAIL"),
        f("email_key", "EMAIL", unique=True),
        f("workspace_slug", "SLUG", unique=True),
        f("issuer", "REF"),
        f("subject", "TEXT", nullable=True),
        f("desired_policy_id", "ID"),
        f("desired_access", "CODE"),
        f("setup_state", "CODE"),
        f("support_contact", "EMAIL"),
        f("access_epoch", "REV"),
        f("revision", "REV"),
        f("created_at", "TIME"),
        f("updated_at", "TIME"),
        f("retired_at", "TIME", nullable=True),
        fk("desired_policy_id", "storage_policies.policy_id"),
        sa.UniqueConstraint("operator_id", "workspace_id"),
        c("desired_access", "enabled disabled retired"),
        c("setup_state", "pending preparing ready_for_claim active needs_attention retired"),
        sa.CheckConstraint("updated_at>=created_at", name="ck_update_time"),
        sa.CheckConstraint("retired_at IS NULL OR retired_at>=created_at", name="ck_retire_time"),
        sa.CheckConstraint(
            "setup_state!='active' OR subject IS NOT NULL", name="ck_active_subject"
        ),
        sa.CheckConstraint(
            ("setup_state!='retired' OR (retired_at IS NOT NULL AND desired_access='retired')"),
            name="ck_retired",
        ),
        sa.CheckConstraint(
            (
                "workspace_slug NOT IN "
                "('admin','login','api','www','mail','static','assets','support','statu"
                "s')"
            ),
            name="ck_reserved_slug",
        ),
    )
    op.create_index(
        "operators_subject",
        "operators",
        ["issuer", "subject"],
        unique=True,
        sqlite_where=sa.text("subject IS NOT NULL"),
    )
    op.create_index("operators_setup", "operators", ["setup_state", "operator_id"])
    op.create_index("operators_access", "operators", ["desired_access", "operator_id"])


def _assignments():
    op.create_table(
        "component_deployments",
        f("component_deployment_id", "ID", primary=True),
        f("deployment_id", "ID"),
        f("component", "CODE"),
        f("scope_kind", "CODE"),
        f("operator_id", "ID", nullable=True),
        f("workspace_id", "ID", nullable=True),
        f("desired_release_id", "ID"),
        f("observed_release_id", "ID", nullable=True),
        f("operation_id", "ID", nullable=True),
        f("state", "CODE"),
        f("observation_ref", "REF", nullable=True),
        f("observed_at", "TIME", nullable=True),
        f("revision", "REV"),
        c("component", "admin operator tenant owner"),
        c("scope_kind", "deployment workspace"),
        c("state", "pending applying applied needs_attention unknown"),
        fk("deployment_id", "control_meta.deployment_id"),
        fk("operator_id workspace_id", "operators.operator_id operators.workspace_id"),
        fk(
            "desired_release_id component",
            "qualified_releases.release_id qualified_releases.component",
        ),
        fk(
            "observed_release_id component",
            "qualified_releases.release_id qualified_releases.component",
        ),
        fk("operation_id", "operations.operation_id"),
        sa.CheckConstraint(
            (
                "(component='operator' AND scope_kind='workspace' AND operator_id IS "
                "NOT NULL AND workspace_id IS NOT NULL) OR (component IN "
                "('admin','tenant','owner') AND scope_kind='deployment' AND "
                "operator_id IS NULL AND workspace_id IS NULL)"
            ),
            name="ck_assignment_scope",
        ),
        sa.CheckConstraint(
            (
                "state!='applied' OR (observed_release_id IS NOT NULL AND "
                "desired_release_id=observed_release_id AND observation_ref IS NOT "
                "NULL AND observed_at IS NOT NULL)"
            ),
            name="ck_applied",
        ),
    )
    op.create_index(
        "component_deployments_shared",
        "component_deployments",
        ["deployment_id", "component"],
        unique=True,
        sqlite_where=sa.text("scope_kind='deployment'"),
    )
    op.create_index(
        "component_deployments_workspace",
        "component_deployments",
        ["deployment_id", "component", "workspace_id"],
        unique=True,
        sqlite_where=sa.text("scope_kind='workspace'"),
    )
    op.create_index(
        "component_deployments_state",
        "component_deployments",
        ["state", "component", "component_deployment_id"],
    )


def _identity():
    op.create_table(
        "invitations",
        f("invitation_id", "ID", primary=True),
        f("operator_id", "ID"),
        f("token_hash", "HASH", unique=True),
        f("email_key", "EMAIL"),
        f("assignment_revision", "REV"),
        f("access_epoch", "REV"),
        f("state", "CODE"),
        f("expires_at", "TIME"),
        f("claimed_at", "TIME", nullable=True),
        f("claimed_issuer", "REF", nullable=True),
        f("claimed_subject", "TEXT", nullable=True),
        f("delivery_attempts", "COUNT", default=0),
        f("last_delivery_code", "CODE", nullable=True),
        f("created_at", "TIME"),
        f("revision", "REV"),
        fk("operator_id", "operators.operator_id"),
        c("state", "pending_delivery sent claimed revoked expired"),
        sa.CheckConstraint("expires_at>created_at", name="ck_expiry"),
        sa.CheckConstraint(
            (
                "(claimed_at IS NULL AND claimed_issuer IS NULL AND claimed_subject IS "
                "NULL AND state!='claimed') OR (claimed_at IS NOT NULL AND "
                "claimed_issuer IS NOT NULL AND claimed_subject IS NOT NULL AND "
                "claimed_at>=created_at AND claimed_at<expires_at AND state='claimed')"
            ),
            name="ck_claim_identity",
        ),
    )
    op.create_index(
        "invitations_live",
        "invitations",
        ["operator_id"],
        unique=True,
        sqlite_where=sa.text("state IN ('pending_delivery','sent')"),
    )
    op.create_index("invitations_operator", "invitations", ["operator_id", "state", "expires_at"])
    op.create_table(
        "admin_principals",
        f("principal_id", "ID", primary=True),
        f("issuer", "REF"),
        f("subject", "TEXT"),
        f("enabled", "BOOLEAN", default=0),
        f("session_generation", "REV"),
        f("revision", "REV"),
        f("created_at", "TIME"),
        sa.UniqueConstraint("issuer", "subject"),
    )
    op.create_table(
        "admin_sessions",
        f("session_hash", "HASH", primary=True),
        f("principal_id", "ID"),
        f("csrf_hash", "HASH"),
        f("generation", "REV"),
        f("authenticated_at", "TIME"),
        f("mfa_verified_at", "TIME"),
        f("expires_at", "TIME"),
        f("last_seen_at", "TIME"),
        f("revoked_at", "TIME", nullable=True),
        fk("principal_id", "admin_principals.principal_id"),
        sa.CheckConstraint(
            (
                "expires_at>authenticated_at AND expires_at-authenticated_at<=28800000 "
                "AND mfa_verified_at<expires_at AND "
                "last_seen_at>=authenticated_at AND (revoked_at IS NULL OR "
                "revoked_at>=authenticated_at)"
            ),
            name="ck_session_times",
        ),
    )
    op.create_index(
        "admin_sessions_principal", "admin_sessions", ["principal_id", "revoked_at", "expires_at"]
    )
    op.create_index("admin_sessions_expiry", "admin_sessions", ["expires_at"])
    op.create_table(
        "login_handoffs",
        f("handoff_id", "ID", primary=True),
        f("operator_id", "ID"),
        f("browser_state_hash", "HASH"),
        f("nonce_hash", "HASH", unique=True),
        f("code_hash", "HASH", nullable=True, unique=True),
        f("target_origin", "ORIGIN"),
        f("issuer", "REF", nullable=True),
        f("subject", "TEXT", nullable=True),
        f("assignment_revision", "REV"),
        f("access_epoch", "REV"),
        f("state", "CODE"),
        f("expires_at", "TIME"),
        f("redeemed_at", "TIME", nullable=True),
        f("created_at", "TIME"),
        fk("operator_id", "operators.operator_id"),
        c("state", "initiated issued redeemed expired"),
        sa.CheckConstraint(
            "expires_at>created_at AND expires_at-created_at<=300000", name="ck_handoff_lifetime"
        ),
        sa.CheckConstraint(
            (
                "state NOT IN ('issued','redeemed') OR (code_hash IS NOT NULL AND "
                "issuer IS NOT NULL AND subject IS NOT NULL)"
            ),
            name="ck_issued_identity",
        ),
        sa.CheckConstraint(
            (
                "(state='redeemed' AND redeemed_at IS NOT NULL AND "
                "redeemed_at>=created_at AND redeemed_at<expires_at) OR "
                "(state!='redeemed' AND redeemed_at IS NULL)"
            ),
            name="ck_redemption",
        ),
    )
    op.create_index("login_handoffs_expiry", "login_handoffs", ["expires_at"])
    op.create_index("login_handoffs_operator", "login_handoffs", ["operator_id", "state"])


def _operations():
    op.create_table(
        "operations",
        f("operation_id", "ID", primary=True),
        f("operator_id", "ID", nullable=True),
        f("component_deployment_id", "ID", nullable=True),
        f("kind", "CODE"),
        f("idempotency_key", "KEY"),
        f("request_hash", "HASH"),
        f("request_json", "JSON"),
        f("actor_principal_id", "ID", nullable=True),
        f("system_actor", "REF", nullable=True),
        f("expected_revision", "REV", nullable=True),
        f("access_epoch", "REV", nullable=True),
        f("state", "CODE"),
        f("effect_reference", "REF", nullable=True),
        f("result_json", "JSON", nullable=True),
        f("error_code", "CODE", nullable=True),
        f("created_at", "TIME"),
        f("updated_at", "TIME"),
        f("revision", "REV"),
        fk("operator_id", "operators.operator_id"),
        fk("component_deployment_id", "component_deployments.component_deployment_id"),
        fk("actor_principal_id", "admin_principals.principal_id"),
        c("kind", "provision repair_runtime disable enable rebind retire maintenance_release"),
        c("state", "pending running needs_attention unknown succeeded failed"),
        sa.UniqueConstraint("kind", "idempotency_key"),
        sa.CheckConstraint(
            "(actor_principal_id IS NULL)!=(system_actor IS NULL)", name="ck_one_actor"
        ),
        sa.CheckConstraint(
            "kind='maintenance_release' OR operator_id IS NOT NULL", name="ck_operator_effect"
        ),
        sa.CheckConstraint(
            "kind!='maintenance_release' OR component_deployment_id IS NOT NULL",
            name="ck_release_assignment",
        ),
        sa.CheckConstraint("updated_at>=created_at", name="ck_operation_time"),
        sa.CheckConstraint(
            (
                "(state='succeeded' AND result_json IS NOT NULL AND error_code IS "
                "NULL) OR (state!='succeeded' AND result_json IS NULL)"
            ),
            name="ck_result",
        ),
        sa.CheckConstraint(
            "state NOT IN ('failed','needs_attention') OR error_code IS NOT NULL",
            name="ck_failure_code",
        ),
    )
    op.create_index(
        "operations_operator", "operations", ["operator_id", "created_at", "operation_id"]
    )
    op.create_index("operations_state", "operations", ["state", "updated_at", "operation_id"])
    op.create_table(
        "operation_events",
        f("operation_id", "ID", primary=True),
        f("sequence", "POSITIVE", primary=True),
        f("event_code", "CODE"),
        f("safe_summary", "TEXT"),
        f("recorded_at", "TIME"),
        fk("operation_id", "operations.operation_id"),
    )
    op.create_table(
        "admin_audit",
        f("audit_id", "ID", primary=True),
        f("actor_ref", "REF"),
        f("action", "CODE"),
        f("operator_id", "ID", nullable=True),
        f("operation_id", "ID", nullable=True),
        f("recorded_at", "TIME"),
        f("safe_facts_json", "AUDIT_JSON"),
        fk("operator_id", "operators.operator_id"),
        fk("operation_id", "operations.operation_id"),
    )
    op.create_index(
        "admin_audit_operator", "admin_audit", ["operator_id", "recorded_at", "audit_id"]
    )
    op.create_index("admin_audit_operation", "admin_audit", ["operation_id"])
    op.create_table(
        "workspace_recovery_status",
        f("operator_id", "ID", primary=True),
        f("workspace_id", "ID"),
        f("source_epoch", "REV"),
        f("source_revision", "REV"),
        f("latest_point_ref", "REF", nullable=True),
        f("captured_at", "TIME", nullable=True),
        f("verified_at", "TIME", nullable=True),
        f("checked_at", "TIME"),
        f("observed_at", "TIME"),
        f("dirty_since", "TIME", nullable=True),
        f("protection_state", "CODE"),
        f("active_operation_ref", "REF", nullable=True),
        f("revision", "REV"),
        fk("operator_id workspace_id", "operators.operator_id operators.workspace_id"),
        c("protection_state", "healthy unchanged overdue unavailable unknown"),
        sa.CheckConstraint(
            (
                "verified_at IS NULL OR (latest_point_ref IS NOT NULL AND captured_at "
                "IS NOT NULL AND verified_at>=captured_at)"
            ),
            name="ck_verified_point",
        ),
        sa.CheckConstraint("observed_at>=checked_at", name="ck_observed_time"),
    )
    op.create_index(
        "workspace_recovery_status_state",
        "workspace_recovery_status",
        ["protection_state", "observed_at", "operator_id"],
    )


def _guards():
    immutable = helpers["immutable"]
    for table in ("storage_policies", "operation_events", "admin_audit"):
        immutable(op, table)
    immutable(
        op,
        "qualified_releases",
        (
            "release_id component artifact_kind artifact_digest artifact_ref "
            "compatibility_manifest_ref compatibility_manifest_sha256 "
            "business_schema_revision access_schema_revision admin_schema_revision "
            "admin_recovery_schema_revision inventory_schema_revision "
            "recovery_schema_revision qualification_ref qualified_at"
        ),
    )
    immutable(
        op,
        "operations",
        (
            "operation_id operator_id component_deployment_id kind idempotency_key "
            "request_hash request_json actor_principal_id system_actor "
            "expected_revision access_epoch created_at"
        ),
    )
    op.execute(
        (
            "CREATE TRIGGER operations_terminal BEFORE UPDATE ON operations WHEN "
            "OLD.state IN ('succeeded','failed') BEGIN SELECT RAISE(ABORT, "
            "'terminal operation'); END"
        )
    )


def downgrade():
    raise RuntimeError("Greenfield hosted stores do not support downgrade.")

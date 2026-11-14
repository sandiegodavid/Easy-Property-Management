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
    "login_attempts",
    "email_continuations",
    "managed_identity_sessions",
    "identity_commands",
    "identity_mail_reservations",
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
    _mail_reservations()
    _identity_flows()
    _identity()
    _identity_guards()
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
        f("managed_session_id", "ID"),
        f("managed_valid_until", "TIME"),
        f("revocation_valid_until", "TIME"),
        fk("managed_session_id", "managed_identity_sessions.managed_session_id"),
        sa.CheckConstraint(
            "authenticated_at<=mfa_verified_at AND last_seen_at>=mfa_verified_at "
            "AND (revoked_at IS NULL OR revoked_at>=mfa_verified_at) "
            "AND expires_at<=managed_valid_until AND mfa_verified_at<revocation_valid_until "
            "AND revocation_valid_until<=managed_valid_until",
            name="ck_managed_deadlines",
        ),
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
        f("attempt_id", "ID"),
        f("managed_session_id", "ID"),
        f("identity_operation_id", "ID"),
        f("source_receipt_ref", "REF", nullable=True),
        fk("attempt_id", "login_attempts.attempt_id"),
        fk("managed_session_id", "managed_identity_sessions.managed_session_id"),
        fk("identity_operation_id", "identity_commands.operation_id"),
        sa.CheckConstraint(
            "(issuer IS NULL AND subject IS NULL AND code_hash IS NULL) OR "
            "(issuer IS NOT NULL AND subject IS NOT NULL AND code_hash IS NOT NULL)",
            name="ck_identity_together",
        ),
        sa.CheckConstraint("state!='initiated' OR code_hash IS NULL", name="ck_unissued"),
        sa.CheckConstraint(
            "(redeemed_at IS NULL)=(source_receipt_ref IS NULL)", name="ck_receipt_together"
        ),
        c("state", "initiated issued redeeming redeemed expired"),
        sa.CheckConstraint(
            "expires_at>created_at AND expires_at-created_at<=300000", name="ck_handoff_lifetime"
        ),
        sa.CheckConstraint(
            (
                "state NOT IN ('issued','redeeming','redeemed') OR (code_hash IS NOT NULL AND "
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


def _checks(*rules):
    return [
        sa.CheckConstraint(rule, name=f"ck_identity_{index}") for index, rule in enumerate(rules)
    ]


def _identity_flows():
    _managed_sessions()
    _login_attempts()
    _continuations()
    _identity_commands()
    op.create_index(
        "managed_identity_sessions_identity",
        "managed_identity_sessions",
        ["issuer", "subject", "purpose", "revoked_at"],
    )
    op.create_index(
        "managed_identity_sessions_expiry",
        "managed_identity_sessions",
        ["provider_valid_until", "managed_session_id"],
    )


def _managed_sessions():
    op.create_table(
        "managed_identity_sessions",
        f("managed_session_id", "ID", primary=True),
        f("cookie_hash", "HASH", unique=True),
        f("purpose", "CODE"),
        f("operator_id", "ID", nullable=True),
        f("issuer", "REF"),
        f("subject", "TEXT"),
        f("email_key", "EMAIL"),
        f("method", "CODE"),
        f("authenticated_at", "TIME"),
        f("mfa_verified_at", "TIME", nullable=True),
        *(
            f(name, "TIME")
            for name in (
                "provider_valid_until",
                "remembered_until",
                "revocation_checked_at",
                "revocation_valid_until",
                "issued_at",
            )
        ),
        f("revoked_at", "TIME", nullable=True),
        f("revision", "REV"),
        fk("operator_id", "operators.operator_id"),
        c("purpose", "operator admin"),
        c("method", "google email_link google_totp"),
        *_checks(
            "(purpose='operator')=(operator_id IS NOT NULL)",
            "authenticated_at<=issued_at AND issued_at<provider_valid_until "
            "AND provider_valid_until<=issued_at+1209600000",
            "issued_at<remembered_until AND remembered_until<=issued_at+2592000000",
            "issued_at<=revocation_checked_at AND revocation_checked_at<provider_valid_until "
            "AND revocation_checked_at<revocation_valid_until "
            "AND revocation_valid_until<=revocation_checked_at+300000 "
            "AND revocation_valid_until<=provider_valid_until",
            "(purpose='admin' AND method='google_totp' AND mfa_verified_at IS NOT NULL "
            "AND authenticated_at<=mfa_verified_at AND mfa_verified_at<=issued_at) OR "
            "(purpose='operator' AND method!='google_totp' AND mfa_verified_at IS NULL)",
            "revoked_at IS NULL OR revoked_at>=issued_at",
        ),
    )
    op.create_index(
        "managed_identity_sessions_operator",
        "managed_identity_sessions",
        ["operator_id", "revoked_at", "provider_valid_until"],
    )


def _login_attempts():
    op.create_table(
        "login_attempts",
        f("attempt_id", "ID", primary=True),
        f("purpose", "CODE"),
        f("operator_id", "ID", nullable=True),
        f("parent_managed_session_id", "ID", nullable=True),
        f("completed_managed_session_id", "ID", nullable=True),
        f("source_attempt_id", "ID", nullable=True),
        f("source_browser_hash", "HASH", nullable=True),
        f("central_browser_hash", "HASH"),
        f("method", "CODE"),
        f("email_key", "EMAIL", nullable=True),
        f("target_origin", "ORIGIN"),
        f("return_path", "TEXT"),
        f("confirmed_request_hash", "HASH", nullable=True),
        f("delivery_attempts", "COUNT", default=0),
        f("last_delivery_at", "TIME", nullable=True),
        f("last_delivery_code", "CODE", nullable=True),
        f("state", "CODE"),
        f("created_at", "TIME"),
        f("expires_at", "TIME"),
        f("revision", "REV"),
        fk("operator_id", "operators.operator_id"),
        fk("parent_managed_session_id", "managed_identity_sessions.managed_session_id"),
        fk("completed_managed_session_id", "managed_identity_sessions.managed_session_id"),
        c("purpose", "operator_login admin_login renewal recent_auth"),
        c("method", "google email_link google_totp"),
        c("state", "pending verified completed failed superseded expired"),
        *_checks(
            "created_at<expires_at AND expires_at<=created_at+900000",
            "(source_attempt_id IS NULL)=(source_browser_hash IS NULL)",
            "purpose NOT IN ('operator_login','renewal') OR operator_id IS NOT NULL",
            "(operator_id IS NULL AND source_attempt_id IS NULL AND method='google_totp') OR "
            "(operator_id IS NOT NULL AND source_attempt_id IS NOT NULL "
            "AND method!='google_totp' AND purpose!='admin_login')",
            "purpose NOT IN ('renewal','recent_auth') OR parent_managed_session_id IS NOT NULL",
            "completed_managed_session_id IS NULL OR (state='completed' AND method='google')",
            "(purpose='recent_auth')=(confirmed_request_hash IS NOT NULL)",
            "method!='email_link' OR email_key IS NOT NULL",
            "(delivery_attempts=0 AND last_delivery_at IS NULL AND last_delivery_code IS NULL) OR "
            "(delivery_attempts>0 AND method='email_link' AND last_delivery_at IS NOT NULL "
            "AND created_at<=last_delivery_at AND last_delivery_at<expires_at)",
            "last_delivery_code IS NULL OR last_delivery_code IN ('sent','unknown','rejected')",
            "substr(return_path,1,1)='/' AND instr(return_path,'//')=0 "
            "AND instr(return_path,'?')=0 AND instr(return_path,'#')=0",
        ),
    )
    op.create_index("login_attempts_state", "login_attempts", ["state", "expires_at", "attempt_id"])
    op.create_index(
        "login_attempts_operator", "login_attempts", ["operator_id", "created_at", "attempt_id"]
    )


def _continuations():
    op.create_table(
        "email_continuations",
        f("continuation_id", "ID", primary=True),
        f("original_attempt_id", "ID", unique=True),
        f("code_hash", "HASH", unique=True),
        f("central_browser_hash", "HASH"),
        f("operator_id", "ID"),
        f("target_origin", "ORIGIN"),
        f("access_epoch", "REV"),
        f("managed_session_id", "ID", nullable=True),
        f("replacement_attempt_id", "ID", nullable=True, unique=True),
        f("source_attempt_id", "ID", nullable=True),
        f("source_binding_hash", "HASH", nullable=True),
        f("handoff_id", "ID", nullable=True, unique=True),
        f("state", "CODE"),
        f("created_at", "TIME"),
        f("expires_at", "TIME"),
        f("revision", "REV"),
        fk("original_attempt_id", "login_attempts.attempt_id"),
        fk("replacement_attempt_id", "login_attempts.attempt_id"),
        fk("managed_session_id", "managed_identity_sessions.managed_session_id"),
        fk("operator_id", "operators.operator_id"),
        fk("handoff_id", "login_handoffs.handoff_id"),
        c("state", "verifying unknown verified paired completed rejected expired"),
        *_checks(
            "created_at<expires_at AND expires_at<=created_at+300000",
            "(replacement_attempt_id IS NULL)=(source_attempt_id IS NULL) AND "
            "(replacement_attempt_id IS NULL)=(source_binding_hash IS NULL)",
            "state NOT IN ('verified','paired','completed') OR managed_session_id IS NOT NULL",
            "state NOT IN ('paired','completed') OR replacement_attempt_id IS NOT NULL",
            "replacement_attempt_id IS NULL OR (replacement_attempt_id!=original_attempt_id "
            "AND managed_session_id IS NOT NULL)",
            "state NOT IN ('verifying','verified') OR "
            "(replacement_attempt_id IS NULL AND handoff_id IS NULL)",
            "state!='completed' OR handoff_id IS NOT NULL",
            "handoff_id IS NULL OR replacement_attempt_id IS NOT NULL",
        ),
    )
    op.create_index(
        "email_continuations_state",
        "email_continuations",
        ["state", "expires_at", "continuation_id"],
    )
    op.create_index(
        "email_continuations_operator",
        "email_continuations",
        ["operator_id", "created_at", "continuation_id"],
    )


def _identity_commands():
    op.create_table(
        "identity_commands",
        f("operation_id", "ID", primary=True),
        f("kind", "CODE"),
        f("idempotency_key", "KEY"),
        f("request_hash", "HASH"),
        f("operator_id", "ID", nullable=True),
        f("managed_session_id", "ID"),
        f("attempt_id", "ID", nullable=True),
        f("access_epoch", "REV", nullable=True),
        f("state", "CODE"),
        f("result_json", "JSON", nullable=True),
        f("source_receipt_ref", "REF", nullable=True),
        f("created_at", "TIME"),
        f("updated_at", "TIME"),
        f("revision", "REV"),
        fk("operator_id", "operators.operator_id"),
        fk("managed_session_id", "managed_identity_sessions.managed_session_id"),
        fk("attempt_id", "login_attempts.attempt_id"),
        c(
            "kind",
            "claim pair_email_continuation issue_handoff redeem_handoff renew_session "
            "revoke_session revoke_all recent_auth",
        ),
        c("state", "pending unknown succeeded rejected"),
        sa.UniqueConstraint("kind", "idempotency_key"),
        *_checks(
            "(operator_id IS NULL)=(access_epoch IS NULL)",
            "kind NOT IN ('claim','pair_email_continuation','issue_handoff','redeem_handoff',"
            "'renew_session') OR (attempt_id IS NOT NULL AND operator_id IS NOT NULL)",
            "updated_at>=created_at",
            "(state='succeeded')=(result_json IS NOT NULL)",
        ),
    )
    op.create_index(
        "identity_commands_state", "identity_commands", ["state", "updated_at", "operation_id"]
    )
    op.create_index(
        "identity_commands_operator",
        "identity_commands",
        ["operator_id", "created_at", "operation_id"],
    )


def _guard(table, label, condition):
    op.execute(
        f"CREATE TRIGGER {table}_{label} BEFORE UPDATE ON {table} WHEN {condition} "
        "BEGIN SELECT RAISE(ABORT, 'immutable identity evidence'); END"
    )


def _once(table, columns):
    for column in columns.split():
        _guard(
            table,
            column + "_once",
            f"OLD.{column} IS NOT NULL AND NEW.{column} IS NOT OLD.{column}",
        )


def _identity_guards():
    intents = {
        "login_attempts": "attempt_id purpose operator_id parent_managed_session_id "
        "source_attempt_id source_browser_hash central_browser_hash method target_origin "
        "return_path confirmed_request_hash created_at expires_at",
        "email_continuations": "continuation_id original_attempt_id code_hash "
        "central_browser_hash operator_id target_origin access_epoch created_at expires_at",
        "managed_identity_sessions": "managed_session_id cookie_hash purpose operator_id issuer "
        "subject email_key method authenticated_at mfa_verified_at issued_at "
        "provider_valid_until remembered_until",
        "identity_commands": "operation_id kind idempotency_key request_hash operator_id "
        "managed_session_id attempt_id access_epoch created_at",
        "login_handoffs": "handoff_id operator_id browser_state_hash nonce_hash target_origin "
        "assignment_revision access_epoch expires_at created_at attempt_id managed_session_id "
        "identity_operation_id",
        "admin_sessions": "session_hash principal_id csrf_hash generation authenticated_at "
        "mfa_verified_at expires_at managed_session_id managed_valid_until",
    }
    for table, columns in intents.items():
        helpers["immutable"](op, table, columns, retain=False)
    terminals = {
        "login_attempts": "'completed','failed','superseded','expired'",
        "email_continuations": "'completed','rejected','expired'",
        "identity_commands": "'succeeded','rejected'",
        "login_handoffs": "'redeemed','expired'",
    }
    for table, states in terminals.items():
        _guard(table, "terminal", f"OLD.state IN ({states})")
    _once(
        "email_continuations",
        "managed_session_id replacement_attempt_id source_attempt_id "
        "source_binding_hash handoff_id",
    )
    _once("login_handoffs", "issuer subject code_hash redeemed_at source_receipt_ref")
    _once("identity_commands", "source_receipt_ref")
    _once("login_attempts", "completed_managed_session_id")
    for table in ("admin_sessions", "managed_identity_sessions"):
        _once(table, "revoked_at")
    _guard("login_attempts", "progress", "OLD.state='verified' AND NEW.state='pending'")
    _guard(
        "login_attempts",
        "delivery",
        "NEW.delivery_attempts<OLD.delivery_attempts OR "
        "(OLD.last_delivery_at IS NOT NULL AND "
        "(NEW.last_delivery_at IS NULL OR NEW.last_delivery_at<OLD.last_delivery_at))",
    )
    _guard(
        "email_continuations",
        "progress",
        "(OLD.managed_session_id IS NOT NULL AND NEW.state='verifying') OR "
        "(OLD.replacement_attempt_id IS NOT NULL AND NEW.state IN ('verifying','verified'))",
    )
    _guard(
        "login_handoffs",
        "progress",
        "(OLD.state='issued' AND NEW.state='initiated') OR "
        "(OLD.state='redeeming' AND NEW.state IN ('initiated','issued'))",
    )
    _guard(
        "managed_identity_sessions",
        "observation",
        "NEW.revocation_checked_at<OLD.revocation_checked_at OR "
        "NEW.revocation_valid_until<OLD.revocation_valid_until",
    )
    _identity_reverse_indexes()
    _result_guards()


def _identity_reverse_indexes():
    references = {
        "login_attempts": "parent_managed_session_id completed_managed_session_id",
        "identity_commands": "attempt_id managed_session_id",
        "login_handoffs": "attempt_id managed_session_id identity_operation_id",
        "email_continuations": "managed_session_id",
        "admin_sessions": "managed_session_id",
    }
    for table, columns in references.items():
        for column in columns.split():
            op.create_index(f"{table}_{column}", table, [column])


def _result_guards():
    # Closed result vocabulary: schema checks cannot verify a remote source receipt.
    valid = (
        "json_valid(NEW.result_json) AND json_type(NEW.result_json)='object' "
        "AND json_extract(NEW.result_json,'$.version') IS 1 "
        "AND json_type(NEW.result_json,'$.version')='integer' "
        "AND json_extract(NEW.result_json,'$.kind') IS NEW.kind "
        "AND json_type(NEW.result_json,'$.result_id')='text' "
        "AND length(json_extract(NEW.result_json,'$.result_id'))=36 "
        "AND substr(json_extract(NEW.result_json,'$.result_id'),9,1)='-' "
        "AND substr(json_extract(NEW.result_json,'$.result_id'),14,1)='-' "
        "AND substr(json_extract(NEW.result_json,'$.result_id'),19,1)='-' "
        "AND substr(json_extract(NEW.result_json,'$.result_id'),24,1)='-' "
        "AND length(replace(json_extract(NEW.result_json,'$.result_id'),'-',''))=32 "
        "AND replace(json_extract(NEW.result_json,'$.result_id'),'-','') "
        "NOT GLOB '*[^0-9a-f]*' "
        "AND json_type(NEW.result_json,'$.source_receipt_ref') IS NOT NULL "
        "AND json_extract(NEW.result_json,'$.source_receipt_ref') IS NEW.source_receipt_ref "
        "AND (SELECT count(*) FROM json_each(NEW.result_json))=4 "
        "AND NOT EXISTS (SELECT 1 FROM json_each(NEW.result_json) "
        "WHERE key NOT IN ('version','kind','result_id','source_receipt_ref'))"
    )
    for action in ("INSERT", "UPDATE"):
        op.execute(
            f"CREATE TRIGGER identity_commands_result_{action.lower()} BEFORE {action} "
            "ON identity_commands WHEN NEW.result_json IS NOT NULL AND "
            f"COALESCE(({valid}),0)=0 BEGIN SELECT RAISE(ABORT, 'invalid identity result'); END"
        )


def _mail_reservations():
    table = "identity_mail_reservations"
    op.create_table(
        table,
        f("operation_id", "ID", primary=True),
        f("deployment_id", "ID"),
        f("scope", "JSON"),
        f("kind", "CODE"),
        f("idempotency_key", "KEY"),
        f("request_hash", "HASH"),
        f("destination_hash", "HASH", nullable=True),
        f("network_hash", "HASH", nullable=True),
        f("reserved_at", "TIME"),
        f("redact_after", "TIME"),
        sa.UniqueConstraint("deployment_id", "scope", "kind", "idempotency_key"),
        sa.CheckConstraint("redact_after=reserved_at+90000000", name="ck_mail_retention"),
        sa.CheckConstraint(
            "(destination_hash IS NULL)=(network_hash IS NULL)", name="ck_mail_redaction"
        ),
    )
    for suffix, columns in {
        "destination": ["deployment_id", "destination_hash", "reserved_at"],
        "network": ["deployment_id", "network_hash", "reserved_at"],
        "day": ["deployment_id", "reserved_at"],
        "cleanup": ["deployment_id", "redact_after", "operation_id"],
    }.items():
        op.create_index(
            table + "_" + suffix,
            table,
            columns,
            sqlite_where=sa.text("destination_hash IS NOT NULL") if suffix == "cleanup" else None,
        )
    helpers["immutable"](
        op,
        table,
        "operation_id deployment_id scope kind idempotency_key request_hash "
        "reserved_at redact_after",
    )
    _guard(
        table,
        "digest_immutable",
        "(NEW.destination_hash IS NOT OLD.destination_hash OR "
        "NEW.network_hash IS NOT OLD.network_hash) AND NOT "
        "(OLD.destination_hash IS NOT NULL AND NEW.destination_hash IS NULL "
        "AND NEW.network_hash IS NULL)",
    )

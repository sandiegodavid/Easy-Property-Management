"""Complete greenfield source access baseline; no identity, policy or session seeds."""

from pathlib import Path
import runpy

from alembic import op
import sqlalchemy as sa

revision = "access_0001_initial"
down_revision = None
branch_labels = None
depends_on = None
TABLES = (
    "access_meta",
    "access_sessions",
    "access_receipts",
    "access_audit",
    "usage_state",
    "usage_reservations",
    "draft_leases",
    "source_login_attempts",
    "source_recent_challenges",
)
helpers = runpy.run_path(str(Path(__file__).resolve().parents[2] / "hosted_ddl.py"))
f = helpers["field"]
c = helpers["choices"]
fk = helpers["foreign"]


def upgrade():
    _meta()
    _sessions()
    _receipts()
    _usage()
    _attempts()
    _recent_challenges()
    _guards()


def _meta():
    op.create_table(
        "access_meta",
        f("id", "POSITIVE", primary=True),
        f("deployment_id", "ID"),
        f("operator_id", "ID", unique=True),
        f("workspace_id", "ID", unique=True),
        f("binding_id", "ID"),
        f("resource_generation", "REV"),
        f("issuer", "REF"),
        sa.Column("subject", sa.Text(), nullable=True),
        f("email_key", "EMAIL"),
        f("effective_access", "CODE"),
        f("access_epoch", "REV"),
        f("session_generation", "REV"),
        f("not_before", "TIME"),
        f("effective_policy_id", "ID"),
        f("usable_bytes", "POSITIVE"),
        f("policy_revision", "REV"),
        f("maintenance_operation_id", "ID", nullable=True),
        f("restore_generation", "REV"),
        f("revision", "REV"),
        sa.CheckConstraint("id=1", name="ck_singleton"),
        sa.CheckConstraint(
            "subject IS NULL OR (typeof(subject)='text' AND length(subject) BETWEEN 1 AND 1024)",
            name="ck_subject",
        ),
        c("effective_access", "disabled enabled"),
        sa.CheckConstraint(
            "effective_access!='enabled' OR (subject IS NOT NULL AND binding_id IS NOT NULL)",
            name="ck_enabled_identity",
        ),
    )


def _sessions():
    op.create_table(
        "access_sessions",
        f("session_hash", "HASH", primary=True),
        f("csrf_hash", "HASH"),
        sa.Column("actor_subject", sa.Text(), nullable=False),
        f("handoff_id", "ID", unique=True),
        f("generation", "REV"),
        f("access_epoch", "REV"),
        f("issued_at", "TIME"),
        f("expires_at", "TIME"),
        f("managed_valid_until", "TIME"),
        f("last_seen_at", "TIME"),
        f("revoked_at", "TIME", nullable=True),
        f("session_id", "ID", unique=True),
        f("managed_session_id", "ID"),
        f("managed_observation_revision", "REV"),
        f("revocation_valid_until", "TIME"),
        f("remembered_until", "TIME"),
        f("remembered", "BOOLEAN", default=0),
        f("display_label", "NAME"),
        f("renewed_from_session_id", "ID", nullable=True, unique=True),
        fk("renewed_from_session_id", "access_sessions.session_id"),
        sa.CheckConstraint(
            "typeof(actor_subject)='text' AND length(actor_subject) BETWEEN 1 AND 1024",
            name="ck_actor_subject",
        ),
        sa.CheckConstraint(
            "issued_at<remembered_until AND remembered_until-issued_at<=2592000000 "
            "AND issued_at<expires_at AND expires_at<=remembered_until "
            "AND expires_at<=managed_valid_until AND issued_at<revocation_valid_until "
            "AND revocation_valid_until<=managed_valid_until",
            name="ck_session_lifetime",
        ),
        sa.CheckConstraint("last_seen_at>=issued_at", name="ck_last_seen"),
        sa.CheckConstraint("revoked_at IS NULL OR revoked_at>=issued_at", name="ck_revoked"),
        sa.CheckConstraint(
            "renewed_from_session_id IS NULL OR renewed_from_session_id!=session_id",
            name="ck_not_self_renewal",
        ),
        sa.CheckConstraint(
            "display_label NOT GLOB '*[' || char(1) || '-' || char(31) || char(127) || '<>]*' "
            "AND instr(display_label,char(0))=0",
            name="ck_safe_label",
        ),
    )
    op.create_index(
        "access_sessions_live", "access_sessions", ["generation", "revoked_at", "expires_at"]
    )
    op.create_index("access_sessions_expiry", "access_sessions", ["expires_at"])
    op.create_index("access_sessions_managed", "access_sessions", ["managed_session_id"])
    op.create_table(
        "draft_leases",
        f("record_id", "ID", primary=True),
        f("session_hash", "HASH"),
        f("lease_token_hash", "HASH", unique=True),
        f("access_epoch", "REV"),
        f("restore_generation", "REV"),
        f("expires_at", "TIME"),
        f("renewed_at", "TIME"),
        sa.CheckConstraint("expires_at>renewed_at", name="ck_lease_lifetime"),
    )
    op.create_index("draft_leases_expiry", "draft_leases", ["expires_at"])
    op.create_index("draft_leases_session", "draft_leases", ["session_hash"])


def _receipts():
    op.create_table(
        "access_receipts",
        f("operation_id", "ID", primary=True),
        f("idempotency_key", "KEY", nullable=True),
        f("request_hash", "HASH"),
        f("kind", "CODE"),
        f("access_epoch", "REV"),
        f("source_revision", "REV"),
        f("result_json", "JSON"),
        f("recorded_at", "TIME"),
        sa.UniqueConstraint("kind", "idempotency_key"),
        c(
            "kind",
            "initialize_binding enable disable revoke_sessions rebind claim "
            "maintenance_fence restore_binding apply_policy "
            "issue_session refresh_session revoke_session",
        ),
    )
    op.create_table(
        "access_audit",
        f("audit_id", "ID", primary=True),
        f("operation_id", "ID", nullable=True),
        f("action", "CODE"),
        f("actor_ref", "REF"),
        f("recorded_at", "TIME"),
        f("safe_facts_json", "AUDIT_JSON"),
        fk("operation_id", "access_receipts.operation_id"),
    )
    op.create_index("access_audit_operation", "access_audit", ["operation_id"])
    op.create_index("access_audit_recorded", "access_audit", ["recorded_at", "audit_id"])


def _usage():
    op.create_table(
        "usage_state",
        f("id", "POSITIVE", primary=True),
        f("business_revision", "REF"),
        f("committed_db_bytes", "COUNT"),
        f("retained_file_bytes", "COUNT"),
        f("observed_at", "TIME"),
        f("measurement_version", "REF"),
        f("revision", "REV"),
        sa.CheckConstraint("id=1", name="ck_singleton"),
    )
    op.create_table(
        "usage_reservations",
        f("reservation_id", "ID", primary=True),
        f("operation_id", "ID", unique=True),
        f("request_hash", "HASH"),
        f("reserved_bytes", "POSITIVE"),
        f("purpose", "CODE"),
        f("source_epoch", "REV"),
        f("state", "CODE"),
        f("created_at", "TIME"),
        f("updated_at", "TIME"),
        f("result_revision", "REF", nullable=True),
        c("state", "held committed released unknown"),
        sa.CheckConstraint("updated_at>=created_at", name="ck_reservation_time"),
    )
    op.create_index(
        "usage_reservations_state", "usage_reservations", ["state", "created_at", "reservation_id"]
    )


def _attempts():
    op.create_table(
        "source_login_attempts",
        f("attempt_id", "ID", primary=True),
        f("browser_challenge_hash", "HASH", unique=True),
        f("access_epoch", "REV"),
        f("resource_generation", "REV"),
        f("return_path", "TEXT"),
        f("remembered", "BOOLEAN"),
        f("renewal_session_id", "ID", nullable=True),
        f("state", "CODE"),
        f("handoff_id", "ID", nullable=True, unique=True),
        f("continuation_id", "ID", nullable=True),
        f("binding_assertion_hash", "HASH", nullable=True),
        f("binding_expires_at", "TIME", nullable=True),
        f("created_at", "TIME"),
        f("expires_at", "TIME"),
        f("revision", "REV"),
        fk("renewal_session_id", "access_sessions.session_id"),
        c("state", "pending redeeming completed expired"),
        sa.CheckConstraint(
            "expires_at>created_at AND expires_at-created_at<=900000",
            name="ck_attempt_lifetime",
        ),
        sa.CheckConstraint(
            "(binding_assertion_hash IS NULL AND binding_expires_at IS NULL) OR "
            "(binding_assertion_hash IS NOT NULL AND binding_expires_at IS NOT NULL "
            "AND continuation_id IS NOT NULL AND binding_expires_at>created_at "
            "AND binding_expires_at<=expires_at)",
            name="ck_attempt_binding",
        ),
        sa.CheckConstraint(
            "state NOT IN ('redeeming','completed') OR (handoff_id IS NOT NULL AND "
            "(continuation_id IS NULL OR binding_assertion_hash IS NOT NULL))",
            name="ck_attempt_redemption",
        ),
        sa.CheckConstraint(
            "substr(return_path,1,1)='/' AND instr(return_path,'//')=0 "
            "AND instr(return_path,char(92))=0 AND instr(return_path,'?')=0 "
            "AND instr(return_path,'#')=0",
            name="ck_relative_return_path",
        ),
    )
    op.create_index(
        "source_login_attempts_state",
        "source_login_attempts",
        ["state", "expires_at", "attempt_id"],
    )
    op.create_index(
        "source_login_attempts_continuation", "source_login_attempts", ["continuation_id"]
    )
    op.create_index(
        "source_login_attempts_renewal", "source_login_attempts", ["renewal_session_id"]
    )


def _recent_challenges():
    op.create_table(
        "source_recent_challenges",
        f("challenge_id", "ID", primary=True),
        f("session_id", "ID"),
        f("request_hash", "HASH"),
        f("created_at", "TIME"),
        f("expires_at", "TIME"),
        f("consumed_at", "TIME", nullable=True),
        fk("session_id", "access_sessions.session_id"),
        sa.CheckConstraint(
            "expires_at>created_at AND expires_at-created_at<=300000", name="ck_recent_lifetime"
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR (created_at<=consumed_at AND consumed_at<expires_at)",
            name="ck_recent_consumption",
        ),
    )
    op.create_index("source_recent_challenges_expiry", "source_recent_challenges", ["expires_at"])
    op.create_index(
        "source_recent_challenges_session", "source_recent_challenges", ["session_id", "expires_at"]
    )


def _guards():
    helpers["immutable"](op, "access_receipts")
    helpers["immutable"](op, "access_audit")
    helpers["immutable"](
        op,
        "access_sessions",
        "session_hash csrf_hash actor_subject handoff_id generation access_epoch issued_at "
        "expires_at managed_valid_until session_id managed_session_id remembered_until "
        "remembered display_label renewed_from_session_id",
        retain=False,
    )
    helpers["immutable"](
        op,
        "source_login_attempts",
        "attempt_id browser_challenge_hash access_epoch resource_generation return_path "
        "remembered renewal_session_id created_at expires_at",
        retain=False,
    )
    helpers["immutable"](
        op,
        "source_recent_challenges",
        "challenge_id session_id request_hash created_at expires_at",
        retain=False,
    )
    op.execute(
        "CREATE TRIGGER source_recent_challenges_single_use "
        "BEFORE UPDATE ON source_recent_challenges "
        "WHEN OLD.consumed_at IS NOT NULL AND NEW.consumed_at IS NOT OLD.consumed_at "
        "BEGIN SELECT RAISE(ABORT, 'recent authentication is single use'); END"
    )
    op.execute(
        "CREATE TRIGGER access_meta_initial_disabled BEFORE INSERT ON access_meta "
        "WHEN NEW.effective_access!='disabled' OR NEW.subject IS NOT NULL "
        "BEGIN SELECT RAISE(ABORT, 'new source must be disabled and unbound'); END"
    )


def downgrade():
    raise RuntimeError("Greenfield hosted stores do not support downgrade.")

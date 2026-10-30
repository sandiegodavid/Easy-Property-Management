"""The sole Alembic baseline for the non-portable hosted administrative store."""

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

REVISION = "hosted_0001"


def initialize_schema(connection) -> None:
    operations = Operations(MigrationContext.configure(connection))
    operations.create_table(
        "hosted_operator",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("workspace_id", sa.String, nullable=False),
        sa.Column("issuer", sa.String, nullable=False),
        sa.Column("email", sa.String, nullable=False),
        sa.Column("subject", sa.String, nullable=True),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("generation", sa.Integer, nullable=False),
        sa.Column("not_before", sa.Float, nullable=False),
        sa.Column("restore_marker", sa.String, nullable=True),
        sa.Column("admin_revision", sa.Integer, nullable=False),
        sa.Column("binding_revision", sa.Integer, nullable=False),
        sa.Column("admin_fence", sa.Integer, nullable=False),
        sa.Column("binding_digest", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "admin_revision >= 0 AND binding_revision >= 0 AND admin_fence >= 0 AND generation >= 0"
        ),
    )
    operations.create_table(
        "hosted_admin_receipt",
        sa.Column("operation_id", sa.String, primary_key=True),
        sa.Column("semantic_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text, nullable=False),
        sa.CheckConstraint("length(semantic_hash) = 64 AND semantic_hash NOT GLOB '*[^a-f0-9]*'"),
    )
    operations.create_table(
        "hosted_admin_audit",
        sa.Column(
            "operation_id",
            sa.String,
            sa.ForeignKey("hosted_admin_receipt.operation_id"),
            primary_key=True,
        ),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("authority_reference", sa.String, nullable=False),
        sa.Column("recorded_at", sa.Float, nullable=False),
        sa.Column("before_json", sa.Text, nullable=False),
        sa.Column("after_json", sa.Text, nullable=False),
        sa.CheckConstraint(
            "action IN ('approve','enable','complete_onboarding','disable','revoke','rebind','restore_reset','renew','replace_email')"
        ),
    )
    operations.create_table(
        "hosted_enrollment",
        sa.Column("subject", sa.String, primary_key=True),
        sa.Column("email", sa.String, nullable=False),
        sa.Column("received_at", sa.Float, nullable=False),
    )
    operations.create_table(
        "hosted_session",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("operator_id", sa.String, sa.ForeignKey("hosted_operator.id"), nullable=False),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("assertion_hash", sa.String(64), nullable=False),
        sa.Column("assertion_expiry", sa.Float, nullable=False),
        sa.Column("generation", sa.Integer, nullable=False),
        sa.Column("expires_at", sa.Float, nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False),
    )
    operations.create_table(
        "hosted_blocked_assertion",
        sa.Column("fingerprint", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.Float, nullable=False),
    )
    operations.create_table(
        "hosted_draft_lease",
        sa.Column("record_id", sa.String, primary_key=True),
        sa.Column("session_reference", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.Float, nullable=False),
        sa.Column("renewed_at", sa.Float, nullable=False),
    )
    operations.create_table(
        "alembic_version", sa.Column("version_num", sa.String(32), primary_key=True)
    )
    version = sa.table("alembic_version", sa.column("version_num"))
    connection.execute(version.insert().values(version_num=REVISION))
    for table in ("hosted_admin_receipt", "hosted_admin_audit"):
        for verb in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER {table}_no_{verb.lower()} BEFORE {verb} ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'Administrative history is immutable'); END"
            )


def validate_schema(connection):
    engine = sa.create_engine("sqlite://")
    query = "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
    try:
        with engine.begin() as expected:
            initialize_schema(expected)
            if connection.exec_driver_sql(query).all() != expected.exec_driver_sql(query).all():
                raise ValueError("Hosted access schema differs from the current format.")
    finally:
        engine.dispose()

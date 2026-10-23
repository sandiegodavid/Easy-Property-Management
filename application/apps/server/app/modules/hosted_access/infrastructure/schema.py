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

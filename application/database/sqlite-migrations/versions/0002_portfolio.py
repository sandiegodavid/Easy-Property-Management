"""Add the current PORT-001 portfolio ownership foundation.

Revision ID: 0002_portfolio
Revises: 0001_initial_schema
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_portfolio"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parties",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("party_kind", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("email", sa.String()),
        sa.Column("phone", sa.String()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("archived_at", sa.String()),
        sa.CheckConstraint("party_kind IN ('individual', 'organization')"),
        sa.CheckConstraint("length(trim(display_name)) > 0"),
    )
    op.create_index("parties_active_name", "parties", ["archived_at", "display_name"])
    op.create_table(
        "properties",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("address_line_1", sa.String(), nullable=False),
        sa.Column("address_line_2", sa.String()),
        sa.Column("city", sa.String(), nullable=False),
        sa.Column("region", sa.String()),
        sa.Column("postal_code", sa.String()),
        sa.Column("country_code", sa.String(), nullable=False),
        sa.Column("notes", sa.String()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("archived_at", sa.String()),
        sa.CheckConstraint("status IN ('active', 'archived')"),
        sa.CheckConstraint("length(trim(display_name)) > 0"),
        sa.CheckConstraint("length(trim(address_line_1)) > 0"),
        sa.CheckConstraint("length(trim(city)) > 0"),
        sa.CheckConstraint("length(trim(country_code)) = 2"),
    )
    op.create_index("properties_status_name", "properties", ["status", "display_name"])
    op.create_table(
        "property_ownerships",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("owner_kind", sa.String(), nullable=False),
        sa.Column("party_id", sa.String(), sa.ForeignKey("parties.id")),
        sa.Column("starts_on", sa.String(), nullable=False),
        sa.Column("ends_on", sa.String()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("ended_at", sa.String()),
        sa.CheckConstraint("owner_kind IN ('local_operator', 'client_owner')"),
        sa.CheckConstraint("(owner_kind = 'local_operator' AND party_id IS NULL) OR (owner_kind = 'client_owner' AND party_id IS NOT NULL)"),
        sa.CheckConstraint("ends_on IS NULL OR ends_on >= starts_on"),
    )
    op.create_index("property_ownerships_property_active", "property_ownerships", ["property_id", "ends_on"])
    op.create_index("property_ownerships_party_active", "property_ownerships", ["party_id", "ends_on"])
    op.execute("CREATE UNIQUE INDEX property_ownerships_one_active_operator ON property_ownerships(property_id) WHERE owner_kind = 'local_operator' AND ends_on IS NULL")
    op.execute("CREATE UNIQUE INDEX property_ownerships_one_active_client ON property_ownerships(property_id, party_id) WHERE owner_kind = 'client_owner' AND ends_on IS NULL")


def downgrade() -> None:
    op.drop_table("property_ownerships")
    op.drop_table("properties")
    op.drop_table("parties")

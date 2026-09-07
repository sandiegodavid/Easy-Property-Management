"""Add PORT-002 property classification and rentable spaces.

Revision ID: 0003_portfolio_inventory
Revises: 0002_portfolio
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_portfolio_inventory"
down_revision = "0002_portfolio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite can add a checked, non-null column directly.  Avoid batch table
    # recreation, which cannot faithfully retain PORT-001's unnamed checks.
    op.execute(
        "ALTER TABLE properties ADD COLUMN property_type TEXT NOT NULL "
        "DEFAULT 'single_family_home' "
        "CHECK(property_type IN ('single_family_home', 'condo', 'townhome', 'office'))"
    )
    op.execute(
        "ALTER TABLE properties ADD COLUMN inventory_layout TEXT NOT NULL "
        "DEFAULT 'single_space' "
        "CHECK(inventory_layout IN ('single_space', 'whole_office', 'office_suites'))"
    )

    op.create_table(
        "spaces",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("space_kind", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("suite_or_floor", sa.String()),
        sa.Column("notes", sa.String()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("archived_at", sa.String()),
        sa.Column("archived_by_property_operation_id", sa.String()),
        sa.CheckConstraint("space_kind IN ('whole_home', 'whole_office', 'office_suite')"),
        sa.CheckConstraint("status IN ('active', 'archived')"),
        sa.CheckConstraint("length(trim(display_name)) > 0"),
    )
    op.create_index(
        "spaces_property_status_name",
        "spaces",
        ["property_id", "status", "display_name"],
    )
    op.execute(
        "CREATE UNIQUE INDEX spaces_one_active_name "
        "ON spaces(property_id, normalized_name) WHERE status = 'active'"
    )


def downgrade() -> None:
    op.drop_table("spaces")
    # SQLite does not support DROP COLUMN on all supported versions. PORT-002
    # is a forward-only local schema revision; downgrade is intentionally empty.

"""FILE-001 product schema.

Revision ID: 0001_file_records
"""
from alembic import op
import sqlalchemy as sa
revision = "0001_file_records"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("file_records", sa.Column("id", sa.String(), primary_key=True), sa.Column("original_name", sa.String(), nullable=False), sa.Column("media_type", sa.String(), nullable=False), sa.Column("size_bytes", sa.Integer(), nullable=False), sa.Column("content_sha256", sa.String(), nullable=False), sa.Column("relative_path", sa.String(), nullable=False), sa.Column("created_at", sa.String(), nullable=False), sa.CheckConstraint("size_bytes >= 0"))
    op.create_index("file_records_content", "file_records", ["content_sha256"])
    op.create_table("file_links", sa.Column("id", sa.String(), primary_key=True), sa.Column("file_id", sa.String(), sa.ForeignKey("file_records.id"), nullable=False), sa.Column("entity_type", sa.String(), nullable=False), sa.Column("entity_id", sa.String(), nullable=False), sa.Column("purpose", sa.String(), nullable=False), sa.Column("created_at", sa.String(), nullable=False))
    op.create_index("file_links_entity", "file_links", ["entity_type", "entity_id"])

def downgrade() -> None:
    op.drop_table("file_links"); op.drop_table("file_records")

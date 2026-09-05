"""Initial current schema for a new local workspace.

Revision ID: 0001_initial_schema
Revises: none
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("workspace_metadata", sa.Column("singleton", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.String(), nullable=False, unique=True), sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False), sa.CheckConstraint("singleton = 1"))
    op.create_table("audit_events", sa.Column("id", sa.String(), primary_key=True), sa.Column("occurred_at", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False), sa.Column("entity_id", sa.String(), nullable=False), sa.Column("action", sa.String(), nullable=False),
        sa.Column("before_snapshot", sa.String()), sa.Column("after_snapshot", sa.String()), sa.Column("changed_fields", sa.String(), nullable=False), sa.Column("reason", sa.String()),
        sa.Column("actor_kind", sa.String(), nullable=False), sa.Column("actor_reference", sa.String()), sa.Column("correlation_id", sa.String(), nullable=False), sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("length(trim(entity_type)) > 0"), sa.CheckConstraint("length(trim(entity_id)) > 0"), sa.CheckConstraint("length(trim(action)) > 0"),
        sa.CheckConstraint("actor_kind IN ('local_operator', 'system', 'connector', 'ai_assistant')"))
    op.create_index("audit_events_entity_time", "audit_events", ["entity_type", "entity_id", "occurred_at", "id"])
    op.create_index("audit_events_correlation", "audit_events", ["correlation_id", "occurred_at", "id"])
    op.create_index("audit_events_activity", "audit_events", ["occurred_at", "action", "actor_kind"])
    op.execute("CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END")
    op.execute("CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END")
    op.create_table("file_records", sa.Column("id", sa.String(), primary_key=True), sa.Column("original_name", sa.String(), nullable=False), sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False), sa.Column("content_sha256", sa.String(), nullable=False), sa.Column("relative_path", sa.String(), nullable=False), sa.Column("created_at", sa.String(), nullable=False), sa.CheckConstraint("size_bytes >= 0"))
    op.create_index("file_records_content", "file_records", ["content_sha256"])
    op.create_table("file_links", sa.Column("id", sa.String(), primary_key=True), sa.Column("file_id", sa.String(), sa.ForeignKey("file_records.id"), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False), sa.Column("entity_id", sa.String(), nullable=False), sa.Column("purpose", sa.String(), nullable=False), sa.Column("created_at", sa.String(), nullable=False))
    op.create_index("file_links_entity", "file_links", ["entity_type", "entity_id"])
    op.create_table("tasks", sa.Column("id", sa.String(), primary_key=True), sa.Column("title", sa.String(), nullable=False), sa.Column("notes", sa.String()), sa.Column("status", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False), sa.Column("due_at_utc", sa.String()), sa.Column("due_timezone", sa.String()), sa.Column("is_all_day", sa.Integer(), nullable=False),
        sa.Column("completed_at_utc", sa.String()), sa.Column("cancelled_at_utc", sa.String()), sa.Column("outcome_note", sa.String()), sa.Column("related_entity_type", sa.String()), sa.Column("related_entity_id", sa.String()), sa.Column("related_label", sa.String()),
        sa.Column("created_at_utc", sa.String(), nullable=False), sa.Column("updated_at_utc", sa.String(), nullable=False), sa.CheckConstraint("status IN ('open', 'in_progress', 'completed', 'cancelled')"), sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')"), sa.CheckConstraint("is_all_day IN (0, 1)"))
    op.create_index("tasks_status_due", "tasks", ["status", "due_at_utc"]); op.create_index("tasks_related_record", "tasks", ["related_entity_type", "related_entity_id"])
    op.create_table("task_reminders", sa.Column("id", sa.String(), primary_key=True), sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=False), sa.Column("remind_at_utc", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False), sa.Column("acknowledged_at_utc", sa.String()), sa.Column("dismissed_at_utc", sa.String()), sa.Column("created_at_utc", sa.String(), nullable=False), sa.CheckConstraint("status IN ('pending', 'acknowledged', 'dismissed')"))
    op.create_index("task_reminders_status_time", "task_reminders", ["status", "remind_at_utc"])


def downgrade() -> None:
    op.drop_table("task_reminders"); op.drop_table("tasks"); op.drop_table("file_links"); op.drop_table("file_records")
    op.execute("DROP TRIGGER audit_events_no_delete"); op.execute("DROP TRIGGER audit_events_no_update"); op.drop_table("audit_events"); op.drop_table("workspace_metadata")

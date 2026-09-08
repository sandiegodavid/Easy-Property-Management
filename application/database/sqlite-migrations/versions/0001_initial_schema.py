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
    op.create_table("parties", sa.Column("id", sa.String(), primary_key=True), sa.Column("party_kind", sa.String(), nullable=False), sa.Column("display_name", sa.String(), nullable=False), sa.Column("email", sa.String()), sa.Column("phone", sa.String()), sa.Column("created_at", sa.String(), nullable=False), sa.Column("updated_at", sa.String(), nullable=False), sa.Column("archived_at", sa.String()), sa.CheckConstraint("party_kind IN ('individual', 'organization')"), sa.CheckConstraint("length(trim(display_name)) > 0"))
    op.create_index("parties_active_name", "parties", ["archived_at", "display_name"])
    op.create_table("tenant_profiles", sa.Column("party_id", sa.String(), sa.ForeignKey("parties.id"), primary_key=True),
        sa.Column("preferred_contact_method_id", sa.String(), sa.ForeignKey("tenant_contact_methods.id")), sa.Column("do_not_contact", sa.Integer(), nullable=False), sa.Column("notes", sa.String()),
        sa.Column("created_at", sa.String(), nullable=False), sa.Column("updated_at", sa.String(), nullable=False), sa.Column("archived_at", sa.String()),
        sa.CheckConstraint("do_not_contact IN (0, 1)"))
    op.create_index("tenant_profiles_active_name", "tenant_profiles", ["archived_at"])
    op.create_table("tenant_contact_methods", sa.Column("id", sa.String(), primary_key=True), sa.Column("party_id", sa.String(), sa.ForeignKey("tenant_profiles.party_id"), nullable=False),
        sa.Column("method_kind", sa.String(), nullable=False), sa.Column("display_value", sa.String(), nullable=False), sa.Column("normalized_value", sa.String(), nullable=False), sa.Column("label", sa.String()),
        sa.Column("status", sa.String(), nullable=False), sa.Column("created_at", sa.String(), nullable=False), sa.Column("updated_at", sa.String(), nullable=False), sa.Column("archived_at", sa.String()),
        sa.CheckConstraint("method_kind IN ('email', 'phone')"), sa.CheckConstraint("status IN ('active', 'archived')"), sa.CheckConstraint("length(trim(display_value)) > 0"))
    op.create_index("tenant_contact_methods_party_status", "tenant_contact_methods", ["party_id", "status"])
    op.execute("CREATE UNIQUE INDEX tenant_contact_methods_one_active_value ON tenant_contact_methods(party_id, method_kind, normalized_value) WHERE status = 'active'")
    op.create_table("properties", sa.Column("id", sa.String(), primary_key=True), sa.Column("display_name", sa.String(), nullable=False), sa.Column("address_line_1", sa.String(), nullable=False), sa.Column("address_line_2", sa.String()), sa.Column("city", sa.String(), nullable=False), sa.Column("region", sa.String()), sa.Column("postal_code", sa.String()), sa.Column("country_code", sa.String(), nullable=False), sa.Column("notes", sa.String()), sa.Column("status", sa.String(), nullable=False), sa.Column("created_at", sa.String(), nullable=False), sa.Column("updated_at", sa.String(), nullable=False), sa.Column("archived_at", sa.String()), sa.Column("property_type", sa.String(), nullable=False), sa.Column("inventory_layout", sa.String(), nullable=False), sa.CheckConstraint("status IN ('active', 'archived')"), sa.CheckConstraint("property_type IN ('single_family_home', 'condo', 'townhome', 'office')"), sa.CheckConstraint("inventory_layout IN ('single_space', 'whole_office', 'office_suites')"), sa.CheckConstraint("length(trim(display_name)) > 0"), sa.CheckConstraint("length(trim(address_line_1)) > 0"), sa.CheckConstraint("length(trim(city)) > 0"), sa.CheckConstraint("length(trim(country_code)) = 2"))
    op.create_index("properties_status_name", "properties", ["status", "display_name"])
    op.create_table("property_ownerships", sa.Column("id", sa.String(), primary_key=True), sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id"), nullable=False), sa.Column("owner_kind", sa.String(), nullable=False), sa.Column("party_id", sa.String(), sa.ForeignKey("parties.id")), sa.Column("starts_on", sa.String(), nullable=False), sa.Column("ends_on", sa.String()), sa.Column("created_at", sa.String(), nullable=False), sa.Column("ended_at", sa.String()), sa.CheckConstraint("owner_kind IN ('local_operator', 'client_owner')"), sa.CheckConstraint("(owner_kind = 'local_operator' AND party_id IS NULL) OR (owner_kind = 'client_owner' AND party_id IS NOT NULL)"), sa.CheckConstraint("ends_on IS NULL OR ends_on >= starts_on"))
    op.create_index("property_ownerships_property_active", "property_ownerships", ["property_id", "ends_on"])
    op.create_index("property_ownerships_party_active", "property_ownerships", ["party_id", "ends_on"])
    op.execute("CREATE UNIQUE INDEX property_ownerships_one_active_operator ON property_ownerships(property_id) WHERE owner_kind = 'local_operator' AND ends_on IS NULL")
    op.execute("CREATE UNIQUE INDEX property_ownerships_one_active_client ON property_ownerships(property_id, party_id) WHERE owner_kind = 'client_owner' AND ends_on IS NULL")
    op.create_table("spaces", sa.Column("id", sa.String(), primary_key=True), sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id"), nullable=False), sa.Column("space_kind", sa.String(), nullable=False), sa.Column("display_name", sa.String(), nullable=False), sa.Column("normalized_name", sa.String(), nullable=False), sa.Column("suite_or_floor", sa.String()), sa.Column("notes", sa.String()), sa.Column("status", sa.String(), nullable=False), sa.Column("created_at", sa.String(), nullable=False), sa.Column("updated_at", sa.String(), nullable=False), sa.Column("archived_at", sa.String()), sa.Column("archived_by_property_operation_id", sa.String()), sa.CheckConstraint("space_kind IN ('whole_home', 'whole_office', 'office_suite')"), sa.CheckConstraint("status IN ('active', 'archived')"), sa.CheckConstraint("length(trim(display_name)) > 0"))
    op.create_index("spaces_property_status_name", "spaces", ["property_id", "status", "display_name"])
    op.execute("CREATE UNIQUE INDEX spaces_one_active_name ON spaces(property_id, normalized_name) WHERE status = 'active'")
    op.create_table("space_occupancy_periods", sa.Column("id", sa.String(), primary_key=True), sa.Column("space_id", sa.String(), sa.ForeignKey("spaces.id"), nullable=False), sa.Column("occupancy_status", sa.String(), nullable=False), sa.Column("starts_on", sa.String(), nullable=False), sa.Column("ends_on", sa.String()), sa.Column("record_state", sa.String(), nullable=False), sa.Column("superseded_by_id", sa.String(), sa.ForeignKey("space_occupancy_periods.id")), sa.Column("source_kind", sa.String(), nullable=False), sa.Column("source_id", sa.String()), sa.Column("note", sa.String()), sa.Column("created_at", sa.String(), nullable=False), sa.Column("ended_at", sa.String()), sa.Column("cancelled_at", sa.String()), sa.CheckConstraint("occupancy_status IN ('occupied', 'vacant', 'unknown')"), sa.CheckConstraint("record_state IN ('valid', 'cancelled', 'superseded')"), sa.CheckConstraint("ends_on IS NULL OR ends_on > starts_on"), sa.CheckConstraint("(source_kind = 'manual' AND source_id IS NULL) OR (source_kind = 'lease' AND source_id IS NOT NULL)"))
    op.create_index("space_occupancy_periods_space_dates", "space_occupancy_periods", ["space_id", "starts_on", "ends_on"])
    op.execute("CREATE UNIQUE INDEX space_occupancy_periods_one_open ON space_occupancy_periods(space_id) WHERE record_state = 'valid' AND ends_on IS NULL")
    op.create_table("space_availability", sa.Column("space_id", sa.String(), sa.ForeignKey("spaces.id"), primary_key=True), sa.Column("availability_status", sa.String(), nullable=False), sa.Column("available_on", sa.String()), sa.Column("source_kind", sa.String(), nullable=False), sa.Column("source_id", sa.String()), sa.Column("note", sa.String()), sa.Column("updated_at", sa.String(), nullable=False), sa.CheckConstraint("availability_status IN ('available_now', 'available_on', 'not_available', 'unknown')"), sa.CheckConstraint("(availability_status = 'available_on' AND available_on IS NOT NULL) OR (availability_status != 'available_on' AND available_on IS NULL)"), sa.CheckConstraint("(source_kind = 'manual' AND source_id IS NULL) OR (source_kind IN ('listing', 'lease') AND source_id IS NOT NULL)"))
    op.create_index("space_availability_status_date", "space_availability", ["availability_status", "available_on"])


def downgrade() -> None:
    op.drop_table("space_availability"); op.drop_table("space_occupancy_periods"); op.drop_table("spaces"); op.drop_table("property_ownerships"); op.drop_table("properties"); op.drop_table("tenant_contact_methods"); op.drop_table("tenant_profiles"); op.drop_table("parties")
    op.drop_table("task_reminders"); op.drop_table("tasks"); op.drop_table("file_links"); op.drop_table("file_records")
    op.execute("DROP TRIGGER audit_events_no_delete"); op.execute("DROP TRIGGER audit_events_no_update"); op.drop_table("audit_events"); op.drop_table("workspace_metadata")

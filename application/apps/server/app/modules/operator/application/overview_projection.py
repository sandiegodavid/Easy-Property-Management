"""Explicit metadata allowlists and typed route identities; no domain derivation."""

FIELDS = {
    "properties": (
        "id",
        "display_name",
        "status",
        "address_line_1",
        "city",
        "country_code",
        "time_zone",
    ),
    "spaces": (
        "id",
        "property_id",
        "display_name",
        "revision",
        "occupancy",
        "availability",
        "needs_attention",
    ),
    "relationships": (
        "id",
        "property_id",
        "property_name",
        "owner_kind",
        "party_id",
        "owner_name",
        "starts_on",
        "ends_on",
        "relationship_state",
    ),
    "leases": (
        "id",
        "property_id",
        "space_id",
        "lease_kind",
        "status",
        "contract_starts_on",
        "contract_ends_on",
        "occupancy_starts_on",
        "actual_move_out_on",
        "is_current",
    ),
    "tasks": (
        "id",
        "title",
        "status",
        "priority",
        "revision",
        "due_at_utc",
        "due_timezone",
        "is_all_day",
        "waiting_for_kind",
        "waiting_for_label",
        "follow_up_at_utc",
        "follow_up_timezone",
        "follow_up_state",
        "follow_up_due_today",
        "follow_up_actionable",
        "task_deadline_state",
        "as_of",
    ),
    "maintenance": ("id", "property_id", "space_id", "summary", "status", "priority", "category"),
    "communications": (
        "id",
        "subject",
        "channel",
        "direction",
        "status",
        "occurred_at_utc",
        "occurred_timezone",
    ),
    "concerns": (
        "id",
        "owner_party_id",
        "property_id",
        "summary",
        "status",
        "priority",
        "concern_type",
    ),
}
TARGETS = {
    "properties": "property",
    "spaces": "space",
    "relationships": "property",
    "leases": "lease",
    "tasks": "task",
    "maintenance": "maintenance_issue",
    "communications": "communication",
    "concerns": "owner_concern",
}


def item_view(section, row):
    result = {_camel(key): row[key] for key in FIELDS[section]}
    target_id = row["property_id"] if section == "relationships" else row["id"]
    result["target"] = {"entityType": TARGETS[section], "entityId": target_id}
    return result


def _camel(value):
    first, *rest = value.split("_")
    return first + "".join(word.title() for word in rest)

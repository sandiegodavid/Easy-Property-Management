"""Exact structure and retained-data validation for OWNER-004."""
from datetime import UTC, date, datetime
from json import loads
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, inspect, text
from app.platform.migration_errors import MigrationSchemaError
from .sqlalchemy_models import OwnerConcernFollowUpOperationModel, OwnerConcernModel
from ..domain.models import Concern

MODELS=(OwnerConcernModel,OwnerConcernFollowUpOperationModel)
TRIGGERS={"owner_concern_follow_up_operations_no_update":"CREATE TRIGGER owner_concern_follow_up_operations_no_update BEFORE UPDATE ON owner_concern_follow_up_operations BEGIN SELECT RAISE(ABORT, 'owner concern operations are immutable'); END","owner_concern_follow_up_operations_no_delete":"CREATE TRIGGER owner_concern_follow_up_operations_no_delete BEFORE DELETE ON owner_concern_follow_up_operations BEGIN SELECT RAISE(ABORT, 'owner concern operations are immutable'); END"}
def _sql(value):return " ".join(str(value).replace('"','').replace('`','').split()).casefold()
def validate_owner_concern_schema(connection):
    inspector=inspect(connection)
    for model in MODELS:
        table=model.__table__; actual={item["name"]:item for item in inspector.get_columns(table.name)}; expected={item.name:item for item in table.columns}
        if not inspector.has_table(table.name) or set(actual)!=set(expected):raise MigrationSchemaError("Owner-management columns are incompatible.")
        for name,column in expected.items():
            if str(actual[name]["type"]).upper()!=str(column.type).upper() or bool(actual[name]["nullable"])!=bool(column.nullable):raise MigrationSchemaError("Owner-management column definitions are incompatible.")
        if {item["name"] for item in inspector.get_columns(table.name) if item["primary_key"]}!={item.name for item in table.primary_key.columns}:raise MigrationSchemaError("Owner-management primary keys are incompatible.")
        expected_fk={(tuple(fk.parent.name for fk in item.elements),item.elements[0].column.table.name,tuple(fk.column.name for fk in item.elements)) for item in table.constraints if isinstance(item,ForeignKeyConstraint)};actual_fk={(tuple(item["constrained_columns"]),item["referred_table"],tuple(item["referred_columns"])) for item in inspector.get_foreign_keys(table.name)}
        if actual_fk!=expected_fk:raise MigrationSchemaError("Owner-management foreign keys are incompatible.")
        expected_index={item.name:(tuple(column.name for column in item.columns),bool(item.unique)) for item in table.indexes};actual_index={item["name"]:(tuple(item["column_names"]),bool(item.get("unique"))) for item in inspector.get_indexes(table.name)}
        if actual_index!=expected_index:raise MigrationSchemaError("Owner-management indexes are incompatible.")
        expected_unique={tuple(item.name for item in constraint.columns) for constraint in table.constraints if isinstance(constraint,UniqueConstraint)}|{(item.name,) for item in table.columns if item.unique};actual_unique={tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)}
        if actual_unique!=expected_unique:raise MigrationSchemaError("Owner-management unique constraints are incompatible.")
        if {_sql(item["sqltext"]) for item in inspector.get_check_constraints(table.name)}!={_sql(item.sqltext) for item in table.constraints if isinstance(item,CheckConstraint)}:raise MigrationSchemaError("Owner-management checks are incompatible.")
    actual={name:_sql(sql) for name,sql in connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='owner_concern_follow_up_operations'")}
    if actual!={name:_sql(sql) for name,sql in TRIGGERS.items()}:raise MigrationSchemaError("Owner-management operation triggers are incompatible.")
    _validate_data(connection)
def _validate_data(connection):
    if connection.execute(text("PRAGMA foreign_key_check")).first():raise MigrationSchemaError("Owner-management foreign-key references are invalid.")
    concerns=list(connection.execute(text("SELECT * FROM owner_concerns")).mappings());by_id={row["id"]:row for row in concerns}
    for row in concerns:
        for field in ("id","owner_party_id","property_id"): _uuid(row[field])
        for field in ("raised_at_utc","recorded_at_utc","updated_at_utc","resolved_at_utc","dismissed_at_utc"):
            if row[field] is not None:_timestamp(row[field])
        try:ZoneInfo(row["property_timezone_snapshot"])
        except (TypeError,ZoneInfoNotFoundError) as error:raise MigrationSchemaError("Owner concern property timezone is invalid.") from error
        if row["status"] in ("open","in_progress") and not connection.execute(text("SELECT 1 FROM properties WHERE id=:id AND status='active'"),{"id":row["property_id"]}).first():raise MigrationSchemaError("Archived properties cannot retain unresolved owner concerns.")
        if row["concern_type"] in ("lease","tenant","vacancy") and row["space_id"] is None:raise MigrationSchemaError("Owner concern type context is invalid.")
        if row["concern_type"] in ("lease","tenant") and row["lease_id"] is None:raise MigrationSchemaError("Owner concern lease context is invalid.")
        if row["concern_type"]=="tenant" and row["tenant_party_id"] is None:raise MigrationSchemaError("Owner concern tenant context is invalid.")
        if row["space_id"] and not connection.execute(text("SELECT 1 FROM spaces WHERE id=:space AND property_id=:property"),{"space":row["space_id"],"property":row["property_id"]}).first():raise MigrationSchemaError("Owner concern space context is invalid.")
        if row["lease_id"] and not connection.execute(text("SELECT 1 FROM leases WHERE id=:lease AND space_id=:space"),{"lease":row["lease_id"],"space":row["space_id"]}).first():raise MigrationSchemaError("Owner concern lease context is invalid.")
        if row["originating_communication_id"] and not connection.execute(text("""SELECT 1 FROM communications source
            WHERE source.id=:id AND source.direction='inbound' AND (
              source.status='recorded' OR (source.status='superseded' AND source.superseded_by_communication_id IS NOT NULL
                AND EXISTS(SELECT 1 FROM communications correction WHERE correction.id=source.superseded_by_communication_id AND correction.supersedes_communication_id=source.id AND correction.status='recorded')))
        """),{"id":row["originating_communication_id"]}).first():raise MigrationSchemaError("Owner concern originating communication is invalid.")
        if row["originating_communication_id"] and not connection.execute(text("""SELECT 1 FROM communication_participants participant
            JOIN communication_links link ON link.communication_id=participant.communication_id
            WHERE participant.communication_id=:id AND participant.party_id=:owner
            AND participant.role IN ('sender','reporter') AND (
              (link.entity_type='property' AND link.entity_id=:property)
              OR (link.entity_type='space' AND EXISTS(SELECT 1 FROM spaces s WHERE s.id=link.entity_id AND s.property_id=:property))
              OR (link.entity_type='lease' AND EXISTS(SELECT 1 FROM leases l JOIN spaces s ON s.id=l.space_id WHERE l.id=link.entity_id AND s.property_id=:property))
              OR (link.entity_type='rent_expectation' AND EXISTS(SELECT 1 FROM rent_expectations expectation JOIN leases l ON l.id=expectation.lease_id JOIN spaces s ON s.id=l.space_id WHERE expectation.id=link.entity_id AND s.property_id=:property))
              OR (link.entity_type='maintenance_issue' AND EXISTS(SELECT 1 FROM maintenance_issues issue WHERE issue.id=link.entity_id AND issue.property_id=:property))
              OR (link.entity_type='owner_concern' AND EXISTS(SELECT 1 FROM owner_concerns source WHERE source.id=link.entity_id AND source.property_id=:property))
            )"""),{"id":row["originating_communication_id"],"owner":row["owner_party_id"],"property":row["property_id"]}).first():raise MigrationSchemaError("Owner concern originating communication context is invalid.")
        if row["concern_type"]=='vacancy' and (row["observed_occupancy_status"] not in {'occupied','vacant','unknown'} or row["observed_availability_status"] not in {'available_now','available_on','not_available','unknown'} or (row["observed_availability_status"]=='available_on' and not _date(row["observed_available_on"])) or (row["observed_availability_status"]!='available_on' and row["observed_available_on"] is not None)):raise MigrationSchemaError("Owner concern vacancy snapshots are invalid.")
        if row["concern_type"]!='vacancy' and any(row[field] is not None for field in ("observed_occupancy_status","observed_availability_status","observed_available_on")):raise MigrationSchemaError("Owner concern non-vacancy snapshots are invalid.")
        if row["replaces_concern_id"] and (row["replaces_concern_id"] not in by_id or by_id[row["replaces_concern_id"]]["status"]!="dismissed"):raise MigrationSchemaError("Owner concern replacement lineage is invalid.")
        _audit_history(connection,row)
    if connection.execute(text("SELECT replaces_concern_id FROM owner_concerns WHERE replaces_concern_id IS NOT NULL GROUP BY replaces_concern_id HAVING count(*)>1")).first():raise MigrationSchemaError("Owner concern replacement lineage branches.")
    for item in concerns:
        seen=set();current=item
        while current["replaces_concern_id"]:
            parent=current["replaces_concern_id"]
            if parent in seen:raise MigrationSchemaError("Owner concern replacement lineage is cyclic.")
            seen.add(parent);current=by_id[parent]
    for row in connection.execute(text("SELECT * FROM owner_concern_follow_up_operations")).mappings():
        for field in ("id","idempotency_key","concern_id","task_id","correlation_id"):_uuid(row[field])
        _timestamp(row["created_at_utc"])
        if row["concern_id"] not in by_id or not connection.execute(text("SELECT 1 FROM tasks WHERE id=:task AND related_entity_type='owner_concern' AND related_entity_id=:concern"),{"task":row["task_id"],"concern":row["concern_id"]}).first():raise MigrationSchemaError("Owner concern follow-up references are invalid.")
        for entity,action,item_id in (("owner_concern_follow_up_operation","created",row["id"]),("owner_concern","follow_up_created",row["concern_id"]),("task","created",row["task_id"])):
            if not connection.execute(text("SELECT 1 FROM audit_events WHERE entity_type=:entity AND entity_id=:id AND action=:action AND correlation_id=:correlation"),{"entity":entity,"id":item_id,"action":action,"correlation":row["correlation_id"]}).first():raise MigrationSchemaError("Owner concern follow-up audit correlation is incomplete.")
    if connection.execute(text("SELECT 1 FROM communication_links link LEFT JOIN owner_concerns concern ON concern.id=link.entity_id WHERE link.entity_type='owner_concern' AND concern.id IS NULL LIMIT 1")).first():raise MigrationSchemaError("Owner concern communication links are invalid.")
def _uuid(value):
    try:UUID(str(value))
    except (ValueError,TypeError,AttributeError) as error:raise MigrationSchemaError("Owner-management UUID is invalid.") from error
def _timestamp(value):
    try:parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"));assert parsed.tzinfo and parsed.utcoffset()==UTC.utcoffset(parsed)
    except (ValueError,AssertionError) as error:raise MigrationSchemaError("Owner-management timestamp is invalid.") from error
def _date(value):
    try: date.fromisoformat(str(value)); return True
    except (TypeError,ValueError): return False
def _audit_history(connection,row):
    events = list(connection.execute(text("SELECT action,before_snapshot,after_snapshot FROM audit_events WHERE entity_type='owner_concern' AND entity_id=:id ORDER BY occurred_at,id"), {"id": row["id"]}).mappings())
    created = [event for event in events if event["action"] == "created"]
    if (len(created) != 1 or not _created_snapshot_matches(created[0]["after_snapshot"], row)
            or not _complete_state(_snapshot(created[0]["after_snapshot"]))):
        raise MigrationSchemaError("Owner concern creation audit history is incomplete.")
    created_after = _snapshot(created[0]["after_snapshot"])
    mutations = [event for event in events if event["action"] in {"updated", "status_changed"}]
    # A matching final snapshot alone cannot prove that every retained mutation
    # happened.  Walk the ordered audit history instead: each mutation must
    # begin at the exact preceding concern state and establish the next one.
    previous = created_after
    for event in mutations:
        before = _snapshot(event["before_snapshot"])
        after = _snapshot(event["after_snapshot"])
        if not _same_state(before, previous) or not _complete_state(after):
            raise MigrationSchemaError("Owner concern audit mutation chain is incomplete.")
        previous = after
    updates = [_snapshot(event["after_snapshot"]) for event in events if event["action"] == "updated"]
    transitions = [_snapshot(event["after_snapshot"]) for event in events if event["action"] == "status_changed"]
    current = Concern(**dict(row)).to_dict()
    if not _same_state(previous, current):
        raise MigrationSchemaError("Owner concern retained state has no complete audit chain.")
    mutation_snapshots = updates + transitions
    if row["status"] in ("open", "in_progress"):
        # Creation substantiates an untouched open concern. Once a lifecycle
        # transition exists, it cannot prove the current active state: a raw
        # rewrite could otherwise revert an audited in-progress concern to open.
        matching_mutation = any(_same_snapshot(snapshot, current) for snapshot in mutation_snapshots)
        if transitions:
            if not matching_mutation:
                raise MigrationSchemaError("Owner concern retained active state has no matching audit event.")
        elif not matching_mutation and not _same_snapshot(created_after, current):
            raise MigrationSchemaError("Owner concern retained active state has no matching audit event.")
    if row["status"] in ("resolved", "dismissed"):
        fields = ("status", "updated_at_utc", "resolved_at_utc", "resolution_summary", "dismissed_at_utc", "dismissal_reason")
        if not any(_same_values(snapshot, row, fields) for snapshot in transitions):
            raise MigrationSchemaError("Owner concern lifecycle audit history is incomplete.")
    if row["status"] in ("open", "in_progress") and any(snapshot.get("status") in ("resolved", "dismissed") for snapshot in transitions):
        if not any(snapshot.get("status") == "open" and snapshot.get("resolvedAtUtc") is None and snapshot.get("dismissedAtUtc") is None and isinstance(snapshot.get("reopenReason"), str) and snapshot["reopenReason"].strip() for snapshot in transitions):
            raise MigrationSchemaError("Owner concern reopen audit history is incomplete.")
    if row["replaces_concern_id"]:
        source = connection.execute(text("SELECT * FROM owner_concerns WHERE id=:id"), {"id": row["replaces_concern_id"]}).mappings().first()
        source_events = connection.execute(text("SELECT after_snapshot FROM audit_events WHERE entity_type='owner_concern' AND entity_id=:id AND action='status_changed'"), {"id": row["replaces_concern_id"]}).scalars()
        if source is None or not any(_same_values(_snapshot(snapshot), source, ("status", "updated_at_utc", "dismissed_at_utc", "dismissal_reason")) for snapshot in source_events):
            raise MigrationSchemaError("Owner concern replacement audit history is incomplete.")
        if created_after.get("replacesConcernId") != row["replaces_concern_id"]:
            raise MigrationSchemaError("Owner concern replacement creation history is incomplete.")
def _snapshot(value):
    try:
        parsed = loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}
def _same_values(snapshot, row, fields):
    return all(snapshot.get(_camel(field)) == row[field] for field in fields)
def _same_snapshot(snapshot, values):
    return all(snapshot.get(field) == value for field, value in values.items())
def _same_state(snapshot, values):
    """Compare just the durable Concern representation, ignoring audit-only context."""
    return all(snapshot.get(field) == values.get(field) for field in _STATE_FIELDS)
def _complete_state(snapshot):
    """Mutations must retain every durable Concern field, not a partial patch."""
    return all(field in snapshot for field in _STATE_FIELDS)
def _created_snapshot_matches(snapshot, row):
    values = _snapshot(snapshot)
    immutable = ("id", "owner_party_id", "owner_display_name_snapshot", "property_id", "property_display_name_snapshot", "space_id", "space_display_name_snapshot", "lease_id", "lease_display_snapshot", "tenant_party_id", "tenant_display_name_snapshot", "originating_communication_id", "concern_type", "raised_at_utc", "property_timezone_snapshot", "recorded_at_utc", "replaces_concern_id", "observed_occupancy_status", "observed_availability_status", "observed_available_on")
    return _same_values(values, row, immutable)
def _camel(value):
    head, *tail = value.split("_")
    return head + "".join(item.title() for item in tail)
_STATE_FIELDS = tuple(
    _camel(field)
    for field in Concern.__dataclass_fields__
    if field not in {"idempotency_key", "request_fingerprint"}
)

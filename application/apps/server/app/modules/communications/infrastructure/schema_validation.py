"""Exact structure and retained-data validation for COM-001."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import inspect, text
from sqlalchemy.dialects import sqlite

from app.modules.communications.application.ports import CommunicationContextOperations
from app.modules.communications.infrastructure.sqlalchemy_models import CommunicationLinkModel, CommunicationModel, CommunicationOperationModel, CommunicationParticipantModel
from app.platform.migration_errors import MigrationSchemaError

MODELS = (CommunicationModel, CommunicationParticipantModel, CommunicationLinkModel, CommunicationOperationModel)
OPERATION_TRIGGERS = {
    "communication_operations_no_update": "CREATE TRIGGER communication_operations_no_update BEFORE UPDATE ON communication_operations BEGIN SELECT RAISE(ABORT, 'communication operations are immutable'); END",
    "communication_operations_no_delete": "CREATE TRIGGER communication_operations_no_delete BEFORE DELETE ON communication_operations BEGIN SELECT RAISE(ABORT, 'communication operations are immutable'); END",
}


def _sql(value): return " ".join(str(value).replace('"', '').split()).casefold()
def _where(value):
    if value is None: return ""
    return _sql(value.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True})) if hasattr(value, "compile") else _sql(value)


def _trigger_sql(value: str) -> str:
    return " ".join(value.replace('"', "").split()).casefold()


def validate_communication_schema(connection, context: CommunicationContextOperations | None = None) -> None:
    inspector = inspect(connection)
    for model in MODELS:
        table = model.__table__; actual = {item["name"]: item for item in inspector.get_columns(table.name)}; expected = {item.name: item for item in table.columns}
        if set(actual) != set(expected): raise MigrationSchemaError(f"{table.name} columns are incompatible with COM-001.")
        for name, column in expected.items():
            if str(actual[name]["type"]).upper() != str(column.type).upper() or bool(actual[name]["nullable"]) != bool(column.nullable): raise MigrationSchemaError(f"{table.name}.{name} is incompatible with COM-001.")
        if {item["name"] for item in inspector.get_columns(table.name) if item["primary_key"]} != {item.name for item in table.primary_key.columns}: raise MigrationSchemaError(f"{table.name} primary key is incompatible with COM-001.")
        actual_fk = {(item["constrained_columns"][0], item["referred_table"], item["referred_columns"][0]) for item in inspector.get_foreign_keys(table.name)}
        expected_fk = {(fk.parent.name, fk.column.table.name, fk.column.name) for column in table.columns for fk in column.foreign_keys}
        if actual_fk != expected_fk: raise MigrationSchemaError(f"{table.name} foreign keys are incompatible with COM-001.")
        actual_index = {(item["name"], tuple(item["column_names"]), bool(item["unique"]), _where(item.get("dialect_options", {}).get("sqlite_where"))) for item in inspector.get_indexes(table.name)}
        expected_index = {(item.name, tuple(column.name for column in item.columns), bool(item.unique), _where(item.dialect_options["sqlite"].get("where"))) for item in table.indexes}
        if actual_index != expected_index: raise MigrationSchemaError(f"{table.name} indexes are incompatible with COM-001.")
        if {_sql(item["sqltext"]) for item in inspector.get_check_constraints(table.name)} != {_sql(item.sqltext) for item in table.constraints if item.__class__.__name__ == "CheckConstraint"}: raise MigrationSchemaError(f"{table.name} checks are incompatible with COM-001.")
        actual_unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)}
        expected_unique = {tuple(item.columns.keys()) for item in table.constraints if item.__class__.__name__ == "UniqueConstraint"} | {(column.name,) for column in table.columns if column.unique}
        if actual_unique != expected_unique: raise MigrationSchemaError(f"{table.name} unique constraints are incompatible with COM-001.")
    _validate_data(connection, context)
    triggers = {name: _trigger_sql(sql) for name, sql in connection.exec_driver_sql(
        "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'communication_operations'"
    )}
    expected_triggers = {name: _trigger_sql(sql) for name, sql in OPERATION_TRIGGERS.items()}
    if triggers != expected_triggers:
        raise MigrationSchemaError("COM-001 operation immutability triggers are incompatible.")


def _validate_data(connection, context: CommunicationContextOperations | None) -> None:
    if connection.execute(text("PRAGMA foreign_key_check")).first() is not None: raise MigrationSchemaError("COM-001 has invalid foreign-key references.")
    rows = connection.execute(text("SELECT * FROM communications")).mappings().all()
    by_id = {row["id"]: row for row in rows}
    for row in rows:
        try: UUID(row["id"]); ZoneInfo(row["occurred_timezone"])
        except (ValueError, ZoneInfoNotFoundError) as error: raise MigrationSchemaError("COM-001 communication identity or time zone is invalid.") from error
        _utc_timestamp(row["occurred_at_utc"], "communication occurrence")
        _utc_timestamp(row["created_at"], "communication creation")
        _utc_timestamp(row["updated_at"], "communication update")
        if row["recorded_at"] is not None:
            _utc_timestamp(row["recorded_at"], "communication recording")
        source = row["supersedes_communication_id"]; child = row["superseded_by_communication_id"]
        if source:
            parent = by_id.get(source)
            if parent is None or parent["status"] != "superseded" or parent["superseded_by_communication_id"] != row["id"]: raise MigrationSchemaError("COM-001 correction lineage is invalid.")
        if child and (child not in by_id or by_id[child]["supersedes_communication_id"] != row["id"]): raise MigrationSchemaError("COM-001 correction lineage is invalid.")
        seen: set[str] = set(); current = row
        while current["supersedes_communication_id"]:
            parent_id = current["supersedes_communication_id"]
            if parent_id in seen: raise MigrationSchemaError("COM-001 correction lineage contains a cycle.")
            seen.add(parent_id); current = by_id.get(parent_id)
            if current is None: break
    for row in connection.execute(text("SELECT * FROM communication_participants")).mappings():
        _uuid(row["id"], "participant")
        _uuid(row["communication_id"], "participant communication")
        _uuid(row["party_id"], "participant party")
        if row["party_contact_method_id"] is not None:
            _uuid(row["party_contact_method_id"], "participant contact")
            if not isinstance(row["contact_display_snapshot"], str) or not row["contact_display_snapshot"].strip():
                raise MigrationSchemaError("COM-001 participant contact snapshots are inconsistent.")
        elif row["contact_display_snapshot"] is not None:
            raise MigrationSchemaError("COM-001 participant contact snapshots are inconsistent.")
        if not isinstance(row["party_display_name_snapshot"], str) or not row["party_display_name_snapshot"].strip():
            raise MigrationSchemaError("COM-001 participant name snapshot is invalid.")
        if row["communication_id"] not in by_id: raise MigrationSchemaError("COM-001 participant parent is invalid.")
        if context is not None:
            try:
                context.validate_retained_participant(connection, row["party_id"], row["party_contact_method_id"])
            except (KeyError, ValueError) as error:
                raise MigrationSchemaError("COM-001 participant reference is invalid.") from error
    missing = connection.execute(text("SELECT c.id FROM communications c LEFT JOIN communication_participants p ON p.communication_id=c.id GROUP BY c.id HAVING count(p.id)=0")).first()
    if missing: raise MigrationSchemaError("COM-001 communications require participants.")
    link_rows = list(connection.execute(text("SELECT * FROM communication_links")).mappings())
    for row in link_rows:
        _uuid(row["id"], "link")
        _uuid(row["communication_id"], "link communication")
        _uuid(row["entity_id"], "link target")
        if row["communication_id"] not in by_id:
            raise MigrationSchemaError("COM-001 link parent is invalid.")
    if context is not None:
        try:
            context.validate_communication_task_references(connection, set(by_id))
        except (KeyError, ValueError) as error:
            raise MigrationSchemaError("COM-001 follow-up task reference is invalid.") from error
        for row in link_rows:
            try:
                current_zone = context.validate_link(connection, row["entity_type"], row["entity_id"])
            except (KeyError, ValueError) as error:
                raise MigrationSchemaError("COM-001 typed link target is invalid.") from error
            snapshot = row["property_timezone_snapshot"]
            if current_zone is None:
                if snapshot is not None:
                    raise MigrationSchemaError("COM-001 non-property links cannot retain a time-zone snapshot.")
            else:
                if not isinstance(snapshot, str):
                    raise MigrationSchemaError("COM-001 property links require a time-zone snapshot.")
                try:
                    ZoneInfo(snapshot)
                except ZoneInfoNotFoundError as error:
                    raise MigrationSchemaError("COM-001 property link time-zone snapshot is invalid.") from error
                if snapshot != by_id[row["communication_id"]]["occurred_timezone"]:
                    raise MigrationSchemaError("COM-001 property link time-zone snapshot is inconsistent.")
    operation_rows = list(connection.execute(text("SELECT * FROM communication_operations")).mappings())
    for row in operation_rows:
        _uuid(row["id"], "operation")
        try: UUID(row["idempotency_key"]); UUID(row["correlation_id"])
        except ValueError as error: raise MigrationSchemaError("COM-001 operation identity is invalid.") from error
        _utc_timestamp(row["created_at"], "operation creation")
        if len(row["request_fingerprint"]) != 64 or any(char not in "0123456789abcdef" for char in row["request_fingerprint"]): raise MigrationSchemaError("COM-001 operation fingerprint is invalid.")
        target = row["target_communication_id"]
        result = row["result_communication_id"]
        follow_up_task_id = row["follow_up_task_id"]
        if target is not None:
            _uuid(target, "operation target")
        if result is not None:
            _uuid(result, "operation result")
        if follow_up_task_id is not None:
            _uuid(follow_up_task_id, "operation follow-up task")
        action = row["action"]
        valid = (
            action == "created" and target is None and result in by_id
            or action in {"recorded", "patched"} and target == result and target in by_id
            or action == "corrected" and target in by_id and result in by_id and target != result
            and by_id[result]["supersedes_communication_id"] == target
        )
        if not valid:
            raise MigrationSchemaError("COM-001 operation target, result, or action is invalid.")
        if not _has_operation_audit(connection, action, target, result, row["correlation_id"]):
            raise MigrationSchemaError("COM-001 operation audit correlation is invalid.")
    _validate_operation_coverage(by_id, operation_rows)
    _validate_follow_up_audits(connection, operation_rows)
    _validate_audit_operation_coverage(connection, operation_rows)


def _uuid(value: object, label: str) -> None:
    try:
        UUID(str(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise MigrationSchemaError(f"COM-001 {label} ID is invalid.") from error


def _utc_timestamp(value: object, label: str) -> None:
    if not isinstance(value, str):
        raise MigrationSchemaError(f"COM-001 {label} timestamp is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MigrationSchemaError(f"COM-001 {label} timestamp is invalid.") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise MigrationSchemaError(f"COM-001 {label} timestamp must be UTC.")


def _has_operation_audit(connection, action: str, target: str | None, result: str | None, correlation_id: str) -> bool:
    expected = {
        "created": ((result, "created"),),
        "recorded": ((target, "recorded"),),
        "patched": ((target, "updated"),),
        "corrected": ((target, "superseded"), (result, "created")),
    }[action]
    for entity_id, audit_action in expected:
        found = connection.execute(text(
            "SELECT 1 FROM audit_events WHERE entity_type = 'communication' "
            "AND entity_id = :entity_id AND action = :action AND correlation_id = :correlation_id"
        ), {"entity_id": entity_id, "action": audit_action, "correlation_id": correlation_id}).first()
        if found is None:
            return False
    return True


def _validate_follow_up_audits(connection, operations) -> None:
    """A communication follow-up retains its task and parent audit records together."""
    expected = {
        (row["result_communication_id"], row["follow_up_task_id"], row["correlation_id"])
        for row in operations if row["follow_up_task_id"] is not None
    }
    if any(row["action"] == "patched" and row["follow_up_task_id"] is not None for row in operations):
        raise MigrationSchemaError("COM-001 patch operations cannot create follow-up tasks.")
    task_events = connection.execute(text(
        "SELECT entity_id, correlation_id, after_snapshot FROM audit_events WHERE entity_type = 'task' "
        "AND action = 'created' AND reason = 'communication_follow_up'"
    )).mappings().all()
    parent_events = connection.execute(text(
        "SELECT entity_id, correlation_id, after_snapshot FROM audit_events WHERE entity_type = 'communication' "
        "AND action = 'follow_up_created'"
    )).mappings().all()
    task_facts = {_follow_up_task_fact(connection, event) for event in task_events}
    parent_facts = {_follow_up_parent_fact(event) for event in parent_events}
    if (
        len(task_events) != len(expected)
        or len(parent_events) != len(expected)
        or None in task_facts
        or None in parent_facts
        or task_facts != expected
        or parent_facts != expected
    ):
        raise MigrationSchemaError("COM-001 follow-up audit correlation is incomplete or invalid.")


def _follow_up_task_fact(connection, event):
    try:
        after = json.loads(event["after_snapshot"] or "{}")
        communication_id = after["relatedEntityId"]
        if after.get("relatedEntityType") != "communication":
            return None
        row = connection.execute(text(
            "SELECT related_entity_type, related_entity_id FROM tasks WHERE id = :id"
        ), {"id": event["entity_id"]}).first()
        if row != ("communication", communication_id):
            return None
        return communication_id, event["entity_id"], event["correlation_id"]
    except (KeyError, TypeError, ValueError):
        return None


def _follow_up_parent_fact(event):
    try:
        after = json.loads(event["after_snapshot"] or "{}")
        return event["entity_id"], after["taskId"], event["correlation_id"]
    except (KeyError, TypeError, ValueError):
        return None


def _validate_audit_operation_coverage(connection, operations) -> None:
    """Recorded lifecycle audit events must each retain their immutable operation."""
    operation_facts = {(row["action"], row["target_communication_id"], row["result_communication_id"], row["correlation_id"]) for row in operations}
    events = connection.execute(text(
        "SELECT entity_id, action, correlation_id FROM audit_events WHERE entity_type = 'communication' "
        "AND action IN ('created', 'recorded', 'updated', 'superseded')"
    )).mappings()
    for event in events:
        action = event["action"]
        correlation = event["correlation_id"]
        entity_id = event["entity_id"]
        if action == "created":
            valid = any(
                fact[0] in {"created", "corrected"} and fact[2] == entity_id and fact[3] == correlation
                for fact in operation_facts
            )
        elif action == "recorded":
            valid = any(
                (fact[0] == "recorded" and fact[1] == entity_id and fact[2] == entity_id and fact[3] == correlation)
                or (fact[0] == "created" and fact[2] == entity_id and fact[3] == correlation)
                for fact in operation_facts
            )
        elif action == "updated":
            valid = ("patched", entity_id, entity_id, correlation) in operation_facts
        else:
            valid = any(fact[0] == "corrected" and fact[1] == entity_id and fact[3] == correlation for fact in operation_facts)
        if not valid:
            raise MigrationSchemaError("COM-001 lifecycle audit has no immutable operation.")


def _validate_operation_coverage(by_id, operations) -> None:
    results = {row["result_communication_id"] for row in operations if row["action"] in {"created", "corrected"}}
    if set(by_id) - results:
        raise MigrationSchemaError("COM-001 communication operation history is incomplete.")

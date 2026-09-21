"""Exact MAINT-001 schema and retained-data validation."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, inspect, text

from app.platform.migration_errors import MigrationSchemaError
from .sqlalchemy_models import (
    MaintenanceAppointmentModel,
    MaintenanceCostContextModel,
    MaintenanceFollowUpOperationModel,
    MaintenanceIssueExpenseLinkModel,
    MaintenanceIssueModel,
    MaintenanceQuoteModel,
    MaintenanceAssignmentModel,
)


MODELS = (
    MaintenanceIssueModel, MaintenanceAppointmentModel, MaintenanceCostContextModel,
    MaintenanceIssueExpenseLinkModel, MaintenanceFollowUpOperationModel, MaintenanceQuoteModel, MaintenanceAssignmentModel,
)
OPERATION_TRIGGERS = {
    "maintenance_follow_up_operations_no_update": "CREATE TRIGGER maintenance_follow_up_operations_no_update BEFORE UPDATE ON maintenance_follow_up_operations BEGIN SELECT RAISE(ABORT, 'maintenance follow-up operations are immutable'); END",
    "maintenance_follow_up_operations_no_delete": "CREATE TRIGGER maintenance_follow_up_operations_no_delete BEFORE DELETE ON maintenance_follow_up_operations BEGIN SELECT RAISE(ABORT, 'maintenance follow-up operations are immutable'); END",
}


def validate_maintenance_schema(connection) -> None:
    inspector = inspect(connection)
    for model in MODELS:
        table = model.__table__
        if not inspector.has_table(table.name):
            raise MigrationSchemaError("Maintenance schema is missing.")
        columns = {column["name"]: column for column in inspector.get_columns(table.name)}
        if set(columns) != {column.name for column in table.columns}:
            raise MigrationSchemaError(f"Maintenance columns for {table.name} are incompatible.")
        for expected in table.columns:
            actual = columns[expected.name]
            if bool(actual["primary_key"]) != expected.primary_key or bool(actual["nullable"]) != expected.nullable:
                raise MigrationSchemaError(f"Maintenance column shape for {table.name} is incompatible.")
            expected_type, actual_type = str(expected.type).upper(), str(actual["type"]).upper()
            if ("INT" in expected_type and "INT" not in actual_type) or ("INT" not in expected_type and not ("TEXT" in actual_type or "CHAR" in actual_type)):
                raise MigrationSchemaError(f"Maintenance column type for {table.name} is incompatible.")
        expected_fks = {(tuple(element.parent.name for element in constraint.elements), constraint.elements[0].column.table.name, tuple(element.column.name for element in constraint.elements)) for constraint in table.constraints if isinstance(constraint, ForeignKeyConstraint)}
        actual_fks = {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"])) for item in inspector.get_foreign_keys(table.name)}
        if actual_fks != expected_fks:
            raise MigrationSchemaError(f"Maintenance foreign keys for {table.name} are incompatible.")
        expected_indexes = {item.name: (tuple(column.name for column in item.columns), bool(item.unique), _where(item.dialect_options["sqlite"].get("where"))) for item in table.indexes}
        actual_indexes = {item["name"]: (tuple(item["column_names"]), bool(item.get("unique")), _where(item.get("dialect_options", {}).get("sqlite_where"))) for item in inspector.get_indexes(table.name)}
        if actual_indexes != expected_indexes:
            raise MigrationSchemaError(f"Maintenance indexes for {table.name} are incompatible.")
        expected_unique = {tuple(column.name for column in item.columns) for item in table.constraints if isinstance(item, UniqueConstraint)}
        actual_unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)}
        if actual_unique != expected_unique:
            raise MigrationSchemaError(f"Maintenance unique constraints for {table.name} are incompatible.")
        expected_checks = {_normalise(item.sqltext.text) for item in table.constraints if isinstance(item, CheckConstraint)}
        actual_checks = {_normalise(item.get("sqltext") or "") for item in inspector.get_check_constraints(table.name)}
        if actual_checks != expected_checks:
            raise MigrationSchemaError(f"Maintenance checks for {table.name} are incompatible.")
    validate_maintenance_data(connection)
    triggers = {
        name: _trigger_sql(sql)
        for name, sql in connection.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' "
            "AND tbl_name = 'maintenance_follow_up_operations'"
        )
    }
    expected_triggers = {name: _trigger_sql(sql) for name, sql in OPERATION_TRIGGERS.items()}
    if triggers != expected_triggers:
        raise MigrationSchemaError("Maintenance follow-up operation triggers are incompatible.")


def validate_maintenance_data(connection) -> None:
    if connection.execute(text("PRAGMA foreign_key_check")).first() is not None:
        raise MigrationSchemaError("Maintenance data has broken foreign keys.")
    _validate_identifiers_and_instants(connection)
    _validate_values(connection)
    checks = (
        """SELECT 1 FROM maintenance_issues i LEFT JOIN spaces s ON s.id=i.space_id
           WHERE i.space_id IS NOT NULL AND (s.id IS NULL OR s.property_id != i.property_id) LIMIT 1""",
        """SELECT 1 FROM maintenance_issues issue LEFT JOIN parties party ON party.id=issue.reporter_party_id
           WHERE (issue.reporter_subject_kind='party' AND party.id IS NULL)
              OR (issue.reporter_subject_kind='local_operator' AND issue.reporter_party_id IS NOT NULL)
              OR (issue.reporter_role IN ('manager','staff') AND issue.reporter_subject_kind != 'local_operator')
              OR (issue.reporter_role='tenant' AND issue.reporter_subject_kind != 'party') LIMIT 1""",
        """SELECT 1 FROM maintenance_appointments a WHERE a.status='scheduled' AND a.ends_at_utc <= a.starts_at_utc LIMIT 1""",
        """SELECT 1 FROM maintenance_cost_contexts replacement JOIN maintenance_cost_contexts original
           ON original.id=replacement.replaces_cost_context_id
           WHERE replacement.issue_id != original.issue_id OR replacement.context_kind != original.context_kind
             OR original.voided_at IS NULL OR replacement.id = replacement.replaces_cost_context_id LIMIT 1""",
        """SELECT 1 FROM maintenance_issue_expense_links link JOIN maintenance_issues issue ON issue.id=link.issue_id
           JOIN expenses expense ON expense.id=link.expense_id
           WHERE link.archived_at IS NULL AND (expense.property_id != issue.property_id
             OR (issue.space_id IS NOT NULL AND expense.space_id IS NOT NULL AND expense.space_id != issue.space_id)) LIMIT 1""",
        """SELECT 1 FROM maintenance_follow_up_operations operation LEFT JOIN tasks task ON task.id=operation.task_id
           WHERE task.id IS NULL OR task.related_entity_type != 'maintenance_issue'
             OR task.related_entity_id != operation.issue_id LIMIT 1""",
        """SELECT 1 FROM maintenance_quotes replacement JOIN maintenance_quotes original ON original.id=replacement.replaces_quote_id
           WHERE replacement.issue_id != original.issue_id OR replacement.provider_party_id != original.provider_party_id
             OR original.withdrawn_at IS NULL OR replacement.id=replacement.replaces_quote_id LIMIT 1""",
        """SELECT 1 FROM maintenance_assignments assignment LEFT JOIN maintenance_quotes quote ON quote.id=assignment.quote_id
           WHERE assignment.quote_id IS NOT NULL AND (quote.id IS NULL OR quote.issue_id != assignment.issue_id OR quote.provider_party_id != assignment.provider_party_id) LIMIT 1""",
        """SELECT 1 FROM maintenance_assignments replacement JOIN maintenance_assignments original ON original.id=replacement.replaces_assignment_id
           WHERE replacement.issue_id != original.issue_id OR original.ended_at IS NULL OR replacement.id=replacement.replaces_assignment_id LIMIT 1""",
        """SELECT 1 FROM maintenance_issues issue WHERE NOT EXISTS (
             SELECT 1 FROM audit_events event WHERE event.entity_type='maintenance_issue' AND event.entity_id=issue.id AND event.action='created'
           ) LIMIT 1""",
        """SELECT 1 FROM maintenance_appointments appointment WHERE NOT EXISTS (
             SELECT 1 FROM audit_events event WHERE event.entity_type='maintenance_appointment' AND event.entity_id=appointment.id AND event.action='created'
           ) LIMIT 1""",
        """SELECT 1 FROM maintenance_cost_contexts context WHERE NOT EXISTS (
             SELECT 1 FROM audit_events event WHERE event.entity_type='maintenance_cost_context' AND event.entity_id=context.id AND event.action='created'
           ) LIMIT 1""",
        """SELECT 1 FROM maintenance_issue_expense_links link WHERE NOT EXISTS (
             SELECT 1 FROM audit_events event WHERE event.entity_type='maintenance_expense_link' AND event.entity_id=link.id AND event.action='created'
           ) LIMIT 1""",
        """SELECT 1 FROM maintenance_issues issue WHERE
           (issue.status='resolved' AND NOT EXISTS (SELECT 1 FROM audit_events event WHERE event.entity_type='maintenance_issue' AND event.entity_id=issue.id AND event.action='resolved'))
           OR (issue.status='cancelled' AND NOT EXISTS (SELECT 1 FROM audit_events event WHERE event.entity_type='maintenance_issue' AND event.entity_id=issue.id AND event.action='cancelled')) LIMIT 1""",
        """SELECT 1 FROM maintenance_appointments appointment WHERE
           (appointment.status='completed' AND NOT EXISTS (SELECT 1 FROM audit_events event WHERE event.entity_type='maintenance_appointment' AND event.entity_id=appointment.id AND event.action='completed'))
           OR (appointment.status='cancelled' AND NOT EXISTS (SELECT 1 FROM audit_events event WHERE event.entity_type='maintenance_appointment' AND event.entity_id=appointment.id AND event.action='cancelled')) LIMIT 1""",
        """SELECT 1 FROM maintenance_cost_contexts context WHERE context.voided_at IS NOT NULL AND NOT EXISTS (
             SELECT 1 FROM audit_events event WHERE event.entity_type='maintenance_cost_context' AND event.entity_id=context.id AND event.action='voided'
           ) LIMIT 1""",
        """SELECT 1 FROM maintenance_issue_expense_links link WHERE link.archived_at IS NOT NULL AND NOT EXISTS (
             SELECT 1 FROM audit_events event WHERE event.entity_type='maintenance_expense_link' AND event.entity_id=link.id AND event.action='archived'
           ) LIMIT 1""",
        """SELECT 1 FROM maintenance_quotes quote WHERE NOT EXISTS (
             SELECT 1 FROM audit_events event WHERE event.entity_type='maintenance_quote' AND event.entity_id=quote.id AND event.action='created'
           ) OR (quote.withdrawn_at IS NOT NULL AND NOT EXISTS (
             SELECT 1 FROM audit_events event WHERE event.entity_type='maintenance_quote' AND event.entity_id=quote.id AND event.action='withdrawn'
           )) LIMIT 1""",
        """SELECT 1 FROM maintenance_assignments assignment WHERE NOT EXISTS (
             SELECT 1 FROM audit_events event WHERE event.entity_type='maintenance_assignment' AND event.entity_id=assignment.id AND event.action='created'
           ) OR (assignment.ended_at IS NOT NULL AND NOT EXISTS (
             SELECT 1 FROM audit_events event WHERE event.entity_type='maintenance_assignment' AND event.entity_id=assignment.id AND event.action='ended'
           )) LIMIT 1""",
        """SELECT 1 FROM maintenance_follow_up_operations operation WHERE
           (SELECT COUNT(*) FROM audit_events event WHERE event.entity_type='task' AND event.entity_id=operation.task_id AND event.action='created' AND event.correlation_id=operation.correlation_id) != 1
           OR (SELECT COUNT(*) FROM audit_events event WHERE event.entity_type='maintenance_issue' AND event.entity_id=operation.issue_id AND event.action='follow_up_created' AND event.correlation_id=operation.correlation_id) != 1 LIMIT 1""",
        """SELECT 1 FROM tasks task JOIN audit_events task_event ON task_event.entity_type='task' AND task_event.entity_id=task.id AND task_event.action='created'
           JOIN audit_events issue_event ON issue_event.entity_type='maintenance_issue' AND issue_event.action='follow_up_created' AND issue_event.correlation_id=task_event.correlation_id
           WHERE task.related_entity_type='maintenance_issue' AND task.related_entity_id=issue_event.entity_id
             AND NOT EXISTS (SELECT 1 FROM maintenance_follow_up_operations operation WHERE operation.task_id=task.id AND operation.issue_id=task.related_entity_id AND operation.correlation_id=task_event.correlation_id) LIMIT 1""",
    )
    if any(connection.execute(text(statement)).first() for statement in checks):
        raise MigrationSchemaError("Maintenance retained data is incompatible.")
    _validate_reporter_history(connection)
    _validate_quote_assignment_history(connection)


_REPORTER_SNAPSHOT_KEYS = (
    "reporterRole", "reporterSubjectKind", "reporterPartyId",
    "reporterDisplayNameSnapshot",
)


def _reporter_snapshot(value):
    if not isinstance(value, dict) or any(key not in value for key in _REPORTER_SNAPSHOT_KEYS):
        return None
    return tuple(value[key] for key in _REPORTER_SNAPSHOT_KEYS)


def _audit_snapshot(value):
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as error:
        raise MigrationSchemaError("Maintenance audit snapshots are incompatible.") from error
    if not isinstance(parsed, dict):
        raise MigrationSchemaError("Maintenance audit snapshots are incompatible.")
    return parsed


def _validate_reporter_history(connection) -> None:
    issues = {
        row["id"]: (
            row["reporter_role"], row["reporter_subject_kind"],
            row["reporter_party_id"], row["reporter_display_name_snapshot"],
        )
        for row in connection.execute(text(
            "SELECT id, reporter_role, reporter_subject_kind, reporter_party_id, "
            "reporter_display_name_snapshot FROM maintenance_issues"
        )).mappings()
    }
    events = connection.execute(text(
        "SELECT entity_id, action, before_snapshot, after_snapshot FROM audit_events "
        "WHERE entity_type='maintenance_issue' ORDER BY entity_id, occurred_at, id"
    )).mappings()
    history: dict[str, list[object]] = {issue_id: [] for issue_id in issues}
    for event in events:
        if event["entity_id"] in history:
            history[event["entity_id"]].append(event)
    for issue_id, expected_current in issues.items():
        expected = None
        created = False
        for event in history[issue_id]:
            before = _reporter_snapshot(_audit_snapshot(event["before_snapshot"]))
            after = _reporter_snapshot(_audit_snapshot(event["after_snapshot"]))
            if event["action"] == "created":
                if created or after is None:
                    raise MigrationSchemaError("Maintenance reporter history is incompatible.")
                created, expected = True, after
                continue
            if event["action"] == "reporter_corrected":
                if not created or before != expected or after is None:
                    raise MigrationSchemaError("Maintenance reporter correction history is incompatible.")
                expected = after
                continue
            # Other maintenance events may carry a full issue snapshot, but
            # they must never alter reporter attribution.
            if expected is not None and ((before is not None and before != expected) or (after is not None and after != expected)):
                raise MigrationSchemaError("Maintenance reporter attribution changed outside a correction.")
        if not created or expected != expected_current:
            raise MigrationSchemaError("Maintenance reporter history does not match retained data.")


_QUOTE_KEYS = ("id", "issueId", "providerPartyId", "providerDisplayNameSnapshot", "label", "scopeSummary", "amountMinor", "currencyCode", "receivedOn", "validThrough", "termsNotes", "replacesQuoteId", "withdrawnAt", "withdrawalReason", "createdAt")
_ASSIGNMENT_KEYS = ("id", "issueId", "providerPartyId", "providerDisplayNameSnapshot", "quoteId", "providerSelectionStatusSnapshot", "selectionReason", "avoidOverrideReason", "instructions", "replacesAssignmentId", "assignedAt", "endedAt", "endReason")


def _row_snapshot(row, keys):
    return {key: row[_snake(key)] for key in keys}


def _snake(value):
    result=[]
    for character in value:
        result.append(("_" + character.lower()) if character.isupper() else character)
    return "".join(result)


def _snapshot(value, keys):
    if not isinstance(value, dict) or any(key not in value for key in keys):
        raise MigrationSchemaError("Maintenance quote or assignment history is incompatible.")
    return {key:value[key] for key in keys}


def _validate_quote_assignment_history(connection) -> None:
    _validate_entity_history(connection, "maintenance_quotes", "maintenance_quote", _QUOTE_KEYS, {"withdrawn": ("quote_withdrawn", "withdrawnAt", "withdrawalReason")})
    assignment_events = _validate_entity_history(connection, "maintenance_assignments", "maintenance_assignment", _ASSIGNMENT_KEYS, {"ended": (("assignment_ended", "assignment_reassigned"), "endedAt", "endReason")})
    reassigned = [event for events in assignment_events.values() for event in events if event["action"] == "ended" and event["reason"] == "assignment_reassigned"]
    created = [event for events in assignment_events.values() for event in events if event["action"] == "created"]
    for ended in reassigned:
        correlation=ended["correlation_id"]
        replacement=[event for event in created if event["correlation_id"] == correlation and event["after"]["replacesAssignmentId"] == ended["entity_id"]]
        if not correlation or len(replacement) != 1:
            raise MigrationSchemaError("Maintenance reassignment audit correlation is incompatible.")
    for event in created:
        replaced=event["after"]["replacesAssignmentId"]
        if replaced is not None:
            matching=[ended for ended in reassigned if ended["entity_id"] == replaced and ended["correlation_id"] == event["correlation_id"]]
            if not event["correlation_id"] or len(matching) != 1:
                raise MigrationSchemaError("Maintenance reassignment audit correlation is incompatible.")


def _validate_entity_history(connection, table, entity_type, keys, transitions):
    rows={row["id"]:_row_snapshot(row,keys) for row in connection.execute(text(f"SELECT * FROM {table}")).mappings()}
    events={item_id:[] for item_id in rows}
    for row in connection.execute(text("SELECT entity_id, action, reason, before_snapshot, after_snapshot, correlation_id FROM audit_events WHERE entity_type=:entity_type ORDER BY entity_id, occurred_at, id"), {"entity_type":entity_type}).mappings():
        if row["entity_id"] not in events:
            raise MigrationSchemaError("Maintenance quote or assignment audit references an unknown record.")
        events[row["entity_id"]].append({**dict(row),"before":_audit_snapshot(row["before_snapshot"]),"after":_audit_snapshot(row["after_snapshot"])})
    for item_id, current in rows.items():
        expected=None
        created=False
        for event in events[item_id]:
            action=event["action"]
            if action == "created":
                after=_snapshot(event["after"],keys)
                if created or event["before"] is not None:
                    raise MigrationSchemaError("Maintenance quote or assignment creation history is incompatible.")
                created,expected=True,after
                continue
            if action not in transitions:
                raise MigrationSchemaError("Maintenance quote or assignment lifecycle action is incompatible.")
            allowed, *changed = transitions[action]
            allowed={allowed} if isinstance(allowed,str) else set(allowed)
            if event.get("reason") not in allowed:
                raise MigrationSchemaError("Maintenance quote or assignment lifecycle reason is incompatible.")
            before=_snapshot(event["before"],keys); after=_snapshot(event["after"],keys)
            if not created or before != expected or any(before[key] != after[key] for key in keys if key not in changed) or any(after[key] is None for key in changed):
                raise MigrationSchemaError("Maintenance quote or assignment lifecycle snapshot is incompatible.")
            expected=after
        if not created or expected != current:
            raise MigrationSchemaError("Maintenance quote or assignment history does not match retained data.")
    return events


def _validate_identifiers_and_instants(connection) -> None:
    identifier_columns = {
        "maintenance_issues": ("id", "property_id", "space_id", "reporter_party_id", "idempotency_key"),
        "maintenance_appointments": ("id", "issue_id", "idempotency_key"),
        "maintenance_cost_contexts": ("id", "issue_id", "replaces_cost_context_id", "idempotency_key"),
        "maintenance_issue_expense_links": ("id", "issue_id", "expense_id", "idempotency_key"),
        "maintenance_follow_up_operations": ("idempotency_key", "issue_id", "task_id", "correlation_id"),
        "maintenance_quotes": ("id", "issue_id", "provider_party_id", "replaces_quote_id", "idempotency_key"),
        "maintenance_assignments": ("id", "issue_id", "provider_party_id", "quote_id", "replaces_assignment_id", "idempotency_key"),
    }
    instant_columns = {
        "maintenance_issues": ("reported_at_utc", "resolved_at", "cancelled_at", "created_at", "updated_at"),
        "maintenance_appointments": ("starts_at_utc", "ends_at_utc", "completed_at", "cancelled_at", "created_at", "updated_at"),
        "maintenance_cost_contexts": ("voided_at", "created_at"),
        "maintenance_issue_expense_links": ("created_at", "archived_at"),
        "maintenance_follow_up_operations": ("created_at",),
        "maintenance_quotes": ("withdrawn_at", "created_at"),
        "maintenance_assignments": ("assigned_at", "ended_at"),
    }
    for table, columns in identifier_columns.items():
        for row in connection.execute(text(f"SELECT {', '.join(columns)}, request_fingerprint FROM {table}")).mappings():
            for column in columns:
                if row[column] is None: continue
                try: UUID(row[column])
                except (TypeError, ValueError, AttributeError) as error: raise MigrationSchemaError("Maintenance identifiers are incompatible.") from error
            fingerprint=row["request_fingerprint"]
            if not isinstance(fingerprint,str) or len(fingerprint)!=64 or any(value not in "0123456789abcdef" for value in fingerprint):
                raise MigrationSchemaError("Maintenance idempotency fingerprints are incompatible.")
    for table, columns in instant_columns.items():
        for row in connection.execute(text(f"SELECT {', '.join(columns)} FROM {table}")).mappings():
            for column in columns:
                value=row[column]
                if value is None: continue
                try:
                    parsed=datetime.fromisoformat(value)
                    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed): raise ValueError
                except (TypeError, ValueError) as error: raise MigrationSchemaError("Maintenance timestamps must be UTC-aware.") from error


def _validate_values(connection) -> None:
    for row in connection.execute(text("SELECT summary, description, category, category_detail, reported_timezone, reporter_display_name_snapshot, resolution_summary, cancellation_reason FROM maintenance_issues")).mappings():
        _bounded(row["summary"], 240, True); _bounded(row["description"], 10_000, True)
        _bounded(row["category_detail"], 200, row["category"] == "other"); _bounded(row["reporter_display_name_snapshot"], 240, True); _bounded(row["resolution_summary"], 1000, False); _bounded(row["cancellation_reason"], 1000, False); _zone(row["reported_timezone"])
    for row in connection.execute(text("SELECT purpose, instructions, scheduled_timezone, outcome_note, cancellation_reason FROM maintenance_appointments")).mappings():
        _bounded(row["purpose"], 500, True); _bounded(row["instructions"], 4000, False); _bounded(row["outcome_note"], 4000, False); _bounded(row["cancellation_reason"], 1000, False); _zone(row["scheduled_timezone"])
    for row in connection.execute(text("SELECT label, observed_on, source_note, void_reason FROM maintenance_cost_contexts")).mappings():
        _bounded(row["label"], 200, True); _bounded(row["source_note"], 4000, False); _bounded(row["void_reason"], 1000, False)
        try: date.fromisoformat(row["observed_on"])
        except (TypeError, ValueError) as error: raise MigrationSchemaError("Maintenance observed dates are incompatible.") from error
    for row in connection.execute(text("SELECT archive_reason FROM maintenance_issue_expense_links")).mappings():
        _bounded(row["archive_reason"], 1000, False)
    for row in connection.execute(text("SELECT provider_display_name_snapshot, label, scope_summary, received_on, valid_through, terms_notes, withdrawal_reason FROM maintenance_quotes")).mappings():
        _bounded(row["provider_display_name_snapshot"], 240, True); _bounded(row["label"], 200, True); _bounded(row["scope_summary"], 4000, True); _bounded(row["terms_notes"], 4000, False); _bounded(row["withdrawal_reason"], 1000, False)
        try: date.fromisoformat(row["received_on"]); row["valid_through"] is None or date.fromisoformat(row["valid_through"])
        except (TypeError, ValueError) as error: raise MigrationSchemaError("Maintenance quote dates are incompatible.") from error
    for row in connection.execute(text("SELECT provider_display_name_snapshot, selection_reason, avoid_override_reason, instructions, end_reason FROM maintenance_assignments")).mappings():
        _bounded(row["provider_display_name_snapshot"], 240, True); _bounded(row["selection_reason"], 1000, False); _bounded(row["avoid_override_reason"], 1000, False); _bounded(row["instructions"], 4000, False); _bounded(row["end_reason"], 1000, False)


def _bounded(value, maximum: int, required: bool) -> None:
    if value is None:
        if required: raise MigrationSchemaError("Maintenance required text is missing.")
        return
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise MigrationSchemaError("Maintenance text is incompatible.")


def _zone(value) -> None:
    try: ZoneInfo(value)
    except Exception as error: raise MigrationSchemaError("Maintenance timezone is incompatible.") from error


def _where(value) -> str | None:
    return None if value is None else _normalise(str(value))


def _normalise(value: str) -> str:
    return "".join(value.lower().split())


def _trigger_sql(value: str) -> str:
    return " ".join(value.replace('"', "").split()).casefold()

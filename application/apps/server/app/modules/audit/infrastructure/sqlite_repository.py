"""SQLite adapter for immutable audit events."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from app.modules.audit.domain.models import ACTOR_KINDS, AuditEvent


def install_audit_schema(connection: sqlite3.Connection) -> None:
    actors = ", ".join(f"'{actor}'" for actor in sorted(ACTOR_KINDS))
    statements = (
        f"""CREATE TABLE audit_events (
      id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, entity_type TEXT NOT NULL CHECK(length(trim(entity_type)) > 0),
      entity_id TEXT NOT NULL CHECK(length(trim(entity_id)) > 0), action TEXT NOT NULL CHECK(length(trim(action)) > 0),
      before_snapshot TEXT, after_snapshot TEXT, changed_fields TEXT NOT NULL, reason TEXT,
      actor_kind TEXT NOT NULL CHECK(actor_kind IN ({actors})), actor_reference TEXT,
      correlation_id TEXT NOT NULL, schema_version INTEGER NOT NULL
    )""",
        "CREATE INDEX audit_events_entity_time ON audit_events(entity_type, entity_id, occurred_at, id)",
        "CREATE INDEX audit_events_correlation ON audit_events(correlation_id, occurred_at, id)",
        "CREATE INDEX audit_events_activity ON audit_events(occurred_at, action, actor_kind)",
        "CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END",
        "CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END",
    )
    for statement in statements:
        connection.execute(statement)


class SQLiteAuditRepository:
    def __init__(self, database_path: Path) -> None: self.database_path = database_path

    def append(self, connection: Any, event: AuditEvent) -> None:
        connection.execute(_INSERT, _values(event))

    def append_many(self, connection: Any, events: list[AuditEvent]) -> None:
        connection.executemany(_INSERT, [_values(event) for event in events])

    def history(self, entity_type: str | None = None, entity_id: str | None = None, *, correlation_id: str | None = None,
                action: str | None = None, actor_kind: str | None = None, occurred_after: datetime | None = None,
                occurred_before: datetime | None = None, limit: int = 100, offset: int = 0) -> list[AuditEvent]:
        limit = min(max(limit, 1), 500); offset = max(offset, 0)
        clauses: list[str] = []; params: list[object] = []
        for column, value in (("entity_type", entity_type), ("entity_id", entity_id), ("correlation_id", correlation_id), ("action", action), ("actor_kind", actor_kind)):
            if value is not None: clauses.append(f"{column} = ?"); params.append(value)
        if occurred_after: clauses.append("occurred_at >= ?"); params.append(occurred_after.isoformat())
        if occurred_before: clauses.append("occurred_at <= ?"); params.append(occurred_before.isoformat())
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        uri = f"{self.database_path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(f"SELECT {_COLUMNS} FROM audit_events{where} ORDER BY occurred_at, id LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        return [_event_from_row(row) for row in rows]


_COLUMNS = "id, occurred_at, entity_type, entity_id, action, before_snapshot, after_snapshot, changed_fields, reason, actor_kind, actor_reference, correlation_id, schema_version"
_INSERT = f"INSERT INTO audit_events ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
def _values(event: AuditEvent) -> tuple[object, ...]:
    return (event.id, event.occurred_at.isoformat(), event.entity_type, event.entity_id, event.action, _json(event.before_snapshot), _json(event.after_snapshot), _json(list(event.changed_fields)), event.reason, event.actor_kind, event.actor_reference, event.correlation_id, event.schema_version)
def _json(value: object) -> str | None: return json.dumps(value, sort_keys=True, separators=(",", ":")) if value is not None else None
def _event_from_row(row: sqlite3.Row) -> AuditEvent:
    return AuditEvent(row["id"], datetime.fromisoformat(row["occurred_at"]), row["entity_type"], row["entity_id"], row["action"], json.loads(row["before_snapshot"]) if row["before_snapshot"] else None, json.loads(row["after_snapshot"]) if row["after_snapshot"] else None, tuple(json.loads(row["changed_fields"])), row["reason"], row["actor_kind"], row["actor_reference"], row["correlation_id"], row["schema_version"])

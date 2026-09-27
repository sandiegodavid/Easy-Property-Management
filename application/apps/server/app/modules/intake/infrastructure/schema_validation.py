"""Exact-schema and retained graph validation for INGEST-001."""
from __future__ import annotations
import json
from datetime import UTC, datetime
from uuid import UUID
from sqlalchemy import inspect, text
from sqlalchemy.dialects import sqlite
from app.modules.intake.domain.models import EvidenceEnvelope, fingerprint
from app.modules.intake.infrastructure.sqlalchemy_models import IntakeDuplicateCandidateModel, IntakeEvidenceRevisionModel, IntakeRevisionFileLinkModel, IntakeSourceModel, IntakeSourceOperationModel
from app.platform.migration_errors import MigrationSchemaError

MODELS = (IntakeSourceModel, IntakeEvidenceRevisionModel, IntakeRevisionFileLinkModel, IntakeSourceOperationModel, IntakeDuplicateCandidateModel)
TRIGGERS = {
    "intake_source_operations_no_update": "CREATE TRIGGER intake_source_operations_no_update BEFORE UPDATE ON intake_source_operations BEGIN SELECT RAISE(ABORT, 'intake operations are immutable'); END",
    "intake_source_operations_no_delete": "CREATE TRIGGER intake_source_operations_no_delete BEFORE DELETE ON intake_source_operations BEGIN SELECT RAISE(ABORT, 'intake operations are immutable'); END",
}
def _sql(value): return " ".join(str(value).replace('"','').split()).casefold()
def _where(value): return "" if value is None else _sql(value.compile(dialect=sqlite.dialect(),compile_kwargs={"literal_binds":True})) if hasattr(value,"compile") else _sql(value)

def validate_intake_schema(connection) -> None:
    inspector=inspect(connection)
    for model in MODELS:
        table=model.__table__; actual={c["name"]:c for c in inspector.get_columns(table.name)}; expected={c.name:c for c in table.columns}
        if set(actual)!=set(expected): raise MigrationSchemaError(f"{table.name} columns are incompatible with INGEST-001.")
        if any(str(actual[name]["type"]).upper()!=str(column.type).upper() or bool(actual[name]["nullable"])!=bool(column.nullable) for name,column in expected.items()): raise MigrationSchemaError(f"{table.name} column definition is incompatible with INGEST-001.")
        if {item["name"] for item in inspector.get_columns(table.name) if item["primary_key"]}!={c.name for c in table.primary_key.columns}: raise MigrationSchemaError(f"{table.name} primary key is incompatible with INGEST-001.")
        actual_fk={(x["constrained_columns"][0],x["referred_table"],x["referred_columns"][0]) for x in inspector.get_foreign_keys(table.name)}; expected_fk={(fk.parent.name,fk.column.table.name,fk.column.name) for col in table.columns for fk in col.foreign_keys}
        if actual_fk!=expected_fk: raise MigrationSchemaError(f"{table.name} foreign keys are incompatible with INGEST-001.")
        actual_indexes={(x["name"],tuple(x["column_names"]),bool(x["unique"]),_where(x.get("dialect_options",{}).get("sqlite_where"))) for x in inspector.get_indexes(table.name)}; expected_indexes={(x.name,tuple(c.name for c in x.columns),bool(x.unique),_where(x.dialect_options["sqlite"].get("where"))) for x in table.indexes}
        if actual_indexes!=expected_indexes: raise MigrationSchemaError(f"{table.name} indexes are incompatible with INGEST-001.")
        actual_unique={tuple(x["column_names"]) for x in inspector.get_unique_constraints(table.name)}; expected_unique={tuple(x.columns.keys()) for x in table.constraints if x.__class__.__name__=="UniqueConstraint"}|{(c.name,) for c in table.columns if c.unique}
        if actual_unique!=expected_unique: raise MigrationSchemaError(f"{table.name} unique constraints are incompatible with INGEST-001.")
        if {_sql(x["sqltext"]) for x in inspector.get_check_constraints(table.name)} != {_sql(x.sqltext) for x in table.constraints if x.__class__.__name__=="CheckConstraint"}: raise MigrationSchemaError(f"{table.name} checks are incompatible with INGEST-001.")
    actual={name:_sql(sql) for name,sql in connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='intake_source_operations'")}; expected={name:_sql(sql) for name,sql in TRIGGERS.items()}
    if actual!=expected: raise MigrationSchemaError("INGEST-001 operation triggers are incompatible.")
    validate_intake_data(connection)

def validate_intake_data(connection) -> None:
    if connection.execute(text("PRAGMA foreign_key_check")).first() is not None: raise MigrationSchemaError("INGEST-001 has invalid foreign keys.")
    sources={r["id"]:r for r in connection.execute(text("SELECT * FROM intake_sources")).mappings()}; revisions={r["id"]:r for r in connection.execute(text("SELECT * FROM intake_evidence_revisions")).mappings()}
    for source in sources.values():
        _uuid(source["id"]); _timestamp(source["occurred_at_utc"]); _timestamp(source["received_at_utc"]); _timestamp(source["created_at"]); _timestamp(source["updated_at"])
        revision=revisions.get(source["current_revision_id"])
        if revision is None or revision["source_id"] != source["id"]: raise MigrationSchemaError("INGEST-001 current revision is invalid.")
        if source["technical_status"] == "superseded" and not source["superseded_by_source_id"]: raise MigrationSchemaError("INGEST-001 superseded source is invalid.")
        for pointer, inverse in (("supersedes_source_id","superseded_by_source_id"),("superseded_by_source_id","supersedes_source_id")):
            target=source[pointer]
            if target and (target not in sources or sources[target][inverse] != source["id"]): raise MigrationSchemaError("INGEST-001 source lineage is invalid.")
    for revision in revisions.values():
        _uuid(revision["id"]); _timestamp(revision["created_at"])
        if revision["source_id"] not in sources: raise MigrationSchemaError("INGEST-001 revision source is invalid.")
        try:
            envelope=json.loads(revision["envelope_json"])
            evidence=EvidenceEnvelope(envelope["sourceKind"], envelope["channel"], envelope["body"], envelope["occurredAtUtc"], envelope.get("subject"), tuple(envelope.get("participants",[])), envelope.get("provider"), envelope.get("conversationRef"), envelope.get("externalSourceId"))
        except (KeyError, TypeError, ValueError) as error: raise MigrationSchemaError("INGEST-001 evidence envelope is invalid.") from error
        if fingerprint(envelope) != revision["content_fingerprint"] or evidence.source_kind != sources[revision["source_id"]]["source_kind"]: raise MigrationSchemaError("INGEST-001 evidence fingerprint is invalid.")
        if revision["revision_number"] == 1 and revision["revision_kind"] != "submitted": raise MigrationSchemaError("INGEST-001 initial revision is invalid.")
    for source_id in sources:
        chain=sorted((r for r in revisions.values() if r["source_id"]==source_id),key=lambda r:r["revision_number"])
        if [r["revision_number"] for r in chain] != list(range(1,len(chain)+1)): raise MigrationSchemaError("INGEST-001 revision sequence is invalid.")
    links=list(connection.execute(text("SELECT * FROM intake_revision_file_links")).mappings())
    for link in links:
        revision=revisions.get(link["revision_id"])
        row=connection.execute(text("SELECT entity_type,entity_id,purpose,archived_at FROM file_links WHERE id=:id"),{"id":link["file_link_id"]}).mappings().first()
        if revision is None or row is None or row["entity_type"]!="intake_source" or row["entity_id"]!=revision["source_id"] or row["purpose"]!=link["attachment_role"] or row["archived_at"] is not None: raise MigrationSchemaError("INGEST-001 attachment association is invalid.")
    for revision in revisions.values():
        declared=json.loads(revision["envelope_json"]).get("attachments",[]); actual=[link for link in links if link["revision_id"]==revision["id"]]
        if len(declared)!=len(actual): raise MigrationSchemaError("INGEST-001 attachment manifest is invalid.")
    for operation in connection.execute(text("SELECT * FROM intake_source_operations")).mappings():
        _uuid(operation["id"]); _uuid(operation["idempotency_key"]); _uuid(operation["correlation_id"]); _timestamp(operation["created_at"])
        if operation["source_id"] not in sources or len(operation["request_fingerprint"])!=64 or any(c not in "0123456789abcdef" for c in operation["request_fingerprint"]): raise MigrationSchemaError("INGEST-001 operation is invalid.")

def _uuid(value):
    try: UUID(str(value))
    except (ValueError,TypeError) as error: raise MigrationSchemaError("INGEST-001 identifier is invalid.") from error
def _timestamp(value):
    try: parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except ValueError as error: raise MigrationSchemaError("INGEST-001 timestamp is invalid.") from error
    if parsed.tzinfo is None or parsed.utcoffset()!=UTC.utcoffset(parsed): raise MigrationSchemaError("INGEST-001 timestamp is not UTC.")

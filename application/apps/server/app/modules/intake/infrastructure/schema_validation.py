"""Exact-schema and retained graph validation for INGEST-001."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import inspect, text
from sqlalchemy.dialects import sqlite

from app.modules.intake.domain.models import FAILURE_CODES, EvidenceEnvelope, canonical_json, fingerprint
from app.modules.intake.infrastructure.sqlalchemy_models import (
    IntakeDuplicateCandidateModel,
    IntakeEvidenceRevisionModel,
    IntakeRevisionFileLinkModel,
    IntakeSourceModel,
    IntakeSourceOperationModel,
)
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
        if source["technical_status"] == "failed" and source["failure_code"] not in FAILURE_CODES: raise MigrationSchemaError("INGEST-001 failed source has an unsupported failure code.")
        if source["technical_status"] != "failed" and source["failure_code"] is not None: raise MigrationSchemaError("INGEST-001 nonfailed source has a failure code.")
        for pointer, inverse in (("supersedes_source_id","superseded_by_source_id"),("superseded_by_source_id","supersedes_source_id")):
            target=source[pointer]
            if target and (target not in sources or sources[target][inverse] != source["id"]): raise MigrationSchemaError("INGEST-001 source lineage is invalid.")
    for source_id in sources:
        seen: set[str] = set(); current = source_id
        while sources[current]["supersedes_source_id"] is not None:
            if current in seen: raise MigrationSchemaError("INGEST-001 source lineage has a cycle.")
            seen.add(current); current = sources[current]["supersedes_source_id"]
    trusted = {"transport_verified", "operator_confirmed"}
    for root in (row for row in sources.values() if row["supersedes_source_id"] is None):
        lineage = [root]
        while lineage[-1]["superseded_by_source_id"] is not None:
            lineage.append(sources[lineage[-1]["superseded_by_source_id"]])
        if any(row["account_identity_state"] in trusted for row in lineage):
            identity = tuple(root[key] for key in (
                "origin_system", "account_scope_hash", "source_kind",
                "external_source_id", "account_identity_state",
            ))
            if any(
                row["account_identity_state"] not in trusted
                or tuple(row[key] for key in (
                    "origin_system", "account_scope_hash", "source_kind",
                    "external_source_id", "account_identity_state",
                )) != identity
                for row in lineage
            ):
                raise MigrationSchemaError("INGEST-001 trusted source lineage has inconsistent identity.")
            if sum(row["superseded_by_source_id"] is None for row in lineage) != 1:
                raise MigrationSchemaError("INGEST-001 trusted source lineage has an invalid current tip.")
    for revision in revisions.values():
        _uuid(revision["id"]); _timestamp(revision["created_at"])
        if revision["source_id"] not in sources: raise MigrationSchemaError("INGEST-001 revision source is invalid.")
        try:
            envelope=json.loads(revision["envelope_json"])
            required = {"schemaVersion", "sourceKind", "channel", "subject", "body", "participants", "occurredAtUtc", "occurredAtContext", "provider", "conversationRef", "externalSourceId", "attachments"}
            if set(envelope) != required or envelope["schemaVersion"] != 1 or canonical_json(envelope) != revision["envelope_json"]: raise ValueError
            evidence=EvidenceEnvelope(envelope["sourceKind"], envelope["channel"], envelope["body"], envelope["occurredAtUtc"], envelope.get("subject"), tuple(envelope.get("participants",[])), envelope.get("provider"), envelope.get("conversationRef"), envelope.get("externalSourceId"), envelope.get("occurredAtContext"))
        except (KeyError, TypeError, ValueError) as error: raise MigrationSchemaError("INGEST-001 evidence envelope is invalid.") from error
        if fingerprint(envelope) != revision["content_fingerprint"] or evidence.source_kind != sources[revision["source_id"]]["source_kind"]: raise MigrationSchemaError("INGEST-001 evidence fingerprint is invalid.")
        if revision["revision_number"] == 1 and revision["revision_kind"] != "submitted": raise MigrationSchemaError("INGEST-001 initial revision is invalid.")
    for source_id in sources:
        chain=sorted((r for r in revisions.values() if r["source_id"]==source_id),key=lambda r:r["revision_number"])
        if [r["revision_number"] for r in chain] != list(range(1,len(chain)+1)): raise MigrationSchemaError("INGEST-001 revision sequence is invalid.")
        if chain[-1]["id"] != sources[source_id]["current_revision_id"]: raise MigrationSchemaError("INGEST-001 current revision is not the lineage tip.")
        for index, revision in enumerate(chain):
            previous = chain[index - 1] if index else None
            if previous is None:
                if revision["supersedes_revision_id"] is not None: raise MigrationSchemaError("INGEST-001 initial revision has a predecessor.")
            elif revision["supersedes_revision_id"] != previous["id"] or previous["superseded_by_revision_id"] != revision["id"]:
                raise MigrationSchemaError("INGEST-001 revision lineage is invalid.")
    links=list(connection.execute(text("SELECT * FROM intake_revision_file_links")).mappings())
    for link in links:
        revision=revisions.get(link["revision_id"])
        row=connection.execute(text("SELECT l.entity_type,l.entity_id,l.purpose,l.archived_at,f.content_sha256,c.storage_state FROM file_links l JOIN file_records f ON f.id=l.file_id JOIN file_content_locations c ON c.file_id=f.id WHERE l.id=:id"),{"id":link["file_link_id"]}).mappings().first()
        # Availability is mutable FILE-001 lifecycle state.  It is verified
        # when admitted and later changes source technical status; historical
        # Intake evidence must remain valid and explainable while unavailable.
        if revision is None or row is None or row["entity_type"]!="intake_source" or row["entity_id"]!=revision["source_id"] or row["purpose"]!=link["attachment_role"] or row["archived_at"] is not None: raise MigrationSchemaError("INGEST-001 attachment association is invalid.")
    for revision in revisions.values():
        declared=json.loads(revision["envelope_json"])["attachments"]; actual=sorted((link for link in links if link["revision_id"]==revision["id"]),key=lambda link:link["display_order"])
        manifest=[]
        for link in actual:
            row=connection.execute(text("SELECT f.content_sha256 FROM file_links l JOIN file_records f ON f.id=l.file_id WHERE l.id=:id"),{"id":link["file_link_id"]}).mappings().one()
            manifest.append({"role":link["attachment_role"],"contentSha256":row["content_sha256"]})
        if declared != manifest or [link["display_order"] for link in actual] != list(range(len(actual))): raise MigrationSchemaError("INGEST-001 attachment manifest is invalid.")
    for operation in connection.execute(text("SELECT * FROM intake_source_operations")).mappings():
        _uuid(operation["id"]); _uuid(operation["idempotency_key"]); _uuid(operation["correlation_id"]); _timestamp(operation["created_at"])
        if operation["source_id"] not in sources or len(operation["request_fingerprint"])!=64 or any(c not in "0123456789abcdef" for c in operation["request_fingerprint"]): raise MigrationSchemaError("INGEST-001 operation is invalid.")
        if operation["operation_type"] == "attention_transition":
            try:
                result = json.loads(operation["result_json"])
                if (canonical_json(result) != operation["result_json"]
                        or result["sourceId"] != operation["source_id"]
                        or result["revision"] != operation["result_revision_id"]
                        or result["attentionStatus"] not in {"unprocessed", "in_review", "resolved", "dismissed"}):
                    raise ValueError
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise MigrationSchemaError("INGEST-001 attention operation result is invalid.") from error

def _uuid(value):
    try: UUID(str(value))
    except (ValueError,TypeError) as error: raise MigrationSchemaError("INGEST-001 identifier is invalid.") from error
def _timestamp(value):
    try: parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except ValueError as error: raise MigrationSchemaError("INGEST-001 timestamp is invalid.") from error
    if parsed.tzinfo is None or parsed.utcoffset()!=UTC.utcoffset(parsed): raise MigrationSchemaError("INGEST-001 timestamp is not UTC.")

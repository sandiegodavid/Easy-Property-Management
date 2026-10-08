"""Exact-schema and retained graph validation for INGEST-001."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import inspect, text
from sqlalchemy.dialects import sqlite

from app.modules.intake.domain.models import (
    FAILURE_CODES,
    EvidenceEnvelope,
    attention_transition_allowed,
    canonical_json,
    fingerprint,
)
from app.modules.intake.infrastructure.sqlalchemy_models import (
    IntakeDuplicateCandidateModel,
    IntakeEvidenceRevisionModel,
    IntakeRevisionFileLinkModel,
    IntakeSourceModel,
    IntakeSourceOperationModel,
)
from app.platform.migration_errors import MigrationSchemaError

MODELS = (
    IntakeSourceModel,
    IntakeEvidenceRevisionModel,
    IntakeRevisionFileLinkModel,
    IntakeSourceOperationModel,
    IntakeDuplicateCandidateModel,
)
TRIGGERS = {
    "intake_source_operations_no_update": "CREATE TRIGGER intake_source_operations_no_update BEFORE UPDATE ON intake_source_operations BEGIN SELECT RAISE(ABORT, 'intake operations are immutable'); END",
    "intake_source_operations_no_delete": "CREATE TRIGGER intake_source_operations_no_delete BEFORE DELETE ON intake_source_operations BEGIN SELECT RAISE(ABORT, 'intake operations are immutable'); END",
}


def _sql(value):
    return " ".join(str(value).replace('"', "").split()).casefold()


def _where(value):
    return (
        ""
        if value is None
        else _sql(value.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        if hasattr(value, "compile")
        else _sql(value)
    )


def validate_intake_schema(connection) -> None:
    inspector = inspect(connection)
    for model in MODELS:
        table = model.__table__
        actual = {c["name"]: c for c in inspector.get_columns(table.name)}
        expected = {c.name: c for c in table.columns}
        if set(actual) != set(expected):
            raise MigrationSchemaError(f"{table.name} columns are incompatible with INGEST-001.")
        if any(
            str(actual[name]["type"]).upper() != str(column.type).upper()
            or bool(actual[name]["nullable"]) != bool(column.nullable)
            for name, column in expected.items()
        ):
            raise MigrationSchemaError(
                f"{table.name} column definition is incompatible with INGEST-001."
            )
        if {item["name"] for item in inspector.get_columns(table.name) if item["primary_key"]} != {
            c.name for c in table.primary_key.columns
        }:
            raise MigrationSchemaError(f"{table.name} primary key is incompatible with INGEST-001.")
        actual_fk = {
            (x["constrained_columns"][0], x["referred_table"], x["referred_columns"][0])
            for x in inspector.get_foreign_keys(table.name)
        }
        expected_fk = {
            (fk.parent.name, fk.column.table.name, fk.column.name)
            for col in table.columns
            for fk in col.foreign_keys
        }
        if actual_fk != expected_fk:
            raise MigrationSchemaError(
                f"{table.name} foreign keys are incompatible with INGEST-001."
            )
        actual_indexes = {
            (
                x["name"],
                tuple(x["column_names"]),
                bool(x["unique"]),
                _where(x.get("dialect_options", {}).get("sqlite_where")),
            )
            for x in inspector.get_indexes(table.name)
        }
        expected_indexes = {
            (
                x.name,
                tuple(c.name for c in x.columns),
                bool(x.unique),
                _where(x.dialect_options["sqlite"].get("where")),
            )
            for x in table.indexes
        }
        if actual_indexes != expected_indexes:
            raise MigrationSchemaError(f"{table.name} indexes are incompatible with INGEST-001.")
        actual_unique = {
            tuple(x["column_names"]) for x in inspector.get_unique_constraints(table.name)
        }
        expected_unique = {
            tuple(x.columns.keys())
            for x in table.constraints
            if x.__class__.__name__ == "UniqueConstraint"
        } | {(c.name,) for c in table.columns if c.unique}
        if actual_unique != expected_unique:
            raise MigrationSchemaError(
                f"{table.name} unique constraints are incompatible with INGEST-001."
            )
        if {_sql(x["sqltext"]) for x in inspector.get_check_constraints(table.name)} != {
            _sql(x.sqltext) for x in table.constraints if x.__class__.__name__ == "CheckConstraint"
        }:
            raise MigrationSchemaError(f"{table.name} checks are incompatible with INGEST-001.")
    actual = {
        name: _sql(sql)
        for name, sql in connection.exec_driver_sql(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='intake_source_operations'"
        )
    }
    expected = {name: _sql(sql) for name, sql in TRIGGERS.items()}
    if actual != expected:
        raise MigrationSchemaError("INGEST-001 operation triggers are incompatible.")
    validate_intake_data(connection)


def validate_intake_data(connection) -> None:
    if connection.execute(text("PRAGMA foreign_key_check")).first() is not None:
        raise MigrationSchemaError("INGEST-001 has invalid foreign keys.")
    sources = {
        r["id"]: r for r in connection.execute(text("SELECT * FROM intake_sources")).mappings()
    }
    revisions = {
        r["id"]: r
        for r in connection.execute(text("SELECT * FROM intake_evidence_revisions")).mappings()
    }
    for source in sources.values():
        _uuid(source["id"])
        if type(source["source_revision"]) is not int or source["source_revision"] < 1:
            raise MigrationSchemaError("INGEST-001 source revision is invalid.")
        _timestamp(source["occurred_at_utc"])
        _timestamp(source["received_at_utc"])
        _timestamp(source["created_at"])
        _timestamp(source["updated_at"])
        revision = revisions.get(source["current_revision_id"])
        if revision is None or revision["source_id"] != source["id"]:
            raise MigrationSchemaError("INGEST-001 current revision is invalid.")
        if source["technical_status"] == "superseded" and not source["superseded_by_source_id"]:
            raise MigrationSchemaError("INGEST-001 superseded source is invalid.")
        if source["technical_status"] == "failed" and source["failure_code"] not in FAILURE_CODES:
            raise MigrationSchemaError("INGEST-001 failed source has an unsupported failure code.")
        if source["technical_status"] != "failed" and source["failure_code"] is not None:
            raise MigrationSchemaError("INGEST-001 nonfailed source has a failure code.")
        for pointer, inverse in (
            ("supersedes_source_id", "superseded_by_source_id"),
            ("superseded_by_source_id", "supersedes_source_id"),
        ):
            target = source[pointer]
            if target and (target not in sources or sources[target][inverse] != source["id"]):
                raise MigrationSchemaError("INGEST-001 source lineage is invalid.")
    for source_id in sources:
        seen: set[str] = set()
        current = source_id
        while sources[current]["supersedes_source_id"] is not None:
            if current in seen:
                raise MigrationSchemaError("INGEST-001 source lineage has a cycle.")
            seen.add(current)
            current = sources[current]["supersedes_source_id"]
    trusted = {"transport_verified", "operator_confirmed"}
    for root in (row for row in sources.values() if row["supersedes_source_id"] is None):
        lineage = [root]
        while lineage[-1]["superseded_by_source_id"] is not None:
            lineage.append(sources[lineage[-1]["superseded_by_source_id"]])
        if any(row["account_identity_state"] in trusted for row in lineage):
            identity = tuple(
                root[key]
                for key in (
                    "origin_system",
                    "account_scope_hash",
                    "source_kind",
                    "external_source_id",
                    "account_identity_state",
                )
            )
            if any(
                row["account_identity_state"] not in trusted
                or tuple(
                    row[key]
                    for key in (
                        "origin_system",
                        "account_scope_hash",
                        "source_kind",
                        "external_source_id",
                        "account_identity_state",
                    )
                )
                != identity
                for row in lineage
            ):
                raise MigrationSchemaError(
                    "INGEST-001 trusted source lineage has inconsistent identity."
                )
            if sum(row["superseded_by_source_id"] is None for row in lineage) != 1:
                raise MigrationSchemaError(
                    "INGEST-001 trusted source lineage has an invalid current tip."
                )
    for revision in revisions.values():
        _uuid(revision["id"])
        _timestamp(revision["created_at"])
        if revision["source_id"] not in sources:
            raise MigrationSchemaError("INGEST-001 revision source is invalid.")
        try:
            envelope = json.loads(revision["envelope_json"])
            required = {
                "schemaVersion",
                "sourceKind",
                "channel",
                "subject",
                "body",
                "participants",
                "occurredAtUtc",
                "occurredAtContext",
                "provider",
                "conversationRef",
                "externalSourceId",
                "attachments",
            }
            if (
                set(envelope) != required
                or envelope["schemaVersion"] != 1
                or canonical_json(envelope) != revision["envelope_json"]
            ):
                raise ValueError
            evidence = EvidenceEnvelope(
                envelope["sourceKind"],
                envelope["channel"],
                envelope["body"],
                envelope["occurredAtUtc"],
                envelope.get("subject"),
                tuple(envelope.get("participants", [])),
                envelope.get("provider"),
                envelope.get("conversationRef"),
                envelope.get("externalSourceId"),
                envelope.get("occurredAtContext"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise MigrationSchemaError("INGEST-001 evidence envelope is invalid.") from error
        if (
            fingerprint(envelope) != revision["content_fingerprint"]
            or evidence.source_kind != sources[revision["source_id"]]["source_kind"]
        ):
            raise MigrationSchemaError("INGEST-001 evidence fingerprint is invalid.")
        if revision["revision_number"] == 1 and revision["revision_kind"] != "submitted":
            raise MigrationSchemaError("INGEST-001 initial revision is invalid.")
    for source_id in sources:
        chain = sorted(
            (r for r in revisions.values() if r["source_id"] == source_id),
            key=lambda r: r["revision_number"],
        )
        if [r["revision_number"] for r in chain] != list(range(1, len(chain) + 1)):
            raise MigrationSchemaError("INGEST-001 revision sequence is invalid.")
        if chain[-1]["id"] != sources[source_id]["current_revision_id"]:
            raise MigrationSchemaError("INGEST-001 current revision is not the lineage tip.")
        for index, revision in enumerate(chain):
            previous = chain[index - 1] if index else None
            if previous is None:
                if revision["supersedes_revision_id"] is not None:
                    raise MigrationSchemaError("INGEST-001 initial revision has a predecessor.")
            elif (
                revision["supersedes_revision_id"] != previous["id"]
                or previous["superseded_by_revision_id"] != revision["id"]
            ):
                raise MigrationSchemaError("INGEST-001 revision lineage is invalid.")
    links = list(connection.execute(text("SELECT * FROM intake_revision_file_links")).mappings())
    for link in links:
        revision = revisions.get(link["revision_id"])
        row = (
            connection.execute(
                text(
                    "SELECT l.entity_type,l.entity_id,l.purpose,l.archived_at,f.content_sha256,c.storage_state FROM file_links l JOIN file_records f ON f.id=l.file_id JOIN file_content_locations c ON c.file_id=f.id WHERE l.id=:id"
                ),
                {"id": link["file_link_id"]},
            )
            .mappings()
            .first()
        )
        # Availability is mutable FILE-001 lifecycle state.  It is verified
        # when admitted and later changes source technical status; historical
        # Intake evidence must remain valid and explainable while unavailable.
        if (
            revision is None
            or row is None
            or row["entity_type"] != "intake_source"
            or row["entity_id"] != revision["source_id"]
            or row["purpose"] != link["attachment_role"]
            or row["archived_at"] is not None
        ):
            raise MigrationSchemaError("INGEST-001 attachment association is invalid.")
    for revision in revisions.values():
        declared = json.loads(revision["envelope_json"])["attachments"]
        actual = sorted(
            (link for link in links if link["revision_id"] == revision["id"]),
            key=lambda link: link["display_order"],
        )
        manifest = []
        for link in actual:
            row = (
                connection.execute(
                    text(
                        "SELECT f.content_sha256 FROM file_links l JOIN file_records f ON f.id=l.file_id WHERE l.id=:id"
                    ),
                    {"id": link["file_link_id"]},
                )
                .mappings()
                .one()
            )
            manifest.append(
                {"role": link["attachment_role"], "contentSha256": row["content_sha256"]}
            )
        if declared != manifest or [link["display_order"] for link in actual] != list(
            range(len(actual))
        ):
            raise MigrationSchemaError("INGEST-001 attachment manifest is invalid.")
    audits = list(
        connection.execute(
            text(
                "SELECT id,entity_type,entity_id,action,before_snapshot,after_snapshot,correlation_id FROM audit_events"
            )
        ).mappings()
    )
    operations, expected_audits = _validate_operations(connection, sources, revisions, audits)
    expected_audits.update(
        _validate_duplicate_candidates(connection, sources, revisions, audits, operations)
    )
    _validate_intake_audit_stream(audits, sources, revisions, expected_audits)
    _validate_lifecycle_consequences(sources, operations, audits)


def _validate_operations(connection, sources, revisions, audits):
    operations = list(connection.execute(text("SELECT * FROM intake_source_operations")).mappings())
    if len({row["correlation_id"] for row in operations}) != len(operations):
        raise MigrationSchemaError("INGEST-001 operation correlations must be unique.")
    expected: set[tuple[str, str, str, str]] = set()
    for operation in operations:
        _uuid(operation["id"])
        _uuid(operation["idempotency_key"])
        _uuid(operation["correlation_id"])
        _timestamp(operation["created_at"])
        if operation["source_id"] not in sources or not _sha256(operation["request_fingerprint"]):
            raise MigrationSchemaError("INGEST-001 operation is invalid.")
        if operation["actor_kind"] not in {
            "local_operator",
            "assistant_connection",
            "voice_workflow",
            "system",
            "ai_assistant",
        }:
            raise MigrationSchemaError("INGEST-001 operation actor is invalid.")
        payload = _operation_payload(operation)
        result = (
            revisions.get(operation["result_revision_id"])
            if operation["result_revision_id"]
            else None
        )
        if result is not None and result["source_id"] != operation["source_id"]:
            raise MigrationSchemaError(
                "INGEST-001 operation result revision belongs to another source."
            )
        if (
            operation["outcome"] != "succeeded"
            or result is None
            or operation["error_code"] is not None
        ):
            raise MigrationSchemaError("INGEST-001 operation outcome is invalid.")
        related = [
            event for event in audits if event["correlation_id"] == operation["correlation_id"]
        ]
        kind = operation["operation_type"]
        _validate_operation_payload(operation, payload, result, sources, revisions, related)
        if kind not in {"integrity_failed", "integrity_restored"}:
            _validate_command_result(operation, result)
        if kind == "admit":
            admitted = _audit(related, "intake_source", operation["source_id"], "admitted")
            replayed = _audit(
                related, "intake_source", operation["source_id"], "admission_replayed"
            )
            if admitted:
                if result["revision_number"] != 1 or result["revision_kind"] != "submitted":
                    raise MigrationSchemaError("INGEST-001 admission result is invalid.")
                _require_snapshot(
                    admitted, None, _admitted_snapshot(sources[operation["source_id"]])
                )
                created = _require_audit(
                    related, "intake_evidence_revision", result["id"], "created"
                )
                _require_snapshot(created, None, _revision_snapshot(result))
                expected.update({_audit_key(admitted), _audit_key(created)})
            elif replayed:
                _require_snapshot(
                    replayed, None, {"sourceId": operation["source_id"], "revision": result["id"]}
                )
                expected.add(_audit_key(replayed))
            else:
                raise MigrationSchemaError("INGEST-001 admission audit evidence is missing.")
        elif kind == "supersede":
            predecessor = sources[operation["source_id"]]["supersedes_source_id"]
            if predecessor is None or result["revision_number"] != 1:
                raise MigrationSchemaError("INGEST-001 supersession result is invalid.")
            admitted = _require_audit(related, "intake_source", operation["source_id"], "admitted")
            superseded = _require_audit(related, "intake_source", predecessor, "superseded")
            created = _require_audit(related, "intake_evidence_revision", result["id"], "created")
            _require_snapshot(admitted, None, _admitted_snapshot(sources[operation["source_id"]]))
            _require_snapshot(
                superseded,
                {"technicalStatus": "ready"},
                {"supersededBySourceId": operation["source_id"], "technicalStatus": "superseded"},
            )
            _require_snapshot(created, None, _revision_snapshot(result))
            expected.update({_audit_key(admitted), _audit_key(superseded), _audit_key(created)})
        elif kind == "correct":
            if result["revision_number"] <= 1:
                raise MigrationSchemaError("INGEST-001 correction result is invalid.")
            corrected = _require_audit(
                related, "intake_source", operation["source_id"], "corrected"
            )
            created = _require_audit(related, "intake_evidence_revision", result["id"], "created")
            _require_snapshot(
                corrected,
                {"revision": result["supersedes_revision_id"]},
                {"revision": result["id"]},
            )
            _require_snapshot(created, None, _revision_snapshot(result))
            expected.update({_audit_key(corrected), _audit_key(created)})
        elif kind == "attention_transition":
            event = _require_audit(
                related, "intake_source", operation["source_id"], "attention_changed"
            )
            before, after = _snapshots(event)
            if (
                set(before) != {"attentionStatus"}
                or set(after) != {"attentionStatus"}
                or not attention_transition_allowed(
                    before["attentionStatus"], after["attentionStatus"]
                )
            ):
                raise MigrationSchemaError("INGEST-001 attention operation audit is invalid.")
            expected.add(_audit_key(event))
        elif kind in {"integrity_failed", "integrity_restored"}:
            event = _require_audit(related, "intake_source", operation["source_id"], kind)
            before, after = _snapshots(event)
            expected_before, expected_after = (
                ("ready", "failed") if kind == "integrity_failed" else ("failed", "ready")
            )
            if (
                set(before) not in ({"technicalStatus"}, {"technicalStatus", "failureCode"})
                or before["technicalStatus"] != expected_before
                or (
                    "failureCode" in before
                    and before["failureCode"]
                    != (None if expected_before == "ready" else "attachment_content_unavailable")
                )
                or set(after) != {"technicalStatus", "failureCode"}
                or after["technicalStatus"] != expected_after
                or (expected_after == "failed" and after["failureCode"] not in FAILURE_CODES)
                or (expected_after == "ready" and after["failureCode"] is not None)
            ):
                raise MigrationSchemaError("INGEST-001 integrity operation audit is invalid.")
            expected.add(_audit_key(event))
        else:
            raise MigrationSchemaError("INGEST-001 operation type is invalid.")
    return operations, expected


def _validate_duplicate_candidates(connection, sources, revisions, audits, operations):
    expected: set[tuple[str, str, str, str]] = set()
    for candidate in connection.execute(
        text("SELECT * FROM intake_source_duplicate_candidates")
    ).mappings():
        _uuid(candidate["id"])
        _timestamp(candidate["created_at"])
        if (
            candidate["source_id"] not in sources
            or candidate["candidate_source_id"] not in sources
            or candidate["source_id"] >= candidate["candidate_source_id"]
        ):
            raise MigrationSchemaError("INGEST-001 duplicate candidate pair is invalid.")
        if (
            candidate["reason"] not in {"content_fingerprint", "conversation_similarity"}
            or candidate["confidence_label"] not in {"low", "medium", "high"}
            or not _payload_text(candidate["confidence_provenance"], 500)
        ):
            raise MigrationSchemaError("INGEST-001 duplicate candidate classification is invalid.")
        if candidate["reason"] == "content_fingerprint" and (
            candidate["confidence_label"],
            candidate["confidence_provenance"],
        ) != ("high", "exact_canonical_evidence"):
            raise MigrationSchemaError("INGEST-001 duplicate candidate confidence is invalid.")
        if candidate["disposition"] == "unreviewed":
            if candidate["decided_at"] is not None or candidate["decision_reason"] is not None:
                raise MigrationSchemaError("INGEST-001 unreviewed duplicate candidate is invalid.")
        elif (
            candidate["disposition"] in {"distinct", "same_source"}
            and candidate["decided_at"] is not None
            and _payload_text(candidate["decision_reason"], 1000)
        ):
            _timestamp(candidate["decided_at"])
        else:
            raise MigrationSchemaError("INGEST-001 duplicate candidate disposition is invalid.")
        event = _require_audit(
            audits, "intake_source_duplicate_candidate", candidate["id"], "created"
        )
        _, after = _snapshots(event)
        if (
            set(after)
            != {"sourceId", "candidateSourceId", "introducedSourceId", "reason", "disposition"}
            or after.get("sourceId") != candidate["source_id"]
            or after.get("candidateSourceId") != candidate["candidate_source_id"]
            or after.get("reason") != candidate["reason"]
            or after.get("disposition") != candidate["disposition"]
        ):
            raise MigrationSchemaError("INGEST-001 duplicate candidate audit evidence is invalid.")
        operation = next(
            (
                row
                for row in operations
                if row["correlation_id"] == event["correlation_id"]
                and row["operation_type"] in {"admit", "supersede", "correct"}
                and row["source_id"] == after["introducedSourceId"]
            ),
            None,
        )
        if operation is None or operation["source_id"] not in {
            candidate["source_id"],
            candidate["candidate_source_id"],
        }:
            raise MigrationSchemaError(
                "INGEST-001 duplicate candidate audit correlation is invalid."
            )
        other = (
            candidate["candidate_source_id"]
            if operation["source_id"] == candidate["source_id"]
            else candidate["source_id"]
        )
        result = revisions[operation["result_revision_id"]]
        if candidate["reason"] == "content_fingerprint" and not any(
            row["source_id"] == other
            and row["content_fingerprint"] == result["content_fingerprint"]
            and _before_or_equal(row["created_at"], candidate["created_at"])
            for row in revisions.values()
        ):
            raise MigrationSchemaError("INGEST-001 duplicate candidate evidence is invalid.")
        expected.add(_audit_key(event))
    return expected


def _operation_payload(operation):
    try:
        payload = json.loads(operation["request_payload_json"])
    except (TypeError, ValueError) as error:
        raise MigrationSchemaError("INGEST-001 operation request payload is invalid.") from error
    if (
        not isinstance(payload, dict)
        or canonical_json(payload) != operation["request_payload_json"]
        or fingerprint(payload) != operation["request_fingerprint"]
    ):
        raise MigrationSchemaError("INGEST-001 operation request fingerprint is invalid.")
    return payload


def _validate_operation_payload(operation, payload, result, sources, revisions, related):
    source = sources[operation["source_id"]]
    kind = operation["operation_type"]
    if kind in {"admit", "supersede"}:
        replay = (
            _audit(related, "intake_source", operation["source_id"], "admission_replayed")
            is not None
        )
        identity = {
            "origin": source["origin_system"],
            "scope": source["account_scope_hash"],
            "identity": source["account_identity_state"],
            "submitter": {
                "kind": source["submitter_kind"],
                "reference": source["submitter_reference"],
            },
            "supersedes": None if replay else source["supersedes_source_id"],
        }
        if kind == "supersede":
            identity["expectedSourceRevision"] = payload.get("expectedSourceRevision")
            identity["expectedEvidenceRevisionId"] = payload.get("expectedEvidenceRevisionId")
            _validate_expected_revision(payload, revisions, source["supersedes_source_id"])
        admitted_revisions = [
            row
            for row in revisions.values()
            if row["source_id"] == operation["source_id"]
            and json.loads(row["envelope_json"]) == payload.get("admit")
        ]
        if (
            set(payload) != {"admit", *identity}
            or any(payload[key] != value for key, value in identity.items())
            or not admitted_revisions
        ):
            raise MigrationSchemaError("INGEST-001 admission request payload is invalid.")
    elif kind == "correct":
        if payload != {
            "correct": operation["source_id"],
            "envelope": json.loads(result["envelope_json"]),
            "reason": result["correction_reason"],
            "expectedSourceRevision": payload.get("expectedSourceRevision"),
            "expectedEvidenceRevisionId": result["supersedes_revision_id"],
        }:
            raise MigrationSchemaError("INGEST-001 correction request payload is invalid.")
        _validate_expected_revision(payload, revisions, operation["source_id"])
    elif kind == "attention_transition":
        event = _require_audit(
            related, "intake_source", operation["source_id"], "attention_changed"
        )
        before, after = _snapshots(event)
        required = {
            "attention",
            "target",
            "reason",
            "expectedRevision",
            "expectedSourceRevision",
            "expectedStatus",
            "actorKind",
            "actorReference",
        }
        if (
            set(payload) != required
            or payload["attention"] != operation["source_id"]
            or payload["target"] != after["attentionStatus"]
            or payload["expectedRevision"] != operation["result_revision_id"]
            or payload["expectedStatus"] != before["attentionStatus"]
            or payload["actorKind"] != operation["actor_kind"]
            or payload["actorReference"] != operation["actor_reference"]
            or not _payload_text(payload["reason"], 1000)
        ):
            raise MigrationSchemaError("INGEST-001 attention request payload is invalid.")
        if (
            type(payload["expectedSourceRevision"]) is not int
            or payload["expectedSourceRevision"] < 1
        ):
            raise MigrationSchemaError("INGEST-001 expected source revision is invalid.")
    elif kind in {"integrity_failed", "integrity_restored"}:
        event = _require_audit(related, "intake_source", operation["source_id"], kind)
        _, after = _snapshots(event)
        target = "failed" if kind == "integrity_failed" else "ready"
        if (
            set(payload) != {"integrity", "target", "reason"}
            or payload["integrity"] != operation["source_id"]
            or payload["target"] != target
            or after["technicalStatus"] != target
            or not _payload_text(payload["reason"], 200)
            or (target == "failed" and payload["reason"] != after["failureCode"])
        ):
            raise MigrationSchemaError("INGEST-001 integrity request payload is invalid.")


def _validate_command_result(operation, revision) -> None:
    try:
        result = json.loads(operation["result_json"])
        if (
            canonical_json(result) != operation["result_json"]
            or result["sourceId"] != operation["source_id"]
            or result["revision"] != operation["result_revision_id"]
            or result["evidenceRevisionId"] != operation["result_revision_id"]
            or result["operationId"] != operation["id"]
            or type(result["sourceRevision"]) is not int
            or result["sourceRevision"] < 1
            or result["fingerprint"] != revision["content_fingerprint"]
            or (
                "evidence" in result and result["evidence"] != json.loads(revision["envelope_json"])
            )
            or result["attentionStatus"]
            not in {"unprocessed", "in_review", "resolved", "dismissed"}
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise MigrationSchemaError("INGEST-001 command operation result is invalid.") from error


def _validate_expected_revision(payload, revisions, source_id):
    revision = revisions.get(payload.get("expectedEvidenceRevisionId"))
    if (
        type(payload.get("expectedSourceRevision")) is not int
        or payload["expectedSourceRevision"] < 1
        or revision is None
        or revision["source_id"] != source_id
    ):
        raise MigrationSchemaError("INGEST-001 expected revision is invalid.")


def _payload_text(value, maximum: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def _audit(events, entity_type, entity_id, action):
    matches = [
        event
        for event in events
        if event["entity_type"] == entity_type
        and event["entity_id"] == entity_id
        and event["action"] == action
    ]
    if len(matches) > 1:
        raise MigrationSchemaError("INGEST-001 audit evidence is duplicated.")
    return matches[0] if matches else None


def _require_audit(events, entity_type, entity_id, action):
    event = _audit(events, entity_type, entity_id, action)
    if event is None:
        raise MigrationSchemaError("INGEST-001 correlated audit evidence is missing.")
    return event


def _snapshots(event):
    try:
        before = None if event["before_snapshot"] is None else json.loads(event["before_snapshot"])
        after = None if event["after_snapshot"] is None else json.loads(event["after_snapshot"])
    except (TypeError, ValueError) as error:
        raise MigrationSchemaError("INGEST-001 audit snapshot is invalid.") from error
    if (before is not None and not isinstance(before, dict)) or (
        after is not None and not isinstance(after, dict)
    ):
        raise MigrationSchemaError("INGEST-001 audit snapshot is invalid.")
    return before, after


def _require_snapshot(event, expected_before, expected_after):
    if _snapshots(event) != (expected_before, expected_after):
        raise MigrationSchemaError("INGEST-001 audit snapshot contradicts retained data.")


def _audit_key(event):
    return event["correlation_id"], event["entity_type"], event["entity_id"], event["action"]


def _admitted_snapshot(source):
    return {
        "id": source["id"],
        "sourceKind": source["source_kind"],
        "technicalStatus": "ready",
        "attentionStatus": "unprocessed",
        "receivedAtUtc": source["received_at_utc"],
    }


def _revision_snapshot(revision):
    return {
        "sourceId": revision["source_id"],
        "revisionNumber": revision["revision_number"],
        "contentFingerprint": revision["content_fingerprint"],
    }


def _before_or_equal(left, right):
    try:
        return datetime.fromisoformat(str(left).replace("Z", "+00:00")) <= datetime.fromisoformat(
            str(right).replace("Z", "+00:00")
        )
    except ValueError as error:
        raise MigrationSchemaError("INGEST-001 timestamp is invalid.") from error


def _validate_intake_audit_stream(audits, sources, revisions, expected):
    for event in audits:
        if event["entity_type"] == "intake_source" and event["action"] == "evidence_read":
            if event["entity_id"] not in sources:
                raise MigrationSchemaError("INGEST-001 evidence read source is invalid.")
            before, after = _snapshots(event)
            revision = None if not isinstance(after, dict) else revisions.get(after.get("revision"))
            if (
                before is not None
                or not isinstance(after, dict)
                or set(after) != {"sourceId", "revision"}
                or after["sourceId"] != event["entity_id"]
                or revision is None
                or revision["source_id"] != event["entity_id"]
            ):
                raise MigrationSchemaError("INGEST-001 evidence read audit is invalid.")
        elif (
            event["entity_type"]
            in {"intake_source", "intake_evidence_revision", "intake_source_duplicate_candidate"}
            and _audit_key(event) not in expected
        ):
            raise MigrationSchemaError(
                "INGEST-001 audit event has no retained lifecycle consequence."
            )


def _validate_lifecycle_consequences(sources, operations, audits):
    state = {}
    for operation in sorted(
        operations, key=lambda row: (_parsed_timestamp(row["created_at"]), row["id"])
    ):
        source_id = operation["source_id"]
        related = [
            event for event in audits if event["correlation_id"] == operation["correlation_id"]
        ]
        kind = operation["operation_type"]
        if kind == "admit":
            if _audit(related, "intake_source", source_id, "admitted"):
                if source_id in state:
                    raise MigrationSchemaError("INGEST-001 source was admitted more than once.")
                state[source_id] = {
                    "revision": 1,
                    "evidence": operation["result_revision_id"],
                    "updated_at": operation["created_at"],
                    "technical": "ready",
                    "attention": "unprocessed",
                    "failure": None,
                }
            elif source_id not in state:
                raise MigrationSchemaError("INGEST-001 admission replay precedes admission.")
        elif kind == "supersede":
            predecessor = sources[source_id]["supersedes_source_id"]
            if (
                source_id in state
                or predecessor not in state
                or state[predecessor]["technical"] != "ready"
            ):
                raise MigrationSchemaError("INGEST-001 supersession lifecycle is invalid.")
            state[source_id] = {"technical": "ready", "attention": "unprocessed", "failure": None}
            state[source_id]["revision"] = 1
            state[source_id]["evidence"] = operation["result_revision_id"]
            state[source_id]["updated_at"] = operation["created_at"]
            payload = json.loads(operation["request_payload_json"])
            if (
                payload["expectedSourceRevision"] != state[predecessor]["revision"]
                or payload["expectedEvidenceRevisionId"] != state[predecessor]["evidence"]
            ):
                raise MigrationSchemaError("INGEST-001 supersession revision is invalid.")
            state[predecessor]["revision"] += 1
            state[predecessor]["updated_at"] = operation["created_at"]
            state[predecessor]["technical"] = "superseded"
        elif kind == "correct":
            if source_id not in state or state[source_id]["technical"] == "superseded":
                raise MigrationSchemaError("INGEST-001 correction lifecycle is invalid.")
            payload = json.loads(operation["request_payload_json"])
            if (
                payload["expectedSourceRevision"] != state[source_id]["revision"]
                or payload["expectedEvidenceRevisionId"] != state[source_id]["evidence"]
            ):
                raise MigrationSchemaError("INGEST-001 correction revision is invalid.")
            state[source_id]["revision"] += 1
            state[source_id]["evidence"] = operation["result_revision_id"]
            state[source_id]["updated_at"] = operation["created_at"]
        elif kind == "attention_transition":
            current = state.get(source_id)
            before, after = _snapshots(
                _require_audit(related, "intake_source", source_id, "attention_changed")
            )
            if (
                current is None
                or current["technical"] != "ready"
                or before["attentionStatus"] != current["attention"]
            ):
                raise MigrationSchemaError("INGEST-001 attention lifecycle is invalid.")
            current["attention"] = after["attentionStatus"]
            payload = json.loads(operation["request_payload_json"])
            if (
                payload["expectedSourceRevision"] != current["revision"]
                or payload["expectedRevision"] != current["evidence"]
            ):
                raise MigrationSchemaError("INGEST-001 attention revision is invalid.")
            current["revision"] += 1
            current["updated_at"] = operation["created_at"]
        elif kind in {"integrity_failed", "integrity_restored"}:
            current = state.get(source_id)
            before, after = _snapshots(_require_audit(related, "intake_source", source_id, kind))
            expected_before, expected_after = (
                ("ready", "failed") if kind == "integrity_failed" else ("failed", "ready")
            )
            if (
                current is None
                or current["technical"] != expected_before
                or before["technicalStatus"] != expected_before
                or after["technicalStatus"] != expected_after
            ):
                raise MigrationSchemaError("INGEST-001 integrity lifecycle is invalid.")
            current["technical"] = expected_after
            current["failure"] = after["failureCode"]
            current["revision"] += 1
            current["updated_at"] = operation["created_at"]
        if kind not in {"integrity_failed", "integrity_restored"}:
            result = json.loads(operation["result_json"])
            if result["sourceRevision"] != state[source_id]["revision"]:
                raise MigrationSchemaError("INGEST-001 operation result revision is invalid.")
            current = state[source_id]
            if (
                result["revision"],
                result["technicalStatus"],
                result["attentionStatus"],
                result["failureCode"],
                result["updatedAt"],
            ) != (
                current["evidence"],
                current["technical"],
                current["attention"],
                current["failure"],
                current["updated_at"],
            ):
                raise MigrationSchemaError(
                    "INGEST-001 command receipt contradicts its resulting state."
                )
    if set(state) != set(sources):
        raise MigrationSchemaError("INGEST-001 source admission lifecycle is incomplete.")
    for source_id, source in sources.items():
        current = state[source_id]
        if current["revision"] != source["source_revision"]:
            raise MigrationSchemaError(
                "INGEST-001 retained source revision contradicts operations."
            )
        if (current["evidence"], current["updated_at"]) != (
            source["current_revision_id"],
            source["updated_at"],
        ):
            raise MigrationSchemaError("INGEST-001 retained source state contradicts operations.")
        if (current["technical"], current["attention"], current["failure"]) != (
            source["technical_status"],
            source["attention_status"],
            source["failure_code"],
        ):
            raise MigrationSchemaError(
                "INGEST-001 retained source lifecycle contradicts operations."
            )


def _parsed_timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise MigrationSchemaError("INGEST-001 timestamp is invalid.") from error


def _sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _uuid(value):
    try:
        UUID(str(value))
    except (ValueError, TypeError) as error:
        raise MigrationSchemaError("INGEST-001 identifier is invalid.") from error


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise MigrationSchemaError("INGEST-001 timestamp is invalid.") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise MigrationSchemaError("INGEST-001 timestamp is not UTC.")

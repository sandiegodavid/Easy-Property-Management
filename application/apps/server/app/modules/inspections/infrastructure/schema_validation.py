"""Exact current INSP-001 schema validation."""

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import inspect, select, text
from sqlalchemy.dialects import sqlite

from app.modules.inspections.infrastructure.sqlalchemy_models import (
    ConditionAcknowledgmentModel,
    ConditionAreaModel,
    ConditionChecklistTemplateItemModel,
    ConditionChecklistTemplateModel,
    ConditionComparisonModel,
    ConditionObservationModel,
    ConditionReportModel,
)
from app.platform.migration_errors import MigrationSchemaError
from app.modules.inspections.application.commands import (
    canonical_json,
    fingerprint,
    validate_command,
)
from app.modules.inspections.infrastructure.command_models import (
    InspectionCommandOperationModel,
    INSPECTION_COMMAND_TRIGGERS,
)

MODELS = (
    ConditionReportModel,
    ConditionAreaModel,
    ConditionObservationModel,
    ConditionAcknowledgmentModel,
    ConditionComparisonModel,
    ConditionChecklistTemplateModel,
    ConditionChecklistTemplateItemModel,
    InspectionCommandOperationModel,
)


def _sql(value):
    return " ".join(
        str(value)
        .replace('"', "")
        .replace("'", "'")
        .replace("condition_reports.", "")
        .replace("condition_comparisons.", "")
        .split()
    ).casefold()


def _index_where(value):
    if value is None or isinstance(value, str) and value == "":
        return ""
    return (
        _sql(value.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        if hasattr(value, "compile")
        else _sql(value)
    )


def validate_inspection_schema(connection) -> None:
    inspector = inspect(connection)
    for model in MODELS:
        table = model.__table__
        if not inspector.has_table(table.name):
            raise MigrationSchemaError(f"{table.name} is missing for INSP-001.")
        actual = {item["name"]: item for item in inspector.get_columns(table.name)}
        expected = {item.name: item for item in table.columns}
        if set(actual) != set(expected):
            raise MigrationSchemaError(f"{table.name} columns are incompatible with INSP-001.")
        for name, column in expected.items():
            if str(actual[name]["type"]).upper() != str(column.type).upper() or bool(
                actual[name]["nullable"]
            ) != bool(column.nullable):
                raise MigrationSchemaError(f"{table.name}.{name} is incompatible with INSP-001.")
        if {item["name"] for item in inspector.get_columns(table.name) if item["primary_key"]} != {
            item.name for item in table.primary_key.columns
        }:
            raise MigrationSchemaError(f"{table.name} primary key is incompatible with INSP-001.")
        actual_fks = {
            (item["constrained_columns"][0], item["referred_table"], item["referred_columns"][0])
            for item in inspector.get_foreign_keys(table.name)
        }
        expected_fks = {
            (fk.parent.name, fk.column.table.name, fk.column.name)
            for column in table.columns
            for fk in column.foreign_keys
        }
        if actual_fks != expected_fks:
            raise MigrationSchemaError(f"{table.name} foreign keys are incompatible with INSP-001.")
        actual_indexes = {
            (
                item["name"],
                tuple(item["column_names"]),
                bool(item["unique"]),
                _index_where(item.get("dialect_options", {}).get("sqlite_where", "")),
            )
            for item in inspector.get_indexes(table.name)
        }
        expected_indexes = {
            (
                item.name,
                tuple(column.name for column in item.columns),
                bool(item.unique),
                _index_where(item.dialect_options["sqlite"].get("where", "")),
            )
            for item in table.indexes
        }
        if actual_indexes != expected_indexes:
            raise MigrationSchemaError(f"{table.name} indexes are incompatible with INSP-001.")
        actual_checks = {
            _sql(item["sqltext"]) for item in inspector.get_check_constraints(table.name)
        }
        expected_checks = {
            _sql(item.sqltext)
            for item in table.constraints
            if item.__class__.__name__ == "CheckConstraint"
        }
        if actual_checks != expected_checks:
            raise MigrationSchemaError(f"{table.name} constraints are incompatible with INSP-001.")
        actual_unique = {
            tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)
        }
        expected_unique = {
            tuple(item.columns.keys())
            for item in table.constraints
            if item.__class__.__name__ == "UniqueConstraint"
        }
        expected_unique |= {(column.name,) for column in table.columns if column.unique}
        if actual_unique != expected_unique:
            raise MigrationSchemaError(
                f"{table.name} unique constraints are incompatible with INSP-001."
            )
    validate_inspection_commands(connection)


def validate_inspection_commands(connection):
    table = InspectionCommandOperationModel.__table__
    triggers = dict(
        connection.execute(
            text(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='inspection_command_operations'"
            )
        ).all()
    )
    if {name: _sql(sql) for name, sql in triggers.items()} != {
        name: _sql(sql) for name, sql in INSPECTION_COMMAND_TRIGGERS.items()
    }:
        raise MigrationSchemaError("Inspection command immutability triggers are incompatible.")
    if any(column["default"] is not None for column in inspect(connection).get_columns(table.name)):
        raise MigrationSchemaError("Inspection command defaults are incompatible.")
    revisions = {}
    correlations = set()
    created_reports, created_templates = set(), set()
    for row in connection.execute(select(table).order_by(table.c.revision)).mappings():
        try:
            for value in (
                row["id"],
                row["idempotency_key"],
                row["correlation_id"],
                row["lease_id"] or row["template_id"],
            ):
                if str(UUID(value)) != value:
                    raise ValueError("Invalid identity")
            instant = datetime.fromisoformat(row["created_at"])
            if instant.tzinfo is None or instant.utcoffset() != UTC.utcoffset(instant):
                raise ValueError("Non-UTC receipt")
            request, result = json.loads(row["request_json"]), json.loads(row["result_json"])
            if set(request) != {
                "targetKind",
                "targetId",
                "expectedRevision",
                "payload",
            } or not isinstance(request["payload"], dict):
                raise ValueError("Malformed request")
            targets = {
                "report.create": "lease",
                "report.patch": "report",
                "report.areas": "report",
                "report.acknowledge": "report",
                "report.finalize": "report",
                "comparison.review": "lease",
                "evidence.attach": "observation",
                "template.create": "template",
                "template.patch": "template",
            }
            if request["targetKind"] != targets[row["action"]]:
                raise ValueError("Command target mismatch")
            if row["action"] == "template.create":
                if request["targetId"] is not None:
                    raise ValueError("Template creation must not target an existing template")
            elif str(UUID(request["targetId"])) != request["targetId"]:
                raise ValueError("Invalid command target")
            validate_command(request["expectedRevision"], row["idempotency_key"])
            if (
                canonical_json(request) != row["request_json"]
                or canonical_json(result) != row["result_json"]
                or fingerprint(row["action"], request) != row["request_fingerprint"]
            ):
                raise ValueError("Rewritten command")
            scope = (row["lease_id"], row["template_id"])
            if (
                row["revision"] != revisions.get(scope, 0) + 1
                or request["expectedRevision"] != row["revision"] - 1
            ):
                raise ValueError("Broken revision history")
            revisions[scope] = row["revision"]
            if (
                result["revision"] != row["revision"]
                or result["operationId"] != row["id"]
                or row["correlation_id"] in correlations
            ):
                raise ValueError("Invalid original result")
            correlations.add(row["correlation_id"])
            required_events = []
            if row["action"].startswith("report."):
                if result["leaseId"] != row["lease_id"] or (
                    row["action"] != "report.create" and result["id"] != request["targetId"]
                ):
                    raise ValueError("Report result scope mismatch")
                if row["action"] == "report.create":
                    created_reports.add(result["id"])
                    required_events.append(("condition_report", result["id"], "created"))
                elif row["action"] == "report.finalize":
                    if result["status"] != "finalized":
                        raise ValueError("Invalid finalization result")
                    required_events.append(("condition_report", result["id"], "finalized"))
                    if result["supersedesReportId"] is not None:
                        required_events.append(
                            ("condition_report", result["supersedesReportId"], "superseded")
                        )
            elif row["action"].startswith("template."):
                if result["id"] != row["template_id"]:
                    raise ValueError("Template result scope mismatch")
                if row["action"] == "template.create":
                    created_templates.add(result["id"])
                    required_events.append(
                        ("condition_checklist_template", result["id"], "created")
                    )
                else:
                    required_events.append(
                        ("condition_checklist_template", result["id"], "updated")
                    )
            elif row["action"] == "evidence.attach":
                if (
                    len(result["links"]) != 1
                    or result["links"][0]["entityId"] != request["targetId"]
                    or result["contentSha256"] != request["payload"]["content_sha256"]
                ):
                    raise ValueError("Invalid evidence result")
                required_events.extend(
                    (
                        ("file", result["id"], "created"),
                        ("file_link", result["links"][0]["id"], "created"),
                        ("condition_observation", request["targetId"], "evidence_attached"),
                    )
                )
            elif row["action"] == "comparison.review":
                for comparison in result["comparisons"]:
                    if comparison["leaseId"] != row["lease_id"]:
                        raise ValueError("Comparison scope mismatch")
                    required_events.append(("condition_comparison", comparison["id"], "classified"))
            for entity_type, entity_id, action in required_events:
                evidence = connection.execute(
                    text(
                        "SELECT correlation_id FROM audit_events WHERE entity_type=:type AND entity_id=:id AND action=:action AND correlation_id=:correlation"
                    ),
                    {
                        "type": entity_type,
                        "id": entity_id,
                        "action": action,
                        "correlation": row["correlation_id"],
                    },
                ).all()
                if len(evidence) != 1:
                    raise ValueError("Missing correlated inspection mutation audit")
            events = (
                connection.execute(
                    text(
                        "SELECT action,correlation_id,before_snapshot,after_snapshot FROM audit_events WHERE entity_type='inspection_command_operation' AND entity_id=:id"
                    ),
                    {"id": row["id"]},
                )
                .mappings()
                .all()
            )
            if (
                len(events) != 1
                or events[0]["action"] != "recorded"
                or events[0]["correlation_id"] != row["correlation_id"]
                or events[0]["before_snapshot"] is not None
                or json.loads(events[0]["after_snapshot"]) != dict(row)
            ):
                raise ValueError("Missing or rewritten command audit")
        except (ValueError, TypeError, KeyError) as error:
            raise MigrationSchemaError("Retained Inspection command history is invalid.") from error
    if (
        set(connection.execute(select(ConditionReportModel.id)).scalars()) != created_reports
        or set(connection.execute(select(ConditionChecklistTemplateModel.id)).scalars())
        != created_templates
    ):
        raise MigrationSchemaError("Inspection records lack their original creation receipt.")

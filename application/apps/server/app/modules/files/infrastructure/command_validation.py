"""Exact-schema and retained immutable Files command history."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, inspect, select, text

from app.modules.files.application.commands import (
    FileCommandReceipt,
    command_fingerprint,
    command_json,
)
from app.modules.files.application.errors import FileError, normalize_filename, normalize_media_type
from app.modules.files.infrastructure.command_triggers import FILE_COMMAND_TRIGGERS
from app.modules.files.infrastructure.sqlalchemy_models import (
    FileCommandOperationModel,
    FileLinkModel,
    FileRecordModel,
)
from app.platform.migration_errors import MigrationSchemaError


def _sql(value):
    return " ".join(str(value).replace('"', "").split()).casefold()


def validate_file_commands(connection):
    table = FileCommandOperationModel.__table__
    inspector = inspect(connection)
    columns = inspector.get_columns(table.name)
    if {
        (c["name"], str(c["type"]).upper(), c["nullable"], bool(c["primary_key"])) for c in columns
    } != {(c.name, str(c.type).upper(), c.nullable, c.primary_key) for c in table.columns}:
        raise MigrationSchemaError("Files command columns are incompatible.")
    if any(c["default"] is not None for c in columns):
        raise MigrationSchemaError("Files command defaults are incompatible.")
    if {
        (tuple(c["constrained_columns"]), c["referred_table"], tuple(c["referred_columns"]))
        for c in inspector.get_foreign_keys(table.name)
    } != {
        ((fk.parent.name,), fk.column.table.name, (fk.column.name,)) for fk in table.foreign_keys
    }:
        raise MigrationSchemaError("Files command foreign keys are incompatible.")
    if {
        (c["name"], tuple(c["column_names"]), bool(c["unique"]))
        for c in inspector.get_indexes(table.name)
    } != {
        (i.name, tuple(c.name for c in i.columns), bool(i.unique)) for i in table.indexes
    } or inspector.get_unique_constraints(table.name):
        raise MigrationSchemaError("Files command indexes are incompatible.")
    if any(
        c.get("dialect_options", {}).get("sqlite_where") is not None
        for c in inspector.get_indexes(table.name)
    ):
        raise MigrationSchemaError("Files command key uniqueness must be unconditional.")
    if {_sql(c["sqltext"]) for c in inspector.get_check_constraints(table.name)} != {
        _sql(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)
    }:
        raise MigrationSchemaError("Files command checks are incompatible.")
    actual_triggers = dict(
        connection.execute(
            text(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='file_command_operations'"
            )
        ).all()
    )
    if {k: _sql(v) for k, v in actual_triggers.items()} != {
        k: _sql(v) for k, v in FILE_COMMAND_TRIGGERS.items()
    }:
        raise MigrationSchemaError("Files command append-only triggers are incompatible.")
    for row in connection.execute(select(table)).mappings():
        try:
            _validate_receipt(connection, FileCommandReceipt(**row))
        except (ValueError, TypeError, KeyError, FileError) as error:
            raise MigrationSchemaError("A retained Files command is invalid.") from error


def _validate_receipt(connection, receipt):
    for value in (
        receipt.id,
        receipt.idempotency_key,
        receipt.file_id,
        receipt.link_id,
        receipt.correlation_id,
    ):
        if str(UUID(value)) != value:
            raise ValueError("Noncanonical command identity")
    if not re.fullmatch(r"[0-9a-f]{64}", receipt.request_fingerprint):
        raise ValueError("Invalid fingerprint")
    instant = datetime.fromisoformat(receipt.created_at)
    if (
        instant.tzinfo is None
        or instant.utcoffset() != UTC.utcoffset(instant)
        or not receipt.created_at.endswith(("+00:00", "Z"))
    ):
        raise ValueError("Command timestamp must be UTC")
    request, result = json.loads(receipt.request_json), receipt.result()
    if command_json(request) != receipt.request_json or command_json(result) != receipt.result_json:
        raise ValueError("Noncanonical command JSON")
    if (
        command_fingerprint(receipt.action, request) != receipt.request_fingerprint
        or result["operationId"] != receipt.id
    ):
        raise ValueError("Rewritten command identity")
    link = (
        connection.execute(
            select(FileLinkModel.__table__).where(FileLinkModel.id == receipt.link_id)
        )
        .mappings()
        .one()
    )
    record = (
        connection.execute(
            select(FileRecordModel.__table__).where(FileRecordModel.id == receipt.file_id)
        )
        .mappings()
        .one()
    )
    if link["file_id"] != record["id"]:
        raise ValueError("Command association mismatch")
    if receipt.action == "upload":
        if set(request) != {
            "originalName",
            "mediaType",
            "contentSha256",
            "entityType",
            "entityId",
            "purpose",
        }:
            raise ValueError("Invalid upload command")
        if (
            normalize_filename(request["originalName"]) != request["originalName"]
            or normalize_media_type(request["mediaType"]) != request["mediaType"]
        ):
            raise ValueError("Invalid normalized metadata")
        expected = {
            "id": record["id"],
            "originalName": record["original_name"],
            "mediaType": record["media_type"],
            "contentSha256": record["content_sha256"],
            "sizeBytes": record["size_bytes"],
            "createdAt": record["created_at"],
        }
        if (
            type(result["sizeBytes"]) is not int
            or any(result.get(k) != v for k, v in expected.items())
            or any(
                request[k] != expected[k] for k in ("originalName", "mediaType", "contentSha256")
            )
        ):
            raise ValueError("Rewritten upload result")
        if (
            result["storageState"] != "available"
            or result["verifiedAt"] != record["created_at"]
            or result["storageProvider"] not in {"local", "s3"}
        ):
            raise ValueError("Invalid original publication state")
        if set(result) != set(expected) | {
            "storageProvider",
            "storageState",
            "verifiedAt",
            "links",
            "operationId",
        }:
            raise ValueError("Unexpected upload result fields")
        expected_link = _link_result(link, archived=False)
        if (
            not isinstance(result["links"], list)
            or len(result["links"]) != 1
            or type(result["links"][0].get("revision")) is not int
            or result["links"] != [expected_link]
            or any(request[k] != expected_link[k] for k in ("entityType", "entityId", "purpose"))
        ):
            raise ValueError("Rewritten upload link")
        _audit(connection, "file", record["id"], "created", receipt, expected)
        _audit(
            connection,
            "file_link",
            link["id"],
            "created",
            receipt,
            {k: v for k, v in expected_link.items() if k not in {"id", "revision"}},
        )
    elif receipt.action == "archive_link":
        if (
            set(request) != {"linkId", "expectedRevision", "confirmed", "reason"}
            or request["expectedRevision"] != 1
            or type(request["expectedRevision"]) is not int
            or request["confirmed"] is not True
            or request["linkId"] != link["id"]
        ):
            raise ValueError("Invalid archive command")
        expected_link = _link_result(link, archived=True)
        if (
            link["archived_at"] is None
            or type(result["revision"]) is not int
            or request["reason"] != link["archive_reason"]
            or result
            != expected_link | {"updatedAt": link["archived_at"], "operationId": receipt.id}
        ):
            raise ValueError("Rewritten archive result")
        _audit(
            connection,
            "file_link",
            link["id"],
            "archived",
            receipt,
            {k: v for k, v in expected_link.items() if k not in {"id", "revision"}},
            before={
                k: v
                for k, v in _link_result(link, archived=False).items()
                if k not in {"id", "revision"}
            },
        )
    else:
        raise ValueError("Unknown command")
    _audit(connection, "file_command_operation", receipt.id, "recorded", receipt, asdict(receipt))


def _link_result(link, *, archived):
    return {
        "id": link["id"],
        "fileId": link["file_id"],
        "entityType": link["entity_type"],
        "entityId": link["entity_id"],
        "purpose": link["purpose"],
        "createdAt": link["created_at"],
        "archivedAt": link["archived_at"] if archived else None,
        "archiveReason": link["archive_reason"] if archived else None,
        "revision": 2 if archived else 1,
    }


def _audit(connection, entity_type, entity_id, action, receipt, expected, before=None):
    rows = (
        connection.execute(
            text(
                "SELECT action,correlation_id,before_snapshot,after_snapshot,actor_kind FROM audit_events WHERE entity_type=:kind AND entity_id=:id AND action=:action"
            ),
            {"kind": entity_type, "id": entity_id, "action": action},
        )
        .mappings()
        .all()
    )
    if len(rows) != 1 or rows[0]["correlation_id"] != receipt.correlation_id:
        raise ValueError("Missing correlated command audit")
    after = json.loads(rows[0]["after_snapshot"])
    actual_before = json.loads(rows[0]["before_snapshot"]) if rows[0]["before_snapshot"] else None
    if actual_before != before or rows[0]["actor_kind"] != "local_operator":
        raise ValueError("Invalid command audit before-state or actor")
    if any(after.get(k) != v for k, v in expected.items()):
        raise ValueError("Rewritten command audit")

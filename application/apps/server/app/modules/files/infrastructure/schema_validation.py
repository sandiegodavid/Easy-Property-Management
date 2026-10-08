"""Current-format and retained-data validation owned by FILE-001."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Mapping

from sqlalchemy import inspect, text

from app.modules.files.application.errors import normalize_filename, normalize_media_type
from app.modules.files.application.ports import FileLink
from app.platform.migration_errors import MigrationSchemaError
from app.modules.files.infrastructure.command_validation import validate_file_commands


def validate_file_schema(connection) -> None:
    validate_file_commands(connection)
    inspector = inspect(connection)
    expected = {
        "file_records": {
            "id",
            "original_name",
            "media_type",
            "size_bytes",
            "content_sha256",
            "created_at",
        },
        "file_links": {
            "id",
            "file_id",
            "entity_type",
            "entity_id",
            "purpose",
            "created_at",
            "archived_at",
            "archive_reason",
        },
        "file_content_locations": {
            "file_id",
            "storage_provider",
            "storage_state",
            "local_relative_path",
            "s3_bucket",
            "s3_object_key",
            "s3_version_id",
            "provider_etag",
            "verified_at",
        },
        "file_publication_cleanup_attentions": {
            "publication_id",
            "provider",
            "opened_at",
            "resolved_at",
        },
    }
    all_indexes = []
    for table, columns in expected.items():
        actual_columns = inspector.get_columns(table)
        if (
            table not in inspector.get_table_names()
            or {item["name"] for item in actual_columns} != columns
        ):
            raise MigrationSchemaError(f"{table} has an incompatible shape.")
        expected_pk = (
            {"file_id"}
            if table == "file_content_locations"
            else ({"publication_id"} if table == "file_publication_cleanup_attentions" else {"id"})
        )
        if {item["name"] for item in actual_columns if item["primary_key"]} != expected_pk:
            raise MigrationSchemaError(f"{table} has an incompatible primary key.")
        for column in actual_columns:
            expected_integer = table == "file_records" and column["name"] == "size_bytes"
            actual_type = str(column["type"]).upper()
            if (expected_integer and "INT" not in actual_type) or (
                not expected_integer and not ("TEXT" in actual_type or "CHAR" in actual_type)
            ):
                raise MigrationSchemaError(f"{table} has incompatible column types.")
            nullable = (
                (
                    table == "file_content_locations"
                    and column["name"]
                    in {
                        "local_relative_path",
                        "s3_bucket",
                        "s3_object_key",
                        "s3_version_id",
                        "provider_etag",
                    }
                )
                or (table == "file_links" and column["name"] in {"archived_at", "archive_reason"})
                or (
                    table == "file_publication_cleanup_attentions"
                    and column["name"] == "resolved_at"
                )
            )
            if bool(column["nullable"]) != nullable and not column["primary_key"]:
                raise MigrationSchemaError(f"{table} has incompatible nullability.")
        all_indexes.extend(inspector.get_indexes(table))
    indexes = {item["name"]: tuple(item["column_names"]) for item in all_indexes}
    active_link_index = next(
        (item for item in all_indexes if item["name"] == "file_links_one_active_association"), None
    )
    active_link_where = (
        str((active_link_index or {}).get("dialect_options", {}).get("sqlite_where", ""))
        .lower()
        .replace(" ", "")
    )
    if (
        indexes.get("file_records_content") != ("content_sha256",)
        or indexes.get("file_links_entity") != ("entity_type", "entity_id")
        or indexes.get("file_content_locations_provider")
        != ("storage_provider", "local_relative_path", "s3_bucket", "s3_object_key")
        or indexes.get("file_links_one_active_association")
        != ("file_id", "entity_type", "entity_id", "purpose")
        or not (
            active_link_index
            and active_link_index.get("unique")
            and active_link_where == "archived_atisnull"
        )
    ):
        raise MigrationSchemaError("FILE-001 indexes are incompatible.")
    if any(
        item.get("unique") and item["name"] != "file_links_one_active_association"
        for item in all_indexes
    ) or any(inspector.get_unique_constraints(table) for table in expected):
        raise MigrationSchemaError("FILE-001 uniqueness is incompatible.")
    foreign_keys = inspector.get_foreign_keys("file_links")
    if not any(
        key["constrained_columns"] == ["file_id"] and key["referred_table"] == "file_records"
        for key in foreign_keys
    ):
        raise MigrationSchemaError("file_links foreign key is missing.")
    location_foreign_keys = inspector.get_foreign_keys("file_content_locations")
    if not any(
        key["constrained_columns"] == ["file_id"] and key["referred_table"] == "file_records"
        for key in location_foreign_keys
    ):
        raise MigrationSchemaError("file content location foreign key is missing.")
    checks = {
        "".join((item.get("sqltext") or "").lower().replace("(", "").replace(")", "").split())
        for item in inspector.get_check_constraints("file_records")
    }
    if checks != {"size_bytes>=0"}:
        raise MigrationSchemaError("file_records constraints are incompatible.")
    link_checks = {
        "".join((item.get("sqltext") or "").lower().replace("(", "").replace(")", "").split())
        for item in inspector.get_check_constraints("file_links")
    }
    if link_checks != {
        "archived_atisnullandarchive_reasonisnullorarchived_atisnotnullandarchive_reasonisnotnullandlengthtrimarchive_reasonbetween1and1000"
    }:
        raise MigrationSchemaError("file_links constraints are incompatible.")
    location_checks = {
        "".join((item.get("sqltext") or "").lower().replace("(", "").replace(")", "").split())
        for item in inspector.get_check_constraints("file_content_locations")
    }
    if location_checks != {
        "storage_providerin'local','s3'",
        "storage_statein'available','missing','quarantined'",
        "storage_provider='local'andlocal_relative_pathisnotnullands3_bucketisnullands3_object_keyisnullands3_version_idisnullorstorage_provider='s3'andlocal_relative_pathisnullands3_bucketisnotnullands3_object_keyisnotnullands3_version_idisnotnull",
    }:
        raise MigrationSchemaError("file content location constraints are incompatible.")


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def validate_file_data(connection, policy_registry: Mapping[str, object]) -> None:
    """Validate persisted FILE-001 facts without reapplying create quotas.

    A create validator sees the prospective association and may count active
    links.  Retained validation instead delegates to an optional owning policy
    hook so restored data is checked as historical state, not as a new write.
    """
    rows = (
        connection.execute(
            text(
                "SELECT r.id, r.original_name, r.media_type, r.size_bytes, r.content_sha256, r.created_at, "
                "l.storage_provider, l.storage_state, l.local_relative_path, l.s3_bucket, l.s3_object_key, l.s3_version_id, l.verified_at "
                "FROM file_records r LEFT JOIN file_content_locations l ON l.file_id=r.id"
            )
        )
        .mappings()
        .all()
    )
    if len(rows) != connection.execute(text("SELECT count(*) FROM file_records")).scalar_one():
        raise MigrationSchemaError("Every file record must have exactly one content location.")
    for row in rows:
        _uuid(row["id"], "file ID")
        if normalize_filename(row["original_name"]) != row["original_name"]:
            raise MigrationSchemaError("A retained file has a non-normalized display name.")
        if normalize_media_type(row["media_type"]) != row["media_type"]:
            raise MigrationSchemaError("A retained file has a non-normalized media type.")
        if (
            type(row["size_bytes"]) is not int
            or row["size_bytes"] < 0
            or not _SHA256.fullmatch(row["content_sha256"])
        ):
            raise MigrationSchemaError("A retained file has invalid immutable content metadata.")
        _utc(row["created_at"], "file created_at")
        _utc(row["verified_at"], "file verified_at")
        provider, state = row["storage_provider"], row["storage_state"]
        if provider not in {"local", "s3"} or state not in {"available", "missing", "quarantined"}:
            raise MigrationSchemaError("A retained file has unsupported storage state.")
        if provider == "local":
            if row["local_relative_path"] != f"managed/{row['content_sha256']}" or any(
                row[key] is not None for key in ("s3_bucket", "s3_object_key", "s3_version_id")
            ):
                raise MigrationSchemaError("A retained local file has an invalid location.")
        elif (
            not all(
                isinstance(row[key], str) and row[key]
                for key in ("s3_bucket", "s3_object_key", "s3_version_id")
            )
            or row["local_relative_path"] is not None
        ):
            raise MigrationSchemaError("A retained S3 file has an invalid exact-version location.")
    link_rows = (
        connection.execute(
            text(
                "SELECT id,file_id,entity_type,entity_id,purpose,created_at,archived_at,archive_reason FROM file_links"
            )
        )
        .mappings()
        .all()
    )
    links_by_file: dict[str, int] = {}
    seen_active: set[tuple[str, str, str, str]] = set()
    for row in link_rows:
        _uuid(row["id"], "file link ID")
        _uuid(row["file_id"], "file link file ID")
        if not all(
            isinstance(row[key], str) and row[key].strip()
            for key in ("entity_type", "entity_id", "purpose")
        ):
            raise MigrationSchemaError("A retained file link has missing association fields.")
        _utc(row["created_at"], "file link created_at")
        if (row["archived_at"] is None) != (row["archive_reason"] is None):
            raise MigrationSchemaError("A retained file link has invalid archive fields.")
        if row["archived_at"] is not None:
            _utc(row["archived_at"], "file link archived_at")
            if not isinstance(row["archive_reason"], str) or not (
                1 <= len(row["archive_reason"].strip()) <= 1000
            ):
                raise MigrationSchemaError("A retained file link has invalid archive reason.")
        else:
            association = (row["file_id"], row["entity_type"], row["entity_id"], row["purpose"])
            if association in seen_active:
                raise MigrationSchemaError("A retained file has duplicate active associations.")
            seen_active.add(association)
        links_by_file[row["file_id"]] = links_by_file.get(row["file_id"], 0) + 1
        policy = policy_registry.get(row["entity_type"])
        if policy is None:
            raise MigrationSchemaError(
                f"A retained file link has unsupported entity type {row['entity_type']}."
            )
        retained = getattr(policy, "validate_retained", None)
        if retained is None:
            raise MigrationSchemaError(
                f"File-link policy {row['entity_type']} has no retained-data validator."
            )
        try:
            retained(connection, FileLink(**dict(row)))
        except Exception as error:
            raise MigrationSchemaError(
                f"A retained {row['entity_type']} file link is invalid: {error}"
            ) from error
    missing = {row["id"] for row in rows} - set(links_by_file)
    if missing:
        raise MigrationSchemaError("Every committed file must retain at least one file link.")
    for row in connection.execute(
        text(
            "SELECT publication_id,provider,opened_at,resolved_at FROM file_publication_cleanup_attentions"
        )
    ).mappings():
        if (
            not isinstance(row["publication_id"], str)
            or not row["publication_id"].strip()
            or row["provider"] not in {"local", "s3"}
        ):
            raise MigrationSchemaError("A retained file cleanup attention is invalid.")
        _utc(row["opened_at"], "cleanup attention opened_at")
        if row["resolved_at"] is not None:
            _utc(row["resolved_at"], "cleanup attention resolved_at")


def _uuid(value: object, label: str) -> None:
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise MigrationSchemaError(f"A retained {label} is not a UUID.")


def _utc(value: object, label: str) -> None:
    if not isinstance(value, str):
        raise MigrationSchemaError(f"A retained {label} is not a timestamp.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise MigrationSchemaError(f"A retained {label} is invalid.") from error
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != UTC.utcoffset(parsed)
        or not (value.endswith("+00:00") or value.endswith("Z"))
    ):
        raise MigrationSchemaError(f"A retained {label} must be UTC.")

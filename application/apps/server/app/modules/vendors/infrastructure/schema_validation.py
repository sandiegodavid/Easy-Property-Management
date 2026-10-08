"""Exact current provider schema and retained data validation."""

import unicodedata
import json
import re
from datetime import datetime
from uuid import UUID

from sqlalchemy import inspect

from app.modules.vendors.domain.category_normalization import normalize_provider_category_name
from app.modules.vendors.domain.category_seeds import PROVIDER_CATEGORY_SEEDS, fingerprint
from app.platform.migration_errors import MigrationSchemaError


def validate_vendor_schema(connection) -> None:
    inspector = inspect(connection)
    expected = {
        "provider_profiles": (
            {
                "party_id",
                "selection_status",
                "revision",
                "selection_reason",
                "notes",
                "created_at",
                "updated_at",
                "archived_at",
            },
            {"selection_reason", "notes", "archived_at"},
            {"party_id"},
        ),
        "provider_categories": (
            {
                "revision",
                "id",
                "display_name",
                "normalized_name",
                "description",
                "display_order",
                "created_at",
                "updated_at",
                "archived_at",
                "archive_reason",
                "create_idempotency_key",
                "create_request_fingerprint",
            },
            {"description", "archived_at", "archive_reason"},
            {"id"},
        ),
        "provider_category_assignments": (
            {
                "id",
                "provider_party_id",
                "category_id",
                "created_at",
                "updated_at",
                "archived_at",
                "archive_reason",
                "create_idempotency_key",
                "create_request_fingerprint",
            },
            {"archived_at", "archive_reason"},
            {"id"},
        ),
        "provider_services": (
            {
                "id",
                "party_id",
                "display_name",
                "normalized_name",
                "created_at",
                "updated_at",
                "archived_at",
            },
            {"archived_at"},
            {"id"},
        ),
        "provider_service_areas": (
            {
                "id",
                "party_id",
                "display_name",
                "normalized_name",
                "country_code",
                "created_at",
                "updated_at",
                "archived_at",
            },
            {"archived_at"},
            {"id"},
        ),
        "provider_work_history": (
            {
                "id",
                "party_id",
                "property_id",
                "performed_on",
                "summary",
                "outcome_notes",
                "created_at",
                "updated_at",
                "archived_at",
            },
            {"property_id", "outcome_notes", "archived_at"},
            {"id"},
        ),
        "provider_references": (
            {
                "id",
                "party_id",
                "reference_name",
                "organization_name",
                "relationship",
                "email",
                "phone",
                "notes",
                "created_at",
                "updated_at",
                "archived_at",
            },
            {
                "reference_name",
                "organization_name",
                "relationship",
                "email",
                "phone",
                "notes",
                "archived_at",
            },
            {"id"},
        ),
        "provider_reputation_links": (
            {
                "id",
                "party_id",
                "source_kind",
                "source_name",
                "normalized_source_key",
                "url",
                "normalized_url",
                "notes",
                "last_checked_on",
                "created_at",
                "updated_at",
                "archived_at",
            },
            {"source_name", "notes", "last_checked_on", "archived_at"},
            {"id"},
        ),
    }
    for table, (names, nullable, primary) in expected.items():
        if not inspector.has_table(table):
            raise MigrationSchemaError("Provider schema is missing.")
        columns = inspector.get_columns(table)
        if {item["name"] for item in columns} != names or {
            item["name"] for item in columns if item["primary_key"]
        } != primary:
            raise MigrationSchemaError("Provider columns are incompatible.")
        for item in columns:
            if not item["primary_key"] and bool(item["nullable"]) != (item["name"] in nullable):
                raise MigrationSchemaError("Provider nullability is incompatible.")
            if (table == "provider_categories" and item["name"] == "display_order") or (
                table in {"provider_profiles", "provider_categories"} and item["name"] == "revision"
            ):
                if "INT" not in str(item["type"]).upper():
                    raise MigrationSchemaError("Provider types are incompatible.")
            elif (
                "TEXT" not in str(item["type"]).upper() and "CHAR" not in str(item["type"]).upper()
            ):
                raise MigrationSchemaError("Provider types are incompatible.")
    required_fks = {
        "provider_profiles": {(("party_id",), "parties", ("id",))},
        "provider_categories": set(),
        "provider_category_assignments": {
            (("provider_party_id",), "provider_profiles", ("party_id",)),
            (("category_id",), "provider_categories", ("id",)),
        },
        "provider_services": {(("party_id",), "provider_profiles", ("party_id",))},
        "provider_service_areas": {(("party_id",), "provider_profiles", ("party_id",))},
        "provider_work_history": {
            (("party_id",), "provider_profiles", ("party_id",)),
            (("property_id",), "properties", ("id",)),
        },
        "provider_references": {(("party_id",), "provider_profiles", ("party_id",))},
        "provider_reputation_links": {(("party_id",), "provider_profiles", ("party_id",))},
    }
    for table, expected_fks in required_fks.items():
        found = {
            (
                tuple(item["constrained_columns"]),
                item["referred_table"],
                tuple(item["referred_columns"]),
            )
            for item in inspector.get_foreign_keys(table)
        }
        if found != expected_fks:
            raise MigrationSchemaError("Provider foreign keys are incompatible.")
    required_indexes = {
        "provider_profiles": {
            "provider_profiles_selection": (("archived_at", "selection_status"), False)
        },
        "provider_categories": {
            "provider_categories_active_order": (
                ("archived_at", "display_order", "normalized_name", "id"),
                False,
            ),
            "provider_categories_one_active_name": (("normalized_name",), True),
        },
        "provider_category_assignments": {
            "provider_category_assignments_provider_status": (
                ("provider_party_id", "archived_at", "category_id"),
                False,
            ),
            "provider_category_assignments_category_status": (
                ("category_id", "archived_at", "provider_party_id"),
                False,
            ),
            "provider_category_assignments_one_active_pair": (
                ("provider_party_id", "category_id"),
                True,
            ),
        },
        "provider_services": {
            "provider_services_party_status": (("party_id", "archived_at"), False),
            "provider_services_one_active_name": (("party_id", "normalized_name"), True),
        },
        "provider_service_areas": {
            "provider_service_areas_party_status": (("party_id", "archived_at"), False),
            "provider_service_areas_one_active_name": (
                ("party_id", "normalized_name", "country_code"),
                True,
            ),
        },
        "provider_work_history": {
            "provider_work_history_party_status": (
                ("party_id", "archived_at", "performed_on"),
                False,
            ),
            "provider_work_history_property": (("property_id", "archived_at"), False),
        },
        "provider_references": {
            "provider_references_party_status": (("party_id", "archived_at"), False)
        },
        "provider_reputation_links": {
            "provider_reputation_links_party_status": (("party_id", "archived_at"), False),
            "provider_reputation_links_one_active_source": (
                ("party_id", "normalized_source_key"),
                True,
            ),
            "provider_reputation_links_one_active_url": (("party_id", "normalized_url"), True),
        },
    }
    for table, required in required_indexes.items():
        found = {
            item["name"]: (tuple(item["column_names"]), bool(item.get("unique")))
            for item in inspector.get_indexes(table)
        }
        if found != required:
            raise MigrationSchemaError("Provider indexes are incompatible.")
    partial_names = {
        "provider_services_one_active_name",
        "provider_service_areas_one_active_name",
        "provider_categories_one_active_name",
        "provider_category_assignments_one_active_pair",
        "provider_reputation_links_one_active_source",
        "provider_reputation_links_one_active_url",
    }
    placeholders = ",".join("?" for _ in partial_names)
    index_sql = {
        name: sql
        for name, sql in connection.exec_driver_sql(
            f"SELECT name, sql FROM sqlite_master WHERE type = 'index' AND name IN ({placeholders})",
            tuple(sorted(partial_names)),
        ).all()
    }
    if any(
        _normalise(index_sql.get(name) or "").partition("where")[2] != "archived_atisnull"
        for name in partial_names
    ):
        raise MigrationSchemaError("Provider partial-index predicates are incompatible.")
    checks = {
        table: {
            _normalise(item.get("sqltext") or "") for item in inspector.get_check_constraints(table)
        }
        for table in expected
    }
    expected_checks = {
        "provider_profiles": {
            "typeof(revision)='integer'andrevision>=1",
            "selection_statusin('neutral','preferred','avoid')",
            "selection_status!='avoid'or(selection_reasonisnotnullandlength(trim(selection_reason))>0)",
        },
        "provider_categories": {
            "length(trim(display_name))between1and160",
            "typeof(revision)='integer'andrevision>=1",
            "display_order>=0",
            "(archived_atisnullandarchive_reasonisnull)or(archived_atisnotnullandarchive_reasonisnotnullandlength(trim(archive_reason))between1and1000)",
        },
        "provider_category_assignments": {
            "(archived_atisnullandarchive_reasonisnull)or(archived_atisnotnullandarchive_reasonisnotnullandlength(trim(archive_reason))between1and1000)"
        },
        "provider_services": {"length(trim(display_name))>0"},
        "provider_service_areas": {
            "length(trim(display_name))>0",
            "country_code=''or(length(country_code)=2andcountry_code=upper(country_code)andcountry_codeglob'[a-z][a-z]')",
        },
        "provider_work_history": {"length(trim(summary))>0"},
        "provider_references": {
            "length(trim(coalesce(reference_name,'')))>0orlength(trim(coalesce(organization_name,'')))>0orlength(trim(coalesce(relationship,'')))>0"
        },
        "provider_reputation_links": {
            "source_kindin('google','yelp','angi','other')",
            "(source_kindin('google','yelp','angi')andsource_nameisnull)or(source_kind='other'andsource_nameisnotnullandlength(trim(source_name))>0)",
            "length(trim(normalized_source_key))>0",
            "length(trim(url))>0",
            "length(trim(normalized_url))>0",
        },
    }
    if checks != expected_checks:
        raise MigrationSchemaError("Provider checks are incompatible.")
    from app.modules.vendors.infrastructure.command_validation import validate_commands

    validate_commands(connection)


def _normalise(value: str) -> str:
    return "".join(value.lower().split())


def validate_vendor_data(connection) -> None:
    """Validate portable category/assignment records and their audit history."""
    categories = (
        connection.exec_driver_sql(
            "SELECT id, display_name, normalized_name, description, display_order, created_at, updated_at, "
            "archived_at, archive_reason, create_idempotency_key, create_request_fingerprint, revision "
            "FROM provider_categories"
        )
        .mappings()
        .all()
    )
    seeds = {item.id: item for item in PROVIDER_CATEGORY_SEEDS}
    if set(seeds) - {row["id"] for row in categories}:
        raise MigrationSchemaError("Provider category seeds are missing.")
    active_names: set[str] = set()
    for row in categories:
        _uuid(row["id"])
        _uuid(row["create_idempotency_key"])
        created_at, updated_at = _timestamp(row["created_at"]), _timestamp(row["updated_at"])
        if updated_at < created_at or not _canonical_text(row["display_name"], 160):
            raise MigrationSchemaError("Provider category data is invalid.")
        if row["description"] is not None and not _canonical_text(row["description"], 1000):
            raise MigrationSchemaError("Provider category description is invalid.")
        if (
            row["normalized_name"] != normalize_provider_category_name(row["display_name"])
            or row["display_order"] < 0
        ):
            raise MigrationSchemaError("Provider category data is invalid.")
        if row["archived_at"] is not None:
            _timestamp(row["archived_at"])
            if not _canonical_text(row["archive_reason"], 1000):
                raise MigrationSchemaError("Provider category lifecycle is invalid.")
        elif row["archive_reason"] is not None or row["normalized_name"] in active_names:
            raise MigrationSchemaError("Provider category lifecycle is invalid.")
        else:
            active_names.add(row["normalized_name"])
        _fingerprint(row["create_request_fingerprint"])
        seed = seeds.get(row["id"])
        if seed and (
            row["create_idempotency_key"] != seed.create_idempotency_key
            or row["create_request_fingerprint"] != seed.create_request_fingerprint
        ):
            raise MigrationSchemaError("Provider category seed identity is invalid.")
    assignments = (
        connection.exec_driver_sql(
            "SELECT id, provider_party_id, category_id, created_at, updated_at, archived_at, archive_reason, "
            "create_idempotency_key, create_request_fingerprint FROM provider_category_assignments"
        )
        .mappings()
        .all()
    )
    pairs: set[tuple[str, str]] = set()
    for row in assignments:
        for field in ("id", "provider_party_id", "category_id", "create_idempotency_key"):
            _uuid(row[field])
        created_at, updated_at = _timestamp(row["created_at"]), _timestamp(row["updated_at"])
        if updated_at < created_at or row["create_request_fingerprint"] != fingerprint(
            row["provider_party_id"], row["category_id"]
        ):
            raise MigrationSchemaError("Provider assignment data is invalid.")
        if row["archived_at"] is not None:
            _timestamp(row["archived_at"])
            if not _canonical_text(row["archive_reason"], 1000):
                raise MigrationSchemaError("Provider assignment lifecycle is invalid.")
        elif (
            row["archive_reason"] is not None
            or (row["provider_party_id"], row["category_id"]) in pairs
        ):
            raise MigrationSchemaError("Provider assignment lifecycle is invalid.")
        else:
            pairs.add((row["provider_party_id"], row["category_id"]))
    category_fingerprints = {
        ("provider_category", row["id"]): row["create_request_fingerprint"] for row in categories
    }
    _validate_audits(
        connection,
        categories,
        assignments,
        seeds,
        category_fingerprints,
    )


def _uuid(value: str) -> None:
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (TypeError, ValueError) as error:
        raise MigrationSchemaError("Provider retained ID is invalid.") from error


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed
    except (TypeError, ValueError) as error:
        raise MigrationSchemaError("Provider retained timestamp is invalid.") from error


def _canonical_text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == unicodedata.normalize("NFKC", value).strip()
        and len(value) <= maximum
    )


def _fingerprint(value: object) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise MigrationSchemaError("Provider retained fingerprint is invalid.")


def _validate_audits(
    connection,
    categories,
    assignments,
    seeds,
    category_fingerprints: dict[tuple[str, str], str],
) -> None:
    events = (
        connection.exec_driver_sql(
            "SELECT entity_type, entity_id, action, before_snapshot, after_snapshot, correlation_id "
            "FROM audit_events WHERE entity_type IN ('provider_category', 'provider_category_assignment') "
            "ORDER BY entity_type, entity_id, occurred_at, id"
        )
        .mappings()
        .all()
    )
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for event in events:
        _uuid(event["correlation_id"])
        key = (event["entity_type"], event["entity_id"])
        grouped.setdefault(key, []).append(
            {
                "action": event["action"],
                "before": _snapshot(event["before_snapshot"]),
                "after": _snapshot(event["after_snapshot"]),
            }
        )
    records = {
        **{("provider_category", row["id"]): _category_snapshot(row) for row in categories},
        **{
            ("provider_category_assignment", row["id"]): _assignment_snapshot(row)
            for row in assignments
        },
    }
    if set(grouped) - set(records):
        raise MigrationSchemaError("Provider audit history references a missing record.")
    for key, record in records.items():
        stream = grouped.get(key, [])
        seed = seeds.get(key[1]) if key[0] == "provider_category" else None
        if seed is not None and not stream:
            continue
        if not stream:
            raise MigrationSchemaError("Provider mutation audit evidence is missing.")
        _validate_audit_stream(stream, record, key[0], seed=seed)
        if stream[-1]["after"] != record:
            raise MigrationSchemaError("Provider audit history does not match retained data.")
        if key[0] == "provider_category":
            created = next((event for event in stream if event["action"] == "created"), None)
            if created is not None and created["after"]:
                created_after = created["after"]
                if category_fingerprints[key] != fingerprint(
                    created_after["displayName"],
                    created_after["description"],
                    created_after["displayOrder"],
                ):
                    raise MigrationSchemaError("Provider category creation fingerprint is invalid.")


def _validate_audit_stream(stream, record, entity_type: str, *, seed=None) -> None:
    allowed = {
        "provider_category": {"created", "updated", "archived", "restored"},
        "provider_category_assignment": {"created", "archived", "restored"},
    }[entity_type]
    first = stream[0]
    if seed is not None:
        if first["action"] not in {"updated", "archived"} or not _is_seed_origin(
            first["before"], seed
        ):
            raise MigrationSchemaError("Provider seed audit sequence is invalid.")
    elif first["action"] != "created" or first["before"] is not None:
        raise MigrationSchemaError("Provider creation audit is invalid.")
    previous: dict[str, object] | None = None
    for index, event in enumerate(stream):
        action, before, after = event["action"], event["before"], event["after"]
        if (
            action not in allowed
            or not isinstance(after, dict)
            or set(after) != set(record)
            or after.get("id") != record["id"]
            or (before is not None and (not isinstance(before, dict) or set(before) != set(record)))
        ):
            raise MigrationSchemaError("Provider audit event is invalid.")
        if index and before != previous:
            raise MigrationSchemaError("Provider audit snapshots are not contiguous.")
        previous_archived = bool(previous and previous.get("archivedAt") is not None)
        archived = after.get("archivedAt") is not None
        if action in {"created", "updated"} and (archived or (index and previous_archived)):
            raise MigrationSchemaError("Provider audit lifecycle is invalid.")
        if action == "archived" and ((index and previous_archived) or not archived):
            raise MigrationSchemaError("Provider archive audit is invalid.")
        if action == "restored" and (not previous_archived or archived):
            raise MigrationSchemaError("Provider restore audit is invalid.")
        previous = after


def _is_seed_origin(snapshot: object, seed) -> bool:
    if not isinstance(snapshot, dict):
        return False
    return all(
        (
            snapshot.get("id") == seed.id,
            snapshot.get("displayName") == seed.display_name,
            snapshot.get("normalizedName") == seed.normalized_name,
            snapshot.get("description") is None,
            snapshot.get("displayOrder") == seed.display_order,
            snapshot.get("archivedAt") is None,
            snapshot.get("archiveReason") is None,
            snapshot.get("revision") == 1,
        )
    )


def _category_snapshot(row) -> dict[str, object]:
    return {
        "revision": row["revision"],
        "id": row["id"],
        "displayName": row["display_name"],
        "normalizedName": row["normalized_name"],
        "description": row["description"],
        "displayOrder": row["display_order"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "archivedAt": row["archived_at"],
        "archiveReason": row["archive_reason"],
    }


def _assignment_snapshot(row) -> dict[str, object]:
    return {
        "id": row["id"],
        "providerPartyId": row["provider_party_id"],
        "categoryId": row["category_id"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "archivedAt": row["archived_at"],
        "archiveReason": row["archive_reason"],
    }


def _snapshot(value: str | None) -> dict[str, object] | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as error:
        raise MigrationSchemaError("Provider audit snapshot is invalid.") from error
    if not isinstance(parsed, dict):
        raise MigrationSchemaError("Provider audit snapshot is invalid.")
    return parsed

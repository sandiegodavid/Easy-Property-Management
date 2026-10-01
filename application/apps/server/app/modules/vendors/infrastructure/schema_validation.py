"""Exact current provider schema and retained data validation."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import inspect

from app.modules.vendors.domain.category_normalization import normalize_provider_category_name
from app.platform.migration_errors import MigrationSchemaError


def validate_vendor_schema(connection) -> None:
    inspector = inspect(connection)
    expected = {
        "provider_profiles": ({"party_id", "selection_status", "selection_reason", "notes", "created_at", "updated_at", "archived_at"}, {"selection_reason", "notes", "archived_at"}, {"party_id"}),
        "provider_categories": ({"id", "display_name", "normalized_name", "description", "display_order", "created_at", "updated_at", "archived_at", "archive_reason", "create_idempotency_key", "create_request_fingerprint"}, {"description", "archived_at", "archive_reason"}, {"id"}),
        "provider_category_assignments": ({"id", "provider_party_id", "category_id", "created_at", "updated_at", "archived_at", "archive_reason", "create_idempotency_key", "create_request_fingerprint"}, {"archived_at", "archive_reason"}, {"id"}),
        "provider_services": ({"id", "party_id", "display_name", "normalized_name", "created_at", "updated_at", "archived_at"}, {"archived_at"}, {"id"}),
        "provider_service_areas": ({"id", "party_id", "display_name", "normalized_name", "country_code", "created_at", "updated_at", "archived_at"}, {"archived_at"}, {"id"}),
        "provider_work_history": ({"id", "party_id", "property_id", "performed_on", "summary", "outcome_notes", "created_at", "updated_at", "archived_at"}, {"property_id", "outcome_notes", "archived_at"}, {"id"}),
        "provider_references": ({"id", "party_id", "reference_name", "organization_name", "relationship", "email", "phone", "notes", "created_at", "updated_at", "archived_at"}, {"reference_name", "organization_name", "relationship", "email", "phone", "notes", "archived_at"}, {"id"}),
        "provider_reputation_links": ({"id", "party_id", "source_kind", "source_name", "normalized_source_key", "url", "normalized_url", "notes", "last_checked_on", "created_at", "updated_at", "archived_at"}, {"source_name", "notes", "last_checked_on", "archived_at"}, {"id"}),
    }
    for table, (names, nullable, primary) in expected.items():
        if not inspector.has_table(table): raise MigrationSchemaError("Provider schema is missing.")
        columns = inspector.get_columns(table)
        if {item["name"] for item in columns} != names or {item["name"] for item in columns if item["primary_key"]} != primary:
            raise MigrationSchemaError("Provider columns are incompatible.")
        for item in columns:
            if not item["primary_key"] and bool(item["nullable"]) != (item["name"] in nullable):
                raise MigrationSchemaError("Provider nullability is incompatible.")
            if table == "provider_categories" and item["name"] == "display_order":
                if "INT" not in str(item["type"]).upper():
                    raise MigrationSchemaError("Provider types are incompatible.")
            elif "TEXT" not in str(item["type"]).upper() and "CHAR" not in str(item["type"]).upper():
                raise MigrationSchemaError("Provider types are incompatible.")
    required_fks = {
        "provider_profiles": {(('party_id',), 'parties', ('id',))},
        "provider_categories": set(),
        "provider_category_assignments": {(('provider_party_id',), 'provider_profiles', ('party_id',)), (('category_id',), 'provider_categories', ('id',))},
        "provider_services": {(('party_id',), 'provider_profiles', ('party_id',))},
        "provider_service_areas": {(('party_id',), 'provider_profiles', ('party_id',))},
        "provider_work_history": {(('party_id',), 'provider_profiles', ('party_id',)), (('property_id',), 'properties', ('id',))},
        "provider_references": {(('party_id',), 'provider_profiles', ('party_id',))},
        "provider_reputation_links": {(('party_id',), 'provider_profiles', ('party_id',))},
    }
    for table, expected_fks in required_fks.items():
        found = {(tuple(item['constrained_columns']), item['referred_table'], tuple(item['referred_columns'])) for item in inspector.get_foreign_keys(table)}
        if found != expected_fks: raise MigrationSchemaError("Provider foreign keys are incompatible.")
    required_indexes = {
        "provider_profiles": {"provider_profiles_selection": (("archived_at", "selection_status"), False)},
        "provider_categories": {"provider_categories_active_order": (("archived_at", "display_order", "normalized_name", "id"), False), "provider_categories_one_active_name": (("normalized_name",), True)},
        "provider_category_assignments": {"provider_category_assignments_provider_status": (("provider_party_id", "archived_at", "category_id"), False), "provider_category_assignments_category_status": (("category_id", "archived_at", "provider_party_id"), False), "provider_category_assignments_one_active_pair": (("provider_party_id", "category_id"), True)},
        "provider_services": {"provider_services_party_status": (("party_id", "archived_at"), False), "provider_services_one_active_name": (("party_id", "normalized_name"), True)},
        "provider_service_areas": {"provider_service_areas_party_status": (("party_id", "archived_at"), False), "provider_service_areas_one_active_name": (("party_id", "normalized_name", "country_code"), True)},
        "provider_work_history": {"provider_work_history_party_status": (("party_id", "archived_at", "performed_on"), False), "provider_work_history_property": (("property_id", "archived_at"), False)},
        "provider_references": {"provider_references_party_status": (("party_id", "archived_at"), False)},
        "provider_reputation_links": {
            "provider_reputation_links_party_status": (("party_id", "archived_at"), False),
            "provider_reputation_links_one_active_source": (("party_id", "normalized_source_key"), True),
            "provider_reputation_links_one_active_url": (("party_id", "normalized_url"), True),
        },
    }
    for table, required in required_indexes.items():
        found = {item['name']: (tuple(item['column_names']), bool(item.get('unique'))) for item in inspector.get_indexes(table)}
        if found != required: raise MigrationSchemaError("Provider indexes are incompatible.")
    partial_names = {
        'provider_services_one_active_name', 'provider_service_areas_one_active_name',
        'provider_categories_one_active_name', 'provider_category_assignments_one_active_pair',
        'provider_reputation_links_one_active_source', 'provider_reputation_links_one_active_url',
    }
    placeholders = ','.join('?' for _ in partial_names)
    index_sql = {name: sql for name, sql in connection.exec_driver_sql(
        f"SELECT name, sql FROM sqlite_master WHERE type = 'index' AND name IN ({placeholders})",
        tuple(sorted(partial_names)),
    ).all()}
    if any(_normalise(index_sql.get(name) or '').partition('where')[2] != 'archived_atisnull' for name in partial_names):
        raise MigrationSchemaError("Provider partial-index predicates are incompatible.")
    checks = {table: {_normalise(item.get('sqltext') or '') for item in inspector.get_check_constraints(table)} for table in expected}
    expected_checks = {
        'provider_profiles': {"selection_statusin('neutral','preferred','avoid')", "selection_status!='avoid'or(selection_reasonisnotnullandlength(trim(selection_reason))>0)"},
        'provider_categories': {"length(trim(display_name))between1and160", "display_order>=0", "(archived_atisnullandarchive_reasonisnull)or(archived_atisnotnullandarchive_reasonisnotnullandlength(trim(archive_reason))between1and1000)"},
        'provider_category_assignments': {"(archived_atisnullandarchive_reasonisnull)or(archived_atisnotnullandarchive_reasonisnotnullandlength(trim(archive_reason))between1and1000)"},
        'provider_services': {"length(trim(display_name))>0"},
        'provider_service_areas': {"length(trim(display_name))>0", "country_code=''or(length(country_code)=2andcountry_code=upper(country_code)andcountry_codeglob'[a-z][a-z]')"},
        'provider_work_history': {"length(trim(summary))>0"},
        'provider_references': {"length(trim(coalesce(reference_name,'')))>0orlength(trim(coalesce(organization_name,'')))>0orlength(trim(coalesce(relationship,'')))>0"},
        'provider_reputation_links': {
            "source_kindin('google','yelp','angi','other')",
            "(source_kindin('google','yelp','angi')andsource_nameisnull)or(source_kind='other'andsource_nameisnotnullandlength(trim(source_name))>0)",
            "length(trim(normalized_source_key))>0",
            "length(trim(url))>0",
            "length(trim(normalized_url))>0",
        },
    }
    if checks != expected_checks: raise MigrationSchemaError("Provider checks are incompatible.")


def _normalise(value: str) -> str:
    return ''.join(value.lower().split())


_SEED_IDS = {
    "00000000-0000-4000-8000-000000000301",
    "00000000-0000-4000-8000-000000000302",
    "00000000-0000-4000-8000-000000000303",
    "00000000-0000-4000-8000-000000000304",
    "00000000-0000-4000-8000-000000000305",
    "00000000-0000-4000-8000-000000000306",
    "00000000-0000-4000-8000-000000000307",
}


def validate_vendor_data(connection) -> None:
    """Validate category lifecycles separately from mutation-time checks."""
    categories = connection.exec_driver_sql(
        "SELECT id, display_name, normalized_name, display_order, created_at, updated_at, "
        "archived_at, archive_reason, create_idempotency_key, create_request_fingerprint "
        "FROM provider_categories"
    ).mappings().all()
    if not _SEED_IDS.issubset({row["id"] for row in categories}):
        raise MigrationSchemaError("Provider category seeds are missing.")
    active_names: set[str] = set()
    for row in categories:
        _uuid(row["id"]); _uuid(row["create_idempotency_key"]); _timestamp(row["created_at"]); _timestamp(row["updated_at"])
        if row["updated_at"] < row["created_at"] or not row["display_name"].strip() or len(row["display_name"]) > 160:
            raise MigrationSchemaError("Provider category data is invalid.")
        if row["normalized_name"] != normalize_provider_category_name(row["display_name"]) or row["display_order"] < 0:
            raise MigrationSchemaError("Provider category data is invalid.")
        archived = row["archived_at"] is not None
        if archived:
            _timestamp(row["archived_at"])
            if not row["archive_reason"] or not row["archive_reason"].strip():
                raise MigrationSchemaError("Provider category lifecycle is invalid.")
        elif row["archive_reason"] is not None or row["normalized_name"] in active_names:
            raise MigrationSchemaError("Provider category lifecycle is invalid.")
        else:
            active_names.add(row["normalized_name"])
        if len(row["create_request_fingerprint"]) != 64 and not row["create_request_fingerprint"].startswith("seed-"):
            raise MigrationSchemaError("Provider category idempotency data is invalid.")
    assignments = connection.exec_driver_sql(
        "SELECT id, provider_party_id, category_id, created_at, updated_at, archived_at, archive_reason, "
        "create_idempotency_key, create_request_fingerprint FROM provider_category_assignments"
    ).mappings().all()
    pairs: set[tuple[str, str]] = set()
    for row in assignments:
        for field in ("id", "provider_party_id", "category_id", "create_idempotency_key"):
            _uuid(row[field])
        _timestamp(row["created_at"]); _timestamp(row["updated_at"])
        if row["updated_at"] < row["created_at"] or len(row["create_request_fingerprint"]) != 64:
            raise MigrationSchemaError("Provider assignment data is invalid.")
        if row["archived_at"] is not None:
            _timestamp(row["archived_at"])
            if not row["archive_reason"] or not row["archive_reason"].strip():
                raise MigrationSchemaError("Provider assignment lifecycle is invalid.")
        elif row["archive_reason"] is not None or (row["provider_party_id"], row["category_id"]) in pairs:
            raise MigrationSchemaError("Provider assignment lifecycle is invalid.")
        else:
            pairs.add((row["provider_party_id"], row["category_id"]))


def _uuid(value: str) -> None:
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (TypeError, ValueError) as error:
        raise MigrationSchemaError("Provider retained ID is invalid.") from error


def _timestamp(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
    except (TypeError, ValueError) as error:
        raise MigrationSchemaError("Provider retained timestamp is invalid.") from error

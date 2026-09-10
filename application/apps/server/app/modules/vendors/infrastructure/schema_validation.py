"""Exact current provider schema validation for VEND-001 and VEND-002."""

from sqlalchemy import inspect

from app.platform.migration_errors import MigrationSchemaError


def validate_vendor_schema(connection) -> None:
    inspector = inspect(connection)
    expected = {
        "provider_profiles": ({"party_id", "selection_status", "selection_reason", "notes", "created_at", "updated_at", "archived_at"}, {"selection_reason", "notes", "archived_at"}, {"party_id"}),
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
            if "TEXT" not in str(item["type"]).upper() and "CHAR" not in str(item["type"]).upper():
                raise MigrationSchemaError("Provider types are incompatible.")
    required_fks = {
        "provider_profiles": {(('party_id',), 'parties', ('id',))},
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

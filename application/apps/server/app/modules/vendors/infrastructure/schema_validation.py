"""Exact current VEND-001 schema validation."""

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
    }
    for table, (names, nullable, primary) in expected.items():
        if not inspector.has_table(table): raise MigrationSchemaError("VEND-001 schema is missing.")
        columns = inspector.get_columns(table)
        if {item["name"] for item in columns} != names or {item["name"] for item in columns if item["primary_key"]} != primary:
            raise MigrationSchemaError("VEND-001 columns are incompatible.")
        for item in columns:
            if not item["primary_key"] and bool(item["nullable"]) != (item["name"] in nullable):
                raise MigrationSchemaError("VEND-001 nullability is incompatible.")
            if "TEXT" not in str(item["type"]).upper() and "CHAR" not in str(item["type"]).upper():
                raise MigrationSchemaError("VEND-001 types are incompatible.")
    required_fks = {
        "provider_profiles": {(('party_id',), 'parties', ('id',))},
        "provider_services": {(('party_id',), 'provider_profiles', ('party_id',))},
        "provider_service_areas": {(('party_id',), 'provider_profiles', ('party_id',))},
        "provider_work_history": {(('party_id',), 'provider_profiles', ('party_id',)), (('property_id',), 'properties', ('id',))},
        "provider_references": {(('party_id',), 'provider_profiles', ('party_id',))},
    }
    for table, expected_fks in required_fks.items():
        found = {(tuple(item['constrained_columns']), item['referred_table'], tuple(item['referred_columns'])) for item in inspector.get_foreign_keys(table)}
        if found != expected_fks: raise MigrationSchemaError("VEND-001 foreign keys are incompatible.")
    required_indexes = {
        "provider_profiles": {"provider_profiles_selection": (("archived_at", "selection_status"), False)},
        "provider_services": {"provider_services_party_status": (("party_id", "archived_at"), False), "provider_services_one_active_name": (("party_id", "normalized_name"), True)},
        "provider_service_areas": {"provider_service_areas_party_status": (("party_id", "archived_at"), False), "provider_service_areas_one_active_name": (("party_id", "normalized_name", "country_code"), True)},
        "provider_work_history": {"provider_work_history_party_status": (("party_id", "archived_at", "performed_on"), False), "provider_work_history_property": (("property_id", "archived_at"), False)},
        "provider_references": {"provider_references_party_status": (("party_id", "archived_at"), False)},
    }
    for table, required in required_indexes.items():
        found = {item['name']: (tuple(item['column_names']), bool(item.get('unique'))) for item in inspector.get_indexes(table)}
        if found != required: raise MigrationSchemaError("VEND-001 indexes are incompatible.")
    index_sql = {name: sql for name, sql in connection.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type = 'index' AND name IN ('provider_services_one_active_name', 'provider_service_areas_one_active_name')").all()}
    if _normalise(index_sql.get('provider_services_one_active_name') or '').partition('where')[2] != 'archived_atisnull' or _normalise(index_sql.get('provider_service_areas_one_active_name') or '').partition('where')[2] != 'archived_atisnull':
        raise MigrationSchemaError("VEND-001 partial-index predicates are incompatible.")
    checks = {table: {_normalise(item.get('sqltext') or '') for item in inspector.get_check_constraints(table)} for table in expected}
    expected_checks = {
        'provider_profiles': {"selection_statusin('neutral','preferred','avoid')", "selection_status!='avoid'or(selection_reasonisnotnullandlength(trim(selection_reason))>0)"},
        'provider_services': {"length(trim(display_name))>0"},
        'provider_service_areas': {"length(trim(display_name))>0", "country_code=''or(length(country_code)=2andcountry_code=upper(country_code)andcountry_codeglob'[a-z][a-z]')"},
        'provider_work_history': {"length(trim(summary))>0"},
        'provider_references': {"length(trim(coalesce(reference_name,'')))>0orlength(trim(coalesce(organization_name,'')))>0orlength(trim(coalesce(relationship,'')))>0"},
    }
    if checks != expected_checks: raise MigrationSchemaError("VEND-001 checks are incompatible.")


def _normalise(value: str) -> str:
    return ''.join(value.lower().split())

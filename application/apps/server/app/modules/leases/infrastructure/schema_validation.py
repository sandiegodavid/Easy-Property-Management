"""Exact current LEASE-001 schema validation."""

from sqlalchemy import inspect

from app.platform.migration_errors import MigrationSchemaError


EXPECTED = {
    "leases": {
        "columns": {"id", "space_id", "lease_kind", "status", "contract_starts_on", "contract_ends_on", "occupancy_starts_on", "executed_on", "actual_move_out_on", "end_reason", "notes", "created_at", "updated_at"},
        "nullable": {"contract_ends_on", "executed_on", "actual_move_out_on", "end_reason", "notes"},
        "integer": set(),
        "indexes": {"leases_space_status_dates": (("space_id", "status", "contract_starts_on", "contract_ends_on"), False)},
        "foreign_keys": {(('space_id',), 'spaces', ('id',))},
        "checks": {"lease_kindin('residential','commercial')", "statusin('draft','executed','ended','terminated','void')", "end_reasonisnullorend_reasonin('contract_completed','early_termination','mutual_termination','other')", "contract_ends_onisnullorcontract_ends_on>contract_starts_on", "occupancy_starts_on>=contract_starts_on", "(status='draft'andexecuted_onisnullandactual_move_out_onisnullandend_reasonisnull)or(status='executed'andexecuted_onisnotnullandactual_move_out_onisnullandend_reasonisnull)or(status='ended'andexecuted_onisnotnullandactual_move_out_onisnotnullandend_reasonisnotnullandend_reason='contract_completed')or(status='terminated'andexecuted_onisnotnullandactual_move_out_onisnotnullandend_reasonisnotnullandend_reasonin('early_termination','mutual_termination','other'))or(status='void'andexecuted_onisnotnullandactual_move_out_onisnullandend_reasonisnull)"},
    },
    "lease_term_versions": {
        "columns": {"id", "lease_id", "effective_on", "ends_on", "base_rent_minor", "currency_code", "payment_frequency", "payment_due_day", "agreed_security_deposit_minor", "created_at"},
        "nullable": {"ends_on", "payment_due_day"},
        "integer": {"base_rent_minor", "payment_due_day", "agreed_security_deposit_minor"},
        "indexes": {"lease_terms_lease_dates": (("lease_id", "effective_on", "ends_on"), False)},
        "foreign_keys": {(('lease_id',), 'leases', ('id',))},
        "checks": {"ends_onisnullorends_on>effective_on", "base_rent_minor>=0", "length(currency_code)=3andcurrency_code=upper(currency_code)", "payment_frequencyin('monthly','weekly')", "(payment_frequency='monthly'andpayment_due_daybetween1and31)or(payment_frequency='weekly'andpayment_due_dayisnull)", "agreed_security_deposit_minor>=0"},
    },
    "lease_participants": {
        "columns": {"id", "lease_id", "tenant_party_id", "participant_role", "starts_on", "ends_on", "notes", "created_at", "updated_at"},
        "nullable": {"ends_on", "notes"},
        "integer": set(),
        "indexes": {"lease_participants_lease_dates": (("lease_id", "starts_on", "ends_on"), False), "lease_participants_tenant_dates": (("tenant_party_id", "starts_on", "ends_on"), False)},
        "foreign_keys": {(('lease_id',), 'leases', ('id',)), (('tenant_party_id',), 'tenant_profiles', ('party_id',))},
        "checks": {"participant_rolein('primary_tenant','co_tenant','guarantor','business_signatory')", "ends_onisnullorends_on>starts_on"},
    },
    "lease_renewal_options": {
        "columns": {"id", "lease_id", "status", "proposed_starts_on", "proposed_ends_on", "notice_due_on", "response_due_on", "decided_on", "notes", "created_at", "updated_at"},
        "nullable": {"proposed_ends_on", "notice_due_on", "response_due_on", "decided_on", "notes"},
        "integer": set(),
        "indexes": {"lease_renewals_lease_status_dates": (("lease_id", "status", "notice_due_on", "response_due_on"), False)},
        "foreign_keys": {(('lease_id',), 'leases', ('id',))},
        "checks": {"statusin('open','exercised','declined','expired','withdrawn')", "proposed_ends_onisnullorproposed_ends_on>proposed_starts_on", "(status='open'anddecided_onisnull)or(status!='open'anddecided_onisnotnull)"},
    },
    "lease_termination_cases": {
        "columns": {"id", "lease_id", "status", "reason", "notice_received_on", "requested_termination_on", "expected_move_out_on", "agreed_termination_on", "accepted_on", "completed_on", "tenant_explanation", "contract_clause_reference", "operator_notes", "created_at", "updated_at"},
        "nullable": {"agreed_termination_on", "accepted_on", "completed_on", "tenant_explanation", "contract_clause_reference", "operator_notes"},
        "integer": set(),
        "indexes": {"lease_termination_cases_lease_status": (("lease_id", "status", "requested_termination_on"), False)},
        "foreign_keys": {(('lease_id',), 'leases', ('id',))},
        "checks": {"statusin('requested','under_review','proposed','accepted','withdrawn','declined','completed')", "reasonin('job_relocation','military','habitability','mutual','other')", "(statusin('accepted','completed')andagreed_termination_onisnotnullandaccepted_onisnotnull)or(statusnotin('accepted','completed')andcompleted_onisnull)", "(status='completed'andcompleted_onisnotnull)orstatus!='completed'"},
    },
    "lease_termination_proposals": {
        "columns": {"id", "termination_case_id", "proposal_version", "proposed_termination_on", "expected_move_out_on", "rent_responsibility_ends_on", "termination_fee_minor", "currency_code", "fee_waived", "replacement_tenant_condition", "access_arrangement", "other_terms", "response_due_on", "status", "decided_on", "created_at"},
        "nullable": {"rent_responsibility_ends_on", "termination_fee_minor", "currency_code", "replacement_tenant_condition", "access_arrangement", "other_terms", "response_due_on", "decided_on"},
        "integer": {"proposal_version", "termination_fee_minor", "fee_waived"},
        "indexes": {"lease_termination_proposals_case_version": (("termination_case_id", "proposal_version"), True)},
        "foreign_keys": {(('termination_case_id',), 'lease_termination_cases', ('id',))},
        "checks": {"proposal_version>0", "termination_fee_minorisnullortermination_fee_minor>=0", "fee_waivedin(0,1)", "(termination_fee_minorisnullandcurrency_codeisnull)or(termination_fee_minorisnotnullandlength(currency_code)=3andcurrency_code=upper(currency_code))", "statusin('open','accepted','rejected','countered','withdrawn','expired')", "(status='open'anddecided_onisnull)or(status!='open'anddecided_onisnotnull)"},
    },
}


def validate_lease_schema(connection) -> None:
    inspector = inspect(connection)
    for table, expected in EXPECTED.items():
        if not inspector.has_table(table):
            raise MigrationSchemaError(f"{table} schema is missing or incompatible with LEASE-001.")
        columns = inspector.get_columns(table)
        if {column["name"] for column in columns} != expected["columns"]:
            raise MigrationSchemaError(f"{table} columns are incompatible with LEASE-001.")
        if {column["name"] for column in columns if column["primary_key"]} != {"id"}:
            raise MigrationSchemaError(f"{table} primary key is incompatible with LEASE-001.")
        for column in columns:
            name = column["name"]
            if not column["primary_key"] and bool(column["nullable"]) != (name in expected["nullable"]):
                raise MigrationSchemaError(f"{table} nullability is incompatible with LEASE-001.")
            type_name = str(column["type"]).upper()
            expects_integer = name in expected["integer"]
            if expects_integer != ("INT" in type_name):
                raise MigrationSchemaError(f"{table} column types are incompatible with LEASE-001.")
            if not expects_integer and "TEXT" not in type_name and "CHAR" not in type_name:
                raise MigrationSchemaError(f"{table} column types are incompatible with LEASE-001.")
        indexes = {item["name"]: (tuple(item["column_names"]), bool(item.get("unique"))) for item in inspector.get_indexes(table)}
        if indexes != expected["indexes"] or inspector.get_unique_constraints(table):
            raise MigrationSchemaError(f"{table} indexes are incompatible with LEASE-001.")
        foreign_keys = {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"])) for item in inspector.get_foreign_keys(table)}
        if foreign_keys != expected["foreign_keys"]:
            raise MigrationSchemaError(f"{table} foreign keys are incompatible with LEASE-001.")
        checks = {_normalise(item.get("sqltext") or "") for item in inspector.get_check_constraints(table)}
        if checks != expected["checks"]:
            raise MigrationSchemaError(f"{table} constraints are incompatible with LEASE-001.")


def _normalise(value: str) -> str:
    return "".join(value.lower().split())

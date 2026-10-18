"""Masked IDs, durable Tenant edits and transactional lease execution eligibility."""

import json
from dataclasses import replace
from datetime import date
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from app.bootstrap.api import create_app
from app.modules.leases.application.service import LeaseConflictError, ParticipantCommand
from app.modules.leases.tests import test_leases as lease_fixtures
from app.modules.leases.tests.commands import lease_command
from app.modules.tenants.application.service import (
    TenantConflictError,
    TenantError,
    TenantProfilePatchCommand,
    TenantCreateCommand,
)
from app.modules.tenants.domain.audit_policy import TENANT_ACTIVITY_POLICY
from app.modules.parties.domain.official_ids import OfficialId
from app.modules.tenants.tests.test_command_readiness import (
    tenant_services as tenant_services,
    create,
)
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema
from app.platform.testing_client import LocalApiClient


ID = OfficialId("drivers_license", "US", "A123", "OR", "2030-10-31")


@pytest.mark.parametrize(
    "fields",
    [
        {"last_four": "123456789"},
        {"last_four": "••12"},
        {"issuing_country": "us"},
        {"issuing_region": "Oregon State"},
        {"expires_on": "2028-02-30"},
        {"document_type": "social_security"},
    ],
)
def test_rejects_full_numbers_and_malformed_metadata(fields):
    with pytest.raises(ValueError):
        replace(ID, **fields)


def test_masked_id_edits_retry_conflict_noop_and_rollback(tenant_services):
    workspace, tenants, _, _ = tenant_services
    first = create(tenants)
    assert first["profile"]["officialIds"] == []
    command, key = TenantProfilePatchCommand(official_ids=(ID,)), str(uuid4())
    changed = tenants.update_profile(first["id"], command, expected_revision=1, idempotency_key=key)
    assert changed["profile"]["officialIds"] == [ID.to_dict()]
    assert changed["revision"] == 2
    assert (
        tenants.update_profile(first["id"], command, expected_revision=1, idempotency_key=key)
        == changed
    )
    assert tenants.recover(key=key) == changed
    with pytest.raises(TenantConflictError):
        tenants.update_profile(
            first["id"],
            TenantProfilePatchCommand(official_ids=()),
            expected_revision=1,
            idempotency_key=key,
        )
    with pytest.raises(TenantConflictError):
        tenants.update_profile(
            first["id"], command, expected_revision=1, idempotency_key=str(uuid4())
        )
    noop = tenants.update_profile(
        first["id"], command, expected_revision=2, idempotency_key=str(uuid4())
    )
    assert noop["revision"] == 2
    with patch.object(
        tenants.unit_of_work.recorder,
        "record_change",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError):
            tenants.update_profile(
                first["id"],
                TenantProfilePatchCommand(official_ids=()),
                expected_revision=2,
                idempotency_key=str(uuid4()),
            )
    assert tenants.get(first["id"])["profile"] == changed["profile"]
    with pytest.raises(TenantError):
        TenantProfilePatchCommand(official_ids=(ID, ID))
    with pytest.raises(TenantError):
        TenantProfilePatchCommand(
            official_ids=tuple(replace(ID, last_four=f"{i:04}") for i in range(11))
        )
    assert TENANT_ACTIVITY_POLICY.redact(changed["profile"])["officialIds"] == "[redacted]"
    validate_latest_schema(workspace.paths.database)


def test_http_masked_contract_and_retained_corruption(tenant_services, tmp_path):
    workspace, tenants, _, _ = tenant_services
    first = create(tenants)
    config = tmp_path / "http-config.json"
    config.write_text(json.dumps({"localWorkspacePath": str(workspace.paths.root)}))
    with LocalApiClient(create_app(config)) as client:
        payload = {
            "expectedRevision": 1,
            "idempotencyKey": str(uuid4()),
            "officialIds": [ID.to_dict()],
        }
        response = client.patch(f"/api/tenants/{first['id']}", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["profile"]["officialIds"] == [ID.to_dict()]
        activity = client.get("/api/audit/events").json()["events"]
        changes = [
            item
            for item in activity
            if item["entityType"] == "tenant_profile" and item["action"] == "updated"
        ]
        assert changes[-1]["after"]["officialIds"] == "[redacted]"
        contextual = client.get(f"/api/audit/events/tenant_profile/{first['id']}").json()["events"]
        assert any(item["after"]["officialIds"] == [ID.to_dict()] for item in contextual)
        for malformed in (
            {**ID.to_dict(), "lastFour": "123456789"},
            {**ID.to_dict(), "fullNumber": "secret"},
        ):
            response = client.patch(
                f"/api/tenants/{first['id']}", json={**payload, "officialIds": [malformed]}
            )
            assert response.status_code == 422
    with tenants.unit_of_work.engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(text("UPDATE tenant_profiles SET official_ids_json='{}'"))
        connection.execute(
            text("UPDATE tenant_profiles SET official_ids_json=:ids"),
            {
                "ids": json.dumps(
                    [
                        {
                            "document_type": "passport",
                            "issuing_country": "US",
                            "last_four": "12345678",
                        }
                    ]
                )
            },
        )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(workspace.paths.database)


def test_execution_checks_all_ids_in_transaction_and_replays_original_result():
    case = lease_fixtures.LeaseTerminationTests()
    case.setUp()
    try:
        property_record = lease_fixtures.inventory_command(
            case.portfolio,
            "create_property",
            lease_fixtures.PropertyCreateCommand(
                "ID requirement home",
                "2 Main Street",
                "Portland",
                "US",
                "single_family_home",
                (lease_fixtures.OwnershipInput("local_operator"),),
                region="OR",
            ),
        )
        case.space_id = case.portfolio.get_property(property_record.id)["spaces"][0]["id"]
        draft = case._new_draft()
        co = case.tenants.create(
            TenantCreateCommand("individual", "Co tenant awaiting ID"),
            expected_revision=0,
            idempotency_key=str(uuid4()),
        )
        lease_command(
            case.service, "add_participant", draft["id"], ParticipantCommand(co["id"], "co_tenant")
        )
        draft = case.service.get(draft["id"])
        tenant = case.tenants.get(case.tenant_id)
        case.tenants.update_profile(
            case.tenant_id,
            TenantProfilePatchCommand(official_ids=()),
            expected_revision=tenant["revision"],
            idempotency_key=str(uuid4()),
        )
        key = str(uuid4())
        kwargs = {
            "expected_revision": case.portfolio.get_space_status(case.space_id)["revision"],
            "expected_lease_revision": draft["leaseRevision"],
            "idempotency_key": key,
            "executed_on": date.today().isoformat(),
            "confirmed": True,
        }
        with pytest.raises(LeaseConflictError, match="official ID"):
            case.service.execute(draft["id"], **kwargs)
        assert case.service.get(draft["id"])["status"] == "draft"
        tenant = case.tenants.get(case.tenant_id)
        case.tenants.update_profile(
            case.tenant_id,
            TenantProfilePatchCommand(official_ids=(ID,)),
            expected_revision=tenant["revision"],
            idempotency_key=str(uuid4()),
        )
        with pytest.raises(LeaseConflictError, match="official ID"):
            case.service.execute(draft["id"], **kwargs)
        case.tenants.update_profile(
            co["id"],
            TenantProfilePatchCommand(official_ids=(ID,)),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
        reads = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if "official_ids_json" in statement and statement.lstrip().startswith("SELECT"):
                reads.append(statement)

        event.listen(case.service.unit_of_work.engine, "before_cursor_execute", capture)
        try:
            executed = case.service.execute(draft["id"], **kwargs)
        finally:
            event.remove(case.service.unit_of_work.engine, "before_cursor_execute", capture)
        assert executed["status"] == "executed"
        assert len([query for query in reads if " IN " in query]) == 1
        tenant = case.tenants.get(case.tenant_id)
        case.tenants.update_profile(
            case.tenant_id,
            TenantProfilePatchCommand(official_ids=()),
            expected_revision=tenant["revision"],
            idempotency_key=str(uuid4()),
        )
        assert case.service.execute(draft["id"], **kwargs) == executed
        validate_latest_schema(case.workspace.paths.database)
    finally:
        case.doCleanups()

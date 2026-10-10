from __future__ import annotations

from uuid import uuid4

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command as alembic_command
from app.platform.testing_client import LocalApiClient as TestClient

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.leases.infrastructure.unit_of_work import SQLiteLeaseParticipationGuard
from app.modules.parties.application.service import (
    ContactMethodCommand,
    ContactReferenceResolution,
    PartyConflictError,
    PartyContactService,
    PartyValidationError,
    SharedPartyFactory,
)
from app.modules.parties.domain.contact_values import contact_search_terms
from app.modules.parties.infrastructure.unit_of_work import (
    SQLitePartyOperations,
    SQLitePartyReadOperations,
    SQLitePartyUnitOfWork,
)
from app.modules.portfolio.application.service import PartyCreateCommand, PortfolioService
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioUnitOfWork
from app.modules.tenants.application.service import (
    TenantConflictError,
    TenantCreateCommand,
    TenantError,
    TenantProfilePatchCommand,
    TenantService,
)
from app.modules.tenants.infrastructure.schema_validation import validate_tenant_schema
from app.modules.tenants.infrastructure.unit_of_work import (
    SQLiteTenantContactReferenceGuard,
    SQLiteTenantUnitOfWork,
)
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.config import LocalConfig
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import _config as alembic_config
from app.platform.product_migrations import initialize_latest_schema
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction


from app.modules.tenants.tests.command_helpers import current_tenant_command


class TenantTests(unittest.TestCase):
    def tenant_command(self, action, *args, **kwargs):
        return current_tenant_command(self.tenants, action, *args, **kwargs)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.workspace = WorkspaceService(LocalConfig(root / "config.json", root / "workspace"))
        self.workspace.initialize()
        self.audit = SQLiteAuditRepository(self.workspace.paths.database)
        self.tenants = TenantService(
            SQLiteTenantUnitOfWork(
                self.workspace.paths.database,
                AuditRecorder(self.audit),
                SQLiteLeaseParticipationGuard(),
                SQLitePartyOperations(self.workspace.paths.database),
                SQLitePartyReadOperations(SQLitePartyOperations(self.workspace.paths.database)),
            ),
            SharedPartyFactory(),
        )
        self.contacts = PartyContactService(
            SQLitePartyUnitOfWork(
                self.workspace.paths.database,
                AuditRecorder(self.audit),
                (SQLiteTenantContactReferenceGuard(AuditRecorder(self.audit)),),
            )
        )

    def contact_command(self, action, party_id, *args, **kwargs):
        """Existing lifecycle fixtures explicitly submit the current Party revision."""
        revision = self.contacts.unit_of_work.methods(party_id)[0].revision
        return getattr(self.contacts, action)(
            party_id, *args, expected_revision=revision, idempotency_key=str(uuid4()), **kwargs
        )

    def test_creates_profile_contacts_and_audits_them_together(self) -> None:
        tenant = self.tenant_command(
            "create",
            TenantCreateCommand(
                "individual",
                "Robin Renter",
                contacts=(
                    ContactMethodCommand("email", " Robin@Example.Test ", label="Home"),
                    ContactMethodCommand("phone", "+1 (503) 555-0111"),
                ),
            ),
        )
        self.assertEqual(tenant["profile"]["partyId"], tenant["id"])
        self.assertEqual(tenant["contactMethods"][0]["displayValue"], "Robin@Example.Test")
        events = self.audit.history(
            correlation_id=self.audit.history("party", tenant["id"])[-1].correlation_id
        )
        self.assertEqual(
            {item.entity_type for item in events},
            {"party", "tenant_profile", "party_contact_method", "tenant_command_operation"},
        )
        with self.assertRaises(PartyConflictError):
            self.contact_command(
                "add", tenant["id"], ContactMethodCommand("email", "robin@example.test")
            )

    def test_designates_existing_party_and_keeps_identity_when_profile_archives(self) -> None:
        portfolio = PortfolioService(
            SQLitePortfolioUnitOfWork(self.workspace.paths.database, AuditRecorder(self.audit)),
            time_zone_resolver=BundledAddressTimeZoneResolver(),
        )
        party = portfolio.create_party(PartyCreateCommand("individual", "Existing Person"))
        tenant = self.tenant_command("designate", party.id, notes="Contact after work")
        self.tenant_command("archive", party.id, confirmed=True)
        archived = self.tenants.get(party.id)
        self.assertIsNone(archived["archivedAt"])
        self.assertIsNotNone(archived["profile"]["archivedAt"])
        self.assertEqual(tenant["id"], party.id)

    def test_preferred_contact_requires_explicit_change_before_archive(self) -> None:
        tenant = self.tenant_command(
            "create",
            TenantCreateCommand(
                "individual",
                "Taylor Tenant",
                contacts=(
                    ContactMethodCommand("email", "taylor@example.test"),
                    ContactMethodCommand("phone", "555 555 0100"),
                ),
            ),
        )
        email, phone = tenant["contactMethods"]
        self.tenant_command(
            "update_profile",
            tenant["id"],
            TenantProfilePatchCommand.from_mapping(
                {
                    "preferredContactMethodId": email["id"],
                }
            ),
        )
        with self.assertRaises(PartyValidationError):
            self.contact_command("archive", tenant["id"], email["id"], confirmed=True)
        self.contact_command(
            "archive",
            tenant["id"],
            email["id"],
            confirmed=True,
            reference_resolutions=(
                ContactReferenceResolution(
                    "tenant",
                    tenant["id"],
                    replacement_contact_method_id=phone["id"],
                    expected_tenant_revision=self.tenants.get(tenant["id"])["revision"],
                ),
            ),
        )
        self.assertEqual(
            self.tenants.get(tenant["id"])["profile"]["preferredContactMethodId"], phone["id"]
        )

    def test_searches_contact_values_and_supports_archived_only_listing(self) -> None:
        tenant = self.tenant_command(
            "create",
            TenantCreateCommand(
                "individual",
                "Searchable Person",
                contacts=(ContactMethodCommand("email", "find-me@example.test"),),
            ),
        )
        self.assertEqual(
            [item["id"] for item in self.tenants.list(search="find-me@example")], [tenant["id"]]
        )
        self.tenant_command("archive", tenant["id"], confirmed=True)
        self.assertEqual(self.tenants.list(search="find-me@example"), [])
        self.assertEqual(
            [item["id"] for item in self.tenants.list(archive_state="archived")], [tenant["id"]]
        )

    def test_phone_search_uses_canonical_format(self) -> None:
        tenant = self.tenant_command(
            "create",
            TenantCreateCommand(
                "individual",
                "Phone Search",
                contacts=(ContactMethodCommand("phone", "(503) 555-0100"),),
            ),
        )
        self.assertEqual(
            [item["id"] for item in self.tenants.list(search="503-555")], [tenant["id"]]
        )

    def test_shared_party_contact_values_are_searchable_without_contact_methods(self) -> None:
        tenant = self.tenant_command(
            "create",
            TenantCreateCommand(
                "individual",
                "Shared Contact",
                contacts=(
                    ContactMethodCommand("email", "shared@example.test"),
                    ContactMethodCommand("phone", "503/555/0199"),
                ),
            ),
        )
        self.assertEqual(
            [item["id"] for item in self.tenants.list(search="shared@example")], [tenant["id"]]
        )
        self.assertEqual(
            [item["id"] for item in self.tenants.list(search="5035550199")], [tenant["id"]]
        )

    def test_alphanumeric_search_does_not_broaden_to_digits_only_phone_matches(self) -> None:
        expected = self.tenant_command(
            "create",
            TenantCreateCommand(
                "individual",
                "Unit Contact",
                contacts=(ContactMethodCommand("email", "unit1@example.test"),),
            ),
        )
        self.tenant_command(
            "create",
            TenantCreateCommand(
                "individual",
                "Unrelated Phone",
                contacts=(ContactMethodCommand("phone", "555-000-0001"),),
            ),
        )
        self.assertEqual(
            [item["id"] for item in self.tenants.list(search="unit1@example.test")],
            [expected["id"]],
        )

    def test_unicode_text_and_like_metacharacters_are_literal_searches(self) -> None:
        expected = self.tenant_command(
            "create",
            TenantCreateCommand(
                "individual",
                "租客1",
                contacts=(ContactMethodCommand("email", "unit_one@example.test"),),
            ),
        )
        self.tenant_command(
            "create",
            TenantCreateCommand(
                "individual",
                "Unrelated",
                contacts=(ContactMethodCommand("phone", "555-000-0001"),),
            ),
        )
        literal_percent = self.tenant_command(
            "create", TenantCreateCommand("individual", "100% Reliable")
        )
        self.assertEqual(
            [item["id"] for item in self.tenants.list(search="租客1")], [expected["id"]]
        )
        self.assertEqual(
            [item["id"] for item in self.tenants.list(search="unit_one@example.test")],
            [expected["id"]],
        )
        self.assertEqual(
            [item["id"] for item in self.tenants.list(search="%")], [literal_percent["id"]]
        )
        self.assertEqual(contact_search_terms("#1"), ("#1",))

    def test_archived_contact_value_can_be_added_again(self) -> None:
        tenant = self.tenant_command(
            "create",
            TenantCreateCommand(
                "individual",
                "Reuse Contact",
                contacts=(ContactMethodCommand("email", "reuse@example.test"),),
            ),
        )
        old_method = tenant["contactMethods"][0]
        self.contact_command("archive", tenant["id"], old_method["id"], confirmed=True)
        replacement = self.contact_command(
            "add", tenant["id"], ContactMethodCommand("email", "REUSE@example.test")
        )
        self.assertNotEqual(replacement["id"], old_method["id"])

    def test_archived_profile_rejects_profile_and_contact_edits(self) -> None:
        tenant = self.tenant_command(
            "create",
            TenantCreateCommand(
                "individual",
                "Inactive Person",
                contacts=(ContactMethodCommand("phone", "5035550199"),),
            ),
        )
        method_id = tenant["contactMethods"][0]["id"]
        self.tenant_command("archive", tenant["id"], confirmed=True)
        with self.assertRaises(TenantConflictError):
            self.tenant_command(
                "update_profile",
                tenant["id"],
                TenantProfilePatchCommand.from_mapping({"notes": "blocked"}),
            )
        updated = self.contact_command(
            "update", tenant["id"], method_id, ContactMethodCommand("phone", "5035550100")
        )
        self.assertEqual(updated["displayValue"], "5035550100")
        self.assertEqual(
            self.contact_command("archive", tenant["id"], method_id, confirmed=True)["status"],
            "archived",
        )

    def test_audit_failure_rolls_back_tenant_creation(self) -> None:
        with patch.object(
            self.tenants.unit_of_work.recorder,
            "record_change",
            side_effect=sqlite3.DatabaseError("audit unavailable"),
        ):
            with self.assertRaises(sqlite3.DatabaseError):
                self.tenant_command("create", TenantCreateCommand("individual", "Not Saved"))
        self.assertEqual(self.tenants.list(), [])

    def test_schema_validation_rejects_unrestricted_contact_uniqueness(self) -> None:
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("DROP INDEX party_contact_methods_one_active_value")
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX party_contact_methods_one_active_value "
                    "ON party_contact_methods(party_id, method_kind, normalized_value)"
                )
            with engine.connect() as connection:
                with self.assertRaises(MigrationSchemaError):
                    validate_tenant_schema(connection)
        finally:
            engine.dispose()

    def test_api_exposes_tenant_activity_with_registered_snapshot_policy(self) -> None:
        config = Path(self.temp.name) / "config.local.json"
        config.write_text(
            json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8"
        )
        with TestClient(create_app(config)) as client:
            created = client.post(
                "/api/tenants",
                json={
                    "partyKind": "individual",
                    "displayName": "Alex Tenant",
                    "expectedRevision": 0,
                    "idempotencyKey": str(uuid4()),
                    "contacts": [{"methodKind": "email", "value": "alex@example.test"}],
                },
            )
            self.assertEqual(created.status_code, 201)
            tenant_id = created.json()["id"]
            self.assertEqual(
                client.get(f"/api/audit/events/tenant_profile/{tenant_id}").status_code, 200
            )
            activity = client.get("/api/audit/events")
            self.assertEqual(activity.status_code, 200)
            contact_event = next(
                item
                for item in activity.json()["events"]
                if item["entityType"] == "party_contact_method"
            )
            self.assertEqual(contact_event["after"]["displayValue"], "[redacted]")
            self.assertEqual(contact_event["after"]["normalizedValue"], "[redacted]")
            contact_history = client.get(
                f"/api/audit/events/party_contact_method/{contact_event['entityId']}"
            )
            self.assertEqual(
                contact_history.json()["events"][0]["after"]["displayValue"], "alex@example.test"
            )
            self.assertEqual(
                contact_history.json()["events"][0]["after"]["normalizedValue"], "alex@example.test"
            )

            patched = client.patch(
                f"/api/tenants/{tenant_id}",
                json={
                    "notes": "Evenings only",
                    "expectedRevision": 1,
                    "idempotencyKey": str(uuid4()),
                },
            )
            self.assertEqual(patched.status_code, 200)
            self.assertFalse(patched.json()["profile"]["doNotContact"])
            cleared = client.patch(
                f"/api/tenants/{tenant_id}",
                json={"notes": None, "expectedRevision": 2, "idempotencyKey": str(uuid4())},
            )
            self.assertIsNone(cleared.json()["profile"]["notes"])
            self.assertEqual(client.patch(f"/api/tenants/{tenant_id}", json={}).status_code, 422)
            self.assertEqual(
                client.post(
                    f"/api/tenants/{tenant_id}/archive", json={"confirmed": "yes"}
                ).status_code,
                422,
            )

            invalid = client.post(
                "/api/tenants",
                json={
                    "partyKind": "individual",
                    "displayName": "   ",
                    "expectedRevision": 0,
                    "idempotencyKey": str(uuid4()),
                },
            )
            self.assertEqual(invalid.status_code, 400)

    def test_profile_patch_commands_validate_direct_construction(self) -> None:
        for values in (
            {},
            {"do_not_contact": "false"},
            {"preferred_contact_method_id": "   "},
            {"notes": "   "},
        ):
            with self.assertRaises(TenantError):
                TenantProfilePatchCommand(**values)

    def test_party_contact_api_supports_non_tenant_parties_and_extensions(self) -> None:
        owner = PortfolioService(
            SQLitePortfolioUnitOfWork(self.workspace.paths.database, AuditRecorder(self.audit)),
            time_zone_resolver=BundledAddressTimeZoneResolver(),
        ).create_party(PartyCreateCommand("organization", "Owner LLC"))
        config = Path(self.temp.name) / "party-api.json"
        config.write_text(
            json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8"
        )
        with TestClient(create_app(config)) as client:
            response = client.post(
                f"/api/parties/{owner.id}/contact-methods",
                json={
                    "methodKind": "phone",
                    "value": "+1 (503) 555-0199 ext. 42",
                    "label": "Leasing",
                    "expectedRevision": 1,
                    "idempotencyKey": str(uuid4()),
                },
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["extension"], "42")
            self.assertEqual(
                client.get(f"/api/parties/{owner.id}/contact-methods").json()[0]["id"],
                response.json()["id"],
            )
            self.assertEqual(
                client.post(
                    f"/api/tenants/{owner.id}/contact-methods",
                    json={
                        "methodKind": "email",
                        "value": "old-route@example.test",
                    },
                ).status_code,
                404,
            )

    def test_party_search_finds_active_owner_by_contact_and_excludes_archived_party(self) -> None:
        owner = PortfolioService(
            SQLitePortfolioUnitOfWork(self.workspace.paths.database, AuditRecorder(self.audit)),
            time_zone_resolver=BundledAddressTimeZoneResolver(),
        ).create_party(PartyCreateCommand("organization", "Searchable Owner"))
        contact_service = PartyContactService(
            SQLitePartyUnitOfWork(self.workspace.paths.database, AuditRecorder(self.audit))
        )
        contact_service.add(
            owner.id,
            ContactMethodCommand("email", "owner-search@example.test"),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
        config = Path(self.temp.name) / "party-search-api.json"
        config.write_text(
            json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8"
        )
        with TestClient(create_app(config)) as client:
            found = client.get(
                "/api/parties",
                params={
                    "activeOnly": "true",
                    "search": "owner-search@example.test",
                },
            )
            self.assertEqual(found.status_code, 200)
            self.assertEqual([item["id"] for item in found.json()], [owner.id])
            self.assertEqual(
                found.json()[0]["contactMethods"][0]["displayValue"],
                "owner-search@example.test",
            )
            self.assertEqual(
                client.post(
                    f"/api/parties/{owner.id}/archive",
                    json={"confirmed": True, "expectedRevision": 2, "idempotencyKey": str(uuid4())},
                ).status_code,
                200,
            )
            self.assertEqual(
                client.get(
                    "/api/parties",
                    params={
                        "activeOnly": "true",
                        "search": "owner-search@example.test",
                    },
                ).json(),
                [],
            )

    def test_tenant_creation_requires_confirmation_for_exact_contact_duplicate(self) -> None:
        config = Path(self.temp.name) / "duplicate-api.json"
        config.write_text(
            json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8"
        )
        payload = {
            "partyKind": "individual",
            "displayName": "First Person",
            "expectedRevision": 0,
            "idempotencyKey": str(uuid4()),
            "contacts": [{"methodKind": "email", "value": "same@example.test"}],
        }
        with TestClient(create_app(config)) as client:
            first = client.post("/api/tenants", json=payload)
            self.assertEqual(first.status_code, 201)
            duplicate = client.post(
                "/api/tenants",
                json={**payload, "displayName": "Second Person", "idempotencyKey": str(uuid4())},
            )
            self.assertEqual(duplicate.status_code, 409)
            self.assertEqual(duplicate.json()["detail"]["code"], "possible_duplicate_party")
            self.assertEqual(duplicate.json()["detail"]["candidatePartyIds"], [first.json()["id"]])
            confirmed = client.post(
                "/api/tenants",
                json={
                    **payload,
                    "displayName": "Second Person",
                    "confirmedNewParty": True,
                    "idempotencyKey": str(uuid4()),
                },
            )
            self.assertEqual(confirmed.status_code, 201)

    def test_active_tenant_role_blocks_shared_party_archival(self) -> None:
        tenant = self.tenant_command("create", TenantCreateCommand("individual", "Active Tenant"))
        config = Path(self.temp.name) / "guard-api.json"
        config.write_text(
            json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8"
        )
        with TestClient(create_app(config)) as client:
            blocked = client.post(
                f"/api/parties/{tenant['id']}/archive",
                json={"confirmed": True, "expectedRevision": 1, "idempotencyKey": str(uuid4())},
            )
            self.assertEqual(blocked.status_code, 409)
        self.assertIsNone(self.tenants.get(tenant["id"])["archivedAt"])

    def test_database_uniqueness_treats_null_extensions_as_equal(self) -> None:
        tenant = self.tenant_command("create", TenantCreateCommand("individual", "Unique Contact"))
        now = "2026-01-01T00:00:00+00:00"
        with sqlite3.connect(self.workspace.paths.database) as connection:
            values = (
                tenant["id"],
                "email",
                "same@example.test",
                "same@example.test",
                "active",
                now,
                now,
            )
            connection.execute(
                "INSERT INTO party_contact_methods "
                "(id, party_id, method_kind, display_value, normalized_value, status, created_at, updated_at) "
                "VALUES ('one', ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO party_contact_methods "
                    "(id, party_id, method_kind, display_value, normalized_value, status, created_at, updated_at) "
                    "VALUES ('two', ?, ?, ?, ?, ?, ?, ?)",
                    values,
                )

    def test_contact_syntax_and_extension_aware_uniqueness(self) -> None:
        for kind, value in (
            ("email", "missing-at.example"),
            ("phone", "1-800-FLOWERS"),
            ("phone", "١٢٣٤٥٦٧"),
            ("phone", "123+4567"),
            ("phone", "+123+4567"),
        ):
            with self.assertRaises(PartyValidationError):
                ContactMethodCommand(kind, value)
        with self.assertRaises(PartyValidationError):
            ContactMethodCommand("phone", "5" + ("-" * 400) + "035550")
        tenant = self.tenant_command(
            "create", TenantCreateCommand("organization", "Shared Switchboard")
        )
        first = self.contact_command(
            "add", tenant["id"], ContactMethodCommand("phone", "503/555/0199 x12")
        )
        second = self.contact_command(
            "add", tenant["id"], ContactMethodCommand("phone", "503-555-0199", extension="13")
        )
        self.assertEqual((first["extension"], second["extension"]), ("12", "13"))
        with self.assertRaises(PartyConflictError):
            self.contact_command(
                "add", tenant["id"], ContactMethodCommand("phone", "5035550199", extension="12")
            )

    def test_party_create_rejects_duplicate_contacts_in_one_request(self) -> None:
        config = Path(self.temp.name) / "party-duplicates.json"
        config.write_text(
            json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8"
        )
        with TestClient(create_app(config)) as client:
            response = client.post(
                "/api/parties",
                json={
                    "partyKind": "individual",
                    "displayName": "Duplicate Contact",
                    "expectedRevision": 0,
                    "idempotencyKey": str(uuid4()),
                    "contacts": [
                        {"methodKind": "phone", "value": "503-555-0199"},
                        {"methodKind": "phone", "value": "(503) 555 0199"},
                    ],
                },
            )
        self.assertEqual(response.status_code, 409)

    def test_feature_adapters_do_not_import_each_others_persistence_models(self) -> None:
        tenant_adapter = Path(__file__).parents[1] / "infrastructure" / "unit_of_work.py"
        lease_adapter = Path(__file__).parents[2] / "leases" / "infrastructure" / "unit_of_work.py"
        self.assertNotIn("leases.infrastructure.sqlalchemy_models", tenant_adapter.read_text())
        self.assertNotIn("parties.infrastructure.sqlalchemy_models", tenant_adapter.read_text())
        self.assertNotIn("tenants.infrastructure.sqlalchemy_models", lease_adapter.read_text())
        self.assertNotIn("portfolio.infrastructure.sqlalchemy_models", lease_adapter.read_text())

    def test_contact_archive_rejects_unknown_and_unused_reference_resolutions(self) -> None:
        owner = PortfolioService(
            SQLitePortfolioUnitOfWork(self.workspace.paths.database, AuditRecorder(self.audit)),
            time_zone_resolver=BundledAddressTimeZoneResolver(),
        ).create_party(PartyCreateCommand("organization", "Resolution Owner"))
        contact = PartyContactService(
            SQLitePartyUnitOfWork(self.workspace.paths.database, AuditRecorder(self.audit))
        ).add(
            owner.id,
            ContactMethodCommand("email", "resolution@example.test"),
            expected_revision=1,
            idempotency_key=str(uuid4()),
        )
        config = Path(self.temp.name) / "resolution-api.json"
        config.write_text(
            json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8"
        )
        with TestClient(create_app(config)) as client:
            unused = client.post(
                f"/api/parties/{owner.id}/contact-methods/{contact['id']}/archive",
                json={
                    "confirmed": True,
                    "expectedRevision": 2,
                    "idempotencyKey": str(uuid4()),
                    "referenceResolutions": [
                        {
                            "role": "tenant",
                            "expectedTenantRevision": 1,
                            "roleRecordId": owner.id,
                            "clear": True,
                        }
                    ],
                },
            )
            self.assertEqual(unused.status_code, 400)
            unknown = client.post(
                f"/api/parties/{owner.id}/contact-methods/{contact['id']}/archive",
                json={
                    "confirmed": True,
                    "expectedRevision": 2,
                    "idempotencyKey": str(uuid4()),
                    "referenceResolutions": [
                        {
                            "role": "vendor",
                            "roleRecordId": owner.id,
                            "clear": True,
                        }
                    ],
                },
            )
            self.assertEqual(unknown.status_code, 400)
        with self.assertRaises(PartyValidationError):
            ContactReferenceResolution("tenant", owner.id, "replacement-id", True)

    def test_baseline_downgrade_removes_party_dependents_in_order(self) -> None:
        database = Path(self.temp.name) / "downgrade.sqlite"
        initialize_latest_schema(database)
        engine = create_sqlite_engine(database)
        try:
            with immediate_transaction(engine) as connection:
                config = alembic_config()
                config.attributes["connection"] = connection
                alembic_command.downgrade(config, "base")
            with sqlite3.connect(database) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            self.assertFalse({"tenant_profiles", "party_contact_methods", "parties"} & tables)
        finally:
            engine.dispose()

    def test_repeated_profile_status_changes_are_conflicts(self) -> None:
        tenant = self.tenant_command(
            "create", TenantCreateCommand("individual", "Lifecycle Tenant")
        )
        self.tenant_command("archive", tenant["id"], confirmed=True)
        with self.assertRaises(TenantConflictError):
            self.tenant_command("archive", tenant["id"], confirmed=True)
        self.tenant_command("restore", tenant["id"])
        with self.assertRaises(TenantConflictError):
            self.tenant_command("restore", tenant["id"])

    @fast_backup_encryption()
    def test_encrypted_backup_export_and_restore_preserve_tenant_data(self) -> None:
        tenant = self.tenant_command(
            "create",
            TenantCreateCommand(
                "individual",
                "Backup Tenant",
                contacts=(
                    ContactMethodCommand("email", "backup@example.test"),
                    ContactMethodCommand("phone", "503-555-0123"),
                ),
                notes="Preferred language recorded locally",
            ),
        )
        email_id = tenant["contactMethods"][0]["id"]
        phone_id = tenant["contactMethods"][1]["id"]
        self.tenant_command(
            "update_profile",
            tenant["id"],
            TenantProfilePatchCommand(
                preferred_contact_method_id=email_id,
                do_not_contact=True,
            ),
        )
        self.contact_command("archive", tenant["id"], phone_id, confirmed=True)
        recorder = AuditRecorder(self.audit)
        backups = BackupService(
            self.workspace,
            recorder,
            lambda database: AuditRecorder(SQLiteAuditRepository(database)),
        )
        passphrase = "tenant backup passphrase"
        backup = backups.create_backup(
            passphrase,
            output_path=Path(self.temp.name) / "tenant-backup",
        )
        exported = backups.create_backup(
            passphrase,
            package_type="export",
            output_path=Path(self.temp.name) / "tenant-export",
        )
        self.assertEqual(
            backups.validate_archive(exported.archive_path, passphrase).manifest["packageType"],
            "export",
        )
        restored_path = Path(self.temp.name) / "restored-tenant-workspace"
        backups.restore(backup.archive_path, passphrase, restored_path)
        restored_audit = SQLiteAuditRepository(
            restored_path / "database" / "property-management.sqlite"
        )
        restored_service = TenantService(
            SQLiteTenantUnitOfWork(
                restored_path / "database" / "property-management.sqlite",
                AuditRecorder(restored_audit),
                SQLiteLeaseParticipationGuard(),
                SQLitePartyOperations(restored_path / "database" / "property-management.sqlite"),
                SQLitePartyReadOperations(
                    SQLitePartyOperations(restored_path / "database" / "property-management.sqlite")
                ),
            ),
            SharedPartyFactory(),
        )
        restored = restored_service.get(tenant["id"])
        self.assertTrue(restored["profile"]["doNotContact"])
        self.assertEqual(restored["profile"]["preferredContactMethodId"], email_id)
        self.assertEqual(restored["contactMethods"][1]["status"], "archived")
        with sqlite3.connect(
            restored_path / "database" / "property-management.sqlite"
        ) as connection:
            normalized = connection.execute(
                "SELECT normalized_value FROM party_contact_methods WHERE id = ?", (phone_id,)
            ).fetchone()[0]
        self.assertEqual(normalized, "5035550123")
        self.assertTrue(restored_audit.history("tenant_profile", tenant["id"]))

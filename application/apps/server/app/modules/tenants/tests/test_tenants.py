from __future__ import annotations

import sqlite3
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.bootstrap.api import create_app

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.parties.application.service import SharedPartyFactory
from app.modules.portfolio.application.service import PartyCreateCommand, PortfolioService
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioUnitOfWork
from app.modules.tenants.application.service import (
    ContactMethodCommand,
    TenantConflictError,
    TenantCreateCommand,
    TenantError,
    TenantProfilePatchCommand,
    TenantService,
)
from app.modules.tenants.infrastructure.unit_of_work import SQLiteTenantUnitOfWork
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.application.backup_service import BackupService
from app.platform.config import LocalConfig
from app.platform.migration_errors import MigrationSchemaError
from app.platform.sqlite_engine import create_sqlite_engine
from app.modules.tenants.infrastructure.schema_validation import validate_tenant_schema
from app.modules.tenants.domain.contact_values import contact_search_terms


class TenantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.workspace = WorkspaceService(LocalConfig(root / "config.json", root / "workspace"))
        self.workspace.initialize()
        self.audit = SQLiteAuditRepository(self.workspace.paths.database)
        self.tenants = TenantService(
            SQLiteTenantUnitOfWork(self.workspace.paths.database, AuditRecorder(self.audit)),
            SharedPartyFactory(),
        )

    def test_creates_profile_contacts_and_audits_them_together(self) -> None:
        tenant = self.tenants.create(TenantCreateCommand(
            "individual", "Robin Renter", contacts=(
                ContactMethodCommand("email", " Robin@Example.Test ", "Home"),
                ContactMethodCommand("phone", "+1 (503) 555-0111"),
            ),
        ))
        self.assertEqual(tenant["profile"]["partyId"], tenant["id"])
        self.assertEqual(tenant["contactMethods"][0]["displayValue"], "Robin@Example.Test")
        events = self.audit.history(correlation_id=self.audit.history("party", tenant["id"])[-1].correlation_id)
        self.assertEqual({item.entity_type for item in events}, {"party", "tenant_profile", "tenant_contact_method"})
        with self.assertRaises(TenantConflictError):
            self.tenants.add_contact(tenant["id"], ContactMethodCommand("email", "robin@example.test"))

    def test_designates_existing_party_and_keeps_identity_when_profile_archives(self) -> None:
        portfolio = PortfolioService(SQLitePortfolioUnitOfWork(self.workspace.paths.database, AuditRecorder(self.audit)))
        party = portfolio.create_party(PartyCreateCommand("individual", "Existing Person", None, None))
        tenant = self.tenants.designate(party.id, notes="Contact after work")
        self.tenants.archive(party.id, confirmed=True)
        archived = self.tenants.get(party.id)
        self.assertIsNone(archived["archivedAt"])
        self.assertIsNotNone(archived["profile"]["archivedAt"])
        self.assertEqual(tenant["id"], party.id)

    def test_preferred_contact_requires_explicit_change_before_archive(self) -> None:
        tenant = self.tenants.create(TenantCreateCommand("individual", "Taylor Tenant", contacts=(
            ContactMethodCommand("email", "taylor@example.test"), ContactMethodCommand("phone", "555 555 0100"),
        )))
        email, phone = tenant["contactMethods"]
        self.tenants.update_profile(tenant["id"], TenantProfilePatchCommand.from_mapping({
            "preferredContactMethodId": email["id"],
        }))
        with self.assertRaises(TenantError):
            self.tenants.archive_contact(tenant["id"], email["id"], confirmed=True)
        self.tenants.archive_contact(tenant["id"], email["id"], confirmed=True, replacement_preferred_contact_method_id=phone["id"])
        self.assertEqual(self.tenants.get(tenant["id"])["profile"]["preferredContactMethodId"], phone["id"])

    def test_searches_contact_values_and_supports_archived_only_listing(self) -> None:
        tenant = self.tenants.create(TenantCreateCommand(
            "individual", "Searchable Person", contacts=(ContactMethodCommand("email", "find-me@example.test"),),
        ))
        self.assertEqual([item["id"] for item in self.tenants.list(search="find-me@example")], [tenant["id"]])
        self.tenants.archive(tenant["id"], confirmed=True)
        self.assertEqual(self.tenants.list(search="find-me@example"), [])
        self.assertEqual([item["id"] for item in self.tenants.list(archive_state="archived")], [tenant["id"]])

    def test_phone_search_uses_canonical_format(self) -> None:
        tenant = self.tenants.create(TenantCreateCommand(
            "individual", "Phone Search", contacts=(ContactMethodCommand("phone", "(503) 555-0100"),),
        ))
        self.assertEqual([item["id"] for item in self.tenants.list(search="503-555")], [tenant["id"]])

    def test_shared_party_contact_values_are_searchable_without_contact_methods(self) -> None:
        tenant = self.tenants.create(TenantCreateCommand(
            "individual", "Shared Contact", "shared@example.test", "503/555/0199",
        ))
        self.assertEqual([item["id"] for item in self.tenants.list(search="shared@example")], [tenant["id"]])
        self.assertEqual([item["id"] for item in self.tenants.list(search="5035550199")], [tenant["id"]])

    def test_alphanumeric_search_does_not_broaden_to_digits_only_phone_matches(self) -> None:
        expected = self.tenants.create(TenantCreateCommand(
            "individual", "Unit Contact", contacts=(ContactMethodCommand("email", "unit1@example.test"),),
        ))
        self.tenants.create(TenantCreateCommand(
            "individual", "Unrelated Phone", contacts=(ContactMethodCommand("phone", "555-000-0001"),),
        ))
        self.assertEqual([item["id"] for item in self.tenants.list(search="unit1@example.test")], [expected["id"]])

    def test_unicode_text_and_like_metacharacters_are_literal_searches(self) -> None:
        expected = self.tenants.create(TenantCreateCommand(
            "individual", "租客1", contacts=(ContactMethodCommand("email", "unit_one@example.test"),),
        ))
        self.tenants.create(TenantCreateCommand(
            "individual", "Unrelated", contacts=(ContactMethodCommand("phone", "555-000-0001"),),
        ))
        literal_percent = self.tenants.create(TenantCreateCommand("individual", "100% Reliable"))
        self.assertEqual([item["id"] for item in self.tenants.list(search="租客1")], [expected["id"]])
        self.assertEqual([item["id"] for item in self.tenants.list(search="unit_one@example.test")], [expected["id"]])
        self.assertEqual([item["id"] for item in self.tenants.list(search="%")], [literal_percent["id"]])
        self.assertEqual(contact_search_terms("#1"), ("#1",))

    def test_archived_contact_value_can_be_added_again(self) -> None:
        tenant = self.tenants.create(TenantCreateCommand(
            "individual", "Reuse Contact", contacts=(ContactMethodCommand("email", "reuse@example.test"),),
        ))
        old_method = tenant["contactMethods"][0]
        self.tenants.archive_contact(tenant["id"], old_method["id"], confirmed=True)
        replacement = self.tenants.add_contact(tenant["id"], ContactMethodCommand("email", "REUSE@example.test"))
        self.assertNotEqual(replacement.id, old_method["id"])

    def test_archived_profile_rejects_profile_and_contact_edits(self) -> None:
        tenant = self.tenants.create(TenantCreateCommand(
            "individual", "Inactive Person", contacts=(ContactMethodCommand("phone", "5035550199"),),
        ))
        method_id = tenant["contactMethods"][0]["id"]
        self.tenants.archive(tenant["id"], confirmed=True)
        with self.assertRaises(TenantConflictError):
            self.tenants.update_profile(tenant["id"], TenantProfilePatchCommand.from_mapping({"notes": "blocked"}))
        with self.assertRaises(TenantConflictError):
            self.tenants.update_contact(tenant["id"], method_id, ContactMethodCommand("phone", "5035550100"))
        with self.assertRaises(TenantConflictError):
            self.tenants.archive_contact(tenant["id"], method_id, confirmed=True)

    def test_audit_failure_rolls_back_tenant_creation(self) -> None:
        with patch.object(self.tenants.unit_of_work.recorder, "record_change", side_effect=sqlite3.DatabaseError("audit unavailable")):
            with self.assertRaises(sqlite3.DatabaseError):
                self.tenants.create(TenantCreateCommand("individual", "Not Saved"))
        self.assertEqual(self.tenants.list(), [])

    def test_schema_validation_rejects_unrestricted_contact_uniqueness(self) -> None:
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("DROP INDEX tenant_contact_methods_one_active_value")
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX tenant_contact_methods_one_active_value "
                    "ON tenant_contact_methods(party_id, method_kind, normalized_value)"
                )
            with engine.connect() as connection:
                with self.assertRaises(MigrationSchemaError):
                    validate_tenant_schema(connection)
        finally:
            engine.dispose()

    def test_api_exposes_tenant_activity_with_registered_snapshot_policy(self) -> None:
        config = Path(self.temp.name) / "config.local.json"
        config.write_text(json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8")
        with TestClient(create_app(config)) as client:
            created = client.post("/api/tenants", json={
                "partyKind": "individual",
                "displayName": "Alex Tenant",
                "email": "alex-party@example.test",
                "contacts": [{"methodKind": "email", "value": "alex@example.test"}],
            })
            self.assertEqual(created.status_code, 201)
            tenant_id = created.json()["id"]
            self.assertEqual(client.get(f"/api/audit/events/tenant_profile/{tenant_id}").status_code, 200)
            activity = client.get("/api/audit/events")
            self.assertEqual(activity.status_code, 200)
            contact_event = next(item for item in activity.json()["events"] if item["entityType"] == "tenant_contact_method")
            self.assertEqual(contact_event["after"]["displayValue"], "[redacted]")
            self.assertEqual(contact_event["after"]["normalizedValue"], "[redacted]")
            contact_history = client.get(f"/api/audit/events/tenant_contact_method/{contact_event['entityId']}")
            self.assertEqual(contact_history.json()["events"][0]["after"]["displayValue"], "alex@example.test")
            self.assertEqual(contact_history.json()["events"][0]["after"]["normalizedValue"], "alex@example.test")
            party_event = next(item for item in activity.json()["events"] if item["entityType"] == "party")
            self.assertEqual(party_event["after"]["email"], "[redacted]")
            party_history = client.get(f"/api/audit/events/party/{tenant_id}")
            self.assertEqual(party_history.json()["events"][0]["after"]["email"], "alex-party@example.test")

            patched = client.patch(f"/api/tenants/{tenant_id}", json={"notes": "Evenings only"})
            self.assertEqual(patched.status_code, 200)
            self.assertFalse(patched.json()["profile"]["doNotContact"])
            cleared = client.patch(f"/api/tenants/{tenant_id}", json={"notes": None})
            self.assertIsNone(cleared.json()["profile"]["notes"])
            self.assertEqual(client.patch(f"/api/tenants/{tenant_id}", json={}).status_code, 400)
            self.assertEqual(client.post(f"/api/tenants/{tenant_id}/archive", json={"confirmed": "yes"}).status_code, 422)

            invalid = client.post("/api/tenants", json={"partyKind": "individual", "displayName": "   "})
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

    def test_repeated_profile_status_changes_are_conflicts(self) -> None:
        tenant = self.tenants.create(TenantCreateCommand("individual", "Lifecycle Tenant"))
        self.tenants.archive(tenant["id"], confirmed=True)
        with self.assertRaises(TenantConflictError):
            self.tenants.archive(tenant["id"], confirmed=True)
        self.tenants.restore(tenant["id"])
        with self.assertRaises(TenantConflictError):
            self.tenants.restore(tenant["id"])

    def test_encrypted_backup_export_and_restore_preserve_tenant_data(self) -> None:
        tenant = self.tenants.create(TenantCreateCommand(
            "individual", "Backup Tenant", contacts=(
                ContactMethodCommand("email", "backup@example.test"),
                ContactMethodCommand("phone", "503-555-0123"),
            ), notes="Preferred language recorded locally",
        ))
        email_id = tenant["contactMethods"][0]["id"]
        phone_id = tenant["contactMethods"][1]["id"]
        self.tenants.update_profile(tenant["id"], TenantProfilePatchCommand(
            preferred_contact_method_id=email_id,
            do_not_contact=True,
        ))
        self.tenants.archive_contact(tenant["id"], phone_id, confirmed=True)
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
        self.assertEqual(backups.validate_archive(exported.archive_path, passphrase).manifest["packageType"], "export")
        restored_path = Path(self.temp.name) / "restored-tenant-workspace"
        backups.restore(backup.archive_path, passphrase, restored_path)
        restored_audit = SQLiteAuditRepository(restored_path / "database" / "property-management.sqlite")
        restored_service = TenantService(
            SQLiteTenantUnitOfWork(restored_path / "database" / "property-management.sqlite", AuditRecorder(restored_audit)),
            SharedPartyFactory(),
        )
        restored = restored_service.get(tenant["id"])
        self.assertTrue(restored["profile"]["doNotContact"])
        self.assertEqual(restored["profile"]["preferredContactMethodId"], email_id)
        self.assertEqual(restored["contactMethods"][1]["status"], "archived")
        with sqlite3.connect(restored_path / "database" / "property-management.sqlite") as connection:
            normalized = connection.execute(
                "SELECT normalized_value FROM tenant_contact_methods WHERE id = ?", (phone_id,)
            ).fetchone()[0]
        self.assertEqual(normalized, "5035550123")
        self.assertTrue(restored_audit.history("tenant_profile", tenant["id"]))

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.parties.application.service import PartyCreateCommand, SharedPartyFactory
from app.modules.parties.infrastructure.unit_of_work import SQLitePartyOperations
from app.modules.portfolio.application.service import OwnershipInput, PortfolioService, PropertyCreateCommand
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioLeaseOperations, SQLitePortfolioUnitOfWork
from app.modules.vendors.application.service import (
    ProviderLifecycleConflict, ProviderProfileCommand, ProviderService, ServiceAreaCommand,
    ProviderError, ProviderSearchCommand, ServiceCommand, WorkHistoryCommand, ReferenceCommand,
)
from app.modules.vendors.infrastructure.unit_of_work import SQLiteProviderUnitOfWork
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.application.backup_service import BackupService
from app.modules.vendors.infrastructure.schema_validation import validate_vendor_schema
from app.platform.migration_errors import MigrationSchemaError
from app.platform.sqlite_engine import create_sqlite_engine
from app.platform.config import LocalConfig


class ProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = root / "config.json"
        self.workspace = WorkspaceService(LocalConfig(self.config, root / "workspace"))
        self.workspace.initialize()
        self.config.write_text(json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8")
        audit = SQLiteAuditRepository(self.workspace.paths.database)
        self.recorder = AuditRecorder(audit)
        self.providers = ProviderService(SQLiteProviderUnitOfWork(
            self.workspace.paths.database, self.recorder,
            SQLitePartyOperations(self.workspace.paths.database),
            SQLitePortfolioLeaseOperations(self.workspace.paths.database),
        ))
        self.portfolio = PortfolioService(SQLitePortfolioUnitOfWork(self.workspace.paths.database, self.recorder))

    def test_provider_lifecycle_labels_search_and_audit(self) -> None:
        created = self.providers.create(
            PartyCreateCommand("organization", "Northwest Plumbing"),
            ProviderProfileCommand("preferred", notes="Local operator shortlist"),
        )
        party_id = created["party"]["id"]
        created = self.providers.add_service(party_id, ServiceCommand("Plumbing"))
        self.assertEqual(created["services"][0]["normalizedName"], "plumbing")
        with self.assertRaises(ProviderLifecycleConflict):
            self.providers.add_service(party_id, ServiceCommand(" plumbing "))
        self.providers.add_area(party_id, ServiceAreaCommand("Portland Metro", "us"))
        property_id = self.portfolio.create_property(PropertyCreateCommand(
            "Provider test home", "1 Main", "Portland", "US", "single_family_home", (OwnershipInput("local_operator"),),
        )).id
        self.providers.add_work_history(party_id, WorkHistoryCommand("2025-01-01", "Repaired a fixture", property_id))
        self.assertEqual([item["party"]["id"] for item in self.providers.list(ProviderSearchCommand(
            archive_state="active", search="fixture", service=None, service_area=None,
            selection_status="preferred", property_id=property_id, has_reference=False,
        ))], [party_id])
        self.assertEqual(ProviderSearchCommand(service="  \uff25lectrical  ").service, "electrical")
        with self.assertRaises(ProviderError):
            ProviderSearchCommand(archive_state="invalid")
        events = self.recorder.repository.history("provider_profile", party_id)
        self.assertTrue(events)

    def test_provider_http_contract_and_party_route(self) -> None:
        with TestClient(create_app(self.config)) as client:
            response = client.post("/api/providers", json={
                "party": {"partyKind": "individual", "displayName": "Casey Contractor"},
                "contacts": [{"methodKind": "phone", "value": "503-555-0100"}],
                "services": [{"displayName": "Electrical"}],
                "selectionStatus": "avoid", "selectionReason": "Not a current fit",
            })
            self.assertEqual(response.status_code, 201)
            party_id = response.json()["party"]["id"]
            self.assertEqual(response.json()["services"][0]["displayName"], "Electrical")
            self.assertEqual([item["party"]["id"] for item in client.get("/api/providers").json()], [party_id])
            self.assertEqual(client.get(f"/api/providers/{party_id}").status_code, 200)
            self.assertEqual(client.get(f"/api/parties/{party_id}").json()["activeRoles"], ["provider"])
            listed = client.get("/api/providers", params={"service": "  \uff25lectrical  "})
            self.assertEqual(listed.status_code, 200)
            self.assertEqual([item["party"]["id"] for item in listed.json()], [party_id])
            service = client.post(f"/api/providers/{party_id}/services", json={"displayName": "Appliance repair"})
            self.assertEqual(service.status_code, 201)
            self.assertEqual(len(service.json()["services"]), 2)
            listed = client.get("/api/providers", params={"service": "  \uff25lectrical  "})
            self.assertEqual(listed.status_code, 200)
            self.assertEqual([item["party"]["id"] for item in listed.json()], [party_id])
            patched = client.patch(f"/api/providers/{party_id}", json={"notes": "Only the notes changed"})
            self.assertEqual(patched.status_code, 200)
            self.assertEqual(patched.json()["profile"]["selectionStatus"], "avoid")
            self.assertEqual(patched.json()["profile"]["selectionReason"], "Not a current fit")
            cleared = client.patch(f"/api/providers/{party_id}", json={"selectionStatus": "neutral", "selectionReason": None})
            self.assertEqual(cleared.status_code, 200)
            self.assertIsNone(cleared.json()["profile"]["selectionReason"])
            self.assertEqual(client.patch(f"/api/providers/{party_id}", json={"selectionStatus": None}).status_code, 422)
            self.assertEqual(client.get("/api/parties", params={"search": "Casey"}).status_code, 200)
            duplicate = client.post("/api/parties", json={
                "partyKind": "individual", "displayName": "Another Casey",
                "contacts": [{"methodKind": "phone", "value": "5035550100"}],
            })
            self.assertEqual(duplicate.status_code, 409)
            self.assertEqual(duplicate.json()["detail"]["code"], "possible_duplicate_party")
            self.assertEqual(client.post("/api/parties", json={
                "partyKind": "individual", "displayName": "Confirmed Casey",
                "contacts": [{"methodKind": "phone", "value": "5035550100"}],
                "confirmedNewParty": True,
            }).status_code, 201)
            self.assertEqual(client.post(f"/api/parties/{party_id}/archive", json={"confirmed": True}).status_code, 409)
            self.assertEqual(client.post(f"/api/providers/{party_id}/archive", json={"confirmed": True}).status_code, 200)

    def test_encrypted_backup_restore_preserves_provider_history(self) -> None:
        provider = self.providers.create(
            PartyCreateCommand("organization", "Restorable Provider"),
            ProviderProfileCommand("avoid", "Operator decision", "Internal context"),
        )
        party_id = provider["party"]["id"]
        self.providers.add_service(party_id, ServiceCommand("Electrical"))
        self.providers.add_area(party_id, ServiceAreaCommand("Portland Metro", "US"))
        self.providers.add_work_history(party_id, WorkHistoryCommand("2025-03-01", "Historical rewiring"))
        self.providers.add_reference(party_id, ReferenceCommand(reference_name="Reference", notes="Private note"))
        backups = BackupService(self.workspace, self.recorder, lambda database: AuditRecorder(SQLiteAuditRepository(database)))
        archive = backups.create_backup("provider backup passphrase", output_path=Path(self.temp.name) / "provider-backup")
        restored_path = Path(self.temp.name) / "restored-provider"
        backups.restore(archive.archive_path, "provider backup passphrase", restored_path)
        audit = SQLiteAuditRepository(restored_path / "database" / "property-management.sqlite")
        service = ProviderService(SQLiteProviderUnitOfWork(
            restored_path / "database" / "property-management.sqlite", AuditRecorder(audit),
            SQLitePartyOperations(restored_path / "database" / "property-management.sqlite"),
            SQLitePortfolioLeaseOperations(restored_path / "database" / "property-management.sqlite"),
        ))
        restored = service.detail(party_id, include_archived=True)
        self.assertEqual(restored["services"][0]["displayName"], "Electrical")
        self.assertEqual(restored["references"][0]["referenceName"], "Reference")
        self.assertTrue(audit.history("provider_profile", party_id))

    def test_initial_records_are_atomic_and_correlated(self) -> None:
        created = self.providers.create(
            PartyCreateCommand("organization", "Atomic Provider"), ProviderProfileCommand(),
            services=(ServiceCommand("Painting"),), areas=(ServiceAreaCommand("Portland", "US"),),
            work_history=(WorkHistoryCommand("2025-01-01", "Prior painting"),),
            references=(ReferenceCommand(reference_name="A Reference"),),
        )
        party_id = created["party"]["id"]
        self.assertEqual((len(created["services"]), len(created["serviceAreas"]), len(created["workHistory"]), len(created["references"])), (1, 1, 1, 1))
        events = SQLiteAuditRepository(self.workspace.paths.database).history(correlation_id=SQLiteAuditRepository(self.workspace.paths.database).history("provider_profile", party_id)[0].correlation_id)
        self.assertEqual({event.entity_type for event in events}, {"party", "provider_profile", "provider_service", "provider_service_area", "provider_work_history", "provider_reference"})

    def test_avoid_constraint_and_exact_schema_validation_fail_closed(self) -> None:
        with sqlite3.connect(self.workspace.paths.database) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO parties (id, party_kind, display_name, created_at, updated_at) VALUES ('party', 'individual', 'One', 'now', 'now')")
                connection.execute("INSERT INTO provider_profiles (party_id, selection_status, selection_reason, created_at, updated_at) VALUES ('party', 'avoid', NULL, 'now', 'now')")
        with sqlite3.connect(self.workspace.paths.database) as connection:
            connection.execute("INSERT INTO parties (id, party_kind, display_name, created_at, updated_at) VALUES ('vendor', 'individual', 'Vendor', 'now', 'now')")
            connection.execute("INSERT INTO provider_profiles (party_id, selection_status, created_at, updated_at) VALUES ('vendor', 'neutral', 'now', 'now')")
            for country_code in ("11", "\u00c5A"):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("INSERT INTO provider_service_areas (id, party_id, display_name, normalized_name, country_code, created_at, updated_at) VALUES (?, 'vendor', 'Area', 'area', ?, 'now', 'now')", (country_code, country_code))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO provider_references (id, party_id, reference_name, created_at, updated_at) VALUES ('blank-reference', 'vendor', '   ', 'now', 'now')")
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("DROP INDEX provider_services_one_active_name")
                connection.exec_driver_sql("CREATE INDEX provider_services_one_active_name ON provider_services(id)")
            with engine.connect() as connection:
                with self.assertRaises(MigrationSchemaError):
                    validate_vendor_schema(connection)
        finally:
            engine.dispose()

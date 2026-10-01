from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import event

from fastapi.testclient import TestClient

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.parties.application.service import PartyCreateCommand, SharedPartyFactory
from app.modules.parties.infrastructure.unit_of_work import SQLitePartyOperations
from app.modules.portfolio.application.service import OwnershipInput, PortfolioService, PropertyCreateCommand
from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioLeaseOperations, SQLitePortfolioUnitOfWork
from app.modules.vendors.application.service import (
    ProviderError,
    ProviderLifecycleConflict,
    ProviderProfileCommand,
    ProviderSearchCommand,
    ProviderService,
    ProviderCategoryCommand,
    ProviderCategoryPatchCommand,
    ProviderCategoryAssignmentCommand,
    ReferenceCommand,
    ReputationLinkCommand,
    ReputationLinkPatchCommand,
    ServiceAreaCommand,
    ServiceCommand,
    WorkHistoryCommand,
)
from app.modules.vendors.infrastructure.schema_validation import validate_vendor_data, validate_vendor_schema
from app.modules.vendors.infrastructure.unit_of_work import SQLiteProviderUnitOfWork
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.tests.fast_encryption import fast_backup_encryption
from app.platform.config import LocalConfig
from app.platform.migration_errors import MigrationSchemaError
from app.platform.sqlite_engine import create_sqlite_engine


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
        self.portfolio = PortfolioService(
            SQLitePortfolioUnitOfWork(self.workspace.paths.database, self.recorder),
            time_zone_resolver=BundledAddressTimeZoneResolver(),
        )

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
            "Provider test home", "1 Main", "Portland", "US", "single_family_home", (OwnershipInput("local_operator"),), region="OR",
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

    def test_category_catalog_assignment_lifecycle_and_idempotency(self) -> None:
        seeded = self.providers.list_categories()
        self.assertEqual([item["displayName"] for item in seeded], [
            "Legal / Attorney", "Landscaping", "Electrical", "HVAC / A/C",
            "Appliance repair", "Plumbing", "General maintenance",
        ])
        command = ProviderCategoryCommand(
            "  Specialty Restoration ", 8, "00000000-0000-4000-8000-000000000901", "Water and fire work",
        )
        category = self.providers.create_category(command)
        self.assertEqual(self.providers.create_category(command)["id"], category["id"])
        party_id = self.providers.create(
            PartyCreateCommand("organization", "Category Provider"), ProviderProfileCommand(),
            category_ids=(category["id"],),
        )["party"]["id"]
        self.assertEqual(self.providers.detail(party_id)["categories"][0]["id"], category["id"])
        self.assertEqual(self.providers.list(ProviderSearchCommand(category_id=category["id"]))[0]["party"]["id"], party_id)
        assignment = self.providers.detail(party_id)["categories"][0]["assignmentId"]
        archived = self.providers.archive_category_assignment(party_id, assignment, confirmed=True, reason="Incorrect classification")
        self.assertEqual(archived["categories"][0]["assignmentArchivedAt"] is not None, True)
        self.assertEqual(self.providers.list(ProviderSearchCommand(category_state="uncategorized"))[0]["party"]["id"], party_id)
        restored = self.providers.restore_category_assignment(party_id, assignment, confirmed=True)
        self.assertIsNone(restored["categories"][0]["assignmentArchivedAt"])
        assigned = self.providers.assign_category(
            party_id, ProviderCategoryAssignmentCommand(
                seeded[0]["id"], "00000000-0000-4000-8000-000000000902",
            ),
        )
        self.assertEqual(len(assigned["categories"]), 2)
        self.workspace.open()

    def test_category_normalization_collapses_unicode_whitespace(self) -> None:
        category = self.providers.create_category(ProviderCategoryCommand(
            "  Specialty\u00a0 /\tRestoration  ", 8,
            "00000000-0000-4000-8000-000000000922",
        ))
        self.assertEqual(category["normalizedName"], "specialty / restoration")
        self.assertEqual(
            [item["id"] for item in self.providers.list_categories(search="Specialty  /  Restoration")],
            [category["id"]],
        )
        with self.assertRaises(ProviderLifecycleConflict):
            self.providers.create_category(ProviderCategoryCommand(
                "Specialty  /  Restoration", 9,
                "00000000-0000-4000-8000-000000000923",
            ))
        with create_sqlite_engine(self.workspace.paths.database).begin() as connection:
            connection.exec_driver_sql(
                "UPDATE provider_categories SET normalized_name = ? WHERE id = ?",
                ("specialty  / restoration", category["id"]),
            )
        with create_sqlite_engine(self.workspace.paths.database).connect() as connection:
            with self.assertRaises(MigrationSchemaError):
                validate_vendor_data(connection)

    def test_category_patch_noop_and_archive_retries_preserve_reason(self) -> None:
        category = self.providers.create_category(ProviderCategoryCommand(
            "Category lifecycle", 8, "00000000-0000-4000-8000-000000000921",
        ))
        category_id = category["id"]
        events_before = len(self.recorder.repository.history("provider_category", category_id))
        unchanged = self.providers.update_category(category_id, ProviderCategoryPatchCommand(
            display_name="Category lifecycle",
        ))
        self.assertEqual(unchanged["updatedAt"], category["updatedAt"])
        self.assertEqual(len(self.recorder.repository.history("provider_category", category_id)), events_before)

        archived = self.providers.archive_category(category_id, confirmed=True, reason="Retired")
        events_after_archive = len(self.recorder.repository.history("provider_category", category_id))
        self.assertEqual(
            self.providers.archive_category(category_id, confirmed=True, reason="Retired"),
            archived,
        )
        self.assertEqual(len(self.recorder.repository.history("provider_category", category_id)), events_after_archive)
        with self.assertRaises(ProviderLifecycleConflict):
            self.providers.archive_category(category_id, confirmed=True, reason="Different reason")

        party_id = self.providers.create(
            PartyCreateCommand("organization", "Category retry provider"), ProviderProfileCommand(),
            category_ids=(self.providers.list_categories()[0]["id"],),
        )["party"]["id"]
        assignment_id = self.providers.detail(party_id)["categories"][0]["assignmentId"]
        self.providers.archive_category_assignment(party_id, assignment_id, confirmed=True, reason="Not offered")
        self.providers.archive_category_assignment(party_id, assignment_id, confirmed=True, reason="Not offered")
        with self.assertRaises(ProviderLifecycleConflict):
            self.providers.archive_category_assignment(party_id, assignment_id, confirmed=True, reason="Different reason")

    def test_category_http_contract_and_provider_page(self) -> None:
        with TestClient(create_app(self.config)) as client:
            catalog = client.get("/api/provider-categories")
            self.assertEqual(catalog.status_code, 200)
            self.assertEqual(len(catalog.json()), 7)
            created = client.post("/api/provider-categories", json={
                "displayName": "Roofing", "description": "Roof repairs", "displayOrder": 9,
                "idempotencyKey": "00000000-0000-4000-8000-000000000911",
            })
            self.assertEqual(created.status_code, 201)
            category_id = created.json()["id"]
            replay = client.post("/api/provider-categories", json={
                "displayName": "Roofing", "description": "Roof repairs", "displayOrder": 9,
                "idempotencyKey": "00000000-0000-4000-8000-000000000911",
            })
            self.assertEqual(replay.json()["id"], category_id)
            provider = client.post("/api/providers", json={
                "party": {"partyKind": "organization", "displayName": "Roofing Co."},
                "categoryIds": [category_id],
            })
            self.assertEqual(provider.status_code, 201)
            party_id = provider.json()["party"]["id"]
            page = client.get("/api/providers", params={"categoryId": category_id, "limit": 1})
            self.assertEqual(page.status_code, 200)
            self.assertEqual(page.json()["items"][0]["party"]["id"], party_id)
            self.assertEqual(page.json()["items"][0]["categories"][0]["displayName"], "Roofing")
            assignment_id = provider.json()["categories"][0]["assignmentId"]
            archived = client.post(f"/api/providers/{party_id}/category-assignments/{assignment_id}/archive", json={"confirmed": True, "reason": "Not offered"})
            self.assertEqual(archived.status_code, 200)
            self.assertEqual(client.get("/api/providers", params={"categoryState": "uncategorized"}).json()["items"][0]["party"]["id"], party_id)

    def test_provider_page_selects_ids_with_filters_cursor_and_limit_before_hydration(self) -> None:
        party_ids = []
        for name in ("Alpha Electric", "Bravo Plumbing", "Charlie HVAC"):
            party_ids.append(self.providers.create(
                PartyCreateCommand("organization", name), ProviderProfileCommand(),
            )["party"]["id"])
        statements: list[str] = []
        listener = lambda _connection, _cursor, statement, _parameters, _context, _many: statements.append(statement)
        event.listen(self.providers.unit_of_work.engine, "before_cursor_execute", listener)
        try:
            first = self.providers.page(ProviderSearchCommand(limit=1))
            second = self.providers.page(ProviderSearchCommand(limit=1, cursor=first["nextCursor"]))
            third = self.providers.page(ProviderSearchCommand(limit=1, cursor=second["nextCursor"]))
        finally:
            event.remove(self.providers.unit_of_work.engine, "before_cursor_execute", listener)
        self.assertEqual(
            [first["items"][0]["party"]["id"], second["items"][0]["party"]["id"], third["items"][0]["party"]["id"]],
            party_ids,
        )
        selection = next(statement for statement in statements if "FROM provider_profiles pp JOIN parties p" in statement)
        self.assertIn("LIMIT ?", selection)
        self.assertIn("unicode_casefold(p.display_name)", selection)

    def test_unicode_cursor_and_query_budget_remain_stable_for_page_sizes(self) -> None:
        with sqlite3.connect(self.workspace.paths.database) as connection:
            stamp = "2026-10-01T00:00:00+00:00"
            rows = []
            for index in range(200):
                party_id = str(uuid4())
                rows.append((party_id, "organization", f"Provider {index:03d}", stamp, stamp))
            for name in ("Éclair A", "Éclair B"):
                party_id = str(uuid4())
                rows.append((party_id, "organization", name, stamp, stamp))
            connection.executemany(
                "INSERT INTO parties (id, party_kind, display_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            connection.executemany(
                "INSERT INTO provider_profiles (party_id, selection_status, created_at, updated_at) VALUES (?, 'neutral', ?, ?)",
                [(row[0], stamp, stamp) for row in rows],
            )

        def page_query_count(limit: int) -> tuple[dict[str, object], int]:
            statements: list[str] = []
            listener = lambda _connection, _cursor, statement, _parameters, _context, _many: statements.append(statement)
            event.listen(self.providers.unit_of_work.engine, "before_cursor_execute", listener)
            try:
                page = self.providers.page(ProviderSearchCommand(limit=limit))
            finally:
                event.remove(self.providers.unit_of_work.engine, "before_cursor_execute", listener)
            return page, len(statements)

        one, one_count = page_query_count(1)
        hundred, hundred_count = page_query_count(100)
        two_hundred, two_hundred_count = page_query_count(200)
        self.assertEqual((len(one["items"]), len(hundred["items"]), len(two_hundred["items"])), (1, 100, 200))
        self.assertEqual((one_count, hundred_count, two_hundred_count), (one_count, one_count, one_count))

        first = self.providers.page(ProviderSearchCommand(search="ÉCLAIR", limit=1))
        second = self.providers.page(ProviderSearchCommand(search="ÉCLAIR", limit=1, cursor=first["nextCursor"]))
        self.assertEqual(
            [first["items"][0]["party"]["displayName"], second["items"][0]["party"]["displayName"]],
            ["Éclair A", "Éclair B"],
        )

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
            self.assertEqual([item["party"]["id"] for item in client.get("/api/providers").json()["items"]], [party_id])
            self.assertEqual(client.get(f"/api/providers/{party_id}").status_code, 200)
            self.assertEqual(client.get(f"/api/parties/{party_id}").json()["activeRoles"], ["provider"])
            listed = client.get("/api/providers", params={"service": "  \uff25lectrical  "})
            self.assertEqual(listed.status_code, 200)
            self.assertEqual([item["party"]["id"] for item in listed.json()["items"]], [party_id])
            service = client.post(f"/api/providers/{party_id}/services", json={"displayName": "Appliance repair"})
            self.assertEqual(service.status_code, 201)
            self.assertEqual(len(service.json()["services"]), 2)
            listed = client.get("/api/providers", params={"service": "  \uff25lectrical  "})
            self.assertEqual(listed.status_code, 200)
            self.assertEqual([item["party"]["id"] for item in listed.json()["items"]], [party_id])
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

    @fast_backup_encryption()
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
        reputation = self.providers.add_reputation_link(party_id, ReputationLinkCommand(
            "google", "https://GOOGLE.example:443/provider?id=123", notes="Private reputation note",
            last_checked_on="2025-03-02",
        ))
        reputation_link_id = reputation["reputationLinks"][0]["id"]
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
        self.assertEqual(restored["reputationLinks"][0]["url"], "https://google.example/provider?id=123")
        self.assertTrue(audit.history("provider_reputation_link", reputation_link_id))
        self.assertTrue(audit.history("provider_profile", party_id))

    def test_reputation_command_canonicalization_and_validation(self) -> None:
        item = ReputationLinkCommand(
            "other", " HTTPS://Example.COM:443/reviews/path?listing=1 ",
            "  Better Business Bureau  ", "  Manually checked  ", "2025-01-02",
        )
        self.assertEqual(item.source_name, "Better Business Bureau")
        self.assertEqual(item.normalized_source_key, "better business bureau")
        self.assertEqual(item.url, "https://example.com/reviews/path?listing=1")
        for arguments in (
            ("google", "https://example.com", "Unexpected name"),
            ("other", "https://example.com", None),
            ("google", "http://example.com", None),
            ("google", "https://user@example.com", None),
            ("google", "https://example.com/path#fragment", None),
            ("google", "relative/path", None),
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ProviderError):
                ReputationLinkCommand(arguments[0], arguments[1], arguments[2])
        with self.assertRaises(ProviderError):
            ReputationLinkCommand(
                "google", "https://example.com",
                last_checked_on=(date.today() + timedelta(days=1)).isoformat(),
            )

    def test_reputation_link_lifecycle_uniqueness_noop_and_atomic_audit(self) -> None:
        party_id = self.providers.create(
            PartyCreateCommand("organization", "Reputation Provider"), ProviderProfileCommand(),
        )["party"]["id"]
        created = self.providers.add_reputation_link(
            party_id, ReputationLinkCommand("google", "https://Example.com:443/reviews", notes="Private"),
        )
        link_id = created["reputationLinks"][0]["id"]
        self.assertEqual(created["reputationLinks"][0]["url"], "https://example.com/reviews")
        self.assertEqual(self.providers.list(ProviderSearchCommand())[0]["reputationLinkCount"], 1)
        with self.assertRaises(ProviderLifecycleConflict):
            self.providers.add_reputation_link(party_id, ReputationLinkCommand("google", "https://other.example/reviews"))
        with self.assertRaises(ProviderLifecycleConflict):
            self.providers.add_reputation_link(party_id, ReputationLinkCommand("yelp", "https://example.com/reviews"))

        before_events = len(self.recorder.repository.history("provider_reputation_link", link_id))
        unchanged = self.providers.update_reputation_link(party_id, link_id, ReputationLinkPatchCommand())
        self.assertEqual(len(self.recorder.repository.history("provider_reputation_link", link_id)), before_events)
        self.assertEqual(unchanged["reputationLinks"][0]["notes"], "Private")
        updated = self.providers.update_reputation_link(
            party_id, link_id, ReputationLinkPatchCommand(notes=None, last_checked_on="2025-04-01"),
        )
        self.assertIsNone(updated["reputationLinks"][0]["notes"])

        archived = self.providers.archive_reputation_link(party_id, link_id, confirmed=True)
        self.assertIsNotNone(archived["reputationLinks"][0]["archivedAt"])
        self.assertEqual(self.providers.detail(party_id)["reputationLinks"], [])
        replacement = self.providers.add_reputation_link(
            party_id, ReputationLinkCommand("google", "https://replacement.example/reviews"),
        )
        replacement_id = replacement["reputationLinks"][0]["id"]
        with self.assertRaises(ProviderLifecycleConflict):
            self.providers.restore_reputation_link(party_id, link_id)
        self.providers.archive_reputation_link(party_id, replacement_id, confirmed=True)
        restored = self.providers.restore_reputation_link(party_id, link_id)
        self.assertIsNone(restored["reputationLinks"][0]["archivedAt"])

        with patch.object(self.providers.unit_of_work.recorder, "record_change", side_effect=sqlite3.DatabaseError("audit unavailable")):
            with self.assertRaises(sqlite3.DatabaseError):
                self.providers.add_reputation_link(
                    party_id, ReputationLinkCommand("yelp", "https://yelp.example/reviews"),
                )
        self.assertEqual(len(self.providers.detail(party_id)["reputationLinks"]), 1)

    def test_reputation_http_contract_and_activity_redaction(self) -> None:
        with TestClient(create_app(self.config)) as client:
            provider = client.post("/api/providers", json={
                "party": {"partyKind": "organization", "displayName": "HTTP Reputation"},
            }).json()
            party_id = provider["party"]["id"]
            invalid_payloads = (
                {"sourceKind": "google", "sourceName": "Wrong", "url": "https://example.com"},
                {"sourceKind": "other", "url": "https://example.com"},
                {"sourceKind": "google", "url": "http://example.com"},
                {"sourceKind": "google", "url": "https://example.com#fragment"},
                {"sourceKind": "google", "url": "https://example.com", "unexpected": True},
            )
            for payload in invalid_payloads:
                with self.subTest(payload=payload):
                    self.assertEqual(client.post(f"/api/providers/{party_id}/reputation-links", json=payload).status_code, 422)
            created = client.post(f"/api/providers/{party_id}/reputation-links", json={
                "sourceKind": "other", "sourceName": "Nextdoor",
                "url": "https://NEXTDOOR.example:443/profile?id=private",
                "notes": "Private note", "lastCheckedOn": "2025-01-02",
            })
            self.assertEqual(created.status_code, 201)
            link_id = created.json()["reputationLinks"][0]["id"]
            self.assertEqual(client.get("/api/providers").json()["items"][0]["reputationLinkCount"], 1)
            patched = client.patch(f"/api/providers/{party_id}/reputation-links/{link_id}", json={
                "notes": None, "lastCheckedOn": None,
            })
            self.assertEqual(patched.status_code, 200)
            self.assertIsNone(patched.json()["reputationLinks"][0]["notes"])
            activity = next(event for event in client.get("/api/audit/events").json()["events"] if event["entityType"] == "provider_reputation_link")
            contextual = client.get(f"/api/audit/events/provider_reputation_link/{link_id}").json()["events"][-1]
            self.assertEqual(activity["after"]["url"], "[redacted]")
            self.assertEqual(activity["after"]["normalizedUrl"], "[redacted]")
            self.assertEqual(activity["after"]["notes"], "[redacted]")
            self.assertEqual(contextual["after"]["url"], "https://nextdoor.example/profile?id=private")

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
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO provider_reputation_links (id, party_id, source_kind, source_name, normalized_source_key, url, normalized_url, created_at, updated_at) VALUES ('bad-known', 'vendor', 'google', 'Not allowed', 'google', 'https://example.com', 'https://example.com', 'now', 'now')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO provider_reputation_links (id, party_id, source_kind, source_name, normalized_source_key, url, normalized_url, created_at, updated_at) VALUES ('bad-other', 'vendor', 'other', NULL, 'other', 'https://example.com', 'https://example.com', 'now', 'now')")
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

    def test_reputation_schema_rejects_weakened_partial_index(self) -> None:
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("DROP INDEX provider_reputation_links_one_active_url")
                connection.exec_driver_sql("CREATE INDEX provider_reputation_links_one_active_url ON provider_reputation_links(id)")
            with engine.connect() as connection:
                with self.assertRaises(MigrationSchemaError):
                    validate_vendor_schema(connection)
        finally:
            engine.dispose()

    def test_category_retained_validation_rejects_nonportable_metadata(self) -> None:
        category = self.providers.create_category(ProviderCategoryCommand(
            "Portable category", 8, "00000000-0000-4000-8000-000000000941", "Portable description",
        ))
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "UPDATE provider_categories SET description = '  noncanonical' WHERE id = ?",
                    (category["id"],),
                )
            with engine.connect() as connection:
                with self.assertRaises(MigrationSchemaError):
                    validate_vendor_data(connection)
        finally:
            engine.dispose()

    def test_category_retained_validation_rejects_tampered_seed_identity(self) -> None:
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "UPDATE provider_categories SET create_request_fingerprint = ? WHERE display_order = 0",
                    ("a" * 64,),
                )
            with engine.connect() as connection:
                with self.assertRaises(MigrationSchemaError):
                    validate_vendor_data(connection)
        finally:
            engine.dispose()

    def test_category_retained_validation_anchors_edited_seed_origin(self) -> None:
        seed = self.providers.list_categories()[0]
        self.providers.update_category(seed["id"], ProviderCategoryPatchCommand(description="Edited seed"))
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                original = connection.exec_driver_sql(
                    "SELECT before_snapshot FROM audit_events "
                    "WHERE entity_type = 'provider_category' AND entity_id = ?",
                    (seed["id"],),
                ).scalar_one()
                fabricated = json.loads(original)
                fabricated["displayName"] = "Fabricated origin"
                connection.exec_driver_sql("DROP TRIGGER audit_events_no_update")
                connection.exec_driver_sql(
                    "UPDATE audit_events SET before_snapshot = ? "
                    "WHERE entity_type = 'provider_category' AND entity_id = ?",
                    (json.dumps(fabricated, separators=(",", ":")), seed["id"]),
                )
            with engine.connect() as connection:
                with self.assertRaises(MigrationSchemaError):
                    validate_vendor_data(connection)
        finally:
            engine.dispose()

    def test_category_retained_validation_requires_correlated_mutation_audit(self) -> None:
        category = self.providers.create_category(ProviderCategoryCommand(
            "Audited category", 8, "00000000-0000-4000-8000-000000000942", None,
        ))
        engine = create_sqlite_engine(self.workspace.paths.database)
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("DROP TRIGGER audit_events_no_update")
                connection.exec_driver_sql(
                    "UPDATE audit_events SET after_snapshot = '{}' "
                    "WHERE entity_type = 'provider_category' AND entity_id = ?",
                    (category["id"],),
                )
            with engine.connect() as connection:
                with self.assertRaises(MigrationSchemaError):
                    validate_vendor_data(connection)
        finally:
            engine.dispose()

from __future__ import annotations

import sqlite3
import tempfile
import unittest
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.portfolio.application.service import OwnershipInput, PartyCreateCommand, PortfolioError, PortfolioService, PropertyCreateCommand, SpaceCreateCommand
from app.modules.portfolio.infrastructure.schema_validation import _normalise_sql, validate_portfolio_schema
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioUnitOfWork
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig
from app.platform.migration_errors import MigrationSchemaError
from app.platform.sqlite_engine import create_sqlite_engine


class PortfolioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.workspace = WorkspaceService(LocalConfig(root / "config.json", root / "workspace")); self.workspace.initialize()
        self.audit = SQLiteAuditRepository(self.workspace.paths.database)
        self.service = PortfolioService(SQLitePortfolioUnitOfWork(self.workspace.paths.database, AuditRecorder(self.audit)))

    def _party(self):
        return self.service.create_party(PartyCreateCommand("individual", "Morgan Owner", "morgan@example.test"))

    def _property(self, ownerships):
        return self.service.create_property(PropertyCreateCommand(
            "Maple duplex", "10 Maple Street", "Portland", "US", "single_family_home",
            tuple(ownerships), region="OR", postal_code="97201",
        ))

    def test_ownership_contexts_are_derived_from_relationships(self) -> None:
        self_owned = self._property([OwnershipInput("local_operator")])
        owner = self._party()
        managed = self._property([OwnershipInput("client_owner", owner.id)])
        mixed = self._property([OwnershipInput("local_operator"), OwnershipInput("client_owner", owner.id)])
        self.assertEqual(self.service.get_property(self_owned.id)["ownershipContext"], "self_owned")
        self.assertEqual(self.service.get_property(managed.id)["ownershipContext"], "managed_for_owner")
        self.assertEqual(self.service.get_property(mixed.id)["ownershipContext"], "mixed")
        self.assertEqual([record["id"] for record in self.service.list_properties(ownership_context_filter="mixed")], [mixed.id])

    def test_ownership_replacement_preserves_the_prior_relationship_and_correlation(self) -> None:
        property = self._property([OwnershipInput("local_operator")]); owner = self._party()
        updated = self.service.replace_ownerships(property.id, (OwnershipInput("client_owner", owner.id),), "2099-01-01")
        self.assertEqual(updated["ownershipContext"], "self_owned")
        self.assertEqual(len(updated["ownerships"]), 1)
        self.assertEqual(updated["ownerships"][0]["endsOn"], "2099-01-01")
        events = self.audit.history("property_ownership")
        replacement_events = [event for event in events if event.reason == "ownership_replaced"]
        self.assertEqual(len(replacement_events), 2)
        self.assertEqual(replacement_events[0].correlation_id, replacement_events[1].correlation_id)
        property_event = self.audit.history("property", property.id)[-1]
        self.assertEqual(property_event.action, "ownership_changed")
        self.assertEqual(property_event.after_snapshot["ownershipContext"], "managed_for_owner")

    def test_rejects_invalid_or_unknown_client_ownership(self) -> None:
        with self.assertRaises(PortfolioError):
            self._property([])
        with self.assertRaises(PortfolioError):
            self._property([OwnershipInput("client_owner", "missing")])
        with self.assertRaises(PortfolioError):
            self._property([OwnershipInput("local_operator"), OwnershipInput("local_operator")])

    def test_audit_failure_rolls_back_portfolio_creation(self) -> None:
        with patch.object(self.service.unit_of_work.recorder, "record_change", side_effect=sqlite3.DatabaseError("audit unavailable")):
            with self.assertRaises(sqlite3.DatabaseError):
                self._property([OwnershipInput("local_operator")])
        self.assertEqual(self.service.list_properties(), [])

    def test_typed_api_creates_and_filters_a_managed_property(self) -> None:
        config = self.temp.name + "/config.local.json"
        Path(config).write_text(json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8")
        with TestClient(create_app(Path(config))) as client:
            party = client.post("/api/parties", json={"partyKind": "organization", "displayName": "Northwest Holdings"})
            self.assertEqual(party.status_code, 201)
            property = client.post("/api/properties", json={
                "displayName": "Pine office", "addressLine1": "1 Pine Avenue", "city": "Portland",
                "countryCode": "US", "propertyType": "office", "ownerships": [{"ownerKind": "client_owner", "partyId": party.json()["id"]}],
            })
            self.assertEqual(property.status_code, 201)
            self.assertEqual(property.json()["ownershipContext"], "managed_for_owner")
            records = client.get("/api/properties", params={"ownershipContext": "managed_for_owner"})
            self.assertEqual([item["id"] for item in records.json()], [property.json()["id"]])
            invalid = client.post("/api/properties", json={
                "displayName": "Bad", "addressLine1": "1 Test", "city": "Portland", "countryCode": "US",
                "propertyType": "single_family_home", "ownerships": [{"ownerKind": "client_owner"}],
            })
            self.assertEqual(invalid.status_code, 422)
            inline = client.post("/api/properties", json={
                "displayName": "Cedar home", "addressLine1": "2 Cedar", "city": "Portland", "countryCode": "US",
                "propertyType": "single_family_home", "ownerships": [{"ownerKind": "client_owner", "inlineParty": {"partyKind": "individual", "displayName": "Casey Owner"}}],
            })
            self.assertEqual(inline.status_code, 201)
            self.assertEqual(inline.json()["ownerships"][0]["party"]["displayName"], "Casey Owner")
            space_id = inline.json()["spaces"][0]["id"]
            self.assertEqual(client.get("/api/audit/events").status_code, 200)
            self.assertEqual(client.get(f"/api/audit/events/space/{space_id}").status_code, 200)
            self.assertEqual(client.post("/api/properties", json={
                "displayName": "Ignored", "addressLine1": "3 Cedar", "city": "Portland", "countryCode": "US",
                "propertyType": "single_family_home", "ownershipContext": "mixed", "ownerships": [{"ownerKind": "local_operator"}],
            }).status_code, 422)

    def test_party_archiving_requires_no_active_ownership(self) -> None:
        owner = self._party(); property = self._property([OwnershipInput("client_owner", owner.id)])
        with self.assertRaises(PortfolioError): self.service.archive_party(owner.id, confirmed=True)
        self.service.replace_ownerships(property.id, (OwnershipInput("local_operator"),), date.today().isoformat())
        self.assertIsNotNone(self.service.archive_party(owner.id, confirmed=True).archived_at)

    def test_party_with_future_ownership_cannot_be_archived_and_out_of_order_schedule_is_rejected(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        future_owner = self._party()
        self.service.replace_ownerships(property.id, (OwnershipInput("client_owner", future_owner.id),), "2030-01-01")
        with self.assertRaises(PortfolioError):
            self.service.archive_party(future_owner.id, confirmed=True)
        current_owner = self._party()
        property = self._property([OwnershipInput("client_owner", current_owner.id)])
        replacement = self._party()
        self.service.replace_ownerships(property.id, (OwnershipInput("client_owner", replacement.id),), "2030-01-01")
        with self.assertRaises(PortfolioError):
            self.service.archive_party(current_owner.id, confirmed=True)
        with self.assertRaises(PortfolioError):
            self.service.replace_ownerships(property.id, (OwnershipInput("local_operator"),), "2029-01-01")

    def test_direct_inline_owner_must_be_a_party_command(self) -> None:
        with self.assertRaises(PortfolioError):
            OwnershipInput("client_owner", inline_party=object())

    def test_direct_property_command_rejects_non_ownership_items(self) -> None:
        with self.assertRaises(PortfolioError):
            PropertyCreateCommand(
                "Maple duplex",
                "10 Maple Street",
                "Portland",
                "US",
                "single_family_home",
                (object(),),
            )

    def test_same_date_future_ownership_replacement_is_rejected(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        first_owner = self._party()
        second_owner = self._party()
        self.service.replace_ownerships(
            property.id,
            (OwnershipInput("client_owner", first_owner.id),),
            "2030-01-01",
        )
        with self.assertRaises(PortfolioError):
            self.service.replace_ownerships(
                property.id,
                (OwnershipInput("client_owner", second_owner.id),),
                "2030-01-01",
            )
        with self.assertRaises(PortfolioError):
            self.service.archive_party(first_owner.id, confirmed=True)

    def test_schema_validation_rejects_changed_partial_index_predicate(self) -> None:
        with sqlite3.connect(self.workspace.paths.database) as connection:
            connection.execute("DROP INDEX property_ownerships_one_active_operator")
            connection.execute(
                "CREATE UNIQUE INDEX property_ownerships_one_active_operator "
                "ON property_ownerships(property_id)"
            )
        engine = create_sqlite_engine(self.workspace.paths.database)
        with engine.connect() as connection:
            with self.assertRaises(MigrationSchemaError):
                validate_portfolio_schema(connection)

    def test_schema_validation_rejects_index_on_the_wrong_table(self) -> None:
        with sqlite3.connect(self.workspace.paths.database) as connection:
            connection.execute("DROP INDEX parties_active_name")
            connection.execute(
                "CREATE INDEX parties_active_name ON properties(archived_at, display_name)"
            )
        engine = create_sqlite_engine(self.workspace.paths.database)
        with engine.connect() as connection:
            with self.assertRaises(MigrationSchemaError):
                validate_portfolio_schema(connection)

    def test_schema_validation_rejects_missing_spaces_foreign_key(self) -> None:
        with sqlite3.connect(self.workspace.paths.database) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("ALTER TABLE spaces RENAME TO spaces_with_foreign_key")
            connection.execute(
                "CREATE TABLE spaces ("
                "id TEXT PRIMARY KEY, property_id TEXT NOT NULL, space_kind TEXT NOT NULL, "
                "display_name TEXT NOT NULL, normalized_name TEXT NOT NULL, suite_or_floor TEXT, "
                "notes TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
                "archived_at TEXT, archived_by_property_operation_id TEXT, "
                "CHECK(space_kind IN ('whole_home', 'whole_office', 'office_suite')), "
                "CHECK(status IN ('active', 'archived')), CHECK(length(trim(display_name)) > 0))"
            )
            connection.execute(
                "INSERT INTO spaces SELECT * FROM spaces_with_foreign_key"
            )
            connection.execute("DROP TABLE spaces_with_foreign_key")
            connection.execute(
                "CREATE INDEX spaces_property_status_name "
                "ON spaces(property_id, status, display_name)"
            )
            connection.execute(
                "CREATE UNIQUE INDEX spaces_one_active_name "
                "ON spaces(property_id, normalized_name) WHERE status = 'active'"
            )
        engine = create_sqlite_engine(self.workspace.paths.database)
        with engine.connect() as connection:
            with self.assertRaises(MigrationSchemaError):
                validate_portfolio_schema(connection)

    def test_sql_normalization_preserves_constraint_grouping(self) -> None:
        expected = "(owner_kind = 'local_operator' AND party_id IS NULL) OR (owner_kind = 'client_owner' AND party_id IS NOT NULL)"
        incompatible = "owner_kind = 'local_operator' AND (party_id IS NULL OR owner_kind = 'client_owner') AND party_id IS NOT NULL"
        self.assertNotEqual(_normalise_sql(expected), _normalise_sql(incompatible))

    def test_residential_property_creates_one_whole_home_space(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        detail = self.service.get_property(property.id)
        self.assertEqual(detail["propertyType"], "single_family_home")
        self.assertEqual(detail["inventoryLayout"], "single_space")
        self.assertEqual(
            [(space["spaceKind"], space["displayName"]) for space in detail["spaces"]],
            [("whole_home", "Whole home")],
        )

    def test_office_suites_are_created_and_can_add_a_suite(self) -> None:
        office = self.service.create_property(
            PropertyCreateCommand(
                "Pine offices",
                "1 Pine Avenue",
                "Portland",
                "US",
                "office",
                (OwnershipInput("local_operator"),),
                inventory_layout="office_suites",
                spaces=(SpaceCreateCommand("Suite 100"), SpaceCreateCommand("Suite 200")),
            )
        )
        added = self.service.add_space(office.id, SpaceCreateCommand("Suite 300"))
        detail = self.service.get_property(office.id)
        self.assertEqual(added.space_kind, "office_suite")
        self.assertEqual([space["displayName"] for space in detail["spaces"]], ["Suite 100", "Suite 200", "Suite 300"])
        events = self.audit.history("space")
        self.assertEqual(len(events), 3)
        with self.assertRaises(PortfolioError):
            self.service.create_property(
                PropertyCreateCommand(
                    "Invalid office",
                    "2 Pine Avenue",
                    "Portland",
                    "US",
                    "office",
                    (OwnershipInput("local_operator"),),
                    inventory_layout="office_suites",
                )
            )

    def test_archiving_a_property_archives_its_spaces_atomically(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        archived = self.service.archive_property(property.id, confirmed=True)
        self.assertEqual(archived.status, "archived")
        self.assertEqual(self.service.get_property(property.id)["spaces"][0]["status"], "archived")
        restored = self.service.restore_property(property.id)
        self.assertEqual(restored.status, "active")
        self.assertEqual(self.service.get_property(property.id)["spaces"][0]["status"], "active")

    def test_space_names_are_case_insensitively_unique_and_retired_spaces_stay_archived(self) -> None:
        office = self.service.create_property(
            PropertyCreateCommand(
                "Pine offices", "1 Pine Avenue", "Portland", "US", "office",
                (OwnershipInput("local_operator"),),
                inventory_layout="office_suites",
                spaces=(SpaceCreateCommand("Suite 100"), SpaceCreateCommand("Suite 200")),
            )
        )
        spaces = self.service.get_property(office.id)["spaces"]
        with self.assertRaises(PortfolioError):
            self.service.add_space(office.id, SpaceCreateCommand("suite 100"))

        retired = self.service.archive_space(spaces[0]["id"], confirmed=True)
        replacement = self.service.add_space(office.id, SpaceCreateCommand("suite 100"))
        with self.assertRaises(PortfolioError):
            self.service.restore_space(retired.id)
        with self.assertRaises(PortfolioError):
            self.service.patch_space(spaces[1]["id"], {"displayName": "SUITE 100"})

        self.service.archive_property(office.id, confirmed=True)
        self.service.restore_property(office.id)
        all_spaces = {item.id: item for item in self.service.unit_of_work.spaces(office.id)}
        self.assertEqual(all_spaces[retired.id].status, "archived")
        self.assertEqual(all_spaces[replacement.id].status, "active")

    def test_space_patch_archive_and_restore_api(self) -> None:
        config = Path(self.temp.name) / "space-api-config.json"
        config.write_text(
            json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}),
            encoding="utf-8",
        )
        with TestClient(create_app(config)) as client:
            created = client.post(
                "/api/properties",
                json={
                    "displayName": "Oak offices",
                    "addressLine1": "10 Oak Road",
                    "city": "Portland",
                    "countryCode": "US",
                    "propertyType": "office",
                    "inventoryLayout": "office_suites",
                    "ownerships": [{"ownerKind": "local_operator"}],
                    "spaces": [{"displayName": "Suite A"}, {"displayName": "Suite B"}],
                },
            )
            self.assertEqual(created.status_code, 201)
            space_id = created.json()["spaces"][0]["id"]
            patched = client.patch(
                f"/api/spaces/{space_id}",
                json={"displayName": "Suite 101", "notes": "North wing"},
            )
            self.assertEqual(patched.status_code, 200)
            self.assertEqual(patched.json()["displayName"], "Suite 101")
            self.assertEqual(
                client.post(f"/api/spaces/{space_id}/archive", json={"confirmed": True}).status_code,
                200,
            )
            self.assertEqual(client.post(f"/api/spaces/{space_id}/restore").status_code, 200)

    def test_partial_property_patch_normalizes_values_and_preserves_archival_time(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        archived = self.service.archive_property(property.id, confirmed=True)
        updated = self.service.patch_property(property.id, {"displayName": "  Updated Maple  ", "countryCode": "us"})
        self.assertEqual(updated.display_name, "Updated Maple")
        self.assertEqual(updated.country_code, "US")
        self.assertEqual(updated.archived_at, archived.archived_at)

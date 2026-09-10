from __future__ import annotations

import sqlite3
import tempfile
import unittest
import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.portfolio.application.ports import PortfolioConflictError
from app.modules.portfolio.application.service import AvailabilityCommand, OccupancyCommand, OwnershipInput, PartyCreateCommand, PortfolioError, PortfolioService, PropertyCreateCommand, SpaceClassificationCommand, SpaceCreateCommand
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
        return self.service.create_party(PartyCreateCommand("individual", "Morgan Owner"))

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

    def test_spaces_have_explicit_unknown_statuses_and_statuses_are_independent(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        space_id = self.service.get_property(property.id)["spaces"][0]["id"]
        initial = self.service.get_space_status(space_id)
        self.assertEqual(initial["currentOccupancy"]["occupancyStatus"], "unknown")
        self.assertEqual(initial["availability"]["availabilityStatus"], "unknown")
        changed = self.service.classify_space(
            space_id,
            SpaceClassificationCommand(
                occupancy=OccupancyCommand("vacant", date.today().isoformat()),
            ),
        )
        self.assertEqual(changed["currentOccupancy"]["occupancyStatus"], "vacant")
        self.assertEqual(changed["availability"]["availabilityStatus"], "unknown")

    def test_scheduled_transition_does_not_change_current_status_and_can_be_cancelled(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        space_id = self.service.get_property(property.id)["spaces"][0]["id"]
        scheduled = self.service.change_occupancy(space_id, OccupancyCommand("occupied", "2099-01-01"))
        self.assertEqual(scheduled["currentOccupancy"]["occupancyStatus"], "unknown")
        period_id = scheduled["scheduledOccupancy"]["id"]
        restored = self.service.cancel_scheduled_occupancy(space_id, period_id)
        self.assertIsNone(restored["scheduledOccupancy"])
        self.assertEqual(restored["currentOccupancy"]["occupancyStatus"], "unknown")

    def test_occupied_or_scheduled_space_cannot_be_archived(self) -> None:
        office = self.service.create_property(PropertyCreateCommand(
            "Oak office", "1 Oak", "Portland", "US", "office", (OwnershipInput("local_operator"),),
            inventory_layout="office_suites", spaces=(SpaceCreateCommand("A"), SpaceCreateCommand("B")),
        ))
        space_id = self.service.get_property(office.id)["spaces"][0]["id"]
        self.service.classify_space(
            space_id,
            SpaceClassificationCommand(
                OccupancyCommand("occupied", date.today().isoformat()),
                AvailabilityCommand("not_available"),
            ),
        )
        with self.assertRaises(PortfolioError):
            self.service.archive_space(space_id, confirmed=True)
        self.service.change_occupancy(space_id, OccupancyCommand("vacant", "2099-01-01"))
        with self.assertRaises(PortfolioError):
            self.service.archive_space(space_id, confirmed=True)

    def test_availability_date_rules_and_property_summary(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        space_id = self.service.get_property(property.id)["spaces"][0]["id"]
        with self.assertRaises(PortfolioError):
            AvailabilityCommand("available_on")
        with self.assertRaises(PortfolioError):
            AvailabilityCommand("available_on", "2000-01-01")
        self.service.change_availability(space_id, AvailabilityCommand("available_on", "2099-01-01"))
        detail = self.service.get_property(property.id)
        self.assertEqual(detail["statusSummary"]["availableLaterCount"], 1)
        self.assertEqual(self.service.list_properties(availability_filter="available_on")[0]["id"], property.id)

    def test_availability_becomes_available_now_on_its_date(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        space_id = self.service.get_property(property.id)["spaces"][0]["id"]
        self.service.change_availability(
            space_id,
            AvailabilityCommand("available_on", date.today().isoformat()),
        )
        status = self.service.get_space_status(space_id)
        self.assertEqual(status["availability"]["availabilityStatus"], "available_now")
        self.assertEqual(status["availability"]["availableOn"], date.today().isoformat())
        summary = self.service.get_property(property.id)["statusSummary"]
        self.assertEqual(summary["availableNowCount"], 1)
        self.assertEqual(summary["availableLaterCount"], 0)

    def test_status_api_rejects_invalid_availability_and_returns_a_scheduled_transition(self) -> None:
        config = Path(self.temp.name) / "status-api-config.json"
        config.write_text(json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8")
        with TestClient(create_app(config)) as client:
            created = client.post("/api/properties", json={
                "displayName": "Status home", "addressLine1": "9 Status Lane", "city": "Portland",
                "countryCode": "US", "propertyType": "single_family_home",
                "ownerships": [{"ownerKind": "local_operator"}],
                "spaces": [{"displayName": "Whole home", "occupancy": {"occupancyStatus": "vacant", "effectiveOn": date.today().isoformat()}}],
            })
            self.assertEqual(created.status_code, 201)
            space_id = created.json()["spaces"][0]["id"]
            self.assertEqual(client.put(f"/api/spaces/{space_id}/availability", json={"availabilityStatus": "available_on"}).status_code, 422)
            changed = client.put(f"/api/spaces/{space_id}/occupancy", json={"occupancyStatus": "occupied", "effectiveOn": "2099-01-01"})
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(changed.json()["scheduledOccupancy"]["occupancyStatus"], "occupied")

    def test_future_initial_occupancy_is_rejected_without_creating_a_property(self) -> None:
        with self.assertRaises(PortfolioError):
            self.service.create_property(PropertyCreateCommand(
                "Future home", "1 Future Way", "Portland", "US", "single_family_home",
                (OwnershipInput("local_operator"),),
                spaces=(SpaceCreateCommand(
                    "Whole home",
                    initial_occupancy=OccupancyCommand("occupied", "2099-01-01"),
                ),),
            ))
        self.assertEqual(self.service.list_properties(), [])

    def test_normal_occupancy_change_rejects_same_day_overwrite(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        space_id = self.service.get_property(property.id)["spaces"][0]["id"]
        with self.assertRaises(PortfolioError):
            self.service.change_occupancy(
                space_id,
                OccupancyCommand("vacant", date.today().isoformat()),
            )

    def test_only_latest_scheduled_transition_can_be_cancelled(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        space_id = self.service.get_property(property.id)["spaces"][0]["id"]
        first = self.service.change_occupancy(space_id, OccupancyCommand("vacant", "2090-01-01"))
        first_id = first["scheduledOccupancy"]["id"]
        self.service.change_occupancy(space_id, OccupancyCommand("occupied", "2091-01-01"))
        with self.assertRaises(PortfolioError):
            self.service.cancel_scheduled_occupancy(space_id, first_id)
        self.assertEqual(self.service.get_space_status(space_id)["scheduledOccupancy"]["id"], first_id)

    def test_classification_is_atomic_and_uses_one_correlation_id(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        space_id = self.service.get_property(property.id)["spaces"][0]["id"]
        before_count = len(self.audit.history())
        result = self.service.classify_space(
            space_id,
            SpaceClassificationCommand(
                OccupancyCommand("vacant", date.today().isoformat(), "Ready"),
                AvailabilityCommand("available_now", note="List it"),
            ),
        )
        self.assertEqual(result["currentOccupancy"]["occupancyStatus"], "vacant")
        self.assertEqual(result["availability"]["availabilityStatus"], "available_now")
        events = self.audit.history()[before_count:]
        self.assertEqual(len(events), 2)
        self.assertEqual(len({event.correlation_id for event in events}), 1)

    def test_classification_audit_failure_rolls_back_both_statuses(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        space_id = self.service.get_property(property.id)["spaces"][0]["id"]
        command = SpaceClassificationCommand(
            OccupancyCommand("vacant", date.today().isoformat()),
            AvailabilityCommand("available_now"),
        )
        with patch.object(
            self.service.unit_of_work.recorder,
            "record_change",
            side_effect=sqlite3.DatabaseError("audit unavailable"),
        ):
            with self.assertRaises(sqlite3.DatabaseError):
                self.service.classify_space(space_id, command)
        status = self.service.get_space_status(space_id)
        self.assertEqual(status["currentOccupancy"]["occupancyStatus"], "unknown")
        self.assertEqual(status["availability"]["availabilityStatus"], "unknown")

    def test_filters_ignore_archived_spaces(self) -> None:
        office = self.service.create_property(PropertyCreateCommand(
            "Filter office", "8 Filter", "Portland", "US", "office",
            (OwnershipInput("local_operator"),), inventory_layout="office_suites",
            spaces=(SpaceCreateCommand("A"), SpaceCreateCommand("B")),
        ))
        space_id = self.service.get_property(office.id)["spaces"][0]["id"]
        self.service.change_availability(space_id, AvailabilityCommand("available_now"))
        self.service.archive_space(space_id, confirmed=True)
        self.assertEqual(self.service.list_properties(availability_filter="available_now"), [])

    def test_needs_attention_query_accepts_true_and_false(self) -> None:
        config = Path(self.temp.name) / "attention-api-config.json"
        config.write_text(json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}), encoding="utf-8")
        with TestClient(create_app(config)) as client:
            created = client.post("/api/properties", json={
                "displayName": "Attention home", "addressLine1": "7 Review", "city": "Portland",
                "countryCode": "US", "propertyType": "single_family_home",
                "ownerships": [{"ownerKind": "local_operator"}],
            })
            self.assertEqual(created.status_code, 201)
            true_results = client.get("/api/properties", params={"needsAttention": "true"})
            false_results = client.get("/api/properties", params={"needsAttention": "false"})
            self.assertEqual(true_results.status_code, 200)
            self.assertEqual(false_results.status_code, 200)
            self.assertEqual(len(true_results.json()), 1)
            self.assertEqual(false_results.json(), [])
            space_id = created.json()["spaces"][0]["id"]
            classified = client.put(f"/api/spaces/{space_id}/classification", json={
                "occupancy": {
                    "occupancyStatus": "vacant",
                    "effectiveOn": date.today().isoformat(),
                },
                "availability": {"availabilityStatus": "available_now"},
            })
            self.assertEqual(classified.status_code, 200)
            self.assertEqual(classified.json()["currentOccupancy"]["occupancyStatus"], "vacant")
            self.assertEqual(len(client.get("/api/properties", params={"needsAttention": "false"}).json()), 1)

    def test_classification_can_complete_unknown_values_separately(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        space_id = self.service.get_property(property.id)["spaces"][0]["id"]

        availability_only = self.service.classify_space(
            space_id,
            SpaceClassificationCommand(
                availability=AvailabilityCommand("available_now"),
            ),
        )
        self.assertEqual(
            availability_only["currentOccupancy"]["occupancyStatus"],
            "unknown",
        )
        self.assertEqual(
            availability_only["availability"]["availabilityStatus"],
            "available_now",
        )

        occupancy_later = self.service.classify_space(
            space_id,
            SpaceClassificationCommand(
                occupancy=OccupancyCommand("vacant", date.today().isoformat()),
            ),
        )
        self.assertEqual(
            occupancy_later["currentOccupancy"]["occupancyStatus"],
            "vacant",
        )
        self.assertEqual(
            occupancy_later["availability"]["availabilityStatus"],
            "available_now",
        )

    def test_later_classification_preserves_historical_unknown_period(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        space_id = self.service.get_property(property.id)["spaces"][0]["id"]
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        with sqlite3.connect(self.workspace.paths.database) as connection:
            connection.execute(
                "UPDATE space_occupancy_periods SET starts_on = ? WHERE space_id = ?",
                (yesterday, space_id),
            )

        self.service.classify_space(
            space_id,
            SpaceClassificationCommand(
                occupancy=OccupancyCommand("vacant", date.today().isoformat()),
            ),
        )
        periods = self.service.unit_of_work.space_statuses([space_id])[0][space_id]
        self.assertEqual(
            [(item.occupancy_status, item.starts_on, item.ends_on) for item in periods],
            [
                ("unknown", yesterday, date.today().isoformat()),
                ("vacant", date.today().isoformat(), None),
            ],
        )

    def test_normal_occupancy_change_rejects_historical_date(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        space_id = self.service.get_property(property.id)["spaces"][0]["id"]
        with self.assertRaisesRegex(PortfolioError, "cannot take effect in the past"):
            self.service.change_occupancy(
                space_id,
                OccupancyCommand(
                    "vacant",
                    (date.today() - timedelta(days=1)).isoformat(),
                ),
            )

    def test_status_exposes_all_scheduled_transitions_and_latest_can_be_cancelled(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        space_id = self.service.get_property(property.id)["spaces"][0]["id"]
        self.service.change_occupancy(
            space_id,
            OccupancyCommand("vacant", "2090-01-01"),
        )
        status = self.service.change_occupancy(
            space_id,
            OccupancyCommand("occupied", "2091-01-01"),
        )
        timeline = status["scheduledOccupancyTimeline"]
        self.assertEqual(
            [item["startsOn"] for item in timeline],
            ["2090-01-01", "2091-01-01"],
        )
        latest_id = timeline[-1]["id"]
        cancelled = self.service.cancel_scheduled_occupancy(space_id, latest_id)
        self.assertEqual(
            [item["startsOn"] for item in cancelled["scheduledOccupancyTimeline"]],
            ["2090-01-01"],
        )

    def test_scheduled_replacement_is_atomic_and_preserves_superseded_record(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        space_id = self.service.get_property(property.id)["spaces"][0]["id"]
        scheduled = self.service.change_occupancy(
            space_id,
            OccupancyCommand("vacant", "2090-01-01"),
        )
        old_id = scheduled["scheduledOccupancy"]["id"]
        replaced = self.service.replace_scheduled_occupancy(
            space_id,
            old_id,
            OccupancyCommand("occupied", "2090-01-01", "Corrected"),
        )
        replacement = replaced["scheduledOccupancy"]
        periods = self.service.unit_of_work.space_statuses([space_id])[0][space_id]
        old = next(item for item in periods if item.id == old_id)
        self.assertEqual(old.record_state, "superseded")
        self.assertEqual(old.superseded_by_id, replacement["id"])
        self.assertEqual(replacement["occupancyStatus"], "occupied")

    def test_portfolio_status_summary_aggregates_active_properties(self) -> None:
        first = self._property([OwnershipInput("local_operator")])
        second = self._property([OwnershipInput("local_operator")])
        first_space = self.service.get_property(first.id)["spaces"][0]["id"]
        self.service.classify_space(
            first_space,
            SpaceClassificationCommand(
                OccupancyCommand("vacant", date.today().isoformat()),
                AvailabilityCommand("available_now"),
            ),
        )
        summary = self.service.portfolio_status_summary()
        self.assertEqual(summary["activePropertyCount"], 2)
        self.assertEqual(summary["activeSpaceCount"], 2)
        self.assertEqual(summary["vacantCount"], 1)
        self.assertEqual(summary["unknownOccupancyCount"], 1)
        self.assertEqual(summary["availableNowCount"], 1)
        self.assertEqual(summary["needsAttentionPropertyCount"], 1)

    def test_status_api_uses_typed_dates_and_exposes_summary_and_replacement(self) -> None:
        config = Path(self.temp.name) / "typed-status-api-config.json"
        config.write_text(
            json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}),
            encoding="utf-8",
        )
        with TestClient(create_app(config)) as client:
            created = client.post(
                "/api/properties",
                json={
                    "displayName": "Typed status home",
                    "addressLine1": "8 Contract Way",
                    "city": "Portland",
                    "countryCode": "US",
                    "propertyType": "single_family_home",
                    "ownerships": [{"ownerKind": "local_operator"}],
                },
            )
            space_id = created.json()["spaces"][0]["id"]
            malformed_occupancy = client.put(
                f"/api/spaces/{space_id}/occupancy",
                json={"occupancyStatus": "vacant", "effectiveOn": "not-a-date"},
            )
            malformed_availability = client.put(
                f"/api/spaces/{space_id}/availability",
                json={"availabilityStatus": "available_on", "availableOn": "not-a-date"},
            )
            self.assertEqual(malformed_occupancy.status_code, 422)
            self.assertEqual(malformed_availability.status_code, 422)

            first = client.put(
                f"/api/spaces/{space_id}/occupancy",
                json={"occupancyStatus": "vacant", "effectiveOn": "2090-01-01"},
            )
            second = client.put(
                f"/api/spaces/{space_id}/occupancy",
                json={"occupancyStatus": "occupied", "effectiveOn": "2091-01-01"},
            )
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            timeline = second.json()["scheduledOccupancyTimeline"]
            self.assertEqual(len(timeline), 2)
            latest_id = timeline[-1]["id"]
            replacement = client.put(
                f"/api/spaces/{space_id}/occupancy/scheduled/{latest_id}/replace",
                json={"occupancyStatus": "vacant", "effectiveOn": "2091-01-01"},
            )
            self.assertEqual(replacement.status_code, 200)
            self.assertEqual(
                replacement.json()["scheduledOccupancyTimeline"][-1]["occupancyStatus"],
                "vacant",
            )
            summary = client.get("/api/portfolio/status-summary")
            self.assertEqual(summary.status_code, 200)
            self.assertEqual(summary.json()["activePropertyCount"], 1)

    def test_classification_rejects_explicit_unknown_targets(self) -> None:
        with self.assertRaisesRegex(PortfolioError, "occupied or vacant"):
            SpaceClassificationCommand(
                occupancy=OccupancyCommand("unknown", date.today().isoformat()),
            )
        with self.assertRaisesRegex(PortfolioError, "known status"):
            SpaceClassificationCommand(
                availability=AvailabilityCommand("unknown"),
            )

    def test_api_rejects_unknown_classification_and_maps_source_conflict(self) -> None:
        config = Path(self.temp.name) / "conflict-api-config.json"
        config.write_text(
            json.dumps({"localWorkspacePath": str(self.workspace.paths.root)}),
            encoding="utf-8",
        )
        with TestClient(create_app(config)) as client:
            created = client.post(
                "/api/properties",
                json={
                    "displayName": "Conflict home",
                    "addressLine1": "9 Source Way",
                    "city": "Portland",
                    "countryCode": "US",
                    "propertyType": "single_family_home",
                    "ownerships": [{"ownerKind": "local_operator"}],
                },
            )
            space_id = created.json()["spaces"][0]["id"]
            unknown = client.put(
                f"/api/spaces/{space_id}/classification",
                json={
                    "occupancy": {
                        "occupancyStatus": "unknown",
                        "effectiveOn": date.today().isoformat(),
                    }
                },
            )
            self.assertEqual(unknown.status_code, 422)

            with sqlite3.connect(self.workspace.paths.database) as connection:
                connection.execute(
                    "UPDATE space_availability "
                    "SET source_kind = 'listing', source_id = 'listing-1' "
                    "WHERE space_id = ?",
                    (space_id,),
                )
            conflict = client.put(
                f"/api/spaces/{space_id}/availability",
                json={"availabilityStatus": "available_now"},
            )
            self.assertEqual(conflict.status_code, 409)

    def test_source_owned_classification_and_timeline_conflicts_raise_conflict(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        occupancy_space_id = self.service.get_property(property.id)["spaces"][0]["id"]
        with sqlite3.connect(self.workspace.paths.database) as connection:
            connection.execute(
                "UPDATE space_occupancy_periods "
                "SET source_kind = 'lease', source_id = 'lease-1' "
                "WHERE space_id = ?",
                (occupancy_space_id,),
            )
        with self.assertRaises(PortfolioConflictError):
            self.service.classify_space(
                occupancy_space_id,
                SpaceClassificationCommand(
                    occupancy=OccupancyCommand("vacant", date.today().isoformat()),
                ),
            )

        property = self._property([OwnershipInput("local_operator")])
        availability_space_id = self.service.get_property(property.id)["spaces"][0]["id"]
        with sqlite3.connect(self.workspace.paths.database) as connection:
            connection.execute(
                "UPDATE space_availability "
                "SET source_kind = 'listing', source_id = 'listing-1' "
                "WHERE space_id = ?",
                (availability_space_id,),
            )
        with self.assertRaises(PortfolioConflictError):
            self.service.classify_space(
                availability_space_id,
                SpaceClassificationCommand(
                    availability=AvailabilityCommand("available_now"),
                ),
            )

        scheduled = self.service.change_occupancy(
            availability_space_id,
            OccupancyCommand("vacant", "2090-01-01"),
        )
        with sqlite3.connect(self.workspace.paths.database) as connection:
            connection.execute(
                "UPDATE space_occupancy_periods "
                "SET source_kind = 'lease', source_id = 'lease-2' "
                "WHERE id = ?",
                (scheduled["scheduledOccupancy"]["id"],),
            )
        with self.assertRaises(PortfolioConflictError):
            self.service.change_occupancy(
                availability_space_id,
                OccupancyCommand("occupied", "2090-01-01"),
            )

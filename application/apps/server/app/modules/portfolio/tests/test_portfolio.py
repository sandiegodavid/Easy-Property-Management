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
from app.modules.portfolio.application.service import OwnershipInput, PartyCreateCommand, PortfolioError, PortfolioService, PropertyCreateCommand
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
            "Maple duplex", "10 Maple Street", "Portland", "US", tuple(ownerships), region="OR", postal_code="97201",
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
                "countryCode": "US", "ownerships": [{"ownerKind": "client_owner", "partyId": party.json()["id"]}],
            })
            self.assertEqual(property.status_code, 201)
            self.assertEqual(property.json()["ownershipContext"], "managed_for_owner")
            records = client.get("/api/properties", params={"ownershipContext": "managed_for_owner"})
            self.assertEqual([item["id"] for item in records.json()], [property.json()["id"]])
            invalid = client.post("/api/properties", json={
                "displayName": "Bad", "addressLine1": "1 Test", "city": "Portland", "countryCode": "US",
                "ownerships": [{"ownerKind": "client_owner"}],
            })
            self.assertEqual(invalid.status_code, 422)
            inline = client.post("/api/properties", json={
                "displayName": "Cedar home", "addressLine1": "2 Cedar", "city": "Portland", "countryCode": "US",
                "ownerships": [{"ownerKind": "client_owner", "inlineParty": {"partyKind": "individual", "displayName": "Casey Owner"}}],
            })
            self.assertEqual(inline.status_code, 201)
            self.assertEqual(inline.json()["ownerships"][0]["party"]["displayName"], "Casey Owner")
            self.assertEqual(client.post("/api/properties", json={
                "displayName": "Ignored", "addressLine1": "3 Cedar", "city": "Portland", "countryCode": "US",
                "ownershipContext": "mixed", "ownerships": [{"ownerKind": "local_operator"}],
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

    def test_sql_normalization_preserves_constraint_grouping(self) -> None:
        expected = "(owner_kind = 'local_operator' AND party_id IS NULL) OR (owner_kind = 'client_owner' AND party_id IS NOT NULL)"
        incompatible = "owner_kind = 'local_operator' AND (party_id IS NULL OR owner_kind = 'client_owner') AND party_id IS NOT NULL"
        self.assertNotEqual(_normalise_sql(expected), _normalise_sql(incompatible))

    def test_partial_property_patch_normalizes_values_and_preserves_archival_time(self) -> None:
        property = self._property([OwnershipInput("local_operator")])
        archived = self.service.archive_property(property.id, confirmed=True)
        updated = self.service.patch_property(property.id, {"displayName": "  Updated Maple  ", "countryCode": "us"})
        self.assertEqual(updated.display_name, "Updated Maple")
        self.assertEqual(updated.country_code, "US")
        self.assertEqual(updated.archived_at, archived.archived_at)

"""Focused regression checks for the synthetic identity and ownership plan."""

import json
from collections import Counter
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo

from demo.seed import Seeder, tenant_ids
from demo.verify import (
    EXPECTED,
    ISSUES_BY_LOCATION,
    PROPERTY_LOCATIONS,
    identity_checks,
    location_checks,
)

from app.modules.portfolio.infrastructure.time_zone import BundledAddressTimeZoneResolver


class DemoIdentityTests(TestCase):
    def setUp(self):
        self.plan = json.loads(Path(__file__).with_name("dataset.json").read_text())
        self.catalog = {
            "owners": {row["key"]: row["key"] for row in self.plan["owners"]},
            "providers": ["provider"],
            "properties": [dict(row, id=row["key"]) for row in self.plan["properties"]],
        }
        self.records = {"/api/providers/provider": {"profile": {"officialIds": ["license"]}}}
        for row in self.catalog["properties"]:
            self.records[f"/api/properties/{row['id']}"] = {
                "ownerships": [
                    {"partyId": None if owner == "operator" else owner, "sharePercent": share}
                    for owner, share in zip(
                        row.get("coOwners", [row["owner"]]),
                        row.get("ownershipShares", [100]),
                        strict=True,
                    )
                ]
            }

    def verify(self):
        with patch("demo.verify.read", side_effect=lambda _client, path: self.records[path]):
            identity_checks(None, self.catalog)

    def test_every_owner_has_a_recorded_share_and_properties_total_100(self):
        self.verify()
        for record in self.records.values():
            if "ownerships" in record:
                self.assertEqual(sum(item["sharePercent"] for item in record["ownerships"]), 100)

    def test_unassigned_owner_is_rejected(self):
        self.catalog["owners"]["unassigned"] = "unassigned"
        with self.assertRaisesRegex(RuntimeError, "no property ownership"):
            self.verify()

    def test_missing_or_changed_share_is_rejected(self):
        original = deepcopy(self.records)
        for share in (None, 99):
            self.records = deepcopy(original)
            record = self.records["/api/properties/shared-ten-owner-home"]
            record["ownerships"][0]["sharePercent"] = share
            with self.assertRaisesRegex(RuntimeError, "Ownership share mismatch"):
                self.verify()

    def test_provider_without_id_is_rejected(self):
        self.records["/api/providers/provider"]["profile"]["officialIds"] = []
        with self.assertRaisesRegex(RuntimeError, "no license or official ID"):
            self.verify()

    def test_all_tenants_have_ids_including_a_multiple_id_example(self):
        for row in self.plan["properties"]:
            for index, _name in enumerate(row["tenants"]):
                identifiers = tenant_ids(row, index)
                self.assertTrue(identifiers)
                for item in identifiers:
                    self.assertEqual(len(item["lastFour"]), 4)
        home = next(row for row in self.plan["properties"] if row["key"] == "op-home")
        self.assertEqual(
            {item["documentType"] for item in tenant_ids(home, 0)},
            {"passport", "drivers_license"},
        )


class DemoLocationTests(TestCase):
    def setUp(self):
        self.plan = json.loads(Path(__file__).with_name("dataset.json").read_text())
        self.catalog = {"properties": [dict(row, id=row["key"]) for row in self.plan["properties"]]}
        resolver = BundledAddressTimeZoneResolver()
        self.records = {
            f"/api/properties/{row['id']}": {
                "addressLine1": row["address"],
                "city": row["city"],
                "region": row["region"],
                "postalCode": row["postalCode"],
                "countryCode": "US",
                "timeZone": resolver.resolve(
                    address_line_1=row["address"],
                    city=row["city"],
                    region=row["region"],
                    postal_code=row["postalCode"],
                    country_code="US",
                ),
            }
            for row in self.catalog["properties"]
        }

    def verify(self):
        with patch("demo.verify.read", side_effect=lambda _client, path: self.records[path]):
            location_checks(None, self.catalog)

    def test_location_distribution_and_resolved_zones(self):
        self.verify()

    def test_maintenance_issue_distribution_includes_existing_issues(self):
        properties = {row["key"]: row for row in self.plan["properties"]}
        locations = Counter(
            (properties[issue["property"]]["city"], properties[issue["property"]]["region"])
            for issue in self.plan["issues"]
        )
        self.assertEqual(locations, ISSUES_BY_LOCATION)
        self.assertEqual(len(self.plan["issues"]), EXPECTED["maintenance_issues"])
        self.assertEqual(len({row["key"] for row in self.plan["issues"]}), len(self.plan["issues"]))

    def test_changed_address_or_zone_is_rejected(self):
        record = self.records["/api/properties/o1-late"]
        for field, wrong in (("postalCode", "97205"), ("timeZone", "America/Los_Angeles")):
            with self.subTest(field=field):
                original = record[field]
                record[field] = wrong
                with self.assertRaisesRegex(RuntimeError, "address or time zone mismatch"):
                    self.verify()
                record[field] = original

    def test_missing_property_is_rejected(self):
        self.catalog["properties"].pop()
        with self.assertRaisesRegex(RuntimeError, "location counts mismatch"):
            self.verify()

    def test_property_local_scheduled_instants_cover_standard_and_daylight_time(self):
        seed = object.__new__(Seeder)
        for day in (date(2026, 1, 15), date(2026, 7, 15)):
            seed.today = day
            for _count, zone in PROPERTY_LOCATIONS.values():
                with self.subTest(day=day, zone=zone):
                    instant = datetime.fromisoformat(seed.instant(0, zone=zone))
                    local = instant.astimezone(ZoneInfo(zone))
                    self.assertEqual(local.date(), day)
                    self.assertEqual(local.hour, 10)

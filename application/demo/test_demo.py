"""Focused regression checks for the synthetic identity and ownership plan."""

import json
from copy import deepcopy
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from demo.seed import tenant_ids
from demo.verify import identity_checks


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

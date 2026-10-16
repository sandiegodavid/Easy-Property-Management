"""Verify demo relationships and counts against its actual persisted records."""

import argparse
import json
import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from app.bootstrap.api import create_app
from app.modules.workspace.application.service import WorkspaceService
from app.platform.testing_client import LocalApiClient

EXPECTED = {
    "properties": 11,
    "spaces": 12,
    "provider_profiles": 20,
    "leases": 9,
    "tenant_profiles": 12,
    "lease_participants": 12,
    "expenses": 40,
    "communications": 6,
    "maintenance_issues": 4,
    "maintenance_quotes": 6,
    "maintenance_appointments": 3,
    "condition_reports": 1,
    "security_deposit_accounts": 9,
    "security_deposit_receipts": 9,
    "tasks": 1,
}
OFFICE_SUITE_COUNT = 2
VACANT_SPACE_COUNT = 3


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def database_checks(database):
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        require(
            connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Integrity failure"
        )
        require(
            not connection.execute("PRAGMA foreign_key_check").fetchall(), "Foreign-key failure"
        )
        counts = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in EXPECTED
        }
        require(counts == EXPECTED, f"Unexpected counts: {counts}")
        expense_counts = connection.execute(
            "SELECT o.owner_kind, o.party_id, count(*) FROM expenses e "
            "JOIN property_ownerships o ON e.property_id=o.property_id "
            "GROUP BY o.owner_kind, o.party_id"
        ).fetchall()
        require(sorted(row[2] for row in expense_counts) == [8, 12, 20], "Expense group mismatch")
        linked = connection.execute(
            "SELECT count(DISTINCT provider_party_id) FROM expenses"
        ).fetchone()[0]
        require(
            linked == EXPECTED["provider_profiles"], "Some providers lack property expense links"
        )
        funded = connection.execute(
            "SELECT a.id FROM security_deposit_accounts a "
            "LEFT JOIN security_deposit_receipts r ON r.account_id=a.id AND r.voided_at IS NULL "
            "GROUP BY a.id HAVING COALESCE(sum(r.amount_minor),0) != a.agreed_amount_minor"
        ).fetchall()
        require(not funded, "A deposit is not fully funded")
    return counts


def read(client, path, **params):
    response = client.get(path, params=params)
    response.raise_for_status()
    return response.json()


def api_checks(client, catalog):
    vacant = 0
    leasing_statuses = Counter()
    for row in catalog["properties"]:
        space = read(client, f"/api/spaces/{row['spaceId']}/status")
        vacant += space["currentOccupancy"]["occupancyStatus"] == "vacant"
        expected = (
            "available_now"
            if row.get("vacant")
            else "available_on"
            if row.get("openForLeasingLater")
            else "not_available"
        )
        availability = space["availability"]
        require(availability["effectiveStatus"] == expected, f"Leasing status: {row['key']}")
        leasing_statuses[expected] += 1
        if expected == "available_on":
            opening = date.fromisoformat(catalog["asOf"]).replace(day=1) + timedelta(days=365)
            expected_opening = row.get("leasingAvailableOn") or opening.isoformat()
            require(availability["availableOn"] == expected_opening, "Leasing opening date")
        if not row.get("vacant"):
            require(space["currentOccupancy"]["occupancyStatus"] == "occupied", "Occupancy")
        if not row.get("leaseId"):
            continue
        lease = read(client, f"/api/leases/{row['leaseId']}")
        require(lease["status"] == "executed", f"Unexecuted demo Lease: {row['key']}")
        if row.get("leaseEndsOn"):
            require(lease["contractEndsOn"] == row["leaseEndsOn"], "Lease end date mismatch")
            require(lease["terms"][0]["endsOn"] == row["leaseEndsOn"], "Term end date mismatch")
            require(
                all(item["endsOn"] == row["leaseEndsOn"] for item in lease["participants"]),
                "Participant end date mismatch",
            )
        participants = lease["participants"]
        require(
            {item["tenantPartyId"] for item in participants} == set(row["tenantIds"]),
            f"Tenant membership mismatch: {row['key']}",
        )
        require(len(participants) == len(row["tenants"]), f"Tenant count mismatch: {row['key']}")
        expected_roles = {
            party_id: "business_signatory"
            if row["type"] == "office"
            else "primary_tenant"
            if index == 0
            else "co_tenant"
            for index, party_id in enumerate(row["tenantIds"])
        }
        require(
            all(
                item["participantRole"] == expected_roles[item["tenantPartyId"]]
                for item in participants
            ),
            f"Tenant role mismatch: {row['key']}",
        )
        for party_id, name in zip(row["tenantIds"], row["tenants"], strict=True):
            tenant = read(client, f"/api/tenants/{party_id}")
            require(tenant["displayName"] == name, f"Tenant name mismatch: {row['key']}")
        require(lease["terms"][0]["agreedSecurityDepositMinor"] > 0, "Missing agreed deposit")
    suites = next(row for row in catalog["properties"] if row["key"] == "op-office-suites")
    require(len(suites["spaceIds"]) == OFFICE_SUITE_COUNT, "Harbor Offices must have two spaces")
    for space_id in suites["spaceIds"][1:]:
        space = read(client, f"/api/spaces/{space_id}/status")
        require(space["currentOccupancy"]["occupancyStatus"] == "vacant", "Suite occupancy")
        require(space["availability"]["effectiveStatus"] == "available_now", "Suite leasing")
        vacant += 1
        leasing_statuses["available_now"] += 1
    require(vacant == VACANT_SPACE_COUNT, f"Expected three vacant spaces, found {vacant}")
    require(
        leasing_statuses == {"not_available": 7, "available_on": 2, "available_now": 3},
        f"Unexpected leasing mix: {dict(leasing_statuses)}",
    )
    late = read(client, "/api/rent-expectations", timelinessStatus="late")["items"]
    require(len(late) == 1, f"Expected one unpaid late rent, found {len(late)}")
    prepaid = next(row for row in catalog["properties"] if row.get("prepaid"))
    expectations = read(client, "/api/rent-expectations", leaseId=prepaid["leaseId"])["items"]
    require(
        any(
            row["dueOn"] > catalog["asOf"] and row["settlementStatus"] == "paid"
            for row in expectations
        ),
        "Missing prepaid future rent",
    )
    return {
        "vacancies": vacant,
        "leasingStatuses": dict(leasing_statuses),
        "lateUnpaidRent": len(late),
        "prepaidRent": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).parent / "config.local.json")
    args = parser.parse_args()
    service = WorkspaceService.from_local_config(args.config)
    service.open(integrity_check=True)
    runtime = service.paths.root.parent / f"{service.paths.root.name}-demo-runtime"
    catalog = json.loads((runtime / "catalog.json").read_text())
    counts = database_checks(service.paths.database)
    with LocalApiClient(create_app(args.config)) as client:
        scenarios = api_checks(client, catalog)
    report = {"counts": counts, "scenarios": scenarios, "asOf": catalog["asOf"]}
    (runtime / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

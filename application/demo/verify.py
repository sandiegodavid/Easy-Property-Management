"""Verify demo relationships and counts against its actual persisted records."""

import argparse
import json
import sqlite3
from pathlib import Path

from app.bootstrap.api import create_app
from app.modules.workspace.application.service import WorkspaceService
from app.platform.testing_client import LocalApiClient

EXPECTED = {
    "properties": 10,
    "spaces": 10,
    "provider_profiles": 20,
    "leases": 9,
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
    for row in catalog["properties"]:
        space = read(client, f"/api/spaces/{row['spaceId']}/status")
        vacant += space["currentOccupancy"]["occupancyStatus"] == "vacant"
        if not row.get("leaseId"):
            continue
        lease = read(client, f"/api/leases/{row['leaseId']}")
        require(lease["status"] == "executed", f"Unexecuted demo Lease: {row['key']}")
        require(lease["terms"][0]["agreedSecurityDepositMinor"] > 0, "Missing agreed deposit")
    require(vacant == 1, f"Expected one vacancy, found {vacant}")
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
    return {"vacancies": vacant, "lateUnpaidRent": len(late), "prepaidRent": True}


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

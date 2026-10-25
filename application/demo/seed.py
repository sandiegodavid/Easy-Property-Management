"""Create a synthetic demo through the real API, with resumable safe writes."""

import argparse
import json
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from app.bootstrap.api import create_app
from app.modules.workspace.application.service import WorkspaceService
from app.platform.testing_client import LocalApiClient

HERE = Path(__file__).resolve().parent
TIMEZONE = "America/Los_Angeles"
OWNER_GROUPS = ("operator", "owner_1", "owner_2")
EXPENSE_COUNTS = (12, 8, 20)


def save_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def month_after(day):
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def tenant_ids(record, index):
    identifiers = [
        {
            "documentType": "business_registration" if record["type"] == "office" else "passport",
            "issuingCountry": "US",
            "lastFour": "DEMO",
        }
    ]
    if record["key"] == "op-home" and index == 0:
        identifiers.append(
            {
                "documentType": "drivers_license",
                "issuingCountry": "US",
                "issuingRegion": "OR",
                "lastFour": "TEST",
            }
        )
    return identifiers


class Seeder:
    """Journal original requests before dispatch; never recreate a populated workspace."""

    def __init__(self, client, journal_path, as_of):
        self.client = client
        self.path = journal_path
        self.journal = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.today = as_of
        self.start = as_of.replace(day=1)
        self.next_month = month_after(as_of)
        self.catalog = {"owners": {}, "providers": [], "properties": [], "issues": []}

    def get(self, path, **params):
        response = self.client.get(path, params=params)
        if response.status_code != HTTPStatus.OK:
            raise RuntimeError(f"GET {path}: {response.status_code} {response.text}")
        return response.json()

    def write(self, path, payload, *, label, method="post"):
        key = str(uuid5(NAMESPACE_URL, f"epm-synthetic-demo-v1/{label}"))
        previous = self.journal.get(label)
        if previous:
            if previous["path"] != path or previous["method"] != method:
                raise RuntimeError(f"Demo plan changed for {label}; choose a new destination.")
            if "result" in previous:
                return previous["result"]
            payload = previous["request"]
        else:
            payload = {**payload, "idempotencyKey": key}
            self.journal[label] = {"path": path, "method": method, "request": payload}
            save_json(self.path, self.journal)
        response = getattr(self.client, method)(path, json=payload)
        if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
            # Known rejections may be corrected on the next run; unknown writes retain identity.
            if response.status_code < HTTPStatus.INTERNAL_SERVER_ERROR:
                del self.journal[label]
                save_json(self.path, self.journal)
            raise RuntimeError(f"{label}: {response.status_code} {response.text}")
        result = response.json()
        self.journal[label]["result"] = result
        save_json(self.path, self.journal)
        return result

    def owners(self, plan):
        for owner in plan["owners"]:
            result = self.write(
                "/api/parties",
                {
                    "expectedRevision": 0,
                    "confirmedNewParty": True,
                    "partyKind": "individual",
                    "displayName": owner["name"],
                    "contacts": [{"methodKind": "email", "value": owner["email"]}],
                },
                label=owner["key"],
            )
            self.catalog["owners"][owner["key"]] = result["id"]

    def providers(self, plan):
        categories = {row["displayName"]: row["id"] for row in self.get("/api/provider-categories")}
        for index, provider in enumerate(plan["providers"]):
            result = self.write(
                "/api/providers",
                {
                    "expectedRevision": 0,
                    "confirmedNewParty": True,
                    "party": {"partyKind": "organization", "displayName": provider["name"]},
                    "contacts": [{"methodKind": "email", "value": provider["email"]}],
                    "categoryIds": [categories[provider["category"]]],
                    "services": [{"displayName": provider["service"]}],
                    "serviceAreas": [{"displayName": "Portland metro", "countryCode": "US"}],
                    "selectionStatus": "preferred" if index % 4 == 0 else "neutral",
                    "selectionReason": "Synthetic demo shortlist" if index % 4 == 0 else None,
                    "notes": "Fictional provider; do not contact.",
                    "officialIds": [
                        {
                            "documentType": "license",
                            "issuingCountry": "US",
                            "issuingRegion": "OR",
                            "lastFour": "DEMO",
                        }
                    ],
                },
                label=f"provider-{index}",
            )
            self.catalog["providers"].append(result["party"]["id"])

    def property(self, item):
        space_names = item.get("spaceNames") or [
            item.get("unit", "Whole office" if item["type"] == "office" else "Whole home")
        ]
        ownerships = [
            {"ownerKind": "local_operator", "sharePercent": share}
            if owner == "operator"
            else {
                "ownerKind": "client_owner",
                "partyId": self.catalog["owners"][owner],
                "sharePercent": share,
            }
            for owner, share in zip(
                item.get("coOwners", [item["owner"]]),
                item.get("ownershipShares", [100]),
                strict=True,
            )
        ]
        result = self.write(
            "/api/properties",
            {
                "expectedPropertyRevision": 0,
                "displayName": item["name"],
                "addressLine1": item["address"],
                "addressLine2": item.get("unit"),
                "city": item["city"],
                "region": item["region"],
                "postalCode": item["postalCode"],
                "countryCode": "US",
                "propertyType": item["type"],
                "inventoryLayout": "office_suites"
                if item.get("spaceNames")
                else "whole_office"
                if item["type"] == "office"
                else "single_space",
                "ownerships": ownerships,
                "notes": item["notes"],
                "spaces": [
                    {
                        "displayName": name,
                        "occupancy": {
                            "occupancyStatus": "vacant",
                            "effectiveOn": self.today.isoformat(),
                        },
                        "availability": self.leasing_availability(item),
                    }
                    for name in space_names
                ],
            },
            label=item["key"],
        )
        record = {
            **item,
            "id": result["id"],
            "timeZone": result["timeZone"],
            "spaceId": result["spaces"][0]["id"],
            "spaceIds": [space["id"] for space in result["spaces"]],
        }
        if not item.get("vacant"):
            self.lease(record)
        self.update_leasing_status(record)
        self.catalog["properties"].append(record)

    def leasing_availability(self, item):
        if item.get("leasingUnclassified"):
            return {"availabilityStatus": "unknown"}
        if item.get("vacant"):
            return {"availabilityStatus": "available_now"}
        if item.get("openForLeasingLater"):
            return {
                "availabilityStatus": "available_on",
                "availableOn": item.get("leasingAvailableOn")
                or (self.start + timedelta(days=365)).isoformat(),
            }
        return {"availabilityStatus": "not_available"}

    def update_leasing_status(self, record):
        """Bring an older demo's availability up to date without changing its leases."""
        desired = self.leasing_availability(record)
        current = self.get(f"/api/spaces/{record['spaceId']}/status")
        availability = current["availability"]
        if availability["recordedStatus"] == desired["availabilityStatus"] and availability.get(
            "availableOn"
        ) == desired.get("availableOn"):
            return
        self.write(
            f"/api/spaces/{record['spaceId']}/availability",
            {**desired, "expectedRevision": current["revision"]},
            method="put",
            label=(
                f"{record['key']}-leasing-status-{desired['availabilityStatus']}-"
                f"{desired.get('availableOn', 'undated')}"
            ),
        )

    def lease(self, record):
        tenants = [
            self.write(
                "/api/tenants",
                {
                    "expectedRevision": 0,
                    "confirmedNewParty": True,
                    "partyKind": "organization" if record["type"] == "office" else "individual",
                    "displayName": name,
                    "officialIds": tenant_ids(record, index),
                    "contacts": [
                        {
                            "methodKind": "email",
                            "value": f"{record['key']}-tenant-{index + 1}@example.invalid",
                        }
                    ],
                },
                label=f"{record['key']}-tenant-{index + 1}",
            )
            for index, name in enumerate(record["tenants"])
        ]
        draft = self.write(
            "/api/leases",
            {
                "expectedLeaseRevision": 0,
                "spaceId": record["spaceId"],
                "leaseKind": "commercial" if record["type"] == "office" else "residential",
                "contractStartsOn": self.start.isoformat(),
                "contractEndsOn": record.get("leaseEndsOn")
                or (self.start + timedelta(days=365)).isoformat(),
                "occupancyStartsOn": self.today.isoformat(),
                "initialTerm": {
                    "baseRentMinor": record["rentMinor"],
                    "agreedSecurityDepositMinor": record["rentMinor"],
                    "currencyCode": "USD",
                    "paymentFrequency": "monthly",
                    "paymentDueDay": 1,
                },
                "participants": [
                    {
                        "tenantPartyId": tenant["id"],
                        "participantRole": (
                            "business_signatory"
                            if record["type"] == "office"
                            else "primary_tenant"
                            if index == 0
                            else "co_tenant"
                        ),
                    }
                    for index, tenant in enumerate(tenants)
                ],
                "notes": (
                    "Synthetic lease; contract begins this month; move-in is demo day. "
                    f"{record['notes']}"
                ),
            },
            label=f"{record['key']}-lease",
        )
        current = self.get(f"/api/leases/{draft['id']}")
        space = self.get(f"/api/spaces/{record['spaceId']}/status")
        self.write(
            f"/api/leases/{draft['id']}/execute",
            {
                "expectedLeaseRevision": current["leaseRevision"],
                "expectedRevision": space["revision"],
                "confirmed": True,
                "executedOn": self.today.isoformat(),
            },
            label=f"{record['key']}-execute",
        )
        record.update(
            leaseId=draft["id"],
            tenantId=tenants[0]["id"],
            tenantIds=[tenant["id"] for tenant in tenants],
            termId=draft["terms"][0]["id"],
        )
        self.money(record)

    def money(self, record):
        self.write(
            f"/api/leases/{record['leaseId']}/rent-expectations/synchronize",
            {
                "expectedRevision": 0,
                "leaseTermId": record["termId"],
                "scheduleAnchorOn": self.start.isoformat(),
                "throughOn": (month_after(self.next_month) - timedelta(days=1)).isoformat(),
            },
            label=f"{record['key']}-schedule",
        )
        expectations = self.get("/api/rent-expectations", leaseId=record["leaseId"])["items"]
        current = [row for row in expectations if row["dueOn"] < self.next_month.isoformat()]
        if not record.get("late"):
            self.rent_receipt(record, current, "rent")
        if record.get("prepaid"):
            future = [row for row in expectations if row["dueOn"] >= self.next_month.isoformat()]
            self.rent_receipt(record, future, "prepaid")
        account = self.write(
            f"/api/leases/{record['leaseId']}/security-deposit",
            {"expectedRevision": 0, "leaseTermId": record["termId"]},
            label=f"{record['key']}-deposit",
        )
        self.write(
            f"/api/security-deposits/{account['id']}/receipts",
            {
                "expectedRevision": account["depositAccountRevision"],
                "receivedOn": self.today.isoformat(),
                "amount": f"{record['rentMinor'] / 100:.2f}",
                "currencyCode": "USD",
                "receivedByKind": "local_operator",
                "receivedFromPartyId": record["tenantId"],
                "reference": f"DEMO-DEPOSIT-{record['key']}",
            },
            label=f"{record['key']}-deposit-receipt",
        )

    def rent_receipt(self, record, expectations, suffix):
        ledger = self.get(f"/api/leases/{record['leaseId']}/rent-ledger")
        return self.write(
            "/api/rent-receipts",
            {
                "expectedRevision": ledger["rentLedgerRevision"],
                "leaseId": record["leaseId"],
                "receivedOn": self.today.isoformat(),
                "currencyCode": "USD",
                "amountMinor": sum(row["expectedAmountMinor"] for row in expectations),
                "paymentMethodKind": "bank_transfer",
                "paymentMethodLabel": "Demo bank transfer",
                "duplicateConfirmed": suffix == "prepaid",
                "duplicateReason": (
                    "Separate payment of next month's rent on the same day."
                    if suffix == "prepaid"
                    else None
                ),
                "allocations": [
                    {"expectationId": row["id"], "amountMinor": row["expectedAmountMinor"]}
                    for row in expectations
                ],
                "notes": "Next month's rent paid early."
                if suffix == "prepaid"
                else "Synthetic rent payment.",
            },
            label=f"{record['key']}-{suffix}",
        )

    def expenses(self):
        categories = self.get("/api/expense-categories")
        for group, count in zip(OWNER_GROUPS, EXPENSE_COUNTS, strict=True):
            properties = [row for row in self.catalog["properties"] if row["owner"] == group]
            for index in range(count):
                row = properties[index % len(properties)]
                provider = self.catalog["providers"][index % len(self.catalog["providers"])]
                category = categories[index % len(categories)]
                self.write(
                    "/api/expenses",
                    {
                        "expectedRevision": 0,
                        "propertyId": row["id"],
                        "spaceId": row["spaceId"],
                        "categoryId": category["id"],
                        "paidByKind": "local_operator",
                        "paidOn": self.today.isoformat(),
                        "amount": f"{85 + index * 37}.00",
                        "currencyCode": "USD",
                        "providerPartyId": provider,
                        "description": (
                            f"{category['displayName']} — {row['name']} — demo {index + 1}"
                        ),
                        "reference": f"DEMO-{group}-{index + 1:02}",
                        "notes": "Fictional paid expense; operator paid on behalf of portfolio.",
                    },
                    label=f"expense-{group}-{index}",
                )

    def issue(self, item):
        row = next(p for p in self.catalog["properties"] if p["key"] == item["property"])
        result = self.write(
            "/api/maintenance-issues",
            {
                "expectedRevision": 0,
                "propertyId": row["id"],
                "spaceId": row["spaceId"],
                "summary": item["summary"],
                "description": item["description"],
                "category": item["category"],
                "priority": item["priority"],
                "reportedAtUtc": self.instant(-1, zone=row["timeZone"]),
                "reporter": {"role": "manager", "subjectKind": "local_operator"},
            },
            label=item["key"],
        )
        self.catalog["issues"].append({**item, "id": result["id"]})
        for index, amount in enumerate(item.get("quotes", [])):
            current = self.get(f"/api/maintenance-issues/{result['id']}")
            self.write(
                f"/api/maintenance-issues/{result['id']}/quotes",
                {
                    "expectedRevision": current["revision"],
                    "providerPartyId": self.catalog["providers"][item["providerIndexes"][index]],
                    "label": f"Option {index + 1}",
                    "scopeSummary": item["description"],
                    "amount": f"{amount}.00",
                    "receivedOn": self.today.isoformat(),
                    "validThrough": (self.today + timedelta(days=14)).isoformat(),
                },
                label=f"{item['key']}-quote-{index}",
            )
        if item.get("appointmentDays") is not None:
            current = self.get(f"/api/maintenance-issues/{result['id']}")
            self.write(
                f"/api/maintenance-issues/{result['id']}/appointments",
                {
                    "expectedRevision": current["revision"],
                    "startsAtUtc": self.instant(item["appointmentDays"], zone=row["timeZone"]),
                    "endsAtUtc": self.instant(
                        item["appointmentDays"], hour=12, zone=row["timeZone"]
                    ),
                    "purpose": item["summary"],
                    "instructions": "Demo access confirmed; no actual visit.",
                },
                label=f"{item['key']}-appointment",
            )

    def instant(self, days, *, hour=10, zone):
        local = datetime.combine(self.today + timedelta(days=days), datetime.min.time())
        return local.replace(hour=hour, tzinfo=ZoneInfo(zone)).astimezone(UTC).isoformat()

    def communications(self, plan):
        for index, item in enumerate(plan["communications"]):
            row = next(p for p in self.catalog["properties"] if p["key"] == item["property"])
            party = row.get("tenantId") or self.catalog["owners"].get(row["owner"])
            if not party:
                party = self.catalog["providers"][0]
            links = [{"entityType": "property", "entityId": row["id"]}]
            if row.get("leaseId"):
                links.append({"entityType": "lease", "entityId": row["leaseId"]})
            self.write(
                "/api/communications",
                {
                    "expectedRevision": 0,
                    "direction": "inbound",
                    "channel": "email",
                    "subject": item["subject"],
                    "body": item["body"],
                    "occurredAtUtc": self.instant(-1, zone=row["timeZone"]),
                    "occurredTimezone": row["timeZone"],
                    "participants": [{"partyId": party, "role": "sender"}],
                    "links": links,
                    "record": True,
                },
                label=f"communication-{index}",
            )

    def inspection(self):
        row = next(p for p in self.catalog["properties"] if p["key"] == "o2-condo-101")
        self.write(
            f"/api/leases/{row['leaseId']}/condition-reports",
            {
                "expectedRevision": 0,
                "reportKind": "pre_move_in",
                "walkthroughOn": self.today.isoformat(),
                "conductedBy": "Demo operator",
                "tenantPresence": "present",
                "generalNotes": "Draft walkthrough ready for operator review.",
                "areas": [
                    {
                        "displayName": "Kitchen",
                        "observations": [
                            {
                                "itemName": "Sink and plumbing",
                                "conditionState": "good",
                                "isCompleted": True,
                            },
                            {
                                "itemName": "Cabinets",
                                "conditionState": "fair",
                                "isCompleted": True,
                                "notes": "Minor cosmetic wear; no repair needed.",
                            },
                        ],
                    }
                ],
            },
            label="owner-2-inspection",
        )

    def rent_follow_up(self):
        row = next(p for p in self.catalog["properties"] if p["key"] == "o1-late")
        self.write(
            "/api/tasks",
            {
                "expectedRevision": 0,
                "title": "Follow up unpaid rent — Birch Townhome",
                "priority": "high",
                "dueAtUtc": self.instant(0, zone=row["timeZone"]),
                "dueTimezone": row["timeZone"],
                "relatedEntityType": "lease",
                "relatedEntityId": row["leaseId"],
                "relatedLabel": row["name"],
                "notes": "Current month's rent remains unpaid. Contact tenant.",
            },
            label="owner-1-rent-follow-up",
        )


def prepare(args):
    root = args.workspace.expanduser().resolve()
    runtime = root.parent / f"{root.name}-demo-runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    config = runtime / "config.json"
    if not config.exists():
        save_json(config, {"localWorkspacePath": str(root)})
    journal = runtime / "seed-journal.json"
    if root.exists() and any(root.iterdir()) and not journal.exists():
        raise RuntimeError(
            "Destination is populated without a demo journal; choose an empty folder."
        )
    service = WorkspaceService.from_local_config(config)
    service.initialize()
    metadata = runtime / "seed-metadata.json"
    if metadata.exists():
        as_of = date.fromisoformat(json.loads(metadata.read_text())["asOf"])
    else:
        as_of = args.as_of or datetime.now(ZoneInfo(TIMEZONE)).date()
        save_json(metadata, {"asOf": as_of.isoformat(), "datasetVersion": 1})
        save_json(journal, {})
    return service, config, journal, runtime, as_of


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, required=True, help="Empty external workspace path"
    )
    parser.add_argument(
        "--as-of", type=date.fromisoformat, help="Demo date; default: today in Pacific time"
    )
    parser.add_argument("--local-config", type=Path, default=HERE / "config.local.json")
    args = parser.parse_args()
    service, config, journal, runtime, as_of = prepare(args)
    plan = json.loads((HERE / "dataset.json").read_text())
    with LocalApiClient(create_app(config)) as client:
        seed = Seeder(client, journal, as_of)
        seed.owners(plan)
        seed.providers(plan)
        for item in plan["properties"]:
            seed.property(item)
        seed.expenses()
        for item in plan["issues"]:
            seed.issue(item)
        seed.communications(plan)
        seed.inspection()
        seed.rent_follow_up()
        save_json(runtime / "catalog.json", {"asOf": as_of.isoformat(), **seed.catalog})
    service.open(integrity_check=True)
    save_json(args.local_config, {"localWorkspacePath": str(service.paths.root)})
    print(
        f"Demo ready: {service.paths.root}\nConfig: {config}\nCatalog: {runtime / 'catalog.json'}"
    )


if __name__ == "__main__":
    main()

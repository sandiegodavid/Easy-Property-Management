"""Exact ownership portions, retained history and portable command receipts."""

import json
import sqlite3
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from app.bootstrap.api import create_app
from app.bootstrap.operator_inventory_commands import inventory_fingerprint
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.portfolio.application.ports import PortfolioConflictError
from app.modules.portfolio.application.service import (
    OwnershipInput,
    PartyCreateCommand,
    PropertyCreateCommand,
)
from app.modules.portfolio.domain.models import validate_ownership_shares
from app.modules.portfolio.infrastructure.unit_of_work import _SQLitePortfolioTransaction
from app.modules.portfolio.tests import test_portfolio as fixtures
from app.modules.workspace.application.backup_service import BackupService
from app.modules.workspace.tests.test_backup_service import MemorySecretStore
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema
from app.platform.testing_client import LocalApiClient as TestClient


@pytest.fixture
def case():
    value = fixtures.PortfolioTests()
    value.setUp()
    try:
        yield value
    finally:
        value.doCleanups()


def command(shares=(6000, 4000)):
    owners = (OwnershipInput("local_operator", share_basis_points=shares[0]),)
    if len(shares) > 1:
        owners += (
            OwnershipInput(
                "client_owner",
                inline_party=PartyCreateCommand("individual", "Portion Owner"),
                share_basis_points=shares[1],
            ),
        )
    return PropertyCreateCommand(
        "Shared home",
        "10 Maple Street",
        "Portland",
        "US",
        "single_family_home",
        owners,
        region="OR",
    )


@pytest.mark.parametrize(
    "values", [[None], [None, None], [6000, None], [10000], [3333, 3333, 3334]]
)
def test_valid_exact_and_unknown_shares(values):
    validate_ownership_shares(values)


@pytest.mark.parametrize(
    "values",
    [[0], [-1], [10001], [True], [1.5], ["5000"], [5000], [6000, 6000], [10000, None], [9999]],
)
def test_invalid_share_values_or_aggregate(values):
    with pytest.raises(ValueError):
        validate_ownership_shares(values)


def test_share_only_change_is_revisioned_effective_dated_and_replayed(case):
    created = case.service.create_property(
        command(), expected_revision=0, idempotency_key="shares-create"
    )
    assert [item["sharePercent"] for item in created["ownerships"]] == ["60.00", "40.00"]
    owner = next(item["partyId"] for item in created["ownerships"] if item["partyId"])
    future = (date.fromisoformat(created["effectiveLocalDate"]) + timedelta(days=1)).isoformat()
    inputs = (
        OwnershipInput("local_operator", share_basis_points=5000),
        OwnershipInput("client_owner", owner, share_basis_points=5000),
    )
    changed = case.service.replace_ownerships(
        created["id"], inputs, future, expected_revision=1, idempotency_key="share-change"
    )
    assert changed["propertyRevision"] == 2
    timeline = [item.to_dict() for item in case.service.unit_of_work.ownerships(created["id"])]
    assert len(timeline) == 4
    assert {item["sharePercent"] for item in timeline if item["endsOn"] is None} == {"50.00"}
    assert all(item["endsOn"] == future for item in timeline if item["sharePercent"] != "50.00")
    assert (
        case.service.replace_ownerships(
            created["id"], inputs, future, expected_revision=1, idempotency_key="share-change"
        )
        == changed
    )
    with pytest.raises(PortfolioConflictError) as stale:
        case.service.replace_ownerships(
            created["id"], inputs, future, expected_revision=1, idempotency_key="stale-share-change"
        )
    assert stale.value.code == "portfolio_inventory_revision_conflict"
    with pytest.raises(PortfolioConflictError):
        case.service.replace_ownerships(
            created["id"],
            (
                replace(inputs[0], share_basis_points=4500),
                replace(inputs[1], share_basis_points=5500),
            ),
            future,
            expected_revision=1,
            idempotency_key="share-change",
        )
    validate_latest_schema(case.workspace.paths.database)


def test_unknowns_stay_unknown_and_noop_retains_revision(case):
    created = case.service.create_property(
        command((None, None)), expected_revision=0, idempotency_key="unknown-create"
    )
    assert all(item["sharePercent"] is None for item in created["ownerships"])
    inputs = tuple(
        OwnershipInput(item["ownerKind"], item["partyId"]) for item in created["ownerships"]
    )
    unchanged = case.service.replace_ownerships(
        created["id"],
        inputs,
        created["effectiveLocalDate"],
        expected_revision=1,
        idempotency_key="unknown-noop",
    )
    assert unchanged["propertyRevision"] == 1
    assert unchanged["updatedAt"] == created["updatedAt"]
    validate_latest_schema(case.workspace.paths.database)


def test_failure_after_owner_insert_rolls_back_parties_property_shares_and_receipt(case):
    original = _SQLitePortfolioTransaction.insert_ownership

    def fail(tx, item):
        original(tx, item)
        raise RuntimeError("after ownership write")

    with patch.object(_SQLitePortfolioTransaction, "insert_ownership", fail):
        with pytest.raises(RuntimeError, match="ownership write"):
            case.service.create_property(
                command(), expected_revision=0, idempotency_key="failed-shares"
            )
    with sqlite3.connect(case.workspace.paths.database) as connection:
        for table in (
            "properties",
            "property_ownerships",
            "parties",
            "portfolio_inventory_operations",
        ):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    validate_latest_schema(case.workspace.paths.database)


def test_schema_rejects_bad_storage_and_retained_validation_rejects_bad_totals(case):
    created = case.service.create_property(
        command(), expected_revision=0, idempotency_key="tamper-shares"
    )
    with sqlite3.connect(case.workspace.paths.database) as connection:
        for value in (0, 10001, 12.5, "invalid"):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE property_ownerships SET share_basis_points = ? WHERE id = ?",
                    (value, created["ownerships"][0]["id"]),
                )
        connection.execute(
            "UPDATE property_ownerships SET share_basis_points = 5900 WHERE id = ?",
            (created["ownerships"][0]["id"],),
        )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(case.workspace.paths.database)


def test_api_typed_percentages_and_batched_property_owner_projections(case):
    config = Path(case.temp.name) / "shares-api.json"
    config.write_text(json.dumps({"localWorkspacePath": str(case.workspace.paths.root)}))
    payload = {
        "displayName": "API shares",
        "addressLine1": "1 Main Street",
        "city": "Portland",
        "region": "OR",
        "countryCode": "US",
        "propertyType": "single_family_home",
        "expectedPropertyRevision": 0,
        "idempotencyKey": "api-shares",
        "ownerships": [
            {"ownerKind": "local_operator", "sharePercent": "60.00"},
            {
                "ownerKind": "client_owner",
                "sharePercent": "40.00",
                "inlineParty": {"partyKind": "individual", "displayName": "Shared Owner"},
            },
        ],
    }
    with TestClient(create_app(config)) as client:
        for value in ("NaN", "-1", "0", "100.01", "1.234", True):
            invalid = {
                **payload,
                "ownerships": [{"ownerKind": "local_operator", "sharePercent": value}],
            }
            assert client.post("/api/properties", json=invalid).status_code == 422
        invalid_total = {
            **payload,
            "ownerships": [
                {**payload["ownerships"][0], "sharePercent": "61.00"},
                payload["ownerships"][1],
            ],
        }
        assert client.post("/api/properties", json=invalid_total).status_code == 400
        response = client.post("/api/properties", json=payload)
        assert response.status_code == 201, response.text
        created = response.json()
        with sqlite3.connect(case.workspace.paths.database) as connection:
            retained = connection.execute(
                "SELECT request_fingerprint FROM portfolio_inventory_operations WHERE id = ?",
                (created["operationId"],),
            ).fetchone()[0]
        assert (
            inventory_fingerprint("create_property", None, payload, payload["idempotencyKey"])
            == retained
        )
        assert client.post("/api/properties", json=payload).json() == created
        owner = next(item["partyId"] for item in created["ownerships"] if item["partyId"])
        update_payload = {
            "expectedPropertyRevision": 1,
            "idempotencyKey": "api-share-update",
            "effectiveOn": created["effectiveLocalDate"],
            "ownerships": [
                {"ownerKind": "local_operator", "sharePercent": "60.0"},
                {"ownerKind": "client_owner", "partyId": owner, "sharePercent": "40"},
            ],
        }
        updated = client.put(f"/api/properties/{created['id']}/ownerships", json=update_payload)
        assert updated.status_code == 200, updated.text
        with sqlite3.connect(case.workspace.paths.database) as connection:
            retained = connection.execute(
                "SELECT request_fingerprint FROM portfolio_inventory_operations WHERE id = ?",
                (updated.json()["operationId"],),
            ).fetchone()[0]
        assert (
            inventory_fingerprint(
                "replace_ownerships",
                created["id"],
                update_payload,
                update_payload["idempotencyKey"],
            )
            == retained
        )
        directory = client.get("/api/operator/properties", params={"q": "API shares"})
        assert directory.status_code == 200, directory.text
        assert {item["sharePercent"] for item in directory.json()["items"][0]["owners"]} == {
            "40.00",
            "60.00",
        }
        for kind, identity in (("properties", created["id"]), ("owners", owner)):
            overview = client.get(f"/api/operator/{kind}/{identity}/overview")
            assert overview.status_code == 200, overview.text
            relationships = overview.json()["sections"]["relationships"]
            assert relationships["availability"] == "available", relationships
            assert relationships["items"][0]["sharePercent"] in {"40.00", "60.00"}
    validate_latest_schema(case.workspace.paths.database)


def test_encrypted_backup_preserves_exact_shares_history_and_original_response(case):
    created = case.service.create_property(
        command(), expected_revision=0, idempotency_key="backup-shares"
    )
    with sqlite3.connect(case.workspace.paths.database) as connection:
        expected = connection.execute("SELECT * FROM property_ownerships ORDER BY id").fetchall()
    backups = BackupService(
        case.workspace,
        AuditRecorder(case.audit),
        lambda db: AuditRecorder(SQLiteAuditRepository(db)),
        MemorySecretStore(),
    )
    backup = backups.create_backup(
        "ownership share portability", output_path=Path(case.temp.name) / "shares.epmbackup"
    )
    restored = backups.restore(
        backup.archive_path, "ownership share portability", Path(case.temp.name) / "restored-shares"
    )
    database = restored.workspace_path / "database" / "property-management.sqlite"
    validate_latest_schema(database)
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT * FROM property_ownerships ORDER BY id").fetchall()
            == expected
        )
        result = json.loads(
            connection.execute(
                "SELECT response_json FROM portfolio_inventory_operations WHERE id = ?",
                (created["operationId"],),
            ).fetchone()[0]
        )
        assert result == created

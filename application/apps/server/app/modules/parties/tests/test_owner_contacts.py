"""Shared owner contacts: atomic creation, address lifecycle and portability."""

import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.bootstrap.api import create_app
from app.modules.parties.application.service import (
    ContactMethodCommand,
    PartyContactService,
    PartyValidationError,
)
from app.modules.parties.tests.test_identity_commands import identities as identities, create
from app.modules.portfolio.tests.test_inventory_readiness import fixture as fixture, _create
from app.modules.portfolio.application.service import OwnershipInput, PartyCreateCommand
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema
from app.platform.testing_client import LocalApiClient as TestClient


@pytest.mark.parametrize("value", ["", " \n ", "bad\x00address", "x" * 1001])
def test_mailing_address_rejects_invalid_content(value):
    with pytest.raises(PartyValidationError):
        ContactMethodCommand("mailing_address", value)


def test_shared_address_lifecycle_replays_and_keeps_only_one_primary(identities):
    workspace, identity, _ = identities
    party = create(identity)
    contacts = PartyContactService(identity.unit_of_work)
    key = str(uuid4())
    command = ContactMethodCommand("mailing_address", " 10  Oak St\r\n Portland OR 97201 \n US ")
    address = contacts.add(party["id"], command, expected_revision=1, idempotency_key=key)
    assert address["displayValue"] == "10 Oak St\nPortland OR 97201\nUS"
    updated = contacts.update(
        party["id"],
        address["id"],
        ContactMethodCommand("mailing_address", "20 Pine Street\nPortland OR 97201\nUS"),
        expected_revision=2,
        idempotency_key=str(uuid4()),
    )
    assert updated["revision"] == 3
    assert contacts.add(party["id"], command, expected_revision=1, idempotency_key=key) == address
    second = contacts.add(
        party["id"],
        ContactMethodCommand("mailing_address", "Another address"),
        expected_revision=3,
        idempotency_key=str(uuid4()),
    )
    assert address["isPrimary"] is True
    assert second["isPrimary"] is False
    validate_latest_schema(workspace.paths.database)
    with pytest.raises(IntegrityError):
        with identity.unit_of_work.engine.begin() as connection:
            row = dict(
                connection.execute(
                    text("SELECT * FROM party_contact_methods WHERE id = :id"),
                    {"id": address["id"]},
                )
                .mappings()
                .one()
            )
            row.update(
                id=str(uuid4()), display_value="Another address", normalized_value="another address"
            )
            from app.modules.parties.infrastructure.sqlalchemy_models import PartyContactMethodModel

            connection.execute(PartyContactMethodModel.__table__.insert().values(**row))
    with identity.unit_of_work.engine.begin() as connection:
        connection.execute(
            text("UPDATE party_contact_methods SET normalized_value = 'rewritten' WHERE id = :id"),
            {"id": address["id"]},
        )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(workspace.paths.database)


def test_inline_owner_contacts_are_atomic_replayable_and_redacted(fixture):
    property = _create(fixture)
    config = Path(fixture.temp.name) / "contacts-api.json"
    config.write_text(json.dumps({"localWorkspacePath": str(fixture.workspace.paths.root)}))
    payload = {
        "expectedPropertyRevision": property["propertyRevision"],
        "idempotencyKey": "owner-with-contacts",
        "effectiveOn": property["effectiveLocalDate"],
        "ownerships": [
            {
                "ownerKind": "client_owner",
                "inlineParty": {
                    "partyKind": "individual",
                    "displayName": "Owner with contacts",
                    "contacts": [
                        {"methodKind": "email", "value": "Owner@example.test"},
                        {"methodKind": "phone", "value": "503-555-0199"},
                        {"methodKind": "phone", "value": "+1 503 555 0188", "label": "Mobile"},
                        {
                            "methodKind": "mailing_address",
                            "value": "10 Oak St\nPortland OR 97201\nUS",
                        },
                    ],
                },
            }
        ],
    }
    with TestClient(create_app(config)) as client:
        original = client.put(f"/api/properties/{property['id']}/ownerships", json=payload)
        assert original.status_code == 200, original.text
        assert (
            client.put(f"/api/properties/{property['id']}/ownerships", json=payload).json()
            == original.json()
        )
        owner_id = next(
            owner["partyId"] for owner in original.json()["ownerships"] if owner["endsOn"] is None
        )
        details = client.get(f"/api/parties/{owner_id}").json()
        assert len(details["contactMethods"]) == 4
        assert (
            next(
                contact
                for contact in details["contactMethods"]
                if contact["methodKind"] == "mailing_address"
            )["displayValue"]
            == "10 Oak St\nPortland OR 97201\nUS"
        )
        activity = client.get("/api/audit/events").json()["events"]
        contact_events = [
            event for event in activity if event["entityType"] == "party_contact_method"
        ]
        assert len(contact_events) == 4
        assert all(event["after"]["displayValue"] == "[redacted]" for event in contact_events)
        assert len({event["correlationId"] for event in contact_events}) == 1
        address_id = next(
            contact["id"]
            for contact in details["contactMethods"]
            if contact["methodKind"] == "mailing_address"
        )
        for role in ("tenants", "providers"):
            response = client.post(
                f"/api/{role}/from-party/{owner_id}",
                json={"expectedRevision": 0, "idempotencyKey": str(uuid4())},
            )
            assert response.status_code == 201, response.text
            response = client.get(f"/api/{role}/{owner_id}")
            assert response.status_code == 200, response.text
            assert (
                next(
                    contact["id"]
                    for contact in response.json()["contactMethods"]
                    if contact["methodKind"] == "mailing_address"
                )
                == address_id
            )
    validate_latest_schema(fixture.workspace.paths.database)
    # A failed owning workflow must leave neither the person nor their contacts.
    with fixture.service.unit_of_work.engine.connect() as connection:
        counts = [
            connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in ("parties", "party_contact_methods")
        ]
    with patch.object(
        fixture.service, "_new_ownerships", side_effect=RuntimeError("after contact write")
    ):
        with pytest.raises(RuntimeError, match="after contact write"):
            fixture.service.replace_ownerships(
                property["id"],
                (
                    OwnershipInput(
                        "client_owner",
                        inline_party=PartyCreateCommand("individual", "Rolled back owner"),
                        inline_contacts=(
                            ContactMethodCommand("mailing_address", "Unsaved address"),
                        ),
                    ),
                ),
                property["effectiveLocalDate"],
                expected_revision=2,
                idempotency_key="contacts-rollback",
            )
    with fixture.service.unit_of_work.engine.connect() as connection:
        assert counts == [
            connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in ("parties", "party_contact_methods")
        ]

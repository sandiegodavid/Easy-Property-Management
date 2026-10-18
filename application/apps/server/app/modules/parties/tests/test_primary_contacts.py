"""Shared contact cardinality, atomic primary selection and retained history."""

import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.modules.parties.application.service import (
    ContactMethodCommand,
    PartyConflictError,
    PartyContactService,
    PartyValidationError,
    PartyCreateCommand,
)
from app.modules.parties.tests.test_identity_commands import identities as identities
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema


def create(identity):
    return identity.create(
        PartyCreateCommand("individual", "Primary contacts"),
        expected_revision=0,
        idempotency_key=str(uuid4()),
    )


@pytest.mark.parametrize(
    "kind,first,second",
    [
        ("email", "first@example.test", "second@example.test"),
        ("phone", "5035550111", "5035550222"),
        ("mailing_address", "10 Oak Street", "20 Pine Street"),
    ],
)
def test_primary_switch_is_atomic_replayable_and_required_before_removal(
    identities, kind, first, second
):
    workspace, identity, _ = identities
    party = create(identity)
    service = PartyContactService(identity.unit_of_work)
    one = service.add(
        party["id"],
        ContactMethodCommand(kind, first),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    two = service.add(
        party["id"],
        ContactMethodCommand(kind, second),
        expected_revision=2,
        idempotency_key=str(uuid4()),
    )
    assert one["isPrimary"] is True and two["isPrimary"] is False
    with pytest.raises(PartyConflictError, match="another primary"):
        service.archive(
            party["id"],
            one["id"],
            confirmed=True,
            expected_revision=3,
            idempotency_key=str(uuid4()),
        )
    with pytest.raises(PartyConflictError, match="another primary"):
        service.update(
            party["id"],
            one["id"],
            ContactMethodCommand(kind, first, is_primary=False),
            expected_revision=3,
            idempotency_key=str(uuid4()),
        )
    key = str(uuid4())
    command = ContactMethodCommand(kind, second, is_primary=True)
    switched = service.update(
        party["id"], two["id"], command, expected_revision=3, idempotency_key=key
    )
    assert switched["revision"] == 4 and switched["isPrimary"] is True
    current = service.list(party["id"])
    assert [c["id"] for c in current if c["isPrimary"]] == [two["id"]]
    assert (
        service.update(party["id"], two["id"], command, expected_revision=3, idempotency_key=key)
        == switched
    )
    with pytest.raises(PartyConflictError):
        service.update(
            party["id"],
            two["id"],
            ContactMethodCommand(kind, second, is_primary=False),
            expected_revision=3,
            idempotency_key=key,
        )
    with pytest.raises(PartyConflictError):
        service.update(
            party["id"],
            one["id"],
            ContactMethodCommand(kind, first, is_primary=True),
            expected_revision=3,
            idempotency_key=str(uuid4()),
        )
    with pytest.raises(IntegrityError), identity.unit_of_work.engine.begin() as connection:
        connection.execute(
            text("UPDATE party_contact_methods SET is_primary = 1 WHERE id = :id"),
            {"id": one["id"]},
        )
    with identity.unit_of_work.engine.connect() as connection:
        correlation = connection.execute(
            text("SELECT correlation_id FROM party_command_operations WHERE id = :id"),
            {"id": switched["operationId"]},
        ).scalar_one()
        events = (
            connection.execute(
                text(
                    "SELECT * FROM audit_events WHERE correlation_id = :id AND entity_type = 'party_contact_method'"
                ),
                {"id": correlation},
            )
            .mappings()
            .all()
        )
    assert len(events) == 2
    assert {json.loads(e["after_snapshot"])["isPrimary"] for e in events} == {True, False}
    validate_latest_schema(workspace.paths.database)
    removed = service.archive(
        party["id"], one["id"], confirmed=True, expected_revision=4, idempotency_key=str(uuid4())
    )
    assert removed["status"] == "archived" and removed["isPrimary"] is False
    restored = service.restore(
        party["id"], one["id"], expected_revision=5, idempotency_key=str(uuid4())
    )
    assert restored["isPrimary"] is False
    service.archive(
        party["id"], one["id"], confirmed=True, expected_revision=6, idempotency_key=str(uuid4())
    )
    service.archive(
        party["id"], two["id"], confirmed=True, expected_revision=7, idempotency_key=str(uuid4())
    )
    last = service.restore(
        party["id"], one["id"], expected_revision=8, idempotency_key=str(uuid4())
    )
    assert last["isPrimary"] is True
    validate_latest_schema(workspace.paths.database)


def test_primary_switch_rolls_back_both_contacts_receipt_and_audits(identities):
    workspace, identity, _ = identities
    party = create(identity)
    service = PartyContactService(identity.unit_of_work)
    one = service.add(
        party["id"],
        ContactMethodCommand("email", "first@example.test"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    two = service.add(
        party["id"],
        ContactMethodCommand("email", "second@example.test"),
        expected_revision=2,
        idempotency_key=str(uuid4()),
    )
    before = service.list(party["id"])
    with patch.object(PartyContactService, "_finish", side_effect=RuntimeError("receipt failure")):
        with pytest.raises(RuntimeError, match="receipt failure"):
            service.update(
                party["id"],
                two["id"],
                ContactMethodCommand("email", "second@example.test", is_primary=True),
                expected_revision=3,
                idempotency_key=str(uuid4()),
            )
    assert service.list(party["id"]) == before
    assert next(c for c in before if c["id"] == one["id"])["isPrimary"] is True
    validate_latest_schema(workspace.paths.database)


def test_primary_retained_data_rejects_missing_primary(identities):
    workspace, identity, _ = identities
    party = create(identity)
    service = PartyContactService(identity.unit_of_work)
    service.add(
        party["id"],
        ContactMethodCommand("email", "first@example.test"),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    with identity.unit_of_work.engine.begin() as connection:
        connection.execute(
            text("UPDATE party_contact_methods SET is_primary = 0 WHERE party_id = :id"),
            {"id": party["id"]},
        )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(workspace.paths.database)


def test_initial_primary_and_add_primary_use_shared_selection_rules(identities):
    workspace, identity, _ = identities
    party = identity.create(
        PartyCreateCommand("individual", "Explicit primary"),
        expected_revision=0,
        idempotency_key=str(uuid4()),
        contacts=(
            ContactMethodCommand("email", "one@example.test"),
            ContactMethodCommand("email", "two@example.test", is_primary=True),
        ),
    )
    service = PartyContactService(identity.unit_of_work)
    assert [c["displayValue"] for c in service.list(party["id"]) if c["isPrimary"]] == [
        "two@example.test"
    ]
    added = service.add(
        party["id"],
        ContactMethodCommand("email", "three@example.test", is_primary=True),
        expected_revision=1,
        idempotency_key=str(uuid4()),
    )
    assert added["revision"] == 2
    assert [c["displayValue"] for c in service.list(party["id"]) if c["isPrimary"]] == [
        "three@example.test"
    ]
    validate_latest_schema(workspace.paths.database)
    with pytest.raises(PartyConflictError):
        identity.create(
            PartyCreateCommand("individual", "Invalid primary choices"),
            expected_revision=0,
            idempotency_key=str(uuid4()),
            contacts=(
                ContactMethodCommand("phone", "5035550111", is_primary=True),
                ContactMethodCommand("phone", "5035550222", is_primary=True),
            ),
        )


@pytest.mark.parametrize("value", [1, 0, "true", []])
def test_primary_command_rejects_non_boolean(value):
    with pytest.raises(PartyValidationError):
        ContactMethodCommand("email", "test@example.test", is_primary=value)

"""Provider-owned IDs: bounded metadata, optional numbers and durable history."""

import json
from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.bootstrap.api import create_app
from app.modules.vendors.application.service import (
    ProviderError,
    ProviderLifecycleConflict,
    ProviderProfilePatchCommand,
    ProviderSearchCommand,
)
from app.modules.vendors.domain.official_ids import ProviderOfficialId
from app.modules.vendors.domain.audit_policy import PROVIDER_ACTIVITY_SNAPSHOT_POLICY
from app.modules.vendors.tests.test_command_readiness import (
    provider_services as provider_services,
    create,
)
from app.platform.migration_errors import MigrationSchemaError
from app.platform.product_migrations import validate_latest_schema
from app.platform.testing_client import LocalApiClient


ID = ProviderOfficialId("license", "US", "A123", "OR", "2030-10-31", "OR-A123")


@pytest.mark.parametrize(
    "fields",
    [
        {"document_type": "unsupported"},
        {"document_number": "X" * 81},
        {"document_number": "OR-B456"},
        {"document_number": "OR-A123\n"},
        {"last_four": "123456789"},
        {"expires_on": "2027-02-30"},
    ],
)
def test_rejects_malformed_numbers_and_metadata(fields):
    with pytest.raises(ValueError):
        replace(ID, **fields)


@pytest.mark.parametrize("kind", sorted(ProviderOfficialId.document_types))
def test_every_provider_id_type_can_retain_an_optional_full_number(kind):
    assert replace(ID, document_type=kind).to_dict()["documentNumber"] == "OR-A123"
    assert replace(ID, document_type=kind, document_number=None).to_dict()["documentNumber"] is None


def test_profile_id_replay_conflict_noop_rollback_and_retained_history(provider_services):
    workspace, service, audit = provider_services
    first = create(service)
    party = first["party"]["id"]
    assert first["profile"]["officialIds"] == []
    command, key = ProviderProfilePatchCommand(official_ids=(ID,)), str(uuid4())
    changed = service.update_profile(party, command, expected_revision=1, idempotency_key=key)
    assert changed["profile"]["officialIds"] == [ID.to_dict()]
    assert changed["revision"] == 2
    assert (
        service.update_profile(party, command, expected_revision=1, idempotency_key=key) == changed
    )
    assert service.recover(key=key) == changed
    with pytest.raises(ProviderLifecycleConflict):
        service.update_profile(
            party,
            ProviderProfilePatchCommand(official_ids=()),
            expected_revision=1,
            idempotency_key=key,
        )
    with pytest.raises(ProviderLifecycleConflict):
        service.update_profile(party, command, expected_revision=1, idempotency_key=str(uuid4()))
    noop = service.update_profile(party, command, expected_revision=2, idempotency_key=str(uuid4()))
    assert noop["revision"] == 2
    assert len(audit.history("provider_profile", party)) == 2
    with patch.object(
        service.unit_of_work.recorder,
        "record_change",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            service.update_profile(
                party,
                ProviderProfilePatchCommand(official_ids=()),
                expected_revision=2,
                idempotency_key=str(uuid4()),
            )
    assert service.detail(party)["profile"] == changed["profile"]
    summary = service.page(ProviderSearchCommand())["items"][0]["profile"]
    assert summary["officialIds"][0]["documentNumber"] is None
    assert (
        PROVIDER_ACTIVITY_SNAPSHOT_POLICY.redact(changed["profile"])["officialIds"] == "[redacted]"
    )
    with pytest.raises(ProviderError):
        ProviderProfilePatchCommand(official_ids=(ID, ID))
    with pytest.raises(ProviderError):
        ProviderProfilePatchCommand(
            official_ids=tuple(
                replace(ID, last_four=f"{i:04}", document_number=None) for i in range(11)
            )
        )
    validate_latest_schema(workspace.paths.database)
    with service.unit_of_work.engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(text("UPDATE provider_profiles SET official_ids_json='{}'"))
        connection.execute(
            text("UPDATE provider_profiles SET official_ids_json=:ids"),
            {
                "ids": json.dumps([{**ID.__dict__, "last_four": "123456789"}]),
            },
        )
    with pytest.raises(MigrationSchemaError):
        validate_latest_schema(workspace.paths.database)


def test_http_contract_and_activity_privacy(provider_services):
    workspace, service, _ = provider_services
    party = create(service)["party"]["id"]
    workspace.config.config_path.write_text(
        json.dumps({"localWorkspacePath": str(workspace.paths.root)})
    )
    with LocalApiClient(create_app(workspace.config.config_path)) as client:
        payload = {
            "expectedRevision": 1,
            "idempotencyKey": str(uuid4()),
            "officialIds": [ID.to_dict()],
        }
        response = client.patch(f"/api/providers/{party}", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["profile"]["officialIds"] == [ID.to_dict()]
        for invalid in (
            {**ID.to_dict(), "documentNumber": "X" * 81},
            {**ID.to_dict(), "lastFour": "123456789"},
            {**ID.to_dict(), "fullNumber": "secret"},
        ):
            assert (
                client.patch(
                    f"/api/providers/{party}", json={**payload, "officialIds": [invalid]}
                ).status_code
                == 422
            )
        activity = client.get("/api/audit/events")
        assert activity.status_code == 200
        assert "OR-A123" not in activity.text
        history = client.get("/api/audit/events/provider_profile/" + party)
        assert history.status_code == 200
        assert "OR-A123" in history.text

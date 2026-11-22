"""Legacy draft authority cannot be composed while session admission is unavailable."""

from unittest.mock import Mock

import pytest

from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.hosted_access.infrastructure.draft_leases import (
    HostedRecoveryAuthority,
    SQLiteDraftLeaseStore,
)
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore


def test_legacy_draft_adapter_is_never_constructed(deployment_values, tmp_path):
    deployment = HostedDeployment.model_validate(deployment_values)
    before = list(tmp_path.iterdir())
    with pytest.raises(HostedAccessError) as caught:
        SQLiteDraftLeaseStore(SQLiteHostedSessionStore(deployment))
    assert caught.value.code == "hosted_access_unavailable"
    assert caught.value.status == 503
    assert list(tmp_path.iterdir()) == before


def test_missing_hosted_actor_cannot_enter_recovery_mutation():
    store, clock = Mock(), Mock()
    authority = HostedRecoveryAuthority(store, clock)
    with pytest.raises(HostedAccessError) as caught:
        authority.mutation("private-draft")
    assert caught.value.code == "hosted_draft_lease_conflict"
    store.guard.assert_not_called()
    clock.assert_not_called()


def test_local_mode_draft_lease_route_returns_404_not_500():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.modules.hosted_access.api.draft_leases import build_draft_lease_router
    from app.platform.api_errors import register_api_error_handlers

    app = FastAPI()
    register_api_error_handlers(app)
    app.include_router(build_draft_lease_router(service=None))
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/api/hosted/drafts/00000000-0000-4000-8000-000000000001/lease",
        json={"token": "a" * 43, "expectedRevision": 1},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "hosted_mode_required"

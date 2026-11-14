"""Retired hosted composition fails closed; ordinary local Operator stays usable."""

import json
from unittest.mock import Mock
from uuid import uuid4

from fastapi import FastAPI
import pytest

from app.bootstrap.api import create_app
from app.bootstrap.hosted_access import compose_hosted_access
from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.domain.models import HostedAccessError
from app.modules.workspace.application.service import WorkspaceService
from app.platform.browser_transport import BrowserTransportPolicy
from app.platform.testing_client import LocalApiClient


def test_retired_composition_denies_before_storage_identity_or_recovery_setup(
    deployment_values, tmp_path, monkeypatch
):
    deployment = HostedDeployment.model_validate(deployment_values)
    app, runtime = FastAPI(), Mock()
    storage, verifier = Mock(), Mock()
    monkeypatch.setattr(
        "app.modules.hosted_access.infrastructure.storage_budget.build_storage_budget", storage
    )
    monkeypatch.setattr(
        "app.modules.hosted_access.infrastructure.cloudflare_identity.CloudflareIdentityVerifier",
        verifier,
    )
    routes = list(app.routes)
    with pytest.raises(HostedAccessError) as caught:
        compose_hosted_access(app, deployment, runtime)
    assert caught.value.code == "hosted_access_unavailable"
    assert caught.value.status == 503
    storage.assert_not_called()
    verifier.assert_not_called()
    assert runtime.mock_calls == []
    assert app.routes == routes
    assert app.user_middleware == []
    assert not hasattr(app.state, "hosted_storage_budget")
    assert list(tmp_path.iterdir()) == []


def test_hosted_mode_cannot_combine_local_transport(deployment_values, tmp_path, monkeypatch):
    deployment = HostedDeployment.model_validate(deployment_values)
    monkeypatch.setattr("app.bootstrap.api.load_hosted_deployment", lambda _: deployment)
    config = tmp_path / "local.json"
    config.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "workspace")}))
    with pytest.raises(ValueError, match="cannot be combined"):
        create_app(
            tmp_path / "local.json",
            hosted_deployment_path=tmp_path / "protected.json",
            transport_policy=BrowserTransportPolicy(),
        )


def test_local_operator_bootstrap_and_task_creation_remain_usable(tmp_path, monkeypatch):
    config = tmp_path / "local.json"
    config.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "workspace")}))
    manifest = WorkspaceService.from_local_config(config).initialize()
    hosted = Mock(side_effect=AssertionError("Local launch must never compose hosted access"))
    monkeypatch.setattr("app.bootstrap.api.compose_hosted_access", hosted)
    with LocalApiClient(create_app(config)) as client:
        bootstrap = client.get("/api/operator/bootstrap")
        assert bootstrap.status_code == 200, bootstrap.text
        assert bootstrap.json()["workspaceId"] == str(manifest.workspace_id)
        assert client.get("/api/operator/recovery").status_code == 200
        body = {
            "title": "Local Operator task",
            "expectedRevision": 0,
            "idempotencyKey": str(uuid4()),
        }
        created = client.post("/api/tasks", json=body)
        assert created.status_code == 201, created.text
        assert client.post("/api/tasks", json=body).json() == created.json()
    hosted.assert_not_called()
    assert not (tmp_path / "hosted-access.sqlite").exists()


def test_real_app_refuses_retired_hosted_composition(deployment_values, tmp_path, monkeypatch):
    config = tmp_path / "local.json"
    config.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "workspace")}))
    manifest = WorkspaceService.from_local_config(config).initialize()
    deployment = HostedDeployment.model_validate(
        {**deployment_values, "workspace_id": manifest.workspace_id}
    )
    monkeypatch.setattr("app.bootstrap.api.load_hosted_deployment", lambda _: deployment)
    storage = Mock(side_effect=AssertionError("Retired composition must not probe storage"))
    monkeypatch.setattr(
        "app.modules.hosted_access.infrastructure.storage_budget.build_storage_budget", storage
    )
    with pytest.raises(HostedAccessError) as caught:
        create_app(config, hosted_deployment_path=tmp_path / "protected.json")
    assert caught.value.code == "hosted_access_unavailable"
    assert caught.value.status == 503
    assert not deployment.administration_database.exists()
    storage.assert_not_called()

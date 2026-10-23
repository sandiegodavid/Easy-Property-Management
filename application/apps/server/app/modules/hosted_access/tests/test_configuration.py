"""Reject ambiguous or unsafe deployment identity before serving requests."""

import json
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.infrastructure.configuration import (
    HostedConfigurationError,
    load_hosted_deployment,
    validate_workspace_binding,
)
from app.platform.config import LocalConfig
from app.modules.workspace.application.service import WorkspaceService


@pytest.mark.parametrize(
    "origin",
    [
        "http://demo-a.example.com",
        "https://demo-a.example.com/",
        "https://demo-a.example.com:443",
        "https://user@demo-a.example.com",
        "https://demo-a.example.com?x=1",
        "https://demo-a.example.com#fragment",
        "https://127.0.0.1:8001",
        "https://demo-a..example.com",
        "https://demo-a.example.com\n",
    ],
)
def test_reject_ambiguous_origins(deployment_values, origin):
    with pytest.raises(ValidationError):
        HostedDeployment.model_validate({**deployment_values, "public_origin": origin})


@pytest.mark.parametrize(
    "changes",
    [
        {"deployment_mode": "local"},
        {"unexpected_secret": "must not appear in errors"},
        {"administration_database": "relative.sqlite"},
        {"capabilities": ["records.read", "host.admin"]},
        {"capabilities": ["records.read", "files.write"]},
        {"allowed_email": "Operator <operator@example.com>"},
        {"identity_audience": "unqualified-audience"},
        {"expires_at": "2099-01-01T00:00:00Z"},
        {"enabled_at": "2026-10-23T00:00:00"},
    ],
)
def test_reject_invalid_configuration(deployment_values, changes):
    with pytest.raises(ValidationError):
        HostedDeployment.model_validate({**deployment_values, **changes})


def test_binding_validates_existing_identity_without_creating_admin_database(
    tmp_path, deployment_values
):
    service = WorkspaceService(LocalConfig(tmp_path / "local.json", tmp_path / "workspace"))
    manifest = service.initialize()
    deployment = HostedDeployment.model_validate(
        {**deployment_values, "workspace_id": manifest.workspace_id}
    )
    validate_workspace_binding(deployment, service)
    assert not deployment.administration_database.exists()
    with pytest.raises(HostedConfigurationError, match="does not match"):
        validate_workspace_binding(deployment.model_copy(update={"workspace_id": uuid4()}), service)
    with pytest.raises(HostedConfigurationError, match="outside portable"):
        validate_workspace_binding(
            deployment.model_copy(
                update={"administration_database": service.paths.root / "authorization.sqlite"}
            ),
            service,
        )


def test_invalid_file_is_safe_and_does_not_disclose_submitted_secret(tmp_path, monkeypatch):
    config = tmp_path / "hosted.json"
    config.write_text(json.dumps({"secret": "do-not-disclose"}))
    monkeypatch.setattr(
        "app.modules.hosted_access.infrastructure.configuration._secure_file", Mock()
    )
    with pytest.raises(HostedConfigurationError) as caught:
        load_hosted_deployment(config)
    assert "do-not-disclose" not in str(caught.value)


def test_secure_loader_rejects_symlink_and_relative_path(tmp_path):
    target = tmp_path / "actual.json"
    target.write_text("{}")
    link = tmp_path / "hosted.json"
    link.symlink_to(target)
    with pytest.raises(HostedConfigurationError, match="regular file"):
        load_hosted_deployment(link)
    with pytest.raises(HostedConfigurationError, match="absolute"):
        load_hosted_deployment(Path("hosted.json"))

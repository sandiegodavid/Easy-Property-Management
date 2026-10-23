"""Expired/broken workspaces cannot prevent private administrator revocation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from app.modules.hosted_access.application.configuration import (
    HostedDeployment,
    HostedConfigurationError,
)
from app.modules.hosted_access.infrastructure.admin import administer
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore


@pytest.mark.parametrize("action", ["disable", "revoke", "enrollments"])
def test_admin_can_fence_after_expiry_without_opening_business_data(
    deployment_values, monkeypatch, action
):
    deployment = HostedDeployment.model_validate(deployment_values)
    SQLiteHostedSessionStore.initialize(deployment)
    expired = deployment.model_copy(
        update={
            "enabled_at": datetime.now(UTC) - timedelta(days=15),
            "expires_at": datetime.now(UTC) - timedelta(days=1),
        }
    )
    monkeypatch.setattr(
        "app.modules.hosted_access.infrastructure.admin.load_hosted_deployment", lambda _: expired
    )
    workspace = Mock()
    workspace.open.side_effect = AssertionError("Revocation must not open a broken workspace")
    result = administer(deployment.administration_database, workspace, action, None)
    assert result
    workspace.open.assert_not_called()


def test_reactivation_still_requires_valid_current_deployment(deployment_values, monkeypatch):
    deployment = HostedDeployment.model_validate(deployment_values)
    monkeypatch.setattr(
        "app.modules.hosted_access.infrastructure.admin.load_hosted_deployment",
        lambda _: deployment,
    )
    monkeypatch.setattr(
        "app.modules.hosted_access.infrastructure.admin.validate_workspace_binding",
        Mock(side_effect=HostedConfigurationError("expired")),
    )
    with pytest.raises(HostedConfigurationError, match="expired"):
        administer(deployment.administration_database, Mock(), "activate", "subject")

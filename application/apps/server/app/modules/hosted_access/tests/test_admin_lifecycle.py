"""Retired CLI actions never open business data or mutate private stores."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from app.modules.hosted_access.application.configuration import (
    HostedDeployment,
)
from app.modules.hosted_access.infrastructure.admin import administer
from app.modules.hosted_access.domain.models import HostedAccessError


@pytest.mark.parametrize("action", ["disable", "revoke", "enrollments"])
def test_retired_admin_actions_deny_after_expiry_without_opening_business_data(
    deployment_values, monkeypatch, action
):
    deployment = HostedDeployment.model_validate(deployment_values)
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
    with pytest.raises(HostedAccessError) as caught:
        administer(deployment.administration_database, workspace, action, None)
    assert caught.value.code == "hosted_access_unavailable"
    assert caught.value.status == 503
    assert not deployment.administration_database.exists()
    workspace.open.assert_not_called()


@pytest.mark.parametrize(
    "action", ["initialize", "activate", "disable", "revoke", "rebind", "enrollments"]
)
def test_retired_admin_actions_never_mutate_existing_store(
    deployment_values, monkeypatch, tmp_path, action
):
    deployment = HostedDeployment.model_validate(deployment_values)
    path = deployment.administration_database
    path.write_bytes(b"private current-store evidence")
    path.chmod(0o600)
    before = path.stat()
    monkeypatch.setattr(
        "app.modules.hosted_access.infrastructure.admin.load_hosted_deployment",
        lambda _: deployment,
    )
    workspace = Mock()
    for _ in range(2):
        with pytest.raises(HostedAccessError) as caught:
            administer(path, workspace, action, "subject")
        assert caught.value.code == "hosted_access_unavailable"
        assert caught.value.status == 503
    assert path.read_bytes() == b"private current-store evidence"
    assert path.stat() == before
    assert list(tmp_path.iterdir()) == [path]
    workspace.open.assert_not_called()

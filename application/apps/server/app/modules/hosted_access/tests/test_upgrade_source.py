"""Real retained-workspace and access-schema probes never initialize missing data."""

import json
from uuid import uuid4

import pytest

from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.application.maintenance import MaintenanceCommand
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore
from app.modules.hosted_admin.infrastructure import upgrade_source
from app.modules.workspace.application.service import WorkspaceService, WorkspaceNotInitializedError


@pytest.fixture
def probe(tmp_path, deployment_values, monkeypatch):
    local = tmp_path / "local.json"
    local.write_text(json.dumps({"localWorkspacePath": str(tmp_path / "volume/workspace")}))
    workspace = WorkspaceService.from_local_config(local)
    workspace.initialize(workspace_id=deployment_values["workspace_id"])
    deployment = HostedDeployment.model_validate(deployment_values)
    SQLiteHostedSessionStore.initialize(deployment)
    monkeypatch.setattr(upgrade_source, "load_hosted_deployment", lambda _: deployment)
    return workspace, deployment, local


def test_probe_reads_live_workspace_but_stopped_probe_requires_owned_pause(probe):
    workspace, deployment, local = probe
    result = upgrade_source.check(None, local, stopped=False)
    assert result == {
        "workspace_id": workspace.open().workspace_id,
        "compatible": True,
        "maintenance_owner": None,
    }
    with pytest.raises(ValueError, match="owned maintenance"):
        upgrade_source.check(None, local, stopped=True)
    access = SQLiteHostedSessionStore(deployment)
    try:
        owner = str(uuid4())
        access.maintenance.execute(
            MaintenanceCommand(
                id=str(uuid4()),
                owner=owner,
                action="pause",
                expected_revision=0,
                expected_admin_revision=0,
                expected_binding_revision=0,
                expected_fence=0,
                authority_reference="owner:1",
                reason="Upgrade",
                release="a" * 64,
            )
        )
    finally:
        access.engine.dispose()
    assert upgrade_source.check(None, local, stopped=True)["maintenance_owner"] == owner


def test_probe_refuses_wrong_workspace_and_missing_or_changed_schema(probe):
    workspace, _deployment, local = probe
    workspace.paths.manifest.unlink()
    with pytest.raises(WorkspaceNotInitializedError):
        upgrade_source.check(None, local, stopped=False)
    assert not workspace.paths.manifest.exists()

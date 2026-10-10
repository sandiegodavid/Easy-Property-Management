"""Readiness reasons stay safe and distinct at the real bootstrap boundary."""

import json

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.api import create_app
from app.modules.workspace.application.service import WorkspaceService


@pytest.mark.parametrize("state", ["missing", "invalid", "migration_required", "ready", "busy"])
def test_bootstrap_workspace_reasons(tmp_path, state):
    config = tmp_path / "config.json"
    root = tmp_path / "workspace"
    config.write_text(json.dumps({"localWorkspacePath": str(root)}))
    if state != "missing":
        WorkspaceService.from_local_config(config).initialize()
    manifest = root / "workspace.json"
    if state == "invalid":
        manifest.write_text("not json")
    if state == "migration_required":
        value = json.loads(manifest.read_text())
        value["formatVersion"] = 999
        manifest.write_text(json.dumps(value))
    with TestClient(create_app(config), base_url="http://127.0.0.1:8000") as client:
        if state == "busy":
            with TestClient(create_app(config), base_url="http://127.0.0.1:8000") as other:
                result = other.get("/api/operator/bootstrap").json()
        else:
            result = client.get("/api/operator/bootstrap").json()
        assert result["canWrite"] is (state == "ready")
        assert result["reasonCode"] == (None if state == "ready" else "workspace_" + state)
        if state != "ready":
            assert result["preferences"] is None
            assert str(root) not in json.dumps(result)
    if state == "missing":
        assert not root.exists()

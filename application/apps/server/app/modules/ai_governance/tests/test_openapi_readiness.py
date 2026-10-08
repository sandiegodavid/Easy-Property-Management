"""Production contract discovery must not initialize or open a workspace."""

import json
from unittest.mock import patch

from app.bootstrap.api import create_app
from app.modules.workspace.application.runtime import WorkspaceRuntime
from app.modules.workspace.application.service import WorkspaceService


def test_production_openapi_is_reproducible_without_workspace_access(tmp_path):
    config = tmp_path / "config.json"
    workspace = tmp_path / "not-initialized"
    config.write_text(json.dumps({"localWorkspacePath": str(workspace)}), encoding="utf-8")
    with (
        patch.object(WorkspaceService, "open", side_effect=AssertionError("workspace opened")),
        patch.object(WorkspaceService, "initialize", side_effect=AssertionError("initialized")),
        patch.object(WorkspaceRuntime, "start", side_effect=AssertionError("runtime started")),
    ):
        first = create_app(config).openapi()
        second = create_app(config).openapi()
    assert first == second
    assert not workspace.exists()
    for path, methods in first["paths"].items():
        if not path.startswith("/api/ai/"):
            continue
        for operation in methods.values():
            assert operation["operationId"]
            for code, response in operation["responses"].items():
                if code.startswith("2") and code != "204":
                    assert response["content"]["application/json"]["schema"]

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.bootstrap.api import create_app


class WorkspaceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.workspace_path = root / "workspace"
        self.config_path = root / "config.local.json"
        self.config_path.write_text(
            json.dumps({"localWorkspacePath": str(self.workspace_path)}),
            encoding="utf-8",
        )
        self.client = TestClient(create_app(self.config_path))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_workspace_initialization_is_explicit_and_then_reported(self) -> None:
        unavailable = self.client.get("/health")
        self.assertEqual(unavailable.status_code, 503)

        initialized = self.client.post("/api/workspace/initialize")
        self.assertEqual(initialized.status_code, 201)
        self.assertEqual(initialized.json()["path"], str(self.workspace_path.resolve()))
        self.assertIn("workspaceId", initialized.json()["manifest"])

        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        reported = self.client.get("/api/workspace")
        self.assertEqual(reported.status_code, 200)
        self.assertEqual(reported.json()["manifest"]["formatVersion"], 1)

    def test_database_failure_returns_a_controlled_api_error(self) -> None:
        self.client.post("/api/workspace/initialize")
        with patch(
            "app.modules.workspace.infrastructure.sqlite_store.sqlite3.connect",
            side_effect=sqlite3.DatabaseError("database unavailable"),
        ):
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 500)
        self.assertIn("Workspace database is invalid", response.json()["detail"])

    def test_lifespan_runs_integrity_validation_and_retains_a_writer_lock(self) -> None:
        unavailable = self.client.get("/health")
        self.assertEqual(unavailable.status_code, 503)

        initialized = self.client.post("/api/workspace/initialize")
        self.assertEqual(initialized.status_code, 201)
        self.assertEqual(self.client.get("/health").status_code, 200)

        with TestClient(create_app(self.config_path)) as second_client:
            blocked = second_client.get("/health")
            self.assertEqual(blocked.status_code, 503)
            self.assertIn("already using this workspace", blocked.json()["detail"])
            self.assertEqual(second_client.post("/api/workspace/initialize").status_code, 503)

    def test_write_endpoints_fail_closed_without_lifespan_startup(self) -> None:
        client = TestClient(create_app(self.config_path))

        response = client.post("/api/workspace/initialize")

        self.assertEqual(response.status_code, 503)

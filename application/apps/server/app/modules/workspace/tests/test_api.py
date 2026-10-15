from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.platform.testing_client import LocalApiClient as TestClient

from app.bootstrap.api import _automatic_backup_scheduler, create_app


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

    def test_bootstrap_composes_the_internal_intake_admission_port(self) -> None:
        self.assertTrue(callable(self.client.app.state.intake_admission.admit))

    def test_sidebar_backup_status_is_bounded_and_read_only(self) -> None:
        self.assertEqual(self.client.get("/api/workspace/backup-status").status_code, 503)
        self.client.post("/api/workspace/initialize")
        response = self.client.get("/api/workspace/backup-status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"lastSuccessAt": None, "needsAttention": False})
        with patch(
            "app.modules.workspace.application.backup_service.BackupService.backup_status",
            return_value={
                "lastSuccessAt": "2026-10-14T15:10:00+00:00",
                "lastFailure": None,
                "lastRetentionFailure": {"reason": "private path"},
                "history": [{"destination": "private path"}],
            },
        ):
            response = self.client.get("/api/workspace/backup-status")
        self.assertEqual(
            response.json(),
            {"lastSuccessAt": "2026-10-14T15:10:00Z", "needsAttention": True},
        )

    def test_sidebar_backup_status_sanitizes_read_failure(self) -> None:
        from app.modules.workspace.application.backup_service import BackupError

        self.client.post("/api/workspace/initialize")
        with patch(
            "app.modules.workspace.application.backup_service.BackupService.backup_status",
            side_effect=BackupError("private filesystem details"),
        ):
            response = self.client.get("/api/workspace/backup-status")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Backup status is unavailable."})

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

    def test_task_create_requires_a_json_boolean_for_is_all_day(self) -> None:
        self.assertEqual(self.client.post("/api/workspace/initialize").status_code, 201)
        for invalid_value in ("false", "yes", 0, 1):
            response = self.client.post(
                "/api/tasks", json={"title": "Inspection", "isAllDay": invalid_value}
            )
            self.assertEqual(response.status_code, 422)

    def test_scheduler_cancellation_waits_for_an_inflight_backup_worker(self) -> None:
        started = threading.Event()
        release = threading.Event()

        class Runtime:
            writer_lock_acquired = True
            ready = True

        class Backups:
            def run_due_automatic_backup(self) -> None:
                started.set()
                release.wait(timeout=5)

        async def exercise() -> None:
            scheduler = asyncio.create_task(_automatic_backup_scheduler(Backups(), Runtime()))
            while not started.is_set():
                await asyncio.sleep(0.01)
            scheduler.cancel()
            await asyncio.sleep(0.05)
            self.assertFalse(scheduler.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await scheduler

        asyncio.run(exercise())

    def test_scheduler_records_unexpected_worker_failure_and_keeps_running(self) -> None:
        recorded = threading.Event()

        class Runtime:
            writer_lock_acquired = True
            ready = True

        class Backups:
            def run_due_automatic_backup(self) -> None:
                raise RuntimeError("unexpected worker failure")

            def record_scheduler_failure(self, error: Exception) -> None:
                self.error = error
                recorded.set()

        async def exercise() -> None:
            scheduler = asyncio.create_task(_automatic_backup_scheduler(Backups(), Runtime()))
            while not recorded.is_set():
                await asyncio.sleep(0.01)
            self.assertFalse(scheduler.done())
            scheduler.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await scheduler

        asyncio.run(exercise())

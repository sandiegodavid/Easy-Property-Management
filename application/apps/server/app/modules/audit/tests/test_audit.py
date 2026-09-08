from __future__ import annotations

import sqlite3
import json
import math
from dataclasses import replace
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.audit.api.router import build_router
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.domain.models import AuditEvent, AuditSnapshotPolicyRegistry, DefaultAuditSnapshotPolicy, changed_paths
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.workspace.application.service import WorkspaceService
from app.modules.workspace.application.runtime import WorkspaceRuntime
from app.modules.files.application.service import FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.platform.config import LocalConfig
from app.platform.product_migrations import ProductSchemaError, validate_latest_schema


class AuditLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); config = root / "config.json"; config.write_text(json.dumps({"localWorkspacePath": str(root / "workspace")}), encoding="utf-8")
        self.workspace = WorkspaceService(LocalConfig(config, root / "workspace"))
        self.manifest = self.workspace.initialize(); self.repository = SQLiteAuditRepository(self.workspace.paths.database)
        self.recorder = AuditRecorder(self.repository)

    def test_workspace_creation_and_domain_change_are_audited_atomically(self) -> None:
        self.assertEqual(self.repository.history("workspace", self.manifest.workspace_id)[0].action, "created")
        with closing(sqlite3.connect(self.workspace.paths.database)) as connection:
            connection.execute("CREATE TABLE ledger_probe (id TEXT PRIMARY KEY, amount INTEGER NOT NULL)")
            connection.execute("INSERT INTO ledger_probe VALUES ('rent', 1800)")
            connection.execute("UPDATE ledger_probe SET amount = 1900 WHERE id = 'rent'")
            event = self.recorder.record_change(connection, entity_type="rent", entity_id="rent", action="updated", before={"amount": 1800}, after={"amount": 1900})
            connection.commit()
        self.assertEqual(self.repository.history("rent", "rent"), [event])

    def test_rollback_leaves_no_audit_event_and_triggers_are_append_only(self) -> None:
        with closing(sqlite3.connect(self.workspace.paths.database)) as connection:
            self.recorder.record_change(connection, entity_type="issue", entity_id="one", action="created", before=None, after={"status": "open"})
            connection.rollback()
        self.assertEqual(self.repository.history("issue", "one"), [])
        event = self.repository.history("workspace", self.manifest.workspace_id)[0]
        with closing(sqlite3.connect(self.workspace.paths.database)) as connection:
            with self.assertRaises(sqlite3.IntegrityError): connection.execute("UPDATE audit_events SET action='changed' WHERE id=?", (event.id,))
            with self.assertRaises(sqlite3.IntegrityError): connection.execute("DELETE FROM audit_events WHERE id=?", (event.id,))

    def test_snapshot_redaction_and_history_api_are_policy_controlled(self) -> None:
        class TaxPolicy(DefaultAuditSnapshotPolicy):
            def validate(self, snapshot): return None
            def redact(self, snapshot): return {**snapshot, "taxId": "[redacted]"} if snapshot else None
        policy = TaxPolicy(schema_version=7)
        with closing(sqlite3.connect(self.workspace.paths.database)) as connection:
            event = AuditEvent.change(entity_type="provider", entity_id="p1", action="created", before_snapshot=None, after_snapshot={"taxId": "123"}, snapshot_policy=policy)
            self.repository.append(connection, event); connection.commit()
        runtime = WorkspaceRuntime(self.workspace); runtime.start(); self.addCleanup(runtime.stop)
        app = FastAPI(); app.include_router(build_router(runtime, self.repository, AuditSnapshotPolicyRegistry({("provider", 7): policy})))
        with TestClient(app) as client:
            response = client.get("/api/audit/events/provider/p1")
        self.assertEqual(response.status_code, 200); self.assertEqual(response.json()["events"][0]["after"]["taxId"], "[redacted]")

    def test_snapshot_safety_and_changed_paths(self) -> None:
        with self.assertRaises(ValueError): AuditEvent.change(entity_type="connector", entity_id="mail", action="updated", before_snapshot=None, after_snapshot={"accessToken": "secret"})
        with self.assertRaises(ValueError): AuditEvent.change(entity_type="connector", entity_id="mail", action="updated", before_snapshot=None, after_snapshot={"credentials": [{"apiKey": "secret"}]})
        with self.assertRaises(ValueError): AuditEvent.change(entity_type="issue", entity_id="one", action="updated", before_snapshot=None, after_snapshot={"created": object()})
        with self.assertRaises(ValueError): AuditEvent.change(entity_type="issue", entity_id="one", action="updated", before_snapshot=None, after_snapshot={"status": "open"}, actor_kind="invalid")  # type: ignore[arg-type]
        with self.assertRaises(ValueError): AuditEvent.change(entity_type="issue", entity_id="one", action="updated", before_snapshot=None, after_snapshot={"amount": math.nan})
        self.assertEqual(changed_paths({}, {"note": None}), ("note",))

    def test_bulk_history_filters_and_actor_classification(self) -> None:
        with closing(sqlite3.connect(self.workspace.paths.database)) as connection:
            events = self.recorder.record_many(connection, [
                {"entity_type": "issue", "entity_id": "one", "action": "ingested", "before_snapshot": None, "after_snapshot": {"status": "open"}, "actor_kind": "connector"},
                {"entity_type": "issue", "entity_id": "two", "action": "ai_reviewed", "before_snapshot": None, "after_snapshot": {"status": "open"}, "actor_kind": "ai_assistant"},
            ], correlation_id="batch", summary_entity_type="import", summary_entity_id="batch")
            connection.commit()
        self.assertEqual([event.id for event in self.repository.history(correlation_id="batch")], [event.id for event in events])
        self.assertEqual(self.repository.history(actor_kind="connector")[0].action, "ingested")

    def test_history_filters_normalize_offsets_to_utc(self) -> None:
        from datetime import datetime
        with closing(sqlite3.connect(self.workspace.paths.database)) as connection:
            event = AuditEvent.change(entity_type="issue", entity_id="offset", action="created", before_snapshot=None, after_snapshot={"status": "open"})
            event = replace(event, occurred_at=datetime.fromisoformat("2026-01-01T03:00:00+00:00"))
            self.repository.append(connection, event); connection.commit()
        self.assertEqual(self.repository.history("issue", "offset", occurred_after=datetime.fromisoformat("2026-01-01T05:00:00+02:00")), [event])

    def test_unknown_history_policy_fails_closed(self) -> None:
        with closing(sqlite3.connect(self.workspace.paths.database)) as connection:
            self.repository.append(connection, AuditEvent.change(entity_type="provider", entity_id="p2", action="created", before_snapshot=None, after_snapshot={"name": "Vendor"}))
            connection.commit()
        runtime = WorkspaceRuntime(self.workspace); runtime.start(); self.addCleanup(runtime.stop)
        app = FastAPI(); app.include_router(build_router(runtime, self.repository, AuditSnapshotPolicyRegistry()))
        with TestClient(app) as client: response = client.get("/api/audit/events/provider/p2")
        self.assertEqual(response.status_code, 503); self.assertNotIn("Vendor", response.text)

    def test_tampered_audit_schema_is_rejected(self) -> None:
        with closing(sqlite3.connect(self.workspace.paths.database)) as connection:
            connection.execute("DROP INDEX audit_events_activity")
            connection.execute("DROP TRIGGER audit_events_no_update")
            connection.execute("CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events BEGIN SELECT 1; END")
            connection.commit()
        with self.assertRaises(ProductSchemaError): validate_latest_schema(self.workspace.paths.database)

    def test_extra_or_incompatible_workspace_schema_is_rejected(self) -> None:
        with closing(sqlite3.connect(self.workspace.paths.database)) as connection:
            connection.execute("CREATE TABLE platform_schema_migrations (version INTEGER)"); connection.commit()
        with self.assertRaises(ProductSchemaError): validate_latest_schema(self.workspace.paths.database)
        with closing(sqlite3.connect(self.workspace.paths.database)) as connection:
            connection.execute("DROP TABLE platform_schema_migrations")
            connection.execute("DROP TABLE workspace_metadata")
            connection.execute("CREATE TABLE workspace_metadata (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), workspace_id TEXT NOT NULL, format_version TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)")
            connection.commit()
        with self.assertRaises(ProductSchemaError): validate_latest_schema(self.workspace.paths.database)

    def test_default_history_endpoint_is_read_only(self) -> None:
        from app.bootstrap.api import create_app
        config = self.workspace.config.config_path
        with TestClient(create_app(config)) as client:
            response = client.get(f"/api/audit/events/workspace/{self.manifest.workspace_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][0]["action"], "created")

    def test_file_names_are_redacted_only_from_general_activity(self) -> None:
        source = Path(self.temp.name) / "job-relocation-letter.pdf"
        source.write_bytes(b"private supporting document")
        item = FileService(
            self.workspace,
            FilesystemContentStore(self.workspace.paths.files),
            SQLiteFileUnitOfWork(self.workspace.paths.database, self.recorder),
        ).add(source, source.name, "application/pdf")

        from app.bootstrap.api import create_app
        with TestClient(create_app(self.workspace.config.config_path)) as client:
            activity = client.get("/api/audit/events").json()["events"]
            contextual = client.get(f"/api/audit/events/file/{item.id}").json()["events"]
        file_activity = next(event for event in activity if event["entityType"] == "file")
        self.assertEqual(file_activity["after"]["originalName"], "[redacted]")
        self.assertEqual(contextual[0]["after"]["originalName"], source.name)

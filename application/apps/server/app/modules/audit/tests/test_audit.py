from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from app.bootstrap.api import create_app
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.domain.models import AuditEvent, AuditSnapshotPolicyRegistry, DefaultAuditSnapshotPolicy, changed_paths
from app.modules.workspace.infrastructure.sqlite_store import WorkspaceDatabaseError
from app.platform.migrations import BootstrapMigrationRunner, PlatformMigrationError, build_bootstrap_migration_runner
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig


class AuditLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.workspace_path = root / "workspace"
        self.config_path = root / "config.local.json"
        self.config_path.write_text(f'{{"localWorkspacePath": "{self.workspace_path}"}}', encoding="utf-8")
        self.service = WorkspaceService(LocalConfig(self.config_path, self.workspace_path), build_bootstrap_migration_runner)
        self.manifest = self.service.initialize()
        self.repository = SQLiteAuditRepository(self.service.paths.database)
        self.recorder = AuditRecorder(self.repository)

    def test_workspace_initialization_is_recorded(self) -> None:
        events = self.repository.history("workspace", self.manifest.workspace_id)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "created")
        self.assertEqual(events[0].after_snapshot["workspaceId"], self.manifest.workspace_id)
        self.assertEqual(events[0].actor_kind, "system")

    def test_versioned_schema_migration_records_outcome_and_safety_copy(self) -> None:
        with closing(sqlite3.connect(self.service.paths.database)) as connection:
            version = connection.execute("SELECT version FROM platform_schema_migrations").fetchone()
        self.assertEqual(version, (1,))
        migration_events = self.repository.history("platform_migration", "1")
        self.assertEqual(migration_events[0].action, "migration_applied")
        self.assertTrue((self.workspace_path / "backups" / "migration-safety" / "property-management.before-platform-migration.sqlite").is_file())

    def test_change_and_audit_event_commit_together_with_prior_values(self) -> None:
        with closing(sqlite3.connect(self.service.paths.database)) as connection:
            connection.execute("CREATE TABLE sample_sensitive_records (id TEXT PRIMARY KEY, amount INTEGER NOT NULL)")
            connection.execute("INSERT INTO sample_sensitive_records VALUES ('rent-1', 1800)")
            before = {"amount": 1800, "accountReference": "****1234"}
            after = {"amount": 1900, "accountReference": "****1234"}
            connection.execute("UPDATE sample_sensitive_records SET amount = 1900 WHERE id = 'rent-1'")
            event = self.recorder.record_change(
                connection,
                entity_type="rent_expectation",
                entity_id="rent-1",
                action="updated",
                before=before,
                after=after,
                reason="annual_review",
            )
            connection.commit()

        events = self.repository.history("rent_expectation", "rent-1")
        self.assertEqual(events, [event])
        self.assertEqual(events[0].changed_fields, ("amount",))
        self.assertEqual(events[0].before_snapshot, before)
        self.assertEqual(events[0].after_snapshot, after)

    def test_rolled_back_domain_change_has_no_audit_event(self) -> None:
        with closing(sqlite3.connect(self.service.paths.database)) as connection:
            connection.execute("CREATE TABLE rollback_records (id TEXT PRIMARY KEY)")
            self.recorder.record_change(
                connection,
                entity_type="issue",
                entity_id="issue-1",
                action="created",
                before=None,
                after={"status": "open"},
            )
            connection.rollback()

        self.assertEqual(self.repository.history("issue", "issue-1"), [])

    def test_audit_events_cannot_be_updated_or_deleted(self) -> None:
        event = self.repository.history("workspace", self.manifest.workspace_id)[0]
        with closing(sqlite3.connect(self.service.paths.database)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE audit_events SET action = 'changed' WHERE id = ?", (event.id,))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM audit_events WHERE id = ?", (event.id,))

    def test_recorder_rejects_credentials_from_snapshots(self) -> None:
        with closing(sqlite3.connect(self.service.paths.database)) as connection:
            with self.assertRaisesRegex(ValueError, "secret field"):
                self.recorder.record_change(
                    connection,
                    entity_type="connector",
                    entity_id="mail-1",
                    action="updated",
                    before=None,
                    after={"accessToken": "must-not-be-retained"},
                )

    def test_snapshot_policy_rejects_sensitive_values_nested_in_lists(self) -> None:
        forbidden = [
            {"credentials": [{"access_token": "secret"}]},
            {"clientSecret": "secret"}, {"apiKey": "secret"}, {"accountNumber": "123456789"},
        ]
        for snapshot in forbidden:
            with self.assertRaisesRegex(ValueError, "secret field"):
                AuditEvent.change(entity_type="connector", entity_id="mail-1", action="updated",
                                  before_snapshot=None, after_snapshot=snapshot)

    def test_changed_paths_distinguishes_missing_and_null(self) -> None:
        self.assertEqual(changed_paths({}, {"note": None}), ("note",))
        self.assertEqual(changed_paths({"note": None}, {}), ("note",))

    def test_bulk_events_share_correlation_and_support_activity_filters(self) -> None:
        correlation_id = "bulk-import-1"
        with closing(sqlite3.connect(self.service.paths.database)) as connection:
            events = self.recorder.record_many(connection, [
                {"entity_type": "issue", "entity_id": "issue-1", "action": "imported", "before_snapshot": None,
                 "after_snapshot": {"status": "open"}, "actor_kind": "connector"},
                {"entity_type": "issue", "entity_id": "issue-2", "action": "imported", "before_snapshot": None,
                 "after_snapshot": {"status": "open"}, "actor_kind": "connector"},
            ], correlation_id=correlation_id, summary_entity_type="import", summary_entity_id="batch-1")
            connection.commit()
        found = self.repository.history(correlation_id=correlation_id, actor_kind="connector")
        self.assertEqual([event.id for event in found], [event.id for event in events[:2]])
        self.assertEqual(len(self.repository.history(correlation_id=correlation_id)), 3)

    def test_connector_ai_and_operator_decisions_are_distinguishable(self) -> None:
        correlation_id = "issue-intake-1"
        with closing(sqlite3.connect(self.service.paths.database)) as connection:
            for action, actor, entity_id in [
                ("ingested", "connector", "source-1"), ("ai_draft_created", "ai_assistant", "draft-1"),
                ("ai_reviewed", "ai_assistant", "draft-1"), ("approved", "local_operator", "draft-1"),
                ("created", "local_operator", "issue-1"),
            ]:
                self.recorder.record_change(connection, entity_type="issue_intake", entity_id=entity_id, action=action,
                    before=None, after={"state": action}, actor_kind=actor, correlation_id=correlation_id)
            connection.commit()
        events = self.repository.history(correlation_id=correlation_id)
        self.assertEqual([(event.action, event.actor_kind) for event in events], [
            ("ingested", "connector"), ("ai_draft_created", "ai_assistant"), ("ai_reviewed", "ai_assistant"),
            ("approved", "local_operator"), ("created", "local_operator"),
        ])

    def test_portable_snapshots_and_invalid_actor_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "portable JSON"):
            AuditEvent.change(entity_type="issue", entity_id="one", action="updated", before_snapshot=None,
                              after_snapshot={"created": object()})
        with self.assertRaisesRegex(ValueError, "actor kind"):
            AuditEvent.change(entity_type="issue", entity_id="one", action="updated", before_snapshot=None,
                              after_snapshot={"status": "open"}, actor_kind="not_a_real_actor")  # type: ignore[arg-type]

    def test_history_endpoint_returns_read_only_event_history(self) -> None:
        with TestClient(create_app(self.config_path)) as client:
            response = client.get(f"/api/audit/events/workspace/{self.manifest.workspace_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][0]["action"], "created")

    def test_history_endpoint_uses_registered_domain_presentation_policy(self) -> None:
        class TaxPolicy(DefaultAuditSnapshotPolicy):
            def validate(self, snapshot):
                return None

            def redact(self, snapshot):
                return {**snapshot, "taxId": "[redacted]"} if snapshot else None

        policy = TaxPolicy(schema_version=7)
        with closing(sqlite3.connect(self.service.paths.database)) as connection:
            event = AuditEvent.change(entity_type="provider", entity_id="provider-1", action="created",
                before_snapshot=None, after_snapshot={"taxId": "123-45-6789"}, snapshot_policy=policy)
            self.repository.append(connection, event)
            connection.commit()
        from app.modules.audit.api.router import build_router
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(build_router(self.service, self.repository, AuditSnapshotPolicyRegistry({("provider", 7): policy})))
        with TestClient(test_app) as client:
            response = client.get("/api/audit/events/provider/provider-1")
        self.assertEqual(response.json()["events"][0]["after"]["taxId"], "[redacted]")

    def test_history_with_no_registered_policy_fails_closed(self) -> None:
        with closing(sqlite3.connect(self.service.paths.database)) as connection:
            event = AuditEvent.change(entity_type="provider", entity_id="provider-2", action="created",
                before_snapshot=None, after_snapshot={"name": "Vendor"})
            self.repository.append(connection, event)
            connection.commit()
        from app.modules.audit.api.router import build_router
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(build_router(self.service, self.repository, AuditSnapshotPolicyRegistry()))
        with TestClient(test_app) as client:
            response = client.get("/api/audit/events/provider/provider-2")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Vendor", response.text)

    def test_failed_legacy_migration_rolls_back_and_can_retry(self) -> None:
        database = Path(self.temporary_directory.name) / "legacy-workspace" / "database" / "legacy.sqlite"
        database.parent.mkdir(parents=True)
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE workspace_metadata (singleton INTEGER PRIMARY KEY, workspace_id TEXT, format_version INTEGER, created_at TEXT)")
            connection.execute("INSERT INTO workspace_metadata VALUES (1, ?, ?, ?)", (self.manifest.workspace_id, self.manifest.format_version, self.manifest.created_at.isoformat()))
            connection.execute("""CREATE TABLE audit_events (id TEXT, occurred_at TEXT, entity_type TEXT, entity_id TEXT,
                action TEXT, before_snapshot TEXT, after_snapshot TEXT, changed_fields TEXT, reason TEXT,
                actor_kind TEXT, actor_reference TEXT, correlation_id TEXT, schema_version INTEGER)""")
            connection.execute("INSERT INTO audit_events VALUES ('bad', '2026-01-01T00:00:00+00:00', 'issue', '1', 'created', NULL, '{}', '[]', NULL, 'invalid', NULL, 'c1', 1)")
            connection.commit()
        runner = BootstrapMigrationRunner(database, database.parent.parent / "backups", AuditRecorder(SQLiteAuditRepository(database)))
        with self.assertRaises(PlatformMigrationError):
            runner.apply(self.manifest)
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events_legacy'").fetchone(), None)
            self.assertEqual(connection.execute("SELECT actor_kind FROM audit_events").fetchone(), ("invalid",))
            connection.execute("UPDATE audit_events SET actor_kind = 'system' WHERE id = 'bad'")
            connection.execute("CREATE TABLE retry_marker (value TEXT)")
            connection.commit()
        runner.apply(self.manifest)
        snapshot = database.parent.parent / "backups" / "migration-safety" / "legacy.before-platform-migration.sqlite"
        self.assertTrue(snapshot.is_file())
        with closing(sqlite3.connect(snapshot)) as connection:
            self.assertEqual(connection.execute("SELECT actor_kind FROM audit_events WHERE id = 'bad'").fetchone(), ("system",))
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'retry_marker'").fetchone(), ("retry_marker",))

    def test_empty_existing_migration_snapshot_is_replaced(self) -> None:
        with closing(sqlite3.connect(self.service.paths.database)) as connection:
            connection.execute("DROP TABLE platform_schema_migrations")
        snapshot = self.service.paths.backups / "migration-safety" / "property-management.before-platform-migration.sqlite"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.unlink(missing_ok=True)
        snapshot.touch()
        runner = BootstrapMigrationRunner(self.service.paths.database, self.service.paths.backups, self.recorder)
        runner.apply(self.manifest)
        self.assertGreater(snapshot.stat().st_size, 0)
        with closing(sqlite3.connect(snapshot)) as connection:
            self.assertEqual(connection.execute("SELECT workspace_id FROM workspace_metadata").fetchone(), (self.manifest.workspace_id,))

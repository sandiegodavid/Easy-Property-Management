"""Transactional platform migrations for the pre-ORM local workspace."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository, install_audit_schema
from app.modules.workspace.domain.models import WorkspaceManifest


class PlatformMigrationError(RuntimeError):
    """A migration could not complete without changing the live workspace."""


class BootstrapMigrationRunner:
    """Owns the one native bootstrap migration until ORM-owned schemas begin."""

    def __init__(self, database_path: Path, backups_path: Path, recorder: AuditRecorder) -> None:
        self.database_path = database_path
        self.backups_path = backups_path
        self.recorder = recorder

    def apply(self, manifest: WorkspaceManifest) -> None:
        try:
            with closing(sqlite3.connect(self.database_path)) as connection:
                if self._applied(connection, 1):
                    return
                self._backup_before_migration(manifest)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute("CREATE TABLE IF NOT EXISTS platform_schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
                    audit_applied = self._applied(connection, 1)
                    legacy = self._table_exists(connection, "audit_events")
                    if legacy and not audit_applied:
                        self._validate_legacy_rows(connection)
                        for name in ("audit_events_no_update", "audit_events_no_delete"):
                            connection.execute(f"DROP TRIGGER IF EXISTS {name}")
                        for name in ("audit_events_entity_time", "audit_events_correlation", "audit_events_activity"):
                            connection.execute(f"DROP INDEX IF EXISTS {name}")
                        connection.execute("ALTER TABLE audit_events RENAME TO audit_events_legacy")
                    if not audit_applied:
                        install_audit_schema(connection)
                    if legacy and not audit_applied:
                        connection.execute("INSERT INTO audit_events (id, occurred_at, entity_type, entity_id, action, before_snapshot, after_snapshot, changed_fields, reason, actor_kind, actor_reference, correlation_id, schema_version) SELECT id, occurred_at, entity_type, entity_id, action, before_snapshot, after_snapshot, changed_fields, reason, actor_kind, actor_reference, correlation_id, schema_version FROM audit_events_legacy")
                        connection.execute("DROP TABLE audit_events_legacy")
                    if not audit_applied:
                        connection.execute("INSERT INTO platform_schema_migrations (version, applied_at) VALUES (1, datetime('now'))")
                    if not audit_applied and not legacy:
                        self.recorder.record_change(connection, entity_type="workspace", entity_id=manifest.workspace_id, action="created", before=None, after=manifest.to_dict(), actor_kind="system", reason="workspace_initialized")
                    if not audit_applied:
                        self.recorder.record_change(connection, entity_type="platform_migration", entity_id="1", action="migration_applied", before=None, after={"version": 1}, actor_kind="system", reason="audit_schema_installed")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except (sqlite3.Error, OSError) as error:
            raise PlatformMigrationError(f"Unable to apply platform migrations: {error}") from error

    def _backup_before_migration(self, manifest: WorkspaceManifest) -> None:
        backup_dir = self.backups_path / "migration-safety"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{self.database_path.stem}.before-platform-migration.sqlite"
        temporary_path = backup_dir / f".{backup_path.name}.{uuid4().hex}.tmp"
        try:
            with closing(sqlite3.connect(self.database_path)) as source, closing(sqlite3.connect(temporary_path)) as snapshot:
                source.backup(snapshot)
            self._validate_snapshot(temporary_path, manifest)
            temporary_path.replace(backup_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _validate_snapshot(snapshot_path: Path, manifest: WorkspaceManifest) -> None:
        try:
            with closing(sqlite3.connect(f"{snapshot_path.resolve().as_uri()}?mode=ro", uri=True)) as snapshot:
                if snapshot.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise PlatformMigrationError("Migration-safety SQLite snapshot integrity check failed.")
                metadata = snapshot.execute(
                    "SELECT workspace_id, format_version, created_at FROM workspace_metadata WHERE singleton = 1"
                ).fetchone()
        except sqlite3.Error as error:
            raise PlatformMigrationError(f"Migration-safety SQLite snapshot is invalid: {error}") from error
        expected = (manifest.workspace_id, manifest.format_version, manifest.created_at.isoformat())
        if metadata != expected:
            raise PlatformMigrationError("Migration-safety SQLite snapshot does not match the live workspace identity.")

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
        return connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None

    def _applied(self, connection: sqlite3.Connection, version: int) -> bool:
        return self._table_exists(connection, "platform_schema_migrations") and connection.execute("SELECT 1 FROM platform_schema_migrations WHERE version = ?", (version,)).fetchone() is not None

    @staticmethod
    def _validate_legacy_rows(connection: sqlite3.Connection) -> None:
        invalid = connection.execute("SELECT id FROM audit_events WHERE actor_kind NOT IN ('local_operator', 'system', 'connector', 'ai_assistant') OR trim(entity_type) = '' OR trim(entity_id) = '' OR trim(action) = '' LIMIT 1").fetchone()
        if invalid:
            raise PlatformMigrationError(f"Legacy audit event {invalid[0]} cannot be migrated safely.")


def build_bootstrap_migration_runner(database_path: Path, backups_path: Path) -> BootstrapMigrationRunner:
    """Production composition for the temporary bootstrap migration."""
    return BootstrapMigrationRunner(database_path, backups_path, AuditRecorder(SQLiteAuditRepository(database_path)))

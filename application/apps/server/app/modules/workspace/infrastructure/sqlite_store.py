"""The minimal persistent SQLite store required to establish a workspace."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.workspace.domain.models import WorkspaceManifest


class WorkspaceDatabaseError(RuntimeError):
    """Raised when the workspace database does not match its manifest."""


class SQLiteWorkspaceStore:
    def __init__(self, database_path: Path, audit_recorder: AuditRecorder | None = None) -> None:
        self.database_path = database_path
        self.audit_recorder = audit_recorder

    def persist_identity(self, manifest: WorkspaceManifest) -> None:
        """Persist identity into the Alembic-created baseline schema."""
        try:
            self._reject_symlink()
            with closing(sqlite3.connect(self.database_path)) as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA foreign_keys = ON")
                existing = connection.execute(
                    "SELECT workspace_id, format_version, created_at FROM workspace_metadata WHERE singleton = 1"
                ).fetchone()
                expected = (manifest.workspace_id, manifest.format_version, manifest.created_at.isoformat())
                if existing is None:
                    connection.execute(
                        "INSERT INTO workspace_metadata (singleton, workspace_id, format_version, created_at) "
                        "VALUES (1, ?, ?, ?)",
                        expected,
                    )
                    if self.audit_recorder is None:
                        raise WorkspaceDatabaseError("Workspace identity auditing is not configured.")
                    self.audit_recorder.record_change(
                        connection,
                        entity_type="workspace",
                        entity_id=manifest.workspace_id,
                        action="created",
                        before=None,
                        after=manifest.to_dict(),
                        actor_kind="system",
                        reason="workspace_initialized",
                    )
                elif existing != expected:
                    raise WorkspaceDatabaseError("Workspace database identity does not match its manifest.")
                connection.commit()
        except sqlite3.Error as error:
            raise WorkspaceDatabaseError(f"Unable to persist SQLite workspace identity: {error}") from error

    def verify(self, manifest: WorkspaceManifest, *, integrity_check: bool = False) -> None:
        self._reject_symlink()
        if not self.database_path.is_file():
            raise WorkspaceDatabaseError(f"Workspace database is missing: {self.database_path}")
        database_uri = f"{self.database_path.resolve().as_uri()}?mode=ro"
        try:
            with closing(sqlite3.connect(database_uri, uri=True)) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone() if integrity_check else ("ok",)
                metadata = connection.execute(
                    "SELECT workspace_id, format_version, created_at FROM workspace_metadata WHERE singleton = 1"
                ).fetchone()
        except sqlite3.Error as error:
            raise WorkspaceDatabaseError(f"Unable to validate SQLite workspace database: {error}") from error
        if integrity != ("ok",):
            raise WorkspaceDatabaseError("Workspace SQLite integrity check failed.")
        expected = (manifest.workspace_id, manifest.format_version, manifest.created_at.isoformat())
        if metadata != expected:
            raise WorkspaceDatabaseError("Workspace database identity does not match its manifest.")

    def _reject_symlink(self) -> None:
        if self.database_path.is_symlink() or self.database_path.parent.is_symlink():
            raise WorkspaceDatabaseError("Workspace database paths must not be symbolic links.")

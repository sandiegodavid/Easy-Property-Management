"""Composition helper for workspace identity persistence."""

from __future__ import annotations

from pathlib import Path

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.workspace.infrastructure.sqlite_store import SQLiteWorkspaceStore


def create_workspace_store(database: Path) -> SQLiteWorkspaceStore:
    """Build the local store with the ledger required for workspace creation."""
    return SQLiteWorkspaceStore(database, AuditRecorder(SQLiteAuditRepository(database)))

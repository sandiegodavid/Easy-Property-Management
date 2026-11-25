"""Regression tests for SQLiteMaintenanceUnitOfWork engine configuration (Finding 12)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.maintenance.infrastructure.unit_of_work import SQLiteMaintenanceUnitOfWork
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig
from app.platform.attempt_fences import ClosedCommandError


def test_maintenance_uow_enforces_foreign_keys_and_special_path_chars(tmp_path: Path):
    # Path contains '#' and '?' which raw sqlite:/// string interpolation breaks.
    workspace = WorkspaceService(LocalConfig(tmp_path / "config.json", tmp_path / "ws#1?test"))
    workspace.initialize()
    db = workspace.paths.database
    uow = SQLiteMaintenanceUnitOfWork(
        db,
        AuditRecorder(SQLiteAuditRepository(db)),
        portfolio=None,
        finance=None,
        tasks=None,
        task_operations=None,
    )

    assert uow.read(lambda tx: tx.connection.execute(text("PRAGMA foreign_keys")).scalar_one()) == 1

    def bad_fk_insert(tx):
        tx.connection.execute(
            text(
                "INSERT INTO maintenance_issues "
                "(id, revision, property_id, summary, description, category, priority, status, "
                "reported_at_utc, reported_timezone, reporter_role, reporter_subject_kind, "
                "reporter_display_name_snapshot, idempotency_key, request_fingerprint, "
                "created_at, updated_at) "
                "VALUES (:id, 1, :prop_id, 'Leak', 'Desc', 'plumbing', 'normal', 'open', "
                "'2026-11-24T12:00:00Z', 'America/Los_Angeles', 'manager', 'local_operator', "
                "'Operator', :idem, :fp, '2026-11-24T12:00:00Z', '2026-11-24T12:00:00Z')"
            ),
            {
                "id": str(uuid4()),
                "prop_id": str(uuid4()),
                "idem": str(uuid4()),
                "fp": "a" * 64,
            },
        )

    with pytest.raises(IntegrityError):
        uow.write(bad_fk_insert)


def test_maintenance_uow_maps_closed_attempt_fence_to_closed_command_error(tmp_path: Path):
    workspace = WorkspaceService(LocalConfig(tmp_path / "config.json", tmp_path / "ws-fence"))
    workspace.initialize()
    db = workspace.paths.database
    uow = SQLiteMaintenanceUnitOfWork(
        db,
        AuditRecorder(SQLiteAuditRepository(db)),
        portfolio=None,
        finance=None,
        tasks=None,
        task_operations=None,
    )
    fenced_key = str(uuid4())

    def seed_fence(tx):
        tx.connection.execute(
            text(
                "INSERT INTO command_attempt_fences "
                "(id, attempt_key, receipt_table, recovery_id, form_key, "
                "request_fingerprint, created_at) "
                "VALUES (:id, :idem, 'maintenance_issues', :rid, "
                "'maintenance.issue.create', :fp, '2026-11-24T12:00:00Z')"
            ),
            {
                "id": str(uuid4()),
                "idem": fenced_key,
                "rid": str(uuid4()),
                "fp": "b" * 64,
            },
        )

    uow.write(seed_fence)

    def write_fenced_issue(tx):
        tx.connection.execute(
            text(
                "INSERT INTO maintenance_issues "
                "(id, revision, property_id, summary, description, category, priority, status, "
                "reported_at_utc, reported_timezone, reporter_role, reporter_subject_kind, "
                "reporter_display_name_snapshot, idempotency_key, request_fingerprint, "
                "created_at, updated_at) "
                "VALUES (:id, 1, :prop_id, 'Leak', 'Desc', 'plumbing', 'normal', 'open', "
                "'2026-11-24T12:00:00Z', 'America/Los_Angeles', 'manager', 'local_operator', "
                "'Operator', :idem, :fp, '2026-11-24T12:00:00Z', '2026-11-24T12:00:00Z')"
            ),
            {
                "id": str(uuid4()),
                "prop_id": str(uuid4()),
                "idem": fenced_key,
                "fp": "c" * 64,
            },
        )

    with pytest.raises(ClosedCommandError):
        uow.write(write_fenced_issue)

"""Regression tests for inspection batching (Finding 8) and OperationalError mapping (Finding 9)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.inspections.application.commands import InspectionConflictError
from app.modules.inspections.application.service import (
    AreaInput,
    InspectionService,
    ObservationInput,
)
from app.modules.inspections.infrastructure.unit_of_work import SQLiteInspectionUnitOfWork
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig


def test_inspection_uow_maps_only_locked_operational_error_to_conflict(tmp_path: Path):
    workspace = WorkspaceService(LocalConfig(tmp_path / "config.json", tmp_path / "workspace"))
    workspace.initialize()
    db = workspace.paths.database
    uow = SQLiteInspectionUnitOfWork(db, AuditRecorder(SQLiteAuditRepository(db)))

    def raise_locked(_tx):
        raise OperationalError("BEGIN IMMEDIATE", {}, Exception("database is locked"))

    def raise_disk_full(_tx):
        raise OperationalError("INSERT", {}, Exception("database or disk is full"))

    with pytest.raises(InspectionConflictError):
        uow.write(raise_locked)

    with pytest.raises(OperationalError, match="disk is full"):
        uow.write(raise_disk_full)


def test_template_views_uses_constant_query_budget(tmp_path: Path):
    workspace = WorkspaceService(LocalConfig(tmp_path / "config.json", tmp_path / "workspace"))
    workspace.initialize()
    db = workspace.paths.database
    uow = SQLiteInspectionUnitOfWork(db, AuditRecorder(SQLiteAuditRepository(db)))
    svc = InspectionService(uow, None)

    for idx in range(5):
        svc.create_template(
            expected_revision=0,
            idempotency_key=str(uuid4()),
            display_name=f"Template {idx}",
            areas=(
                AreaInput("Kitchen", (ObservationInput("Floor", "good", is_completed=True),)),
                AreaInput("Bath", (ObservationInput("Sink", "good", is_completed=True),)),
            ),
        )

    statements: list[str] = []

    def capture(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(uow.engine, "before_cursor_execute", capture)
    try:
        views = svc.list_templates()
    finally:
        event.remove(uow.engine, "before_cursor_execute", capture)

    assert len(views) == 5
    # 1 query for templates + revisions, 1 batched IN (...) query for all template items.
    assert len(statements) == 2

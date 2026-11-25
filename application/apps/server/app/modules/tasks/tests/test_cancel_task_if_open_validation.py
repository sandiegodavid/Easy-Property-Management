"""Regression tests for SQLiteTaskTransactionOperations.cancel_task_if_open audit contract."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.tasks.application.waiting import WaitingCommand
from app.modules.tasks.application.waiting_service import TaskWaitingService
from app.modules.tasks.infrastructure.schema_validation import validate_task_data
from app.modules.tasks.infrastructure.transaction_operations import SQLiteTaskTransactionOperations
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork
from app.modules.workspace.application.service import WorkspaceService
from app.platform.sqlite_engine import create_sqlite_engine


def _init_workspace(tmp_path: Path) -> tuple[Path, str]:
    workspace = tmp_path / "workspace"
    config = tmp_path / "config.json"
    config.write_text(f'{{"localWorkspacePath": "{workspace}"}}', encoding="utf-8")
    service = WorkspaceService.from_local_config(config)
    manifest = service.initialize()
    return service.paths.database, manifest.workspace_id


def test_cancel_task_if_open_passes_startup_task_history_validation(tmp_path: Path) -> None:
    database, _workspace_id = _init_workspace(tmp_path)
    recorder = AuditRecorder(SQLiteAuditRepository(database))
    uow = SQLiteTaskUnitOfWork(database, recorder)
    ops = SQLiteTaskTransactionOperations()

    def run(tx):
        created = ops.create_task(
            tx.connection,
            {
                "title": "Deposit prepaid check",
                "relatedEntityType": "prepaid_check",
                "relatedEntityId": str(uuid4()),
                "relatedLabel": "Prepaid check",
            },
            correlation_id=str(uuid4()),
            record_change=tx.record_change,
        )
        ops.cancel_task_if_open(
            tx.connection,
            created.id,
            committed_at=datetime.now(UTC).isoformat(),
            reason="prepaid_check_lifecycle_changed",
            correlation_id=str(uuid4()),
            record_change=tx.record_change,
        )

    uow.write(run)

    engine = create_sqlite_engine(database)
    try:
        with engine.connect() as conn:
            validate_task_data(conn)
    finally:
        engine.dispose()


def test_cancel_task_if_open_with_waiting_context_passes_startup_validation(tmp_path: Path) -> None:
    database, workspace_id = _init_workspace(tmp_path)
    recorder = AuditRecorder(SQLiteAuditRepository(database))
    uow = SQLiteTaskUnitOfWork(database, recorder)
    ops = SQLiteTaskTransactionOperations()
    identity = (workspace_id, str(uuid4()))
    waiting_service = TaskWaitingService(uow, read_identity=lambda: identity)

    created = uow.write(
        lambda tx: ops.create_task(
            tx.connection,
            {
                "title": "Deposit prepaid check with waiting",
                "relatedEntityType": "prepaid_check",
                "relatedEntityId": str(uuid4()),
                "relatedLabel": "Prepaid check",
            },
            correlation_id=str(uuid4()),
            record_change=tx.record_change,
        )
    )

    waiting_service.mutate(
        WaitingCommand(
            task_id=created.id,
            action="set",
            expected_revision=1,
            idempotency_key=str(uuid4()),
            kind="person",
            label="Tenant",
        )
    )

    uow.write(
        lambda tx: ops.cancel_task_if_open(
            tx.connection,
            created.id,
            committed_at=datetime.now(UTC).isoformat(),
            reason="prepaid_check_lifecycle_changed",
            correlation_id=str(uuid4()),
            record_change=tx.record_change,
        )
    )

    engine = create_sqlite_engine(database)
    try:
        with engine.connect() as conn:
            validate_task_data(conn)
    finally:
        engine.dispose()

"""FastAPI composition for the local application."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.modules.workspace.api.router import build_router
from app.modules.audit.api.router import build_router as build_audit_router
from app.modules.audit.infrastructure.sqlite_repository import SQLiteAuditRepository
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.audit.domain.models import AuditSnapshotPolicyRegistry, DEFAULT_SNAPSHOT_POLICY
from app.modules.workspace.application.backup_service import BackupError, BackupService
from app.modules.workspace.application.runtime import WorkspaceRuntime
from app.modules.workspace.application.service import WorkspaceService
from app.modules.files.application.service import FileService
from app.modules.files.infrastructure.content_store import FilesystemContentStore
from app.modules.files.infrastructure.sqlite_repository import SQLiteFileUnitOfWork
from app.modules.files.api.router import build_router as build_files_router
from app.modules.tasks.api.router import build_router as build_tasks_router
from app.modules.tasks.application.service import TaskService
from app.modules.tasks.infrastructure.unit_of_work import SQLiteTaskUnitOfWork
from app.modules.portfolio.api.router import build_router as build_portfolio_router
from app.modules.portfolio.application.service import PortfolioService
from app.modules.portfolio.infrastructure.unit_of_work import SQLitePortfolioUnitOfWork
from app.platform.version import application_version

logger = logging.getLogger(__name__)


def create_app(config_path: Path | None = None) -> FastAPI:
    """Create the local API without implicitly initializing a workspace."""
    service = WorkspaceService.from_local_config(config_path)
    audit_repository = SQLiteAuditRepository(service.paths.database)
    recorder = AuditRecorder(audit_repository)
    backups = BackupService(service, recorder, lambda database: AuditRecorder(SQLiteAuditRepository(database)))
    runtime = WorkspaceRuntime(service)
    files = FileService(service, FilesystemContentStore(service.paths.files),
                        SQLiteFileUnitOfWork(service.paths.database, recorder))
    tasks = TaskService(SQLiteTaskUnitOfWork(service.paths.database, recorder))
    portfolio = PortfolioService(SQLitePortfolioUnitOfWork(service.paths.database, recorder))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.start()
        scheduler: asyncio.Task[None] | None = None
        try:
            if runtime.writer_lock_acquired:
                scheduler = asyncio.create_task(_automatic_backup_scheduler(backups, runtime))
            elif runtime.error:
                logger.warning("Workspace is not ready: %s", runtime.error)
            yield
        finally:
            try:
                if scheduler is not None:
                    scheduler.cancel()
                    try:
                        await scheduler
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        logger.exception("Automatic backup scheduler stopped unexpectedly during shutdown.")
            finally:
                runtime.stop()

    app = FastAPI(title="Easy Property Management", version=application_version(), lifespan=lifespan)
    app.state.backup_service = backups
    app.state.workspace_runtime = runtime
    app.state.file_service = files
    app.state.task_service = tasks
    app.state.portfolio_service = portfolio
    app.include_router(build_router(service, runtime))
    policies = AuditSnapshotPolicyRegistry({
        ("workspace", 1): DEFAULT_SNAPSHOT_POLICY,
        ("file", 1): DEFAULT_SNAPSHOT_POLICY,
        ("file_link", 1): DEFAULT_SNAPSHOT_POLICY,
        ("task", 1): DEFAULT_SNAPSHOT_POLICY,
        ("task_reminder", 1): DEFAULT_SNAPSHOT_POLICY,
        ("property", 1): DEFAULT_SNAPSHOT_POLICY,
        ("party", 1): DEFAULT_SNAPSHOT_POLICY,
        ("property_ownership", 1): DEFAULT_SNAPSHOT_POLICY,
        ("space", 1): DEFAULT_SNAPSHOT_POLICY,
        ("space_occupancy", 1): DEFAULT_SNAPSHOT_POLICY,
        ("space_availability", 1): DEFAULT_SNAPSHOT_POLICY,
        ("backup_operation", 1): DEFAULT_SNAPSHOT_POLICY,
        ("backup_retention", 1): DEFAULT_SNAPSHOT_POLICY,
        ("workspace_restore", 1): DEFAULT_SNAPSHOT_POLICY,
    })
    app.include_router(build_audit_router(runtime, audit_repository, policies))
    app.include_router(build_files_router(files, runtime))
    app.include_router(build_tasks_router(tasks, runtime))
    app.include_router(build_portfolio_router(portfolio, runtime))
    return app


async def _automatic_backup_scheduler(backups: BackupService, runtime: WorkspaceRuntime) -> None:
    """Recheck the local backup schedule while this server owns the workspace."""
    while runtime.writer_lock_acquired:
        if not runtime.ready:
            await asyncio.sleep(1)
            continue
        worker = asyncio.create_task(asyncio.to_thread(backups.run_due_automatic_backup))
        try:
            # Shielding lets cancellation stop the scheduler without abandoning its synchronous worker.
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            try:
                await worker
            except BackupError as error:
                logger.warning("Automatic backup stopped with an error during shutdown: %s", error)
            except Exception:
                logger.exception("Automatic backup worker crashed during shutdown.")
            raise
        except BackupError as error:
            logger.warning("Automatic backup was not run: %s", error)
        except Exception as error:
            logger.exception("Automatic backup worker crashed; recording failure before retrying.")
            backups.record_scheduler_failure(error)
        await asyncio.sleep(60)

"""FastAPI composition for the local application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.modules.workspace.api.router import build_router
from app.modules.workspace.application.backup_service import BackupError, BackupService
from app.modules.workspace.application.runtime import WorkspaceRuntime
from app.modules.workspace.application.service import WorkspaceService

logger = logging.getLogger(__name__)


def create_app(config_path: Path | None = None) -> FastAPI:
    """Create the local API without implicitly initializing a workspace."""
    service = WorkspaceService.from_local_config(config_path)
    backups = BackupService(service)
    runtime = WorkspaceRuntime(service)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.start()
        try:
            if runtime.ready:
                try:
                    backups.run_due_automatic_backup()
                except BackupError as error:
                    logger.warning("Automatic backup was not run: %s", error)
            elif runtime.error:
                logger.warning("Workspace is not ready: %s", runtime.error)
            yield
        finally:
            runtime.stop()

    app = FastAPI(title="Easy Property Management", version="0.1.0", lifespan=lifespan)
    app.state.backup_service = backups
    app.state.workspace_runtime = runtime
    app.include_router(build_router(service, runtime))
    return app

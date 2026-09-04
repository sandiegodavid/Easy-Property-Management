"""FastAPI composition for the local application."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from app.modules.workspace.api.router import build_router
from app.modules.workspace.application.service import WorkspaceService


def create_app(config_path: Path | None = None) -> FastAPI:
    """Create the local API without implicitly initializing a workspace."""
    service = WorkspaceService.from_local_config(config_path)
    app = FastAPI(title="Easy Property Management", version="0.1.0")
    app.include_router(build_router(service))
    return app

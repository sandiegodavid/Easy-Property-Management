"""Retired hosted-demo CLI fails closed without opening an Operator workspace."""

from pathlib import Path
from typing import NoReturn

from app.modules.hosted_access.infrastructure.configuration import load_hosted_deployment
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore
from app.modules.workspace.application.service import WorkspaceService


def administer(path: Path, service: WorkspaceService, action: str, subject: str | None) -> NoReturn:
    """Keep the existing command entry importable, without obsolete lifecycle dispatch."""
    deployment = load_hosted_deployment(path)
    SQLiteHostedSessionStore.initialize(deployment)

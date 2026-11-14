"""Retired hosted-demo composition fails closed; local Operator is independent."""

from fastapi import FastAPI

from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_access.infrastructure.session_store import SQLiteHostedSessionStore
from app.modules.workspace.application.runtime import WorkspaceRuntime


def compose_hosted_access(
    app: FastAPI, deployment: HostedDeployment, runtime: WorkspaceRuntime
) -> SQLiteHostedSessionStore:
    """Never attach obsolete routes/authority; current hosted composition is H03-owned."""
    return SQLiteHostedSessionStore(deployment)

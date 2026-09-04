"""Server-lifetime workspace ownership and readiness state."""

from __future__ import annotations

from app.modules.workspace.application.service import WorkspaceError, WorkspaceNotInitializedError, WorkspaceService
from app.platform.locking import WorkspaceOperationInProgressError, WorkspaceOperationLock


class WorkspaceRuntime:
    """Keeps one server instance responsible for an active local workspace."""

    def __init__(self, service: WorkspaceService) -> None:
        self.service = service
        self._lock = WorkspaceOperationLock(service.paths.root.parent / f".{service.paths.root.name}.server.lock")
        self.startup_attempted = False
        self.writer_lock_acquired = False
        self.error: WorkspaceError | None = None

    @property
    def ready(self) -> bool:
        return self.startup_attempted and self.writer_lock_acquired and self.error is None

    @property
    def can_write(self) -> bool:
        return self.writer_lock_acquired

    def start(self) -> None:
        self.startup_attempted = True
        try:
            self._lock.__enter__()
        except WorkspaceOperationInProgressError as error:
            self.error = WorkspaceError(f"Another local server is already using this workspace: {error}")
            return
        self.writer_lock_acquired = True
        self.refresh()

    def refresh(self) -> None:
        if not self.writer_lock_acquired:
            self.error = WorkspaceError("This server does not hold the workspace writer lock.")
            return
        try:
            self.service.open(integrity_check=True)
        except WorkspaceError as error:
            self.error = error
        else:
            self.error = None

    def stop(self) -> None:
        if self.writer_lock_acquired:
            self._lock.__exit__(None, None, None)
        self.writer_lock_acquired = False

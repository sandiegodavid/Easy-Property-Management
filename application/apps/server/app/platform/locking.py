"""Cross-process exclusion for operations that must not overlap in one workspace."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TextIO
from types import TracebackType

try:  # POSIX systems, including the supported macOS local-first deployment.
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows.
    fcntl = None  # type: ignore[assignment]

if os.name == "nt":  # pragma: no cover - exercised on Windows.
    import msvcrt


class WorkspaceOperationInProgressError(RuntimeError):
    """Raised when another local process is already changing or packaging the workspace."""


class WorkspaceOperationLock:
    """An advisory, non-blocking owner-only lock held for one workspace operation."""

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._handle: TextIO | None = None
        self._locked = False

    def __enter__(self) -> "WorkspaceOperationLock":
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.lock_path.open("a+", encoding="utf-8")
            if os.name == "posix":
                self.lock_path.chmod(0o600)
            self._acquire_file_lock()
            self._locked = True
        except BlockingIOError as error:
            self._close()
            raise WorkspaceOperationInProgressError(
                "Another workspace operation is already running. Wait for it to finish and try again."
            ) from error
        except OSError as error:
            self._close()
            raise WorkspaceOperationInProgressError(f"Unable to acquire the workspace operation lock: {error}") from error
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._close()

    def _close(self) -> None:
        if self._handle is None:
            return
        try:
            if self._locked:
                self._release_file_lock()
        finally:
            self._handle.close()
            self._handle = None
            self._locked = False

    def _acquire_file_lock(self) -> None:
        if fcntl is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        self._handle.seek(0)
        self._handle.write("0")
        self._handle.flush()
        self._handle.seek(0)
        msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _release_file_lock(self) -> None:
        if fcntl is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            return
        self._handle.seek(0)
        msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.platform.locking import WorkspaceOperationLock


class WorkspaceOperationLockTests(unittest.TestCase):
    def test_failed_acquisition_does_not_release_an_unowned_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock = WorkspaceOperationLock(Path(temporary_directory) / "workspace.lock")
            lock._handle = lock.lock_path.open("a+", encoding="utf-8")
            self.addCleanup(lock._handle.close)

            with patch.object(lock, "_release_file_lock") as release:
                lock._close()

            release.assert_not_called()

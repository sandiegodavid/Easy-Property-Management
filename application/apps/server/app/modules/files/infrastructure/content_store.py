from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.modules.files.application.errors import FileError, MAX_FILE_BYTES
from app.platform.locking import WorkspaceOperationInProgressError, WorkspaceOperationLock


@dataclass
class _Lease:
    store: "FilesystemContentStore"
    relative_path: str
    size_bytes: int
    content_sha256: str
    published: bool
    lock: WorkspaceOperationLock | None

    def commit(self) -> None:
        self._release()

    def rollback(self) -> None:
        try:
            if self.published:
                (self.store.files_root / self.relative_path).unlink(missing_ok=True)
        finally:
            self._release()

    def _release(self) -> None:
        if self.lock is not None:
            lock, self.lock = self.lock, None
            lock.__exit__(None, None, None)


class FilesystemContentStore:
    def __init__(self, files_root: Path) -> None:
        self.files_root = files_root

    def store(self, source: Path) -> _Lease:
        managed = self.files_root / "managed"
        managed.mkdir(mode=0o700, exist_ok=True)
        temporary = managed / f".{uuid4().hex}.uploading"
        digest = hashlib.sha256(); size = 0
        try:
            with source.open("rb") as input_file, temporary.open("xb") as output:
                while chunk := input_file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise FileError("File exceeds the 50 MiB local upload limit.")
                    digest.update(chunk); output.write(chunk)
            content_hash = digest.hexdigest()
            relative = f"managed/{content_hash}"
            target = self.files_root / relative
            lock = self._acquire_digest_lock(content_hash)
            try:
                if target.exists():
                    self.path_for(relative, content_hash, size)
                    temporary.unlink()
                    return _Lease(self, relative, size, content_hash, False, lock)
                temporary.chmod(0o600)
                temporary.replace(target)
                return _Lease(self, relative, size, content_hash, True, lock)
            except Exception:
                lock.__exit__(None, None, None)
                raise
        finally:
            temporary.unlink(missing_ok=True)

    def _acquire_digest_lock(self, digest: str) -> WorkspaceOperationLock:
        lock = WorkspaceOperationLock(self.files_root.parent / ".file-content-locks" / f"{digest}.lock")
        deadline = time.monotonic() + 10
        while True:
            try:
                return lock.__enter__()
            except WorkspaceOperationInProgressError as error:
                if time.monotonic() >= deadline:
                    raise FileError("Another upload of the same content did not finish in time.") from error
                time.sleep(0.05)

    def path_for(self, relative_path: str, content_hash: str, size: int) -> Path:
        path = (self.files_root / relative_path).resolve()
        if self.files_root.resolve() not in path.parents or not path.is_file():
            raise FileError("Stored file content is unavailable.")
        digest = hashlib.sha256(); actual = 0
        with path.open("rb") as input_file:
            while chunk := input_file.read(1024 * 1024):
                actual += len(chunk); digest.update(chunk)
        if actual != size or digest.hexdigest() != content_hash:
            raise FileError("Stored file content failed its integrity check.")
        return path

"""Pin a pre-created control-tree lock; never create or unlink its stable inode."""

import fcntl
import os
from pathlib import Path
import stat

from app.platform.locking import WorkspaceOperationInProgressError


PRIVATE_MODE = 0o600


class HostedWriterLock:
    def __init__(self, path: Path):
        self.path = path
        self.descriptor = None
        self.identity = None

    def __enter__(self):
        if self.descriptor is not None:
            raise WorkspaceOperationInProgressError("Workspace writer is already active.")
        descriptor = None
        try:
            if not self.path.is_absolute() or self.path.resolve(strict=True) != self.path:
                raise OSError("Unsafe writer lock")
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            info = os.fstat(descriptor)
            identity = (info.st_dev, info.st_ino)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != PRIVATE_MODE
                or info.st_nlink != 1
                or (self.identity is not None and self.identity != identity)
            ):
                raise OSError("Unsafe writer lock")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.descriptor, self.identity = descriptor, identity
        except OSError as error:
            if descriptor is not None:
                os.close(descriptor)
            raise WorkspaceOperationInProgressError("Workspace writer is unavailable.") from error
        return self

    def __exit__(self, *args):
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None

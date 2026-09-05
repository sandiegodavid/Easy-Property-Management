"""Backup destination rules and workspace operation locks."""

from __future__ import annotations

import os
import tempfile
import warnings
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Iterator

from app.modules.workspace.application.backup_models import BackupError, PackageType
from app.modules.workspace.application.service import WorkspacePaths, WorkspaceService
from app.platform.config import LocalConfig, LocalConfigError, repository_root, save_backup_destination
from app.platform.locking import WorkspaceOperationInProgressError, WorkspaceOperationLock


class BackupDestinationPolicy:
    def __init__(self, workspace_service: WorkspaceService) -> None:
        self.workspace_service = workspace_service

    @property
    def paths(self) -> WorkspacePaths:
        return self.workspace_service.paths

    def configure(self, destination_path: Path) -> LocalConfig:
        destination = destination_path.expanduser().resolve()
        self.validate_external(destination)
        created = not destination.exists()
        try:
            destination.mkdir(parents=True, exist_ok=True)
            if created:
                secure_directory(destination)
            _require_atomic_archive_publication(destination)
            updated = save_backup_destination(self.workspace_service.config, destination)
        except (OSError, LocalConfigError) as error:
            raise BackupError(f"Backup destination is not writable: {error}") from error
        self.workspace_service.config = updated
        if _same_volume(destination, self.paths.root):
            warnings.warn("Backup destination is on the same volume as the live workspace.", RuntimeWarning, stacklevel=2)
        return updated

    def resolve_output(self, workspace_id: str, package_type: PackageType, output_path: Path | None) -> Path:
        if output_path is not None:
            destination = output_path.expanduser().resolve()
            self.validate_external(destination.parent)
            destination.parent.mkdir(parents=True, exist_ok=True)
            _require_atomic_archive_publication(destination.parent)
            if destination.suffix != ".epm-backup":
                destination = destination.with_suffix(".epm-backup")
            if destination.exists():
                raise BackupError("Refusing to overwrite an existing backup archive.")
            return destination
        destination = self.require_configured()
        from datetime import UTC, datetime
        from uuid import uuid4

        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
        return destination / f"easy-property-management-{package_type}-{stamp}-{workspace_id[:8]}-{uuid4().hex[:8]}.epm-backup"

    def require_configured(self) -> Path:
        destination = self.workspace_service.config.backup_destination_path
        if destination is None:
            raise BackupError("No separate backup destination is configured.")
        self.validate_external(destination)
        created = not destination.exists()
        destination.mkdir(parents=True, exist_ok=True)
        if created:
            secure_directory(destination)
        _require_atomic_archive_publication(destination)
        return destination

    def validate_external(self, destination: Path) -> None:
        workspace_root = self.paths.root.resolve()
        repository = repository_root().resolve()
        resolved = destination.resolve()
        if resolved == workspace_root or workspace_root in resolved.parents:
            raise BackupError("Backup destination must be outside the live workspace.")
        if resolved == repository or repository in resolved.parents:
            raise BackupError("Backup destination must be outside the Git repository.")

    def validate_restore_destination(self, destination: Path) -> None:
        self.validate_external(destination)
        if destination.exists() and any(destination.iterdir()):
            raise BackupError("Restore destination must be new or an empty directory.")


class WorkspaceLockCoordinator:
    def __init__(self, paths: WorkspacePaths) -> None:
        self.paths = paths

    @contextmanager
    def operation(self) -> Iterator[None]:
        with self._lock_at(self.paths.root.parent / f".{self.paths.root.name}.operations.lock"):
            yield

    @contextmanager
    def restore(self, destination: Path) -> Iterator[None]:
        active_parent = self.paths.root.parent
        if active_parent.is_dir():
            with self.operation():
                with self._destination_lock(destination):
                    yield
            return
        with self._destination_lock(destination):
            yield

    @contextmanager
    def _destination_lock(self, destination: Path) -> Iterator[None]:
        key = sha256(str(destination).encode("utf-8")).hexdigest()
        lock_path = Path(tempfile.gettempdir()) / "easy-property-management-locks" / f"restore-{key}.lock"
        with self._lock_at(lock_path):
            yield

    @contextmanager
    def _lock_at(self, lock_path: Path) -> Iterator[None]:
        try:
            with WorkspaceOperationLock(lock_path):
                yield
        except WorkspaceOperationInProgressError as error:
            raise BackupError(str(error)) from error


def secure_directory(directory: Path) -> None:
    if os.name == "posix":
        directory.chmod(0o700)


def secure_file(file_path: Path) -> None:
    if os.name == "posix":
        file_path.chmod(0o600)


def _same_volume(first: Path, second: Path) -> bool:
    try:
        return os.stat(first).st_dev == os.stat(second).st_dev
    except OSError:
        return False


def _require_atomic_archive_publication(destination: Path) -> None:
    """Reject destinations that cannot atomically publish a completed archive."""
    source = destination / f".epm-publication-probe-{os.urandom(8).hex()}"
    target = destination / f".epm-publication-probe-{os.urandom(8).hex()}"
    try:
        source.write_bytes(b"probe")
        os.link(source, target)
    except OSError as error:
        raise BackupError(
            "Backup destination does not support required atomic archive publication; "
            "choose a filesystem with hard-link support."
        ) from error
    finally:
        target.unlink(missing_ok=True)
        source.unlink(missing_ok=True)

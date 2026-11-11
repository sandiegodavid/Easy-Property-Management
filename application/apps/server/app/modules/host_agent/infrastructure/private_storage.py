"""Root-only preparation of fresh registered projects; no adoption or recursive cleanup."""

import os
from pathlib import Path
import stat

from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.hosted_admin.infrastructure.project_quota import ProjectQuota, protected_directory

ROLES = ("workspace", "control", "scratch")


class PrivateStorage:
    def __init__(self, targets):
        self.targets = targets

    def projects(self, allocation):
        if allocation.limits is None:
            raise HostAgentDenied()
        return tuple(ProjectQuota(binding) for binding in self.targets.bindings(allocation))

    def prepare(self, allocation):
        projects = self.projects(allocation)
        # Verify mount/enforcement and protected parents before reserving any path.
        for project in projects:
            project.filesystem()
            with protected_directory(project.binding.directory.parent):
                if project.binding.directory.exists() or project.binding.directory.is_symlink():
                    raise HostAgentDenied()
        for role, project in zip(ROLES, projects, strict=True):
            path = project.binding.directory
            # Root can initialize mode 000. Owning UID cannot write before ALL limits exist.
            path.mkdir(mode=0o000)
            project.initialize_empty()
            os.chown(path, allocation.host_uid, allocation.host_gid)
            limits = getattr(allocation.limits, role)
            project.set_limits(limits.byte_ceiling, limits.inode_ceiling)
            if role == "control":
                data = path / "data"
                data.mkdir(mode=0o700)
                os.chown(data, allocation.host_uid, allocation.host_gid)
                descriptor = os.open(
                    path / "writer.lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
                try:
                    os.fchown(descriptor, allocation.host_uid, allocation.host_gid)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        granted = []
        try:
            for project in projects:
                project.observe()
                project.binding.directory.chmod(0o700)
                granted.append(project.binding.directory)
            return self.verify(allocation)
        except Exception:
            for path in reversed(granted):
                path.chmod(0o000)
            raise

    def verify(self, allocation):
        result = {}
        for role, project in zip(ROLES, self.projects(allocation), strict=True):
            path = project.binding.directory
            self._private(path, allocation, directory=True)
            actual = project.observe()
            limits = getattr(allocation.limits, role)
            if (
                actual["hard_bytes"] != ((limits.byte_ceiling + 1023) // 1024) * 1024
                or actual["hard_inodes"] != limits.inode_ceiling
            ):
                raise HostAgentDenied()
            result[role] = actual
            if role == "control":
                self._private(path / "data", allocation, directory=True)
                self._private(path / "writer.lock", allocation, directory=False)
        return result

    @staticmethod
    def _private(path: Path, allocation, *, directory):
        info = path.lstat()
        if (
            info.st_uid != allocation.host_uid
            or info.st_gid != allocation.host_gid
            or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or (not directory and info.st_nlink != 1)
        ):
            raise HostAgentDenied()

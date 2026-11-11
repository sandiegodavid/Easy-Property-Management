"""Refresh host service inputs from owning inventory; never resume Caddy autosave."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
from tempfile import NamedTemporaryFile

from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.host_agent.infrastructure.gateway import closed_config
from app.modules.host_agent.infrastructure.host_services import tunnel_config


class ProjectionPublisher:
    """Protected setup owns this root directory and separate read-only service groups."""

    def __init__(self, directory: Path, *, reader_gid: int):
        self.directory, self.reader_gid = directory, reader_gid
        self.identity = self._directory()

    def _directory(self):
        info = self.directory.lstat()
        if (
            self.directory.resolve(strict=True) != self.directory
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_gid != self.reader_gid
            or stat.S_IMODE(info.st_mode) != 0o750
        ):
            raise HostAgentDenied()
        return info.st_dev, info.st_ino

    @contextmanager
    def _parent(self):
        if self._directory() != self.identity:
            raise HostAgentDenied()
        descriptor = os.open(self.directory, os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if (info.st_dev, info.st_ino) != self.identity:
                raise HostAgentDenied()
            yield descriptor
        finally:
            os.close(descriptor)

    def publish(self, config):
        data = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
        if len(data) > 8 * 1024 * 1024:
            raise HostAgentDenied()
        with self._parent() as parent:
            with NamedTemporaryFile(dir=self.directory, delete=False) as file:
                name = Path(file.name).name
                try:
                    file.write(data)
                    file.flush()
                    os.fchown(file.fileno(), os.geteuid(), self.reader_gid)
                    os.fchmod(file.fileno(), 0o640)
                    os.fsync(file.fileno())
                    os.replace(name, "config.json", src_dir_fd=parent, dst_dir_fd=parent)
                    os.fsync(parent)
                finally:
                    try:
                        os.unlink(name, dir_fd=parent)
                    except FileNotFoundError:
                        pass


class IngressBootstrap:
    def __init__(
        self,
        inventory,
        gateway_settings,
        tunnel_settings,
        gateway_files,
        tunnel_files,
        *,
        contain_all,
    ):
        self.inventory, self.gateway_settings, self.tunnel_settings = (
            inventory,
            gateway_settings,
            tunnel_settings,
        )
        self.gateway_files, self.tunnel_files, self.contain_all = (
            gateway_files,
            tunnel_files,
            contain_all,
        )

    def refresh(self):
        # The service runner must call this before *every* gateway start, not just
        # once on boot. No Admin RPC is needed to retain the current protected deny.
        with self.inventory.exclusive():
            try:
                snapshot = self.inventory.ingress_projection()
                if self.gateway_settings.port != self.tunnel_settings.gateway_port:
                    raise HostAgentDenied()
                gateway = closed_config(snapshot, self.gateway_settings)
                tunnel = tunnel_config(snapshot, self.tunnel_settings)
                self.gateway_files.publish(gateway)
                self.tunnel_files.publish(tunnel)
            except Exception as original:
                try:
                    self.contain_all()
                except Exception as containment:
                    raise ExceptionGroup(
                        "Ingress startup requires attention.", [original, containment]
                    ) from original
                raise

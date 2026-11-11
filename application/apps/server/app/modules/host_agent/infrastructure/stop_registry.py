"""Protected stop-only projection. Inventory remains the sole allocation/start authority.

Created before starts, retained across agent death and damaged inventory. No discovery,
container adoption, automatic recreation or database schema. Only trusted host root
may operate this projection. Its separate singleton/gate lock orders containment with
in-flight starts, including systemd ExecStopPost after SIGKILL.
"""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
from tempfile import NamedTemporaryFile
from uuid import uuid4

from pydantic import model_validator

from app.modules.host_agent.application.build_inputs import HostPrincipal
from app.modules.host_agent.application.dispatch import (
    HostAgentDenied,
    HostAgentUnavailable,
    HostEffect,
)
from app.platform.hosted_contracts.semantic import SemanticRequest
from app.platform.hosted_contracts.values import RequestHash

MAX_TARGETS = 4096
MAX_BYTES = 32768
FILE_MODE = 0o600
DIRECTORY_MODE = 0o700


class StopTarget(SemanticRequest):
    command: HostEffect
    container_id: RequestHash
    image_digest: RequestHash
    host_uid: HostPrincipal
    host_gid: HostPrincipal

    @model_validator(mode="after")
    def nonroot(self):
        if (
            self.host_uid <= 0
            or self.host_gid <= 0
            or self.command.effect.kind != "start_container"
        ):
            raise ValueError("A registered non-root start target is required.")
        return self

    def matches(self, other):
        # One container can have multiple start commands. Its original projection
        # keeps the first command solely for owning scope lookup, never for replay.
        return (
            self.container_id,
            self.image_digest,
            self.host_uid,
            self.host_gid,
            self.command.effect.binding_id,
            self.command.effect.resource_generation,
            self.command.effect.parent.scope,
            self.command.effect.parent.deployment_id,
        ) == (
            other.container_id,
            other.image_digest,
            other.host_uid,
            other.host_gid,
            other.command.effect.binding_id,
            other.command.effect.resource_generation,
            other.command.effect.parent.scope,
            other.command.effect.parent.deployment_id,
        )


class StopRegistry:
    def __init__(self, directory: Path):
        self.directory = directory
        self.owner = os.geteuid()
        if not directory.is_absolute() or directory.resolve(strict=True) != directory:
            raise HostAgentDenied()
        info = directory.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != self.owner
            or stat.S_IMODE(info.st_mode) != DIRECTORY_MODE
        ):
            raise HostAgentDenied()
        self.identity = (info.st_dev, info.st_ino)

    def _directory(self):
        info = self.directory.lstat()
        if (
            info.st_dev,
            info.st_ino,
        ) != self.identity or self.directory.resolve() != self.directory:
            raise HostAgentDenied()
        if info.st_uid != self.owner or stat.S_IMODE(info.st_mode) != DIRECTORY_MODE:
            raise HostAgentDenied()

    @contextmanager
    def lock(self, name, *, wait=False):
        self._directory()
        descriptor = os.open(
            self.directory / name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, FILE_MODE
        )
        try:
            self._file(descriptor)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
            except BlockingIOError as error:
                raise HostAgentUnavailable() from error
            yield descriptor
        finally:
            os.close(descriptor)

    def _file(self, descriptor):
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != self.owner
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != FILE_MODE
        ):
            raise HostAgentDenied()

    def read(self, name):
        self._directory()
        descriptor = os.open(self.directory / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            self._file(descriptor)
            data = os.read(descriptor, MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise HostAgentDenied()
            return data
        finally:
            os.close(descriptor)

    def _sync(self):
        descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def publish(self, name, data, *, immutable=False):
        self._directory()
        if len(data) > MAX_BYTES:
            raise HostAgentDenied()
        with NamedTemporaryFile(dir=self.directory, prefix=".pending-", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
                if immutable:
                    os.link(temporary, self.directory / name, follow_symlinks=False)
                else:
                    os.replace(temporary, self.directory / name)
                self._sync()
            finally:
                temporary.unlink(missing_ok=True)

    def targets(self):
        # The path inventory is root-controlled, bounded and never a Docker label scan.
        self._directory()
        names = []
        with os.scandir(self.directory) as entries:
            for entry in entries:
                if entry.name.endswith(".target"):
                    names.append(entry.name)
                    if len(names) > MAX_TARGETS:
                        raise HostAgentUnavailable()
        return tuple(sorted(names))

    def target(self, name):
        result = StopTarget.model_validate_json(self.read(name))
        if name != result.container_id + ".target":
            raise HostAgentDenied()
        return result

    def register(self, target):
        name = target.container_id + ".target"
        if (self.directory / name).exists():
            if not self.target(name).matches(target):
                raise HostAgentDenied()
        else:
            if len(self.targets()) >= MAX_TARGETS:
                raise HostAgentUnavailable()
            self.publish(name, target.model_dump_json().encode(), immutable=True)

    def note(self, target, *, stopped):
        self.publish(
            target.container_id + ".attention",
            json.dumps(
                {"code": "runtime_needs_attention", "stop_verified": stopped}, sort_keys=True
            ).encode(),
        )

    def _owner_live(self):
        descriptor = os.open(
            self.directory / "owner.lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
        )
        try:
            self._file(descriptor)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                epoch = os.pread(descriptor, 128, 0)
                if (
                    not epoch
                    or not (self.directory / "ready").exists()
                    or self.read("ready") != epoch
                ):
                    raise HostAgentUnavailable()
                return
            raise HostAgentUnavailable()
        finally:
            os.close(descriptor)

    @contextmanager
    def starting(self, command, allocation, actual):
        with self.lock("gate.lock"):
            self._owner_live()
            target = StopTarget(
                command=command,
                container_id=actual["Id"],
                image_digest=allocation.image_digest,
                host_uid=allocation.host_uid,
                host_gid=allocation.host_gid,
            )
            self.register(target)
            yield
            # Still current after an in-flight start? A dead owner is not readiness.
            self._owner_live()

    @contextmanager
    def owner_lease(self):
        with self.lock("owner.lock") as descriptor:
            epoch = str(uuid4()).encode()
            os.ftruncate(descriptor, 0)
            os.write(descriptor, epoch)
            os.fsync(descriptor)
            self.unready()
            try:
                yield lambda: self.publish("ready", epoch)
            finally:
                self.unready()

    def unready(self):
        self._directory()
        (self.directory / "ready").unlink(missing_ok=True)
        self._sync()

    def contain(self, engine, target):
        # Exact immutable Engine ID is the stop authority. No labels, file paths,
        # current inventory or changed sandbox can redirect it to another runtime.
        stopped = False
        try:
            actual = engine.inspect(target.container_id)
            if actual is not None and actual["State"]["Running"]:
                try:
                    engine.stop(target.container_id)
                except Exception:
                    # A lost response may have stopped it. Inspect, never claim a stop
                    # from the request result alone or retry an unknown allocation.
                    pass
                actual = engine.inspect(target.container_id)
            stopped = actual is None or actual["State"]["Running"] is False
            if not stopped:
                raise HostAgentUnavailable()
        finally:
            self.note(target, stopped=stopped)

    def contain_all(self, engine):
        failures = []
        with self.lock("gate.lock", wait=True):
            self.unready()
            for name in self.targets():
                try:
                    self.contain(engine, self.target(name))
                except Exception as error:
                    failures.append(error)
        if failures:
            raise ExceptionGroup("Runtime containment requires attention.", failures)

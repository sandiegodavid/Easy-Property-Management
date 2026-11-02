"""Private Linux ext4 project-quota primitives; no portal accepts these bindings.

The root collector supplies a protected binding. Observations do not establish
sandbox qualification and never use host free space as project usage.
"""

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
from uuid import UUID

GET_ATTRIBUTES = 0x801C581F
SET_ATTRIBUTES = 0x401C5820
INHERIT = 0x200
QUOTA_BLOCK = 1024


class QuotaUnavailable(ValueError):
    """Privacy-safe failure suitable for existing unavailable/readiness views."""

    def __init__(self, code="admin_project_quota_unavailable"):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ProjectBinding:
    mount: Path
    directory: Path
    filesystem_uuid: str
    project_id: int
    uid: int

    def __post_init__(self):
        if (
            not self.mount.is_absolute()
            or not self.directory.is_absolute()
            or ".." in self.directory.parts
            or ".." in self.mount.parts
            or self.directory == self.mount
            or not self.directory.is_relative_to(self.mount)
            or str(UUID(self.filesystem_uuid)) != self.filesystem_uuid
            or type(self.project_id) is not int
            or not 0 < self.project_id < 2**32
            or type(self.uid) is not int
            or self.uid <= 0
        ):
            raise QuotaUnavailable("admin_project_binding_invalid")


class DiskQuota(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "block_hard",
            "block_soft",
            "allocated_bytes",
            "inode_hard",
            "inode_soft",
            "allocated_inodes",
            "block_time",
            "inode_time",
        )
    ] + [("valid", ctypes.c_uint32)]


class QuotaInfo(ctypes.Structure):
    _fields_ = [
        ("block_grace", ctypes.c_uint64),
        ("inode_grace", ctypes.c_uint64),
        ("flags", ctypes.c_uint32),
        ("valid", ctypes.c_uint32),
    ]


@contextmanager
def protected_directory(path, uid=0, owned_root=None):
    """Walk without following any symlink, retaining the opened leaf."""
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, part in enumerate(path.parts[1:]):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            info = os.fstat(descriptor)
            current = Path(*path.parts[: index + 2])
            owner = (
                uid
                if index == len(path.parts) - 2
                or (owned_root and current.is_relative_to(owned_root))
                else 0
            )
            if info.st_uid != owner or info.st_mode & 0o022:
                raise QuotaUnavailable("admin_project_path_unsafe")
        yield descriptor
    finally:
        os.close(descriptor)


def attributes(descriptor):
    buffer = bytearray(28)
    fcntl.ioctl(descriptor, GET_ATTRIBUTES, buffer, True)
    return struct.unpack("=5I8s", buffer)


class ProjectQuota:
    def __init__(self, binding):
        self.binding = binding

    def filesystem(self):
        if sys.platform != "linux" or os.geteuid() != 0:
            raise QuotaUnavailable("admin_project_probe_requires_root_linux")
        binding = self.binding
        with protected_directory(binding.mount):
            result = subprocess.run(
                [
                    "/usr/bin/findmnt",
                    "--json",
                    "--target",
                    str(binding.mount),
                    "--output",
                    "TARGET,SOURCE,FSTYPE,UUID",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            rows = json.loads(result.stdout)["filesystems"]
            if len(rows) != 1:
                raise QuotaUnavailable()
            row = rows[0]
            device = Path(row["source"])
            if (
                row["target"] != str(binding.mount)
                or row["fstype"] != "ext4"
                or row["uuid"] != binding.filesystem_uuid
                or not device.is_absolute()
                or not stat.S_ISBLK(device.stat().st_mode)
                or device.stat().st_rdev != binding.mount.stat().st_dev
            ):
                raise QuotaUnavailable("admin_project_filesystem_changed")
        features = subprocess.run(
            ["/usr/sbin/tune2fs", "-l", str(device)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
        fields = dict(line.split(":", 1) for line in features.splitlines() if ":" in line)
        if (
            not {"project", "quota"} <= set(fields.get("Filesystem features", "").split())
            or int(fields.get("Inode size", "0")) < 256
        ):
            raise QuotaUnavailable("admin_project_features_unavailable")
        self._control(device, 0x800005, QuotaInfo())
        # Q_GETINFO proves accounting only: ext4 keeps it on after quotaoff.
        # The generic VFS Q_XGETQSTATV ABI separately reports enforcement.
        status = ctypes.create_string_buffer(256)
        status[0] = 1
        self._control(device, 0x5808, status)
        flags = struct.unpack_from("=H", status.raw, 2)[0]
        if flags & 0x30 != 0x30:  # FS_QUOTA_PDQ_ACCT | FS_QUOTA_PDQ_ENFD
            raise QuotaUnavailable("admin_project_enforcement_unavailable")
        return device

    def _control(self, device, command, value):
        libc = ctypes.CDLL(None, use_errno=True)
        libc.quotactl.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
        libc.quotactl.restype = ctypes.c_int
        result = libc.quotactl(
            (command << 8) | 2,
            os.fsencode(device),
            self.binding.project_id if command not in {0x800005, 0x5808} else 0,
            ctypes.byref(value),
        )
        if result:
            raise QuotaUnavailable("admin_project_enforcement_unavailable")
        return value

    def initialize_empty(self):
        """Root-owned EMPTY destination only; never relabel a populated tree."""
        self.filesystem()
        with protected_directory(self.binding.directory) as descriptor:
            if os.listdir(descriptor):
                raise QuotaUnavailable("admin_project_destination_not_empty")
            current = list(attributes(descriptor))
            if current[3] not in {0, self.binding.project_id}:
                raise QuotaUnavailable("admin_project_identity_changed")
            current[0] |= INHERIT
            current[3] = self.binding.project_id
            fcntl.ioctl(descriptor, SET_ATTRIBUTES, struct.pack("=5I8s", *current))
            if attributes(descriptor)[3] != self.binding.project_id:
                raise QuotaUnavailable()

    def set_limits(self, hard_bytes, hard_inodes):
        if any(
            type(value) is not int or not 0 < value < 2**63 for value in (hard_bytes, hard_inodes)
        ):
            raise QuotaUnavailable("admin_project_limits_invalid")
        device = self.filesystem()
        with protected_directory(self.binding.directory, self.binding.uid) as descriptor:
            if attributes(descriptor)[3] != self.binding.project_id:
                raise QuotaUnavailable("admin_project_identity_changed")
        quota = DiskQuota()
        quota.block_hard = (hard_bytes + QUOTA_BLOCK - 1) // QUOTA_BLOCK
        quota.inode_hard = hard_inodes
        quota.valid = 1 | 4  # QIF_BLIMITS | QIF_ILIMITS; zero soft limits, no grace.
        self._control(device, 0x800008, quota)
        return self.observe()

    def observe(self):
        device = self.filesystem()
        with protected_directory(self.binding.directory, self.binding.uid) as descriptor:
            flags, _, _, project, _, _ = attributes(descriptor)
            if (
                project != self.binding.project_id
                or not flags & INHERIT
                or os.fstat(descriptor).st_dev != self.binding.mount.stat().st_dev
            ):
                raise QuotaUnavailable("admin_project_identity_changed")
        quota = self._control(device, 0x800007, DiskQuota())
        if not quota.block_hard or not quota.inode_hard:
            raise QuotaUnavailable("admin_project_limits_missing")
        return {
            "project_id": project,
            "allocated_bytes": quota.allocated_bytes,
            "allocated_inodes": quota.allocated_inodes,
            "hard_bytes": quota.block_hard * QUOTA_BLOCK,
            "hard_inodes": quota.inode_hard,
        }

    def verify_tree(self, maximum=100000):
        """Explicit stopped-writer attribution check, never a usage HTTP scan."""
        if type(maximum) is not int or not 0 < maximum <= 100000:
            raise QuotaUnavailable("admin_project_scan_bound_invalid")
        self.observe()
        pending = [self.binding.directory]
        visited = 0
        while pending:
            path = pending.pop()
            with protected_directory(path, self.binding.uid, self.binding.directory) as descriptor:
                values = attributes(descriptor)
                if values[3] != self.binding.project_id or not values[0] & INHERIT:
                    raise QuotaUnavailable("admin_project_descendant_invalid")
                for name in os.listdir(descriptor):
                    visited += 1
                    if visited > maximum:
                        raise QuotaUnavailable("admin_project_scan_bound_exceeded")
                    info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(path / name)
                        continue
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != self.binding.uid:
                        raise QuotaUnavailable("admin_project_descendant_invalid")
                    child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
                    try:
                        if attributes(child)[3] != self.binding.project_id:
                            raise QuotaUnavailable("admin_project_descendant_invalid")
                    finally:
                        os.close(child)
        return visited

    def availability(self):
        """Existing Admin unavailable shape; no private binding/OS exception text."""
        try:
            self.observe()
            return {"state": "available", "error": None}
        except (OSError, ValueError, subprocess.SubprocessError) as _error:
            return {"state": "unavailable", "error": "admin_project_quota_unavailable"}

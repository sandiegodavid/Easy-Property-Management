"""Linux fixed-size ext4 loop volume: hard capacity, including staging/journals.

No mount/resize is performed by the application. Root provisions the volume and
keeps the backing image inaccessible to the unprivileged application identity.
"""

import os
from pathlib import Path
import re
import stat
import tempfile

from app.modules.hosted_access.application.configuration import (
    HostedConfigurationError,
    WORKSPACE_BYTES,
)
from app.modules.hosted_access.application.storage_budget import HostedStorageBudget, StorageFacts

SECTOR_BYTES = 512


def _unescape(value):
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)


def _protected_image(path):
    for parent in path.parents:
        info = parent.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
            raise HostedConfigurationError(
                "Storage image parents must be protected and root-owned."
            )
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or info.st_mode & 0o077
        or info.st_size != WORKSPACE_BYTES
        or info.st_blocks * SECTOR_BYTES < info.st_size
    ):
        raise HostedConfigurationError(
            "Storage image must be root-owned, private, fully allocated and exactly 250 MiB."
        )


def _mount_identity(volume):
    entries = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        fields = line.split()
        separator = fields.index("-")
        if _unescape(fields[4]) == str(volume):
            entries.append((fields, separator))
    if len(entries) != 1:
        raise HostedConfigurationError("Storage volume must be a dedicated Linux mount.")
    fields, separator = entries[0]
    if fields[3] != "/" or fields[separator + 1] != "ext4":
        raise HostedConfigurationError(
            "A complete dedicated ext4 volume is required, not a bind/subvolume."
        )
    required = {"rw", "nodev", "nosuid", "noexec"}
    if not required.issubset(fields[5].split(",")):
        raise HostedConfigurationError("Storage mount requires rw,nodev,nosuid,noexec.")
    device = fields[2]
    if not re.fullmatch(r"\d+:\d+", device):
        raise HostedConfigurationError("Storage block device is invalid.")
    return device


def validate_storage_volume(deployment, workspace_root):
    volume, image = deployment.storage_volume, deployment.storage_image
    if os.name != "posix" or not Path("/proc/self/mountinfo").is_file() or os.geteuid() == 0:
        raise HostedConfigurationError(
            "Hosted storage requires Linux and an unprivileged service identity."
        )
    if any(path.is_symlink() for path in (volume, *volume.parents)):
        raise HostedConfigurationError("Storage volume cannot use symlink paths.")
    _protected_image(image)
    device = _mount_identity(volume)
    sys_device = Path("/sys/dev/block") / device
    if (sys_device / "size").read_text().strip() != str(WORKSPACE_BYTES // SECTOR_BYTES):
        raise HostedConfigurationError("Storage block device must be exactly 250 MiB.")
    backing = _unescape((sys_device / "loop/backing_file").read_text().strip())
    if Path(backing) != image:
        raise HostedConfigurationError("Storage mount does not match the pinned backing image.")
    temporary = Path(os.environ.get("TMPDIR", ""))
    if temporary != volume / "tmp" or Path(tempfile.gettempdir()).resolve() != temporary:
        raise HostedConfigurationError(
            "TMPDIR and Python staging must use the volume's private tmp directory."
        )
    paths = (workspace_root, temporary)
    for path in paths:
        if volume not in path.parents or path.resolve() != path:
            raise HostedConfigurationError(
                "Workspace and staging must be real children of the storage volume."
            )
        info = path.stat()
        if (
            info.st_uid != os.geteuid()
            or info.st_mode & 0o077
            or info.st_dev != volume.stat().st_dev
        ):
            raise HostedConfigurationError(
                "Workspace and staging must be private to the service and on the bounded volume."
            )
    if volume in deployment.administration_database.resolve().parents:
        raise HostedConfigurationError(
            "Administrative recovery state must remain outside the quota volume."
        )
    usage = os.statvfs(volume)
    if (usage.f_bfree - usage.f_bavail) * usage.f_frsize < 16 * 1024 * 1024:
        raise HostedConfigurationError(
            "The volume must reserve at least 16 MiB for root-only recovery."
        )
    return volume, image


def build_storage_budget(deployment, workspace_root):
    try:
        volume, image = validate_storage_volume(deployment, workspace_root)
    except (OSError, ValueError) as error:
        if isinstance(error, HostedConfigurationError):
            raise
        raise HostedConfigurationError(
            "The bounded hosted storage volume could not be validated."
        ) from error
    device = volume.stat().st_dev

    def facts():
        sys_device = Path("/sys/dev/block") / f"{os.major(device)}:{os.minor(device)}"
        if (
            volume.stat().st_dev != device
            or image.stat().st_size != WORKSPACE_BYTES
            or (sys_device / "size").read_text().strip() != str(WORKSPACE_BYTES // SECTOR_BYTES)
        ):
            raise ValueError("The bounded mount changed.")
        bounded, host = os.statvfs(volume), os.statvfs(image.parent)
        return StorageFacts(
            capacity_bytes=WORKSPACE_BYTES,
            available_bytes=bounded.f_bavail * bounded.f_frsize,
            host_total_bytes=host.f_blocks * host.f_frsize,
            host_available_bytes=host.f_bavail * host.f_frsize,
            available_inodes=bounded.f_favail,
        )

    return HostedStorageBudget(facts)

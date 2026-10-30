"""Opt-in root Linux proof over a disposable image and actual hosted validator."""

import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts.host_admin import HostPaths, protected
from app.modules.hosted_admin.infrastructure.linux_provisioning import LinuxProvisioning
from app.modules.hosted_access.infrastructure.storage_budget import validate_storage_volume


@pytest.mark.skipif(
    sys.platform != "linux"
    or os.geteuid() != 0
    or os.environ.get("EPM_RUN_LINUX_VOLUME_QUALIFICATION") != "1",
    reason="Explicit root Linux qualification with loop-mount capability is required",
)
def test_real_formatter_mount_and_unprivileged_hosted_storage_validation():
    # /var/lib avoids writable /tmp ancestors forbidden by the owning validator.
    # This test never uses registered instances, systemd, fstab or provider APIs.
    with TemporaryDirectory(prefix="epm-volume-qualification-", dir="/var/lib") as directory:
        root = Path(directory)
        root.chmod(0o711)
        paths = HostPaths(data=root, security_root=root, owner_uid=0)
        adapter = LinuxProvisioning(
            SimpleNamespace(paths=paths, protected=protected), subprocess.run
        )
        payload = {"target": "d-test", "operation_id": str(uuid4())}
        locations = adapter.paths_for("d-test")
        for parent in (locations["image"].parent, locations["home"], locations["volume"]):
            parent.mkdir(mode=0o711)
        adapter.image(payload)
        adapter.image(payload)  # Existing UUID must be reused without reformatting.
        image, volume = locations["image"], locations["volume"]
        assert image.stat().st_blocks * 512 >= image.stat().st_size == 250 * 1024 * 1024
        subprocess.run(
            ["/usr/bin/mount", "-o", "loop,nodev,nosuid,noexec", str(image), str(volume)],
            check=True,
        )
        try:
            identity = pwd.getpwnam("nobody")
            for path in (volume, volume / "tmp", locations["workspace"]):
                path.mkdir(exist_ok=True)
                os.chown(path, identity.pw_uid, identity.pw_gid)
                path.chmod(0o700)
            # Fork inherits imports without exposing a root-only source checkout.
            read, write = os.pipe()
            child = os.fork()
            if child == 0:
                os.close(read)
                try:
                    os.setgroups([])
                    os.setgid(identity.pw_gid)
                    os.setuid(identity.pw_uid)
                    os.environ["TMPDIR"] = str(volume / "tmp")
                    import tempfile

                    tempfile.tempdir = None
                    deployment = SimpleNamespace(
                        storage_volume=volume,
                        storage_image=image,
                        administration_database=root / "access.sqlite",
                    )
                    validate_storage_volume(deployment, locations["workspace"])
                    result = {"verified": True}
                except Exception as error:
                    result = {"error": str(error)}
                os.write(write, json.dumps(result).encode())
                os.close(write)
                os._exit(0)
            os.close(write)
            with os.fdopen(read) as stream:
                result = json.load(stream)
            os.waitpid(child, 0)
            assert result == {"verified": True}
            assert image.stat().st_blocks * 512 >= image.stat().st_size
        finally:
            subprocess.run(["/usr/bin/umount", str(volume)], check=True)

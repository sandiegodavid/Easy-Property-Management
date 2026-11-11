"""Explicit fresh-GCE disk setup; never called from Add operator or service restart."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

GIB = 1024**3
SIZE = 50 * GIB
MOUNT = Path("/srv/epm/data")
STATE = Path("/etc/epm/bootstrap/data.json")
DEVICE = Path("/dev/disk/by-id/google-epm-h02-data")
UNIT = Path("/etc/systemd/system/srv-epm-data.mount")


def run(*args, check=True):
    return subprocess.run(
        [str(a) for a in args], check=check, capture_output=True, text=True, timeout=120
    )


def require_blank(tree, signatures):
    """Pure rejection gate before any formatting intent or mkfs call."""
    devices = tree.get("blockdevices", [])
    if len(devices) != 1:
        raise ValueError("A single fresh data disk is required")
    disk = devices[0]
    if (
        disk.get("type") != "disk"
        or disk.get("size") != SIZE
        or disk.get("children")
        or any(disk.get("mountpoints") or [])
        or signatures.get("signatures")
    ):
        raise ValueError("Data disk is not the reviewed empty 50-GiB device")


def save(value):
    temporary = STATE.with_suffix(".new")
    with temporary.open("x") as output:
        os.chmod(temporary, 0o600)
        output.write(json.dumps(value, sort_keys=True) + "\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(STATE)
    descriptor = os.open(STATE.parent, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def mounted(uuid):
    result = run("findmnt", "-J", "-M", MOUNT, "-o", "TARGET,UUID,FSTYPE,OPTIONS")
    rows = json.loads(result.stdout)["filesystems"]
    if len(rows) != 1:
        raise ValueError("The protected data mount is unavailable")
    row = rows[0]
    if (
        row["target"] != str(MOUNT)
        or row["uuid"] != uuid
        or row["fstype"] != "ext4"
        or not {"rw", "prjquota", "nodev", "nosuid", "noexec"} <= set(row["options"].split(","))
    ):
        raise ValueError("The protected data mount does not match its original identity")


def initialize():
    if (
        sys.platform != "linux"
        or os.geteuid() != 0
        or os.environ.get("EPM_H02_QUALIFICATION") != "1"
    ):
        raise RuntimeError("Explicit root qualification setup is required")
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if STATE.parent.resolve() != STATE.parent or STATE.parent.stat().st_mode & 0o077:
        raise ValueError("Unsafe bootstrap directory")
    with (STATE.parent / "disk.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        device = DEVICE.resolve(strict=True)
        if not stat.S_ISBLK(device.stat().st_mode):
            raise ValueError("The registered data device is not a block disk")
        if STATE.exists():
            state = json.loads(STATE.read_text())
            if state["phase"] != "ready":
                raise ValueError(
                    "Partial disk initialization requires private review, not reformatting"
                )
            actual = run("blkid", "-s", "UUID", "-o", "value", device).stdout.strip()
            if actual != state["uuid"]:
                raise ValueError("Data disk identity changed")
            mounted(actual)
            return state
        tree = json.loads(
            run("lsblk", "-b", "-J", "-o", "PATH,TYPE,SIZE,MOUNTPOINTS", device).stdout
        )
        signatures = json.loads(run("wipefs", "--json", "--no-act", device).stdout)
        require_blank(tree, signatures)
        MOUNT.mkdir(mode=0o711, parents=True, exist_ok=True)
        if MOUNT.resolve() != MOUNT or any(MOUNT.iterdir()):
            raise ValueError("The data mount point is not empty")
        # Persist intent BEFORE mkfs. An interrupted setup is never automatically adopted.
        save({"phase": "formatting", "device": str(DEVICE)})
        run("mkfs.ext4", "-q", "-F", "-O", "quota,project", "-I", "256", device)
        run("tune2fs", "-Q", "prjquota", device)
        uuid = run("blkid", "-s", "UUID", "-o", "value", device).stdout.strip()
        if not uuid:
            raise ValueError("No filesystem identity was observed")
        UNIT.write_text(f"""[Unit]
Description=EPM retained project-quota data disk
Before=docker.service
[Mount]
What=/dev/disk/by-uuid/{uuid}
Where={MOUNT}
Type=ext4
Options=prjquota,nodev,nosuid,noexec
[Install]
WantedBy=local-fs.target
""")
        run("systemctl", "daemon-reload")
        run("systemctl", "enable", "--now", UNIT.name)
        mounted(uuid)
        MOUNT.chmod(0o711)
        for role in ("workspace", "control", "scratch"):
            (MOUNT / role).mkdir(mode=0o711)
        state = {"phase": "ready", "device": str(DEVICE), "uuid": uuid}
        save(state)
        return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initialize-empty-disk", required=True, action="store_true")
    parser.parse_args()
    print(json.dumps(initialize(), sort_keys=True))

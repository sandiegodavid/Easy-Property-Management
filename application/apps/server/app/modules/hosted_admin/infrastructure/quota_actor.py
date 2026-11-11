"""Adversarial workload executed as the actual isolated non-login service UID.

Only the root qualification harness invokes this file. It never serves HTTP.
"""

import ctypes
import errno
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import tempfile


def denied(operation, allowed=(errno.EPERM, errno.EACCES, errno.EROFS, errno.EXDEV)):
    try:
        operation()
    except OSError as error:
        assert error.errno in allowed, (error.errno, allowed)
        return error.errno
    raise AssertionError("An escape unexpectedly succeeded")


def fill(directory, mode):
    try:
        for index in range(8192):
            with (directory / f"fill-{index}").open("wb", buffering=0) as stream:
                if mode == "bytes":
                    stream.write(b"x" * 65536)
                    os.fsync(stream.fileno())
        raise AssertionError("The project limit did not stop allocation")
    except OSError as error:
        assert error.errno == errno.EDQUOT, error
        return {"errno": error.errno, "iterations": index}


def deleted_file(directory):
    with (directory / "deleted-open").open("wb", buffering=0) as stream:
        (directory / "deleted-open").unlink()
        try:
            for _ in range(64):
                stream.write(b"d" * 65536)
                os.fsync(stream.fileno())
        except OSError as error:
            assert error.errno == errno.EDQUOT
            return {"errno": error.errno, "deleted_open_charged": True}
    raise AssertionError("Deleted-open content escaped its project quota")


def attacks(workspace, other, scratch):
    result = {}
    own = workspace / "owned"
    own.write_text("original")
    child = workspace / "child"
    child.mkdir()
    for target in (own, workspace, child):
        descriptor = os.open(target, os.O_RDONLY)
        try:
            for command in (0x401C5820, 0x40086602, 0x40046602, 0x40046604):
                # Direct native AND compatibility encodings on files/directories.
                value = bytearray(struct.pack("=5I8s", 0, 0, 0, 0, 0, b"\0" * 8))
                result[f"ioctl_{target.name}_{command:x}"] = denied(
                    lambda: fcntl.ioctl(descriptor, command, value)
                )
        finally:
            os.close(descriptor)
    inherited = subprocess.run(
        [
            sys.executable,
            "-c",
            "import fcntl,os,sys; fd=os.open(sys.argv[1],os.O_RDONLY); "
            "\ntry: fcntl.ioctl(fd,0x40046602,bytearray(8))"
            "\nexcept OSError as e: sys.exit(0 if e.errno==1 else 2)"
            "\nsys.exit(3)",
            str(own),
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    assert inherited.returncode == 0
    result["child_exec_filter"] = "mutation-denied"
    result["read_other"] = denied(lambda: (other / "secret").read_bytes())
    result["read_raw_image"] = denied(
        lambda: (workspace.parent.parent / "shared.ext4").read_bytes()
    )
    result["write_other"] = denied(lambda: (other / "escape").write_text("escape"))
    result["link_other"] = denied(lambda: os.link(other / "secret", workspace / "foreign"))
    result["rename_other"] = denied(lambda: os.rename(own, other / "escape"))
    result["link_scratch"] = denied(lambda: os.link(own, scratch / "cross-project"))
    result["rename_scratch"] = denied(lambda: os.rename(own, scratch / "cross-project"))
    for path in ("/etc/epm-escape", "/run/epm-escape", "/dev/shm/epm-escape"):
        result[path] = denied(lambda: Path(path).write_text("escape"))
    for path in ("/tmp", "/var/tmp", str(scratch)):
        with tempfile.NamedTemporaryFile(dir=path) as stream:
            stream.write(b"accounted temporary data")
            stream.flush()
            assert os.stat(stream.name).st_dev == workspace.stat().st_dev
        (Path(path) / ("temp-proof-" + str(len(result)))).write_text("accounted")
        result[path] = "writable-accounted"
    libc = ctypes.CDLL(None, use_errno=True)
    for name, args in (
        ("quotactl", (0x80000202, b"/dev/loop0", 0, None)),
        ("mount", (None, b"/tmp", None, 0, None)),
        ("unshare", (0x10000000,)),
    ):
        assert getattr(libc, name)(*args) == -1
        assert ctypes.get_errno() == errno.EPERM
        result[name] = errno.EPERM
    status = Path("/proc/self/status").read_text()
    assert "NoNewPrivs:\t1" in status and "CapEff:\t0000000000000000" in status
    for path in Path("/proc/self/fd").iterdir():
        if int(path.name) <= 2:
            continue
        try:
            target = path.resolve(strict=True)
        except FileNotFoundError:
            continue
        assert not target.is_file() or target.is_relative_to(workspace)
    result["inherited_descriptors"] = "no-unbudgeted-regular-files"
    # The same boundary must still support actual SQLite and file publication.
    connection = sqlite3.connect(workspace / "records.sqlite")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE records(value TEXT)")
    connection.execute("INSERT INTO records VALUES ('retained')")
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert connection.execute("SELECT value FROM records").fetchone() == ("retained",)
    connection.close()
    (child / "nested").write_text("inherits project")
    result["normal_writes"] = "sqlite-wal-checkpoint-and-files"
    return result


def main():
    mode, root, other, scratch = sys.argv[1:]
    directory = Path(root)
    if mode in {"bytes", "inodes"}:
        result = fill(directory, mode)
    elif mode == "deleted":
        result = deleted_file(directory)
    elif mode == "enforcement-off":
        (directory / "negative-control").write_bytes(b"n" * (16 * 1024 * 1024))
        result = {"allocated_above_hard_limit_with_enforcement_off": True}
    else:
        result = attacks(directory, Path(other), Path(scratch))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

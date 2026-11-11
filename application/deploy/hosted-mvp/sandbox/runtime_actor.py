"""Disposable native Docker workload; never included in production candidates."""

import ctypes
import errno
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import resource
import signal
import struct
import sys
import time

from app.platform.hosted_writer_lock import HostedWriterLock
from app.platform.locking import WorkspaceOperationInProgressError


def deny(operation, allowed=(errno.EPERM, errno.EACCES, errno.EROFS, errno.ENOENT)):
    try:
        operation()
    except OSError as error:
        assert error.errno in allowed, error
        return error.errno
    raise AssertionError("Sandbox escape succeeded")


def security():
    output = {}
    root = Path("/workspace")
    own = root / "probe"
    own.write_text("retained")
    own.chmod(0o600)
    output["owned_chmod"] = "allowed"
    output["readonly_root_chmod"] = deny(lambda: Path("/etc/passwd").chmod(0o600))
    output["stable_lock_chmod"] = deny(lambda: Path("/control/writer.lock").chmod(0o600))
    for path in (root, own):
        descriptor = os.open(path, os.O_RDONLY)
        try:
            for request in (0x401C5820, 0x40086602, 0x40046602, 0x40046604):
                output[f"ioctl_{path.name}_{request:x}"] = deny(
                    lambda: fcntl.ioctl(
                        descriptor,
                        request,
                        bytearray(struct.pack("=5I8s", 0, 0, 0, 0, 0, b"\0" * 8)),
                    )
                )
        finally:
            os.close(descriptor)
    libc = ctypes.CDLL(None, use_errno=True)
    for name, args in (
        ("quotactl", (0x80000202, b"/dev/loop0", 0, None)),
        ("mount", (None, b"/tmp", None, 0, None)),
        ("unshare", (0x10000000,)),
    ):
        assert getattr(libc, name)(*args) == -1 and ctypes.get_errno() == errno.EPERM
        output[name] = errno.EPERM
    for path in (
        "/etc/escape",
        "/run/escape",
        "/dev/shm/escape",
        "/other/secret",
        "/var/run/docker.sock",
        "/control/writer.lock",
    ):
        output[path] = deny(lambda: Path(path).write_bytes(b"escape"))
    for path in ("/tmp", "/var/tmp", "/scratch", "/control/data"):
        target = Path(path) / "accounted"
        target.write_text("accounted")
        output[path] = "writable-accounted"
    connection = sqlite3.connect(root / "records.sqlite")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE IF NOT EXISTS records(value TEXT)")
    connection.execute("INSERT INTO records VALUES ('retained')")
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    status = Path("/proc/self/status").read_text()
    assert "NoNewPrivs:\t1" in status and "CapEff:\t0000000000000000" in status
    cgroup = Path("/sys/fs/cgroup")
    output["cgroup"] = {
        name: (cgroup / name).read_text().strip()
        for name in ("memory.max", "memory.swap.max", "pids.max", "cpu.max")
    }
    assert output["cgroup"]["memory.max"] == str(128 * 1024 * 1024)
    assert output["cgroup"]["memory.swap.max"] == "0" and output["cgroup"]["pids.max"] == "32"
    quota, period = map(int, output["cgroup"]["cpu.max"].split())
    assert quota * 2 == period
    assert resource.getrlimit(resource.RLIMIT_CORE) == (0, 0)
    assert resource.getrlimit(resource.RLIMIT_NOFILE) == (128, 128)
    output["writer_lock"] = "acquired-read-only-control-inode"
    return output


def exhaust_bytes(path, *, deleted=False):
    with (path / "fill-bytes").open("wb", buffering=0) as stream:
        if deleted:
            (path / "fill-bytes").unlink()
        try:
            for index in range(4096):
                stream.write(b"b" * 4096)
                os.fsync(stream.fileno())
        except OSError as error:
            assert error.errno in {errno.EDQUOT, errno.ENOSPC}, error
            return {"errno": error.errno, "writes": index, "deleted_open": deleted}
    raise AssertionError("Byte allocation was not bounded")


def wal_failure():
    path = Path("/workspace/wal-failure.sqlite")
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE retained(value BLOB)")
        connection.execute("INSERT INTO retained VALUES ('original')")
        connection.commit()
        try:
            connection.execute("INSERT INTO retained VALUES (?)", (b"b" * (12 * 1024 * 1024),))
            connection.commit()
        except sqlite3.OperationalError as error:
            assert error.sqlite_errorcode & 0xFF in {sqlite3.SQLITE_FULL, sqlite3.SQLITE_IOERR}, (
                error
            )
            failure = {"code": error.sqlite_errorcode, "name": error.sqlite_errorname}
            connection.rollback()
        else:
            raise AssertionError("Quota failure was not observed")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM retained").fetchall() == [("original",)]
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    return {"storage_failure": failure, "original_row_retained": True}


def exhaust(path, *, inodes=False):
    try:
        for index in range(16384):
            with (path / f"fill-{index}").open("wb", buffering=0) as stream:
                stream.write(b"i" if inodes else b"b" * 4096)
                os.fsync(stream.fileno())
    except OSError as error:
        assert error.errno in {errno.EDQUOT, errno.ENOSPC}, error
        return {"errno": error.errno, "writes": index}
    raise AssertionError("Allocation was not bounded")


def main():
    mode = sys.argv[1]
    if mode == "hold":
        signal.signal(signal.SIGTERM, lambda *args: sys.exit(0))
        with HostedWriterLock(Path("/control/writer.lock")):
            print("writer-ready", flush=True)
            time.sleep(120)
        return
    if mode == "try_lock":
        try:
            with HostedWriterLock(Path("/control/writer.lock")):
                raise AssertionError("Second writer acquired the stable lock")
        except WorkspaceOperationInProgressError:
            print(json.dumps({"second_writer_denied": True}))
        return
    with HostedWriterLock(Path("/control/writer.lock")):
        result = workload(mode)
    print(json.dumps(result, sort_keys=True))


def workload(mode):
    if mode == "security":
        result = security()
    elif mode in {"bytes", "deleted"}:
        result = exhaust_bytes(Path(sys.argv[2]), deleted=mode == "deleted")
    elif mode == "inodes":
        result = exhaust(Path(sys.argv[2]), inodes=True)
    elif mode == "logs":
        for _ in range(768):
            print("bounded-log-" + "x" * 4096, flush=True)
        result = {"log_payload_bytes": 768 * 4096}
    elif mode == "wal":
        result = wal_failure()
    else:
        raise ValueError("Unknown qualification workload")
    return result


if __name__ == "__main__":
    main()

"""Synthetic capacity actor; only the opt-in private Docker fixture starts this.

The local application composition is exercised inside a network-none container.
It is not a production hosted-launch/admission bypass. Benchmark SQLite/files are
separate from the valid empty business workspace and are not H04 logical usage.
"""

from contextlib import closing
from http import HTTPStatus
from http.client import HTTPConnection
import errno
import json
import os
from pathlib import Path
import sqlite3
import statistics
import subprocess
import sys
from threading import Thread
import time

import uvicorn

from app.bootstrap.api import create_app
from app.modules.workspace.application.service import WorkspaceService
from app.platform.hosted_writer_lock import HostedWriterLock

SCRATCH = Path("/scratch")
DATABASE = Path("/workspace/benchmark.sqlite")
ROWS = 48000
CHUNK = 1024
MIB = 1024 * 1024
MAX_DURATION_SECONDS = 60
MAX_FAULT_MIB = 384
MAX_FAULT_FILES = 9000
MAX_CHILDREN = 80
MAX_DESCRIPTORS = 600
OOM_EXIT = -9


def request():
    start = time.monotonic()
    connection = HTTPConnection("127.0.0.1", 8000, timeout=10)
    try:
        connection.request("GET", "/api/properties", headers={"Origin": "http://127.0.0.1:8000"})
        response = connection.getresponse()
        body = response.read()
        if response.status != HTTPStatus.OK:
            raise RuntimeError(
                f"Synthetic property read returned {response.status}: {body[:200]!r}"
            )
        return (time.monotonic() - start) * 1000
    finally:
        connection.close()


def start_application():
    config = SCRATCH / "locator.json"
    config.write_text(json.dumps({"localWorkspacePath": "/workspace/current"}))
    WorkspaceService.from_local_config(config).initialize()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(config),
            host="127.0.0.1",
            port=8000,
            loop="asyncio",
            http="h11",
            log_level="error",
            access_log=False,
        )
    )
    Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            request()
            return
        except OSError, RuntimeError:
            time.sleep(0.1)
    raise RuntimeError("Synthetic local application did not become ready")


def load_database():
    connection = sqlite3.connect(DATABASE)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE IF NOT EXISTS payload(id INTEGER PRIMARY KEY, value BLOB)")
    if connection.execute("SELECT count(*) FROM payload").fetchone()[0] == 0:
        connection.executemany(
            "INSERT INTO payload(value) VALUES (?)", ((b"x" * CHUNK,) for _ in range(ROWS))
        )
        connection.commit()
    return connection


def sample(duration, loaded):
    connection = load_database() if loaded else None
    latencies = []
    peak_backup_bytes = 0

    def backup_progress(*args):
        nonlocal peak_backup_bytes
        sizes = sum(
            path.stat().st_blocks * 512
            for path in SCRATCH.glob("bounded-backup.sqlite*")
            if path.is_file()
        )
        peak_backup_bytes = max(peak_backup_bytes, sizes)

    start = time.monotonic()
    try:
        while time.monotonic() - start < duration:
            latencies.append(request())
            if connection is not None:
                connection.execute(
                    "UPDATE payload SET value=? WHERE id BETWEEN 1 AND 32", (os.urandom(CHUNK),)
                )
                connection.commit()
                try:
                    with closing(sqlite3.connect(SCRATCH / "bounded-backup.sqlite")) as target:
                        connection.backup(target, pages=128, progress=backup_progress)
                except sqlite3.Error as error:
                    print(
                        json.dumps(
                            dict(
                                backup_error=error.sqlite_errorname,
                                code=error.sqlite_errorcode,
                                peak_backup_bytes=peak_backup_bytes,
                            )
                        ),
                        flush=True,
                    )
                    raise
            time.sleep(0.05)
        sizes = {p.name: p.stat().st_size for p in DATABASE.parent.glob("benchmark.sqlite*")}
        return dict(
            requests=len(latencies),
            p95_ms=sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)],
            mean_ms=statistics.mean(latencies),
            elapsed_seconds=time.monotonic() - start,
            benchmark_files=sizes,
            backup_bytes=(SCRATCH / "bounded-backup.sqlite").stat().st_size if loaded else 0,
            peak_backup_allocated_bytes=peak_backup_bytes,
        )
    finally:
        if connection is not None:
            connection.close()


def fault():
    connection = load_database()
    connection.execute("CREATE TABLE IF NOT EXISTS retained(value TEXT)")
    connection.execute("INSERT INTO retained VALUES ('acknowledged')")
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    fill = Path("/workspace/quota-fill")
    observed = None
    try:
        with fill.open("wb", buffering=0) as output:
            for _ in range(MAX_FAULT_MIB):
                output.write(b"x" * MIB)
                os.fsync(output.fileno())
    except OSError as error:
        observed = error.errno
    try:
        assert observed in (errno.EDQUOT, errno.ENOSPC), observed
        try:
            connection.execute("INSERT INTO payload(value) VALUES (?)", (b"x" * MIB,))
            connection.commit()
        except sqlite3.DatabaseError:
            connection.rollback()
        else:
            raise AssertionError("Saturated workspace unexpectedly accepted a large transaction")
        assert connection.execute("SELECT value FROM retained").fetchall() == [("acknowledged",)]
    finally:
        connection.close()
        fill.unlink(missing_ok=True)
    with closing(sqlite3.connect(DATABASE)) as reopened:
        assert reopened.execute("SELECT value FROM retained").fetchall() == [("acknowledged",)]
    return dict(errno=observed, wal_failure_preserved_acknowledged_row=True)


def bounded_tree_fault(path, *, deleted=False):
    fill = path / "capacity-fault"
    observed = None
    try:
        with fill.open("wb", buffering=0) as output:
            if deleted:
                fill.unlink()
            try:
                for _ in range(MAX_FAULT_MIB):
                    output.write(b"x" * MIB)
                    os.fsync(output.fileno())
            except OSError as error:
                observed = error.errno
            assert observed in (errno.EDQUOT, errno.ENOSPC)
            if deleted:
                with (path / "still-full").open("wb", buffering=0) as another:
                    try:
                        another.write(b"x" * MIB)
                    except OSError as error:
                        assert error.errno in (errno.EDQUOT, errno.ENOSPC)
                    else:
                        raise AssertionError("Deleted-open file escaped its quota")
    finally:
        fill.unlink(missing_ok=True)
        (path / "still-full").unlink(missing_ok=True)
    return observed


def inode_fault():
    root = Path("/control/data/inode-fault")
    root.mkdir()
    count, observed = 0, None
    try:
        try:
            for index in range(MAX_FAULT_FILES):
                (root / str(index)).write_bytes(b"x")
                count += 1
        except OSError as error:
            observed = error.errno
        assert observed in (errno.EDQUOT, errno.ENOSPC)
    finally:
        for path in root.iterdir():
            path.unlink()
        root.rmdir()
    return dict(files_created=count, errno=observed)


def process_fault():
    children, observed = [], None
    try:
        try:
            for _ in range(MAX_CHILDREN):
                children.append(subprocess.Popen(["/bin/sleep", "30"]))
        except OSError as error:
            observed = error.errno
        assert observed == errno.EAGAIN
    finally:
        for child in children:
            child.terminate()
        for child in children:
            child.wait(timeout=5)
    return dict(children=len(children), errno=observed)


def descriptor_fault():
    descriptors, observed = [], None
    try:
        try:
            for _ in range(MAX_DESCRIPTORS):
                descriptors.append(os.open("/dev/null", os.O_RDONLY))
        except OSError as error:
            observed = error.errno
        assert observed == errno.EMFILE
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
    return dict(descriptors=len(descriptors), errno=observed)


def resource_faults():
    output = dict(workspace=fault())
    output["control_bytes"] = bounded_tree_fault(Path("/control/data"))
    output["scratch_bytes"] = bounded_tree_fault(SCRATCH)
    output["deleted_open"] = bounded_tree_fault(SCRATCH, deleted=True)
    output["inodes"] = inode_fault()
    output["pids"] = process_fault()
    output["descriptors"] = descriptor_fault()
    try:
        Path("/dev/shm/capacity-probe").write_bytes(b"x")
    except OSError as error:
        assert error.errno in (errno.EROFS, errno.EPERM, errno.EACCES)
        output["shared_memory_readonly"] = True
    else:
        raise AssertionError("Declared read-only shared memory accepted a write")
    code = (
        "import time\nx=[]\nfor _ in range(1024): x.append(bytearray(1024*1024)); time.sleep(.001)"
    )
    child = subprocess.run([sys.executable, "-B", "-c", code], check=False, timeout=60)
    assert child.returncode == OOM_EXIT, child.returncode
    output["bounded_memory_child_killed"] = True
    for _ in range(2048):
        print("synthetic-capacity-log " + "x" * 4096, flush=True)
    output["application_survived_faults_ms"] = request()
    return output


def run_command(value):
    if value["kind"] == "fault":
        return resource_faults()
    if value["kind"] in {"empty", "loaded"}:
        duration = value["duration_seconds"]
        if type(duration) is not int or not 1 <= duration <= MAX_DURATION_SECONDS:
            raise ValueError("Bounded fixture duration required")
        return sample(duration, value["kind"] == "loaded")
    raise ValueError("Unknown synthetic workload")


def publish(path, value):
    temporary = path.with_name(path.name + ".next")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def main():
    if (
        os.getuid() == 0
        or os.environ.get("EPM_RUN_CAPACITY_FIXTURE") != "1"
        or not Path("/.dockerenv").exists()
    ):
        raise RuntimeError("Only the explicitly isolated non-root Docker capacity fixture may run")
    with HostedWriterLock(Path("/control/writer.lock")):
        start_application()
        publish(SCRATCH / "ready.json", dict(uid=os.getuid(), gid=os.getgid()))
        previous = None
        while True:
            path = SCRATCH / "command.json"
            if path.exists():
                value = json.loads(path.read_text())
                if value["sequence"] != previous:
                    result = run_command(value)
                    publish(SCRATCH / f"result-{value['sequence']}.json", result)
                    previous = value["sequence"]
            time.sleep(0.1)


if __name__ == "__main__":
    main()

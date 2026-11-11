"""Bounded kernel/fixture observations; not the future H04 admission ledger adapter."""

import csv
import io
import os
from pathlib import Path
import subprocess
import time

from app.modules.host_agent.application.capacity import CapacitySnapshot, Commitment, Resources

MAX_QUOTA_BYTES = 2 * 1024 * 1024
MAX_PROJECTS = 4096
SHARED_UNITS = ("epm-gateway", "epm-egress", "epm-tunnel", "epm-host-guardian")


def quota_commitments(text, excluded):
    if len(text.encode()) > MAX_QUOTA_BYTES:
        raise ValueError("Kernel project report exceeds the bounded collector")
    rows = list(csv.DictReader(io.StringIO(text)))
    if len(rows) > MAX_PROJECTS:
        raise ValueError("Too many project records; capacity remains unknown")
    seen, result = set(), []
    for row in rows:
        identity = int(row["Project"].removeprefix("#"))
        if not 0 <= identity < 2**32 or identity in seen:
            raise ValueError("Invalid or duplicate project identity")
        seen.add(identity)
        if not identity or identity in excluded:
            continue
        used, hard = int(row["BlockUsed"]) * 1024, int(row["BlockHardLimit"]) * 1024
        files, ceiling = int(row["FileUsed"]), int(row["FileHardLimit"])
        if min(used, hard, files, ceiling) < 0:
            raise ValueError("Negative kernel quota observation")
        if not any((used, hard, files, ceiling)):
            continue
        # Kernel block accounting can transiently exceed a ceiling by a block.
        # Charge the larger observation; never silently discard retained limits.
        reserved = (
            Resources(data_bytes=max(used, hard), data_inodes=max(files, ceiling))
            if hard and ceiling
            else None
        )
        result.append(
            Commitment(
                identity=f"kernel-project-{identity}",
                state="retained",
                reserved=reserved,
                observed=Resources(data_bytes=used, data_inodes=files),
            )
        )
    if not excluded <= seen:
        raise ValueError("A current project is absent from kernel accounting")
    return result


def project_ledger(excluded):
    completed = subprocess.run(
        ["repquota", "-P", "-n", "-O", "csv", "/srv/epm/data"],
        env=os.environ | {"LC_ALL": "C"},
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return quota_commitments(completed.stdout, excluded)


def shared_services():
    result = {}
    for name in SHARED_UNITS:
        root = Path("/sys/fs/cgroup/system.slice") / (name + ".service")
        pids = int((root / "pids.current").read_text())
        if not pids:
            raise ValueError("A shared service is not populated; capacity is unknown")
        result[name] = dict(
            memory_current=int((root / "memory.current").read_text()),
            pids=pids,
            cpu=(root / "cpu.stat").read_text(),
        )
    return result


def resource_snapshot(profile, observation, commitments, revision):
    """Conservatively credit anonymous RAM and quota-attributed bytes/inodes only.

    CPU is reserved at configured limits, not discounted because a runtime is idle.
    Boot image/cache/log use not individually attributed stays in shared observation.
    """
    data, boot, memory = (observation[name] for name in ("data", "boot", "memory"))
    pid_limit = int(Path("/proc/sys/kernel/pid_max").read_text())
    used_pids = int(Path("/proc/loadavg").read_text().split()[3].split("/")[1])
    total = Resources(
        memory_bytes=memory["MemTotal"],
        cpu_millicores=len(os.sched_getaffinity(0)) * 1000,
        pids=pid_limit,
        data_bytes=data["total_bytes"],
        data_inodes=data["total_inodes"],
        boot_bytes=boot["total_bytes"],
        boot_inodes=boot["total_inodes"],
    )
    available = Resources(
        memory_bytes=memory["MemAvailable"],
        cpu_millicores=total.cpu_millicores,
        pids=max(0, pid_limit - used_pids),
        data_bytes=data["available_bytes"],
        data_inodes=data["available_inodes"],
        boot_bytes=boot["available_bytes"],
        boot_inodes=boot["available_inodes"],
    )
    attributed = Resources()
    for row in commitments:
        attributed = attributed.plus(row.observed)
    consumed = total.remaining(available)
    if not attributed.fits(consumed):
        raise ValueError("Attributable usage cannot be reconciled with physical consumption")
    return CapacitySnapshot(
        revision=revision,
        observed_at=time.time_ns() // 1000000,
        complete=True,
        profile_ref=profile.reference,
        profile_revision=profile.revision,
        total=total,
        available=available,
        shared_observed=consumed.remaining(attributed),
        commitments=tuple(commitments),
    )

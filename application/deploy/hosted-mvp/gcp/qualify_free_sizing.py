"""Closed H04.9 Free (50,000,000-byte) physical storage sizing validator and GCP runner.

Derives justified nonzero physical byte and inode ceilings for workspace, control, and
scratch strictly from native Linux/Docker/GCP ext4 prjquota evidence across all three
workload shapes plus independent byte and inode exhaustion proofs. Never accepts macOS
or synthetic/unmeasured constants, and leaves H05 backup/restore reservations deferred.
"""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import platform
import pwd
import shutil
import subprocess
import sys
from uuid import uuid4

from app.modules.host_agent.application.dispatch import Allocation, ResourceLimits, TreeLimits
from app.modules.host_agent.infrastructure.private_storage import PrivateStorage
from app.modules.host_agent.infrastructure.quota_targets import QuotaTargets

FREE_LOGICAL_BYTES = 50_000_000
SHA256_HEX_LEN = 64
MIN_CLI_ARGS = 4
REQUIRED_WORKLOADS = ("database_heavy", "retained_file_heavy", "many_small_files_history")
REQUIRED_EXHAUSTION = ("byte_exhaustion", "inode_exhaustion")
TREE_ROLES = ("workspace", "control", "scratch")
LINUX_QUOTA_ERRORS = (122, 28)  # EDQUOT, ENOSPC
REQUIRED_MOUNT_OPTIONS = frozenset({"prjquota", "nodev", "nosuid", "noexec"})
MIB = 1024 * 1024
MIN_MARGIN_FACTOR = 1.25
MIN_HEADROOM_BYTES = {
    "workspace": 32 * MIB,
    "control": 16 * MIB,
    "scratch": 32 * MIB,
}
MIN_HEADROOM_INODES = {
    "workspace": 1024,
    "control": 512,
    "scratch": 512,
}
DOCUMENT_FIELDS = {
    "version",
    "slice",
    "logical_free_bytes",
    "measurement_sha256",
    "source_sha256",
    "margin_factor",
    "measured_peaks",
    "derived_trees",
    "h05_backup_restore_reserve",
    "restore_readiness",
    "admission_enabled",
}


def _round_up(value: int, step: int) -> int:
    return int(math.ceil(value / step) * step)


def _validate_workload_entry(
    shape: str,
    entry: object,
    peaks: dict[str, dict[str, int]],
) -> None:
    if not isinstance(entry, dict):
        raise ValueError(f"Missing required workload shape: {shape}")
    logical_used = entry.get("logical_used_bytes")
    if not isinstance(logical_used, int) or logical_used <= 0:
        raise ValueError(f"Workload {shape} recorded no positive logical usage")
    if logical_used > FREE_LOGICAL_BYTES:
        raise ValueError(f"Workload {shape} exceeded logical 50,000,000-byte Free ceiling")
    reached_envelope = logical_used >= int(FREE_LOGICAL_BYTES * 0.80) or (
        entry.get("logical_507_triggered") is True
    )
    if not reached_envelope:
        raise ValueError(f"Workload {shape} did not approach 50 MB envelope or trigger 507")
    trees = entry.get("trees")
    if not isinstance(trees, dict):
        raise ValueError(f"Workload {shape} missing per-tree measurements")
    for role in TREE_ROLES:
        tree = trees.get(role)
        if not isinstance(tree, dict):
            raise ValueError(f"Workload {shape} missing tree measurement for {role}")
        p_bytes = tree.get("peak_bytes")
        p_inodes = tree.get("peak_inodes")
        if not isinstance(p_bytes, int) or p_bytes <= 0:
            raise ValueError(f"Workload {shape}/{role} peak_bytes must be positive")
        if not isinstance(p_inodes, int) or p_inodes <= 0:
            raise ValueError(f"Workload {shape}/{role} peak_inodes must be positive")
        peaks[role]["peak_bytes"] = max(peaks[role]["peak_bytes"], p_bytes)
        peaks[role]["peak_inodes"] = max(peaks[role]["peak_inodes"], p_inodes)


def _validate_exhaustion_entry(kind: str, fault: object) -> None:
    if not isinstance(fault, dict):
        raise ValueError(f"Missing required exhaustion proof: {kind}")
    if fault.get("errno") not in LINUX_QUOTA_ERRORS:
        raise ValueError(f"{kind} did not observe Linux EDQUOT/ENOSPC")
    if fault.get("sqlite_integrity_ok") is not True:
        raise ValueError(f"{kind} failed SQLite integrity verification")
    if fault.get("acknowledged_rows_preserved") is not True:
        raise ValueError(f"{kind} did not preserve acknowledged rows")
    if fault.get("reservations_reconciled") is not True:
        raise ValueError(f"{kind} did not reconcile usage_reservations")
    if fault.get("http_507_observed") is not True:
        raise ValueError(f"{kind} did not verify HTTP 507 storage rejection")


def validate_free_sizing_evidence(record: dict[str, object]) -> dict[str, dict[str, int]]:
    """Validate raw native Linux/Docker/GCP H04.9 evidence and return per-tree peaks."""
    if record.get("platform") != "Linux":
        raise ValueError("H04.9 sizing qualification must run on native Linux (never macOS)")
    if record.get("prjquota_verified") is not True:
        raise ValueError("ext4 prjquota verification is required")
    mount_options = set(record.get("mount_options") or [])
    if not REQUIRED_MOUNT_OPTIONS <= mount_options:
        raise ValueError(
            f"Required mount options missing: {REQUIRED_MOUNT_OPTIONS - mount_options}"
        )
    source_sha = record.get("source_sha256")
    if not isinstance(source_sha, str) or len(source_sha) != SHA256_HEX_LEN:
        raise ValueError("source_sha256 must be a 64-character hex digest")

    workloads = record.get("workloads")
    if not isinstance(workloads, dict):
        raise ValueError("workloads map is required")
    peaks: dict[str, dict[str, int]] = {
        role: {"peak_bytes": 0, "peak_inodes": 0} for role in TREE_ROLES
    }
    for shape in REQUIRED_WORKLOADS:
        _validate_workload_entry(shape, workloads.get(shape), peaks)

    exhaustion = record.get("exhaustion")
    if not isinstance(exhaustion, dict):
        raise ValueError("exhaustion proofs are required")
    for kind in REQUIRED_EXHAUSTION:
        _validate_exhaustion_entry(kind, exhaustion.get(kind))

    return peaks


def derive_free_sizing_budget(
    evidence_bytes: bytes,
    *,
    margin_factor: float = 1.35,
) -> dict[str, object]:
    """Derive closed Free physical tree ceilings with justified nonzero margins."""
    if not math.isfinite(margin_factor) or margin_factor < MIN_MARGIN_FACTOR:
        raise ValueError(f"margin_factor must be >= {MIN_MARGIN_FACTOR}")
    record = json.loads(evidence_bytes)
    peaks = validate_free_sizing_evidence(record)

    derived: dict[str, TreeLimits] = {}
    for role in TREE_ROLES:
        byte_ceiling = _round_up(
            int(math.ceil(peaks[role]["peak_bytes"] * margin_factor)) + MIN_HEADROOM_BYTES[role],
            MIB,
        )
        inode_ceiling = _round_up(
            int(math.ceil(peaks[role]["peak_inodes"] * margin_factor)) + MIN_HEADROOM_INODES[role],
            256,
        )
        derived[role] = TreeLimits(byte_ceiling=byte_ceiling, inode_ceiling=inode_ceiling)

    limits = ResourceLimits(
        workspace=derived["workspace"],
        control=derived["control"],
        scratch=derived["scratch"],
    )
    return {
        "version": 1,
        "slice": "H04.9",
        "logical_free_bytes": FREE_LOGICAL_BYTES,
        "measurement_sha256": sha256(evidence_bytes).hexdigest(),
        "source_sha256": record["source_sha256"],
        "margin_factor": margin_factor,
        "measured_peaks": peaks,
        "derived_trees": limits.model_dump(),
        "h05_backup_restore_reserve": "deferred_to_H05",
        "restore_readiness": "unavailable_pending_H05",
        "admission_enabled": False,
    }


def validate_free_sizing_document(
    document: dict[str, object],
    evidence_bytes: bytes,
    *,
    expected_source_sha256: str,
) -> ResourceLimits:
    """Verify a closed H04.9 sizing document against its bound native evidence bytes."""
    if set(document) != DOCUMENT_FIELDS:
        raise ValueError("Unexpected or missing fields in H04.9 sizing document")
    if (
        document["version"] != 1
        or document["slice"] != "H04.9"
        or document["logical_free_bytes"] != FREE_LOGICAL_BYTES
        or document["h05_backup_restore_reserve"] != "deferred_to_H05"
        or document["restore_readiness"] != "unavailable_pending_H05"
        or document["admission_enabled"] is not False
    ):
        raise ValueError("Permissive or malformed H04.9 sizing document")
    if document["measurement_sha256"] != sha256(evidence_bytes).hexdigest():
        raise ValueError("Evidence measurement_sha256 mismatch")
    if document["source_sha256"] != expected_source_sha256:
        raise ValueError("Evidence source_sha256 mismatch")

    peaks = validate_free_sizing_evidence(json.loads(evidence_bytes))
    limits = ResourceLimits.model_validate(document["derived_trees"])
    for role in TREE_ROLES:
        tree = getattr(limits, role)
        if tree.byte_ceiling <= peaks[role]["peak_bytes"]:
            raise ValueError(f"{role} byte_ceiling has no positive margin above measured peak")
        if tree.inode_ceiling <= peaks[role]["peak_inodes"]:
            raise ValueError(f"{role} inode_ceiling has no positive margin above measured peak")
    return limits


def _reserve_projects(data_root: Path, count: int) -> int:
    with (data_root / "qualification-projects").open("r+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        base = int(handle.read())
        handle.seek(0)
        handle.truncate()
        handle.write(str(base + count))
        handle.flush()
        os.fsync(handle.fileno())
        return base


def _build_h04_actor_image(root: Path, *, base_image: str, source_root: Path) -> str:
    context = root / "image"
    context.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("free_sizing_actor.py"), context / "actor.py")
    shutil.copytree(source_root / "apps" / "server", context / "server")
    shutil.copytree(source_root / "database", context / "database")
    (context / "Dockerfile").write_text(
        f"FROM {base_image}\n"
        "COPY server /opt/epm/h04/apps/server\n"
        "COPY database /opt/epm/h04/database\n"
        "COPY actor.py /opt/epm/h04/free_sizing_actor.py\n"
        "ENV PYTHONPATH=/opt/epm/h04/apps/server\n"
        "ENV EPM_APPLICATION_ROOT=/opt/epm/h04\n"
        "ENV TMPDIR=/scratch\n"
        "ENV SQLITE_TMPDIR=/scratch\n"
        "HEALTHCHECK NONE\n"
        'ENTRYPOINT ["/opt/epm/venv/bin/python", "-B", "/opt/epm/h04/free_sizing_actor.py"]\n'
        "CMD []\n",
        encoding="utf-8",
    )
    tag = f"epm-h04-sizing:{root.name}"
    subprocess.run(["docker", "build", "--network=none", "-t", tag, str(context)], check=True)
    inspected = json.loads(
        subprocess.run(
            ["docker", "image", "inspect", tag], check=True, capture_output=True, text=True
        ).stdout
    )
    return str(inspected[0]["Id"]).removeprefix("sha256:")


def _mode_limits(mode: str) -> ResourceLimits:
    if mode == "byte_exhaustion":
        return ResourceLimits(
            workspace=TreeLimits(byte_ceiling=16 * MIB, inode_ceiling=4096),
            control=TreeLimits(byte_ceiling=32 * MIB, inode_ceiling=2048),
            scratch=TreeLimits(byte_ceiling=32 * MIB, inode_ceiling=2048),
        )
    if mode == "inode_exhaustion":
        return ResourceLimits(
            workspace=TreeLimits(byte_ceiling=128 * MIB, inode_ceiling=256),
            control=TreeLimits(byte_ceiling=32 * MIB, inode_ceiling=2048),
            scratch=TreeLimits(byte_ceiling=32 * MIB, inode_ceiling=2048),
        )
    return ResourceLimits(
        workspace=TreeLimits(byte_ceiling=256 * MIB, inode_ceiling=8192),
        control=TreeLimits(byte_ceiling=64 * MIB, inode_ceiling=4096),
        scratch=TreeLimits(byte_ceiling=128 * MIB, inode_ceiling=4096),
    )


def _cleanup_gcp_qualification(
    created_users: list[str], run_root: Path, image_tag: str, *, image_built: bool
) -> None:
    for user in created_users:
        subprocess.run(["userdel", user], check=False)
    if image_built:
        subprocess.run(["docker", "rmi", "-f", image_tag], check=False, capture_output=True)
    shutil.rmtree(run_root, ignore_errors=True)


@dataclass(frozen=True)
class _GcpSizingContext:
    storage: PrivateStorage
    run_root: Path
    image_tag: str
    actor_image_id: str
    project_base: int
    created_users: list[str]


def _run_gcp_sizing_actor(ctx: _GcpSizingContext, *, mode: str, index: int) -> dict[str, object]:
    user = f"epm-h4s-{ctx.run_root.name[-6:]}{index}"
    subprocess.run(
        ["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", user],
        check=True,
    )
    ctx.created_users.append(user)
    owner = pwd.getpwnam(user)
    allocation = Allocation(
        binding_id=str(uuid4()),
        resource_generation=1,
        host_uid=owner.pw_uid,
        host_gid=owner.pw_gid,
        workspace_project=ctx.project_base + 3 * index,
        control_project=ctx.project_base + 3 * index + 1,
        scratch_project=ctx.project_base + 3 * index + 2,
        filesystem_identity="isolated-h04-sizing-fixture",
        image_digest=ctx.actor_image_id,
        limits=_mode_limits(mode),
    )
    ctx.storage.prepare(allocation)
    project_dirs = {
        role: ctx.storage.projects(allocation)[idx].binding.directory
        for idx, role in enumerate(TREE_ROLES)
    }
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--user",
        f"{owner.pw_uid}:{owner.pw_gid}",
        "-v",
        f"{project_dirs['workspace']}:/workspace:rw",
        "-v",
        f"{project_dirs['control']}:/control:rw",
        "-v",
        f"{project_dirs['scratch']}:/scratch:rw",
        ctx.image_tag,
        mode,
        "--target-bytes",
        str(FREE_LOGICAL_BYTES),
    ]
    completed = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=600)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Actor {mode} failed (rc={completed.returncode}): {completed.stderr.strip()}"
        )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def run_gcp_qualification(output_dir: Path, *, image: str, source_sha256: str) -> dict[str, object]:
    """Opt-in native Linux/Docker/GCP H04.9 qualification runner with real ext4 prjquota."""
    if platform.system() != "Linux":
        raise RuntimeError("H04.9 native sizing qualification requires Linux (never macOS)")
    if os.geteuid() != 0 or os.environ.get("EPM_RUN_H04_SIZING_QUALIFICATION") != "1":
        raise RuntimeError(
            "Explicit root GCP opt-in required: set EPM_RUN_H04_SIZING_QUALIFICATION=1"
        )
    data_root = Path("/srv/epm/data")
    bootstrap = json.loads(Path("/etc/epm/bootstrap/data.json").read_text(encoding="utf-8"))
    mounted = json.loads(
        subprocess.run(
            ["findmnt", "-J", "-M", str(data_root), "-o", "UUID,OPTIONS"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
    )["filesystems"][0]
    mount_options = sorted(mounted["options"].split(","))
    if bootstrap["phase"] != "ready" or mounted["uuid"] != bootstrap["uuid"]:
        raise RuntimeError("Protected retained data filesystem UUID/phase mismatch")
    if not REQUIRED_MOUNT_OPTIONS <= set(mount_options):
        raise RuntimeError(f"/srv/epm/data missing required mount options: {mount_options}")

    run_root = data_root / "qualification" / f"h04-sizing-{uuid4().hex[:10]}"
    image_tag = f"epm-h04-sizing:{run_root.name}"
    created_users: list[str] = []
    image_built = False
    try:
        run_root.mkdir(mode=0o711, parents=True)
        for name in TREE_ROLES:
            (run_root / name).mkdir(mode=0o711)
        targets = QuotaTargets(
            data_root,
            "isolated-h04-sizing-fixture",
            bootstrap["uuid"],
            *(run_root / name for name in TREE_ROLES),
        )
        storage = PrivateStorage(targets)
        source_root = Path(__file__).resolve().parents[3]
        actor_image_id = _build_h04_actor_image(run_root, base_image=image, source_root=source_root)
        image_built = True
        modes = (*REQUIRED_WORKLOADS, *REQUIRED_EXHAUSTION)
        project_base = _reserve_projects(data_root, len(modes) * 3)
        workloads: dict[str, object] = {}
        exhaustion: dict[str, object] = {}
        sizing_ctx = _GcpSizingContext(
            storage=storage,
            run_root=run_root,
            image_tag=image_tag,
            actor_image_id=actor_image_id,
            project_base=project_base,
            created_users=created_users,
        )
        for index, mode in enumerate(modes):
            parsed = _run_gcp_sizing_actor(sizing_ctx, mode=mode, index=index)
            if mode in REQUIRED_WORKLOADS:
                workloads[mode] = parsed
            else:
                exhaustion[mode] = parsed
    finally:
        _cleanup_gcp_qualification(created_users, run_root, image_tag, image_built=image_built)

    evidence = {
        "platform": platform.system(),
        "kernel": platform.release(),
        "machine": platform.machine(),
        "filesystem_uuid": bootstrap["uuid"],
        "prjquota_verified": True,
        "mount_options": mount_options,
        "source_sha256": source_sha256,
        "base_image": image,
        "actor_image_id": actor_image_id,
        "workloads": workloads,
        "exhaustion": exhaustion,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_bytes = json.dumps(evidence, indent=2, sort_keys=True).encode("utf-8")
    (output_dir / "HOSTED_MVP_H04_9_EVIDENCE.json").write_bytes(evidence_bytes)
    document = derive_free_sizing_budget(evidence_bytes)
    validate_free_sizing_document(document, evidence_bytes, expected_source_sha256=source_sha256)
    (output_dir / "HOSTED_MVP_H04_9_FREE_SIZING.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return document


if __name__ == "__main__":
    if len(sys.argv) < MIN_CLI_ARGS:
        print(
            "Usage: qualify_free_sizing.py <output_dir> <operator_image_digest> <source_sha256>",
            file=sys.stderr,
        )
        raise SystemExit(2)
    result = run_gcp_qualification(Path(sys.argv[1]), image=sys.argv[2], source_sha256=sys.argv[3])
    print(json.dumps(result, indent=2, sort_keys=True))

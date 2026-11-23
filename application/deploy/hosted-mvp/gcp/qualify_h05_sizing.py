"""Closed H05.9 backup/restore physical reserve sizing validator and native GCP runner.

Derives justified nonzero physical byte and inode ceilings for workspace, control, and
scratch — including H05 backup staging (`scratch`), concurrent restore staging + 1 retained
prior/forensic incarnation (`workspace`), and 7-point `recovery.sqlite` + audit churn
(`control`) — strictly from native Linux/Docker/GCP ext4 prjquota evidence. Never accepts
macOS or synthetic/unmeasured constants.
"""

from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

from app.modules.host_agent.application.dispatch import ResourceLimits, TreeLimits

FREE_LOGICAL_BYTES = 50_000_000
SHA256_HEX_LEN = 64
MIN_CAPTURES = 7
CLI_ARGC = 4
REQUIRED_WORKLOADS = ("database_heavy", "retained_file_heavy", "many_small_files_history")
REQUIRED_EXHAUSTION = (
    "backup_byte_exhaustion",
    "backup_inode_exhaustion",
    "restore_byte_exhaustion",
    "restore_inode_exhaustion",
)
TREE_ROLES = ("workspace", "control", "scratch")
LINUX_QUOTA_ERRORS = (122, 28)  # EDQUOT, ENOSPC
REQUIRED_MOUNT_OPTIONS = frozenset({"prjquota", "nodev", "nosuid", "noexec"})
MIB = 1024 * 1024
MIN_MARGIN_FACTOR = 1.25
MIN_HEADROOM_BYTES = {
    "workspace": 64 * MIB,
    "control": 16 * MIB,
    "scratch": 48 * MIB,
}
MIN_HEADROOM_INODES = {
    "workspace": 2048,
    "control": 512,
    "scratch": 1024,
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


def _validate_tree_peaks(
    shape: str,
    trees: object,
    peaks: dict[str, dict[str, int]],
) -> None:
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
    if logical_used < int(FREE_LOGICAL_BYTES * 0.80):
        raise ValueError(f"Workload {shape} did not approach 50 MB logical envelope")
    captures = entry.get("captures_completed")
    if not isinstance(captures, int) or captures < MIN_CAPTURES:
        raise ValueError(f"Workload {shape} must exercise at least 7 verified captures")
    if entry.get("restore_state") != "succeeded":
        raise ValueError(f"Workload {shape} did not complete concurrent restore staging")
    if entry.get("startup_mode_after_restore") != "normal":
        raise ValueError(f"Workload {shape} did not validate normal mode after restore")
    _validate_tree_peaks(shape, entry.get("trees"), peaks)


def _validate_exhaustion_entry(kind: str, fault: object) -> None:
    if not isinstance(fault, dict):
        raise ValueError(f"Missing required exhaustion proof: {kind}")
    if fault.get("errno") not in LINUX_QUOTA_ERRORS:
        raise ValueError(f"{kind} did not observe Linux EDQUOT/ENOSPC")
    if fault.get("sqlite_integrity_ok") is not True:
        raise ValueError(f"{kind} failed SQLite integrity verification")
    if fault.get("original_tree_preserved") is not True:
        raise ValueError(f"{kind} did not preserve original business tree")
    if fault.get("no_empty_init") is not True:
        raise ValueError(f"{kind} did not prove zero silent empty initialization")
    if fault.get("honest_status_recorded") is not True:
        raise ValueError(f"{kind} did not verify honest recovery status")


def validate_h05_sizing_evidence(record: dict[str, object]) -> dict[str, dict[str, int]]:
    """Validate raw native Linux/Docker/GCP H05.9 evidence and return per-tree peaks."""
    if record.get("platform") != "Linux":
        raise ValueError("H05.9 sizing qualification must run on native Linux (never macOS)")
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


def derive_h05_sizing_budget(
    evidence_bytes: bytes,
    *,
    h04_baseline_trees: dict[str, dict[str, int]] | None = None,
    margin_factor: float = 1.35,
) -> dict[str, object]:
    """Derive pinned H05.9 physical tree ceilings and backup/restore reserve deltas."""
    if not math.isfinite(margin_factor) or margin_factor < MIN_MARGIN_FACTOR:
        raise ValueError(f"margin_factor must be >= {MIN_MARGIN_FACTOR}")
    record = json.loads(evidence_bytes)
    peaks = validate_h05_sizing_evidence(record)

    derived: dict[str, TreeLimits] = {}
    reserve: dict[str, dict[str, int]] = {}
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
        base_bytes = (
            int(h04_baseline_trees[role]["byte_ceiling"])
            if h04_baseline_trees and role in h04_baseline_trees
            else 0
        )
        base_inodes = (
            int(h04_baseline_trees[role]["inode_ceiling"])
            if h04_baseline_trees and role in h04_baseline_trees
            else 0
        )
        reserve[role] = {
            "byte_ceiling": byte_ceiling,
            "inode_ceiling": inode_ceiling,
            "backup_restore_delta_bytes": max(0, byte_ceiling - base_bytes),
            "backup_restore_delta_inodes": max(0, inode_ceiling - base_inodes),
        }

    limits = ResourceLimits(
        workspace=derived["workspace"],
        control=derived["control"],
        scratch=derived["scratch"],
    )
    return {
        "version": 1,
        "slice": "H05.9",
        "logical_free_bytes": FREE_LOGICAL_BYTES,
        "measurement_sha256": sha256(evidence_bytes).hexdigest(),
        "source_sha256": record["source_sha256"],
        "margin_factor": margin_factor,
        "measured_peaks": peaks,
        "derived_trees": limits.model_dump(),
        "h05_backup_restore_reserve": reserve,
        "restore_readiness": "qualified",
        "admission_enabled": True,
    }


def validate_h05_sizing_document(
    document: dict[str, object],
    evidence_bytes: bytes,
    *,
    expected_source_sha256: str,
) -> ResourceLimits:
    """Verify a closed H05.9 sizing document against its bound native Linux evidence bytes."""
    if set(document) != DOCUMENT_FIELDS:
        raise ValueError("Unexpected or missing fields in H05.9 sizing document")
    if (
        document["version"] != 1
        or document["slice"] != "H05.9"
        or document["logical_free_bytes"] != FREE_LOGICAL_BYTES
        or document["restore_readiness"] != "qualified"
        or document["admission_enabled"] is not True
    ):
        raise ValueError("Malformed H05.9 sizing document")
    reserve = document["h05_backup_restore_reserve"]
    if not isinstance(reserve, dict) or set(reserve) != set(TREE_ROLES):
        raise ValueError("h05_backup_restore_reserve must contain pinned per-tree ceilings")
    if document["measurement_sha256"] != sha256(evidence_bytes).hexdigest():
        raise ValueError("Evidence measurement_sha256 mismatch")
    if document["source_sha256"] != expected_source_sha256:
        raise ValueError("Evidence source_sha256 mismatch")

    peaks = validate_h05_sizing_evidence(json.loads(evidence_bytes))
    limits = ResourceLimits.model_validate(document["derived_trees"])
    for role in TREE_ROLES:
        tree = getattr(limits, role)
        if tree.byte_ceiling <= peaks[role]["peak_bytes"]:
            raise ValueError(f"{role} byte_ceiling has no positive margin above measured peak")
        if tree.inode_ceiling <= peaks[role]["peak_inodes"]:
            raise ValueError(f"{role} inode_ceiling has no positive margin above measured peak")
    return limits


def build_h05_actor_image(root: Path, *, base_image: str, source_root: Path) -> str:
    """Build an offline Docker actor image for native GCP H05.9 qualification."""
    context = root / "image"
    context.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("h05_sizing_actor.py"), context / "actor.py")
    shutil.copytree(source_root / "apps" / "server", context / "server")
    shutil.copytree(source_root / "database", context / "database")
    (context / "Dockerfile").write_text(
        f"FROM {base_image}\n"
        "COPY server /opt/epm/h05/apps/server\n"
        "COPY database /opt/epm/h05/database\n"
        "COPY actor.py /opt/epm/h05/h05_sizing_actor.py\n"
        "ENV PYTHONPATH=/opt/epm/h05/apps/server\n"
        "ENV EPM_APPLICATION_ROOT=/opt/epm/h05\n"
        "ENV TMPDIR=/scratch\n"
        "ENV SQLITE_TMPDIR=/scratch\n"
        "HEALTHCHECK NONE\n"
        'ENTRYPOINT ["/opt/epm/venv/bin/python", "-B", "/opt/epm/h05/h05_sizing_actor.py"]\n'
        "CMD []\n",
        encoding="utf-8",
    )
    tag = f"epm-h05-sizing:{root.name}"
    subprocess.run(["docker", "build", "--network=none", "-t", tag, str(context)], check=True)
    return tag


def main() -> None:
    if len(sys.argv) != CLI_ARGC:
        raise SystemExit(
            "Usage: qualify_h05_sizing.py <evidence.json> <h04-baseline.json> <output.json>"
        )
    evidence_path = Path(sys.argv[1])
    baseline_path = Path(sys.argv[2])
    output_path = Path(sys.argv[3])
    evidence_bytes = evidence_path.read_bytes()
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    doc = derive_h05_sizing_budget(
        evidence_bytes,
        h04_baseline_trees=baseline.get("derived_trees"),
    )
    validate_h05_sizing_document(
        doc, evidence_bytes, expected_source_sha256=str(doc["source_sha256"])
    )
    output_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

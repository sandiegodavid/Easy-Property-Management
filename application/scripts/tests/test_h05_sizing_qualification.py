"""H05.9 backup/restore physical reserve sizing actor and closed validator tests."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import runpy

import pytest

GCP_DIR = Path(__file__).resolve().parents[2] / "deploy" / "hosted-mvp" / "gcp"
H04_BASELINE = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "hosting"
    / "qualification"
    / "reports"
    / "HOSTED_MVP_H04_9_FREE_SIZING.json"
)
SOURCE_SHA = "b" * 64
MIB = 1024 * 1024
LINUX_EDQUOT = 122
LINUX_ENOSPC = 28
REQUIRED_CAPTURES = 7
PEAK_WS_INODES = 6200


def _valid_h05_linux_evidence() -> dict[str, object]:
    return {
        "platform": "Linux",
        "kernel": "7.0.0-1017-gcp",
        "prjquota_verified": True,
        "mount_options": ["rw", "nodev", "nosuid", "noexec", "prjquota"],
        "source_sha256": SOURCE_SHA,
        "workloads": {
            "database_heavy": {
                "shape": "database_heavy",
                "logical_used_bytes": 46_000_000,
                "captures_completed": 7,
                "restore_state": "succeeded",
                "startup_mode_after_restore": "normal",
                "trees": {
                    "workspace": {"peak_bytes": 156 * MIB, "peak_inodes": 48},
                    "control": {"peak_bytes": 8 * MIB, "peak_inodes": 24},
                    "scratch": {"peak_bytes": 72 * MIB, "peak_inodes": 18},
                },
            },
            "retained_file_heavy": {
                "shape": "retained_file_heavy",
                "logical_used_bytes": 48_000_000,
                "captures_completed": 7,
                "restore_state": "succeeded",
                "startup_mode_after_restore": "normal",
                "trees": {
                    "workspace": {"peak_bytes": 148 * MIB, "peak_inodes": 140},
                    "control": {"peak_bytes": 6 * MIB, "peak_inodes": 20},
                    "scratch": {"peak_bytes": 16 * MIB, "peak_inodes": 14},
                },
            },
            "many_small_files_history": {
                "shape": "many_small_files_history",
                "logical_used_bytes": 42_000_000,
                "captures_completed": 7,
                "restore_state": "succeeded",
                "startup_mode_after_restore": "normal",
                "trees": {
                    "workspace": {"peak_bytes": 132 * MIB, "peak_inodes": 6200},
                    "control": {"peak_bytes": 10 * MIB, "peak_inodes": 32},
                    "scratch": {"peak_bytes": 12 * MIB, "peak_inodes": 22},
                },
            },
        },
        "exhaustion": {
            "backup_byte_exhaustion": {
                "kind": "backup_byte_exhaustion",
                "errno": LINUX_EDQUOT,
                "sqlite_integrity_ok": True,
                "original_tree_preserved": True,
                "no_empty_init": True,
                "honest_status_recorded": True,
            },
            "backup_inode_exhaustion": {
                "kind": "backup_inode_exhaustion",
                "errno": LINUX_ENOSPC,
                "sqlite_integrity_ok": True,
                "original_tree_preserved": True,
                "no_empty_init": True,
                "honest_status_recorded": True,
            },
            "restore_byte_exhaustion": {
                "kind": "restore_byte_exhaustion",
                "errno": LINUX_EDQUOT,
                "sqlite_integrity_ok": True,
                "original_tree_preserved": True,
                "no_empty_init": True,
                "honest_status_recorded": True,
            },
            "restore_inode_exhaustion": {
                "kind": "restore_inode_exhaustion",
                "errno": LINUX_ENOSPC,
                "sqlite_integrity_ok": True,
                "original_tree_preserved": True,
                "no_empty_init": True,
                "honest_status_recorded": True,
            },
        },
    }


@pytest.mark.parametrize(
    "shape",
    ("database_heavy", "retained_file_heavy", "many_small_files_history"),
)
def test_h05_actor_measures_7_captures_and_concurrent_restore(tmp_path: Path, shape: str):
    actor = runpy.run_path(str(GCP_DIR / "h05_sizing_actor.py"))
    dirs = actor["SizingDirs"](
        workspace=tmp_path / shape / "workspace",
        control=tmp_path / shape / "control",
        scratch=tmp_path / shape / "scratch",
        r2=tmp_path / shape / "r2",
    )
    result = actor["run_h05_workload"](
        shape,
        dirs,
        target_bytes=120_000,
        captures=REQUIRED_CAPTURES,
    )
    assert result["shape"] == shape
    assert result["captures_completed"] == REQUIRED_CAPTURES
    assert result["restore_state"] == "succeeded"
    assert result["startup_mode_after_restore"] == "normal"
    for role in ("workspace", "control", "scratch"):
        assert result["trees"][role]["peak_bytes"] > 0
        assert result["trees"][role]["peak_inodes"] > 0
    # Prior incarnation-1 and restored incarnation-2 both exist concurrently on workspace.
    assert (tmp_path / shape / "workspace" / "incarnation-1").is_dir()
    assert (tmp_path / shape / "workspace" / "incarnation-2").is_dir()


@pytest.mark.parametrize(
    ("kind", "sim_errno"),
    (
        ("backup_byte_exhaustion", LINUX_EDQUOT),
        ("backup_inode_exhaustion", LINUX_ENOSPC),
        ("restore_byte_exhaustion", LINUX_EDQUOT),
        ("restore_inode_exhaustion", LINUX_ENOSPC),
    ),
)
def test_h05_actor_exhaustion_proof_preserves_original_tree(
    tmp_path: Path, kind: str, sim_errno: int
):
    actor = runpy.run_path(str(GCP_DIR / "h05_sizing_actor.py"))
    dirs = actor["SizingDirs"](
        workspace=tmp_path / kind / "workspace",
        control=tmp_path / kind / "control",
        scratch=tmp_path / kind / "scratch",
        r2=tmp_path / kind / "r2",
    )
    result = actor["run_exhaustion_proof"](
        kind,
        dirs,
        simulated_errno=sim_errno,
    )
    assert result["errno"] == sim_errno
    assert result["sqlite_integrity_ok"] is True
    assert result["original_tree_preserved"] is True
    assert result["no_empty_init"] is True
    assert result["honest_status_recorded"] is True


def test_h05_validator_derives_pinned_reserve_and_rejects_invalid_evidence():
    mod = runpy.run_path(str(GCP_DIR / "qualify_h05_sizing.py"))
    baseline = json.loads(H04_BASELINE.read_text(encoding="utf-8"))
    evidence = _valid_h05_linux_evidence()
    raw_bytes = json.dumps(evidence, sort_keys=True).encode()

    doc = mod["derive_h05_sizing_budget"](
        raw_bytes,
        h04_baseline_trees=baseline["derived_trees"],
    )
    assert doc["slice"] == "H05.9"
    assert doc["restore_readiness"] == "qualified"
    assert doc["admission_enabled"] is True
    assert isinstance(doc["h05_backup_restore_reserve"], dict)
    assert doc["h05_backup_restore_reserve"]["workspace"]["backup_restore_delta_bytes"] > 0
    assert doc["h05_backup_restore_reserve"]["scratch"]["backup_restore_delta_bytes"] > 0

    limits = mod["validate_h05_sizing_document"](doc, raw_bytes, expected_source_sha256=SOURCE_SHA)
    assert limits.workspace.byte_ceiling > 156 * MIB
    assert limits.workspace.inode_ceiling > PEAK_WS_INODES
    assert limits.scratch.byte_ceiling > 72 * MIB

    # Reject macOS / non-Linux evidence.
    bad_platform = deepcopy(evidence)
    bad_platform["platform"] = "Darwin"
    with pytest.raises(ValueError, match="native Linux"):
        mod["validate_h05_sizing_evidence"](bad_platform)

    # Reject missing prjquota mount option.
    bad_mount = deepcopy(evidence)
    bad_mount["mount_options"] = ["rw", "nodev", "nosuid"]
    with pytest.raises(ValueError, match="mount options"):
        mod["validate_h05_sizing_evidence"](bad_mount)

    # Reject < 7 captures.
    bad_caps = deepcopy(evidence)
    bad_caps["workloads"]["database_heavy"]["captures_completed"] = 3
    with pytest.raises(ValueError, match="7 verified captures"):
        mod["validate_h05_sizing_evidence"](bad_caps)

    # Reject missing exhaustion proof.
    bad_ex = deepcopy(evidence)
    del bad_ex["exhaustion"]["restore_inode_exhaustion"]
    with pytest.raises(ValueError, match="restore_inode_exhaustion"):
        mod["validate_h05_sizing_evidence"](bad_ex)

    # Reject tampered measurement hash.
    tampered_doc = deepcopy(doc)
    tampered_doc["measurement_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="measurement_sha256"):
        mod["validate_h05_sizing_document"](
            tampered_doc, raw_bytes, expected_source_sha256=SOURCE_SHA
        )

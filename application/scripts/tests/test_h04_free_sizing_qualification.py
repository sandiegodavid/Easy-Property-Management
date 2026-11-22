"""H04.9 Free-pilot (50 MB) physical storage sizing actor and closed validator tests."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import runpy

import pytest

GCP_DIR = Path(__file__).resolve().parents[2] / "deploy" / "hosted-mvp" / "gcp"
SOURCE_SHA = "a" * 64
MIB = 1024 * 1024
LINUX_EDQUOT = 122
LINUX_ENOSPC = 28
SCALED_TARGET_BYTES = 3_000_000
FREE_LOGICAL_BYTES = 50_000_000
PEAK_WS_BYTES = 110 * MIB
PEAK_WS_INODES = 2650
PEAK_CTL_BYTES = 6 * MIB
PEAK_CTL_INODES = 32
PEAK_SCRATCH_BYTES = 64 * MIB
PEAK_SCRATCH_INODES = 12


def _valid_linux_evidence() -> dict[str, object]:
    return {
        "platform": "Linux",
        "kernel": "7.0.0-1017-gcp",
        "prjquota_verified": True,
        "mount_options": ["rw", "nodev", "nosuid", "noexec", "prjquota"],
        "source_sha256": SOURCE_SHA,
        "workloads": {
            "database_heavy": {
                "shape": "database_heavy",
                "logical_used_bytes": 48_500_000,
                "logical_507_triggered": True,
                "trees": {
                    "workspace": {"peak_bytes": PEAK_WS_BYTES, "peak_inodes": 24},
                    "control": {"peak_bytes": 4 * MIB, "peak_inodes": 16},
                    "scratch": {
                        "peak_bytes": PEAK_SCRATCH_BYTES,
                        "peak_inodes": PEAK_SCRATCH_INODES,
                    },
                },
            },
            "retained_file_heavy": {
                "shape": "retained_file_heavy",
                "logical_used_bytes": 49_200_000,
                "logical_507_triggered": True,
                "trees": {
                    "workspace": {"peak_bytes": 54 * MIB, "peak_inodes": 96},
                    "control": {"peak_bytes": 3 * MIB, "peak_inodes": 16},
                    "scratch": {"peak_bytes": 8 * MIB, "peak_inodes": 8},
                },
            },
            "many_small_files_history": {
                "shape": "many_small_files_history",
                "logical_used_bytes": 42_000_000,
                "logical_507_triggered": True,
                "trees": {
                    "workspace": {"peak_bytes": 62 * MIB, "peak_inodes": PEAK_WS_INODES},
                    "control": {"peak_bytes": PEAK_CTL_BYTES, "peak_inodes": PEAK_CTL_INODES},
                    "scratch": {"peak_bytes": 2 * MIB, "peak_inodes": PEAK_SCRATCH_INODES},
                },
            },
        },
        "exhaustion": {
            "byte_exhaustion": {
                "kind": "byte_exhaustion",
                "errno": LINUX_EDQUOT,
                "sqlite_integrity_ok": True,
                "acknowledged_rows_preserved": True,
                "reservations_reconciled": True,
                "http_507_observed": True,
            },
            "inode_exhaustion": {
                "kind": "inode_exhaustion",
                "errno": LINUX_ENOSPC,
                "sqlite_integrity_ok": True,
                "acknowledged_rows_preserved": True,
                "reservations_reconciled": True,
                "http_507_observed": True,
            },
        },
    }


@pytest.mark.parametrize(
    "shape",
    ("database_heavy", "retained_file_heavy", "many_small_files_history"),
)
def test_sizing_actor_executes_all_three_workload_shapes_with_logical_507(tmp_path: Path, shape):
    actor = runpy.run_path(str(GCP_DIR / "free_sizing_actor.py"))
    result = actor["run_workload"](
        shape,
        workspace_dir=tmp_path / shape / "workspace",
        control_dir=tmp_path / shape / "control",
        scratch_dir=tmp_path / shape / "scratch",
        target_bytes=SCALED_TARGET_BYTES,
    )
    assert result["shape"] == shape
    assert result["items_written"] > 0
    assert 0 < result["logical_used_bytes"] <= SCALED_TARGET_BYTES
    assert result["logical_507_triggered"] is True
    for role in ("workspace", "control", "scratch"):
        assert result["trees"][role]["peak_bytes"] > 0
        assert result["trees"][role]["peak_inodes"] > 0


def test_derive_and_validate_free_sizing_document_happy_path():
    mod = runpy.run_path(str(GCP_DIR / "qualify_free_sizing.py"))
    evidence_bytes = json.dumps(_valid_linux_evidence(), sort_keys=True).encode("utf-8")

    doc = mod["derive_free_sizing_budget"](evidence_bytes, margin_factor=1.35)
    assert doc["slice"] == "H04.9"
    assert doc["logical_free_bytes"] == FREE_LOGICAL_BYTES
    assert doc["h05_backup_restore_reserve"] == "deferred_to_H05"
    assert doc["restore_readiness"] == "unavailable_pending_H05"
    assert doc["admission_enabled"] is False

    limits = mod["validate_free_sizing_document"](
        doc, evidence_bytes, expected_source_sha256=SOURCE_SHA
    )
    assert limits.workspace.byte_ceiling > PEAK_WS_BYTES
    assert limits.workspace.inode_ceiling > PEAK_WS_INODES
    assert limits.control.byte_ceiling > PEAK_CTL_BYTES
    assert limits.control.inode_ceiling > PEAK_CTL_INODES
    assert limits.scratch.byte_ceiling > PEAK_SCRATCH_BYTES
    assert limits.scratch.inode_ceiling > PEAK_SCRATCH_INODES


@pytest.mark.parametrize(
    "mutator,match",
    [
        (lambda e: e.__setitem__("platform", "Darwin"), "native Linux"),
        (lambda e: e.__setitem__("prjquota_verified", False), "prjquota"),
        (lambda e: e.__setitem__("mount_options", ["rw", "prjquota"]), "mount options"),
        (lambda e: e["workloads"].pop("many_small_files_history"), "Missing required workload"),
        (
            lambda e: e["exhaustion"]["inode_exhaustion"].__setitem__("errno", 1),
            "EDQUOT/ENOSPC",
        ),
        (
            lambda e: e["exhaustion"]["byte_exhaustion"].__setitem__(
                "reservations_reconciled", False
            ),
            "reconcile",
        ),
    ],
)
def test_validator_rejects_incomplete_or_non_linux_evidence(mutator, match):
    mod = runpy.run_path(str(GCP_DIR / "qualify_free_sizing.py"))
    evidence = _valid_linux_evidence()
    mutator(evidence)
    with pytest.raises(ValueError, match=match):
        mod["derive_free_sizing_budget"](json.dumps(evidence).encode("utf-8"))


def test_validator_rejects_tampered_document_or_permissive_admission():
    mod = runpy.run_path(str(GCP_DIR / "qualify_free_sizing.py"))
    evidence_bytes = json.dumps(_valid_linux_evidence(), sort_keys=True).encode("utf-8")
    doc = mod["derive_free_sizing_budget"](evidence_bytes)

    with pytest.raises(ValueError, match="measurement_sha256"):
        mod["validate_free_sizing_document"](
            doc, evidence_bytes + b" ", expected_source_sha256=SOURCE_SHA
        )

    permissive = deepcopy(doc)
    permissive["admission_enabled"] = True
    with pytest.raises(ValueError, match="Permissive"):
        mod["validate_free_sizing_document"](
            permissive, evidence_bytes, expected_source_sha256=SOURCE_SHA
        )

    zero_margin = deepcopy(doc)
    zero_margin["derived_trees"]["workspace"]["byte_ceiling"] = PEAK_WS_BYTES
    with pytest.raises(ValueError, match="no positive margin"):
        mod["validate_free_sizing_document"](
            zero_margin, evidence_bytes, expected_source_sha256=SOURCE_SHA
        )

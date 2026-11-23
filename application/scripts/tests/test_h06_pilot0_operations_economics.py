"""Focused tests for Slice H06.9 9-case operations_economics.json qualification."""

from __future__ import annotations

from pathlib import Path
import runpy

GCP_DIR = Path(__file__).resolve().parents[2] / "deploy" / "hosted-mvp" / "gcp"
EXPECTED_CASE_COUNT = 9


def test_h06_pilot0_9_case_operations_economics_qualification(tmp_path: Path):
    mod = runpy.run_path(str(GCP_DIR / "qualify_h06_pilot0.py"))
    out = tmp_path / "ops-econ.json"
    report = mod["run_pilot0_qualification"](out)
    assert report["status"] == "passed"
    assert len(report["cases"]) == EXPECTED_CASE_COUNT
    mod["validate_operations_economics_report"](report)
    assert out.is_file()

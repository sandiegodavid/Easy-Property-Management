"""Focused tests for H04.10 deployed H04/H05 handoff qualification runner and validator."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
APPLICATION_DIR = REPO_ROOT / "application"
SIZING_REPORT = (
    REPO_ROOT
    / "docs"
    / "hosting"
    / "qualification"
    / "reports"
    / "HOSTED_MVP_H04_9_FREE_SIZING.json"
)
SCRIPT_PATH = APPLICATION_DIR / "deploy" / "hosted-mvp" / "gcp" / "qualify_h04_handoff.py"
EXPECTED_OPERATORS = 2

sys.path.insert(0, str(APPLICATION_DIR / "apps" / "server"))

_spec = importlib.util.spec_from_file_location("qualify_h04_handoff", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules["qualify_h04_handoff"] = _mod
_spec.loader.exec_module(_mod)


@pytest.fixture(scope="module")
def component_report():
    return _mod.run_handoff_qualification(
        application_directory=APPLICATION_DIR,
        dataset_path=APPLICATION_DIR / "demo" / "dataset.json",
        sizing_path=SIZING_REPORT,
        mode="component",
    )


def test_h04_10_component_handoff_qualification_passes_end_to_end(component_report):
    report = component_report
    _mod.validate_h04_handoff_report(report)
    assert report["slice"] == "H04.10"
    assert report["h05_handoff_status"] == "ready_for_h05"
    assert len(report["operators"]) == EXPECTED_OPERATORS
    by_mode = {op["initial_data"]: op for op in report["operators"]}
    assert by_mode["synthetic"]["observed_usage_bytes"] > by_mode["empty"]["observed_usage_bytes"]
    assert report["gateway_handoff"]["eligible_rejected_by_gateway"] is True
    assert report["gateway_handoff"]["held_routes_only"] is True
    assert report["gateway_handoff"]["admin_lite_v2_verified"] is True
    assert report["operator_settings"]["protection_state"] == "unavailable"
    assert report["cleanup"]["disposable_operators_removed"] is True


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (lambda r: r["operators"].pop(), "exactly two disposable"),
        (
            lambda r: r["operators"][0].__setitem__("protection_state", "ready"),
            "fabricated H05 protection",
        ),
        (
            lambda r: r["gateway_handoff"].__setitem__("eligible_rejected_by_gateway", False),
            "closed-handoff checks",
        ),
        (
            lambda r: r["admin_lite_boundaries"].__setitem__("zero_token_leakage", False),
            "Admin-lite boundary checks",
        ),
        (
            lambda r: r["operator_settings"].__setitem__("paid_upgrade_controls_absent", False),
            "Operator Settings",
        ),
        (
            lambda r: r["cleanup"].__setitem__("disposable_operators_removed", False),
            "cleanly removed",
        ),
        (
            lambda r: r.__setitem__("mode", "gcp_native"),
            "real ext4 prjquota enforcement",
        ),
    ],
)
def test_h04_10_validator_rejects_incomplete_or_fabricated_reports(
    component_report, mutate, expected_error
):
    mutated = copy.deepcopy(component_report)
    mutate(mutated)
    with pytest.raises(ValueError, match=expected_error):
        _mod.validate_h04_handoff_report(mutated)

"""H05.11 Cloud KMS plan, 17-case recovery.json validator, and joint H04/H05 handoff tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import runpy

import pytest

GCP_DIR = Path(__file__).resolve().parents[2] / "deploy" / "hosted-mvp" / "gcp"
EXPECTED_CASE_COUNT = 17
EXPECTED_OPERATORS = 2


def test_cloud_plan_kms_plan_generates_reviewed_h05_commands():
    mod = runpy.run_path(str(GCP_DIR / "cloud_plan.py"))
    target = mod["Target"](
        project="synthetic-project",
        region="us-west1",
        zone="us-west1-b",
        instance="epm-h02-host",
        network="epm-h02-network",
        subnet="epm-h02-subnet",
        subnet_cidr="10.80.0.0/24",
        repository="epm-h02-candidates",
        service_account="epm-h02-host",
        image="ubuntu-2404-noble-amd64-v20261105",
        tunnel_id="00000000-0000-4000-8000-000000000001",
    )
    cmds = mod["kms_plan"](target)
    assert cmds[0] == [
        "services",
        "enable",
        "cloudkms.googleapis.com",
        "--project=synthetic-project",
    ]
    assert any("operator-workspace-kek" in cmd for cmd in cmds)
    assert any("admin-control-kek" in cmd for cmd in cmds)
    assert any("--role=roles/cloudkms.cryptoKeyEncrypterDecrypter" in cmd for cmd in cmds)
    with pytest.raises(ValueError, match="Canonical Cloud KMS"):
        mod["kms_plan"](target, keyring="BAD_KEYRING!")


def test_h05_recovery_spec_mapping_and_validator():
    mod = runpy.run_path(str(GCP_DIR / "qualify_h05_recovery.py"))
    spec = mod["load_recovery_spec"]()
    assert len(spec["cases"]) == EXPECTED_CASE_COUNT
    assert set(mod["CASE_TEST_MAP"]) == set(spec["cases"])

    handoff = mod["_run_joint_positive_handoff"]()
    assert handoff["status"] == "passed"
    assert len(handoff["operators_verified"]) == EXPECTED_OPERATORS
    assert handoff["admin_route_policy"] == "separate_exact_host_method_allowlists_v3"

    valid_report = {
        "version": 1,
        "proof": "recovery",
        "owner": "H05",
        "revision": 1,
        "level": "component",
        "status": "passed",
        "pins": {
            "source": "a" * 64,
            "tool": "pytest",
            "image": "component",
            "schema": "h05",
            "workload": "two_operators",
            "configuration": "v1",
        },
        "cases": {c: {"status": "passed"} for c in spec["cases"]},
        "joint_h04_h05_positive_handoff": handoff,
    }
    mod["validate_h05_recovery_report"](valid_report)

    missing_case = deepcopy(valid_report)
    del missing_case["cases"]["forensic_prior_tree"]
    with pytest.raises(ValueError, match="Case set mismatch"):
        mod["validate_h05_recovery_report"](missing_case)

    failed_case = deepcopy(valid_report)
    failed_case["cases"]["whole_host_control_loss"]["status"] = "failed"
    with pytest.raises(ValueError, match="whole_host_control_loss"):
        mod["validate_h05_recovery_report"](failed_case)

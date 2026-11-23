"""H06.6 focused tests: loopback health probes, production Dockerfiles, and 9-case image_schema."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import runpy

import pytest

from app.modules.hosted_access.infrastructure.health_probes import internal_health_server

GCP_DIR = Path(__file__).resolve().parents[2] / "deploy" / "hosted-mvp" / "gcp"
EXPECTED_CASES = 9


def test_internal_health_server_rejects_non_loopback_bind():
    with pytest.raises(ValueError, match="127.0.0.1"):
        with internal_health_server(lambda: True, host="0.0.0.0"):
            pass


def test_h06_image_schema_9_case_qualification_and_validator():
    mod = runpy.run_path(str(GCP_DIR / "qualify_h06_image_schema.py"))
    report = mod["run_image_schema_qualification"]()
    assert report["status"] == "passed"
    assert len(report["cases"]) == EXPECTED_CASES
    mod["validate_image_schema_report"](report)

    broken = deepcopy(report)
    del broken["cases"]["partial_initializer"]
    with pytest.raises(ValueError, match="Case set mismatch"):
        mod["validate_image_schema_report"](broken)

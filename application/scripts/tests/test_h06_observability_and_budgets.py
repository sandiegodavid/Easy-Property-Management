"""Focused tests for Slice H06.7 GCP observability, Ops Agent, alerts & budget plans."""

from __future__ import annotations

from pathlib import Path
import runpy

import pytest

GCP_DIR = Path(__file__).resolve().parents[2] / "deploy" / "hosted-mvp" / "gcp"


def _sample_target(cloud_plan: dict[str, object]):
    return cloud_plan["Target"](
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


def test_observability_plan_covers_logging_monitoring_uptime_and_budget():
    cloud_plan = runpy.run_path(str(GCP_DIR / "cloud_plan.py"))
    target = _sample_target(cloud_plan)
    obs = cloud_plan["observability_plan"](
        target,
        notification_email="owner@epmdemo.xyz",
        heartbeat_host="epmdemo.xyz",
        billing_account="01ABCD-23EF45-6789AB",
        monthly_budget_usd=250,
    )
    commands = obs["commands"]
    flat = [" ".join(cmd) for cmd in commands]
    assert any(
        "logging.googleapis.com" in line and "monitoring.googleapis.com" in line for line in flat
    )
    assert any("roles/logging.logWriter" in line for line in flat)
    assert any("roles/monitoring.metricWriter" in line for line in flat)
    assert any("--retention-days=30" in line for line in flat)
    assert any("epm_hosted_recovery_alerts" in line for line in flat)
    assert any("epm_host_guardian_containment" in line for line in flat)
    assert any("epm-pilot0-host-heartbeat" in line for line in flat)
    assert any(
        "--budget-amount=250USD" in line and "--credit-types-treatment=exclude-all-credits" in line
        for line in flat
    )

    policies = obs["alert_policies"]
    assert set(policies) == {
        "backup_alerts",
        "containment_alerts",
        "disk_headroom",
        "memory_headroom",
        "cpu_headroom",
        "host_loss_heartbeat",
    }
    heartbeat_cond = policies["host_loss_heartbeat"]["conditions"][0]["conditionThreshold"]
    assert heartbeat_cond["comparison"] == "COMPARISON_LT"
    assert heartbeat_cond["thresholdValue"] == 1.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"notification_email": "not-an-email"},
        {"notification_email": "owner@epmdemo.xyz", "heartbeat_host": "bad host"},
        {"notification_email": "owner@epmdemo.xyz", "monthly_budget_usd": 0},
        {"notification_email": "owner@epmdemo.xyz", "billing_account": "invalid"},
    ],
)
def test_observability_plan_rejects_invalid_inputs(kwargs):
    cloud_plan = runpy.run_path(str(GCP_DIR / "cloud_plan.py"))
    target = _sample_target(cloud_plan)
    with pytest.raises(ValueError):
        cloud_plan["observability_plan"](target, **kwargs)


def test_install_ops_agent_config_writes_valid_yaml_atomically(tmp_path: Path):
    cloud_plan = runpy.run_path(str(GCP_DIR / "cloud_plan.py"))
    install_services = runpy.run_path(str(GCP_DIR / "install_services.py"))
    dest = tmp_path / "ops-agent" / "config.yaml"
    written = install_services["install_ops_agent_config"](
        cloud_plan["ops_agent_config"](), destination=dest
    )
    assert written == dest
    body = dest.read_text(encoding="utf-8")
    assert "systemd_journald" in body and "hostmetrics" in body
    with pytest.raises(ValueError):
        install_services["install_ops_agent_config"]("invalid: true", destination=dest)


def test_qualify_h06_observability_synthetic_alert_and_recovery(tmp_path: Path):
    mod = runpy.run_path(str(GCP_DIR / "qualify_h06_observability.py"))
    out = tmp_path / "report.json"
    report = mod["run_observability_qualification"](out)
    assert report["status"] == "passed"
    synth = report["cases"]["synthetic_alert_and_recovery_delivery"]
    assert synth["incident_delivered"] is True
    assert synth["duplicate_suppressed"] is True
    assert synth["recovery_notice_delivered"] is True
    assert synth["duplicate_recovery_suppressed"] is True
    assert out.is_file()

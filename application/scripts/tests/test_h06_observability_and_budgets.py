"""Focused tests for Slice H06.7 GCP observability, Ops Agent, alerts & budget plans."""

from __future__ import annotations

from pathlib import Path
import runpy

import pytest

GCP_DIR = Path(__file__).resolve().parents[2] / "deploy" / "hosted-mvp" / "gcp"
CPU_THRESHOLD_PERCENT = 85.0


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
        billing=("01ABCD-23EF45-6789AB", "732190125040"),
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
    assert any(
        "epm_hosted_recovery_alerts" in line and "severity>=WARNING" in line for line in flat
    )
    assert any("runtime_containment_attention" in line for line in flat)
    assert any("epm-pilot0-host-heartbeat" in line for line in flat)
    assert any(
        "--budget-amount=250USD" in line
        and "--filter-projects=projects/732190125040" in line
        and "--credit-types-treatment=exclude-all-credits" in line
        for line in flat
    )

    policies = obs["alert_policies"]
    assert set(policies) == {
        "backup_alerts",
        "containment_alerts",
        "disk_headroom",
        "inode_headroom",
        "memory_headroom",
        "cpu_headroom",
        "host_loss_heartbeat",
    }
    backup_agg = policies["backup_alerts"]["conditions"][0]["conditionThreshold"]["aggregations"][0]
    assert backup_agg["perSeriesAligner"] == "ALIGN_SUM"
    disk_filter = policies["disk_headroom"]["conditions"][0]["conditionThreshold"]["filter"]
    assert 'metric.labels.device!=monitoring.regex.full_match("/dev/loop.*")' in disk_filter
    cpu_cond = policies["cpu_headroom"]["conditions"][0]["conditionThreshold"]
    assert 'metric.labels.cpu_state!="idle"' in cpu_cond["filter"]
    assert cpu_cond["thresholdValue"] == CPU_THRESHOLD_PERCENT
    assert cpu_cond["aggregations"][0]["crossSeriesReducer"] == "REDUCE_SUM"
    assert cpu_cond["aggregations"][0]["groupByFields"] == ["resource.label.instance_id"]
    heartbeat_cond = policies["host_loss_heartbeat"]["conditions"][0]["conditionThreshold"]
    assert heartbeat_cond["comparison"] == "COMPARISON_LT"
    assert heartbeat_cond["thresholdValue"] == 1.0
    assert heartbeat_cond["aggregations"][0]["perSeriesAligner"] == "ALIGN_FRACTION_TRUE"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"notification_email": "not-an-email"},
        {"notification_email": "owner@epmdemo.xyz", "heartbeat_host": "bad host"},
        {"notification_email": "owner@epmdemo.xyz", "monthly_budget_usd": 0},
        {"notification_email": "owner@epmdemo.xyz", "billing": ("invalid", "732190125040")},
        {"notification_email": "owner@epmdemo.xyz", "billing": ("01ABCD-23EF45-6789AB", "bad")},
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

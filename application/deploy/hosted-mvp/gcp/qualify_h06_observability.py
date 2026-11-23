#!/usr/bin/env python3
"""H06.7 GCP Observability, Alert Policies, Budget & Synthetic Alert Delivery Qualifier."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import runpy
import sys
from time import time_ns
from urllib.request import Request

from app.modules.hosted_recovery.infrastructure.alerting import (
    DeduplicatingAlertEmitter,
    RecoveryAlert,
    StructuredLogAlertSink,
    WebhookAlertSink,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
GCP_DIR = REPO_ROOT / "application" / "deploy" / "hosted-mvp" / "gcp"
REQUIRED_CLI_ARGS = 2
EXPECTED_DELIVERED_ALERTS = 2


class _MemoryLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(self.format(record))


def verify_synthetic_alert_and_recovery() -> dict[str, object]:
    """Prove deduplicated incident delivery, SSRF rejection, and recovery notice."""
    unsafe_urls = (
        "http://alerts.epmdemo.xyz/hook",
        "https://127.0.0.1/hook",
        "https://metadata.google.internal/computeMetadata/v1/",
    )
    rejected_urls: list[str] = []
    for bad_url in unsafe_urls:
        try:
            WebhookAlertSink(bad_url)
        except ValueError:
            rejected_urls.append(bad_url)
    if len(rejected_urls) != len(unsafe_urls):
        raise ValueError("WebhookAlertSink failed to reject unsafe URLs.")

    delivered_webhooks: list[dict[str, object]] = []

    def _recording_opener(request: Request, _timeout: float) -> bytes:
        body = request.data.decode("utf-8") if isinstance(request.data, bytes) else "{}"
        delivered_webhooks.append(json.loads(body))
        return b'{"ok":true}'

    test_logger = logging.getLogger("epm.h067.synthetic_alert_test")
    test_logger.setLevel(logging.INFO)
    test_logger.propagate = False
    handler = _MemoryLogHandler()
    test_logger.addHandler(handler)
    try:
        emitter = DeduplicatingAlertEmitter(
            [
                StructuredLogAlertSink(test_logger),
                WebhookAlertSink(
                    "https://alerts.epmdemo.xyz/pilot0-webhook",
                    opener=_recording_opener,
                ),
            ]
        )
        incident = RecoveryAlert(
            deployment_id="b77f7c7e-c89c-4d44-b337-e8d4f13ee46f",
            operator_id="00000000-0000-4000-8000-000000000101",
            workspace_id="00000000-0000-4000-8000-000000000201",
            alert_kind="backup_overdue",
            protection_state="overdue",
            recorded_at=1_795_476_000_000,
            consecutive_failures=2,
            last_error_code="backup_proxy_timeout",
            last_verified_at=1_795_370_000_000,
            dirty_since=1_795_380_000_000,
        )
        first_sent = emitter.notify_incident(incident)
        duplicate_sent = emitter.notify_incident(incident)
        recovered_sent = emitter.notify_recovered(
            deployment_id=incident.deployment_id,
            operator_id=incident.operator_id,
            workspace_id=incident.workspace_id,
            protection_state="healthy",
            recorded_at=1_795_476_600_000,
            last_verified_at=1_795_476_500_000,
        )
        second_recovered_sent = emitter.notify_recovered(
            deployment_id=incident.deployment_id,
            operator_id=incident.operator_id,
            workspace_id=incident.workspace_id,
            protection_state="healthy",
            recorded_at=1_795_476_900_000,
            last_verified_at=1_795_476_500_000,
        )
    finally:
        test_logger.removeHandler(handler)

    if not (first_sent and not duplicate_sent and recovered_sent and not second_recovered_sent):
        raise ValueError("Alert deduplication or recovery notice semantics failed.")
    if (
        len(delivered_webhooks) != EXPECTED_DELIVERED_ALERTS
        or len(handler.messages) != EXPECTED_DELIVERED_ALERTS
    ):
        raise ValueError("Expected exactly 2 delivered alerts (1 incident + 1 recovery).")
    if (
        delivered_webhooks[0]["alert_kind"] != "backup_overdue"
        or delivered_webhooks[1]["alert_kind"] != "backup_recovered"
    ):
        raise ValueError("Delivered alert sequence did not match incident -> recovered.")

    return {
        "status": "passed",
        "unsafe_webhook_urls_rejected": len(rejected_urls),
        "incident_delivered": first_sent,
        "duplicate_suppressed": not duplicate_sent,
        "recovery_notice_delivered": recovered_sent,
        "duplicate_recovery_suppressed": not second_recovered_sent,
        "webhook_delivery_count": len(delivered_webhooks),
        "structured_log_delivery_count": len(handler.messages),
    }


def run_observability_qualification(output_path: Path | None = None) -> dict[str, object]:
    cloud_plan = runpy.run_path(str(GCP_DIR / "cloud_plan.py"))
    target = cloud_plan["Target"](
        project="project-47b72bb7-ba90-42c9-910",
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
    obs = cloud_plan["observability_plan"](
        target,
        notification_email="ops@epmdemo.xyz",
        heartbeat_host="epmdemo.xyz",
        billing_account="01ABCD-23EF45-6789AB",
        monthly_budget_usd=250,
    )
    startup_text = (GCP_DIR / "startup.sh").read_text(encoding="utf-8")
    if "curl |" in startup_text or "/etc/google-cloud-ops-agent" not in startup_text:
        raise ValueError("startup.sh violated H06.7 Ops Agent staging or curl-pipe policy.")

    synthetic = verify_synthetic_alert_and_recovery()
    report: dict[str, object] = {
        "version": 1,
        "proof": "h06_7_observability_alerts_and_budget",
        "owner": "H06.7",
        "status": "passed",
        "recorded_at_ms": time_ns() // 1_000_000,
        "plan_summary": {
            "command_count": len(obs["commands"]),
            "alert_policy_names": sorted(obs["alert_policies"]),
            "log_retention_days": obs["log_retention_days"],
            "monthly_budget_usd": obs["monthly_budget_usd"],
            "budget_excludes_credits": obs["budget_excludes_credits"],
        },
        "cases": {
            "observability_plan_and_ops_agent": {"status": "passed"},
            "synthetic_alert_and_recovery_delivery": synthetic,
        },
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return report


def main() -> int:
    if len(sys.argv) != REQUIRED_CLI_ARGS:
        raise SystemExit("Usage: qualify_h06_observability.py <output.json>")
    run_observability_qualification(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

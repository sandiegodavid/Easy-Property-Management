# HOSTED-001 Slice H06.7 Checkpoint — GCP Observability, Alert Policies & Billing Budget

**Date:** 2026-11-23  
**Slice:** `H06.7` (of [HOSTED_MVP_H06_DESIGN.md](../../design/HOSTED_MVP_H06_DESIGN.md))  
**Status:** Complete (ready for `H06.8`)  
**Operations Runbook:** [H06_7_GCP_OBSERVABILITY_AND_BUDGET_RUNBOOK.md](../../runbooks/H06_7_GCP_OBSERVABILITY_AND_BUDGET_RUNBOOK.md)

---

## 1. Deliverables Completed

### Reviewed GCP Observability, Ops Agent & Budget Plans (D3, D9)
- Extended [cloud_plan.py](../../../application/deploy/hosted-mvp/gcp/cloud_plan.py):
  - Added `logging.googleapis.com` and `monitoring.googleapis.com` to base `plan()`.
  - Added `ops_agent_config()` generating hardened `/etc/google-cloud-ops-agent/config.yaml` (collecting systemd journal + Docker JSON logs with JSON timestamp parsing + 60s `hostmetrics` CPU/RAM/disk/inode pipeline).
  - Added `observability_plan(target, notification_email=..., heartbeat_host=..., billing_account=..., monthly_budget_usd=250)` with strict input validation, emitting explicit reviewed `gcloud` commands for:
    - Enabling `logging.googleapis.com`, `monitoring.googleapis.com`, `billingbudgets.googleapis.com`
    - Binding `roles/logging.logWriter` and `roles/monitoring.metricWriter` to `epm-h02-host@<project>.iam.gserviceaccount.com`
    - Setting Cloud Logging `_Default` bucket retention to 30 days
    - Creating operational-owner email notification channel
    - Creating log-based metrics `epm_hosted_recovery_alerts` and `epm_host_guardian_containment`
    - Creating external HTTPS uptime heartbeat check `epm-pilot0-host-heartbeat`
    - Creating `$250/month` before-credit GCP Billing Budget (`--credit-types-treatment=exclude-all-credits`, 50%/80%/100% thresholds)
  - Emits all 6 declarative Cloud Monitoring alert policy payloads: `backup_alerts`, `containment_alerts`, `disk_headroom` (>80%), `memory_headroom` (>85%), `cpu_headroom` (>85% for 10m), and `host_loss_heartbeat` (`COMPARISON_LT` 1.0 for 5m).
- Added atomic `install_ops_agent_config()` to [install_services.py](../../../application/deploy/hosted-mvp/gcp/install_services.py) and pre-created `/etc/google-cloud-ops-agent` in [startup.sh](../../../application/deploy/hosted-mvp/gcp/startup.sh) (preserving the zero `curl |` policy).

### Live GCP Project Observability Provisioning (`project-47b72bb7-ba90-42c9-910`)
Executed directly against GCP control plane (zero VM runtime; `epm-h02-host` remained **STOPPED**):
- Enabled `logging.googleapis.com`, `monitoring.googleapis.com`, `billingbudgets.googleapis.com`.
- Granted `roles/logging.logWriter` and `roles/monitoring.metricWriter` to `epm-h02-host@project-47b72bb7-ba90-42c9-910.iam.gserviceaccount.com`.
- Set Cloud Logging `_Default` bucket retention to `30` days.
- Created live log-based metrics `epm_hosted_recovery_alerts` and `epm_host_guardian_containment`.
- Remaining owner-specific bindings (notification email channel, 6 alert policies, uptime check, `$250/mo` Billing Budget against the active billing account, and Ops Agent package install on `epm-h02-host`) are sequenced with the concrete operational owner contact and live deployment in `H06.8`–`H06.10`.

### Synthetic Alert Delivery & Recovery Notice Verification
- Created [qualify_h06_observability.py](../../../application/deploy/hosted-mvp/gcp/qualify_h06_observability.py) and [test_h06_observability_and_budgets.py](../../../application/scripts/tests/test_h06_observability_and_budgets.py).
- Verified `WebhookAlertSink` SSRF rejection (HTTP, loopback, GCP metadata), `DeduplicatingAlertEmitter` incident delivery + duplicate suppression, and `notify_recovered` recovery-notice delivery + duplicate suppression across both `StructuredLogAlertSink` and `WebhookAlertSink`.
- Generated [HOSTED_MVP_H06_7_OBSERVABILITY_AND_ALERTS.json](HOSTED_MVP_H06_7_OBSERVABILITY_AND_ALERTS.json) (`status: "passed"`).

---

## 2. Validation Results

| Check | Result |
| --- | --- |
| `pytest scripts/tests/test_h06_observability_and_budgets.py scripts/tests/test_hosted_gcp.py` | **38 passed** |
| `qualify_h06_observability.py` → `HOSTED_MVP_H06_7_OBSERVABILITY_AND_ALERTS.json` | **passed** |
| `ruff check --config pyproject.toml` on all H06.7 Python files | **All checks passed** |
| `ruff format --check --config pyproject.toml` on all H06.7 Python files | **4 files already formatted** |
| Live GCP APIs, IAM (`logWriter`/`metricWriter`), 30d retention & log-based metrics | **provisioned & verified** |
| `epm-h02-host` VM state | **STOPPED** |

---

## 3. Next Slice

Proceed to **H06.8 — Pilot 0 Operations Runbooks & Cost/Admin-Minutes/Adoption Worksheets** (Launch Gate, Incident/Support Triage, Announced Maintenance Window, Break-Glass/Retirement runbooks, and `PILOT_0_COST_AND_OPS_WORKSHEET.md`).

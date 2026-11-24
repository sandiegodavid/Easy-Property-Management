# Slice H06.7 Operations Runbook — GCP Observability, Alert Policies & Before-Credit Billing Budget

**Slice:** `H06.7` ([HOSTED_MVP_H06_DESIGN.md](../design/HOSTED_MVP_H06_DESIGN.md))  
**Checkpoint:** [HOSTED_MVP_H06_7_CHECKPOINT_2026-11-23.md](../qualification/reports/HOSTED_MVP_H06_7_CHECKPOINT_2026-11-23.md)  
**Target Project:** `project-47b72bb7-ba90-42c9-910` (`us-west1`, VM `epm-h02-host`)

This runbook records the exact operator steps to provision GCP Cloud Logging/Monitoring APIs, IAM bindings, 30-day log retention, log-based backup/containment metrics, Ops Agent config, owner notification channels, alert policies, external VM heartbeat uptime check, and the `$250/month` before-credit Billing Budget.

---

## 1. Local Plan & Synthetic Alert Verification

Run from the repository root:

```bash
cd application

# 1. Verify observability_plan(), ops_agent_config(), install_ops_agent_config(), and GCP plan contracts
PYTHONPATH=apps/server .venv/bin/pytest \
  scripts/tests/test_h06_observability_and_budgets.py \
  scripts/tests/test_hosted_gcp.py

# 2. Generate and verify the synthetic alert + deduplication + recovery-notice report
PYTHONPATH=apps/server .venv/bin/python \
  deploy/hosted-mvp/gcp/qualify_h06_observability.py \
  ../docs/hosting/qualification/reports/HOSTED_MVP_H06_7_OBSERVABILITY_AND_ALERTS.json

# 3. Verify Python lint and formatting
.venv/bin/ruff check --config pyproject.toml \
  deploy/hosted-mvp/gcp/cloud_plan.py \
  deploy/hosted-mvp/gcp/install_services.py \
  deploy/hosted-mvp/gcp/qualify_h06_observability.py \
  scripts/tests/test_h06_observability_and_budgets.py

.venv/bin/ruff format --check --config pyproject.toml \
  deploy/hosted-mvp/gcp/cloud_plan.py \
  deploy/hosted-mvp/gcp/install_services.py \
  deploy/hosted-mvp/gcp/qualify_h06_observability.py \
  scripts/tests/test_h06_observability_and_budgets.py
```

---

## 2. Live GCP Control-Plane Provisioning (Executed in H06.7; Zero VM Runtime)

These commands run against the GCP control plane while `epm-h02-host` remains **STOPPED**:

```bash
PROJECT=project-47b72bb7-ba90-42c9-910
SA=epm-h02-host@${PROJECT}.iam.gserviceaccount.com

# 1. Enable Cloud Logging, Cloud Monitoring, and Cloud Billing Budgets APIs
gcloud services enable \
  logging.googleapis.com \
  monitoring.googleapis.com \
  billingbudgets.googleapis.com \
  --project="${PROJECT}"

# 2. Grant logWriter and metricWriter to the host VM service account
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/logging.logWriter" \
  --quiet

gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/monitoring.metricWriter" \
  --quiet

# 3. Bound Cloud Logging retention to 30 days
gcloud logging buckets update _Default \
  --location=global \
  --retention-days=30 \
  --project="${PROJECT}"

# 4. Create log-based metrics for backup alerts and host guardian containment
gcloud logging metrics create epm_hosted_recovery_alerts \
  --description="Hosted recovery overdue/failure alerts (H05/H06)" \
  --log-filter='(jsonPayload.event="hosted_recovery_alert" OR textPayload:"hosted_recovery_alert") AND severity>=WARNING AND NOT textPayload:"\"backup_recovered\""' \
  --project="${PROJECT}"

gcloud logging metrics create epm_host_guardian_containment \
  --description="Host guardian container containment events (H02/H06)" \
  --log-filter='jsonPayload.event="runtime_containment_attention" OR textPayload:"runtime_containment_attention"' \
  --project="${PROJECT}"
```

---

## 3. Pilot 0 Launch-Time Owner Bindings (Executed with Final Owner Email & Billing Account)

Once the concrete Pilot 0 operational owner email (`OWNER_EMAIL`) and GCP billing account ID (`BILLING_ACCOUNT`, format `XXXXXX-XXXXXX-XXXXXX`) are confirmed in the Pilot 0 Launch Gate (`H06.8`/`H06.10`):

```bash
PROJECT=project-47b72bb7-ba90-42c9-910
OWNER_EMAIL="<real-owner-email>"
BILLING_ACCOUNT="<XXXXXX-XXXXXX-XXXXXX>"
HEARTBEAT_HOST="epmdemo.xyz"

# 1. Create the operational owner email notification channel
gcloud beta monitoring channels create \
  --display-name="EPM Pilot 0 Owner Email" \
  --type=email \
  --channel-labels="email_address=${OWNER_EMAIL}" \
  --project="${PROJECT}"

# 2. Create the external HTTPS host-loss uptime check (5-minute period)
gcloud monitoring uptime create epm-pilot0-host-heartbeat \
  --resource-type=uptime-url \
  --resource-labels="host=${HEARTBEAT_HOST},project_id=${PROJECT}" \
  --protocol=https \
  --path=/ \
  --period=5 \
  --timeout=10 \
  --project="${PROJECT}"

# 3. Resolve numeric project number and create the $250/month before-credit Billing Budget (50%, 80%, 100% thresholds)
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')
gcloud billing budgets create \
  --billing-account="${BILLING_ACCOUNT}" \
  --display-name="EPM Pilot 0 Monthly Gross Spend (\$250)" \
  --budget-amount=250USD \
  --filter-projects="projects/${PROJECT_NUMBER}" \
  --credit-types-treatment=exclude-all-credits \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=0.8 \
  --threshold-rule=percent=1.0
```

Create the 6 Cloud Monitoring alert policies (`backup_alerts`, `containment_alerts`, `disk_headroom` >80%, `memory_headroom` >85%, `cpu_headroom` >85% for 10m, `host_loss_heartbeat` `< 1.0` for 5m) from the JSON definitions emitted by `cloud_plan.observability_plan(...)` and attach the email notification channel ID returned in Step 1.

---

## 4. Installing GCP Ops Agent Config on `epm-h02-host`

When provisioning or updating `epm-h02-host`:
1. Write `/etc/google-cloud-ops-agent/config.yaml` (`0644`, root-owned) via `install_services.install_ops_agent_config(cloud_plan.ops_agent_config())`.
2. Install the signed `google-cloud-ops-agent` APT package from Google's official signed APT repository (never `curl | bash`).
3. Restart and verify:
   ```bash
   sudo systemctl enable --now google-cloud-ops-agent.service
   sudo systemctl status google-cloud-ops-agent.service --no-pager
   ```
4. Confirm host metrics (`agent.googleapis.com/disk/percent_used`, `memory/percent_used`, `cpu/utilization`) and redacted structured JSON logs appear in Cloud Monitoring and Cloud Logging without any cookies, bearer tokens, DEKs, or R2 secrets.

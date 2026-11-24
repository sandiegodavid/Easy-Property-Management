# H06.10 Operations Runbook — Live Pilot 0 Launch-Day Gates (Gates 1–6)

**Applies to:** HOSTED-001 Slice H06.10 (Live Pilot 0 Go/No-Go execution on `epm-h02-host` / `epmdemo.xyz`)  
**Exit Review:** [HOSTED_MVP_H06_10_EXIT_REVIEW.md](../qualification/reports/HOSTED_MVP_H06_10_EXIT_REVIEW.md)  
**Acceptance Register:** [HOSTED_MVP_ACCEPTANCE.md](../qualification/HOSTED_MVP_ACCEPTANCE.md)  
**Related Runbooks:** [H06_6_IMAGE_AND_LIVE_R2_KMS_RUNBOOK.md](H06_6_IMAGE_AND_LIVE_R2_KMS_RUNBOOK.md) · [H06_7_GCP_OBSERVABILITY_AND_BUDGET_RUNBOOK.md](H06_7_GCP_OBSERVABILITY_AND_BUDGET_RUNBOOK.md) · [H06_8_PILOT0_ADMISSION_AND_CAPACITY_RUNBOOK.md](H06_8_PILOT0_ADMISSION_AND_CAPACITY_RUNBOOK.md)

---

## 0. Environment Constants & Prerequisites

```bash
export PROJECT_ID="project-47b72bb7-ba90-42c9-910"
export PROJECT_NUMBER="732190125040"
export BILLING_ACCOUNT="0129C0-EFF863-71F114"
export ZONE="us-west1-b"
export INSTANCE="epm-h02-host"
export SUPPORT_EMAIL="dctech92130@gmail.com"
export OWNER_NAME="DC Technology"
```

- **SSH Access:** `epm-h02-host` has no public SSH port; always use `--tunnel-through-iap` with `gcloud compute ssh` / `gcloud compute scp`.
- **VM Python:** Always use `/opt/epm/python/bin/python3` (Python 3.14) on `epm-h02-host`, **not** `/usr/bin/python3` (Python 3.12).
- **VM Cost Control:** Always start `epm-h02-host` only when actively running live gates or admitting operators, and stop it immediately afterward (`gcloud compute instances stop ...`).

---

## 1. Gate 1 — Seal Operational Owner & Economics Baseline

Record concrete operational owner details in [PILOT_0_COST_AND_OPS_WORKSHEET.md](../qualification/reports/PILOT_0_COST_AND_OPS_WORKSHEET.md):
- **Owner:** `DC Technology`
- **Monitored Support & Alert Email (`EPM_SUPPORT_CONTACT`):** `dctech92130@gmail.com`
- **GCP Project / Project Number / Billing Account:** `project-47b72bb7-ba90-42c9-910` / `732190125040` / `0129C0-EFF863-71F114`
- **GCP Credits Expiry Date:** `January 22, 2027`

---

## 2. Gate 3 — Live GCP Observability, Alerts, Budget & Ops Agent

Executed live on GCP project `project-47b72bb7-ba90-42c9-910` and `epm-h02-host` (recorded in [HOSTED_MVP_H06_10_LIVE_OBSERVABILITY.json](../qualification/reports/HOSTED_MVP_H06_10_LIVE_OBSERVABILITY.json)):

1. **Create owner email notification channel:**
   ```bash
   gcloud beta monitoring channels create \
     --project="$PROJECT_ID" \
     --display-name="EPM Pilot 0 Owner Email" \
     --type=email \
     --channel-labels="email_address=$SUPPORT_EMAIL"
   # Recorded: projects/project-47b72bb7-ba90-42c9-910/notificationChannels/10994584444383148615
   ```

2. **Create external HTTPS uptime check (`epm-pilot0-host-heartbeat`):**
   ```bash
   gcloud monitoring uptime create epm-pilot0-host-heartbeat \
     --project="$PROJECT_ID" \
     --resource-type=uptime-url \
     --resource-labels="host=epmdemo.xyz,project_id=$PROJECT_ID" \
     --protocol=https --path=/ --period=5 --timeout=10
   # Recorded: projects/project-47b72bb7-ba90-42c9-910/uptimeCheckConfigs/epm-pilot0-host-heartbeat-LjGDGoURNUM
   ```

3. **Create `$250/mo` before-credit GCP Billing Budget:**
   > **Operational Gotcha:** `gcloud billing budgets create` requires `--billing-project="$PROJECT_ID"` (quota project) and `--filter-projects="projects/$PROJECT_NUMBER"` (numeric project number, not string project ID).
   ```bash
   gcloud billing budgets create \
     --billing-account="$BILLING_ACCOUNT" \
     --billing-project="$PROJECT_ID" \
     --display-name='EPM Pilot 0 Monthly Gross Spend ($250)' \
     --budget-amount=250USD \
     --filter-projects="projects/$PROJECT_NUMBER" \
     --credit-types-treatment=exclude-all-credits \
     --threshold-rule=percent=0.5 \
     --threshold-rule=percent=0.8 \
     --threshold-rule=percent=1.0
   # Recorded: billingAccounts/0129C0-EFF863-71F114/budgets/7b2ec8a9-1f99-4e31-a74b-040623e8d33a
   ```

4. **Create 3rd log-based metric for GCE inode headroom (`epm_host_inode_headroom`):**
   > **Operational Gotcha:** GCP Ops Agent `hostmetrics` does not export an `agent.googleapis.com/disk/inode_percent_used` metric on GCE VMs. Use a Cloud Logging log-based metric (`epm_host_inode_headroom`) matching `host_inode_headroom_alert` events alongside `epm_hosted_recovery_alerts` and `epm_host_guardian_containment`.
   ```bash
   gcloud logging metrics create epm_host_inode_headroom \
     --project="$PROJECT_ID" \
     --description='Host inode utilization > 80% alerts (H06.7)' \
     --log-filter='jsonPayload.event="host_inode_headroom_alert" OR textPayload:"host_inode_headroom_alert"'
   ```

5. **Create all 7 Cloud Monitoring alert policies** (attached to channel `10994584444383148615`):
   > **Operational Gotcha:** Log-based metric alert policies must include `AND resource.type="gce_instance"` in the metric filter (`cloud_plan.py` updated to match).
   - `backup_alerts`: `13238644082096496292`
   - `containment_alerts`: `1453814380948339794`
   - `disk_headroom`: `9608306146000673870`
   - `inode_headroom`: `10870507054876049767`
   - `memory_headroom`: `582520471517413336`
   - `cpu_headroom`: `4267280413202838215`
   - `host_loss_heartbeat`: `10354216567484543828`

6. **Install and start `google-cloud-ops-agent` on `epm-h02-host`:**
   > **Operational Gotcha:** Ops Agent `parse_json` requires `time_format: "%Y-%m-%dT%H:%M:%S.%L%z"` whenever `time_key: time` is configured (`cloud_plan.py` updated to match).
   - Installed `google-cloud-ops-agent` (`2.73.0~ubuntu24.04`), wrote `/etc/google-cloud-ops-agent/config.yaml`, restarted and verified `systemctl is-active google-cloud-ops-agent.service` → `active`.

---

## 3. Gate 4 — Live GCP 17-Case `recovery.json` Proof

1. Run `qualify_h05_recovery.py` natively on `epm-h02-host` using `/opt/epm/python/bin/python3`:
   ```bash
   PYTHONPATH=/tmp/epm-h0610/application/apps/server \
     /tmp/epm-h0610/venv/bin/python \
     /tmp/epm-h0610/application/deploy/hosted-mvp/gcp/qualify_h05_recovery.py \
     /tmp/epm-h0610/gcp_recovery_17.json
   ```
2. Download the report to [HOSTED_MVP_H06_10_GCP_RECOVERY_17.json](../qualification/reports/HOSTED_MVP_H06_10_GCP_RECOVERY_17.json) (17/17 `recovery.json` cases + joint H04/H05 positive handoff passed), paired with live R2 + Cloud KMS + `SO_PEERCRED` `epm-backup-proxy` proof ([HOSTED_MVP_H06_6_LIVE_R2_KMS_RECOVERY.json](../qualification/reports/HOSTED_MVP_H06_6_LIVE_R2_KMS_RECOVERY.json)).

---

## 4. Gate 2 — Immutable Production OCI Image Builds & Zero-Checkout 6-Store Proof

1. **Build fresh frontend bundles locally** (`npm run build`, `npm run build:admin`, `npm run build:central`) and archive with `COPYFILE_DISABLE=1 tar -czf ...` (prevents macOS `._*` AppleDouble files from failing `hosted_package.py`'s strict allowlist `validate_path`).
2. **Prime `uv`'s offline build cache once on `epm-h02-host`** (so `hosted_package.py`'s `--offline --build-constraints deploy/hosted-mvp/build-constraints.txt` has `setuptools==84.0.0` cached):
   ```bash
   uv build --wheel --build-constraints deploy/hosted-mvp/build-constraints.txt --out-dir /tmp/prime
   ```
3. **Package all 3 components and build immutable Docker images on `epm-h02-host`:**
   ```bash
   python hosted_package.py --component admin --identity --architecture amd64 \
     --lock /opt/epm/agent-bundle/dependencies.lock \
     --wheelhouse /opt/epm/agent-bundle/wheelhouse --output /tmp/build/admin
   python hosted_package.py --component operator --architecture amd64 \
     --lock /opt/epm/agent-bundle/dependencies.lock \
     --wheelhouse /opt/epm/agent-bundle/wheelhouse --output /tmp/build/operator
   python hosted_package.py --component host_agent --architecture amd64 \
     --lock /opt/epm/agent-bundle/dependencies.lock \
     --wheelhouse /opt/epm/agent-bundle/wheelhouse --output /tmp/build/host_agent
   python archive_agent.py /tmp/build/host_agent /tmp/build/host-agent.tar.gz

   sudo docker build -t epm-pilot0-admin:h0610 /tmp/build/admin
   sudo docker build -t epm-pilot0-operator:h0610 /tmp/build/operator
   ```
4. **Run zero-checkout, zero-`PYTHONPATH` verification inside both containers** (`sudo docker run --rm --entrypoint /opt/epm/venv/bin/python ...`) verifying `app.hosted_candidates.runtime.inspect(...)`, production entrypoints (`shared_identity_entry`, `admin_entry`, `operator_entry`, `health_probes`), fresh `initialize_store` / `initialize_latest_schema`, idempotent re-init (`already_initialized`), and wrong-store rejection across all 6 stores (`admin`, `admin-recovery`, `business`, `hosted-access`, `recovery`, `host-inventory`).
5. **Pinned Immutable Digests Recorded** in [HOSTED_MVP_H06_10_DOCKER_LINUX_IMAGE_SCHEMA.json](../qualification/reports/HOSTED_MVP_H06_10_DOCKER_LINUX_IMAGE_SCHEMA.json):
   - `epm-pilot0-admin:h0610`: `sha256:22506437168079fc65f56a2a0d9dacad61749bd5ca46484fae1f1ebf492cc70f`
   - `epm-pilot0-operator:h0610`: `sha256:7b0e6791a60ddf3faac7d7633e992fcbcb0fd557021aaf001b2f144a7427864e`
   - `host-agent.tar.gz`: `sha256:61af280717f49de0577b0291d3a1e2716fc4c0990174a18bdbd7bffbf3c74314`

---

## 5. Gate 6 — Live GCP Linux `operations_economics.json` Rehearsal

1. Run `qualify_h06_pilot0.py` on native GCP Linux `epm-h02-host`:
   ```bash
   PYTHONPATH=/tmp/epm-h0610/application/apps/server \
     /tmp/epm-h0610/venv/bin/python \
     /tmp/epm-h0610/application/deploy/hosted-mvp/gcp/qualify_h06_pilot0.py \
     /tmp/epm-h0610/ops_econ_gcp.json
   ```
2. Record the 9-case output in [HOSTED_MVP_H06_10_GCP_OPERATIONS_ECONOMICS.json](../qualification/reports/HOSTED_MVP_H06_10_GCP_OPERATIONS_ECONOMICS.json) and log elapsed rehearsal VM spend (before credits, in integer USD micros) + Admin minutes in [PILOT_0_COST_AND_OPS_WORKSHEET.md](../qualification/reports/PILOT_0_COST_AND_OPS_WORKSHEET.md).

---

## 6. Gate 5 — Live Deployed 4-Browser `identity_handoff.json` Rehearsal

1. **Reinitialize greenfield `admin.sqlite` for the H06.10 schema** (backing up first and preserving `control_meta` + approved `admin_principals` in `/srv/epm/data/host/h0312-identity/admin.sqlite`).
2. **Promote `epm-pilot0-admin:h0610` and `dctech92130@gmail.com` in `/opt/epm/h0312/run_identity.py`** and restart `epm-h03-identity.service`:
   ```bash
   sudo systemctl restart epm-h03-identity.service
   sudo journalctl -u epm-h03-identity.service -n 10 --no-pager
   # Confirm: "private shared registration verified" and "shared routes active; email send route omitted"
   ```
3. **Verify live public GET headers** (note: `HEAD` / `-I` returns `403` by design because Caddy allows explicit `GET` only):
   ```bash
   curl -sS -D - -o /dev/null https://admin.epmdemo.xyz/
   curl -sS -D - -o /dev/null "https://login.epmdemo.xyz/auth/start?flow=operator"
   ```
4. **Live Bug Caught & Resolved During Gate 5:**
   - **Symptom:** Google sign-in popup rendered blank (first) and then closed without showing the TOTP prompt (`iframe.js:277` blocked from calling `https://www.googleapis.com/identitytoolkit/v3/relyingparty/getProjectConfig`).
   - **Root Cause:** `FirebaseHelpers.__call__` applied `API_SECURITY_HEADERS` (`Content-Security-Policy: default-src 'none'`) to `/__/auth/handler` and `/__/auth/iframe`.
   - **Fix:** Updated `application/apps/server/app/modules/hosted_access/infrastructure/firebase_helpers.py` to omit `Content-Security-Policy` on the two Firebase-owned HTML helpers while retaining `HSTS`, `Permissions-Policy`, `nosniff`, `no-referrer`, and `Cache-Control: no-store`, rebuilt `epm-pilot0-admin:h0610`, and re-deployed.
   - **Cold JWKS Note:** First cold `POST /auth/complete` took `5.007s` vs Caddy's `5.0s` upstream header timeout; once JWKS warmed in memory, subsequent Google + TOTP completions succeeded immediately.
5. **Interactive 4-Browser Verification Completed:**
   - **Context 1:** Google + TOTP MFA sign-in on `https://admin.epmdemo.xyz/` → Admin-lite dashboard loaded (`Free pilot (50.00 MB logical storage allowance)`, `Capacity observation unavailable`, empty `Qualified Operator release` fail-closed), then signed out and refreshed (`401` / sign-in screen).
   - **Context 2 (Incognito):** Verified `https://admin.epmdemo.xyz/` isolated from Context 1 and `https://login.epmdemo.xyz/auth/start?flow=operator` displayed `dctech92130@gmail.com`.
   - **Context 3 (Incognito):** Verified fresh Google + TOTP re-authentication after logout and clean sign-out revocation.
   - **Context 4 (Incognito):** Tested uninvited Google account (`uninvited.epm@gmail.com`) on `https://login.epmdemo.xyz/auth/start?flow=operator` → clean fail-closed denial (`"Sign-in could not be completed. Request a new link or start again from your workspace."`).
6. **Capture Server-Side Session Proof & Save Report:**
   - Inspected `admin_sessions` in `/srv/epm/data/host/h0312-identity/admin.sqlite` (`4` MFA-verified sessions, `2` explicit logout revocations) and saved [HOSTED_MVP_H06_10_DEPLOYED_BROWSER_IDENTITY.json](../qualification/reports/HOSTED_MVP_H06_10_DEPLOYED_BROWSER_IDENTITY.json).

---

## 7. Cleanup & VM Shutdown

1. Remove temporary staging directories (`/tmp/epm-h0610*`, `/tmp/epm-fix`, `/tmp/ops-agent-config.yaml`) on `epm-h02-host`.
2. **Stop `epm-h02-host` immediately after qualification** to prevent idle compute spend:
   ```bash
   gcloud compute instances stop "$INSTANCE" \
     --project="$PROJECT_ID" \
     --zone="$ZONE" \
     --format='value(name,status)'
   ```
3. Run local validation (`ruff check`, `ruff format --check`, focused `pytest`) on modified Python files and update [HOSTED_MVP_H06_10_EXIT_REVIEW.md](../qualification/reports/HOSTED_MVP_H06_10_EXIT_REVIEW.md) and [HOSTED_MVP_ACCEPTANCE.md](../qualification/HOSTED_MVP_ACCEPTANCE.md) to **GO**.

---

## 8. Production Pilot 0 Host Bring-Up (`epm-h02-host`)

To move `epm-h02-host` from qualification mode to live Pilot 0 readiness (with `epm-backup-proxy.service`, Admin recovery DB, Free v1 storage policy, qualified Operator release, and live host capacity):

1. **Upgrade `/opt/epm/host-agent` to the H06.10 wheel and install `boto3`:**
   - Package `host_agent` with `hosted_package.py --component host_agent`, install with `pip --python /opt/epm/host-agent/bin/python install --no-index --no-deps --force-reinstall`, clear stale `/opt/epm/host-agent/lib/{database,hosted-candidate.json}` before re-running `stage_schema_resources.py --component host_agent`, and install `boto3` into `/opt/epm/host-agent` (required by `R2ObjectStore` in `epm-backup-proxy.service`).

2. **Reinitialize empty greenfield `inventory.sqlite` for the H06.10 `host-inventory` schema:**
   - Back up `/srv/epm/data/host/inventory/inventory.sqlite` to `.h0211.bak`, run `initialize_store(HostedStore.HOST_INVENTORY, ...)` + `bind_host(conn, HostMetadata.model_validate_json(...))` preserving `/srv/epm/data/host/metadata.json` (`host_id=5a245678-b983-49d3-ab57-818b6c6bdc67`), and update `/etc/systemd/system/epm-h03-identity.service` to use `/opt/epm/host-agent/bin/python`.

3. **Provision and enable `epm-backup-proxy.service`:**
   - Create system user `epm-backup-proxy` (`uid=940`), fetch `/etc/epm/secrets/r2.json` (`0600`) from Secret Manager (`epm-h05-r2-credentials`) via `install_services.r2_credential("project-47b72bb7-ba90-42c9-910")`, write `/etc/epm/backup-proxy.json` (`0640 root:epm-backup-proxy`, `admin_uid=65532`, `socket=/run/epm-backup-proxy/backup-proxy.sock`, `operator-workspace-kek` + `admin-control-kek`), add `/run/epm-backup-proxy` (`0711`) to `/etc/tmpfiles.d/epm-host.conf`, install `/etc/systemd/system/epm-backup-proxy.service`, and run `systemctl enable --now epm-backup-proxy.service`.

4. **Initialize `admin-recovery.sqlite` and seed Pilot 0 metadata in `admin.sqlite`:**
   - Create `/srv/epm/data/host/{admin-recovery,admin-control,admin-scratch}` (`0700 65532:65532`) and run `initialize_store(HostedStore.ADMIN_RECOVERY, /ar/admin-recovery.sqlite)` inside `epm-pilot0-admin:h0610`.
   - Seed `admin.sqlite` inside `epm-pilot0-admin:h0610`:
     - `bootstrap_free_v1_policy` (`05038762-822b-5aa1-8906-99c94decabbc`, 50 MB logical, nightly backup, 14 retained points, keep warm).
     - `qualified_releases`: `00000000-0000-4000-8000-000000000610` (`epm-pilot0-operator:h0610`, `sha256:7b0e6791a60ddf3faac7d7633e992fcbcb0fd557021aaf001b2f144a7427864e`).
     - `capacity_profiles` (`pilot0-free-v1`, rev `1`) and `capacity_snapshots` (rev `1`, `complete=True`, 6 qualified slots on `e2-standard-2`).

5. **Wire Admin recovery, backup-proxy mounts & `v3` Admin-lite/H05 routes in `/opt/epm/h0312/run_identity.py`:**
   > **Operational Gotcha 1:** `verify_runtime_mounts` in `shared_identity_registration.py` only allowlists bind mounts under `/control`, `/run/epm-identity-relay`, and `/run/epm-central-identity`, and `/control` is mounted read-only. Create stub directories `admin-recovery`, `admin-control`, `admin-scratch`, and `backup-proxy` inside `/run/epm-h0312-identity/control` (`0700 65532:65532`), mount `/run/epm-backup-proxy` at `/control/backup-proxy`, and set `"backup_proxy_socket": "/control/backup-proxy/backup-proxy.sock"` in `admin.json`.
   > **Operational Gotcha 2:** `SharedIdentityManifest` defaults to `route_policy="separate_exact_host_method_allowlists_v1"` (auth routes only), causing Caddy to return `403` on `/api/admin/bootstrap` and `/api/admin/operators` (`Retry metadata` / `Capacity observation unavailable` in the UI). Pass `route_policy="separate_exact_host_method_allowlists_v3"` and `admin_routes=ADMIN_H05_ROUTES` to project all Admin-lite and H05 recovery API routes.
   - Restart `epm-h03-identity.service` and confirm all 6 services (`epm-backup-proxy`, `epm-h03-identity`, `epm-gateway`, `epm-tunnel`, `epm-host-guardian`, `google-cloud-ops-agent`) are `active`.


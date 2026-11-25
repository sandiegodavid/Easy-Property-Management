# Off-Host Backup, Restore, Maintenance Windows & Host-Loss Recovery

This guide covers the nightly backup schedulers, async protection summary relay, Operator workspace restore, Admin clean-runtime repair, whole-host control-loss reconstruction, and shared Pilot 0 maintenance windows.

---

## 1. Nightly Backup Schedulers & Async Protection Relay

### Schedulers (H06 D6)
- `WorkspaceBackupScheduler` (inside `operator_entry.py`) and `AdminControlBackupScheduler` (inside `shared_identity_entry.py`) run automatically inside each service's `asyncio` lifespan.
- **Cadence:** Hourly freshness/overdue watchdog tick (28-hour overdue threshold) + deterministic per-scope jittered 24-hour capture (`free-nightly-v1` / `admin-nightly-v1`).
- **Admin Outage Independence:** Operator nightly captures and hourly overdue alerts run locally inside each Operator container via `epm-backup-proxy.service` and never require Admin availability.
- **Inspect scheduler & alert logs:**
  ```bash
  sudo journalctl -u epm-h03-identity.service --grep="hosted_recovery" -n 50 --no-pager
  ```

### Pilot 0 Limitation & Future Enhancement: Automatic In-Container Operator Backups
- **Current Pilot 0 behavior:** `/opt/epm/pilot0/launch_operator.py` runs `epm-op-<slug>` containers as shared UID `65532:65532` and does **not** bind-mount `/run/epm-backup-proxy`. Meanwhile, `epm-backup-proxy.service` authenticates callers by `SO_PEERCRED` against per-operator `HOST_UID`s (`100001`, `100002`, …) in `/srv/epm/data/host/backup-proxy/inventory.sqlite`. As a result, once an operator workspace has uncommitted changes, the in-container `WorkspaceBackupScheduler` logs `backup_proxy_unavailable` and transitions `protection_state` to `overdue` (`Degraded` in Admin-lite) until a manual per-`HOST_UID` backup capture is run (see [pilot0-admission-and-incidents.md](pilot0-admission-and-incidents.md#step-3--launch-container-capture-initial-verified-backup--verify-ingress)).
- **Planned long-term enhancement (choose one when moving past manual Pilot 0 ops / H07):**
  1. **Per-operator `HOST_UID` containers (preferred for H07+ isolation):** Run each `epm-op-<slug>` container under its registered `HOST_UID:HOST_UID` (matching `inventory.sqlite` and `ext4` project quota ownership), bind-mount `/run/epm-backup-proxy` into the container, and grant a shared supplementary group (or per-operator socket directory ACLs) on `/run/epm-central-identity` and `/run/epm-operator-sockets/<operator_id>` so both the identity relay and `epm-backup-proxy` work natively from inside the container.
  2. **Host-side nightly systemd timer (low-change alternative):** Keep `epm-op-<slug>` on UID `65532` without mounting `/run/epm-backup-proxy` into the web container, and install a host `systemd` timer (e.g., `epm-operator-backup.timer`) that iterates `inventory.sqlite` nightly, runs the short-lived `--user <HOST_UID>:<HOST_UID>` backup container against `/run/epm-backup-proxy`, and lets the operator container's `UnixSummaryPublisher` relay the updated `recovery.sqlite` state to Admin.

### Async Protection Summary Relay (`POST /internal/recovery-status`, H06 D7)
- `shared_identity_entry.py` binds `<socket_directory>/recovery-status.sock` (`0600`) on startup and enforces `SO_PEERCRED` UID (`host_relay_uid`) + Ed25519 signature verification against `SourceRegistry` before upserting `workspace_recovery_status` in `admin.sqlite`.
- Each Operator deployment JSON sets:
  ```json
  {
    "recovery_status_socket": "/run/epm-identity-relay/recovery-status.sock",
    "alert_webhook_url": "https://<OPTIONAL_PUBLIC_HTTPS_WEBHOOK>",
    "maintenance_notice_path": "/run/epm/maintenance-notice.json"
  }
  ```
- `alert_webhook_url` is optional (non-HTTPS, redirecting, loopback, link-local, or private-IP URLs fail closed at startup); alerts always emit to structured JSON logs (`epm.hosted_recovery.alerts`) for Cloud Monitoring.
- If the relay or Admin is unreachable, `UnixSummaryPublisher` times out after `5s`, logs a warning, and never blocks or invalidates a workspace backup.

---

## 2. Day-2 Operator Workspace Restore & Minimal Recovery Mode

> **Hard Security Rule (H05 D1 / D10):** There is **no** Admin offline decrypt or customer workspace restore bypass. Workspace restores are strictly Operator-authorized with strong step-up authentication.

- **Normal Mode Restore:** Operator opens **Settings → Data and backup**, selects a verified point (latest by default), clicks **Preview restore**, completes fresh Google/email-link strong step-up (10-min step-up / 10-min preview / 5-min confirm TTLs), confirms rollback, signs in fresh after session revocation, inspects data, and clicks **Accept restored workspace**.
- **Corrupt Business DB (Minimal Recovery Mode):** The Operator container automatically boots into Minimal Recovery Mode (`503 recovery_mode_active` on business routes; never initializes an empty DB). The Operator signs in and completes the same Preview → Step-Up → Confirm → Fresh Sign-In → Accept flow.
- **Lost Browser Response:** Use **Check restore status** (`GET /api/hosted/recovery/operations/{operationId}`) to inspect the original restore phase before retrying.
- **Restored File Layout:** `ChunkedAeadBackupEngine.restore_point()` places databases at `<destination_dir>/<db.filename>` and retained attachments under `<destination_dir>/files/<relative_path>`, staging into a fresh `incarnation-N` (retaining `prior-N` for 7 days).

---

## 3. Admin Clean-Runtime Repair (`repair_runtime`)

When an Operator container fails healthchecks or needs a clean runtime rebuild:
1. Keep ingress **held/closed** (or recovery-mode only).
2. In Admin-lite → select Operator → **Runtime repair**, check the explicit confirmation box and click **Repair runtime** (`POST /api/admin/operators/{operatorId}/repair-runtime`).
3. Verify completion via **Check operation status** (`GET /api/admin/operations/{operationId}`).
4. **Invariants:** `repair_runtime` preserves the original `operator_id`, `workspace_id`, UID/GID, and private SQLite/files volumes, and **never** silently initializes an empty business database over a damaged store (if corrupt, the repaired container boots into Minimal Recovery Mode with `EPM_RECOVERY_MODE_REQUIRED=1`).

---

## 4. Whole-Host Control Loss Reconstruction CLI

On a clean replacement host with `epm-backup-proxy.service` connected to R2 + Cloud KMS and `/run/epm/admin-recovery-authority.json` mounted (4-hour RTO engineering objective):

```bash
cd application
PYTHONPATH=apps/server /opt/epm/host-agent/bin/python -B \
  -m app.modules.hosted_admin.infrastructure.admin_recovery \
  --admin-recovery-db /srv/epm/data/host/admin-recovery/admin-recovery.sqlite \
  --bootstrap-authority /run/epm/admin-recovery-authority.json \
  --control-root /srv/epm/data/host/admin-control \
  --scratch-root /srv/epm/data/host/admin-scratch \
  --backup-proxy-socket /run/epm-backup-proxy/backup-proxy.sock \
  --backup-proxy-uid 940 \
  --kms-key-ref projects/project-47b72bb7-ba90-42c9-910/locations/us-west1/keyRings/epm-h05-recovery/cryptoKeys/admin-control-kek
```

This reconstructs the control catalog from immutable R2 manifests, restores `admin.sqlite` + `host_inventory.sqlite` into a fresh `incarnation_id` (leaving prior in-flight operations inert and revoking prior sessions), and requires explicit reconciliation of host bindings before reopening ingress.

---

## 5. Announced Shared Maintenance Window & Cohort Release (H06 D5)

Pilot 0 uses a single shared cohort maintenance window (per-operator scheduling and canary automation are deferred to H10). Operator containers mount `/run/epm/maintenance-notice.json` **read-only** (`0644`, `root:root`, `<= 8 KiB`); always update it atomically (`tmp` + `os.replace`).

### Prerequisites
1. Build immutable Admin OCI image, Operator OCI image, and Host Agent archive from pinned source.
2. Pass all 9 `image_schema.json` cases and record exact `sha256:` manifest digests.
3. Verify forward-only schema compatibility across all 6 SQLite store families (no destructive downgrade).

### Phase 1 — Announce Window (`>= 24` Hours Before Start)
1. Publish `state: "announced"` atomically (`window_start_utc` and `window_end_utc` are integer UTC epoch-millisecond timestamps matching `MaintenanceNoticeDocument`):
   ```bash
   sudo python3 -c '
   import json, os, time
   now_ms = int(time.time() * 1000)
   doc = {
       "active": True,
       "state": "announced",
       "window_start_utc": now_ms + 86_400_000,
       "window_end_utc": now_ms + 88_200_000,
       "message": "Scheduled platform maintenance for all Pilot 0 workspaces (30 minutes).",
   }
   os.makedirs("/run/epm", exist_ok=True)
   tmp = "/run/epm/maintenance-notice.json.tmp"
   with open(tmp, "w", encoding="utf-8") as f:
       json.dump(doc, f, indent=2); f.write("\n")
   os.chmod(tmp, 0o644)
   os.replace(tmp, "/run/epm/maintenance-notice.json")
   '
   ```
2. Email all active Pilot 0 operators from `dctech92130@gmail.com` with the exact UTC/local start and end window.
3. Confirm the unobtrusive `HostedMaintenanceBanner` appears in the Operator shell header and Settings without blocking normal work.

### Phase 2 — Enter Maintenance, Drain & Capture Pre-Update Points
1. Atomically update `/run/epm/maintenance-notice.json` to `"state": "in_progress"` with `"message": "Updating your workspace. Unfinished drafts are preserved."` (Operator UI displays **`Updating your workspace`** while preserving unfinished local drafts).
2. Allow in-flight HTTP writes to complete cleanly.
3. Capture and verify fresh pre-update recovery points (`manifest_sha256` verified in R2) for `admin.sqlite` and every active Operator workspace before stopping any container.

### Phase 3 — Apply Pinned Release & Verify Readiness
1. Replace/restart Admin and Operator containers using exact pinned digests (`--no-floating-tags`).
2. Verify loopback health probes (`GET http://127.0.0.1:8081/health/live` and `/health/ready` → `200`) on Admin and every active Operator container.
3. Confirm `epm-gateway.service`, `epm-tunnel.service`, `epm-backup-proxy.service`, `epm-host-guardian.service`, `epm-h03-identity.service`, and `google-cloud-ops-agent.service` are `active`.
4. **Rollback Rule:**
   - **Before reopening ingress:** If any container fails readiness/schema validation, roll back to the previous pinned digest while retaining the pre-update verified recovery point.
   - **After reopening ingress:** **Never** perform destructive data rollback; preserve all post-reopen operator writes.

### Phase 4 — Clear Notice & Record Metrics
1. Atomically clear `/run/epm/maintenance-notice.json` (or remove the file cleanly):
   ```bash
   sudo python3 -c '
   import json, os
   doc = {"active": False, "state": "announced", "window_start_utc": None, "window_end_utc": None, "message": None}
   tmp = "/run/epm/maintenance-notice.json.tmp"
   with open(tmp, "w", encoding="utf-8") as f:
       json.dump(doc, f, indent=2); f.write("\n")
   os.chmod(tmp, 0o644)
   os.replace(tmp, "/run/epm/maintenance-notice.json")
   '
   ```
2. Verify Operator UI clears maintenance state, drafts remain intact, and a post-update read/write smoke check passes.
3. Log actual outage duration (seconds), pinned digests, and Admin minutes in [PILOT_0_COST_AND_OPS_WORKSHEET.md](../qualification/reports/PILOT_0_COST_AND_OPS_WORKSHEET.md).

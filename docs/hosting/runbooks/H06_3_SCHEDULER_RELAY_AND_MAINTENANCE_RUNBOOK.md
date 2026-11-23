# H06.3 Operations Runbook — Nightly Schedulers, Async Summary Relay & Shared Maintenance Notice

**Applies to:** HOSTED-001 Slice H06.3 (Operator & Admin runtime operations on `epm-h02-host`)  
**Checkpoint:** [HOSTED_MVP_H06_3_CHECKPOINT_2026-11-23.md](../qualification/reports/HOSTED_MVP_H06_3_CHECKPOINT_2026-11-23.md)  
**Related Runbooks:** [H06_2_HOST_SERVICES_OPERATIONS_RUNBOOK.md](H06_2_HOST_SERVICES_OPERATIONS_RUNBOOK.md) · [H05_RECOVERY_OPERATIONS_RUNBOOK.md](H05_RECOVERY_OPERATIONS_RUNBOOK.md)

---

## 1. Announce, Activate, and Clear a Shared Maintenance Window (D5)

Operator containers mount `/run/epm/maintenance-notice.json` **read-only** (`0644`, `root:root`, `<= 8 KiB`). Always update it atomically (`tmp` + `mv`) so containers never read a partial JSON file.

### 1.1 Announce an Upcoming Maintenance Window (`state: "announced"`)
```bash
sudo python3 -c '
import json, os, time
now_ms = int(time.time() * 1000)
doc = {
    "active": True,
    "window_start_utc": now_ms + 3600_000,
    "window_end_utc": now_ms + 5400_000,
    "message": "Scheduled Pilot 0 maintenance window (30 minutes). Please finish edits before start.",
    "state": "announced",
}
os.makedirs("/run/epm", exist_ok=True)
tmp = "/run/epm/maintenance-notice.json.tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2)
    f.write("\n")
os.chmod(tmp, 0o644)
os.replace(tmp, "/run/epm/maintenance-notice.json")
'
```

### 1.2 Switch to Active Maintenance (`state: "in_progress"`)
Update `"state": "in_progress"` and `"message": "Updating your workspace. Unfinished drafts are preserved."` using the same atomic write pattern right before draining/restarting containers.

### 1.3 Clear Maintenance Notice After Window Ends
```bash
sudo python3 -c '
import json, os
tmp = "/run/epm/maintenance-notice.json.tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump({"active": False}, f)
    f.write("\n")
os.chmod(tmp, 0o644)
os.replace(tmp, "/run/epm/maintenance-notice.json")
'
```

---

## 2. Configure Async Protection Summary Relay (`POST /internal/recovery-status`, D7)

1. `shared_identity_entry.py` automatically binds `<socket_directory>/recovery-status.sock` (`0600`) during startup and enforces `SO_PEERCRED` UID (`host_relay_uid`) + Ed25519 signature verification against `SourceRegistry` before upserting `workspace_recovery_status` in `admin.sqlite`.
2. In each Operator deployment JSON (`OperatorDeployment`), set:
   ```json
   {
     "recovery_status_socket": "/run/epm-identity-relay/recovery-status.sock",
     "alert_webhook_url": "https://<YOUR_PUBLIC_HTTPS_WEBHOOK_ENDPOINT>",
     "maintenance_notice_path": "/run/epm/maintenance-notice.json"
   }
   ```
   - `alert_webhook_url` is optional; when omitted, alerts still emit to structured JSON logs (`epm.hosted_recovery.alerts`) for Cloud Monitoring log-based alerts (H06.7).
   - Non-HTTPS, redirecting, loopback, link-local, or private-IP webhook URLs are rejected fail-closed at startup.
   - If the summary relay or Admin is unreachable, `UnixSummaryPublisher` times out after `5s`, logs a warning, and never blocks or invalidates a workspace backup.

---

## 3. Verify Nightly Backup Schedulers & Watchdog Health (D6)

Both `WorkspaceBackupScheduler` (inside `operator_entry.py`) and `AdminControlBackupScheduler` (inside `shared_identity_entry.py`) run automatically inside each service's `asyncio` lifespan:
- **Cadence:** Hourly freshness/overdue watchdog tick + deterministic per-scope jittered 24-hour capture (`free-nightly-v1` / `admin-nightly-v1`).
- **Admin outage independence:** Operator nightly captures and hourly overdue alerts run locally inside each Operator container using `epm-backup-proxy.service` and never require Admin availability.
- **Inspect scheduler & alert logs:**
  ```bash
  sudo journalctl -u epm-h03-identity.service --grep="hosted_recovery" -n 50 --no-pager
  ```
